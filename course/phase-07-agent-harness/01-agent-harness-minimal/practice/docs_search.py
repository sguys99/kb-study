"""docs_search.py — Phase 1 Baseline Hybrid RAG 검색기를 '도구 본체'로 감싼다.

이 토픽의 핵심 규약: 도구는 (입력 query) → (인용 가능한 문서 청크 리스트) 를 돌려준다.
각 결과에는 chunk_id · score · source_id · text 가 붙어 '어디서 나왔는지' 추적된다.

두 경로:
  1) 실전 경로 — Phase 1/06 의 HybridSearcher(Vector+BM25 RRF)를 그대로 쓴다.
     그쪽 practice 를 import 할 수 있으면 자동으로 그 검색기를 붙인다.
  2) 독립 경로(기본) — 이 파일 안의 작은 mock 코퍼스 + 순수 BM25 로 동작한다.
     상용 API·임베딩·외부 인덱스가 전혀 필요 없다. Phase 7 을 단독으로 돌릴 수 있게 하려는 것.

즉 이 파일은 '검색기가 무엇이든, 도구가 뱉는 계약은 같다'를 보여준다.
Phase 7 의 에이전트는 검색기 내부를 모른다. Retrieval 결과의 '모양'만 안다.

전제: 표준 라이브러리만으로 동작(기본 경로). API 키 불필요.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass


@dataclass
class Doc:
    """검색 대상 문서 청크. Phase 1/04 의 프로비넌스 필드를 축약해 운반한다."""

    chunk_id: str
    source_id: str
    text: str


# 독립 실행용 mock 코퍼스. Part 2 러닝 코퍼스(RAG/GraphRAG 기술 문서)의 축소판이다.
# 멀티홉 질문("CRAG 와 Self-RAG 는 무엇이 다른가")이 성립하도록 서로 연결된 조각을 넣었다.
_MOCK_CORPUS: list[Doc] = [
    Doc(
        "doc-self-rag-01",
        "src-self-rag",
        "Self-RAG 는 생성 도중 특수 reflection 토큰을 뱉어, 검색이 필요한지와 "
        "검색된 문단이 답에 유용한지를 모델 스스로 평가한다. 검색을 항상 하지 않고 "
        "필요할 때만 부르는 적응형(adaptive) 접근이다.",
    ),
    Doc(
        "doc-crag-01",
        "src-crag",
        "CRAG(Corrective RAG)는 검색 품질을 평가하는 경량 retrieval evaluator 를 둔다. "
        "검색 결과가 부실하면 웹 검색으로 보강하거나 질의를 교정한다. 검색 자체의 신뢰도를 "
        "고쳐 쓰는 교정형(corrective) 접근이다.",
    ),
    Doc(
        "doc-adaptive-rag-01",
        "src-adaptive-rag",
        "Adaptive-RAG 는 질문의 난이도를 먼저 분류해, 단순 질문은 검색 없이 답하고 "
        "복잡한 멀티홉 질문은 반복 검색 경로로 보낸다. 질문마다 다른 전략을 고르는 라우팅이 핵심이다.",
    ),
    Doc(
        "doc-agentic-rag-01",
        "src-agentic-rag",
        "Agentic RAG 는 검색을 고정 파이프라인이 아니라 에이전트가 호출하는 도구로 본다. "
        "LLM 이 다음 행동(검색할지·어떤 도구를 쓸지·끝낼지)을 매 턴 스스로 결정한다.",
    ),
    Doc(
        "doc-tool-contract-01",
        "src-tool-use",
        "Tool Contract 는 도구를 이름·설명·입력 스키마(JSON Schema)·출력 계약으로 정의한다. "
        "LLM 은 설명과 스키마만 보고 도구를 언제 어떻게 부를지 판단한다. 계약이 명확할수록 오호출이 준다.",
    ),
    Doc(
        "doc-workflow-vs-agent-01",
        "src-agentic-rag",
        "Workflow 는 코드가 순서를 고정한 파이프라인이고, Agent 는 LLM 이 루프 안에서 "
        "다음 행동을 결정하는 구조다. 예측 가능성이 필요하면 Workflow, 유연성이 필요하면 Agent 다.",
    ),
]

_TOKEN_RE = re.compile(r"[A-Za-z0-9가-힣]+")


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text)]


class _MockBM25:
    """독립 실행용 순수 BM25 검색기. 외부 의존 0. Phase 1 검색기가 없을 때만 쓴다."""

    def __init__(self, docs: list[Doc], *, k1: float = 1.5, b: float = 0.75) -> None:
        self.docs = docs
        self.k1 = k1
        self.b = b
        self.corpus_tokens = [_tokenize(d.text) for d in docs]
        self.doc_len = [len(toks) for toks in self.corpus_tokens]
        self.avgdl = sum(self.doc_len) / len(self.doc_len)
        # 문서 빈도(df) 계산.
        self.df: dict[str, int] = {}
        for toks in self.corpus_tokens:
            for term in set(toks):
                self.df[term] = self.df.get(term, 0) + 1
        self.n = len(docs)

    def _idf(self, term: str) -> float:
        df = self.df.get(term, 0)
        # BM25 표준 idf(음수 방지 +0.5 스무딩).
        return math.log(1 + (self.n - df + 0.5) / (df + 0.5))

    def search(self, query: str, k: int = 5) -> list[tuple[int, float]]:
        q_terms = _tokenize(query)
        scores: list[tuple[int, float]] = []
        for i, toks in enumerate(self.corpus_tokens):
            tf: dict[str, int] = {}
            for t in toks:
                tf[t] = tf.get(t, 0) + 1
            score = 0.0
            for term in q_terms:
                if term not in tf:
                    continue
                freq = tf[term]
                denom = freq + self.k1 * (1 - self.b + self.b * self.doc_len[i] / self.avgdl)
                score += self._idf(term) * (freq * (self.k1 + 1)) / denom
            if score > 0:
                scores.append((i, score))
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:k]


class DocsSearchBackend:
    """docs_search 도구의 검색 백엔드. Phase 1 검색기가 있으면 그걸, 없으면 mock BM25 를 쓴다."""

    def __init__(self) -> None:
        self.mode = "mock-bm25"
        self.docs = _MOCK_CORPUS
        self._mock = _MockBM25(self.docs)
        # 실전 경로: Phase 1/06 HybridSearcher 를 붙일 수 있으면 붙인다.
        # (import 실패는 조용히 넘어가고 mock 을 쓴다 — Phase 7 단독 실행 보장.)
        self._hybrid = None
        try:
            self._try_attach_phase1()
        except Exception:
            self._hybrid = None

    def _try_attach_phase1(self) -> None:
        """Phase 1/06 practice 를 sys.path 에 넣고 HybridSearcher 를 붙인다(있을 때만)."""
        import os
        import sys

        here = os.path.dirname(os.path.abspath(__file__))
        phase1 = os.path.normpath(
            os.path.join(here, "..", "..", "..", "phase-01-source-layer",
                         "06-baseline-hybrid-rag", "practice")
        )
        if not os.path.isdir(phase1):
            return
        sys.path.insert(0, phase1)
        from load_chunks import load_chunks, load_index  # type: ignore
        from hybrid_search import HybridSearcher  # type: ignore

        chunks = load_chunks()
        index = load_index()
        self._hybrid = HybridSearcher(chunks, index)
        self.mode = f"phase1-hybrid({self._hybrid.embed_backend})"

    def search(self, query: str, k: int = 3) -> list[dict]:
        """(query) → 인용 가능한 결과 리스트. 각 항목: chunk_id·score·source_id·text."""
        if self._hybrid is not None:
            results = []
            for cid, score in self._hybrid.search(query, k=k):
                c = self._hybrid.cmap[cid]
                results.append(
                    {
                        "chunk_id": c.chunk_id,
                        "score": round(float(score), 5),
                        "source_id": c.source_id,
                        "text": c.text,
                    }
                )
            return results
        # mock 경로.
        hits = self._mock.search(query, k=k)
        return [
            {
                "chunk_id": self.docs[i].chunk_id,
                "score": round(score, 5),
                "source_id": self.docs[i].source_id,
                "text": self.docs[i].text,
            }
            for i, score in hits
        ]


# 모듈 전역 백엔드(도구가 매 호출마다 재적재하지 않도록 한 번만 만든다).
_BACKEND = DocsSearchBackend()


def docs_search(query: str, k: int = 3) -> list[dict]:
    """docs_search 도구의 실제 실행 함수. tools.py 가 이걸 부른다."""
    return _BACKEND.search(query, k=k)


def backend_mode() -> str:
    """현재 검색 백엔드 이름(labs 출력 대조용)."""
    return _BACKEND.mode


if __name__ == "__main__":
    # 빠른 자기점검: 도구 본체만 단독 호출.
    print(f"[docs_search] backend={backend_mode()}\n")
    for q in ["CRAG 와 Self-RAG 의 차이", "Workflow 와 Agent 는 무엇이 다른가"]:
        print(f"query={q!r}")
        for r in docs_search(q, k=3):
            print(f"  {r['score']:.4f}  [{r['chunk_id']}]  {r['text'][:40]}…")
        print()
