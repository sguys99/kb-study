// 05 Query Tuning 용 제약·인덱스.
//
// 03/04 의 질의는 거의 다 (e:Entity {name: "..."}) 또는 canonical_id 로 시작점을 잡는다.
// 그런데 02 적재 단계는 name/canonical_id 에 인덱스를 만들지 않았다. 그래서 그 질의들은
// PROFILE 로 보면 NodeByLabelScan + Filter 로 풀린다(= Entity 라벨 전체를 훑고 name 을 거른다).
// 노드가 14 개뿐이면 안 느껴지지만, 수만~수백만 노드에선 그대로 병목이 된다.
//
// 아래 제약·인덱스를 추가하면 같은 질의가 NodeIndexSeek 으로 바뀌고 db hits 가 급감한다.
// profile_demo.py 가 추가 전/후를 PROFILE 로 대조해 보여준다.
//
// 실행 방법(둘 중 하나):
//   1) Neo4j Browser(http://localhost:7474)에 붙여넣고 한 문장씩 실행.
//   2) docker exec -i kb-neo4j cypher-shell -u neo4j -p testpassword1 < indexes_constraints.cypher
//
// 주의: 인덱스/제약 생성은 "쓰기" 다(스키마 변경). 가드를 거치지 않고 사람이 직접 적용하는 운영 작업이다.

// === 1) canonical_id 유니크 제약 ==========================================
// canonical_id 는 엔티티의 표준 식별자다. 유니크 제약은 (1) 중복 방지 + (2) 뒤에 깔리는
// range 인덱스를 같이 만들어 준다. canonical_id 등호 조회가 NodeIndexSeek 으로 풀린다.
CREATE CONSTRAINT entity_canonical_id IF NOT EXISTS
FOR (e:Entity) REQUIRE e.canonical_id IS UNIQUE;

// === 2) name range 인덱스 =================================================
// name 은 유니크가 아닐 수 있다(같은 이름 다른 엔티티 가능). 그래서 제약 대신 range 인덱스만 건다.
// (e:Entity {name: "..."}) / WHERE e.name = "..." / e.name STARTS WITH "..." 가 인덱스를 탄다.
CREATE INDEX entity_name IF NOT EXISTS
FOR (e:Entity) ON (e.name);

// === 3) type range 인덱스(선택) ===========================================
// type 별 필터(WHERE e.type = "Model")가 잦으면 같이 건다. 노드가 적으면 효과가 작다.
CREATE INDEX entity_type IF NOT EXISTS
FOR (e:Entity) ON (e.type);

// === 확인 =================================================================
// 추가한 제약·인덱스가 ONLINE 인지 점검. 04 의 entity_embedding/entity_fulltext 도 함께 보인다.
SHOW INDEXES YIELD name, type, state, labelsOrTypes, properties
RETURN name, type, state, labelsOrTypes, properties
ORDER BY name;

// 제약만 따로 보려면:
// SHOW CONSTRAINTS;
