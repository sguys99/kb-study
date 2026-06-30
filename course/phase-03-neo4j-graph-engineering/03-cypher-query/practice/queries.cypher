// Phase 3 / 03 — Cypher Query 모음 (패턴 매칭·멀티홉·경로·집계·Event)
//
// 대상: 02(bulk-ingest-merge)가 적재한 그래프. 새 데이터를 만들지 않는다.
//   - 노드 (:Entity {canonical_id, name, type, unresolved, created})  -- canonical_id 유니크, name 인덱스
//   - 노드 (:Event {event_id, type, time, value, year, venue, created})
//   - 관계 (Entity)-[:USES|IMPROVES|DEVELOPED_BY|COMPARES_TO]->(Entity)
//   - 관계 (:Event)-[:ABOUT]->(:Entity)
//   - 적재 카운트: nodes=14, rels=11(USES 2, IMPROVES 4, COMPARES_TO 1, DEVELOPED_BY 2, ABOUT 2), events=2
//
// 전제: Neo4j 5.26 기동 중. 02 적재 완료(python ingest_bulk.py).
// 실행(둘 중 하나):
//   1) Browser(http://localhost:7474)에 한 구문씩 붙여넣고 실행 (계정 neo4j / testpassword1)
//   2) cypher-shell 로 파일 통째 실행:
//      cat queries.cypher | docker exec -i kb-neo4j cypher-shell -u neo4j -p testpassword1
//
// 비용: 이 토픽은 LLM·임베딩 API를 쓰지 않는다. 키 불필요, 과금 없음(로컬 Neo4j만).


// ============================================================================
// (a) 패턴 매칭 — MATCH / WHERE / RETURN
// ============================================================================

// a-1) LightRAG 가 쓰는(USES) 도구. 방향을 head -> tail 로 정확히 그린다.
//      기대: LightRAG -> Neo4j
MATCH (a:Entity {name: "LightRAG"})-[:USES]->(b:Entity)
RETURN a.name AS user, b.name AS used;

// a-2) USES 관계 전체 중 tail 의 type 이 Tool 인 것만 (WHERE 로 거르기).
//      기대: LightRAG -> Neo4j (Neo4j 의 type 이 Tool)
MATCH (a:Entity)-[:USES]->(b:Entity)
WHERE b.type = "Tool"
RETURN a.name AS user, b.name AS tool;

// a-3) 라벨별 노드 개수 — 그래프 윤곽 보기.
//      기대: Entity 12, Event 2
MATCH (n)
RETURN labels(n) AS label, count(*) AS cnt
ORDER BY cnt DESC;


// ============================================================================
// (b) 멀티홉 순회 — 중간 노드를 명시해 두 칸을 잇는다
// ============================================================================

// b-1) "RAG 를 개선하는 것들은 각각 무엇을 쓰는가?"
//      1홉: x 가 RAG 를 IMPROVES.  2홉: 그 x 가 무언가를 USES.
//      RAG 개선 = Self-RAG / CRAG / GraphRAG. 그중 USES 가 있는 건 CRAG 뿐.
//      기대: CRAG -> LangChain
MATCH (x:Entity)-[:IMPROVES]->(:Entity {name: "RAG"})
MATCH (x)-[:USES]->(tool:Entity)
RETURN x.name AS improver, tool.name AS uses_tool;

// b-2) "RAG 를 개선하는 모델들은 누가 만들었나?" (IMPROVES 다음 DEVELOPED_BY)
//      기대: GraphRAG -> Microsoft (Self-RAG / CRAG 는 DEVELOPED_BY 엣지 없음)
MATCH (x:Entity)-[:IMPROVES]->(:Entity {name: "RAG"})
MATCH (x)-[:DEVELOPED_BY]->(org:Entity)
RETURN x.name AS model, org.name AS developed_by;


// ============================================================================
// (c) 가변 길이 경로 + 최단 경로
// ============================================================================

// c-1) LightRAG 와 RAG 를 잇는 1~3홉 경로 모두 (방향 무시, 연결만).
//      상한(..3)을 반드시 준다 — 없으면 경로 폭발.
//      기대 최단: [LightRAG, GraphRAG, RAG], hop_count = 2
MATCH p = (a:Entity {name: "LightRAG"})-[*1..3]-(b:Entity {name: "RAG"})
RETURN [n IN nodes(p) | n.name] AS hops, length(p) AS hop_count
ORDER BY hop_count
LIMIT 5;

// c-2) 가장 짧은 길 하나만 — shortestPath().
//      기대: [LightRAG, GraphRAG, RAG], hops = 2
MATCH (a:Entity {name: "LightRAG"}), (b:Entity {name: "RAG"})
MATCH p = shortestPath((a)-[*1..5]-(b))
RETURN [n IN nodes(p) | n.name] AS path, length(p) AS hops;

// c-3) 같은 길이의 최단 경로가 여럿이면 모두 — allShortestPaths().
MATCH (a:Entity {name: "LightRAG"}), (b:Entity {name: "RAG"})
MATCH p = allShortestPaths((a)-[*1..5]-(b))
RETURN [n IN nodes(p) | n.name] AS path, length(p) AS hops;


// ============================================================================
// (d) 집계 — count / collect / WITH 파이프라인 / OPTIONAL MATCH
// ============================================================================

// d-1) 가장 많이 참조되는(in-degree 큰) 엔티티.
//      WITH 로 집계 결과를 넘겨야 ORDER BY 가 먹는다.
//      기대 1위: RAG, in_degree = 3
MATCH (n:Entity)<-[r]-()
WITH n, count(r) AS in_degree
RETURN n.name AS entity, in_degree
ORDER BY in_degree DESC
LIMIT 5;

// d-2) "무엇이 무엇에 의해 개선되는가" — collect 로 개선자 이름까지 묶기.
//      기대: RAG <- [Self-RAG, CRAG, GraphRAG], cnt = 3
MATCH (n:Entity)<-[:IMPROVES]-(m:Entity)
WITH n, collect(m.name) AS improvers, count(m) AS cnt
RETURN n.name AS improved, improvers, cnt
ORDER BY cnt DESC;

// d-3) 관계가 하나도 없는 고립 노드 — OPTIONAL MATCH 로 null 도 살린 뒤 0 만 거른다.
//      기대: NeurIPS, multi-hop (어떤 Entity-Entity 관계에도 안 걸린 엔티티)
MATCH (n:Entity)
OPTIONAL MATCH (n)-[r]-(:Entity)
WITH n, count(r) AS deg
WHERE deg = 0
RETURN n.name AS isolated
ORDER BY isolated;


// ============================================================================
// (e) Event 질의 — (:Event)-[:ABOUT]->(:Entity), time 속성
// ============================================================================

// e-1) 어떤 엔티티가 언제 발표됐는가.
//      기대: RAG 2020, GraphRAG 2024
MATCH (e:Event)-[:ABOUT]->(n:Entity)
RETURN n.name AS entity, e.type AS event_type, e.time AS year, e.venue AS venue
ORDER BY year;

// e-2) 특정 연도의 이벤트만 (시점 필터).
//      기대: RAG (NeurIPS, 2020)
MATCH (e:Event)-[:ABOUT]->(n:Entity)
WHERE e.time = "2020"
RETURN n.name AS entity, e.venue AS venue, e.time AS year;
