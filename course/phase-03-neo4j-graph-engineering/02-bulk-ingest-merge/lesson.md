# 3.2 Bulk Ingest & MERGE — UNWIND·MERGE·Constraint

> **Phase 3 · 토픽 02** · Phase 2 가 만든 그래프(JSONL 3종)를 Neo4j 에 한 번에, 중복 없이, 몇 번을 돌려도 같은 결과로 적재한다.

## 학습 목표

이 토픽을 끝내면 다음을 할 수 있다.

- 대량 적재 전에 유니크 제약(Constraint)을 먼저 걸고, 그 이유를 설명한다.
- 파일 전체를 `UNWIND $rows` 배치 한 번으로 MERGE 적재한다(3/01 의 per-row 루프를 끌어올린다).
- 관계의 endpoint 이름을 `canonical_id` 로 해소하고, 표준 집합에 없는 이름은 fallback 노드로 처리한다.
- 관계 타입을 타입별 그룹핑으로 동적 적재한다(파라미터로 못 넣는 제약을 우회).
- 적재를 두 번 돌려 노드·관계·이벤트 카운트가 안 늘어남(idempotent)을 검증한다.

**완료 기준**: constraints 적용 후 `python ingest_bulk.py` 로 Phase 2 그래프가 Neo4j 에 들어가고, 다시 `python verify_idempotent.py` 를 돌려 노드·관계·이벤트 카운트가 1차와 동일하면 완료.

---

## 1. 왜 필요한가 — per-row 루프로는 안 된다

3/01 은 엔티티를 한 건씩 `execute_write` 루프로 MERGE 했다. 노드 다섯 개를 눈으로 확인하기엔 그걸로 충분했다. 다만 그 방식은 행마다 트랜잭션을 열고 닫으며, 행마다 네트워크를 한 번씩 왕복한다. Phase 2 그래프는 작지만, Phase 가 진행되면서 코퍼스가 수백·수천 건으로 불어나면 이 왕복 비용이 그대로 곱해진다.

해법은 단순하다. 행을 하나씩 보내는 대신 **리스트째로 한 번에 보낸다.** 파일 전체를 파이썬에서 `list[dict]` 로 읽어 파라미터 `$rows` 하나로 넘기고, Cypher 안에서 `UNWIND` 로 펼쳐 MERGE 한다. 트랜잭션도 왕복도 행 수만큼 줄어든다. 3/01 이 "대량 적재는 다음 토픽으로 미룬다"고 했던 게 바로 이 페이오프다.

적재 자체는 쉽다. 진짜 일은 **Phase 2 의 정제 결과를 적재 시점에 그대로 살리는 것**이다. 관계 endpoint 를 표준 식별자로 해소하고, 같은 스냅샷을 다시 넣어도 그래프가 불어나지 않게 만드는 일이다.

## 2. 제약 먼저 — 적재 전에 유니크를 건다

순서가 중요하다. 대량 MERGE 를 돌리기 **전에** 유니크 제약을 건다.

```cypher
-- practice/constraints.cypher
CREATE CONSTRAINT entity_canonical_id IF NOT EXISTS
FOR (n:Entity) REQUIRE n.canonical_id IS UNIQUE;

CREATE CONSTRAINT event_id IF NOT EXISTS
FOR (e:Event) REQUIRE e.event_id IS UNIQUE;

CREATE INDEX entity_name IF NOT EXISTS
FOR (n:Entity) ON (n.name);   -- 3/01 에서 이어받은 name 조회 가속 인덱스
```

제약이 두 가지를 해 준다. 첫째, 유니크 제약은 **백킹 인덱스를 자동으로 깔아** MERGE 의 키 조회를 빠르게 만든다. 인덱스가 없으면 MERGE 는 매번 라벨 전체를 훑는다(full scan). 둘째, 같은 `canonical_id` 노드가 둘 생기는 걸 엔진이 막는다.

적재 후에 걸면 늦다. 이미 중복이 들어가 있으면 제약 생성 자체가 실패한다. 그래서 `ingest_bulk.py` 도 적재 직전에 같은 구문을 코드로 한 번 더 실행한다(이중 안전장치).

## 3. UNWIND 배치 적재 + MERGE = idempotent upsert

파일 전체를 `$rows` 로 넘기고 `UNWIND` 로 펼친다. 행마다 MERGE.

```python
# practice/ingest_bulk.py 의 엔티티 적재 부분
def ingest_entities(tx, rows: list[dict]) -> None:
    tx.run(
        """
        UNWIND $rows AS row
        MERGE (n:Entity {canonical_id: row.canonical_id})
        ON CREATE SET n.created = timestamp()
        SET n.name = row.name,
            n.type = row.type,
            n.unresolved = coalesce(row.unresolved, false)
        """,
        rows=rows,    # 파이썬 list[dict] 하나를 파라미터로. 왕복 한 번.
    )
```

MERGE 는 upsert 다. `canonical_id` 가 같으면 노드를 새로 만들지 않고 재사용한다. `ON CREATE SET` 은 최초 생성 때 한 번 돌고, `SET` 은 매번 최신 속성으로 갱신한다. Phase 2/06 의 `graph_store.py` 가 손으로 흉내 냈던 "같은 키면 누적" 의미론이, 여기서는 엔진 기능 그대로다. 그래서 같은 파일을 두 번 적재해도 노드 수가 안 늘어난다.

## 4. 관계 적재 ① — endpoint 를 canonical_id 로 해소한다

여기가 이 토픽의 핵심 난점이다. `normalized_relations.jsonl` 을 다시 보자.

```json
{"head":"LightRAG","type":"USES","tail":"Neo4j", ...}
{"head":"CRAG","type":"USES","tail":"LangChain", ...}
```

`head`/`tail` 은 **이름**이다. 그런데 노드의 유니크 키는 `canonical_id` 다. 이름으로 관계를 MERGE 하면서 노드는 `canonical_id` 로 MERGE 하면, 같은 개체가 노드 둘로 갈라진다. 그래서 적재 전에 `entities` 파일로 `name -> canonical_id` 맵을 만들어 endpoint 를 해소한다. Phase 2 엔티티 해소(Entity Resolution) 결과를 **적재 시점에 적용**하는 셈이다. 별칭(aliases)도 같은 맵에 넣어 별칭으로 들어온 endpoint 까지 해소한다.

문제는 `"LangChain"` 이다. 관계에는 나오는데 entities 파일에는 없다. 표준 엔티티 집합에 아직 없는 endpoint 인데, 현업에서 흔히 마주친다. 이런 미해소 이름은 버리지 않고 **결정적 fallback id** 를 부여해 노드로 넣고 플래그를 단다.

```python
# practice/ingest_bulk.py
def slugify_unresolved(name: str) -> str:
    # 같은 이름이면 항상 같은 id → 재적재가 idempotent.
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return f"ent-unresolved-{slug}"        # "LangChain" → "ent-unresolved-langchain"

def resolve_endpoint(name, name2id, unresolved):
    if name in name2id:
        return name2id[name]
    fallback = slugify_unresolved(name)
    unresolved.setdefault(fallback, {"canonical_id": fallback, "name": name, "unresolved": True})
    return fallback
```

이렇게 하면 (a) `canonical_id` 단일 유니크 키가 유지되고, (b) 슬러그가 결정적이라 재적재가 idempotent 하며, (c) `n.unresolved = true` 로 나중에 보강 대상을 골라낼 수 있다. 나중에 LangChain 이 표준 엔티티로 승격되면 그 노드만 찾아 합치면 된다.

## 5. 관계 적재 ② — 타입은 파라미터로 못 넣는다

Cypher 에서 관계 타입은 파라미터가 안 된다. `MERGE (h)-[r:$type]->(t)` 는 문법 오류다. 타입은 쿼리 구조의 일부라 실행 전에 고정돼야 한다.

기본 경로는 **타입별 그룹핑**이다. 관계를 타입으로 묶어, 타입 하나당 `UNWIND` 를 한 번씩 돈다. 타입 문자열은 코드가 통제하는 화이트리스트(`COMPARES_TO`, `DEVELOPED_BY`, `IMPROVES`, `USES`) 안의 값만 f-string 으로 박는다. 외부 입력을 그대로 박았다간 주입 위험이 생기기 때문이다.

```python
# practice/ingest_bulk.py
ALLOWED_REL_TYPES = {"COMPARES_TO", "DEVELOPED_BY", "IMPROVES", "USES"}

def ingest_relations_of_type(tx, rel_type: str, rows: list[dict]) -> None:
    if rel_type not in ALLOWED_REL_TYPES:        # 화이트리스트 검증 후에만 f-string.
        raise ValueError(f"허용되지 않은 관계 타입: {rel_type}")
    tx.run(
        f"""
        UNWIND $rows AS row
        MERGE (h:Entity {{canonical_id: row.head_id}})
        MERGE (t:Entity {{canonical_id: row.tail_id}})
        MERGE (h)-[r:{rel_type}]->(t)
        ON CREATE SET r.created = timestamp()
        SET r.source_ids = row.source_ids,
            r.provenance_count = row.provenance_count
        """,
        rows=rows,
    )
```

관계 MERGE 키는 `(head canonical_id, type, tail canonical_id)` 다. provenance 는 적재 전에 결정적으로 dedup 한다. `source_id` 기준으로 중복을 제거하고 정렬해 `r.source_ids`(리스트)와 `r.provenance_count`(정수)로 SET 한다. 정렬과 중복 제거가 결정적이라 같은 스냅샷을 다시 넣어도 동일한 리스트가 나온다.

> APOC 플러그인이 있으면 `apoc.merge.relationship(h, rel_type, {}, {}, t)` 한 줄로 동적 타입을 처리할 수도 있다. 다만 플러그인 의존이 늘어 기본 경로는 APOC 없이 group-by-type 으로 간다.
>
> 전체 코드와 실행 절차는 [`practice/`](practice/) 와 [`labs/`](labs/) 참조. 이 토픽은 LLM·임베딩 API 를 쓰지 않는다 — 로컬 Neo4j 만 쓰므로 API 키가 필요 없고 과금도 없다.

## 6. 이벤트 적재 — 노드로 idempotent 하게

이벤트도 같은 방식이다. `event_id` 를 키로 MERGE 하고 `type`·`time`·`value` 와 `roles` 의 평탄한 속성을 SET 한다. 여기에 더해, `roles.published_work` 를 entities 맵으로 해소할 수 있으면 `(:Event)-[:ABOUT]->(:Entity)` 한 줄을 연결한다. 우리 데이터의 두 이벤트는 `published_work` 가 각각 `RAG`·`GraphRAG` 라 둘 다 해소된다. 해소되지 않으면 ABOUT 을 생략한다.

```python
# practice/ingest_bulk.py — 이벤트 노드(ABOUT 엣지는 별도 함수)
def ingest_events(tx, rows: list[dict]) -> None:
    tx.run(
        """
        UNWIND $rows AS row
        MERGE (e:Event {event_id: row.event_id})
        ON CREATE SET e.created = timestamp()
        SET e.type = row.type, e.time = row.time, e.value = row.value,
            e.year = row.year, e.venue = row.venue
        """,
        rows=rows,
    )
```

## 7. idempotent 검증 — 두 번 돌려 카운트를 본다

적재가 끝나면 검증한다. `verify_idempotent.py` 는 `ingest_bulk.run()` 을 그대로 두 번 호출하고, 1차와 2차의 `(nodes, rels, events)` 가 같은지 비교한다. 다르면 어디가 늘었는지 찍고 비-0 으로 종료한다.

이번 데이터 기준으로 적재 후 카운트는 이렇다.

- **노드 14** = 엔티티 11 + 미해소(LangChain) 1 + 이벤트 2
- **관계 11** = 타입 관계 9(`USES` 2, `IMPROVES` 4, `COMPARES_TO` 1, `DEVELOPED_BY` 2) + `ABOUT` 2
- **이벤트 2**

1차와 2차가 둘 다 `nodes=14 rels=11 events=2` 면 통과다. 이 숫자가 안 늘어난다는 게 핵심이다. 같은 스냅샷을 재적재하거나 적재 중 재시도가 한 번 끼어도 그래프가 부풀지 않는다. MERGE 키와 결정적 dedup 이 그걸 보장한다.

---

## 🚨 자주 하는 실수

1. **제약 없이 대량 MERGE 를 돌린다** — `canonical_id` 유니크 제약을 안 건 채 적재하면 인덱스가 없어 MERGE 가 매번 full scan 으로 느려지고, 동시 적재 시 같은 id 노드가 둘 생기기도 한다. 적재 시작 전에 `CREATE CONSTRAINT ... IS UNIQUE` 부터 건다. 적재 후에 걸면 이미 들어간 중복 때문에 제약 생성이 실패한다.
2. **관계 타입을 파라미터로 넣으려 한다** — `MERGE (h)-[r:$type]->(t)` 는 동작하지 않는다. 타입은 쿼리 구조라 실행 전에 고정돼야 한다. 타입별로 그룹핑해 타입당 `UNWIND` 한 번씩 돌리되, 타입 문자열은 화이트리스트로 검증한 값만 f-string 으로 박는다(또는 APOC `apoc.merge.relationship`).
3. **endpoint 를 이름으로 MERGE 한다** — 관계는 이름(`"LightRAG"`)으로, 노드는 `canonical_id`(`ent-model-lightrag`)로 MERGE 하면 같은 개체가 노드 둘로 갈라진다. 적재 전에 반드시 `name -> canonical_id` 로 해소(reconcile)하고, 표준 집합에 없는 이름은 결정적 fallback id 로 노드를 만들어 `unresolved` 플래그를 단다.
4. **provenance dedup 이 비결정적이라 idempotent 가 깨진다** — `source_ids` 를 정렬·중복 제거 없이 그대로 SET 하면, 입력 순서가 흔들릴 때 같은 관계의 속성이 매번 달라진다. 카운트는 그대로여도 속성이 출렁이면 회귀 비교가 무너진다. dedup 은 항상 결정적으로(정렬 + set) 한다.

## 출처

- Neo4j 공식 문서 — https://neo4j.com/docs/
- Neo4j Python Driver Manual — https://neo4j.com/docs/python-manual/current/
- Neo4j Cypher Manual (MERGE / UNWIND / CONSTRAINT) — https://neo4j.com/docs/cypher-manual/current/
- (선택) APOC — https://neo4j.com/docs/apoc/current/

## 다음 토픽

→ [Cypher Query](../03-cypher-query/lesson.md)

