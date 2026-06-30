// 04 하이브리드 검색용 인덱스 두 개를 만든다.
//
// 실행 전제:
//   - 02 적재 완료 + add_embeddings.py 실행으로 e.embedding(1024d)·e.description 이 채워진 상태.
//   - 임베딩보다 인덱스를 먼저 만들어도 되지만, 인덱스 생성 후에는 백그라운드로 채워진다.
//
// 실행 방법(둘 중 하나):
//   1) Neo4j Browser(http://localhost:7474)에 붙여넣고 한 문장씩 실행.
//   2) cypher-shell -u neo4j -p testpassword1 -f indexes.cypher
//      (docker 안에서:  docker exec -i kb-neo4j cypher-shell -u neo4j -p testpassword1 < indexes.cypher)
//
// 두 인덱스는 03 의 멀티홉 Cypher 와 함께 04 의 3중 융합(Vector + Full-text + Graph)을 이룬다.

// === 1) 네이티브 벡터 인덱스 ===============================================
// e.embedding 에 대해 코사인 유사도로 근접 이웃을 찾는 인덱스.
// vector.dimensions 는 임베딩 차원과 반드시 일치해야 한다(voyage-3.5 = 1024, bge-m3 = 1024).
CREATE VECTOR INDEX entity_embedding IF NOT EXISTS
FOR (e:Entity) ON (e.embedding)
OPTIONS {
  indexConfig: {
    `vector.dimensions`: 1024,
    `vector.similarity_function`: 'cosine'
  }
};

// === 2) 풀텍스트 인덱스(Lucene) ============================================
// name·description 에 대한 키워드/BM25 검색. 정확한 용어·약어 매칭에 강하다
// (벡터가 놓치는 "정확히 그 단어" 질의를 보완).
CREATE FULLTEXT INDEX entity_fulltext IF NOT EXISTS
FOR (e:Entity) ON EACH [e.name, e.description];

// === 확인 =================================================================
// 인덱스가 ONLINE 인지(=사용 가능) 점검. state 가 ONLINE 이어야 한다.
SHOW INDEXES YIELD name, type, state, labelsOrTypes, properties
WHERE name IN ['entity_embedding', 'entity_fulltext']
RETURN name, type, state, labelsOrTypes, properties;
