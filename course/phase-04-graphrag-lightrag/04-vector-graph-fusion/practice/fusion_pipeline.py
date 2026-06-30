"""4.4 fusion_pipeline.py — candidates → fuse → rerank → pack 엔드투엔드.

이 토픽의 산출물이다. 앞 토픽의 검색기 출력(Vector·Graph 후보)을 받아
하나의 융합 검색기처럼 동작한다. 4.5(A/B)와 Phase 7 에이전트 도구가 이 진입점을 import 한다.

흐름:
    load_pool()           # Vector·Graph 후보를 공통 스키마로 로드 (candidates.py)
      → fuse_rrf()        # 스케일 다른 점수를 RRF 로 한 순위로 융합 (fuse.py)
      → rerank()          # 질문-문서 쌍으로 cross-encoder 재순위 (rerank.py)
      → pack()            # 토큰 예산 안에 인용 가능하게 패킹 (token_budget.py)

키가 없어도 끝까지 동작한다 — reranker 는 identity 폴백, 토큰은 char/4 근사.

전제: 기본 키 불필요(과금 0). 상용 reranker 만 VOYAGE_API_KEY 사용. 키 하드코딩 금지.
실행:
    python fusion_pipeline.py                 # 기본 예산 1024 토큰으로 엔드투엔드
    python fusion_pipeline.py --budget 512    # 예산 지정
    python fusion_pipeline.py --backend local # reranker 백엔드 지정
"""

from __future__ import annotations

import sys

from candidates import Candidate, load_pool
from fuse import fuse_rrf
from rerank import active_backend, rerank
from token_budget import pack, render_context


def run(question: str, pool: list[Candidate], budget_tokens: int = 1024,
        backend: str | None = None) -> dict:
    """융합 검색기 본체. 패킹된 컨텍스트 + 인용 메타 + 단계별 스냅샷을 돌려준다."""
    fused = fuse_rrf(pool)
    cands = [c for c, _ in fused]
    scores = [s for _, s in fused]

    reranked = rerank(question, cands, scores, top_k=len(cands), backend=backend)
    packed, used = pack(reranked, budget_tokens=budget_tokens)

    return {
        "question": question,
        "backend": active_backend(backend),
        "fused": [(c.id, c.source, round(s, 4)) for c, s in fused],
        "reranked": [(c.id, c.source, round(s, 4)) for c, s in reranked],
        "packed": packed,
        "used_tokens": used,
        "budget_tokens": budget_tokens,
        "context": render_context(packed),
    }


def _arg(argv: list[str], flag: str, default: str | None = None) -> str | None:
    return argv[argv.index(flag) + 1] if flag in argv else default


def main(argv: list[str]) -> None:
    budget = int(_arg(argv, "--budget", "1024"))
    backend = _arg(argv, "--backend")

    question, pool = load_pool()
    result = run(question, pool, budget_tokens=budget, backend=backend)

    print(f"[질문] {result['question']}")
    print(f"[reranker 백엔드] {result['backend']}\n")

    print("[1) RRF 융합 순위]")
    for i, (cid, src, s) in enumerate(result["fused"], 1):
        print(f"  {i:>2}. {cid} [{src:>6}] {s:.4f}")

    print("\n[2) 재순위 순위]")
    for i, (cid, src, s) in enumerate(result["reranked"], 1):
        print(f"  {i:>2}. {cid} [{src:>6}] {s:.4f}")

    print(f"\n[3) 패킹 — 예산 {result['budget_tokens']} 토큰, "
          f"사용 {result['used_tokens']} 토큰, 후보 {len(result['packed'])}개]")
    for p in result["packed"]:
        print(f"  {p['citation']:>22} tok={p['tokens']:>3}  {p['text'][:44]}…")

    print("\n[4) LLM 에 줄 근거 블록]")
    print(result["context"])


if __name__ == "__main__":
    main(sys.argv)
