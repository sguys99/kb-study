# 7.3 Cypher Safety Guard + ontology_check Tool

> **Phase 7 · 토픽 03** · text2cypher 가 만든 Cypher 를 실행 전에 막는 안전 가드와, 스키마 위반을 잡는 세 번째 도구를 완성한다.

## 학습 목표

이 토픽을 끝내면 다음을 할 수 있다.

- LLM 이 생성한 Cypher 를 실행 전에 정적 검사하는 Safety Guard 를 만들고, 쓰기·다중구문·무한 트래버설을 거부 사유와 함께 차단한다.
- 정적 Guard → `execute_read` → Neo4j read-only 권한으로 이어지는 3중 방어선을 코드와 운영 설정으로 구분해 설명한다.
- 라벨·관계 타입·방향을 허용 온톨로지와 대조하는 `ontology_check` 도구를 세 번째 하니스 도구로 등록해, 도구를 3개(docs_search / graph_query / ontology_check)로 확장한다.

**완료 기준**: 쓰기·다중구문 Cypher 를 Safety Guard 가 거부 사유와 함께 차단하고, 스키마에 없는 관계 타입을 ontology_check 가 위반으로 잡아내며, 에이전트가 세 도구(docs_search/graph_query/ontology_check)로 안전하게 답하면 완료.

---

## 1. 왜 필요한가 — 02 가 남긴 구멍

02 에서 `graph_query` 의 `text2cypher` 경로를 만들었다. 자연어를 받아 LLM 이 Cypher 를 생성하고, `execute_read` 로 읽기 전용 실행까지 이었다. 그런데 02 코드에는 이런 주석이 달려 있었다.

```python
# graph_query.py (02) 中
# ⚠️ 여기서는 생성된 Cypher 를 '그대로' 실행할 위험이 남아 있다.
#    쓰기 차단·주입 방어·화이트리스트 검증은 03-cypher-safety-ontology-check 에서 완성한다.
```

LLM 은 실수하고, 프롬프트는 주입당한다. "이 관계를 삭제해줘" 같은 입력이 `MATCH (n) DETACH DELETE n` 을 만들 수 있고, 답변에 세미콜론을 끼워 두 번째 구문을 밀어 넣을 수도 있다. `execute_read` 가 쓰기 트랜잭션을 막긴 하지만, 안전을 그것 하나에 걸어두는 건 얇다. 무한 트래버설(`[*]`)로 DB 를 마비시키는 건 읽기 전용 안에서도 가능하다.

그래서 방어선을 둘 세운다. 실행 전에 Cypher 문자열을 검사하는 **Safety Guard**, 그리고 라벨·관계가 스키마에 맞는지 보는 **ontology_check**.

## 2. 방어선은 한 겹이 아니다 — 3중 구조

안전은 한 지점에 몰아넣지 않는다. 겹친다(defense in depth).

1. **정적 Safety Guard** — 실행 전에 Cypher 문자열을 검사. 쓰기 키워드·다중구문·`LOAD CSV`·위험 프로시저·무상한 경로를 거부하고, `LIMIT` 이 없으면 강제로 붙인다. 이 토픽의 코드.
2. **`execute_read`** — 02 의 `Neo4jBackend.run_read` 가 읽기 전용 트랜잭션 함수로만 실행한다. 쓰기 트랜잭션을 아예 노출하지 않는다.
3. **Neo4j read-only 사용자 권한** — DB 계정 자체에 쓰기 롤이 없으면, 앞의 둘을 다 뚫어도 아무 것도 못 바꾼다. 코드가 아니라 운영 설정이다.

**정적 Guard 는 완벽한 파서가 아니다.** 정규식 deny-list 는 실수를 대부분 걸러 비용과 사고를 줄이는 1차 필터일 뿐, 최종 방어선은 (3) DB 권한이다. 이 한계를 분명히 알고 세 겹으로 겹치는 게 실전이다.

## 3. 실습 (1) — Cypher Safety Guard

`is_safe(cypher)` 하나가 관문이다. 위험하면 `(safe=False, reason)`, 통과하면 `(safe=True, cypher=보강본)` 을 돌려준다. 검사는 가장 위험한 것부터 순서대로 건다.

```python
# practice/cypher_safety.py 의 핵심 — 실행 전 정적 검사
def is_safe(cypher: str) -> SafetyResult:
    if not cypher or not cypher.strip():
        return SafetyResult(safe=False, reason="빈 Cypher")

    # 문자열 리터럴을 지운 사본에서만 검사한다.
    # name:'CREATE THE FUTURE' 의 'CREATE' 를 키워드로 오탐하지 않기 위해서다.
    scrubbed = _strip_string_literals(cypher)

    if _count_statements(scrubbed) > 1:                     # 세미콜론 다중구문
        return SafetyResult(safe=False, reason="다중 구문 금지: ...")
    kw = _has_write_keyword(scrubbed)                       # CREATE/MERGE/DELETE/SET/REMOVE/DROP...
    if kw:
        return SafetyResult(safe=False, reason=f"쓰기/부작용 키워드 금지: {kw!r} 발견")
    proc = _has_dangerous_proc(scrubbed)                    # apoc.create.*, dbms.*, db.create...
    if proc:
        return SafetyResult(safe=False, reason=f"위험 프로시저 금지: {proc!r} 발견")
    if _CALL_SUBQUERY.search(scrubbed):                     # CALL {...} 안에 쓰기 은닉
        return SafetyResult(safe=False, reason="CALL {...} 서브쿼리 금지")
    # ... 읽기 진입점(MATCH 등) 강제 ...
    vl = _var_length_violation(scrubbed)                    # [*], [*..99] 같은 무한/과대 경로
    if vl:
        return SafetyResult(safe=False, reason=vl)

    # 통과: LIMIT 이 없으면 강제로 붙여 결과 폭주를 막는다.
    return SafetyResult(safe=True, cypher=_ensure_limit(cypher, scrubbed))
```

몇 가지 함정은 코드로 미리 막았다. `_strip_string_literals` 는 따옴표 속 값을 지운 사본에서만 키워드를 찾는다. `_WRITE_KEYWORDS` 는 단어 경계(`\b`)로 매칭해 `CREATED_BY` 같은 관계 이름을 오탐하지 않는다. `MAX_HOPS=5` 로 가변 길이 경로 상한을 강제하고, 상한이 아예 없는 `[*]` 는 거부한다.

이 Guard 를 02 의 `text2cypher` 경로에 끼운다. `graph_query_safe.py` 는 02 를 통째로 다시 짜지 않고, 그 경로만 감싼다.

```python
# practice/graph_query_safe.py 의 핵심 — 생성 → Guard → 통과 시에만 실행
def _run_text2cypher_safe(question: str) -> list[dict]:
    cypher = gq02._generate_cypher(question)   # 02 의 생성기 그대로 재사용
    verdict = is_safe(cypher)
    if not verdict.safe:
        # 실행하지 않는다. 거부 사유를 돌려줘 에이전트가 질의를 고치게 한다.
        return [{"generated_cypher": cypher, "blocked": True, "reason": verdict.reason}]
    safe_cypher = verdict.cypher or cypher     # LIMIT 이 보강됐을 수 있는 최종본
    rows = gq02._GRAPH.run_read(safe_cypher, {})  # (2) execute_read 로 읽기 전용 실행
    return [{"generated_cypher": cypher, "safe_cypher": safe_cypher, "blocked": False}, *rows]
```

template·lightrag 경로는 02 를 그대로 위임한다. 바뀌는 건 `text2cypher` 실행 앞단뿐이다.

## 4. 실습 (2) — ontology_check 도구

Safety Guard 는 "이 Cypher 가 위험한가"를 본다. `ontology_check` 는 다른 질문에 답한다 — "이 라벨·관계가 스키마상 타당한가". 둘은 겹치지 않는다. 안전한 읽기 질의라도 스키마에 없는 `:Dataset` 라벨이나 `[:MENTIONS]` 관계를 쓰면 잘못된 답으로 이어진다.

기준은 `ontology.yaml`(허용 라벨·관계·방향)이다. Phase 5(5/02 controlled-vocabulary, 5/04 constraint-validation-shacl)의 어휘·제약을 하니스 그래프에 맞춰 축약해 옮겼다. 로더 `ontology.py` 는 5/02 의 `controlled_vocabulary.py` 패턴(Pydantic 검증 + `normalize` + 색인)을 그대로 잇는다.

```python
# practice/ontology_check.py 의 핵심 — Cypher/삼중항을 허용 온톨로지와 대조
def ontology_check(cypher: str | None = None, triples: list[dict] | None = None) -> dict:
    violations = []
    if cypher:
        for lab in _extract_labels_from_cypher(cypher):      # (:Method), (:Dataset)...
            if _ONTOLOGY.resolve_label(lab) is None:
                violations.append({"kind": "unknown_label", "item": lab, "reason": ...})
        for rel in _extract_relations_from_cypher(cypher):   # [:USES], [:MENTIONS]...
            if _ONTOLOGY.resolve_relation(rel) is None:
                violations.append({"kind": "unknown_relation", "item": rel, "reason": ...})
    if triples:
        for t in triples:
            # 관계 존재 + 방향(domain/range)까지 본다.
            # (Component)-[USES]->(Method) 는 방향 위반 — USES 는 Method->Component 여야 한다.
            v = _check_triple(t["subject"], t["relation"], t["object"])
            if v:
                violations.append(v)
    return {"ok": len(violations) == 0, "checked": {...}, "violations": violations}
```

위반은 세 종류다. `unknown_label`(허용 라벨 밖), `unknown_relation`(허용 관계 밖), `direction_violation`(관계는 있으나 domain/range 방향이 어긋남). 방향 검사가 핵심이다. `USES` 가 온톨로지에 있어도 `(Component)-[:USES]->(Method)` 는 방향이 거꾸로라 위반이다.

세 도구를 한 레지스트리에 등록하면 도구가 3개가 된다. 01 의 `Tool/ToolRegistry`, 02 의 등록 규약을 그대로 잇는다.

```python
# practice/register_all_tools.py 의 핵심 — 도구 3개
def build_registry_full():
    reg = build_registry()                       # 01: docs_search
    reg.register(Tool("graph_query", ..., fn=_run_graph_query_safe))   # 02 스키마 + 03 안전판 실행
    reg.register(Tool("ontology_check", ..., fn=ontology_check))       # 03: 세 번째 도구
    return reg
```

> 전체 코드와 실행 절차는 [`practice/`](practice/) 와 [`labs/`](labs/) 참조.
> 비용을 줄이려면 `text2cypher` 의 LLM 생성을 Ollama 로, 임베딩을 `bge-m3` 로 바꿔도 된다(stack-conventions 규약). Safety Guard·ontology_check 자체는 API 키 없이 표준 라이브러리 + Pydantic 만으로 돈다.

## 5. 결과 해석

`python cypher_safety.py` 를 돌리면 위험/정상 케이스가 한 번에 나온다.

```
[BLOCK] 위험: MATCH 뒤 DELETE
        입력 : MATCH (n:Method) DETACH DELETE n
        사유 : 쓰기/부작용 키워드 금지: 'DETACH' 발견
[PASS ] 정상: LIMIT 없음(보강됨)
        입력 : MATCH (n:Method) RETURN n.name
        실행 : MATCH (n:Method) RETURN n.name LIMIT 50
```

`DETACH DELETE` 는 실행조차 못 하고 사유가 붙어 거부된다. `LIMIT` 이 없던 정상 질의에는 `LIMIT 50` 이 자동으로 붙어 나간다. 이 두 줄이 Guard 가 하는 일의 전부다 — 위험한 건 막고, 안전한 건 결과 폭주만 눌러 통과시킨다.

`ontology_check` 로 위반 Cypher 를 검사하면 라벨·관계가 왜 안 되는지 리포트가 나온다.

```
위반 Cypher: MATCH (m:Method)-[:MENTIONS]->(d:Dataset) RETURN m,d LIMIT 10
{ "ok": false,
  "violations": [
    { "kind": "unknown_relation", "item": "MENTIONS", "reason": "온톨로지에 없는 관계 타입: 'MENTIONS'. 허용: [BUILT_ON, EXTENDS, IMPLEMENTS, IS_A, USES]" },
    { "kind": "unknown_label", "item": "Dataset", "reason": "온톨로지에 없는 라벨: 'Dataset'. ..." } ] }
```

`ok=false` 와 함께 무엇이 왜 틀렸는지 나온다. 에이전트는 이걸 보고 질의를 고치거나 그 관계를 답에서 뺀다. 이게 "스키마에 없는 관계를 잡아낸다"의 실체다.

---

## 🚨 자주 하는 실수

1. **문자열 리터럴 속 키워드를 오탐한다** — `MATCH (n {name:'CREATE THE FUTURE'})` 의 `CREATE` 는 값이지 명령이 아니다. deny-list 를 원본에 그냥 걸면 정상 질의를 막는다. 검사는 반드시 따옴표 속을 지운 사본(`_strip_string_literals`)에서 한다. 반대로, 정규식만 믿고 DB 권한(3번 방어선)을 안 거는 것도 실수다. Guard 는 필터지 최종 방어선이 아니다.
2. **가변 길이 경로 상한을 잊는다** — 쓰기만 막으면 됐다고 생각하기 쉽다. 그런데 `MATCH p=(a)-[*]-(b)` 는 읽기 전용이어도 그래프 크기에 따라 폭발한다. 상한 없는 `[*]` 와 과대한 `[*..99]` 를 함께 거부하고, `LIMIT` 강제까지 걸어야 결과·비용이 통제된다.
3. **ontology_check 를 Safety Guard 와 같은 것으로 여긴다** — 둘은 다른 층이다. Safety Guard 는 "위험한가"(쓰기·주입·폭주), ontology_check 는 "스키마에 맞는가"(허용 라벨·관계·방향)를 본다. 안전한 읽기 질의라도 스키마에 없는 관계를 참조할 수 있으니, 방어와 검증을 한 도구에 뭉치지 말고 둘 다 둔다.

## 출처

- Neo4j Cypher Manual (읽기/쓰기 절, 가변 길이 경로): https://neo4j.com/docs/cypher-manual/current/
- Neo4j 권한·롤 관리(read-only role): https://neo4j.com/docs/operations-manual/current/authentication-authorization/
- Neo4j Python Driver (`execute_read`): https://neo4j.com/docs/api/python-driver/current/
- SHACL (그래프 제약 검증): https://www.w3.org/TR/shacl/ · pySHACL: https://github.com/RDFLib/pySHACL
- Pydantic (Structured Output·검증): https://docs.pydantic.dev/
- Anthropic Tool Use: https://docs.anthropic.com/en/docs/build-with-claude/tool-use

## 다음 토픽

→ [7.4 Adaptive / Corrective RAG (Router·Grader·Query Rewrite)](../04-adaptive-corrective-rag/lesson.md)
