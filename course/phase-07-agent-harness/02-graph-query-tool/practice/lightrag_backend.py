"""lightrag_backend.py — Phase 4 LightRAG 를 graph_query 의 한 백엔드로 감싼다.

Phase 4 에서 만든 LightRAG 인스턴스의 5모드(naive/local/global/hybrid/mix)를
graph_query 도구의 mode 파라미터로 노출한다. 도구 계약은 docs_search 와 같다:
(질의) → 인용 가능한 결과 리스트. LightRAG 는 텍스트 답변을 주므로,
그 답변 문자열을 근거(source='lightrag:<mode>')와 함께 한 행으로 감싼다.

두 경로:
  1) 실전 — Phase 4 practice 의 LightRAG 인스턴스를 붙일 수 있으면 rag.query(...) 를 호출.
  2) 기본(비용 0) — LightRAG·API 키가 없으면 mock 응답. 모드별로 '무엇이 다른지'만 보여준다.

전제(실전 경로만): Phase 4/06~08 의 LightRAG 인스턴스 + ANTHROPIC_API_KEY + VOYAGE_API_KEY.
  비용을 줄이려면 임베딩을 bge-m3(로컬), LLM 을 Ollama 로 바꿔도 파이프라인은 같다.
"""

from __future__ import annotations

# LightRAG 가 지원하는 5모드(glossary 표기 고정: 소문자 그대로).
VALID_MODES = ("naive", "local", "global", "hybrid", "mix")


class LightRAGBackend:
    """graph_query 의 lightrag 백엔드. mode 로 5모드를 분기한다."""

    def __init__(self) -> None:
        self.mode = "mock-lightrag"
        self._rag = None
        try:
            self._try_attach_phase4()
        except Exception:
            self._rag = None

    def _try_attach_phase4(self) -> None:
        """Phase 4 practice 의 LightRAG 인스턴스를 붙인다(있을 때만).

        Phase 4 코드가 build_lightrag() 처럼 초기화된 인스턴스를 제공한다고 가정한다.
        구조가 다르면 이 함수만 프로젝트에 맞게 고치면 된다.
        """
        import os
        import sys

        here = os.path.dirname(os.path.abspath(__file__))
        phase4 = os.path.normpath(
            os.path.join(here, "..", "..", "..", "phase-04-graphrag-lightrag",
                         "06-lightrag-setup", "practice")
        )
        if not os.path.isdir(phase4):
            return
        sys.path.insert(0, phase4)
        from lightrag_app import build_lightrag  # type: ignore

        self._rag = build_lightrag()
        self.mode = "phase4-lightrag"

    def query(self, question: str, mode: str = "hybrid") -> list[dict]:
        """(질의, 모드) → 인용 가능한 한 행 리스트. docs_search 와 같은 출력 모양."""
        if mode not in VALID_MODES:
            return [{"error": f"unknown mode: {mode}. 허용: {VALID_MODES}", "source": "lightrag"}]

        if self._rag is not None:
            from lightrag import QueryParam  # type: ignore

            answer = self._rag.query(question, param=QueryParam(mode=mode))
            return [{"answer": answer, "mode": mode, "source": f"lightrag:{mode}"}]

        # mock 경로: 모드별로 '무엇을 강조하는지'만 흉내 낸다(실제 검색 아님).
        hint = {
            "naive": "그래프를 쓰지 않고 벡터 청크만으로 답한 요약",
            "local": "질문 주변 엔티티의 지역 이웃을 근거로 한 답",
            "global": "커뮤니티 요약을 근거로 한 전역 관점 답",
            "hybrid": "지역 + 전역을 합친 답",
            "mix": "그래프 + 벡터를 융합한 답(권장 기본)",
        }[mode]
        return [
            {
                "answer": f"[mock-lightrag/{mode}] '{question}' 에 대한 {hint}.",
                "mode": mode,
                "source": f"lightrag:{mode}",
            }
        ]


# 모듈 전역 백엔드(매 호출 재적재 방지).
_BACKEND = LightRAGBackend()


def lightrag_query(question: str, mode: str = "hybrid") -> list[dict]:
    return _BACKEND.query(question, mode=mode)


def backend_mode() -> str:
    return _BACKEND.mode


if __name__ == "__main__":
    print(f"[lightrag_backend] backend={backend_mode()}\n")
    for m in VALID_MODES:
        rows = lightrag_query("GraphRAG 는 벡터 RAG 와 무엇이 다른가?", mode=m)
        print(f"mode={m}: {rows[0]['answer']}")
