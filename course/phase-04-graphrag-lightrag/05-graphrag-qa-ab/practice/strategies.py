"""4.5 strategies.py — 같은 후보 풀 위에 네 검색 전략을 세운다.

Phase 4 의 결산이다. 앞 토픽이 만든 검색기들을 '전략'으로 추상화해 같은 골든 질문에
나란히 세운다. 누가 어디서 이기는지 보려면 먼저 모두 같은 시그니처로 맞춰야 한다.

    retrieve(question, pool) -> ranked list[Candidate]

네 전략:
  - Vector  : Phase 1/06 Hybrid(Vector+BM25)의 의미 근접 청크. source=="vector" 후보만 점수순.
              Phase 1 기준선이자 이 A/B 의 비교 원점이다.
  - Local   : 4.2 Local·Path 그래프 근거. graph 후보 중 metadata.source_kind 가 local/path 인 것만.
  - Global  : 4.3 Leiden Community 요약. graph 후보 중 source_kind 가 community 인 것만.
  - Hybrid  : 4.4 Vector+Graph Fusion. fusion_pipeline.run 으로 RRF 융합 → 재순위 → 토큰 패킹.

Hybrid 는 04 의 fusion_pipeline 을 그대로 import 해 호출한다. 04 가 키 없이도 끝까지 도는
설계라(reranker identity 폴백, tiktoken 없으면 char/4 근사), 05 도 과금 0 경로가 기본이다.
상용 경로(VOYAGE_API_KEY + voyageai)는 선택이고, 키 하드코딩은 하지 않는다.

전제: 없음(키 불필요, 과금 0). Hybrid 의 상용 reranker 만 선택적으로 VOYAGE_API_KEY 사용.
실행:
    python strategies.py            # 1번 질문에 네 전략을 세워 순위를 비교 출력
    python strategies.py q5         # 특정 qid 로 비교
"""

from __future__ import annotations

import sys
from pathlib import Path

# 04 의 practice 모듈을 import 경로에 추가한다(candidates/fuse/rerank/token_budget/fusion_pipeline).
# 같은 코드를 05 에서 다시 만들지 않는다 — 04 산출물을 그대로 입력으로 받는다.
_FUSION_DIR = (Path(__file__).resolve().parent.parent.parent
               / "04-vector-graph-fusion" / "practice")
if str(_FUSION_DIR) not in sys.path:
    sys.path.insert(0, str(_FUSION_DIR))

from candidates import Candidate  # noqa: E402  (sys.path 주입 후 import)
import fusion_pipeline  # noqa: E402

from goldenset import load_pool_for  # noqa: E402  (05 의 골든셋 로더)

# graph 후보의 source_kind 분류. Local 전략은 local/path, Global 전략은 community 만 본다.
LOCAL_KINDS = {"local", "path"}
GLOBAL_KINDS = {"community"}


def vector_only(question: str, pool: list[Candidate]) -> list[Candidate]:
    """Vector 전략 — source=="vector" 후보만 원점수 내림차순.

    Phase 1/06 Hybrid 검색기의 의미 근접 청크에 해당한다. 이 A/B 의 기준선(Baseline).
    """
    cands = [c for c in pool if c.source == "vector"]
    return sorted(cands, key=lambda c: c.score, reverse=True)


def local(question: str, pool: list[Candidate]) -> list[Candidate]:
    """Local 전략 — graph 후보 중 local/path(1홉 이웃 + 멀티홉 경로)만 점수순.

    4.2 Local·Path 검색기에 해당한다. 멀티홉 관계를 잇는 데 강하다.
    """
    cands = [c for c in pool
             if c.source == "graph" and c.metadata.get("source_kind") in LOCAL_KINDS]
    return sorted(cands, key=lambda c: c.score, reverse=True)


def global_(question: str, pool: list[Candidate]) -> list[Candidate]:
    """Global 전략 — graph 후보 중 community 요약만 점수순.

    4.3 Leiden Community 요약에 해당한다. 전체 조망(global-summary)에 강하다.
    이름이 파이썬 예약어 global 과 겹치지 않게 끝에 밑줄을 붙였다(roadmap 표기는 Global).
    """
    cands = [c for c in pool
             if c.source == "graph" and c.metadata.get("source_kind") in GLOBAL_KINDS]
    return sorted(cands, key=lambda c: c.score, reverse=True)


def hybrid(question: str, pool: list[Candidate],
           budget_tokens: int = 1024, backend: str | None = None) -> list[Candidate]:
    """Hybrid 전략 — 4.4 fusion_pipeline.run 으로 융합·재순위·패킹.

    Vector·Graph 를 RRF 로 한 순위에 합치고, cross-encoder 로 재순위한 뒤,
    토큰 예산 안에 다양성·중복 가드를 걸어 패킹한다. 패킹에 담긴 후보의 id 순서를
    최종 랭킹으로 본다. fusion_pipeline 결과의 'reranked'(전체 재순위 순서)도 함께 쓰면
    패킹에서 잘린 후보까지 줄을 세울 수 있어, recall@k 비교가 공정해진다.
    """
    result = fusion_pipeline.run(question, pool, budget_tokens=budget_tokens, backend=backend)

    by_id = {c.id: c for c in pool}
    ranked: list[Candidate] = []
    seen: set[str] = set()

    # 1순위: 토큰 예산 안에 실제로 패킹된 후보(LLM 에 들어갈 근거).
    for p in result["packed"]:
        if p["id"] not in seen and p["id"] in by_id:
            ranked.append(by_id[p["id"]])
            seen.add(p["id"])
    # 2순위: 패킹에서 잘렸지만 재순위 상위였던 후보 — top-k 비교를 위해 뒤에 잇는다.
    for cid, _src, _s in result["reranked"]:
        if cid not in seen and cid in by_id:
            ranked.append(by_id[cid])
            seen.add(cid)
    return ranked


# 전략 레지스트리 — roadmap 표기(Vector/Local/Global/Hybrid)를 키로 쓴다.
STRATEGIES = {
    "Vector": vector_only,
    "Local": local,
    "Global": global_,
    "Hybrid": hybrid,
}


def _print_ranking(name: str, ranked: list[Candidate], gold: set[str]) -> None:
    print(f"[{name}] 상위 {min(len(ranked), 5)}개:")
    if not ranked:
        print("  (후보 없음)")
        return
    for i, c in enumerate(ranked[:5], 1):
        mark = "★" if c.id in gold else " "
        kind = c.metadata.get("source_kind", c.source)
        print(f"  {mark}{i:>2}. {c.id} [{kind:>9}] score={c.score:>5.2f}  {c.short(44)}")


def main(argv: list[str]) -> None:
    qid = argv[1] if len(argv) > 1 else None
    question, pool, gold = load_pool_for(qid)

    print(f"[질문 {qid or '(첫 질문)'}] {question}")
    print(f"[gold 근거] {sorted(gold)}\n")

    for name, fn in STRATEGIES.items():
        _print_ranking(name, fn(question, pool), gold)
        print()

    print("[해석] ★ 가 gold 근거다. 어느 전략이 ★ 를 위로 끌어올렸는지 본다.")
    print("[다음] python ab_runner.py 로 전체 골든셋 × 네 전략 리더보드를 낸다.")


if __name__ == "__main__":
    main(sys.argv)
