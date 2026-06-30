# 3.1 Neo4j Fundamentals — LPG·트랜잭션·Python Driver·인덱스·GDS 개요

> **Phase 3 · 토픽 01** · Phase 2가 남긴 JSONL 스냅샷 그래프를 실제 Neo4j로 옮기기 위한 기초를 깐다. LPG 모델을 이해하고, Python Driver로 연결하고, MERGE로 idempotent 적재를 검증한다.

## 학습 목표

이 토픽을 끝내면 다음을 할 수 있다.

- Neo4j 5.26을 Docker로 띄우고 Python Driver로 연결해 헬스체크한다.
- 속성 그래프(Labeled Property Graph, LPG)의 4요소로 코퍼스 엔티티·관계를 모델링한다.
- 관리형 트랜잭션과 MERGE로 노드·관계를 idempotent하게 적재하고, 두 번 넣어도 수가 안 늘어남을 확인한다.
- `canonical_id` 유니크 제약(Constraint)과 조회 인덱스(Index)를 만들고 `SHOW`로 검증한다.
- GDS가 무엇인지 파악하고 `gds.version()`으로 플러그인이 살아있는지 확인한다.

**완료 기준**: `docker compose up`으로 Neo4j 5.26이 뜨고, Python Driver로 연결·MERGE한 노드가 Browser에 보이며, 같은 적재 스크립트를 두 번 실행해도 노드·관계 수가 늘지 않으면(idempotent) 완료.

---

## 1. 왜 LPG/Neo4j인가 — 동기

Phase 1의 Vector RAG는 "비슷한 청크"를 잘 찾는다. 하지만 "LightRAG가 쓰는 그래프 DB를 만든 곳은 어디인가" 같은 질문에는 약하다. 답이 한 청크에 모여 있지 않고 `LightRAG → USES → Neo4j → MADE_BY → Neo4j Inc.` 처럼 관계를 두세 번 타고 가야 나오기 때문이다. 이게 멀티홉(multi-hop)이다. 임베딩 유사도는 홉을 못 센다.

Phase 2에서 우리는 그래프를 JSONL로 만들었다. `normalized_relations.jsonl`에 `head/type/tail`이 들어 있고, `graph_store.py`가 MERGE·version·tombstone 의미론을 흉내 냈다. 딱 거기까지가 시뮬레이션의 한계다. JSONL 파일로는 멀티홉 경로를 질의할 수 없다. `(a)-[:USES]->(b)<-[:USES]-(c)` 같은 패턴을 찾으려면 그래프 탐색 코드를 직접 짜야 하고, 동시 적재·트랜잭션·인덱스도 전부 손으로 떠받쳐야 한다.

여기서 무너진다. 그래서 진짜 그래프 DB가 필요하다. Neo4j는 관계를 1급 시민으로 다루고, 경로 패턴을 Cypher 한 줄로 질의하며, 트랜잭션·인덱스·제약을 엔진이 보장한다. Phase 2가 JSONL로 흉내 낸 MERGE 의미론이 여기서는 엔진 기능 그대로다.

이 토픽이 그 다리 역할을 한다. 대량 적재(전체 그래프를 UNWIND 배치로 넣기)는 다음 토픽 02로 미루고, 여기서는 연결·LPG 이해·소수 노드 MERGE 맛보기·제약/인덱스·트랜잭션·GDS 개요까지만 간다.

> 이 토픽은 LLM·임베딩 API를 쓰지 않는다. 순수 그래프 DB 기초다. Neo4j는 로컬에서 무료(Community Edition)로 돌고 API 키도 필요 없다. 비용 분기 고민이 없는 몇 안 되는 토픽이다.

## 2. LPG 모델 — 4요소

Neo4j의 데이터 모델은 속성 그래프(LPG)다. 네 가지만 알면 된다.

- **노드(Node)**: 사물. 우리 코퍼스에서는 엔티티 — LightRAG, Neo4j, RAG.
- **관계(Relationship)**: 노드와 노드를 잇는 방향 있는 엣지. `USES`, `IMPROVES`. 관계 자체에도 속성을 붙일 수 있다.
- **속성(Property)**: 노드나 관계에 달린 키-값. `name: 'LightRAG'`, `canonical_id: 'ent-model-lightrag'`.
- **라벨(Label)**: 노드의 타입표. `:Entity`, `:Model`. 한 노드에 여러 라벨을 붙일 수 있다.

RDF triple과 비교하면 차이가 한 줄로 정리된다. RDF는 모든 걸 `(주어, 술어, 목적어)` 삼중항으로 쪼개고 속성도 또 다른 삼중항이다. 반면 LPG는 노드·관계에 속성을 통째로 붙여 다룬다 — 개발자 입장에선 JSON 객체에 가깝고 다루기가 직관적이다.

코퍼스 예시를 하나 보자. Phase 2의 `LightRAG --USES--> Neo4j`를 LPG로 쓰면 이렇게 된다.

```cypher
(:Entity:Model {name: 'LightRAG', canonical_id: 'ent-model-lightrag'})
  -[:USES]->
(:Entity:Tool {name: 'Neo4j', canonical_id: 'ent-tool-neo4j'})
```

`:Entity`는 모든 엔티티가 공유하는 라벨(제약·조회의 기준)이고, `:Model`·`:Tool`은 Phase 2의 `type` 필드를 라벨로 옮긴 것이다. `canonical_id`는 Phase 2에서 엔티티 해소가 부여한 표준 식별자로, 이게 Neo4j에서 노드의 유니크 키가 된다.

## 3. Neo4j 띄우기 — docker-compose

핵심 조각만 본다. 전체는 [`practice/docker-compose.yml`](practice/docker-compose.yml).

```yaml
services:
  neo4j:
    image: neo4j:5.26              # 5.26 LTS. 2025+ CalVer(YYYY.MM)로 올려도 동작
    ports:
      - "7474:7474"               # HTTP — Neo4j Browser(웹 UI)
      - "7687:7687"               # Bolt — Driver가 쓰는 프로토콜
    environment:
      - NEO4J_AUTH=neo4j/testpassword1          # 초기 계정. 첫 로그인 강제변경 회피
      - NEO4J_PLUGINS=["graph-data-science"]    # GDS 플러그인 활성화
    volumes:
      - neo4j_data:/data           # 볼륨 없으면 컨테이너 지울 때 데이터 증발
volumes:
  neo4j_data:
```

포트가 둘인 게 핵심이다. **7474는 사람이 브라우저로 보는 HTTP**, **7687은 코드가 붙는 Bolt**. Driver에는 항상 `bolt://...:7687`을 준다(7474를 주면 연결이 안 된다 — 흔한 실수다). `NEO4J_AUTH`로 비밀번호를 미리 박아 두면 첫 접속 때 강제 변경 화면을 만나지 않는다. 볼륨은 빼먹지 마라. 없으면 컨테이너를 지우는 순간 그래프가 통째로 날아간다.

## 4. Python Driver 연결

패키지는 `neo4j`다. 드라이버는 한 번 만들어 앱 전체가 공유하고, 끝날 때 닫는다. 키는 환경변수에서 읽는다. 전체는 [`practice/connect.py`](practice/connect.py).

```python
import os
from neo4j import GraphDatabase

URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
AUTH = (
    os.environ.get("NEO4J_USER", "neo4j"),
    os.environ.get("NEO4J_PASSWORD", "testpassword1"),
)

# 드라이버는 애플리케이션당 하나. 연결 풀을 내부에서 관리한다.
with GraphDatabase.driver(URI, auth=AUTH) as driver:
    driver.verify_connectivity()                 # 연결 안 되면 여기서 예외

    # execute_query: 세션·트랜잭션·재시도를 드라이버가 알아서 처리하는 권장 API
    records, summary, keys = driver.execute_query("RETURN 'pong' AS msg")
    print(records[0]["msg"])                      # -> pong
```

`execute_query()`가 공식 권장 진입점이다(드라이버 5.14에서 안정화). 세션 열고 닫기, 트랜잭션 묶기, 일시적 오류 재시도를 다 알아서 한다. 세션을 직접 만지는 경우는 다음 절에서 다룬다.

## 5. 트랜잭션과 MERGE — idempotent 적재

적재에는 두 길이 있다.

`driver.execute_query()`는 자동이다. 한 방 쿼리에는 이걸 쓴다. 더 세밀하게 제어하고 싶으면 세션을 열어 **관리형 트랜잭션**을 쓴다 — `session.execute_write(fn)`과 `session.execute_read(fn)`. 넘긴 함수 안에서 여러 쿼리를 한 트랜잭션으로 묶고, 일시적 실패가 나면 트랜잭션 전체를 자동 재시도하며, 함수가 끝나면 커밋한다(예외가 나면 롤백). 원자성과 재시도를 공짜로 얻는 길이다.

핵심은 MERGE다. Phase 2 `graph_store.py`가 흉내 낸 "같은 키면 새로 안 만들고 누적" 의미론이 여기서는 Cypher 키워드 하나로 끝난다.

- `CREATE`는 무조건 새로 만든다. 두 번 실행하면 노드가 둘이 된다.
- `MERGE`는 패턴이 있으면 찾고, 없으면 만든다. 키를 잡아 두면 두 번 실행해도 하나다.

`practice/transactions.py`의 적재 함수 핵심.

```python
# practice/transactions.py 의 핵심 부분
def upsert_entity(tx, ent: dict):
    # canonical_id 를 키로 MERGE — 같은 id 면 노드를 재사용(idempotent)
    # ON CREATE 는 처음 만들 때만, SET 은 매번 최신 속성으로 갱신
    tx.run(
        """
        MERGE (n:Entity {canonical_id: $canonical_id})
        ON CREATE SET n.created = timestamp()
        SET n.name = $name, n.type = $type
        """,
        canonical_id=ent["canonical_id"], name=ent["name"], type=ent["type"],
    )

def upsert_relation(tx, head_id: str, rel_type: str, tail_id: str):
    # 양 끝 노드를 MERGE 로 보장한 뒤 관계도 MERGE — (head,type,tail) 가 키
    # 관계 타입은 파라미터로 못 넣어 f-string. rel_type 은 코드가 통제하는 값만 허용
    tx.run(
        f"""
        MERGE (h:Entity {{canonical_id: $head_id}})
        MERGE (t:Entity {{canonical_id: $tail_id}})
        MERGE (h)-[r:{rel_type}]->(t)
        ON CREATE SET r.created = timestamp()
        """,
        head_id=head_id, tail_id=tail_id,
    )
```

적재는 `execute_write`로 부른다.

```python
with driver.session() as session:
    for ent in entities:
        session.execute_write(upsert_entity, ent)
    for rel in relations:
        session.execute_write(upsert_relation, rel["head_id"], rel["type"], rel["tail_id"])
```

읽기는 `execute_read`.

```python
def count_graph(tx):
    rec = tx.run(
        "MATCH (n:Entity) "
        "OPTIONAL MATCH ()-[r]->() "
        "RETURN count(DISTINCT n) AS nodes, count(r) AS rels"
    ).single()
    return rec["nodes"], rec["rels"]
```

스크립트는 적재를 두 번 연속 돌리고 두 번 다 카운트를 찍는다. MERGE가 제대로 걸렸으면 두 카운트가 같다. 이게 완료 기준이다.

## 6. 인덱스와 제약 — 적재 전에 건다

`canonical_id`로 노드를 찾는 일이 앞으로 수만 번 일어난다(매 MERGE가 곧 조회다). 인덱스가 없으면 그때마다 전체 노드를 훑는다(full scan) — 적재가 노드 수의 제곱으로 느려진다.

유니크 제약(Constraint)을 먼저 건다. 전체는 [`practice/indexes.cypher`](practice/indexes.cypher).

```cypher
-- canonical_id 는 엔티티당 하나뿐이어야 한다. 제약이 그걸 강제하고
-- 동시에 백킹 인덱스를 자동 생성해 MERGE 조회를 빠르게 만든다.
CREATE CONSTRAINT entity_canonical_id IF NOT EXISTS
FOR (n:Entity) REQUIRE n.canonical_id IS UNIQUE;
```

이 한 줄이 두 가지를 동시에 한다. `canonical_id` 중복을 엔진이 막아 주고(Phase 2 엔티티 해소가 보장한 "id 하나당 엔티티 하나"가 DB에서도 불변이 된다), MERGE가 쓰는 조회용 인덱스를 깔아 준다. **제약은 대량 적재 전에 거는 게 정석이다.** 적재가 끝난 뒤 걸면 그 시점에 이미 들어간 중복 때문에 제약 생성 자체가 실패한다.

이름으로만 찾는 보조 인덱스도 하나 둔다.

```cypher
-- name 으로 조회·디버깅할 때 가속(유니크는 아니므로 일반 인덱스)
CREATE INDEX entity_name IF NOT EXISTS FOR (n:Entity) ON (n.name);
```

확인은 `SHOW`로 한다.

```cypher
SHOW CONSTRAINTS;
SHOW INDEXES;
```

## 7. GDS 개요 — 지금은 살아있는지만 본다

GDS(Graph Data Science)는 Neo4j 위에서 PageRank·커뮤니티 탐지 같은 그래프 알고리즘을 돌리는 라이브러리다. 작동 방식의 핵심 직관은 이렇다. 디스크 그래프를 그대로 돌리지 않고, 분석할 부분만 메모리로 떠 올린 **graph projection**을 만든 뒤 그 위에서 알고리즘을 실행한다. 빠르고, 원본을 안 건드린다.

이 토픽은 알고리즘을 돌리지 않는다. 플러그인이 제대로 붙었는지만 확인한다.

```cypher
RETURN gds.version() AS version;     -- 버전이 찍히면 플러그인 활성화 성공
```

PageRank(중요 노드 찾기)와 Leiden(커뮤니티 탐지)을 실제로 돌리는 건 토픽 06(`06-gds-pagerank-leiden`)이다. 여기서는 "GDS가 무엇이고, projection이라는 개념이 있고, 우리 컨테이너에서 살아있다"까지만 챙긴다. 파이썬에서 GDS를 쓰는 `graphdatascience` 클라이언트도 있지만 설치는 06에서 다룬다.

---

## 🚨 자주 하는 실수

1. **Driver에 7474(HTTP)를 준다** — Browser 주소(`http://localhost:7474`)를 그대로 드라이버 URI로 넣고 "연결이 안 된다"고 한다. 코드가 붙는 건 Bolt 포트 **7687**이다. 드라이버 URI는 항상 `bolt://localhost:7687`(또는 `neo4j://...`). 7474는 사람이 웹 UI로 들어가는 문이지 프로토콜이 다르다.
2. **제약 없이 MERGE해서 중복이 폭증한다** — `canonical_id`에 유니크 제약을 안 건 채 대량 MERGE를 돌리면, 인덱스가 없어 조회가 full scan으로 느려지는 데다 동시 적재 시 같은 id 노드가 둘씩 생기기도 한다. 적재 시작 전에 `CREATE CONSTRAINT ... IS UNIQUE`부터 건다. 제약이 백킹 인덱스까지 깔아 준다.
3. **MERGE 대신 CREATE로 적재해 idempotent가 깨진다** — 스크립트를 재실행하거나 재시도가 한 번 끼면 노드·관계가 두 배로 불어난다. 키(`canonical_id`, `(head,type,tail)`)로 MERGE하고, 적재를 두 번 돌려 카운트가 그대로인지 반드시 확인한다. 카운트가 늘면 어딘가 MERGE가 아니라 CREATE이거나 키가 잘못 잡힌 것이다.
4. **볼륨을 안 붙여 데이터가 날아간다** — `docker-compose.yml`에 `volumes`를 빼면 `docker compose down`이나 컨테이너 재생성 한 번에 그래프가 통째로 증발한다. `neo4j_data:/data` 볼륨을 반드시 붙인다.

## 출처

- Neo4j 공식 문서 — https://neo4j.com/docs/
- Neo4j Python Driver Manual — https://neo4j.com/docs/python-manual/current/
- Neo4j GDS Manual — https://neo4j.com/docs/graph-data-science/current/
- Neo4j 벡터 인덱스(시맨틱 인덱스) — https://neo4j.com/docs/cypher-manual/current/indexes/semantic-indexes/vector-indexes/

## 다음 토픽

→ [Bulk Ingest & MERGE](../02-bulk-ingest-merge/lesson.md)
