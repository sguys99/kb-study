# Lab — 최소 Agent Harness 세우기 (docs_search + tool-use 루프)

도구 1개(`docs_search`)와 tool-use 루프만으로 최소 동작하는 에이전트 하니스를 세운다.
아래 명령을 순서대로 따라가며 각 단계의 **예상 출력**과 대조하라.

기본 경로는 API 키 없이 돈다(mock 백엔드). Claude 실전 경로는 4단계에서 켠다.

---

## 0. 준비

```bash
cd course/phase-07-agent-harness/01-agent-harness-minimal/practice
python --version   # Python 3.11+ 확인
```

예상 출력:

```
Python 3.11.x
```

기본(폴백) 실행은 표준 라이브러리만 쓴다. 설치 없이 다음 단계로 가도 된다.
Claude 실전 경로를 쓸 때만 아래를 설치한다.

```bash
pip install -r requirements.txt
```

---

## 1. 도구 본체 단독 실행 — `docs_search`

검색기를 도구로 감싼 본체가 (query → 인용 가능한 청크) 를 돌려주는지 먼저 본다.

```bash
python docs_search.py
```

예상 출력(점수는 코퍼스에 따라 다를 수 있고, chunk_id·순서가 핵심):

```
[docs_search] backend=mock-bm25

query='CRAG 와 Self-RAG 의 차이'
  1.9217  [doc-self-rag-01]  Self-RAG 는 생성 도중 특수 reflection 토큰을 뱉어, 검…
  1.9217  [doc-crag-01]  CRAG(Corrective RAG)는 검색 품질을 평가하는 경량 ret…
  0.4509  [doc-adaptive-rag-01]  Adaptive-RAG 는 질문의 난이도를 먼저 분류해, 단순 질문은 검…

query='Workflow 와 Agent 는 무엇이 다른가'
  4.6304  [doc-workflow-vs-agent-01]  Workflow 는 코드가 순서를 고정한 파이프라인이고, Agent 는 …
  ...
```

확인 포인트: `backend=mock-bm25` 이면 독립 경로로 도는 것이다.
Phase 1/06 practice 를 붙였으면 `backend=phase1-hybrid(...)` 로 뜬다.

---

## 2. Tool Contract 확인 — `tools.py`

도구가 어떤 스펙으로 모델에 노출되는지(이름·설명·JSON Schema) 본다.

```bash
python tools.py
```

예상 출력(발췌):

```
=== 등록된 도구 스펙(Anthropic tools 형식) ===
[
  {
    "name": "docs_search",
    "description": "문서 코퍼스에서 질의와 관련된 근거 청크를 검색한다. ...",
    "input_schema": {
      "type": "object",
      "properties": {
        "query": { "type": "string", ... },
        "k": { "type": "integer", "default": 3 }
      },
      "required": ["query"]
    }
  }
]

=== dispatch 테스트 ===
[
  { "chunk_id": "doc-self-rag-01", "score": ..., "source_id": "src-self-rag", "text": "Self-RAG ..." },
  ...
]
```

확인 포인트: `required: ["query"]` 와 출력 항목의 `chunk_id`.
이 계약이 02(`graph_query`)에서도 그대로 쓰인다.

---

## 3. 에이전트 루프 실행 (mock 백엔드, 비용 0)

API 키 없이 루프 자체를 검증한다. 멀티홉 질문을 던진다.

```bash
unset ANTHROPIC_API_KEY   # 폴백 강제(mock)
python agent_loop.py "CRAG 와 Self-RAG 는 무엇이 다른가?"
```

예상 출력:

```
[agent] backend=mock model=mock
[agent] question='CRAG 와 Self-RAG 는 무엇이 다른가?'

[turn 1] tool_use → docs_search({"query": "CRAG 와 Self-RAG 는 무엇이 다른가?", "k": 3})
[turn 2] 최종 답변(stop_reason=end_turn)

'CRAG 와 Self-RAG 는 무엇이 다른가?' 에 대한 답: 검색된 근거를 종합하면 아래와 같다. [doc-self-rag-01] [doc-crag-01] [doc-adaptive-rag-01]

--- 요약 ---
backend    : mock
tool_calls : ['docs_search']
turns      : 2
```

**완료 기준 체크**: `tool_calls` 에 `docs_search` 가 최소 1회 들어 있고,
최종 답변에 `[doc-...]` 인용이 붙었다. 여기까지면 이 토픽은 완료다.

mock 은 실제 추론을 하지 않는다 — 루프·tool_use/tool_result 왕복·인용 형식만
그대로 재현한다. 진짜 비교 답변은 다음 단계(Claude)에서 본다.

---

## 4. (선택) Claude 실전 경로

키가 있으면 실제 모델이 stop_reason 으로 도구 호출을 결정한다.

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export HARNESS_MODEL=claude-sonnet-4-6   # 생략 시 기본값
python agent_loop.py "CRAG 와 Self-RAG 는 무엇이 다른가?"
```

예상 출력(모델 표현은 매번 다르되, 구조는 동일):

```
[agent] backend=claude model=claude-sonnet-4-6
[agent] question='CRAG 와 Self-RAG 는 무엇이 다른가?'

[turn 1] tool_use → docs_search({"query": "Self-RAG CRAG 차이", "k": 3})
[turn 2] 최종 답변(stop_reason=end_turn)

Self-RAG 는 reflection 토큰으로 검색 필요 여부를 모델이 스스로 판단하는 적응형
방식이고 [doc-self-rag-01], CRAG 는 검색 품질을 평가해 부실하면 교정·보강하는
교정형 방식이다 [doc-crag-01]. ...

--- 요약 ---
backend    : claude
tool_calls : ['docs_search']
turns      : 2
```

확인 포인트: mock 과 **루프 구조가 같다**(turn 1 도구 호출 → turn 2 인용 답변).
바뀐 건 답변 문장의 질뿐이다. 하니스 뼈대는 백엔드와 무관하게 동일하다.

비용을 더 줄이려면 로컬 LLM(Ollama)로 바꿀 수 있다. `agent_loop.py` 의
`_make_client` 만 OpenAI 호환 엔드포인트로 교체하면 된다(주석 참조).

---

## 5. 헬스체크 요약

| 단계 | 명령 | 통과 신호 |
|------|------|-----------|
| 도구 본체 | `python docs_search.py` | `backend=...`, chunk_id 출력 |
| Tool Contract | `python tools.py` | `required: ["query"]`, dispatch 결과에 chunk_id |
| 루프(mock) | `python agent_loop.py "..."` | `tool_calls: ['docs_search']`, 답변에 `[doc-...]` |
| 루프(Claude) | 키 설정 후 재실행 | 같은 구조, 답변 품질만 향상 |

`tool_calls` 가 비어 있거나 인용이 없으면, `tools.py` 의 도구 description 이
"먼저 검색하라"를 충분히 강하게 지시하는지 확인한다(모델은 description 으로 판단한다).
