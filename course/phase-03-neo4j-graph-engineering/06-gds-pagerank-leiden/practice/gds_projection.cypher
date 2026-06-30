// GDS 그래프 투영(projection) 관리 Cypher 모음 — 생성 / 조회 / 삭제.
//
// GDS 알고리즘은 디스크의 Neo4j 그래프를 직접 돌리지 않는다.
// 먼저 in-memory 그래프 카탈로그에 "투영"한 뒤, 그 사본 위에서 PageRank·Leiden 을 돌린다.
// 그래서 알고리즘을 부르기 전에 항상 투영이 먼저 있어야 한다.
//
// pagerank.py / leiden.py 가 같은 투영을 코드에서 생성하므로, 이 파일은
// Neo4j Browser 나 cypher-shell 로 직접 만져 보고 싶을 때 참고용으로 둔다.
//
// 우리 그래프는 (:Entity)-[타입드 관계]->(:Entity) + (:Event)-[:ABOUT]->(:Entity) 다.
// PageRank·Leiden 은 Entity 끼리의 연결 구조를 보려는 것이므로, Entity 노드와
// 엔티티 간 관계만 투영한다(Event/ABOUT 은 제외).

// ── 1) 투영 생성 (native projection) ───────────────────────────────────────
// 관계 타입이 4종(COMPARES_TO·DEVELOPED_BY·IMPROVES·USES)이다. '*' 로 전부 잡되,
// orientation: 'UNDIRECTED' 로 무방향 투영한다.
//
// 왜 UNDIRECTED 인가:
//   - Leiden(커뮤니티 탐지)은 무방향 그래프에서 동작한다. 방향 그래프면 에러가 난다.
//   - PageRank 는 방향에 민감하다. 무방향이면 "연결이 많은 노드"를 허브로 본다.
//     우리처럼 관계 방향의 의미가 제각각인(USES·DEVELOPED_BY…) 작은 그래프에선
//     무방향 해석이 더 읽기 쉽다. PageRank·Leiden 을 같은 투영으로 돌리려는 목적도 있다.
//
// 주의: 같은 이름('entityGraph')이 이미 카탈로그에 있으면 에러가 난다.
//       먼저 아래 4) 의 drop 으로 지우거나, gds.graph.exists 로 확인하라.
CALL gds.graph.project(
  'entityGraph',                         // 카탈로그에 저장될 투영 이름
  'Entity',                              // 노드 프로젝션 — Entity 라벨만
  {
    ALL_REL: {                           // 관계 프로젝션 — 모든 엔티티 간 관계를 한 묶음으로
      type: '*',                         // 타입 구분 없이 전부('*')
      orientation: 'UNDIRECTED'          // 무방향 — Leiden 필수, PageRank 해석 단순화
    }
  }
)
YIELD graphName, nodeCount, relationshipCount;
// 기대: graphName='entityGraph', nodeCount=12(Entity), relationshipCount=18
//   엔티티 간 관계 9개를 UNDIRECTED 로 투영하면 양방향으로 9*2=18 개가 된다.
//   (Event 2개와 ABOUT 2개는 투영에 포함하지 않았다.)

// ── 2) 카탈로그 조회 ───────────────────────────────────────────────────────
// 지금 메모리에 어떤 투영들이 떠 있는지, 각각 노드·관계 수가 얼마인지 본다.
CALL gds.graph.list()
YIELD graphName, nodeCount, relationshipCount, memoryUsage
RETURN graphName, nodeCount, relationshipCount, memoryUsage;

// 특정 이름이 있는지만 빠르게 확인하고 싶을 때:
CALL gds.graph.exists('entityGraph') YIELD exists RETURN exists;

// ── 3) (참고) 투영을 검증 — 어떤 노드가 들어갔나 ──────────────────────────
// 투영된 노드 id 와 원본 Entity 의 name 을 매핑해 본다.
// gds.util.asNode(nodeId) 로 투영 id → 실제 노드를 되돌린다.
CALL gds.graph.nodeProperties.stream('entityGraph', [])
YIELD nodeId
RETURN gds.util.asNode(nodeId).name AS name
ORDER BY name;
// (nodeProperties 가 비어 있으면 위 호출이 빈 결과를 낼 수 있다. 단순 노드 목록은
//  아래처럼 원본 그래프에서 직접 보는 편이 확실하다.)
// MATCH (e:Entity) RETURN e.name ORDER BY e.name;

// ── 4) 투영 삭제 ───────────────────────────────────────────────────────────
// 투영은 메모리를 점유한다. 알고리즘을 다 돌렸으면 반드시 지운다.
// 안 지우면 같은 이름으로 재투영할 때 충돌하고, 메모리도 계속 잡고 있다.
CALL gds.graph.drop('entityGraph', false)   // 두 번째 인자 false = 없으면 에러 안 냄
YIELD graphName
RETURN graphName + ' dropped' AS result;
