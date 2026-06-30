"""hybrid_search.py — Vector + BM25 를 RRF 로 융합. 06 Baseline 의 검색기.

왜 융합인가: Dense(의미)와 Sparse(정확 키워드)는 잡는 게 다르다. 서로의 빈틈을
메우려면 두 순위를 합쳐야 한다. 점수 스케일이 다른 둘을 직접 더하면(코사인 0~1 vs
BM25 0~수십) 한쪽이 압도한다. 그래서 점수가 아니라 '순위'를 합치는 RRF 를 쓴다.

Reciprocal Rank Fusion(RRF):
    score(d) = Σ_r  1 / (k + rank_r(d))
  - rank 는 각 검색기에서의 1-base 순위.
  - k 는 평활 상수(관례값 60). 클수록 상위·하위 순위 차이가 완만해진다.
  - 한 검색기에만 잡혀도 점수를 받는다 → 둘 중 하나라도 잘 잡으면 살아남는다.
  단순하고 스케일 보정이 필요 없어 기준선에 딱 맞다.

태그 필터(선택): index.json 의 by_tag 로 후보 chunk_id 집합을 먼저 좁힐 수 있다
  (예: 'rag 태그 청크 안에서만 검색'). 정책·도메인 한정 검색의 출발점이다.

전제: 네트워크·API 키는 vector_index 백엔드에 따른다(폴백이면 0).
"""

from __future__ import annotations

from load_chunks import Chunk, MetaIndex
from bm25_index import BM25Index
from vector_index import VectorIndex

RRF_K = 60  # RRF 평활 상수. 정보검색에서 널리 쓰는 관례값.


def _rrf_merge(
    ranked_lists: list[list[tuple[str, float]]],
    *,
    k: int = RRF_K,
    allow: set[str] | None = None,
) -> list[tuple[str, float]]:
    """여러 (chunk_id, score) 순위 목록을 RRF 로 합쳐 (chunk_id, rrf_score) 로 돌려준다.

    각 목록의 '순위'만 쓴다(원 점수는 융합에 안 쓴다). allow 가 주어지면 그 집합만 남긴다.
    """
    fused: dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, (cid, _score) in enumerate(ranked, start=1):
            if allow is not None and cid not in allow:
                continue
            fused[cid] = fused.get(cid, 0.0) + 1.0 / (k + rank)
    return sorted(fused.items(), key=lambda x: x[1], reverse=True)


class HybridSearcher:
    """Vector + BM25 를 들고 RRF 로 융합 검색하는 기준선 검색기."""

    def __init__(self, chunks: list[Chunk], index: MetaIndex | None = None) -> None:
        self.chunks = chunks
        self.cmap: dict[str, Chunk] = {c.chunk_id: c for c in chunks}
        self.index = index
        self.bm25 = BM25Index(chunks)
        self.vector = VectorIndex(chunks)
        self.embed_backend = self.vector.backend

    def search(
        self,
        query: str,
        k: int = 5,
        *,
        pool: int = 20,
        tag: str | None = None,
    ) -> list[tuple[str, float]]:
        """RRF 융합 상위 k개 (chunk_id, rrf_score).

        pool: 각 검색기에서 가져와 융합할 후보 수(k 보다 넉넉히).
        tag : 주어지면 index.by_tag 의 해당 청크로만 후보를 제한한다.
        """
        allow: set[str] | None = None
        if tag is not None:
            if self.index is None:
                raise ValueError("tag 필터를 쓰려면 MetaIndex 를 넘겨야 한다.")
            allow = set(self.index.chunk_ids_for_tag(tag))
            if not allow:
                return []  # 해당 태그 청크가 없으면 빈 결과.

        dense = self.vector.search(query, k=pool)
        sparse = self.bm25.search(query, k=pool)
        fused = _rrf_merge([dense, sparse], allow=allow)
        return fused[:k]

    def context_chunks(self, query: str, k: int = 5, *, tag: str | None = None) -> list[Chunk]:
        """검색 결과를 Chunk 객체 리스트로(인용 답변 컨텍스트용)."""
        return [self.cmap[cid] for cid, _ in self.search(query, k=k, tag=tag)]


if __name__ == "__main__":
    # 빠른 자기점검: dense·sparse·hybrid 를 같은 질의로 비교한다.
    from load_chunks import load_chunks, load_index

    chunks = load_chunks()
    index = load_index()
    hs = HybridSearcher(chunks, index)
    cmap = hs.cmap
    q = "CRAG 와 Self-RAG 의 차이"
    print(f"[hybrid] backend={hs.embed_backend}  query={q!r}\n")
    print("  dense  :", [cid for cid, _ in hs.vector.search(q, k=3)])
    print("  sparse :", [cid for cid, _ in hs.bm25.search(q, k=3)])
    print("  hybrid :")
    for cid, score in hs.search(q, k=5):
        print(f"    {score:.5f}  {cid:22s}  {cmap[cid].quote[:40]!r}")
