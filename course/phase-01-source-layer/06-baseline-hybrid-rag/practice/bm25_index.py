"""bm25_index.py — BM25(Sparse) 색인·검색. 정확 키워드·약어·고유명사에 강하다.

Dense(임베딩)는 의미는 잘 잡지만 'RRF', 'CRAG', 'voyage-3.5' 같은 정확한 토큰을
놓칠 수 있다. BM25 는 단어 빈도·문서 길이로 점수를 매겨 그 빈틈을 메운다.
그래서 06 Baseline 은 둘을 합친다(hybrid_search.py 의 RRF).

의존: rank-bm25(가벼운 순수 파이썬 BM25 구현).
토크나이저: 추가 무거운 의존 없이, 한국어+영문 혼합을 의식한 단순 정규식.
  - 영문/숫자/하이픈/점이 섞인 토큰(voyage-3.5, GraphRAG, BM25)은 통째로 보존한다.
  - 한글·CJK 는 글자 단위로 끊는다(형태소 분석기 없이도 부분 매칭이 되게 — 거친 근사).
  05 estimate_tokens 의 'CJK 글자 + 영문 단어' 톤과 같은 결을 유지한다.

전제: 네트워크·API 키 불필요. 순수 로컬.
"""

from __future__ import annotations

import re

from rank_bm25 import BM25Okapi

from load_chunks import Chunk

# 영문/숫자 + 내부 하이픈·점·언더스코어. voyage-3.5, GraphRAG, self-rag, bge_m3 를 한 토큰으로.
_ALNUM_RE = re.compile(r"[A-Za-z0-9]+(?:[._-][A-Za-z0-9]+)*")
# CJK(한글·한자·가나) 글자 1개.
_CJK_RE = re.compile(r"[　-〿぀-ヿ㐀-䶿一-鿿가-힣]")


def tokenize(text: str) -> list[str]:
    """한국어+영문 혼합 토크나이저.

    영문/약어/모델명은 소문자화해 통째로, 한글·CJK 는 글자 단위로 끊는다.
    형태소 분석기를 안 쓰는 대신 글자 단위로 거칠게 부분 매칭을 노린다(기준선엔 충분).
    """
    tokens: list[str] = []
    for m in _ALNUM_RE.finditer(text):
        tokens.append(m.group().lower())
    tokens.extend(_CJK_RE.findall(text))
    return tokens


class BM25Index:
    """청크 본문에 대한 BM25 색인. id 목록과 점수를 함께 돌려준다."""

    def __init__(self, chunks: list[Chunk]) -> None:
        self.chunk_ids: list[str] = [c.chunk_id for c in chunks]
        corpus = [tokenize(c.text) for c in chunks]
        # rank-bm25 는 빈 문서를 싫어한다. 빈 토큰 문서는 더미 토큰으로 채워 색인 깨짐을 막는다.
        corpus = [toks if toks else ["∅"] for toks in corpus]
        self.bm25 = BM25Okapi(corpus)

    def search(self, query: str, k: int = 10) -> list[tuple[str, float]]:
        """질의로 상위 k개 (chunk_id, score) 를 점수 내림차순으로 돌려준다."""
        q_tokens = tokenize(query)
        if not q_tokens:
            return []
        scores = self.bm25.get_scores(q_tokens)
        ranked = sorted(
            zip(self.chunk_ids, scores), key=lambda x: x[1], reverse=True
        )
        # 점수 0 이하(질의 토큰이 한 번도 안 나온 청크)는 의미 없으니 떨군다.
        return [(cid, float(s)) for cid, s in ranked[:k] if s > 0.0]


if __name__ == "__main__":
    # 빠른 자기점검: 05 청크로 색인하고 'RRF 약어성 질의' 한 번 던져 본다.
    from load_chunks import load_chunks

    chunks = load_chunks()
    idx = BM25Index(chunks)
    cmap = {c.chunk_id: c for c in chunks}
    q = "GraphRAG 커뮤니티 요약"
    print(f"[bm25] query={q!r}")
    for cid, score in idx.search(q, k=5):
        print(f"  {score:6.3f}  {cid:22s}  {cmap[cid].quote[:40]!r}")
