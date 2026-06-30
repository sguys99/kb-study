"""4.4 rerank.py — 융합된 후보를 질문-문서 쌍으로 다시 점수 매긴다(재순위화).

왜 또 점수를 매기나? fuse.py 의 RRF 는 '각 후보가 자기 출처 안에서 몇 등이었나'만 본다.
질문과 후보 본문을 같이 보지 않는다. 재순위화(Rerank)는 다르다. cross-encoder 가
(질문, 후보) 한 쌍을 통째로 모델에 넣어 '이 후보가 이 질문에 얼마나 답이 되나'를 직접 점수한다.

  - bi-encoder(임베딩): 질문과 문서를 따로 벡터로 만든 뒤 코사인. 빠르지만 둘의 상호작용을 못 본다.
  - cross-encoder(reranker): 질문+문서를 함께 입력해 상호작용을 본다. 느리지만 정확하다.
    그래서 1차로 넓게 뽑고(fuse), 상위 N개만 cross-encoder 로 정밀 재순위하는 2단 구조가 표준.

백엔드 분기(키 없어도 끝까지 동작):
  1) VoyageAI  — VOYAGE_API_KEY + voyageai 패키지가 있으면 rerank-2.5 호출(상용).
  2) 로컬      — sentence-transformers + BAAI/bge-reranker-v2-m3 (키 불필요, 비용 0).
  3) identity  — 둘 다 없으면 융합 점수를 그대로 재순위 점수로 쓰는 폴백(데모용).
                 파이프라인 모양은 같고, 점수 품질만 떨어진다.

전제: 기본은 키 불필요(identity 폴백). 상용 경로만 VOYAGE_API_KEY 필요. 키 하드코딩 금지.
실행:
    python rerank.py                 # 자동 분기(키 있으면 Voyage, 없으면 로컬, 둘 다 없으면 identity)
    python rerank.py --backend local # 로컬 reranker 강제
"""

from __future__ import annotations

import os
import sys

from candidates import Candidate, load_pool
from fuse import fuse_rrf

# VoyageAI 재순위 모델 — 2025-08 출시 기본 모델. 경량은 rerank-2.5-lite, 구버전 rerank-2 도 유효.
VOYAGE_RERANK_MODEL = "rerank-2.5"
# 로컬 무료 reranker — cross-encoder. 키 불필요.
LOCAL_RERANK_MODEL = "BAAI/bge-reranker-v2-m3"


def active_backend(explicit: str | None = None) -> str:
    """쓸 reranker 백엔드를 고른다. explicit 가 있으면 그걸 우선한다."""
    if explicit:
        return explicit
    if os.environ.get("VOYAGE_API_KEY"):
        try:
            import voyageai  # noqa: F401  설치 확인용
            return "voyage"
        except ImportError:
            pass
    try:
        import sentence_transformers  # noqa: F401  설치 확인용
        return "local"
    except ImportError:
        return "identity"


def _rerank_voyage(question: str, docs: list[str], top_k: int) -> list[tuple[int, float]]:
    """VoyageAI rerank-2.5 호출. (원본 인덱스, 관련도 점수) 리스트를 점수순으로 돌려준다."""
    import voyageai

    vo = voyageai.Client()  # VOYAGE_API_KEY 를 환경변수에서 읽는다. 키 하드코딩 금지.
    res = vo.rerank(query=question, documents=docs, model=VOYAGE_RERANK_MODEL, top_k=top_k)
    # SDK 결과: results[i].index(원본 위치), .relevance_score
    return [(r.index, float(r.relevance_score)) for r in res.results]


def _rerank_local(question: str, docs: list[str], top_k: int) -> list[tuple[int, float]]:
    """로컬 cross-encoder(bge-reranker-v2-m3). 키 불필요, 비용 0."""
    from sentence_transformers import CrossEncoder

    model = CrossEncoder(LOCAL_RERANK_MODEL)
    scores = model.predict([(question, d) for d in docs])  # 각 쌍의 관련도 점수
    ranked = sorted(enumerate(scores), key=lambda t: t[1], reverse=True)[:top_k]
    return [(i, float(s)) for i, s in ranked]


def _rerank_identity(fused_scores: list[float], top_k: int) -> list[tuple[int, float]]:
    """폴백 — 융합 점수를 그대로 재순위 점수로 쓴다(모델 호출 없음)."""
    ranked = sorted(enumerate(fused_scores), key=lambda t: t[1], reverse=True)[:top_k]
    return [(i, float(s)) for i, s in ranked]


def rerank(question: str, candidates: list[Candidate], fused_scores: list[float],
           top_k: int = 10, backend: str | None = None) -> list[tuple[Candidate, float]]:
    """융합 후보를 재순위해 (후보, 재순위 점수) 리스트를 점수순으로 돌려준다.

    candidates 와 fused_scores 는 같은 순서로 정렬돼 들어온다고 가정한다(fuse 결과 그대로).
    """
    be = active_backend(backend)
    docs = [c.text for c in candidates]

    if be == "voyage":
        idx_score = _rerank_voyage(question, docs, top_k)
    elif be == "local":
        idx_score = _rerank_local(question, docs, top_k)
    else:
        idx_score = _rerank_identity(fused_scores, top_k)

    return [(candidates[i], s) for i, s in idx_score]


def main(argv: list[str]) -> None:
    backend = None
    if "--backend" in argv:
        backend = argv[argv.index("--backend") + 1]

    question, pool = load_pool()
    fused = fuse_rrf(pool)
    cands = [c for c, _ in fused]
    scores = [s for _, s in fused]

    be = active_backend(backend)
    print(f"[reranker 백엔드] {be}"
          + ("  (VOYAGE_API_KEY 미설정/패키지 없음 → 폴백)" if be == "identity" else ""))
    print(f"[질문] {question}\n")

    reranked = rerank(question, cands, scores, top_k=len(cands), backend=backend)
    print("[재순위 결과] 질문-문서 쌍 점수순:")
    for i, (c, s) in enumerate(reranked, 1):
        print(f"  {i:>2}. {c.id} [{c.source:>6}] rerank={s:.4f}  {c.short(46)}")
    print("\n[다음] python token_budget.py 로 재순위 상위부터 토큰 예산 안에 담는다.")


if __name__ == "__main__":
    main(sys.argv)
