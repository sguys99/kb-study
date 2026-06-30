// 인덱스/제약 — 대량 적재 전에 먼저 건다.
//
// 전제: Neo4j 5.26 기동 중.
// 실행(둘 중 하나):
//   1) Browser(http://localhost:7474) 에 붙여넣고 한 줄씩 실행
//   2) cypher-shell:
//      cat indexes.cypher | docker exec -i kb-neo4j cypher-shell -u neo4j -p testpassword1

// 1) canonical_id 유니크 제약.
//    - Phase 2 엔티티 해소가 보장한 "id 하나당 엔티티 하나" 를 DB 에서도 강제.
//    - 제약은 백킹 인덱스를 자동 생성해 MERGE 조회를 빠르게 만든다.
//    - 반드시 대량 적재 "전" 에 건다. 적재 후 걸면 기존 중복 때문에 실패할 수 있다.
CREATE CONSTRAINT entity_canonical_id IF NOT EXISTS
FOR (n:Entity) REQUIRE n.canonical_id IS UNIQUE;

// 2) name 조회 가속용 보조 인덱스(유니크 아님 — 동명이 있을 수 있으므로 일반 인덱스).
CREATE INDEX entity_name IF NOT EXISTS
FOR (n:Entity) ON (n.name);

// 3) 확인 — 제약과 인덱스가 생겼는지 본다.
SHOW CONSTRAINTS;
SHOW INDEXES;
