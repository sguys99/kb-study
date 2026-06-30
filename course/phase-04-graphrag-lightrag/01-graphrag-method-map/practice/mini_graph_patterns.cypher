// 4.1 mini_graph_patterns.cypher — Local/Path/Global 대표 Cypher 를 cypher-shell 로도 돌릴 수 있게.
//
// mini_graph_neo4j.py 와 같은 미니 그래프를 만들고, 세 검색 패턴의 대표 쿼리를 담았다.
// Python 드라이버 없이 Neo4j Browser 나 cypher-shell 에서 절을 하나씩 붙여 넣어 본다.
//
// 전제: Neo4j 5.26 LTS 기동(practice/docker-compose.yml). GDS·임베딩 불필요, 과금 0.
// 실행 예: cat mini_graph_patterns.cypher | cypher-shell -u neo4j -p testpassword1
//
// 주의: :Mini 라벨로 격리해 Phase 3 의 진짜 그래프를 건드리지 않는다.

// ── 0) 멱등 적재 ────────────────────────────────────────────────────────────
// 먼저 미니 그래프를 비우고 다시 만든다(여러 번 돌려도 중복이 안 쌓이게).
MATCH (n:Mini) DETACH DELETE n;

// 노드 7개 — community 는 Phase 3/06 Leiden 이 매기는 값을 흉내 낸 것이다.
//   community 0 = "검색 기법" 군집,  community 1 = "조직·도구" 군집
UNWIND [
  {name: 'RAG',       type: 'Method',       community: 0},
  {name: 'GraphRAG',  type: 'Method',       community: 0},
  {name: 'LightRAG',  type: 'Framework',    community: 0},
  {name: 'multi-hop', type: 'Concept',      community: 0},
  {name: 'Neo4j',     type: 'Database',     community: 1},
  {name: 'HKUDS',     type: 'Organization', community: 1},
  {name: 'Microsoft', type: 'Organization', community: 1}
] AS e
MERGE (n:Mini {name: e.name})
SET n.type = e.type, n.community = e.community;

// 관계 8개. shortestPath 가 통하도록 무방향처럼 이어 둔다(저장은 방향 그대로).
MATCH (graphrag:Mini {name: 'GraphRAG'}), (rag:Mini {name: 'RAG'})
MERGE (graphrag)-[:EXTENDS]->(rag);
MATCH (graphrag:Mini {name: 'GraphRAG'}), (mh:Mini {name: 'multi-hop'})
MERGE (graphrag)-[:ADDRESSES]->(mh);
MATCH (lightrag:Mini {name: 'LightRAG'}), (graphrag:Mini {name: 'GraphRAG'})
MERGE (lightrag)-[:IMPLEMENTS]->(graphrag);
MATCH (lightrag:Mini {name: 'LightRAG'}), (hkuds:Mini {name: 'HKUDS'})
MERGE (lightrag)-[:DEVELOPED_BY]->(hkuds);
MATCH (lightrag:Mini {name: 'LightRAG'}), (neo:Mini {name: 'Neo4j'})
MERGE (lightrag)-[:USES]->(neo);
MATCH (graphrag:Mini {name: 'GraphRAG'}), (ms:Mini {name: 'Microsoft'})
MERGE (graphrag)-[:DEVELOPED_BY]->(ms);
MATCH (ms:Mini {name: 'Microsoft'}), (hkuds:Mini {name: 'HKUDS'})
MERGE (ms)-[:COMPARES_TO]->(hkuds);

// ── 1) Local — 한 엔티티의 직접 이웃 ────────────────────────────────────────
// "이 엔티티는 무엇과 바로 연결되나" 류 질문.
MATCH (e:Mini {name: 'LightRAG'})-[r]-(nb:Mini)
RETURN type(r) AS rel, nb.name AS neighbor, nb.type AS ntype
ORDER BY rel, neighbor;

// ── 2) Path — 두 엔티티 사이 최단 멀티홉 경로 ──────────────────────────────
// "A와 B는 어떻게 이어지나" 류 질문. Baseline RAG 가 무너지던 자리.
MATCH (a:Mini {name: 'Neo4j'}), (b:Mini {name: 'RAG'}),
      p = shortestPath((a)-[*..6]-(b))
RETURN [n IN nodes(p) | n.name] AS hops, length(p) AS hop_len;

// ── 3) Global/Community — community 단위 집계로 전체 조망 ───────────────────
// "코퍼스가 어떤 묶음으로 나뉘나" 류 전체요약 질문.
MATCH (e:Mini)
WHERE e.community IS NOT NULL
RETURN e.community AS community, count(*) AS size, collect(e.name) AS members
ORDER BY community;
