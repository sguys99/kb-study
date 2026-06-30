"""4.4 token_budget.py — 재순위 점수가 높은 순으로, 토큰 예산 안에 컨텍스트를 담는다.

LLM 컨텍스트 창은 유한하다. 좋은 후보가 100개라도 다 못 넣는다. 그래서:
  1) 토큰을 센다(tiktoken 우선, 없으면 char/4 근사).
  2) 예산(budget)을 정한다(예: 512 / 1024 토큰).
  3) 재순위 점수가 높은 후보부터 그리디로 담는다. 다음 후보를 넣으면 예산을 넘으면 멈춘다.
  4) 가드 두 개를 건다.
       - 중복 제거: 본문이 거의 같은 후보는 한 번만(첫 50자 정규화 키로 근사).
       - 다양성: 한 출처(vector/graph)가 자리를 다 차지하지 못하게 상한을 둔다.
  5) 인용 메타(id·source·span)를 보존해 답변에 출처를 붙일 수 있게 한다.

이 모듈은 외부 의존이 없다(tiktoken 은 선택). 없으면 char/4 근사로 자동 폴백.

전제: 없음(키 불필요, 과금 0).
실행:
    python token_budget.py             # 예산 512 토큰으로 패킹
    python token_budget.py 1024        # 예산 1024 토큰으로 패킹
"""

from __future__ import annotations

import re
import sys

from candidates import Candidate, load_pool
from fuse import fuse_rrf
from rerank import rerank


def count_tokens(text: str) -> int:
    """토큰 수를 센다. tiktoken(cl100k_base)이 있으면 정확히, 없으면 char/4 근사.

    정확 카운트가 꼭 필요하면 Anthropic 의 client.messages.count_tokens 로 바꿀 수 있다.
    실습은 외부 의존을 줄이려 근사를 기본으로 둔다.
    """
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:
        # 영문 기준 1토큰 ≈ 4자. 한국어는 더 촘촘하지만 데모 근사로 충분하다.
        return max(1, len(text) // 4)


def _dedup_key(text: str) -> str:
    """근중복 판별 키 — 공백·기호를 죽이고 앞 50자만 본다."""
    norm = re.sub(r"\s+", " ", text.lower()).strip()
    return norm[:50]


def pack(reranked: list[tuple[Candidate, float]], budget_tokens: int,
         per_source_cap: int = 3) -> tuple[list[dict], int]:
    """재순위 상위부터 그리디로 담는다. 중복·다양성 가드 + 예산 절단.

    돌려주는 각 항목은 인용 가능한 dict — id·source·score·tokens·citation·text.
    """
    packed: list[dict] = []
    used = 0
    seen_keys: set[str] = set()
    source_count: dict[str, int] = {}

    for c, score in reranked:
        key = _dedup_key(c.text)
        if key in seen_keys:                      # 중복 가드 — 거의 같은 본문은 건너뛴다
            continue
        if source_count.get(c.source, 0) >= per_source_cap:  # 다양성 가드
            continue

        t = count_tokens(c.text)
        if used + t > budget_tokens:              # 예산 절단 — 넘으면 이 후보는 버리고 다음을 시도
            continue

        span = c.metadata.get("span") or c.metadata.get("source_kind") or c.metadata.get("doc", "")
        packed.append({
            "id": c.id,
            "source": c.source,
            "score": round(score, 4),
            "tokens": t,
            "citation": f"[{c.id}·{c.source}{(':' + str(span)) if span else ''}]",
            "text": c.text,
        })
        used += t
        seen_keys.add(key)
        source_count[c.source] = source_count.get(c.source, 0) + 1

    return packed, used


def render_context(packed: list[dict]) -> str:
    """패킹 결과를 LLM 프롬프트에 그대로 끼울 근거 블록 문자열로 만든다."""
    lines = []
    for p in packed:
        lines.append(f"{p['citation']} {p['text']}")
    return "\n".join(lines)


def main(argv: list[str]) -> None:
    budget = int(argv[1]) if len(argv) > 1 and argv[1].isdigit() else 512

    question, pool = load_pool()
    fused = fuse_rrf(pool)
    cands = [c for c, _ in fused]
    scores = [s for _, s in fused]
    reranked = rerank(question, cands, scores, top_k=len(cands))

    packed, used = pack(reranked, budget_tokens=budget)

    print(f"[질문] {question}")
    print(f"[예산] {budget} 토큰  →  담긴 후보 {len(packed)}개, 사용 {used} 토큰\n")
    print("[패킹된 컨텍스트]")
    for p in packed:
        print(f"  {p['citation']:>22} score={p['score']:.4f} tok={p['tokens']:>3}  "
              f"{p['text'][:46]}…")
    print("\n[렌더된 근거 블록 미리보기]")
    print(render_context(packed)[:400] + " …")


if __name__ == "__main__":
    main(sys.argv)
