# Lab — Vector · Full-text · Graph Hybrid Search

03 이 멀티홉으로 질의하던 같은 그래프에 임베딩·인덱스를 더해 3중 하이브리드 검색을 돌려본다.
각 명령 아래 **예상 출력**이 있다. 실제 결과를 대조하며 따라간다.

> 실제 실행·과금 검증은 학습자 몫이다(roadmap 방침). 아래 출력은 동봉 데이터(nodes≈14)를 기준으로 한 예시이며,
> 임베딩 점수(score)·등수는 모델/버전에 따라 소수점이 달라질 수 있다. **순위와 구조**가 맞는지를 본다.

## 0. 전제 확인

- Neo4j 5.26 가 떠 있고 02 적재가 끝나 있어야 한다(03 과 같은 그래프).
- 임베딩 백엔드를 고른다.
  - VoyageAI: `export VOYAGE_API_KEY=...` (키는 셸/`.env` 에서만, 코드에 하드코딩 금지)
  - 비용 0: 로컬 Ollama + `bge-m3` — `ollama pull bge-m3` 후 `ollama serve` 기동. 이때 아래 모든 파이썬 명령에 `--backend ollama` 를 붙인다.

## 1. 컨테이너 기동 + 그래프 존재 확인

```bash
cd practice
docker compose up -d
docker compose ps
```

예상 출력(요지):

```
NAME        IMAGE         STATUS                   PORTS
kb-neo4j    neo4j:5.26    Up (healthy)             0.0.0.0:7474->7474/tcp, 0.0.0.0:7687->7687/tcp
```

그래프가 비어 있지 않은지 확인한다.

```bash
docker exec -i kb-neo4j cypher-shell -u neo4j -p testpassword1 \
  "MATCH (n) RETURN count(n) AS nodes;"
```

예상 출력:

```
nodes
14
```

`0` 이 나오면 먼저 02 적재를 끝낸다.

```bash
cd ../../02-bulk-ingest-merge/practice && python ingest_bulk.py && cd -
```

## 2. 의존성 설치

```bash
pip install -r requirements.txt
```

예상 출력(요지): `Successfully installed neo4j-5.x voyageai-0.x ...`

## 3. 임베딩 부여

```bash
python add_embeddings.py
# 비용 0:  python add_embeddings.py --backend ollama
```

예상 출력:

```
[INFO] 임베딩 대상 12 개 엔티티, backend=voyage, dim=1024
[OK] 12 개 엔티티에 description·embedding(1024d) 저장 완료.
```

> 대상 개수는 그래프의 Entity 수다(Event 는 제외). canonical entities 11 + fallback 노드(LangChain 등)에 따라 11~12 사이가 정상이다.

저장이 됐는지 한 건 확인한다.

```bash
docker exec -i kb-neo4j cypher-shell -u neo4j -p testpassword1 \
  "MATCH (e:Entity {name:'LightRAG'}) RETURN e.description AS d, size(e.embedding) AS dim;"
```

예상 출력:

```
d                                                              dim
"LightRAG. aka Light RAG, LightRag. LightRAG ... stores ..."   1024
```

## 4. 인덱스 생성 + ONLINE 확인

```bash
docker exec -i kb-neo4j cypher-shell -u neo4j -p testpassword1 < indexes.cypher
```

예상 출력(마지막 SHOW INDEXES 부분):

```
name                type        state     labelsOrTypes   properties
"entity_embedding"  "VECTOR"    "ONLINE"  ["Entity"]      ["embedding"]
"entity_fulltext"   "FULLTEXT"  "ONLINE"  ["Entity"]      ["name","description"]
```

`state` 가 `POPULATING` 이면 몇 초 뒤 다시 `SHOW INDEXES` 로 `ONLINE` 을 확인한 뒤 다음으로 넘어간다.

## 5. 하이브리드 검색 실행

```bash
python hybrid_search.py
# 비용 0:  python hybrid_search.py --backend ollama
```

예상 출력(질문 1 — 발췌, 점수는 근삿값):

```
============================================================
질문: RAG를 개선하는 모델은?
============================================================

[벡터 단독 top-k]
  1. RAG            score=0.78
  2. GraphRAG       score=0.71
  3. multi-hop      score=0.64
  ...

[풀텍스트 단독]
  1. Self-RAG       score=2.31
  2. CRAG           score=2.10
  3. GraphRAG       score=1.05

[RRF 융합 후 상위]
  1. GraphRAG       rrf=0.0325
  2. Self-RAG       rrf=0.0164
  3. CRAG           rrf=0.0161

[그래프 1~2홉 확장 — 시드 3개 기준]
  (1홉) GraphRAG --[IMPROVES]-- RAG (Model)
  (1홉) Self-RAG --[IMPROVES]-- RAG (Model)
  (1홉) CRAG --[IMPROVES]-- RAG (Model)
  (1홉) CRAG --[USES]-- LangChain (Model)
  (2홉) GraphRAG --[IMPROVES -> IMPROVES]-- Self-RAG (Model)
  ...
```

해석: 벡터 단독이 상위로 못 올린 `Self-RAG`·`CRAG` 를 풀텍스트가 끌어올렸고, RRF 가 둘을 시드로 합쳤다.
그래프 확장이 `IMPROVES` 관계와 한 칸 더 간 `CRAG -[:USES]-> LangChain` 까지 컨텍스트에 담는다.
03 에서 멀티홉 Cypher 로 손수 풀던 답이 자연어 질문 한 줄에서 나온다(= 완료 기준 충족).

예상 출력(질문 2 — 발췌):

```
============================================================
질문: LightRAG가 쓰는 저장소
============================================================
...
[RRF 융합 후 상위]
  1. LightRAG       rrf=...
  2. Neo4j          rrf=...
  ...
[그래프 1~2홉 확장 — 시드 3개 기준]
  (1홉) LightRAG --[USES]-- Neo4j (Tool)
  ...
[OK] 하이브리드 검색 완료.
```

## 6. 단일 질문으로 실험

```bash
python hybrid_search.py --query "그래프 기반으로 RAG를 개선한 프레임워크"
```

말랑한 표현이라 `MATCH {name:...}` 로는 시작점을 못 잡는 질문이다. 벡터+풀텍스트가 `GraphRAG` 를 시드로 잡고,
그래프 확장이 `GraphRAG -[:IMPROVES]-> RAG`, `GraphRAG -[:COMPARES_TO]-> LightRAG` 를 끌어오면 성공이다.

## 정리(선택)

```bash
docker compose down        # 컨테이너만 제거(볼륨 유지 → 임베딩·인덱스 보존)
# docker compose down -v   # 데이터까지 삭제(다시 02 적재부터 해야 함)
```
