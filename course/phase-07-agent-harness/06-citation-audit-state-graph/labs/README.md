# Labs — 06 Structured Output · Citation · Audit Trail + 통합 State Graph

01~05 의 부품이 여기서 하나로 합쳐진다. 명시적 State Graph 위에 구조화 출력·인용 검증·감사
추적을 얹고, FastAPI `/chat` 로 노출한다. **API 키·Neo4j 없이 mock 으로 전 흐름을 재현**하되,
FastAPI 는 실제로 기동해 `curl` 로 200 을 확인한다.

## 0. 준비

```bash
cd course/phase-07-agent-harness/06-citation-audit-state-graph/practice

# 05 와 같은 가상환경을 재사용하면 pydantic·anthropic·PyYAML 은 이미 있다.
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt   # 여기서 fastapi·uvicorn 이 추가된다

# 체크포인트를 비대화로: 자동 승인(기본과 동일)
export AUTO_APPROVE=1
```

통합 계층(schema·citation·audit·state_graph)은 Pydantic 만 있으면 돈다. `state_graph` 는 05
practice(guarded_loop 등)를 import 경로에 자동으로 올리고, 그게 다시 04·03 을 올린다. 즉
01~05 practice 디렉토리가 제자리에 있어야 한다.

### 헬스체크 — 네 부품 단위 자기점검

```bash
python schema.py       # Pydantic 스키마: 유효/무효 입력 판정
python citation.py     # 환각 인용 제거
python audit.py        # 감사 로그 단계 기록
python state_graph.py  # 통합: route→…→answer + citation_check
```

`schema.py` 예상 출력(요지):

```
요청 파싱: {'query': 'Self-RAG 는 언제 검색을 하나?', 'mode': 'agent'}
응답 JSON:
{ ... "stop_reason": "answered", "route": "simple", "backend": "rule/mock" }
[OK] 무효 입력 거부: {'query': '', 'mode': 'agent'} → ValidationError
[OK] 무효 입력 거부: {'query': 'x', 'mode': 'unknown'} → ValidationError
```

`citation.py` 예상 출력:

```
검색으로 나온 실존 인용 id: ['Self-RAG -[RELATES]-> CRAG', 'doc-crag-01', 'doc-self-rag-01']
검증 결과: {'valid': ['doc-self-rag-01', 'Self-RAG -[RELATES]-> CRAG'], 'dropped': ['doc-fake-99'], ...}
[assert] 환각 인용 1건 제거, 실존 인용 2건 유지 통과
```

네 부품이 각각 스키마 검증 · 환각 제거 · 감사 기록 · 통합 실행을 하면 준비 완료.

---

## 시나리오 1 — State Graph 단독 실행 → ChatResponse 에 단계별 audit_trail

`run_harness` 를 코드로 직접 불러 통합 흐름을 확인한다. 한 질문이 route→retrieve→grade→
checkpoint→answer→citation_check 를 밟고, 그 전이가 audit_trail 에 한 줄씩 남는다.

```bash
python state_graph.py
```

예상 출력(첫 질문):

```
=== [agent] Self-RAG 는 언제 검색을 하나? ===
route      : simple | stop_reason: answered | backend: rule/mock
confidence : 0.85
citations  : ['doc-self-rag-01', 'doc-tool-contract-01', 'doc-agentic-rag-01']
audit_trail:
  [0] ok route          {'route': 'simple', 'backend': 'rule/mock', 'tools_planned': ['docs_search']}
  [1] ok retrieve       {'tool': 'docs_search', 'note': '도구 실행'}
  [2] ok grade          {'grade': 'relevant', 'sufficient': True}
  [3] ok checkpoint     {'needed': False, 'approved': True, 'mode': 'not-needed', 'reasons': []}
  [4] ok answer         {'stop_reason': 'answered', 'n_citations': 3, 'budget': {...}}
  [5] ok citation_check {'valid': [...3건...], 'dropped': [], 'hallucinated': 0}

[assert] route→…→answer/stop + citation_check 기록 통과
```

관계 질문(`CRAG 와 Self-RAG 는 어떻게 연결돼 있나?`)은 `route=relation` 으로 `graph_query` 를
타고, 인용이 그래프 경로 근거(`e-agentic-rag` 등)로 붙는다. 두 질문 모두 audit_trail 의
마지막 두 단계가 `answer` → `citation_check` 인지 확인한다 — 이게 State Graph 가 끝까지
돌았다는 증거다.

---

## 시나리오 2 — 환각 인용을 주입하면 citation 검증이 제거한다

답이 '실제로 검색되지 않은' 인용을 달았다고 가정하고, 검증이 그걸 걸러내는지 본다. RAG 신뢰를
가장 크게 무너뜨리는 실패(근거 있는 척하는 거짓말)를 코드로 재현한다.

```bash
python -c "
from citation import build_evidence_index, verify_citations
from schema import Citation

# 이번 질문에서 도구가 실제로 돌려준 결과(allowed set 의 원천).
retrievals = [[{'chunk_id':'doc-self-rag-01','source_id':'src-self-rag','text':'Self-RAG…'}]]
index = build_evidence_index(retrievals)

# 답이 단 인용: 1건은 실존, 1건은 지어냄(doc-HALLUCINATED-42).
cites = [Citation(id='doc-self-rag-01'), Citation(id='doc-HALLUCINATED-42')]
chk = verify_citations(cites, index)
print('valid  =', [c.id for c in chk.valid])
print('dropped=', chk.dropped, '| hallucinated =', chk.hallucinated)
"
```

예상 출력:

```
valid  = ['doc-self-rag-01']
dropped= ['doc-HALLUCINATED-42'] | hallucinated = 1
```

검색 인덱스에 없는 `doc-HALLUCINATED-42` 는 `dropped` 로 빠지고, 실존 인용만 `valid` 에
남는다. 이 검증은 State Graph 의 `citation_check` 단계에서 자동으로 돈다 — 그래서 `/chat`
응답에는 실제 검색 결과에 존재하는 인용만 나간다.

---

## 시나리오 3 — uvicorn 기동 → curl POST /chat → 200 + answer·citations·audit_trail

이제 하니스를 HTTP 로 노출한다. 캡스톤 3개의 공통 완료 기준이 바로 이 curl 이다.

### 3a. 기동 + 헬스체크

```bash
uvicorn app:app --port 8000        # 또는  python app.py
# 다른 터미널에서:
curl -s http://localhost:8000/health
```

예상 출력:

```json
{"status":"ok","backend":"rule/mock"}
```

`ANTHROPIC_API_KEY` 를 넣고 기동하면 `"backend":"claude"` 로 바뀐다. 키가 없어도 200 이다.

### 3b. `/chat` — 200 + 구조화 답 + 검증된 인용 + Audit Trail

```bash
curl -s -X POST http://localhost:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"query":"Self-RAG 는 언제 검색을 하나?","mode":"agent"}' | python -m json.tool
```

예상 출력(핵심 필드):

```json
{
  "answer": {
    "text": "'Self-RAG 는 언제 검색을 하나?' 에 대한 답: ... [doc-self-rag-01] [doc-tool-contract-01] [doc-agentic-rag-01]",
    "citations": [
      {"id": "doc-self-rag-01", "kind": "chunk", "source": "src-self-rag", "snippet": "Self-RAG 는 …"},
      {"id": "doc-tool-contract-01", "kind": "chunk", "source": "src-tool-use", "snippet": "Tool Contract 는 …"},
      {"id": "doc-agentic-rag-01", "kind": "chunk", "source": "src-agentic-rag", "snippet": "Agentic RAG 는 …"}
    ],
    "confidence": 0.85
  },
  "citations": [ /* answer.citations 사본 — 프런트가 바로 렌더링 */ ],
  "audit_trail": [
    {"seq": 0, "step": "route",          "ok": true, "detail": {"route": "simple", "tools_planned": ["docs_search"], ...}},
    {"seq": 1, "step": "retrieve",       "ok": true, "detail": {"tool": "docs_search", ...}},
    {"seq": 2, "step": "grade",          "ok": true, "detail": {"grade": "relevant", "sufficient": true, ...}},
    {"seq": 3, "step": "checkpoint",     "ok": true, "detail": {"needed": false, "approved": true, ...}},
    {"seq": 4, "step": "answer",         "ok": true, "detail": {"stop_reason": "answered", "n_citations": 3, "budget": {...}}},
    {"seq": 5, "step": "citation_check", "ok": true, "detail": {"valid": [...3건...], "dropped": [], "hallucinated": 0}}
  ],
  "stop_reason": "answered",
  "route": "simple",
  "backend": "rule/mock"
}
```

`200 OK` + `answer`(구조화) + `citations`(검증 통과) + `audit_trail`(단계별)이 오면 이 토픽의
완료 기준을 만족한다. 멀티홉 질문(`"query":"CRAG 와 Self-RAG 는 어떻게 연결돼 있나?"`)으로
바꾸면 `route` 가 `relation` 으로 바뀌고 인용이 그래프 경로 근거로 붙는다.

### 3c. 잘못된 요청은 422 로 막힌다

```bash
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://localhost:8000/chat \
  -H 'Content-Type: application/json' -d '{"query":"","mode":"agent"}'
```

예상 출력:

```
422
```

빈 `query` 나 잘못된 `mode` 는 Pydantic(ChatRequest)이 막아 `422 Unprocessable Entity` 를
돌려준다 — Structured Output 이 입력에도 걸린다.

---

## 시나리오 4 — 예산 초과·체크포인트가 audit_trail 에 남는지

가드(05)가 개입한 흔적이 감사 로그에 그대로 남아야 재현·디버깅이 된다.

### 4a. 예산을 조이면 `stop` 단계 + `stop_reason=budget_exceeded`

`mode="baseline"` 은 예산을 도구 1회로 조여 교정 루프를 막는다(agent 와 비교용).

```bash
python -c "
from schema import ChatRequest
from state_graph import run_harness
r = run_harness(ChatRequest(query='Mamba 아키텍처는 무엇인가?', mode='baseline'))
print('stop_reason =', r.stop_reason, '| confidence =', r.answer.confidence)
print('steps =', [e.step for e in r.audit_trail])
"
```

예상 출력:

```
stop_reason = budget_exceeded | confidence = 0.2
steps = ['route', 'retrieve', 'answer', 'citation_check']
```

`Mamba` 는 mock 코퍼스에 없어 검색이 부실하고, 예산 1회 상한에 걸려 `budget_exceeded` 로
멈춘다. `confidence` 가 0.2 로 낮게 매겨져 프런트가 '주의' 배지를 붙일 수 있다.

agent 모드에서 예산을 코드로 더 세게 조이면 audit_trail 에 `stop` 단계가 명시적으로 남는다:

```bash
python -c "
from state_graph import _record_states
from audit import AuditTrail
from guarded_loop import run_guarded
from guards import ToolCache
from budget import Budget
g = run_guarded('Mamba 아키텍처는 무엇인가?',
                budget=Budget(max_tokens=None, max_tool_calls=1, max_seconds=None),
                cache=ToolCache(), verbose=False)
t = AuditTrail(); _record_states(t, g)
print('stop_reason =', g.stop_reason, '| steps =', t.steps())
"
```

예상 출력:

```
stop_reason = budget_exceeded | steps = ['route', 'retrieve', 'grade', 'checkpoint', 'stop']
```

마지막 단계가 `answer` 가 아니라 `stop` 이다 — 답을 못 내고 예산으로 끊겼음을 감사 로그가
남긴다.

### 4b. 체크포인트 거절이 `rejected_by_human` 으로 남는지

```bash
AUTO_APPROVE=0 python -c "
from state_graph import _record_states
from audit import AuditTrail
from guarded_loop import run_guarded
from guards import ToolCache
g = run_guarded('완전히 무관한 외계어 zzzxxx', cache=ToolCache(), verbose=False)
t = AuditTrail(); _record_states(t, g)
print('stop_reason =', g.stop_reason)
print('steps =', t.steps())
"
```

예상 출력(요지):

```
stop_reason = rejected_by_human
steps = ['route', 'retrieve', 'grade', 'correct', 'retrieve', 'grade', 'correct', 'retrieve', 'grade', 'checkpoint', 'stop']
```

저신뢰(근거 계속 부실) 답이 체크포인트에 걸리고, `AUTO_APPROVE=0` 거절이라
`rejected_by_human` 으로 멈춘다. 교정 재시도(`correct`→`retrieve`→`grade` 반복)와 마지막
`checkpoint`→`stop` 이 모두 감사 로그에 남아, "왜 답이 보류됐는지"를 되짚을 수 있다.

---

## 완료 체크

- [ ] 시나리오 1: `state_graph.py` 가 route→retrieve→grade→checkpoint→answer→citation_check 를 audit_trail 에 순서대로 남긴다
- [ ] 시나리오 2: 환각 인용 주입 시 `citation` 검증이 `dropped` 로 제거하고 실존 인용만 `valid` 에 남긴다
- [ ] 시나리오 3: `uvicorn` 기동 → `curl POST /chat` 가 200 + `answer`·`citations`·`audit_trail` JSON 을 반환하고, 잘못된 요청은 422
- [ ] 시나리오 4: 예산 초과는 `stop`(`budget_exceeded`), 체크포인트 거절은 `rejected_by_human` 으로 audit_trail 에 남는다

네 가지가 재현되면 Phase 7 Reference Harness 완성이다. 이제 캡스톤 3개가 이 하니스 하나를
공유하고 도메인 데이터·온톨로지·평가만 갈아 끼운다.
