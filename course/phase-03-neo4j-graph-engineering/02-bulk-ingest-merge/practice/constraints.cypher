// 제약(Constraint) + 인덱스 — 대량 적재 "전에" 먼저 실행한다.
//
// 왜 먼저인가:
//   - 유니크 제약은 백킹 인덱스를 자동으로 깔아, 적재 중 MERGE 의 키 조회를 빠르게 만든다.
//   - 적재 "후" 에 걸면, 이미 들어간 중복 때문에 제약 생성이 실패한다.
//   - ingest_bulk.py 도 적재 직전에 이 3개 구문을 코드로 한 번 더 실행한다(이중 안전장치).
//
// 전제: Neo4j 5.26 기동 중.
// 실행(둘 중 하나):
//   1) Browser(http://localhost:7474) 에 붙여넣고 실행
//   2) cypher-shell:
//      cat constraints.cypher | docker exec -i kb-neo4j cypher-shell -u neo4j -p testpassword1

// 1) Entity 의 canonical_id 유니크 제약.
//    - Phase 2 엔티티 해소가 보장한 "id 하나당 엔티티 하나" 를 DB 에서도 강제한다.
CREATE CONSTRAINT entity_canonical_id IF NOT EXISTS
FOR (n:Entity) REQUIRE n.canonical_id IS UNIQUE;

// 2) Event 의 event_id 유니크 제약.
//    - 이벤트도 키 하나당 노드 하나. 재적재 시 같은 이벤트가 둘로 갈라지지 않게 한다.
CREATE CONSTRAINT event_id IF NOT EXISTS
FOR (e:Event) REQUIRE e.event_id IS UNIQUE;

// 3) name 조회 가속용 보조 인덱스(3/01 에서 이어받음).
//    - 유니크가 아니다(동명 엔티티가 있을 수 있어 일반 인덱스).
CREATE INDEX entity_name IF NOT EXISTS
FOR (n:Entity) ON (n.name);

// 확인 — 제약과 인덱스가 생겼는지 본다.
SHOW CONSTRAINTS;
SHOW INDEXES;
