# Lab 3.3 — Cypher Query 핸즈온

02가 적재한 그래프 위에서 패턴 매칭·멀티홉·경로·집계 Cypher 를 돌려, Vector RAG 가 틀렸던 질문에 정답이 떨어지는지 확인한다. 각 단계에 **예상 출력**을 붙였다. 실제 출력과 대조하라.

전제: Docker / Docker Compose, Python 3.11+, 그리고 **02(bulk-ingest-merge)가 적재한 그래프가 Neo4j 에 들어 있어야 한다**(nodes=14, rels=11, events=2). 이 토픽은 API 키가 필요 없다(로컬 Neo4j 만, 과금 없음).

```bash
cd ../practice    # 이 lab 기준 practice 로 이동
```

---

## 0단계 — 전제 확인: Neo4j 기동 + 02 그래프 적재 여부

02 컨테이너(`kb-neo4j`)가 떠 있는지 본다. 없으면 02 의 compose 로 띄운다(이 토픽은 데이터·compose 를 복제하지 않고 02 것을 재사용한다).

```bash
docker compose -f ../../02-bulk-ingest-merge/practice/docker-compose.yml ps
```

예상 출력(요지) — `Up (healthy)` 면 준비됨:

```
NAME        IMAGE         STATUS                   PORTS
kb-neo4j    neo4j:5.26    Up (healthy)             0.0.0.0:7474->7474/tcp, 0.0.0.0:7687->7687/tcp
```

안 떠 있으면:

```bash
docker compose -f ../../02-bulk-ingest-merge/practice/docker-compose.yml up -d
```

그래프가 비어 있다면(03 만 단독으로 돌리는 경우) 02 적재를 한 번 실행한다:

```bash
( cd ../../02-bulk-ingest-merge/practice && python ingest_bulk.py )
```

예상 출력:

```
[INFO] 미해소 endpoint -> fallback 노드 생성: ['LangChain']
[OK] 적재 완료 — nodes=14 rels=11 events=2
```

의존성 설치(02 와 같은 드라이버):

```bash
pip install -r requirements.txt
```

---

## 1단계 — 적재 상태 확인 (질의 대상 카운트 대조)

cypher-shell 로 라벨별·관계별 카운트를 본다.

```bash
docker exec -i kb-neo4j cypher-shell -u neo4j -p testpassword1 \
  "MATCH (n) RETURN labels(n) AS label, count(*) AS cnt ORDER BY cnt DESC;"
```

예상 출력(요지) — Entity 12, Event 2 = 노드 14:

```
+----------------------+
| label       | cnt    |
+----------------------+
| ["Entity"]  | 12     |
| ["Event"]   | 2      |
+----------------------+
```

```bash
docker exec -i kb-neo4j cypher-shell -u neo4j -p testpassword1 \
  "MATCH ()-[r]->() RETURN type(r) AS rel, count(*) AS cnt ORDER BY rel;"
```

예상 출력 — 합계 11(USES 2, IMPROVES 4, COMPARES_TO 1, DEVELOPED_BY 2, ABOUT 2):

```
+---------------------------+
| rel             | cnt     |
+---------------------------+
| "ABOUT"         | 2       |
| "COMPARES_TO"   | 1       |
| "DEVELOPED_BY"  | 2       |
| "IMPROVES"      | 4       |
| "USES"          | 2       |
+---------------------------+
```

카운트가 다르면 02 적재가 덜 됐거나 다른 데이터다. 0단계로 돌아가 `ingest_bulk.py` 를 다시 돌린다.

---

## 2단계 — 멀티홉 질의: "RAG 가 틀렸던 질문"에 정답

"RAG 를 개선하는 것들은 각각 무엇을 쓰는가?" — 한 청크에 답이 없어 벡터 검색이 무너지던 질문.

```bash
docker exec -i kb-neo4j cypher-shell -u neo4j -p testpassword1 \
  "MATCH (x:Entity)-[:IMPROVES]->(:Entity {name:'RAG'}) MATCH (x)-[:USES]->(t:Entity) RETURN x.name AS improver, t.name AS uses_tool;"
```

예상 출력 — RAG 개선자(Self-RAG·CRAG·GraphRAG) 중 USES 가 있는 CRAG 한 건:

```
+-----------------------------+
| improver | uses_tool        |
+-----------------------------+
| "CRAG"   | "LangChain"      |
+-----------------------------+
```

두 사실('CRAG improves RAG', 'CRAG uses LangChain')이 서로 다른 출처에서 왔어도 그래프가 이어 붙인 결과다.

---

## 3단계 — 경로 질의: 직접 관계 없는 두 엔티티 잇기

"LightRAG 와 RAG 는 어떻게 연결돼 있나?" — 직접 언급 문장이 없어 벡터가 빈손이던 질문.

```bash
docker exec -i kb-neo4j cypher-shell -u neo4j -p testpassword1 \
  "MATCH (a:Entity {name:'LightRAG'}),(b:Entity {name:'RAG'}) MATCH p=shortestPath((a)-[*1..5]-(b)) RETURN [n IN nodes(p) | n.name] AS path, length(p) AS hops;"
```

예상 출력 — 길이 2 경로(`COMPARES_TO` 그리고 `IMPROVES`):

```
+----------------------------------------------+
| path                            | hops       |
+----------------------------------------------+
| ["LightRAG", "GraphRAG", "RAG"] | 2          |
+----------------------------------------------+
```

---

## 4단계 — 집계 질의: 가장 많이 참조되는 엔티티

```bash
docker exec -i kb-neo4j cypher-shell -u neo4j -p testpassword1 \
  "MATCH (n:Entity)<-[r]-() WITH n, count(r) AS d RETURN n.name AS entity, d AS in_degree ORDER BY d DESC LIMIT 3;"
```

예상 출력 — RAG 가 in-degree 3 으로 1위(Self-RAG·CRAG·GraphRAG 가 모두 RAG 를 가리킴):

```
+-------------------------+
| entity      | in_degree |
+-------------------------+
| "RAG"       | 3         |
| ...         | ...       |
+-------------------------+
```

고립 노드(Entity-Entity 관계가 하나도 없는 엔티티)도 확인한다:

```bash
docker exec -i kb-neo4j cypher-shell -u neo4j -p testpassword1 \
  "MATCH (n:Entity) OPTIONAL MATCH (n)-[r]-(:Entity) WITH n, count(r) AS d WHERE d=0 RETURN n.name AS isolated ORDER BY isolated;"
```

예상 출력 — NeurIPS·multi-hop(어느 Entity-Entity 관계에도 안 걸림):

```
+--------------+
| isolated     |
+--------------+
| "NeurIPS"    |
| "multi-hop"  |
+--------------+
```

---

## 5단계 — Event 질의: 시점을 가진 사실

```bash
docker exec -i kb-neo4j cypher-shell -u neo4j -p testpassword1 \
  "MATCH (e:Event)-[:ABOUT]->(n:Entity) RETURN n.name AS entity, e.time AS year, e.venue AS venue ORDER BY year;"
```

예상 출력 — RAG 2020(NeurIPS), GraphRAG 2024(Microsoft):

```
+------------------------------------------+
| entity      | year   | venue             |
+------------------------------------------+
| "RAG"       | "2020" | "NeurIPS"         |
| "GraphRAG"  | "2024" | "Microsoft"       |
+------------------------------------------+
```

---

## 6단계 — Python Driver 로 한 번에 실행

위 질의들을 코드에서 돌려 결과를 정리해 보여준다(04 하이브리드 검색의 그래프 절반이 이 방식이다).

```bash
python run_queries.py
```

예상 출력(요지):

```
=== (a) 패턴 매칭 ===

[LightRAG 가 USES 하는 도구]
  {'user': 'LightRAG', 'used': 'Neo4j'}

=== (b) 멀티홉 순회 ===

[RAG 를 개선하는 것들이 쓰는 도구 (IMPROVES → USES)]
  {'improver': 'CRAG', 'uses_tool': 'LangChain'}

=== (c) 가변 길이 + 최단 경로 ===

[LightRAG ↔ RAG 1~3홉 경로 (짧은 순 5개)]
  {'hops': ['LightRAG', 'GraphRAG', 'RAG'], 'hop_count': 2}
  ...

[LightRAG ↔ RAG 최단 경로 (shortestPath)]
  {'path': ['LightRAG', 'GraphRAG', 'RAG'], 'hops': 2}

=== (d) 집계 ===

[가장 많이 참조되는 엔티티 (in-degree)]
  {'entity': 'RAG', 'in_degree': 3}
  ...

[무엇을 누가 개선하는가 (collect)]
  {'improved': 'RAG', 'improvers': ['Self-RAG', 'CRAG', 'GraphRAG'], 'cnt': 3}
  ...

[고립 노드 (Entity-Entity 관계 없음, OPTIONAL MATCH)]
  {'isolated': 'NeurIPS'}
  {'isolated': 'multi-hop'}

=== (e) Event 질의 ===

[엔티티별 발표 이벤트 (ABOUT, time)]
  {'entity': 'RAG', 'event_type': 'PUBLICATION', 'year': '2020', 'venue': 'NeurIPS'}
  {'entity': 'GraphRAG', 'event_type': 'PUBLICATION', 'year': '2024', 'venue': 'Microsoft'}

[OK] 모든 질의 실행 완료.
```

`collect` 결과의 리스트 순서는 적재·실행 순서에 따라 달라질 수 있다(이름 3개가 다 들어 있으면 정답). 경로 질의의 `LIMIT 5` 안에는 길이 2짜리 외에 더 긴 우회로도 섞여 나올 수 있다 — 맨 위 한 건이 길이 2면 통과다.

---

## 정리

완료 기준 재확인: 2단계 멀티홉이 `CRAG → LangChain`, 3단계 최단 경로가 `LightRAG → GraphRAG → RAG`(길이 2), 4단계 최다 피참조가 `RAG`(in-degree 3)로 나오고, `python run_queries.py` 가 위 예상 출력과 맞으면 이 토픽은 끝이다. 이 질의 패턴들이 다음 토픽 3/04 하이브리드 검색에서 그래프 검색 절반이 된다.

컨테이너는 02 것을 재사용하므로 여기서 따로 내리지 않는다. 다음 토픽으로 이어 쓰려면 그대로 둔다.
