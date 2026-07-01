"""schema.py — 하니스의 입출력 계약을 Pydantic 모델로 못박는다.

05 까지 run_guarded 는 자유 형태 dataclass(GuardedResult)를 돌려줬다. 사람이 읽기엔 됐지만
'서비스가 뱉는 응답'으로는 느슨하다. answer 가 문자열이든 None 이든 통과하고, citations 가
빠져도 아무도 안 막는다. 캡스톤 3개가 이 하니스 하나를 공유하려면, 응답의 '모양'이 스키마로
고정돼 있어야 한다 — 그래야 프런트·평가·감사가 같은 계약 위에서 돈다.

여기서 정의하는 계약(전부 Pydantic v2 BaseModel):
  - ChatRequest   : /chat 요청. {query, mode}. mode 는 agent/baseline enum.
  - Citation      : 인용 한 건. {id, kind, source, snippet}. id 는 chunk_id 또는 그래프 경로.
  - Answer        : 최종 답 '내용'. {text, citations[], confidence}. 자유 텍스트가 아니다.
  - AuditEntry    : 감사 로그 한 줄. {step, detail, ...}. audit.py 가 append 로 채운다.
  - ChatResponse  : /chat 응답 전체. {answer, citations, audit_trail, stop_reason, route, backend}.

Structured Output 을 강제하는 두 방식(lesson 참조):
  1) Pydantic 검증 + 재시도 — LLM 이 뱉은 JSON 을 model_validate 로 검증, 깨지면 다시.
  2) Anthropic tool-use — '최종 답 형식'을 tool 하나로 정의해 스키마 준수를 API 가 강제.
이 파일은 (1)의 뼈대다. 어느 쪽이든 최종 산출은 아래 ChatResponse 로 수렴한다.

전제: 표준 라이브러리 + pydantic>=2.7. API 키·DB 불필요.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


# ── 요청 ────────────────────────────────────────────────────────────────────
class ChatRequest(BaseModel):
    """/chat 요청. 캡스톤 완료 기준의 {"query":..., "mode":"agent"} 를 그대로 받는다."""

    query: str = Field(..., min_length=1, description="사용자 질문")
    mode: Literal["agent", "baseline"] = Field(
        "agent", description="agent=가드 루프 전체, baseline=단순 검색+답(비교용)"
    )

    @field_validator("query")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("query 가 비었다")
        return v


# ── 인용 ────────────────────────────────────────────────────────────────────
class Citation(BaseModel):
    """근거 한 건. 답변의 각 주장이 '어디서' 왔는지 가리킨다.

    kind 로 근거의 종류를 구분한다:
      - chunk : 문서 청크(docs_search 의 chunk_id).
      - graph : 그래프 경로·이웃(graph_query 의 rows 한 줄).
      - source: 출처 식별자(source_id) 만 있을 때.
    id 는 그 근거의 고유 키다. citation.py 가 '이 id 가 실제 검색 결과에 있는가'를 검증한다.
    """

    id: str = Field(..., description="근거 식별자: chunk_id / 그래프 경로 키 / source_id")
    kind: Literal["chunk", "graph", "source"] = "chunk"
    source: str | None = Field(None, description="출처(source_id 등). 있으면 표기용")
    snippet: str | None = Field(None, description="근거 원문 일부(디버깅·표시용, 200자 제한)")

    @field_validator("snippet")
    @classmethod
    def _clip(cls, v: str | None) -> str | None:
        return v if v is None else v[:200]


# ── 답 내용 ─────────────────────────────────────────────────────────────────
class Answer(BaseModel):
    """최종 답의 '내용'. 자유 텍스트가 아니라 구조다.

    confidence 는 0~1. 05 의 grade/stop_reason 을 근거로 상위 루프가 채운다(answered=높음,
    max_retry/budget_exceeded=낮음). 낮은 confidence 는 프런트가 '주의' 배지를 붙이는 근거.
    """

    text: str = Field(..., description="한국어 답변 본문")
    citations: list[Citation] = Field(default_factory=list)
    confidence: float = Field(0.0, ge=0.0, le=1.0)


# ── 감사 로그 한 줄 ─────────────────────────────────────────────────────────
class AuditEntry(BaseModel):
    """audit_trail 의 한 항목. '질문 처리의 한 단계'를 구조화해 남긴다.

    step  : route / retrieve / grade / correct / fallback / checkpoint / answer / stop.
    ok    : 그 단계가 정상이었는지(도구 실패·거절이면 False).
    detail: 단계별 요약 dict(도구명·grade·score·예산 스냅샷 등). 자유 형태로 두되 JSON 직렬화 가능.
    seq   : 순번(0부터). 시간순 재생에 쓴다.
    """

    seq: int
    step: str
    ok: bool = True
    detail: dict = Field(default_factory=dict)


# ── 응답 전체 ───────────────────────────────────────────────────────────────
class ChatResponse(BaseModel):
    """/chat 응답 전체. 캡스톤 완료 기준의 '답변 + 인용 + Audit Trail' 을 한 계약으로 묶는다.

    citations 는 Answer.citations 와 같은 것을 상위에 한 번 더 노출한다(프런트가 답 본문과
    별개로 근거 목록을 바로 렌더링하기 쉽게). answer.citations 가 단일 진실이고, 이건 그 사본.
    """

    answer: Answer
    citations: list[Citation] = Field(default_factory=list)
    audit_trail: list[AuditEntry] = Field(default_factory=list)
    stop_reason: str = "answered"     # 05 GuardedResult.stop_reason 그대로
    route: str = ""                   # 04 route(simple/relation/broad/schema)
    backend: str = "rule/mock"        # claude / rule/mock


if __name__ == "__main__":
    # 빠른 자기점검: 스키마가 유효/무효 입력을 옳게 가르는지.
    req = ChatRequest.model_validate({"query": "  Self-RAG 는 언제 검색을 하나?  ", "mode": "agent"})
    print("요청 파싱:", req.model_dump())

    ans = Answer(
        text="Self-RAG 는 매 스텝 검색 여부를 스스로 정한다.[doc-self-rag-01]",
        citations=[Citation(id="doc-self-rag-01", kind="chunk", source="src-self-rag",
                            snippet="Self-RAG 는 reflection 토큰으로 검색 필요성을 평가한다.")],
        confidence=0.8,
    )
    resp = ChatResponse(
        answer=ans, citations=ans.citations,
        audit_trail=[AuditEntry(seq=0, step="route", detail={"route": "simple"})],
        stop_reason="answered", route="simple", backend="rule/mock",
    )
    print("응답 JSON:")
    print(resp.model_dump_json(indent=2))

    # 무효 입력은 막혀야 한다.
    for bad in [{"query": "", "mode": "agent"}, {"query": "x", "mode": "unknown"}]:
        try:
            ChatRequest.model_validate(bad)
            print("[FAIL] 무효 입력이 통과됨:", bad)
        except Exception as e:
            print(f"[OK] 무효 입력 거부: {bad} → {type(e).__name__}")
