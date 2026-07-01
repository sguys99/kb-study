"""app.py — 완성된 Reference Harness 를 FastAPI /chat 엔드포인트로 노출한다.

캡스톤 3개(금융·의료·연구)의 공통 완료 기준이 이 한 줄이다:

  curl http://localhost:8000/chat -d '{"query":"<멀티홉 질문>","mode":"agent"}'
  → 200 OK + 답변 + 인용(문서 chunk_id / 그래프 경로) + Audit Trail

이 파일은 얇은 어댑터다. 실제 일은 state_graph.run_harness 가 다 한다. FastAPI 는 요청을
ChatRequest 로 검증하고, 응답을 ChatResponse(Pydantic)로 직렬화할 뿐이다. Structured Output
계약(schema.py)이 요청·응답 양쪽을 못박으므로, 프런트·평가·감사가 같은 모양을 본다.

키 없이도 기동한다. run_harness 는 ANTHROPIC_API_KEY 가 없으면 mock 백엔드로 전 흐름을
돌린다(backend='rule/mock'). 그래서 curl 예시가 키·DB 없이 200 을 준다. 캡스톤·운영에서
키를 넣으면 같은 코드가 backend='claude' 로 바뀐다 — 엔드포인트 계약은 그대로.

기동:
  pip install -r requirements.txt
  uvicorn app:app --reload --port 8000
  # 또는  python app.py  (아래 __main__ 이 uvicorn 을 띄운다)

전제: fastapi·uvicorn·pydantic. state_graph(→05→04→03…) 가 import 경로에 붙는다.
"""

from __future__ import annotations

from fastapi import FastAPI

from schema import ChatRequest, ChatResponse
from state_graph import run_harness

app = FastAPI(
    title="KG·GraphRAG Reference Harness",
    description="Phase 7 통합 하니스 — State Graph + Structured Output + Citation + Audit Trail",
    version="1.0.0",
)


@app.get("/health")
def health() -> dict:
    """헬스체크. 컨테이너·기동 확인용. 키·DB 없이 항상 200."""
    import os

    return {
        "status": "ok",
        "backend": "claude" if os.environ.get("ANTHROPIC_API_KEY") else "rule/mock",
    }


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    """질문 하나를 통합 하니스에 태워 구조화 응답을 돌려준다.

    - 요청은 ChatRequest 로 자동 검증된다(query 빈 값·잘못된 mode 는 422).
    - 응답은 ChatResponse 로 직렬화된다: {answer{text,citations,confidence},
      citations[], audit_trail[], stop_reason, route, backend}.
    - 답의 인용은 state_graph 에서 실제 검색 결과와 대조돼 환각 인용이 제거된 뒤 나간다.
    """
    return run_harness(request)


if __name__ == "__main__":
    # python app.py 로도 바로 기동(uvicorn 프로그램matic).
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=False)
