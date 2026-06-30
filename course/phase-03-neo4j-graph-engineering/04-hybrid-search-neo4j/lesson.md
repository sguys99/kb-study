# 3.4 Vector · Full-text · Graph Hybrid Search in Neo4j

> **Phase 3 · 토픽 04** · 03 이 멀티홉으로 풀던 같은 그래프에 임베딩과 인덱스를 더해, 벡터·풀텍스트·그래프를 한 번에 융합하는 검색을 Neo4j 안에서 만든다.

## 학습 목표

이 토픽을 끝내면 다음을 할 수 있다.

- 03 그래프의 각 Entity 에 description 을 만들어 VoyageAI `voyage-3.5`(또는 로컬 `bge-m3`)로 임베딩하고 `e.embedding` 으로 저장한다.
- Neo4j 네이티브 벡터 인덱스와 풀텍스트 인덱스를 만들고, `db.index.vector.queryNodes` · `db.index.fulltext.queryNodes` 로 각각 검색한다.
- 두 랭킹을 RRF 로 융합해 시드 엔티티를 고르고, 03 식 1~2홉 Cypher 로 그래프 확장해 Vector + Full-text + Graph 3중 검색을 완성한다.

**완료 기준**: 벡터 단독은 못 잡던 시드를 풀텍스트가 보완하고, RRF 융합 후 그래프 1~2홉 확장으로 '03에서 멀티홉으로 풀던 질문'의 근거 엔티티+관계가 컨텍스트에 모두 포함되면 완료.

---

## 1. 왜 필요한가 — 벡터만으로도, 그래프만으로도 부족하다

03 에서 그래프는 강했다. "RAG를 개선하는 것들이 쓰는 도구"를 멀티홉으로 결정적으로 뽑았고, "LightRAG와 RAG"의 최단 경로도 찾았다. 한 가지 전제가 있었다. **시작 노드 이름을 정확히 알고 있어야** 한다는 것. `MATCH (a:Entity {name: "LightRAG"})` 는 사용자가 "LightRAG"라고 또박또박 입력해 줄 때만 통한다.

실제 질문은 그렇지 않다. "그래프 기반으로 RAG 개선한 그거" 같은 말랑한 표현으로 들어온다. 어디서 그래프 순회를 시작할지, 즉 **시드 엔티티를 어떻게 잡을지**가 빈자리다. 이 자리를 벡터 검색이 메운다. 의미가 가까운 엔티티를 끌어오니까.

그런데 벡터도 혼자서는 샌다. "RAG"처럼 짧고 흔한 약어나 "Neo4j" 같은 고유명사는 임베딩 공간에서 옆 개념과 잘 안 갈린다. 바로 그 단어를 찾는 일은 키워드 검색, 즉 풀텍스트가 잘한다.

결국 셋이 각자 다른 구멍을 막는다. 풀텍스트는 정확한 용어를, 벡터는 의미 근접을, 그래프는 시드 너머의 관계를 맡는다. 이 토픽은 셋을 한 파이프라인에 묶는다.

## 2. 핵심 개념 — 세 검색을 어떻게 한 줄로 합치나

순서가 핵심이다. 벡터와 풀텍스트로 **시드를 고르고**, 고른 시드에서 **그래프로 퍼뜨린다.**

벡터 검색은 코사인 유사도로 가까운 노드를, 풀텍스트는 Lucene 점수로 키워드가 맞는 노드를 돌려준다. 둘의 점수 스케일이 다르다. 코사인은 0~1 근처지만 Lucene 점수는 단어 빈도에 따라 제멋대로다. 그대로 더하면 한쪽이 다른 쪽을 깔아뭉갠다.

그래서 점수 대신 **등수**만 쓴다. RRF(Reciprocal Rank Fusion)다. 각 랭킹에서 어떤 엔티티가 몇 등인지 보고 `1/(k + rank)` 를 더한다. `k` 는 관례로 60. 두 검색 모두에서 상위에 든 엔티티가 자연히 위로 올라온다. 스케일 문제 없이.

```
RRF(e) = Σ  1 / (60 + rank_i(e))
        i∈{vector, fulltext}
```

Neo4j 에는 RRF 내장이 없다. 그래서 두 검색은 Cypher 로 돌리되 융합은 Python 에서 명시적으로 한다. 융합 결과 상위 N 개가 시드가 되고, 거기서부터는 03 에서 쓴 가변 길이 경로(`-[*1..2]-`)로 이웃·관계·근거를 끌어온다. 벡터·풀텍스트가 입구를, 그래프가 그 너머를 채우는 구조다.

## 3. 실습 — 임베딩 부여 → 인덱스 → 3중 검색

세 단계다. 전체 코드는 [`practice/`](practice/) 에 있고, 단계별 실행과 예상 출력은 [`labs/`](labs/) 에 있다.

### (a) 엔티티에 description·임베딩 부여

벡터 검색을 하려면 엔티티마다 임베딩할 텍스트가 있어야 한다. 03 그래프의 Entity 는 `name`·`type` 뿐이라 이대로는 임베딩이 빈약하다. 이름에 별칭과 **그 엔티티가 걸린 관계의 근거 문장(provenance quote)** 을 붙여 description 을 만든다.

여기 함정이 하나 있다. 02 적재는 관계에 `source_ids` 만 저장했고 quote 텍스트는 Neo4j 에 넣지 않았다. 그래서 quote 는 02 가 쓴 원본 `normalized_relations.jsonl` 에서 직접 읽는다. 새 데이터셋을 만드는 게 아니라 같은 데이터를 입력으로 재사용하는 것이다.

```python
# practice/add_embeddings.py — description 합성 + 저장(핵심 조각)
texts = [compose_description(t["item"]) for t in targets]   # name + aliases + quotes
vectors = embed_texts(texts, backend=backend)               # voyage-3.5 → 1024d

# 임베딩은 db.create.setNodeVectorProperty 로 저장한다(벡터 인덱스 표준 방식).
session.execute_write(lambda tx: tx.run(
    """
    UNWIND $rows AS row
    MATCH (e:Entity {canonical_id: row.canonical_id})
    SET e.description = row.description
    WITH e, row
    CALL db.create.setNodeVectorProperty(e, 'embedding', row.embedding)
    RETURN count(e) AS n
    """, rows=rows))
```

임베딩 함수는 백엔드를 가른다. 기본은 VoyageAI `voyage-3.5`(1024차원), 비용이 부담되면 `--backend ollama` 로 로컬 `bge-m3`(역시 1024차원, 키·과금 없음)를 쓴다. 차원이 같아 인덱스 설정을 그대로 공유한다. 저장과 질의는 **반드시 같은 모델**이어야 코사인 유사도가 의미를 가진다.

```python
# practice/add_embeddings.py — 백엔드 분기
def embed_texts(texts, backend="voyage"):
    if backend == "voyage":   # VOYAGE_API_KEY 필요(하드코딩 금지)
        return _embed_voyage(texts)
    if backend == "ollama":   # 비용 0, ollama serve + bge-m3
        return _embed_ollama(texts)
```

### (b) 벡터·풀텍스트 인덱스 생성

벡터 인덱스의 `vector.dimensions` 는 임베딩 차원과 한 글자도 틀리면 안 된다. 1024 로 임베딩했으면 1024.

```cypher
// practice/indexes.cypher
CREATE VECTOR INDEX entity_embedding IF NOT EXISTS
FOR (e:Entity) ON (e.embedding)
OPTIONS { indexConfig: {
  `vector.dimensions`: 1024,
  `vector.similarity_function`: 'cosine'
} };

CREATE FULLTEXT INDEX entity_fulltext IF NOT EXISTS
FOR (e:Entity) ON EACH [e.name, e.description];
```

인덱스는 만든 뒤 백그라운드로 채워진다. `SHOW INDEXES` 로 `state` 가 `ONLINE` 인지 확인하고 검색해야 빈손을 면한다.

### (c) RRF 융합 + 그래프 확장

두 검색을 Cypher 프로시저로 돌린다.

```cypher
// 벡터 검색
CALL db.index.vector.queryNodes('entity_embedding', $k, $qvec)
YIELD node, score
RETURN node.name AS name, node.canonical_id AS cid, score;

// 풀텍스트 검색
CALL db.index.fulltext.queryNodes('entity_fulltext', $qtext)
YIELD node, score
RETURN node.name AS name, node.canonical_id AS cid, score;
```

두 랭킹을 RRF 로 합치고, 상위 시드에서 1~2홉을 펼친다.

```python
# practice/hybrid_search.py — 융합(핵심 조각)
def reciprocal_rank_fusion(rankings, k_rrf=60):
    scores = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking):     # rank 0부터
            cid = item["cid"]
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k_rrf + rank)
    return sorted(...)  # rrf 내림차순
```

그래프 확장은 03 의 가변 길이 경로와 같은 발상이다. 시드에서 `-[*1..2]-` 로 이웃·관계 타입·`source_ids` 를 끌어와 컨텍스트로 합친다.

```python
# practice/hybrid_search.py — 그래프 확장 Cypher(hops 는 화이트리스트로 검증 후 박는다)
MATCH (seed:Entity) WHERE seed.canonical_id IN $cids
MATCH path = (seed)-[rels*1..2]-(nbr:Entity)
WHERE nbr.canonical_id <> seed.canonical_id
RETURN DISTINCT seed.name, nbr.name, [r IN rels | type(r)] AS rel_chain, length(path) AS hop
```

> 비용을 줄이려면 임베딩을 `bge-m3`(로컬 Ollama)로 바꾼다. `python add_embeddings.py --backend ollama` 와 `python hybrid_search.py --backend ollama` 로 저장·질의를 같은 모델로 맞추면 된다. 품질은 다소 떨어져도 파이프라인은 동일하게 동작한다.

## 4. 결과 해석 — 셋이 합쳐질 때 무엇이 달라지나

"RAG를 개선하는 모델은?" 을 보자. 벡터 단독은 "RAG"·"GraphRAG" 같은 의미상 가까운 노드를 위로 올리지만, 정작 개선 주체인 "Self-RAG"·"CRAG" 는 상위에 못 들기도 한다. 짧은 약어라 임베딩이 뭉뚱그려진다. 풀텍스트는 description 안의 "Self-RAG improves RAG"·"CRAG enhances RAG" 문장을 키워드로 정확히 집어낸다. 벡터가 놓친 시드를 풀텍스트가 보완하는 지점이다.

RRF 가 둘을 합치면 양쪽에서 점수를 받은 엔티티가 위로 모인다. 그 시드에서 1~2홉을 펼치면 `Self-RAG -[:IMPROVES]-> RAG`, `CRAG -[:IMPROVES]-> RAG`, `GraphRAG -[:IMPROVES]-> RAG`, 그리고 한 칸 더 가면 `CRAG -[:USES]-> LangChain` 까지 컨텍스트에 들어온다. 03 에서 멀티홉 Cypher 로 손수 풀던 답이, 이제 자유로운 자연어 질문 한 줄에서 나온다.

"LightRAG가 쓰는 저장소" 도 마찬가지다. 풀텍스트가 "LightRAG ... stores entities in Neo4j" 근거 문장으로 시드를 정확히 잡고, 그래프 확장이 `LightRAG -[:USES]-> Neo4j` 관계를 근거(`source_ids`)와 함께 끌어온다. 어느 한 검색만으로는 이 조합이 나오지 않는다.

---

## 🚨 자주 하는 실수

1. **저장 임베딩과 질의 임베딩 모델이 다르다.** description 을 `voyage-3.5` 로 저장해 놓고 질의는 `bge-m3` 로 임베딩하면, 같은 1024차원이라 에러는 안 나지만 코사인 유사도가 난수에 가까워진다. 검색 결과가 이상하면 제일 먼저 백엔드(`--backend`)가 저장·질의 양쪽에서 같은지 확인한다.
2. **벡터 인덱스 차원을 임베딩과 안 맞춘다.** `vector.dimensions: 1024` 인데 2048차원 임베딩을 넣으면 인덱스가 거부하거나 조용히 검색이 비어 나온다. 임베딩 차원과 인덱스 설정을 한 숫자로 통일한다(이 토픽은 1024).
3. **인덱스가 `ONLINE` 되기 전에 검색한다.** 인덱스 생성은 즉시 끝나도 데이터 반영은 백그라운드다. 만들자마자 `db.index.vector.queryNodes` 를 부르면 결과가 비거나 일부만 나온다. `SHOW INDEXES` 로 `state = ONLINE` 을 확인하고 검색한다. 점수 스케일이 다른 벡터·풀텍스트를 RRF 없이 원점수로 더하는 것도 같은 부류의 실수다.

## 출처

- Neo4j 공식 문서 — https://neo4j.com/docs/
- Neo4j 벡터 인덱스(Cypher Manual) — https://neo4j.com/docs/cypher-manual/current/indexes/semantic-indexes/vector-indexes/
- Neo4j Python Driver Manual — https://neo4j.com/docs/python-manual/current/
- VoyageAI Embeddings — https://docs.voyageai.com/docs/embeddings

## 다음 토픽

→ [Query Tuning & Read-only Guard](../05-query-tuning-readonly-guard/lesson.md)

