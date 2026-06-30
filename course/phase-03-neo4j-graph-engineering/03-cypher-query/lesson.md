# 3.3 Cypher Query — 패턴 매칭·멀티홉·경로·집계

> **Phase 3 · 토픽 03** · 02가 Neo4j에 적재한 그래프 위에서 Cypher로 멀티홉·경로·집계 질의를 돌려, Vector RAG가 틀렸던 질문에 정답을 뽑는다.

## 학습 목표

이 토픽을 끝내면 다음을 할 수 있다.

- `MATCH` 패턴과 `WHERE`로 라벨·관계 방향을 지정해 그래프에서 원하는 부분만 뽑아낸다.
- 중간 노드를 명시한 멀티홉 질의와 가변 길이 경로(`*1..3`)·`shortestPath()`로 "두 엔티티가 어떻게 이어지는지"를 답한다.
- `count()`·`collect()`·`WITH` 파이프라인으로 차수(degree)를 집계해 "가장 많이 참조되는 엔티티"를 찾고, `OPTIONAL MATCH`로 고립 노드를 가려낸다.

**완료 기준**: 02가 적재한 그래프(nodes=14, rels=11, events=2)에서 멀티홉·경로·집계 Cypher 질의가 아래 본문의 기대 결과(예: "RAG를 개선하는 것 중 무언가를 쓰는 건 CRAG→LangChain", "LightRAG↔RAG 최단 경로 길이 2", "최다 피참조 엔티티 RAG, in-degree 3")와 일치하면 완료.

---

## 1. 왜 필요한가 — Vector RAG가 무너졌던 질문

Phase 0에서 RAG가 무너지는 네 가지를 봤다. 그중 두 가지가 여기서 정면으로 풀린다.

"RAG를 개선하는 모델들은 각각 무슨 도구를 쓰지?" 이 질문은 한 청크 안에 답이 없다. 'X improves RAG'는 한 문서에, 'X uses Y'는 다른 문서에 흩어져 있다. 벡터 검색은 질문과 비슷한 문장을 끌어올 뿐 두 사실을 연결하지는 못한다. 멀티홉이 무너지는 지점이다.

"LightRAG와 RAG는 어떻게 연결돼 있나?" 둘을 직접 언급한 문장이 없으면 벡터 검색은 빈손이다. 그런데 그래프에는 `LightRAG -[:COMPARES_TO]- GraphRAG -[:IMPROVES]-> RAG` 라는 두 칸짜리 길이 실제로 있다. 경로(path) 질의가 이걸 찾는다.

02가 적재해 둔 그래프는 이미 엔티티·관계·이벤트가 명시적 구조로 들어가 있다. 이제 그 위에서 Cypher로 순회·경로·집계를 돌리면 벡터로는 안 나오던 답이 결정적으로 떨어진다. 여기서 다루는 질의 패턴들이 다음 토픽 04 하이브리드 검색의 그래프 절반을 이룬다.

## 2. 핵심 개념 — Cypher는 ASCII 그림으로 패턴을 그린다

Cypher의 발상은 단순하다. 노드는 괄호 `()`, 관계는 화살표 `-->`. 찾고 싶은 모양을 그대로 그림으로 그리면 그게 질의다.

```cypher
(a:Entity)-[:USES]->(b:Entity)
```

`a`가 `b`를 USES하는 패턴이다. `:Entity`는 라벨, `:USES`는 관계 타입, 화살표는 방향이다. 여기서 방향이 핵심이다. `LightRAG -USES-> Neo4j`는 있어도 그 반대는 없다. 방향을 빼면(`-[:USES]-`) 양방향으로 매칭돼 의도와 다른 결과가 나온다.

질의는 보통 `MATCH`(패턴 찾기) → `WHERE`(거르기) → `RETURN`(돌려주기) 흐름이다. SQL의 `SELECT … FROM … WHERE`에 대응하지만, 조인 대신 화살표로 관계를 직접 따라간다는 점이 다르다. 멀티홉이 자연스러운 이유다.

우리가 질의할 그래프 모델(02 적재 결과)은 이렇다.

- `(:Entity {canonical_id, name, type, ...})` — canonical_id 유니크, name 인덱스
- 관계 `[:USES] [:IMPROVES] [:DEVELOPED_BY] [:COMPARES_TO]` — 모두 Entity→Entity, 방향 있음
- `(:Event {event_id, type, time, ...})-[:ABOUT]->(:Entity)`

## 3. 실습 — 다섯 가지 질의 패턴

전체 질의 모음은 [`practice/queries.cypher`](practice/queries.cypher)에 있다. 핵심 멀티홉·경로·집계는 [`practice/run_queries.py`](practice/run_queries.py)가 Python Driver로 실행해 결과를 정리해 보여준다. 아래는 본문에서 짚을 핵심 조각이다.

### (a) 패턴 매칭 — 기본

"무엇이 무엇을 쓰는가(USES)?"

```cypher
// LightRAG 가 쓰는 도구를 찾는다. 방향을 정확히 head -> tail 로 그린다.
MATCH (a:Entity {name: "LightRAG"})-[:USES]->(b:Entity)
RETURN a.name AS user, b.name AS used;
```

`name` 인덱스 덕에 시작 노드를 빠르게 잡는다. 결과는 `LightRAG → Neo4j` 한 건. 조건을 더 붙이고 싶으면 `WHERE`를 쓴다.

```cypher
// USES 관계 전체를, tail 의 type 이 Tool 인 것만.
MATCH (a:Entity)-[:USES]->(b:Entity)
WHERE b.type = "Tool"
RETURN a.name AS user, b.name AS tool;
```

### (b) 멀티홉 순회 — 두 칸을 잇는다

"RAG를 개선하는 것들은 각각 무엇을 쓰는가?" 한 청크에는 없는 답이다. 중간 노드 `x`를 두고 두 관계를 연달아 그린다.

```cypher
// 1홉: x 가 RAG 를 IMPROVES.  2홉: 그 x 가 무언가를 USES.
MATCH (x:Entity)-[:IMPROVES]->(:Entity {name: "RAG"})
MATCH (x)-[:USES]->(tool:Entity)
RETURN x.name AS improver, tool.name AS uses_tool;
```

RAG를 개선하는 건 Self-RAG·CRAG·GraphRAG 셋이다. 그중 USES 엣지가 있는 건 CRAG뿐이라 결과는 `CRAG → LangChain` 한 줄이다. 두 사실이 서로 다른 출처에서 왔어도 그래프가 이어 붙인다. 이게 멀티홉의 핵심이다.

### (c) 가변 길이 경로 + 최단 경로

"LightRAG와 RAG는 어떻게 연결돼 있나?" 직접 관계는 없다. 몇 홉이 걸릴지 모르니 가변 길이로 그리고, 방향은 무시한 채 연결만 본다(`-[*1..3]-`).

```cypher
// 1~3홉 안에서 둘을 잇는 경로를 모두 본다. 상한(..3)을 꼭 준다.
MATCH p = (a:Entity {name: "LightRAG"})-[*1..3]-(b:Entity {name: "RAG"})
RETURN [n IN nodes(p) | n.name] AS hops, length(p) AS hop_count
ORDER BY hop_count
LIMIT 5;
```

가장 짧은 길 하나만 필요하면 `shortestPath()`를 쓴다.

```cypher
MATCH (a:Entity {name: "LightRAG"}), (b:Entity {name: "RAG"})
MATCH p = shortestPath((a)-[*1..5]-(b))
RETURN [n IN nodes(p) | n.name] AS path, length(p) AS hops;
```

최단 경로는 `LightRAG — GraphRAG — RAG`, 길이 2다(`COMPARES_TO` 그리고 `IMPROVES`). 벡터 검색에는 "LightRAG와 RAG가 연결됐다"는 문장이 없어 답이 안 나오지만, 그래프는 우회로를 찾아낸다.

### (d) 집계 — 가장 많이 참조되는 엔티티

`count()`로 들어오는 관계 수(in-degree)를 세면 "허브"가 보인다. `WITH`는 중간 결과를 다음 단계로 넘기는 파이프라인 연산자다. 집계한 뒤 정렬하려면 거의 언제나 `WITH`가 필요하다.

```cypher
// 각 엔티티로 들어오는 관계 수를 세어 내림차순.
MATCH (n:Entity)<-[r]-()
WITH n, count(r) AS in_degree
RETURN n.name AS entity, in_degree
ORDER BY in_degree DESC
LIMIT 5;
```

RAG가 in-degree 3으로 1위다(Self-RAG·CRAG·GraphRAG가 모두 RAG를 가리킨다). 누가 가리키는지 이름까지 묶어 보려면 `collect()`를 쓴다.

```cypher
MATCH (n:Entity)<-[:IMPROVES]-(m:Entity)
WITH n, collect(m.name) AS improvers, count(m) AS cnt
RETURN n.name AS improved, improvers, cnt
ORDER BY cnt DESC;
```

고립 노드(아무 관계도 없는 엔티티)는 `OPTIONAL MATCH`로 찾는다. `OPTIONAL MATCH`는 매칭이 없어도 행을 버리지 않고 `null`을 채운다.

```cypher
// 관계가 하나도 없는 엔티티 = 적재됐지만 아직 안 이어진 노드.
MATCH (n:Entity)
OPTIONAL MATCH (n)-[r]-()
WITH n, count(r) AS deg
WHERE deg = 0
RETURN n.name AS isolated;
```

### (e) Event 질의 — 시점을 가진 사실

이벤트는 `(:Event)-[:ABOUT]->(:Entity)`로 엔티티에 걸린다. `time` 속성이 "언제 발표됐는가"를 답해 준다.

```cypher
// 각 엔티티가 어떤 PUBLICATION 이벤트로 언제 발표됐는지.
MATCH (e:Event)-[:ABOUT]->(n:Entity)
RETURN n.name AS entity, e.type AS event_type, e.time AS year
ORDER BY year;
```

RAG는 2020, GraphRAG는 2024. 시점이 들어간 질문("2020년에 발표된 건?")은 `WHERE e.time = "2020"`으로 거른다.

> 전체 코드와 실행 절차는 [`practice/`](practice/)와 [`labs/`](labs/) 참조. 이 토픽은 LLM·임베딩 API를 쓰지 않으므로 키가 필요 없고 과금도 없다(로컬 Neo4j만). Neo4j를 띄울 여건이 안 되면 02의 docker-compose로 같은 컨테이너를 재사용하면 된다.

## 4. 결과 해석 — 왜 Vector RAG로는 안 나오는가

(b)의 `CRAG → LangChain`은 두 문장이 서로 다른 문서에서 왔다. 'CRAG improves RAG'(src-03)와 'CRAG uses LangChain'(src-03 다른 구간)을 벡터 검색이 한 번에 끌어와도, LLM이 "RAG 개선 모델의 도구"라는 두 단계 추론을 매번 정확히 하리라는 보장은 없다. 그래프는 추론이 아니라 순회로 답한다. 같은 입력이면 같은 답이 결정적으로 나온다.

(c)의 최단 경로가 가장 극적이다. "LightRAG와 RAG의 관계"를 직접 서술한 문장은 코퍼스에 없다. 벡터 검색은 의미가 가까운 문장을 찾는 도구라, 존재하지 않는 연결을 만들어내지 못한다. 반면 그래프는 `COMPARES_TO`와 `IMPROVES`를 이어 길이 2짜리 경로를 반환한다. 이것이 "Vector RAG가 못하던 것"의 본질이다.

(d)의 집계도 마찬가지다. "가장 많이 개선 대상이 되는 모델"은 전체 그래프를 훑어 세야 나오는 답이다. 벡터 top-k는 일부 청크만 보므로 전역 집계를 못 한다. Cypher는 그래프 전체에서 `count()`로 정확한 숫자를 돌려준다.

---

## 🚨 자주 하는 실수

1. **관계 방향을 빠뜨린다.** `(a)-[:USES]->(b)`와 `(a)-[:USES]-(b)`는 다르다. 후자는 방향 무시라 의도치 않은 행이 섞인다. "누가 무엇을 쓰는가"처럼 방향이 의미를 가지면 화살표를 명시하고, 경로 탐색처럼 연결만 보면 일부러 방향을 뺀다. 둘을 구분해서 쓴다.
2. **가변 길이에 상한을 안 준다.** `-[*]-`나 `-[*1..]-`는 그래프가 크면 경로가 폭발해 질의가 영영 안 끝난다. 항상 `-[*1..3]-`처럼 상한을 박고, 최단 경로면 `shortestPath()`를 쓴다.
3. **집계할 때 `WITH`를 빼먹거나 Cartesian product를 만든다.** `count()`·`collect()` 뒤에 정렬·필터를 하려면 `WITH`로 중간 결과를 넘겨야 한다. 또 `MATCH (a), (b)`처럼 연결되지 않은 두 패턴을 한 `MATCH`에 나란히 쓰면 모든 a×b 조합(Cartesian product)이 나온다. 둘을 잇는 관계나 `WHERE` 조건을 반드시 건다.

## 출처

- Neo4j 공식 문서 — https://neo4j.com/docs/
- Neo4j Cypher Manual — https://neo4j.com/docs/cypher-manual/current/
- Neo4j Python Driver Manual — https://neo4j.com/docs/python-manual/current/

## 다음 토픽

→ [Hybrid Search in Neo4j](../04-hybrid-search-neo4j/lesson.md)
