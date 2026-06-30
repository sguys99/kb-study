// 4.2 retrievers.cypher — full-text 인덱스 + Local 이웃 + Path 경로 대표 Cypher.
//
// entity_linking / local_retriever / path_retriever 가 내부에서 쓰는 핵심 Cypher 를
// Python 드라이버 없이 Neo4j Browser 나 cypher-shell 에서 절을 하나씩 붙여 넣어 본다.
//
// 전제: Neo4j 5.26 LTS 기동(practice/docker-compose.yml). GDS·임베딩 불필요, 과금 0.
// 실행 예: cat retrievers.cypher | docker exec -i kb-neo4j cypher-shell -u neo4j -p testpassword1
//
// 주의: :Mini 라벨로 격리해 Phase 3 의 진짜 그래프를 건드리지 않는다.

// ── 0) 멱등 적재 (graph_setup.py 와 같은 9노드/9관계 + aliases) ────────────────
MATCH (n:Mini) DETACH DELETE n;

UNWIND [
  {name: 'RAG',           type: 'Method',       community: 0,
   aliases: ['retrieval augmented generation', 'retrieval-augmented generation']},
  {name: 'GraphRAG',      type: 'Method',       community: 0,
   aliases: ['graph rag', 'graph-based rag']},
  {name: 'LightRAG',      type: 'Framework',    community: 0,
   aliases: ['light rag', 'lightrag framework']},
  {name: 'multi-hop',     type: 'Concept',      community: 0,
   aliases: ['multi hop', 'multihop', '멀티홉']},
  {name: 'vector search', type: 'Concept',      community: 0,
   aliases: ['vector retrieval', 'dense retrieval', '벡터 검색']},
  {name: 'Neo4j',         type: 'Database',     community: 1,
   aliases: ['neo4j graph database', 'neo4j db']},
  {name: 'HKUDS',         type: 'Organization', community: 1,
   aliases: ['hong kong university data science', 'hku data science lab']},
  {name: 'Microsoft',     type: 'Organization', community: 1,
   aliases: ['msft', 'microsoft research']},
  {name: 'VoyageAI',      type: 'Organization', community: 1,
   aliases: ['voyage ai', 'voyage']}
] AS e
MERGE (n:Mini {name: e.name})
SET n.type = e.type, n.community = e.community, n.aliases = e.aliases;

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
MATCH (rag:Mini {name: 'RAG'}), (vs:Mini {name: 'vector search'})
MERGE (rag)-[:USES]->(vs);
MATCH (lightrag:Mini {name: 'LightRAG'}), (voy:Mini {name: 'VoyageAI'})
MERGE (lightrag)-[:EMBEDS_WITH]->(voy);

// ── 1) full-text 인덱스 — name·aliases 를 한 번에 검색 ────────────────────────
// 엔티티 링킹의 후보 생성에 쓴다. Neo4j 5.x 네이티브, 플러그인 불필요.
CREATE FULLTEXT INDEX miniNameFulltext IF NOT EXISTS
FOR (n:Mini) ON EACH [n.name, n.aliases];

// ── 2) 엔티티 링킹 — full-text 후보 생성 ──────────────────────────────────────
// 'graph database' 의역이 어떤 노드 후보로 잡히나(점수 높은 순).
CALL db.index.fulltext.queryNodes('miniNameFulltext', 'graph database')
YIELD node, score
WHERE node:Mini
RETURN node.name AS name, score
ORDER BY score DESC LIMIT 3;

// ── 3) Local — 링크된 엔티티의 1~2홉 이웃 서브그래프 ──────────────────────────
// 'LightRAG' 의 2홉 이웃까지. 무방향(-[*1..2]-)으로 방향에 안 갇히게.
MATCH p = (e:Mini {name: 'LightRAG'})-[*1..2]-(nb:Mini)
WITH nb, relationships(p) AS rels, length(p) AS d
WITH DISTINCT nb, d, rels[-1] AS last_rel
RETURN d AS hop, startNode(last_rel).name AS src, type(last_rel) AS rel,
       endNode(last_rel).name AS dst, nb.name AS neighbor
ORDER BY hop, neighbor LIMIT 30;

// ── 4) Path — 두 엔티티 사이 최단 멀티홉 경로 ────────────────────────────────
// 'Neo4j' ↔ 'vector search' 처럼 직접 연결 없는 쌍도 중간 노드로 이어진다.
// 상한 [*..6] 을 반드시 둔다(없으면 경로 폭발).
MATCH (a:Mini {name: 'Neo4j'}), (b:Mini {name: 'vector search'}),
      p = shortestPath((a)-[*..6]-(b))
RETURN [n IN nodes(p) | n.name] AS hops,
       [r IN relationships(p) | type(r)] AS rels,
       length(p) AS hop_len;

// ── 5) Path(여러 경로) — 같은 최단 길이의 경로 모두 ──────────────────────────
MATCH (a:Mini {name: 'LightRAG'}), (b:Mini {name: 'RAG'}),
      p = allShortestPaths((a)-[*..6]-(b))
RETURN [n IN nodes(p) | n.name] AS hops, length(p) AS hop_len
LIMIT 3;
