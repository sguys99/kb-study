// GDS 정리 Cypher — 투영 삭제 + write 로 쓴 속성 되돌리기.
//
// 각 .py 스크립트는 끝에서 자기 투영을 스스로 drop 한다. 하지만 중간에 멈췄거나
// Neo4j Browser 로 직접 투영을 만들었다면 메모리에 남는다. 이 파일로 깔끔히 비운다.

// ── 1) 남은 투영 모두 확인 ─────────────────────────────────────────────────
CALL gds.graph.list() YIELD graphName, nodeCount, relationshipCount
RETURN graphName, nodeCount, relationshipCount;

// ── 2) 이름별로 투영 삭제(없으면 조용히 넘어감: 두 번째 인자 false) ─────────
CALL gds.graph.drop('entityGraph', false) YIELD graphName RETURN graphName;
CALL gds.graph.drop('entityGraph_pagerank', false) YIELD graphName RETURN graphName;
CALL gds.graph.drop('entityGraph_leiden', false) YIELD graphName RETURN graphName;
CALL gds.graph.drop('entityGraph_dashboard', false) YIELD graphName RETURN graphName;

// ── 3) write 모드로 디스크에 쓴 속성 되돌리기 ──────────────────────────────
// leiden.py --write 로 e.community 를, pagerank write 예시로 e.pagerank 를 썼다면
// 다시 깨끗한 상태로 만들고 싶을 때 제거한다. Phase 4 에서 다시 쓸 거면 지우지 않아도 된다.
MATCH (e:Entity) WHERE e.community IS NOT NULL REMOVE e.community;
MATCH (e:Entity) WHERE e.pagerank IS NOT NULL REMOVE e.pagerank;

// ── 4) 확인 ────────────────────────────────────────────────────────────────
// 투영이 비었는지, 속성이 지워졌는지 다시 본다.
CALL gds.graph.list() YIELD graphName RETURN count(graphName) AS remaining_projections;
MATCH (e:Entity) WHERE e.community IS NOT NULL RETURN count(e) AS community_left;
