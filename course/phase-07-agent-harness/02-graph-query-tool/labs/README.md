# Lab — graph_query 도구 붙이기 (template · text2cypher · lightrag)

01의 tool-use 루프에 두 번째 도구 `graph_query`를 얹는다. 세 백엔드를 단독으로 확인한 뒤,
에이전트가 docs_search와 graph_query를 상황에 맞게 골라 부르는지 본다.

기본 경로는 Neo4j·LightRAG·API 키 없이 mock으로 돈다. 실전 경로는 각 단계 끝의 (선택)에서 켠다.

---

## 0. 준비

```bash
cd course/phase-07-agent-harness/02-graph-query-tool/practice
python --version   # Python 3.11+ 확인
unset ANTHROPIC_API_KEY NEO4J_URI NEO4J_PASSWORD   # mock 경로 강제(비용 0)
```

예상 출력:

```
Python 3.11.x
```

기본(mock) 실행은 표준 라이브러리만 쓴다. 설치 없이 다음 단계로 가도 된다.
실전 경로(Claude·Neo4j·LightRAG)를 켤 때만 아래를 설치한다.

```bash
pip install -r requirements.txt
```

---

## 1. 그래프 백엔드 단독 실행 — mock in-memory 그래프

Neo4j 없이 도는 축소 KG가 이웃·경로 질의에 답하는지 먼저 본다.

```bash
python graph_backend.py
```

예상 출력:

```
[graph_backend] kind=mock

neighbors('Self-RAG'):
   {'entity': 'Self-RAG', 'relation': 'USES', 'direction': '->', 'neighbor': 'Reflection Token', ...}
   {'entity': 'Self-RAG', 'relation': 'IS_A', 'direction': '->', 'neighbor': 'Agentic RAG', ...}

path_between('LightRAG', 'Tool Use'):
   {'from': 'LightRAG', 'relation': 'IMPLEMENTS', 'to': 'GraphRAG', 'source': 'e-graphrag'}
   {'from': 'GraphRAG', 'relation': 'EXTENDS', 'to': 'Agentic RAG', 'source': 'e-agentic-rag'}
   {'from': 'Agentic RAG', 'relation': 'BUILT_ON', 'to': 'Tool Use', 'source': 'e-tool-use'}
```

확인 포인트: `kind=mock`이면 독립 경로다. path_between이 3홉(LightRAG → GraphRAG →
Agentic RAG → Tool Use)을 찾아냈다. 이 멀티홉 연결이 벡터 검색으로는 안 잡히는 부분이다.

---

## 2. Template Cypher 단독 실행 — 미리 검증된 안전한 질의

템플릿 카탈로그(모델에 노출되는 이름·설명·파라미터)와 실제 Cypher를 본다.

```bash
python cypher_templates.py
```

예상 출력(발췌):

```
=== 템플릿 카탈로그(LLM 에 노출) ===
[
  { "name": "neighbors",     "description": "엔티티 하나의 1-홉 이웃과 관계를 조회한다. ...",
    "params": { "name": "...", "limit": "..." } },
  { "name": "path_between",  "description": "두 엔티티 사이 최단 경로를 조회한다. ...",
    "params": { "source": "...", "target": "...", "max_hops": "..." } }
]

=== neighbors 템플릿 Cypher ===
MATCH (x {name: $name})-[r]-(nb)
RETURN x.name AS entity, ... elementId(nb) AS source
LIMIT $limit
```

확인 포인트: Cypher가 `$name`·`$limit` **바인딩**만 쓴다(문자열 포매팅 없음 = 주입 없음).
로드 시 쓰기 키워드(CREATE/DELETE...)가 있으면 `assert`가 터진다.

---

## 3. graph_query 세 백엔드 한 번에 — template · text2cypher · lightrag

한 도구 계약이 method로 세 백엔드를 분기하는지 본다.

```bash
python graph_query.py
```

예상 출력(발췌):

```
[graph_query] graph_backend=mock

=== 1) template: neighbors(Self-RAG) ===
{ "method": "template", "template": "neighbors",
  "rows": [ { "entity": "Self-RAG", "relation": "USES", "neighbor": "Reflection Token",
              "source": "e-reflection-token" }, ... ], "backend": "mock" }

=== 2) template: path_between(LightRAG → Tool Use) ===
{ "method": "template", "template": "path_between",
  "rows": [ { "from": "LightRAG", "relation": "IMPLEMENTS", "to": "GraphRAG", ... }, ... ] }

=== 3) text2cypher: "'CRAG' 는 무엇과 연결돼 있나" ===
{ "method": "text2cypher",
  "rows": [ { "generated_cypher": "MATCH (x {name: 'CRAG'})-[r]-(nb) RETURN ..." }, ... ] }

=== 4) lightrag: mix 모드 ===
{ "method": "lightrag", "mode": "mix",
  "rows": [ { "answer": "[mock-lightrag/mix] ... 그래프 + 벡터를 융합한 답(권장 기본).",
              "source": "lightrag:mix" } ] }
```

확인 포인트:
- 세 백엔드 모두 `rows`의 각 항목에 인용용 `source`가 붙는다(계약 통일).
- text2cypher의 첫 행 `generated_cypher`가 '생성 → 실행' 흐름을 보여준다. 키가 없으면
  규칙 기반 mock 생성이다. **이 생성 문자열을 그대로 실행하는 위험을 막는 Safety Guard는 03에서 붙인다.**

---

## 4. Tool Contract 확인 — 01 registry에 graph_query가 얹혔는지

01의 `ToolRegistry`를 재사용해 도구가 2개로 늘었는지 본다.

```bash
python register_graph_tools.py
```

예상 출력(발췌):

```
=== 등록된 도구 이름 ===
['docs_search', 'graph_query']

=== graph_query dispatch: template neighbors ===
{ "method": "template", "template": "neighbors",
  "rows": [ { "entity": "Self-RAG", ..., "source": "e-reflection-token" }, ... ] }

=== graph_query dispatch: lightrag mix ===
{ "method": "lightrag", "mode": "mix", "rows": [ { "answer": "[mock-lightrag/mix] ...", ... } ] }
```

확인 포인트: `['docs_search', 'graph_query']` — 01의 docs_search는 그대로 있고 graph_query가
추가됐다. 01의 Tool/ToolRegistry를 다시 만들지 않고 `import`해 얹은 결과다.

---

## 5. 에이전트 루프 — 도구 2개로 상황별 선택 (mock, 비용 0)

에이전트가 질문 종류에 따라 도구를 골라 부르는지 본다. 먼저 관계·경로 질문.

```bash
python agent_loop.py "LightRAG 와 Tool Use 는 어떻게 이어지나?"
```

예상 출력:

```
[agent] backend=mock model=mock
[agent] tools=['docs_search', 'graph_query']
[agent] question='LightRAG 와 Tool Use 는 어떻게 이어지나?'

[turn 1] tool_use → graph_query({"method": "template", "template": "path_between",
                                 "params": {"source": "LightRAG", "target": "Tool Use"}})
[turn 2] 최종 답변(stop_reason=end_turn)

'LightRAG 와 Tool Use 는 어떻게 이어지나?' 에 대한 답: 검색·그래프 근거를 종합하면
아래와 같다. [e-graphrag] [e-agentic-rag] [e-tool-use]

--- 요약 ---
backend    : mock
tool_calls : ['graph_query']
turns      : 2
```

이번엔 정의·비교 질문을 던진다.

```bash
python agent_loop.py "CRAG 와 Self-RAG 는 무엇이 다른가?"
```

예상 출력:

```
[turn 1] tool_use → docs_search({"query": "CRAG 와 Self-RAG 는 무엇이 다른가?", "k": 3})
[turn 2] 최종 답변(stop_reason=end_turn)
... [doc-self-rag-01] [doc-crag-01] [doc-adaptive-rag-01]

--- 요약 ---
tool_calls : ['docs_search']
```

**완료 기준 체크**: 관계 질문엔 `graph_query`(template Cypher가 파라미터로 실행), 정의 질문엔
`docs_search`를 골랐고, 두 답변 모두 근거 인용(`[e-...]` 또는 `[doc-...]`)이 붙었다. 여기까지면 완료다.

mock은 실제 추론을 하지 않는다 — 도구 선택을 규칙으로 흉내 낸다. 진짜 판단은 다음 단계(Claude)에서 본다.

---

## 6. (선택) Claude 실전 경로

키가 있으면 실제 모델이 어떤 도구·method를 쓸지 스스로 정한다. text2cypher의 Cypher 생성도 진짜 LLM이 한다.

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export HARNESS_MODEL=claude-sonnet-4-6   # 생략 시 기본값
python agent_loop.py "LightRAG 와 Tool Use 는 어떻게 이어지나?"
```

예상 출력(표현은 매번 다르되 구조는 동일):

```
[agent] backend=claude model=claude-sonnet-4-6
[turn 1] tool_use → graph_query({"method": "template", "template": "path_between", ...})
[turn 2] 최종 답변(stop_reason=end_turn)
LightRAG 는 GraphRAG 를 구현하고 [e-graphrag], GraphRAG 는 Agentic RAG 를 확장하며
[e-agentic-rag], Agentic RAG 는 Tool Use 위에 선다 [e-tool-use]. ...
```

확인 포인트: mock과 **루프 구조가 같다**. 바뀐 건 도구·method 선택의 품질과 답변 문장뿐이다.

---

## 7. (선택) Neo4j 실전 백엔드

Neo4j가 있으면 template Cypher를 실제 DB에 읽기 전용으로 실행한다.

```bash
export NEO4J_URI=bolt://localhost:7687
export NEO4J_USER=neo4j
export NEO4J_PASSWORD=your-password
python graph_query.py
```

예상 출력(발췌):

```
[graph_query] graph_backend=neo4j
=== 1) template: neighbors(Self-RAG) ===
{ "method": "template", "template": "neighbors", "rows": [ ... ], "backend": "neo4j" }
```

확인 포인트: `backend=neo4j`로 뜬다. 실행은 `session.execute_read` 안에서만 돈다(읽기 전용).
Phase 3에서 만든 KG를 그대로 붙이면 mock보다 풍부한 이웃·경로가 나온다.

접속 정보가 틀리면 조용히 mock으로 폴백한다(단독 실행 보장). `backend=mock`이 뜨면 접속을 다시 확인한다.

---

## 8. 헬스체크 요약

| 단계 | 명령 | 통과 신호 |
|------|------|-----------|
| 그래프 백엔드 | `python graph_backend.py` | `kind=mock`, path_between 3홉 출력 |
| 템플릿 | `python cypher_templates.py` | Cypher가 `$name` 바인딩 사용 |
| 3-백엔드 | `python graph_query.py` | template/text2cypher/lightrag 모두 `rows`에 `source` |
| Registry | `python register_graph_tools.py` | `['docs_search', 'graph_query']` |
| 루프(관계) | `python agent_loop.py "...이어지나?"` | `tool_calls: ['graph_query']`, `[e-...]` 인용 |
| 루프(정의) | `python agent_loop.py "...다른가?"` | `tool_calls: ['docs_search']`, `[doc-...]` 인용 |
| Neo4j(선택) | 접속 후 `python graph_query.py` | `backend=neo4j` |

에이전트가 관계 질문에도 docs_search만 부른다면, `register_graph_tools.py`의 graph_query
description이 "관계·경로는 graph_query를 써라"를 충분히 강하게 지시하는지 확인한다(모델은 description으로 판단한다).
