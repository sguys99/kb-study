# Lab 3.6 — GDS PageRank · Leiden + Graph Quality Dashboard

02 가 적재하고 04 가 임베딩·인덱싱한 **같은 그래프**를 GDS 로 투영해 중심 노드(PageRank)와
커뮤니티(Leiden)를 뽑고, 품질 대시보드로 건강검진한다. 새 데이터는 만들지 않는다.

> 그래프가 작다(Entity 12개 / 엔티티 간 관계 9개 / Event 2개 / ABOUT 2개 = 노드 14, 관계 11).
> PageRank·Leiden 의 효과는 규모가 커야 또렷하다. 여기선 **메커니즘과 결과 읽는 법**을 익힌다.
> 아래 예상 출력의 점수·커뮤니티는 환경에 따라 소수점·ID 가 다를 수 있다(순위·구조를 보면 된다).

모든 명령은 `practice/` 에서 실행한다. 이 토픽은 LLM·임베딩 API 키가 필요 없다(과금 0).

```bash
cd ../practice
pip install -r requirements.txt
```

---

## (0) 컨테이너 기동 + 그래프 존재 확인

04/05 의 `kb-neo4j` 가 이미 떠 있으면 `up -d` 는 생략 가능하다.

```bash
docker compose up -d
docker compose ps
```

예상 출력(요지):

```
NAME        IMAGE         STATUS                   PORTS
kb-neo4j    neo4j:5.26    Up (healthy)             0.0.0.0:7474->7474, 0.0.0.0:7687->7687
```

그래프가 비어 있지 않은지 확인한다. 비어 있으면 먼저 02 적재 → 04 임베딩/인덱스를 끝내야 한다.

```bash
docker compose exec neo4j cypher-shell -u neo4j -p testpassword1 \
  "MATCH (n) RETURN count(n) AS nodes;"
```

예상 출력:

```
+-------+
| nodes |
+-------+
| 14    |
+-------+
```

`14` (Entity 12 + Event 2)가 나오면 정상이다. `0` 이면 02→04 를 먼저 끝낸다.

---

## (1) 투영 생성 / 조회 (GDS in-memory 카탈로그)

GDS 알고리즘은 디스크 그래프를 직접 안 돌린다. 먼저 메모리에 투영해야 한다.
`gds_projection.cypher` 의 핵심만 cypher-shell 로 확인해 본다.

```bash
docker compose exec neo4j cypher-shell -u neo4j -p testpassword1 \
  "CALL gds.graph.project('entityGraph','Entity',{ALL_REL:{type:'*',orientation:'UNDIRECTED'}}) YIELD graphName,nodeCount,relationshipCount RETURN graphName,nodeCount,relationshipCount;"
```

예상 출력:

```
+--------------------------------------------------+
| graphName     | nodeCount | relationshipCount    |
+--------------------------------------------------+
| "entityGraph" | 12        | 18                   |
+--------------------------------------------------+
```

Entity 12개가 노드로, 엔티티 간 관계 9개가 무방향이라 양방향 18개로 투영된다.
(Event 2개와 ABOUT 2개는 투영에서 제외했다 — PageRank·Leiden 은 Entity 연결 구조만 본다.)

카탈로그를 조회하고, 확인 후 지운다.

```bash
docker compose exec neo4j cypher-shell -u neo4j -p testpassword1 \
  "CALL gds.graph.list() YIELD graphName,nodeCount,relationshipCount RETURN graphName,nodeCount,relationshipCount;"
docker compose exec neo4j cypher-shell -u neo4j -p testpassword1 \
  "CALL gds.graph.drop('entityGraph', false) YIELD graphName RETURN graphName;"
```

`list` 는 `entityGraph` 한 줄, `drop` 은 `"entityGraph"` 를 돌려준다.

> 참고: pagerank.py·leiden.py·quality_dashboard.py 는 **각자 자기 투영을 만들고 끝나면 스스로 지운다.**
> 위 수동 투영은 메커니즘 확인용이다(이름이 겹치지 않게 직접 만든 건 직접 지웠다).

---

## (2) PageRank — 중심 노드(허브) 뽑기

```bash
python pagerank.py --top 5
```

예상 출력(점수는 환경에 따라 다를 수 있다 — 순위와 "평평함"을 본다):

```
[투영] entityGraph_pagerank — nodes=12 rels=18 (UNDIRECTED)

[PageRank] score 내림차순 top-5 — '연결 구조상 중심' 엔티티
  rank score       type          name
  1    0.21834     Model         RAG
  2    0.19460     Model         GraphRAG
  3    0.16127     Model         LightRAG
  4    0.15003     Concept       retrieval quality
  5    0.13988     Organization  Microsoft

[정리] entityGraph_pagerank drop 완료.

[해석] 점수가 서로 비슷하면 그래프가 작아 허브가 덜 두드러진 것이다(정상).
       상위 노드는 Phase 4 검색에서 후보 우선순위·엔트리포인트로 쓰인다.
```

읽는 법: 점수 절대값보다 **순위**가 의미 있다. 여러 관계의 허브인 `RAG`·`GraphRAG` 가 위로 온다.
12개 그래프라 1위와 5위의 격차가 크지 않다 — 규모가 작아 허브가 덜 두드러진 것이다(정상).

---

## (3) Leiden — 커뮤니티(밀집 군집) 나누기

```bash
python leiden.py
```

예상 출력(커뮤니티 개수·ID 는 환경에 따라 다를 수 있다):

```
[투영] entityGraph_leiden — nodes=12 rels=18 (UNDIRECTED, Leiden 필수)

[Leiden] 커뮤니티 2개 — 서로 촘촘히 연결된 엔티티 무리
  community 0 (7개): CRAG, GraphRAG, LightRAG, Microsoft, Neo4j, RAG, Self-RAG
  community 1 (5개): HKUDS, LangChain, NeurIPS, multi-hop, retrieval quality

[정리] entityGraph_leiden drop 완료.

[해석] 작은 그래프라 커뮤니티가 1~2개로 뭉쳐도 정상이다.
       이 커뮤니티 분할이 Phase 4/03 Global Retriever 의 요약·map-reduce 입력이 된다.
```

작은 그래프라 커뮤니티가 1~2개로 뭉치는 게 정상이다. 코퍼스를 키우면 주제별로 더 갈라진다.

이번엔 결과를 디스크에 기록한다(Phase 4 Global Retriever 가 읽을 `e.community`).

```bash
python leiden.py --write
```

예상 출력 끝부분에 write 통계가 더 붙는다:

```
[write] e.community 기록 완료 — communityCount=2 modularity=0.3xxx nodePropertiesWritten=12
  이후 일반 Cypher 로 확인: MATCH (e:Entity) RETURN e.community, collect(e.name)
```

`nodePropertiesWritten=12` 면 Entity 12개 전부에 `community` 가 붙었다는 뜻이다.

---

## (4) Graph Quality Dashboard — 건강검진

`leiden.py --write` 를 먼저 돌려야 7번(커뮤니티) 항목이 채워진다.

```bash
python quality_dashboard.py --top 5
```

예상 출력(요지 — 숫자는 위 (0)~(3) 과 일관된다):

```
============================================================
 Graph Quality Dashboard — 적재된 그래프 건강검진
============================================================
[투영] entityGraph_dashboard — nodes=12 rels=18 (UNDIRECTED)

────────────────────────────────────────────────────────────
■ 1) 규모 — 노드·관계 총수와 분포
────────────────────────────────────────────────────────────
  전체 노드                  14
  전체 관계                  11
  라벨별 노드:
    - Entity          12
    - Event           2
  관계 타입별:
    - IMPROVES        4
    - DEVELOPED_BY    2
    - USES            2
    - ABOUT           2
    - COMPARES_TO     1

────────────────────────────────────────────────────────────
■ 2) 고립 노드 — 아무 관계도 없는 노드(적재 누락 신호)
────────────────────────────────────────────────────────────
  고립 노드                   없음 (모든 노드가 최소 1개 관계를 가짐)

────────────────────────────────────────────────────────────
■ 4) 자기 루프 — (a)-[r]->(a) 자기 참조(보통 추출 오류)
────────────────────────────────────────────────────────────
  자기 루프                   없음

────────────────────────────────────────────────────────────
■ 5) 중복 후보 — 같은 name, 다른 canonical_id(엔티티 해소 누락)
────────────────────────────────────────────────────────────
  중복 후보                   없음 (name 하나당 canonical_id 하나)

────────────────────────────────────────────────────────────
■ 6) 미해소 노드 — 02 가 fallback 으로 만든 unresolved=true
────────────────────────────────────────────────────────────
  미해소 노드 수               1
    - LangChain

────────────────────────────────────────────────────────────
■ 7) 커뮤니티 분포 — Leiden(e.community) 개수·크기
────────────────────────────────────────────────────────────
  커뮤니티 개수                2
    - community 0: 7개
    - community 1: 5개

────────────────────────────────────────────────────────────
■ 3) degree 분포 — 연결 수 최대/평균과 허브 top-k
────────────────────────────────────────────────────────────
  최대 degree                5
  평균 degree                1.57
  degree 허브 top-5 (Entity 무방향 투영):
    1. RAG                   degree=5.0
    2. GraphRAG             degree=3.0
    3. LightRAG            degree=2.0
    4. retrieval quality  degree=2.0
    5. Microsoft          degree=2.0

────────────────────────────────────────────────────────────
■ 8) PageRank top-5 — 연결 구조상 중심 엔티티
────────────────────────────────────────────────────────────
    1. RAG                   score=0.21834
    2. GraphRAG             score=0.19460
    ...

============================================================
 건강검진 끝. 고립 노드·중복 후보·자기 루프가 0 이면 적재가 깨끗하다는 신호다.
============================================================
```

읽는 법:
- **규모**: 14 노드 / 11 관계가 02 적재 결과와 정확히 맞으면 적재 누락이 없다.
- **고립 노드 0 · 자기 루프 0 · 중복 후보 0**: 깨끗한 적재의 3대 신호.
- **미해소 노드 1(LangChain)**: 02 가 엔티티 집합에 없던 endpoint 에 fallback 으로 만든 노드.
  버그가 아니라 "추후 보강 추적" 표식이다. 02 lesson 의 unresolved 처리와 이어진다.
- 14 노드인데 투영은 12 노드인 이유: 투영은 Entity 만 담는다(Event 2개 제외).

---

## (5) 정리 — 투영·속성 비우기

각 스크립트가 자기 투영을 스스로 지우지만, 중간에 멈췄거나 수동 투영이 남았을 수 있다.
`cleanup_gds.cypher` 로 한 번에 비운다.

```bash
docker compose exec -T neo4j cypher-shell -u neo4j -p testpassword1 < cleanup_gds.cypher
```

예상 출력(요지): 남은 투영이 있으면 drop 되고, 마지막에 `remaining_projections 0` 이 나온다.

```
remaining_projections
0
community_left
0
```

> `e.community` 를 Phase 4 에서 다시 쓸 거면 3번 단계의 `REMOVE e.community` 는 건너뛰어도 된다.
> 컨테이너 자체를 내리려면 `docker compose down`(볼륨 유지) / `down -v`(데이터 삭제).

---

## 완료 체크

- [ ] (0) `count(n)` 이 14 로 나온다(02→04 적재 완료).
- [ ] (1) 투영이 nodes=12 / rels=18 로 만들어진다.
- [ ] (2) PageRank top-k 가 score 내림차순으로 나온다(상위가 RAG·GraphRAG 류).
- [ ] (3) Leiden 이 커뮤니티 1~2개를 만들고, `--write` 로 `e.community` 가 12개 노드에 기록된다.
- [ ] (4) 대시보드가 규모·고립·중복·degree·커뮤니티를 한 표로 출력한다.
- [ ] (5) `cleanup_gds.cypher` 로 투영이 0개가 된다.
