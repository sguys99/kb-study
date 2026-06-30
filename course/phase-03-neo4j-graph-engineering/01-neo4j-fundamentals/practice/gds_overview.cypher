// GDS 개요 확인 — 플러그인이 살아있는지만 본다(알고리즘은 실행하지 않는다).
//
// 전제:
//   - docker-compose.yml 에서 NEO4J_PLUGINS=["graph-data-science"] 로 기동
//   - 실제 PageRank·Leiden 실행은 토픽 06(06-gds-pagerank-leiden) 에서 다룬다.
//
// 실행(둘 중 하나):
//   1) Browser 에 붙여넣고 실행
//   2) cypher-shell:
//      cat gds_overview.cypher | docker exec -i kb-neo4j cypher-shell -u neo4j -p testpassword1

// 1) GDS 버전 — 버전이 찍히면 플러그인 활성화 성공.
RETURN gds.version() AS gds_version;

// 2) 사용 가능한 알고리즘 카탈로그 일부 — pageRank / leiden 이 보이는지 확인.
//    (전체 목록은 길다. name 에 'pageRank' 또는 'leiden' 이 들어간 것만 추린다.)
CALL gds.list() YIELD name, description
WHERE toLower(name) CONTAINS 'pagerank' OR toLower(name) CONTAINS 'leiden'
RETURN name, description
ORDER BY name;
