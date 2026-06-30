// 4.3 global.cypher — Global 검색기를 떠받치는 Cypher 모음.
// Neo4j Browser(http://localhost:7474) 나 cypher-shell 에서 한 블록씩 실행해 본다.
// 파이썬 스크립트가 내부에서 돌리는 쿼리와 같다. 손으로 돌려 보며 감을 잡으라고 따로 모았다.
//
// 전제: graph_setup.py 적재 완료(:Mini 노드), Neo4j 5.26 + GDS 플러그인 기동.

// ─────────────────────────────────────────────────────────────────────────────
// 1) Leiden 투영 — 무방향 필수(UNDIRECTED). 방향 그래프로 투영하면 Leiden 이 거부한다.
// ─────────────────────────────────────────────────────────────────────────────
CALL gds.graph.project(
  'miniGraph_leiden',
  'Mini',
  { ALL_REL: { type: '*', orientation: 'UNDIRECTED' } }
)
YIELD nodeCount, relationshipCount
RETURN nodeCount, relationshipCount;

// ─────────────────────────────────────────────────────────────────────────────
// 2) Leiden stream — 멤버만 본다(그래프엔 안 씀). 누가 어느 커뮤니티인지 확인용.
// ─────────────────────────────────────────────────────────────────────────────
CALL gds.leiden.stream('miniGraph_leiden')
YIELD nodeId, communityId
RETURN communityId, collect(gds.util.asNode(nodeId).name) AS members
ORDER BY communityId;

// ─────────────────────────────────────────────────────────────────────────────
// 3) Leiden write — 탐지값을 n.community 속성으로 기록한다(요약·global 입력).
//    graph_setup.py 가 박아 둔 임시 community 시드를 '실제 탐지값'으로 덮어쓴다.
// ─────────────────────────────────────────────────────────────────────────────
CALL gds.leiden.write('miniGraph_leiden', { writeProperty: 'community' })
YIELD communityCount, modularity, nodePropertiesWritten
RETURN communityCount, modularity, nodePropertiesWritten;

// ─────────────────────────────────────────────────────────────────────────────
// 4) 투영 정리 — 인메모리 그래프만 제거(디스크 그래프·community 속성은 유지).
// ─────────────────────────────────────────────────────────────────────────────
CALL gds.graph.drop('miniGraph_leiden', false);

// ─────────────────────────────────────────────────────────────────────────────
// 5) 커뮤니티별 멤버 조회 — community_summarize.py 의 fetch_members 와 같은 쿼리.
// ─────────────────────────────────────────────────────────────────────────────
MATCH (n:Mini)
WHERE n.community IS NOT NULL
RETURN n.community AS cid, collect(n.name) AS members, count(*) AS size
ORDER BY cid;

// ─────────────────────────────────────────────────────────────────────────────
// 6) 커뮤니티 내부 관계 조회 — community_summarize.py 의 fetch_internal_relations 와 동일.
//    $names 에 한 커뮤니티의 멤버 이름 리스트를 넣으면 그 군집 내부 관계만 나온다.
//    Browser 에서 직접 돌릴 땐 :param names => ['Ragas','Langfuse','evaluation', ...] 처럼 준다.
// ─────────────────────────────────────────────────────────────────────────────
MATCH (a:Mini)-[r]->(b:Mini)
WHERE a.name IN $names AND b.name IN $names
RETURN a.name AS src, type(r) AS rel, b.name AS dst
ORDER BY src, dst;
