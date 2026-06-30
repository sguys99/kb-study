# 3.6 GDS PageRank · Leiden + Graph Quality Dashboard

> **Phase 3 · 토픽 06** · 02 가 적재하고 04 가 인덱싱한 같은 그래프를 GDS 로 투영해 중심 노드(PageRank)와 커뮤니티(Leiden)를 뽑고, 품질 대시보드로 적재 결과를 건강검진한다. Phase 3 의 마무리이자 Phase 4 검색의 재료를 만드는 토픽이다.

## 학습 목표

이 토픽을 끝내면 다음을 할 수 있다.

- 디스크 그래프를 GDS in-memory 카탈로그로 **투영**하고, `gds.graph.list`·`drop` 으로 카탈로그를 관리한다.
- `gds.pageRank.stream` 으로 중심 노드(허브)를 score 내림차순으로 **뽑고**, 작은 그래프에서 점수가 평평하게 나오는 것을 정직하게 해석한다.
- `gds.leiden.stream`/`write` 로 그래프를 커뮤니티로 **나누고**, 그 결과가 Phase 4 Global Retriever 의 입력임을 안다.
- 고립 노드·중복 후보·degree 분포·커뮤니티 크기를 한 표로 모으는 품질 대시보드로 적재 그래프를 **건강검진한다**.

**완료 기준**: 같은 그래프를 GDS로 투영해 PageRank top-k 허브와 Leiden 커뮤니티를 뽑고, quality_dashboard.py가 고립 노드·degree 분포·커뮤니티 크기를 한 표로 출력하면 완료.

---

## 1. 왜 필요한가 — 적재·질의를 넘어 "구조"를 본다

01 부터 05 까지 우리는 그래프를 적재하고, 멀티홉으로 질의하고, 하이브리드로 검색하고, 튜닝하고 가드했다. 전부 **노드를 하나씩, 경로를 하나씩** 다루는 일이었다. 한 발짝 물러서서 그래프 **전체의 모양**을 묻는 질문은 아직 안 했다.

이 그래프에서 가장 중심에 있는 엔티티는 뭘까. 어떤 엔티티들이 한 무리로 뭉쳐 있을까. 적재가 끝난 그래프에 끊긴 데나 중복은 없을까. 이런 질문은 경로 하나로는 답이 안 나온다. 그래프 알고리즘이 필요하다.

여기서 GDS(Graph Data Science)가 들어온다. 01 에서 개요만 봤던 그 라이브러리다. PageRank 로 중심 노드를, Leiden 으로 커뮤니티를 뽑는다. 이 둘은 다음 Phase 로 곧장 이어진다. Leiden 커뮤니티는 Phase 4 Global Retriever 가 "커뮤니티별 요약 → map-reduce" 로 전체 요약 질문에 답할 때 재료가 되고, PageRank 중심 노드는 검색 후보의 우선순위·엔트리포인트로 쓰인다. 06 의 출력이 곧 Phase 4 의 입력인 셈이다.

한 가지는 미리 솔직히 밝혀 둔다. **우리 그래프는 작다.** Entity 12개에 엔티티 간 관계가 9개뿐이다. PageRank 의 허브 분리든 Leiden 의 커뮤니티 분할이든, 규모가 어느 정도 커야 또렷해진다. 12개짜리에선 점수가 평평하게 나오고 커뮤니티도 1~2개로 뭉친다. 그러니 이 토픽의 목표는 "극적인 결과"가 아니다. 알고리즘을 돌리는 메커니즘과 그 결과를 읽어 내는 법, 거기에 있다. 코퍼스를 Phase 1~2 에서 50~100건으로 키우고 나면 이 알고리즘들이 비로소 제 힘을 낸다.

## 2. 그래프 투영 — GDS 는 메모리 사본 위에서 돈다

GDS 알고리즘은 디스크의 Neo4j 그래프를 직접 돌리지 않는다. 먼저 **in-memory 그래프 카탈로그**에 사본을 올린다. 이걸 투영(projection)이라 한다. 알고리즘은 그 메모리 사본 위에서 계산한다. 그래서 PageRank·Leiden 을 부르기 전에 **항상 투영이 먼저** 있어야 한다.

native projection 은 `gds.graph.project` 로 만든다. 노드 라벨과 관계를 골라 담는다. 우리 관심사는 엔티티끼리의 연결 구조라, Entity 노드와 엔티티 간 관계만 담는다(Event·ABOUT 은 뺀다).

```cypher
// practice/gds_projection.cypher 의 핵심 — Entity + 엔티티 간 관계를 무방향으로 투영
CALL gds.graph.project(
  'entityGraph',
  'Entity',                                  // 노드: Entity 라벨만
  { ALL_REL: { type: '*', orientation: 'UNDIRECTED' } }  // 관계: 모든 타입('*'), 무방향
)
YIELD graphName, nodeCount, relationshipCount;
// 기대: nodeCount=12, relationshipCount=18 (관계 9개를 무방향으로 → 양방향 18)
```

관계 타입이 4종(COMPARES_TO·DEVELOPED_BY·IMPROVES·USES)이라 `type: '*'` 로 전부 한 묶음에 담았다. 핵심은 `orientation: 'UNDIRECTED'` 다. Leiden 은 무방향 그래프에서만 동작하고, PageRank 도 우리처럼 관계 방향의 의미가 제각각인 작은 그래프에선 무방향 해석이 읽기 쉽다. PageRank·Leiden 을 같은 투영으로 돌리려는 목적도 있다.

투영은 메모리를 점유한다. 다 쓰면 `gds.graph.drop('entityGraph')` 로 반드시 지운다. 안 지우면 같은 이름으로 재투영할 때 충돌하고 메모리도 계속 잡고 있다. `gds.graph.list` 로 지금 떠 있는 투영을 확인할 수 있다.

## 3. 실습 ① — PageRank 로 허브 뽑기

PageRank 는 "중요한 노드가 가리키는 노드는 중요하다"를 반복 계산해 노드마다 점수를 매긴다. 웹페이지 랭킹에서 온 알고리즘인데, 그래프에선 "연결 구조상 중심에 있는 노드"를 찾는 데 쓴다.

stream 과 write 를 구분해야 한다. `stream` 은 점수를 결과 행으로만 돌려준다. 그래프엔 아무것도 안 쓴다(읽기 전용 탐색). `write` 는 점수를 노드 속성으로 디스크에 기록하고, `mutate` 는 투영(메모리)에만 쓴다. 점수를 그냥 보고 싶으면 stream, 나중에 재사용하려면 write 다.

```python
# practice/pagerank.py 의 핵심 — stream 으로 점수만 보고, gds.util.asNode 로 이름을 되돌린다
def run_pagerank_stream(driver, name: str, top: int) -> list[dict]:
    cypher = """
    CALL gds.pageRank.stream($name)
    YIELD nodeId, score
    RETURN gds.util.asNode(nodeId).name AS name,
           gds.util.asNode(nodeId).type AS type,
           score
    ORDER BY score DESC, name ASC
    LIMIT $top
    """
    with driver.session() as session:
        return [dict(r) for r in session.run(cypher, name=name, top=top)]
```

`gds.pageRank.stream` 은 (nodeId, score) 를 준다. nodeId 는 투영 내부의 id 라, `gds.util.asNode(nodeId)` 로 원래 Entity 노드를 되찾아 name·type 을 읽는다. score 내림차순으로 정렬해 top-k 만 본다.

> 전체 코드와 실행 절차는 [`practice/`](practice/) 와 [`labs/`](labs/) 참조.
> 이 토픽은 LLM·임베딩 API 를 쓰지 않는다. PageRank·Leiden·degree 는 GDS·드라이버만으로 돈다. 키 불필요, 과금 0.

## 4. 결과 해석 ① — 점수가 평평한 건 정상이다

`python pagerank.py --top 5` 의 출력은 이렇게 나온다(점수는 환경에 따라 다를 수 있다).

```
[PageRank] score 내림차순 top-5 — '연결 구조상 중심' 엔티티
  1    0.21834     Model         RAG
  2    0.19460     Model         GraphRAG
  3    0.16127     Model         LightRAG
  4    0.15003     Concept       retrieval quality
  5    0.13988     Organization  Microsoft
```

여러 관계의 허브인 `RAG`·`GraphRAG` 가 위로 온다. 점수의 절대값보다 **순위**가 의미 있다. 1위와 5위의 격차가 크지 않은데, 그래프가 12개뿐이라 허브가 덜 두드러져서다. 이건 데이터 문제도 코드 문제도 아니다. 규모의 문제다. 노드가 수천 개로 늘면 진짜 허브 몇 개가 점수에서 확 치고 올라온다. 작은 그래프에선 "순위는 읽히지만 격차는 작다"가 정상적인 그림이다.

이 상위 노드들이 Phase 4 검색에서 후보 우선순위·엔트리포인트로 쓰인다. 질문이 들어오면 "중심 노드에서 출발해 이웃으로 퍼지는" 전략이 자연스럽기 때문이다.

## 5. 실습 ② — Leiden 으로 커뮤니티 나누기

PageRank 가 "누가 중심인가"라면, Leiden(커뮤니티 탐지)은 "누가 누구와 한 무리인가"다. 서로 촘촘히 연결된 노드들을 같은 communityId 로 묶는다. modularity(군집성)를 최대화하는 방향으로 반복하며 군집을 다듬는다.

Leiden 은 무방향 그래프에서 동작한다. 그래서 2절의 투영에서 `orientation: 'UNDIRECTED'` 가 필수였다. 방향 그래프로 투영하면 에러가 난다.

```python
# practice/leiden.py 의 핵심 — stream 으로 (name, communityId) 를 받아 그룹으로 묶는다
def run_leiden_stream(driver, name: str) -> list[dict]:
    cypher = """
    CALL gds.leiden.stream($name)
    YIELD nodeId, communityId
    RETURN gds.util.asNode(nodeId).name AS name, communityId
    ORDER BY communityId ASC, name ASC
    """
    with driver.session() as session:
        return [dict(r) for r in session.run(cypher, name=name)]
```

`--write` 를 주면 `gds.leiden.write` 가 communityId 를 `e.community` 속성으로 디스크에 기록한다. 이게 Phase 4 Global Retriever 가 읽을 입력이다. write 모드는 communityCount·modularity 같은 요약 통계도 함께 돌려준다.

## 6. 결과 해석 ② — 작은 그래프는 커뮤니티가 뭉친다

`python leiden.py` 의 출력이다.

```
[Leiden] 커뮤니티 2개 — 서로 촘촘히 연결된 엔티티 무리
  community 0 (7개): CRAG, GraphRAG, LightRAG, Microsoft, Neo4j, RAG, Self-RAG
  community 1 (5개): HKUDS, LangChain, NeurIPS, multi-hop, retrieval quality
```

커뮤니티가 2개로 나뉘었다. 12개 그래프라 이렇게 1~2개로 뭉치는 게 정상이다. 연결이 한 덩어리로 이어져 있어 잘게 안 갈린다. 코퍼스를 키우면 "검색 기법 군집", "조직·발표 군집"처럼 주제별로 더 또렷하게 갈라진다. communityId 의 숫자값 자체는 의미가 없다(0·1 은 그냥 라벨이다). 어떤 노드들이 **같은 ID 로 묶였는가**가 정보다.

이 커뮤니티 분할이 Phase 4/03 Global Retriever 의 시작점이다. 전체 요약 질문("이 코퍼스의 핵심 흐름은?")이 들어오면, Global Retriever 는 개별 노드가 아니라 **커뮤니티별 요약**을 만들고 그것들을 map-reduce 로 종합한다. 그 첫 단추인 커뮤니티 경계를 06 에서 긋는 셈이다.

## 7. 실습 ③ — Graph Quality Dashboard

Phase 2 의 품질 게이트가 그래프를 만들기 *전* 입력을 거른 검문소였다면, 이 대시보드는 그래프를 만든 *후* 적재 결과를 점검하는 사후 진단이다. 적재된 그래프가 멀쩡한지, 끊긴 데가 없는지, 중복이 새지 않았는지를 숫자로 본다. 전부 순수 Cypher + GDS degree 로 계산한다.

```python
# practice/quality_dashboard.py 의 핵심 지표 두 개 — 고립 노드와 중복 후보
def isolated_nodes(session) -> None:
    # degree 0 인 노드 = 아무 관계도 없는 떠 있는 노드(적재 누락 신호)
    rows = list(session.run(
        "MATCH (n) WHERE NOT (n)--() "
        "RETURN labels(n) AS labels, coalesce(n.name, n.event_id, '?') AS id ORDER BY id"
    ))
    ...

def duplicate_candidates(session) -> None:
    # 같은 name 인데 canonical_id 가 다른 엔티티 = 엔티티 해소가 놓친 쌍
    rows = list(session.run(
        "MATCH (e:Entity) "
        "WITH e.name AS name, collect(DISTINCT e.canonical_id) AS ids "
        "WHERE size(ids) > 1 RETURN name, ids ORDER BY name"
    ))
    ...
```

대시보드가 모으는 지표는 규모(노드/관계 총수·라벨별·관계타입별 분포), 고립 노드, degree 분포(최대/평균 + GDS degree 허브 top-k), 자기 루프, 중복 후보, 미해소 노드, 커뮤니티 분포, PageRank top-k 다. 한 번 돌리면 적재 그래프의 건강 상태가 표 하나로 보인다.

## 8. 결과 해석 ③ — 깨끗한 적재의 신호

`python quality_dashboard.py` 출력의 요지다.

```
■ 1) 규모 — 전체 노드 14 / 전체 관계 11
    Entity 12, Event 2 / IMPROVES 4, DEVELOPED_BY 2, USES 2, ABOUT 2, COMPARES_TO 1
■ 2) 고립 노드 — 없음
■ 4) 자기 루프 — 없음
■ 5) 중복 후보 — 없음 (name 하나당 canonical_id 하나)
■ 6) 미해소 노드 — 1 (LangChain)
■ 7) 커뮤니티 — 2개 (community 0: 7개, community 1: 5개)
```

읽는 법은 단순하다. 노드 14·관계 11 이 02 적재 결과와 정확히 맞으면 누락이 없다. 고립 노드·자기 루프·중복 후보가 모두 0 이면 깨끗한 적재의 3대 신호다. 미해소 노드 1개(LangChain)는 버그가 아니다. 02 가 엔티티 집합에 없던 endpoint 에 fallback 으로 만든 노드이고, `unresolved=true` 표식은 "추후 보강 추적용"이다. 02 lesson 의 미해소 처리와 그대로 이어진다.

투영은 12 노드인데 그래프 전체는 14 노드인 점도 짚어 둔다. 투영에 Entity 만 담고 Event 2개를 뺐기 때문이다. 이 차이를 헷갈리면 "노드가 사라졌다"고 오해하기 쉽다. degree·PageRank 는 투영(12) 기준, 규모 집계는 전체 그래프(14) 기준이다.

---

## 🚨 자주 하는 실수

1. **투영을 안 만들고 알고리즘부터 호출한다** — `gds.pageRank.stream('entityGraph')` 는 `entityGraph` 투영이 카탈로그에 있어야 돈다. 없으면 "graph does not exist" 에러다. GDS 는 항상 투영(`gds.graph.project`) → 알고리즘 → drop 순서다. 디스크 그래프를 직접 가리킬 수 없다.
2. **Leiden 을 방향 그래프로 투영해 에러를 만난다** — Leiden 은 무방향 그래프에서만 동작한다. `orientation: 'UNDIRECTED'` 를 빼면 "must be UNDIRECTED" 류 에러가 난다. PageRank·Leiden·degree 를 같은 무방향 투영으로 돌리면 해석 기준도 일관된다.
3. **작은 그래프의 점수를 과대해석한다** — 12개 그래프에서 PageRank 점수가 비슷하게 평평하고 Leiden 커뮤니티가 1~2개로 뭉치는 건 정상이다. "허브가 안 보인다 = 데이터가 틀렸다"가 아니다. 규모의 문제다. 절대값보다 순위·그룹을 읽고, 효과를 보려면 코퍼스를 키운다. 그리고 다 쓴 투영은 `gds.graph.drop` 으로 꼭 지운다 — 안 지우면 이름 충돌과 메모리 누수가 쌓인다.

## 출처

- Neo4j Documentation — https://neo4j.com/docs/
- Neo4j Python Driver Manual — https://neo4j.com/docs/python-manual/current/
- Neo4j Graph Data Science Library Manual — https://neo4j.com/docs/graph-data-science/current/
- GDS PageRank — https://neo4j.com/docs/graph-data-science/current/algorithms/page-rank/
- GDS Leiden — https://neo4j.com/docs/graph-data-science/current/algorithms/leiden/

## 다음 토픽

→ [GraphRAG Method Map (Local · Global · Path · Community · Memory)](../../phase-04-graphrag-lightrag/01-graphrag-method-map/lesson.md)
