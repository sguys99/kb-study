# Labs — Cypher Safety Guard + ontology_check

단계별로 명령을 돌리고, 아래 **예상 출력**과 대조한다. 실제 값(노드 id 등)은 조금 다를 수 있으니 구조와 판정(BLOCK/PASS/ok)을 본다.

## 0. 준비

```bash
cd course/phase-07-agent-harness/03-cypher-safety-ontology-check/practice
python -m venv .venv && source .venv/bin/activate   # 선택
pip install -r requirements.txt
```

- Safety Guard(`cypher_safety.py`)는 표준 라이브러리만으로 돈다.
- `ontology.py` / `ontology_check.py` 는 Pydantic v2 + PyYAML 이 필요하다.
- API 키·Neo4j 는 없어도 된다. 없으면 mock 그래프 + 02 의 규칙 기반 mock 생성기로 폴백한다.
- 실전 경로를 쓰려면 `ANTHROPIC_API_KEY`(text2cypher LLM 생성) 또는 `NEO4J_URI/NEO4J_USER/NEO4J_PASSWORD`(Neo4j 5.26 LTS 실행)를 환경변수로 준다.

## 1. Safety Guard — 위험 Cypher 를 거부 사유와 함께 차단

```bash
python cypher_safety.py
```

예상 출력(발췌):

```
=== Cypher Safety Guard 검사 ===

[PASS ] 정상: 이웃 조회
        입력 : MATCH (x {name:'Self-RAG'})-[r]-(nb) RETURN nb.name LIMIT 10
        실행 : MATCH (x {name:'Self-RAG'})-[r]-(nb) RETURN nb.name LIMIT 10

[PASS ] 정상: LIMIT 없음(보강됨)
        입력 : MATCH (n:Method) RETURN n.name
        실행 : MATCH (n:Method) RETURN n.name LIMIT 50        ← LIMIT 자동 보강

[PASS ] 정상: 문자열 속 CREATE(오탐 아님)
        입력 : MATCH (n {name:'CREATE THE FUTURE'}) RETURN n
        실행 : MATCH (n {name:'CREATE THE FUTURE'}) RETURN n LIMIT 50

[BLOCK] 위험: 노드 생성
        사유 : 쓰기/부작용 키워드 금지: 'CREATE' 발견

[BLOCK] 위험: MATCH 뒤 DELETE
        사유 : 쓰기/부작용 키워드 금지: 'DELETE' 발견

[BLOCK] 위험: SET 로 속성 변경
        사유 : 쓰기/부작용 키워드 금지: 'SET' 발견

[BLOCK] 위험: 다중 구문 주입
        입력 : MATCH (n) RETURN n; DROP INDEX foo
        사유 : 다중 구문 금지: 세미콜론(;)으로 구문이 둘 이상이다

[BLOCK] 위험: LOAD CSV
        사유 : 쓰기/부작용 키워드 금지: 'LOAD CSV' 발견

[BLOCK] 위험: apoc 쓰기
        입력 : CALL apoc.create.node(['X'],{}) YIELD node RETURN node
        사유 : 쓰기/부작용 키워드 금지: 'CREATE' 발견        ← 쓰기 키워드에 먼저 걸림(BLOCK 은 동일)

[BLOCK] 위험: CALL 서브쿼리
        사유 : CALL {...} 서브쿼리 금지(쓰기 은닉 방지)

[BLOCK] 위험: 무상한 가변 경로
        입력 : MATCH p=(a)-[*]-(b) RETURN p
        사유 : 가변 길이 경로에 홉 상한이 없다: '[*]' (상한 5 이하 필요)

[BLOCK] 위험: 과대 홉 경로
        사유 : 가변 길이 경로 상한이 너무 크다: '[*..99]' (>5)

[assert] Safety Guard 자체검증 통과
```

**헬스체크**: 마지막 줄에 `[assert] Safety Guard 자체검증 통과` 가 나와야 한다. 위험 케이스는 전부 `[BLOCK]`, 정상 케이스는 `[PASS]` 이고 `LIMIT` 이 없던 질의에는 `LIMIT 50` 이 붙어야 한다.

## 2. 온톨로지 로드 — 허용 라벨·관계 집합 확인

```bash
python ontology.py
```

예상 출력(발췌):

```
== 온톨로지 로드 (version=2025.07) ==
  허용 라벨   : ['Component', 'Concept', 'Framework', 'Method']
  허용 관계   : ['BUILT_ON', 'EXTENDS', 'IMPLEMENTS', 'IS_A', 'USES']

== 관계 정규화 ==
  'USES'       -> USES
  'use'        -> USES          ← alias 정규화
  'IS_A'       -> IS_A
  'MENTIONS'   -> REJECT(미등록 관계)

[assert] 온톨로지 자체검증 통과
```

**헬스체크**: 허용 라벨 4개·관계 5개가 나오고, `MENTIONS` 는 REJECT 되어야 한다.

## 3. ontology_check — 스키마 위반 라벨·관계·방향 검출

```bash
python ontology_check.py
```

예상 출력(발췌):

```
=== ontology_check: Cypher 검사 ===

정상 Cypher: MATCH (m:Method)-[:USES]->(c:Component) RETURN m.name, c.name LIMIT 10
{ "ok": true, "checked": { "labels": ["Method","Component"], "relations": ["USES"], "triples": 0 },
  "violations": [] }

위반 Cypher(:Dataset 라벨 + :MENTIONS 관계): MATCH (m:Method)-[:MENTIONS]->(d:Dataset) ...
{ "ok": false,
  "violations": [
    { "kind": "unknown_label", "item": "Dataset", "reason": "온톨로지에 없는 라벨: 'Dataset'. ..." },
    { "kind": "unknown_relation", "item": "MENTIONS", "reason": "온톨로지에 없는 관계 타입: 'MENTIONS'. ..." } ] }

=== ontology_check: 삼중항 방향 검사 ===
{ "ok": false,
  "violations": [
    { "kind": "direction_violation",
      "item": "(Component)-[USES]->(Method)",
      "reason": "방향 위반: USES 는 (Method)-[USES]->(Component) 만 허용. ..." },
    { "kind": "unknown_relation", "item": "(Method)-[CURES]->(Concept)", ... } ] }

[assert] ontology_check 자체검증 통과
```

**헬스체크**: 정상 Cypher 는 `ok=true`, 위반 Cypher 는 `ok=false` 에 `unknown_label` + `unknown_relation` 이 함께 나오고, 방향이 거꾸로인 `(Component)-[USES]->(Method)` 는 `direction_violation` 으로 잡혀야 한다.

## 4. 세 도구 등록 — graph_query(안전판) + ontology_check

```bash
python register_all_tools.py
```

예상 출력(발췌):

```
=== 등록된 도구 이름(3개여야 한다) ===
['docs_search', 'graph_query', 'ontology_check']

=== graph_query(text2cypher) — Safety Guard 통과 후 실행 ===
{ "method": "text2cypher", "rows": [ { "generated_cypher": "MATCH (x {name: 'CRAG'})-[r]-(nb) ... LIMIT 10",
                                        "safe_cypher": "...", "blocked": false }, ... ], "backend": "mock" }

=== ontology_check — 위반 Cypher 검사 ===
{ "ok": false, "violations": [ ... "unknown_label": "Dataset" ..., "unknown_relation": "MENTIONS" ... ] }

[assert] 도구 3개 등록 + ontology_check 위반 탐지 통과
```

**헬스체크**: 도구 이름이 정확히 `['docs_search', 'graph_query', 'ontology_check']` 3개여야 한다. text2cypher 결과에 `blocked: false` 와 `safe_cypher` 가 있어야 한다(Guard 통과).

## 5. 에이전트 루프 — 세 도구로 안전하게 답하기

관계 질문 → `graph_query`:

```bash
python agent_loop.py "Self-RAG 는 무엇과 연결돼 있나?"
```

예상 출력(발췌):

```
[agent] backend=mock model=mock
[agent] tools=['docs_search', 'graph_query', 'ontology_check']
[turn 1] tool_use → graph_query({"method": "template", "template": "neighbors", "params": {"name": "Self-RAG"}})
[turn 2] 최종 답변(stop_reason=end_turn)
'Self-RAG 는 무엇과 연결돼 있나?' 에 대한 답: ... [e-reflection-token] [e-agentic-rag]

--- 요약 ---
tool_calls : ['graph_query']
```

스키마 타당성 질문 → `ontology_check` 가 방향 위반을 잡는다:

```bash
python agent_loop.py "Component 이 Method 를 USES 하는 관계는 스키마상 타당한가?"
```

예상 출력(발췌):

```
[turn 1] tool_use → ontology_check({"triples": [{"subject": "Component", "relation": "USES", "object": "Method"}]})
[turn 2] 최종 답변(stop_reason=end_turn)
'...' 에 대한 답: ... (스키마 위반이 발견돼 해당 관계는 답에서 제외) [근거 없음]
```

**헬스체크**: 첫 질문은 `graph_query` 를, 둘째 질문은 `ontology_check` 를 골라 부르고, 방향이 거꾸로인 관계 질문에는 "스키마 위반이 발견돼 해당 관계는 답에서 제외"가 붙어야 한다. 도구 목록이 3개로 뜨는지도 확인한다.

## (선택) 실전 경로 — Neo4j read-only 권한(3번째 방어선)

Guard·execute_read 를 뚫어도 DB 계정에 쓰기 롤이 없으면 아무 것도 못 바꾼다. 하니스 전용 읽기 계정을 만든다(Neo4j 5.26 LTS, cypher-shell):

```cypher
CREATE ROLE reader IF NOT EXISTS;
GRANT MATCH {*} ON GRAPH neo4j TO reader;
GRANT TRAVERSE ON GRAPH neo4j TO reader;
CREATE USER harness SET PASSWORD 'change-me' CHANGE NOT REQUIRED;
GRANT ROLE reader TO harness;
```

그 뒤 `NEO4J_USER=harness` 로 접속하면 `CREATE`/`DELETE` 는 권한 오류로 막힌다. 이게 3중 방어선의 마지막 겹이다.
