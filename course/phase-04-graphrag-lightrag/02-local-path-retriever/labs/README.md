# 4.2 핸즈온 — Local · Path 검색기를 손으로 돌려 보기

엔티티 링킹 → Local(이웃) → Path(멀티홉 경로) 순으로 직접 실행한다.
4.1 의 :Mini 미니 그래프를 더 풍부하게(alias + 노드/관계 추가) 키운 그래프 위에서 돈다.

명령마다 **예상 출력**을 붙였다. 직접 돌려 결과를 대조하라. Lucene 점수처럼 환경에 따라
미세하게 다를 수 있는 값은 그렇게 표시했다.

> 전제: Python 3.11+, Docker / Docker Compose. 실습 코드는 `../practice/` 에 있다.
> 비용 0 — 기본 경로는 LLM·임베딩 API 를 쓰지 않는다(엔티티 링킹은 full-text/alias 매칭).
> 임베딩 링킹은 선택 분기다. `VOYAGE_API_KEY` 가 있을 때만 켜지고, 없으면 기본 경로로 떨어진다.

---

## 0. Neo4j 기동 + 헬스체크

```bash
cd ../practice
docker compose up -d
docker compose ps
```

예상 출력(STATUS 가 `healthy` 가 될 때까지 30초쯤 걸린다):

```
NAME       IMAGE         STATUS                   PORTS
kb-neo4j   neo4j:5.26    Up 35 seconds (healthy)  0.0.0.0:7474->7474/tcp, 0.0.0.0:7687->7687/tcp
```

`healthy` 로 바뀌면 Bolt(7687) 접속 준비가 끝난 것이다. `starting` 이면 좀 더 기다린다.
4.1 에서 띄운 `kb-neo4j` 가 이미 떠 있으면 새로 띄울 필요 없이 그대로 쓴다.

---

## 1. 미니 그래프 적재 + full-text 인덱스 생성

```bash
pip install -r requirements.txt
export NEO4J_PASSWORD=testpassword1
python graph_setup.py
```

예상 출력:

```
[load] 미니 그래프 적재 완료 — :Mini 노드 9개 + 관계 9개
[index] full-text 인덱스 'miniNameFulltext' 준비 완료 (name + aliases 검색)
```

4.1 의 7노드/7관계에 `vector search`·`VoyageAI` 2개와 관계 2개가 더해져 9개씩이다.
각 노드에 `aliases` 가 붙어 엔티티 링킹이 자연어 표현을 흡수한다.
인덱스 생성은 `IF NOT EXISTS` 라 여러 번 돌려도 안전하다.

---

## 2. 엔티티 링킹 — 자연어 표현을 노드에 꽂기

```bash
python entity_linking.py
```

예상 출력:

```
[엔티티 링킹] 방식: exact/alias/full-text
  'LightRAG'  →  :Mini(LightRAG)  [method=exact, score=1.000]
  'light rag'  →  :Mini(LightRAG)  [method=alias, score=0.950]
  'retrieval augmented generation'  →  :Mini(RAG)  [method=alias, score=0.950]
  'neo4j graph database'  →  :Mini(Neo4j)  [method=alias, score=0.950]
  '벡터 검색'  →  :Mini(vector search)  [method=alias, score=0.950]
  '그래프 데이터베이스 같은 거'  →  :Mini(Neo4j)  [method=fulltext, score=≈1.2]
  '전혀 없는 표현 zzz'  →  (링크 실패: 후보 없음)  [method=none]
```

`LightRAG` 는 name 정확 일치(exact). `light rag` 는 별칭(alias)으로 같은 노드에 꽂힌다.
`그래프 데이터베이스 같은 거` 처럼 정확 일치가 없는 의역은 full-text 가 부분 매칭으로 잡는다
(점수는 Lucene 값이라 환경마다 다를 수 있다). 마지막 표현은 일부러 빗나가게 한 것 — 링킹
실패는 빈 검색 결과의 가장 흔한 원인이다. "그래프가 비었다"가 아니라 "표현이 안 꽂혔다"이다.

임의 표현 하나만 링킹해 보려면:

```bash
python entity_linking.py "msft"
```

예상 출력:

```
[엔티티 링킹] 방식: exact/alias/full-text
  'msft'  →  :Mini(Microsoft)  [method=alias, score=0.950]
```

`VOYAGE_API_KEY` 를 export 하고 `voyageai` 를 설치하면 방식 줄이
`exact/alias/full-text (+임베딩)` 으로 바뀌고, full-text 후보가 임베딩 유사도로 재정렬된다.
키가 없으면 이 분기는 자동으로 건너뛴다(기본 결과는 동일).

---

## 3. Local 검색기 — 이웃 서브그래프 컨텍스트

```bash
python local_retriever.py
```

예상 출력(`LightRAG`, depth=1):

```
(링킹: 'LightRAG' → :Mini(LightRAG) [exact], depth=1)
[Local 컨텍스트] 시작 엔티티: LightRAG
  -- 1홉 --
  LightRAG -[IMPLEMENTS]- GraphRAG  (이웃: GraphRAG/Method)
  LightRAG -[DEVELOPED_BY]- HKUDS  (이웃: HKUDS/Organization)
  LightRAG -[USES]- Neo4j  (이웃: Neo4j/Database)
  LightRAG -[EMBEDS_WITH]- VoyageAI  (이웃: VoyageAI/Organization)
```

(이웃 이름순 정렬이라 GraphRAG → HKUDS → Neo4j → VoyageAI 차례로 나온다.)
자연어 표현으로 시작해도 된다. depth 를 2 로 키우면 이웃의 이웃까지 들어온다:

```bash
python local_retriever.py "light rag" 2
```

예상 출력(요지 — 2홉이 더해져 RAG·multi-hop·Microsoft 등이 추가로 보인다):

```
(링킹: 'light rag' → :Mini(LightRAG) [alias], depth=2)
[Local 컨텍스트] 시작 엔티티: LightRAG
  -- 1홉 --
  LightRAG -[IMPLEMENTS]- GraphRAG  (이웃: GraphRAG/Method)
  LightRAG -[DEVELOPED_BY]- HKUDS  (이웃: HKUDS/Organization)
  LightRAG -[USES]- Neo4j  (이웃: Neo4j/Database)
  LightRAG -[EMBEDS_WITH]- VoyageAI  (이웃: VoyageAI/Organization)
  -- 2홉 --
  Microsoft -[COMPARES_TO]- HKUDS  (이웃: HKUDS/Organization)
  GraphRAG -[DEVELOPED_BY]- Microsoft  (이웃: Microsoft/Organization)
  GraphRAG -[EXTENDS]- RAG  (이웃: RAG/Method)
  GraphRAG -[ADDRESSES]- multi-hop  (이웃: multi-hop/Concept)
```

(2홉 이웃도 이름순이라 HKUDS → Microsoft → RAG → multi-hop 순서다. HKUDS 는 1홉에도
2홉에도 나온다 — DISTINCT 가 `(이웃, 홉, 관계)` 묶음 기준이라 도달 경로가 다르면 따로
센다. 큰 그래프에서는 이런 중복이 노이즈가 되므로 `limit` 으로 상한을 둔다.)
depth 를 키울수록 이웃이 빠르게 늘어난다. 그래서 코드에 `limit` 상한을 둔다.
이 컨텍스트 문자열을 그대로 LLM 프롬프트의 근거 블록에 끼우면 Local 검색이 완성된다.
(컨텍스트 패킹·토큰 예산의 본격적인 다룸은 4.4 의 몫이다.)

---

## 4. Path 검색기 — 멀티홉 경로

```bash
python path_retriever.py
```

예상 출력(`Neo4j` ↔ `RAG`):

```
(링킹: 'Neo4j' → Neo4j [exact], 'RAG' → RAG [exact])
[Path 컨텍스트] Neo4j ↔ RAG 최단 경로 (길이 3 홉)
  Neo4j -[USES]- LightRAG -[IMPLEMENTS]- GraphRAG -[EXTENDS]- RAG
```

`Neo4j` 와 `RAG` 는 직접 연결이 없다. 그런데 `Neo4j → LightRAG → GraphRAG → RAG` 라는
3홉 경로가 나온다. 자연어 표현으로 양 끝을 줘도 된다:

```bash
python path_retriever.py "light rag" "벡터 검색"
```

예상 출력(`LightRAG` ↔ `vector search`):

```
(링킹: 'light rag' → LightRAG [alias], '벡터 검색' → vector search [alias])
[Path 컨텍스트] LightRAG ↔ vector search 최단 경로 (길이 3 홉)
  LightRAG -[IMPLEMENTS]- GraphRAG -[EXTENDS]- RAG -[USES]- vector search
```

양 끝을 자연어로 줬는데 별칭으로 노드에 꽂힌 뒤(`light rag`→LightRAG, `벡터 검색`→vector
search) 3홉 경로로 이어졌다. 이게 Path 검색기의 전부다 — 링킹이 먼저, 경로가 다음.

---

## 5. (선택) 묶음 클래스 + cypher-shell

Local·Path 를 한 클래스로 묶은 `retriever.py` 는 03/04 가 import 할 진입점이다:

```bash
python retriever.py
```

예상 출력(요지):

```
== 엔티티 링킹 ==
  LinkResult(mention='light rag', name='LightRAG', method='alias', score=0.95)

== Local (depth=1) ==
(링킹: 'LightRAG' → :Mini(LightRAG) [exact], depth=1)
[Local 컨텍스트] 시작 엔티티: LightRAG
  -- 1홉 --
  ...

== Path ==
(링킹: 'Neo4j' → Neo4j [exact], 'RAG' → RAG [exact])
[Path 컨텍스트] Neo4j ↔ RAG 최단 경로 (길이 3 홉)
  Neo4j -[USES]- LightRAG -[IMPLEMENTS]- GraphRAG -[EXTENDS]- RAG
```

Python 드라이버 없이 Cypher 만으로 같은 패턴을 보려면:

```bash
cat retrievers.cypher | docker exec -i kb-neo4j cypher-shell -u neo4j -p testpassword1
```

예상 출력(엔티티 링킹·Path 결과만 발췌):

```
name      score
"Neo4j"   ≈1.2

hops                                       rels                                  hop_len
["Neo4j","LightRAG","GraphRAG","RAG","vector search"]  [...]                     4
```

(여기 Path 는 `Neo4j` ↔ `vector search` 라 4홉이다. 어느 쌍을 묻느냐에 따라 홉 수가 달라진다.)

---

## 6. Baseline 대비 — 왜 이게 멀티홉을 이기나

`Neo4j ↔ RAG` 의 3홉 경로는 Vector+BM25 Baseline(Phase 1)이 구조적으로 못 내는 답이다.
`Neo4j` 와 `RAG` 가 한 청크에 같이 안 나오면 벡터 유사도로는 둘의 관계를 찾을 길이 없다.
그래프는 `LightRAG`·`GraphRAG` 라는 중간 노드를 디딤돌 삼아 길을 잇는다. Phase 0 에서
무너졌던 멀티홉이 Path 검색기로 메워진다. 이 우위를 점수로 증명하는 건 4.5 의 A/B 다.

---

## 7. 정리

```bash
python graph_setup.py --reset      # 미니 그래프(:Mini)만 삭제(인덱스는 유지)
docker compose down                # 컨테이너 종료(볼륨 유지)
```

예상 출력:

```
[reset] 미니 그래프(:Mini)를 삭제했다(full-text 인덱스는 유지).
```

`:Mini` 라벨로 격리해 적재했으므로, 같은 DB 에 Phase 3 의 진짜 그래프가 있어도 안 건드린다.

---

## 체크포인트

- [ ] Neo4j 컨테이너가 `healthy` 로 뜬다.
- [ ] `graph_setup.py` 가 :Mini 노드 9개 + 관계 9개 + full-text 인덱스를 적재한다.
- [ ] `light rag`·`벡터 검색` 같은 자연어 표현이 alias/full-text 로 정확한 노드에 링크된다.
- [ ] Local 검색기가 `LightRAG` 의 1홉/2홉 이웃을 컨텍스트 문자열로 직렬화한다.
- [ ] Path 검색기가 `Neo4j ↔ RAG` 를 3홉 경로로 잇는다(직접 검색으로는 안 나오는 답).
- [ ] 링킹 실패 시 "빈 결과"의 원인이 링킹임을 설명할 수 있다.
