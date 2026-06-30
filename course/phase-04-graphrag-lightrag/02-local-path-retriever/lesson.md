# 4.2 Local · Path Retriever — Entity Linking → Neighborhood → Multi-hop Path

> **Phase 4 · 토픽 02** · 4.1 에서 본 검색 패턴 지도 중 Local·Path 를 실제 검색기로 구현한다. 자연어 질문을 그래프 노드에 꽂는 엔티티 링킹부터 이웃 서브그래프 수집(Local), 두 엔티티를 잇는 멀티홉 경로 추적(Path)까지 재사용 가능한 함수·클래스로 만든다.

## 학습 목표

이 토픽을 끝내면 다음을 할 수 있다.

- 자연어 표현을 그래프 노드로 매핑하는 엔티티 링킹(Entity Linking)을 exact·alias·full-text 후보 생성으로 **구현한다**.
- 링크된 엔티티의 1~2홉 이웃을 모아 LLM 컨텍스트 문자열로 직렬화하는 Local 검색기를 **만든다**.
- 두 엔티티를 양 끝점으로 `shortestPath` 멀티홉 경로를 추적하는 Path 검색기를 **만든다**.
- Path 검색기가 잇는 멀티홉 경로를 Baseline(Vector+BM25)이 왜 못 내는지 출력으로 **대비한다**.

**완료 기준**: 자연어 표현(예: `light rag`)이 alias/full-text 로 정확한 `:Mini` 노드에 링크되고, Path 검색기가 `Neo4j ↔ RAG` 를 3홉 경로로 이으면 완료.

---

## 1. 왜 필요한가 — 지도는 봤다, 이제 길을 낸다

4.1 에서 우리는 "어떤 질문에 어떤 검색 패턴"인지를 한 장의 지도로 봤다. Local·Path·Global·Community·Memory. 그리고 미니 그래프 위에서 각 패턴의 대표 Cypher 를 한 줄씩 돌려 봤다. 거기까지가 지도였다. 이제 그 지도 위에 실제로 길을 낸다.

그런데 검색기를 만들려고 보면 4.1 에서 슬쩍 건너뛴 관문이 하나 있다. 4.1 의 Local 데모는 `MATCH (e:Mini {name: 'LightRAG'})` 처럼 시작 노드 이름을 **이미 알고** 코드에 박아 뒀다. 실제 질문은 그렇지 않다. 사용자는 "light rag 는 뭘 쓰나" 라고 묻지, 그래프 안의 정확한 노드 키를 주지 않는다. `light rag` 가 `LightRAG` 노드라는 걸 누가 알려 주나.

이게 그래프 검색의 첫 관문, **엔티티 링킹**이다. 질문의 자연어 표현을 그래프의 어느 노드에 꽂을지 정하는 일이다. 이게 빠지거나 빗나가면 그래프 검색은 시작도 못 한다. `MATCH (e:Mini {name: 'light rag'})` 는 그냥 빈 결과를 낸다. 노드 이름이 `LightRAG` 인데 `light rag` 로 찾았으니까. 학습자가 가장 자주 빠지는 함정이 여기다. 빈 결과를 보고 "그래프가 비었나" 싶지만, 사실은 표현이 안 꽂힌 것이다.

Path 검색기는 한 발 더 나간다. Phase 0 에서 Baseline RAG 가 무너지던 네 가지 중 멀티홉, 그 자리를 정면으로 메운다. "Neo4j 와 RAG 는 어떻게 연결되나" 같은 질문에서 Vector+BM25 는 둘이 같은 청크에 없으면 관계를 못 찾는다. Path 검색기는 중간 노드를 디딤돌 삼아 길을 잇는다. 단, 그러려면 양 끝 엔티티를 먼저 링킹해야 한다. 결국 엔티티 링킹이 Local·Path 둘 다의 출발선이다.

이 토픽은 4.1 의 `:Mini` 미니 그래프를 그대로 이어받되, 엔티티마다 `aliases`(별칭)를 붙이고 노드·관계를 몇 개 더해 멀티홉이 더 또렷하게 드러나게 키운다. 그 위에 엔티티 링킹 → Local → Path 를 차례로 쌓는다.

## 2. 엔티티 링킹 — 자연어 표현을 노드에 꽂기

직관부터 보자. 링킹은 "표현 하나를 받아 가장 그럴듯한 노드 하나를 고르는" 일이다. 정확도 높은 방법부터 차례로 시도해 먼저 맞는 걸 택한다.

세 단계로 후보를 만든다. **exact** — 표현이 노드 `name` 과 정확히 같은가. **alias** — 노드의 별칭 목록 중 하나와 같은가. **full-text** — 앞의 둘이 다 빗나갔을 때, full-text 인덱스로 부분·유사 매칭을 그물처럼 던진다. 표기 흔들림(대소문자, 공백, 하이픈)은 정규화로 죽인 뒤 비교한다. `LightRAG`·`light rag`·`Light-RAG` 가 같은 키가 되도록.

먼저 후보 생성의 그물인 full-text 인덱스를 만든다. `name` 과 `aliases` 를 한 번에 검색하게 건다.

```python
# practice/graph_setup.py 의 핵심 — full-text 인덱스 생성
def create_fulltext_index(session) -> None:
    session.run(
        f"CREATE FULLTEXT INDEX {FULLTEXT_INDEX} IF NOT EXISTS "
        "FOR (n:Mini) ON EACH [n.name, n.aliases]"
    )
```

링킹 본체는 exact → alias → full-text 순으로 내려간다. 하나라도 잡히면 거기서 멈춘다.

```python
# practice/entity_linking.py 의 핵심 — 정확도 높은 순으로 후보를 시도
def link(session, mention: str, use_embedding: bool = False) -> LinkResult:
    hit = link_exact(session, mention)          # ① name 정확 일치
    if hit is not None:
        return hit
    hit = link_alias(session, mention)          # ② 별칭 정확 일치
    if hit is not None:
        return hit
    ft = link_fulltext(session, mention)        # ③ full-text 부분/유사 매칭
    if ft:
        return ft[0]
    return LinkResult(mention, None, "none", 0.0)  # ④ 실패 — 빈 결과의 원인
```

full-text 후보는 Neo4j 5.x 네이티브 프로시저로 가져온다. 별도 플러그인이 필요 없다.

```python
# practice/entity_linking.py 의 핵심 — full-text 후보 생성
rows = session.run(
    "CALL db.index.fulltext.queryNodes($index, $q) "
    "YIELD node, score "
    "WHERE node:Mini "
    "RETURN node.name AS name, score "
    "ORDER BY score DESC LIMIT $k",
    index=FULLTEXT_INDEX, q=mention, k=top_k,
)
```

더 견고하게 하려면 임베딩 링킹을 얹을 수 있다. `그 그래프 데이터베이스` 같은 의역은 full-text 그물도 놓칠 수 있는데, 질문과 노드 이름을 임베딩해 코사인 유사도로 후보를 다시 정렬하면 잡힐 확률이 올라간다. 기본 실습은 키 없이 도는 exact/alias/full-text 로 완결하고, 임베딩은 `VOYAGE_API_KEY` 가 있을 때만 켜지는 선택 분기로 둔다(없으면 자동으로 기본 경로로 떨어진다). 비용을 0 으로 가려면 임베딩 함수만 `bge-m3`(로컬, `sentence-transformers`)로 갈아끼우면 된다. 파이프라인은 그대로다.

> 전체 코드와 실행 절차는 [`practice/`](practice/) 와 [`labs/`](labs/) 참조.
> 기본 경로는 LLM·임베딩 API 를 쓰지 않는다(키 불필요·과금 0). 임베딩 링킹 분기만 `VOYAGE_API_KEY`(`voyage-3.5`)를 쓰고, 비용 0 으로는 Ollama 계열 대신 `bge-m3` 로컬 임베딩으로 바꾼다.

## 3. Local 검색기 — 이웃 서브그래프를 컨텍스트로

링킹으로 시작 노드를 정했으면, Local 은 그 노드의 **이웃을 모아 컨텍스트로 만드는** 일이다. 4.1 의 한 줄 데모를 함수로 끌어올린다. 시작 엔티티를 자연어로 받고, 홉 수(depth)를 파라미터로 받고, 결과를 LLM 이 그대로 읽을 문자열로 직렬화한다.

핵심은 두 가지 제어다. 하나, 가변 길이 패턴에는 **반드시 상한**을 둔다(`-[*1..2]-`). 둘, **무방향**으로 훑는다(`-[r]-`, 화살표 없이). 미니 그래프의 관계는 저장은 방향이 있지만 읽기는 무방향이라야 한다. `LightRAG -[USES]-> Neo4j` 에서 방향을 강제하면 `Neo4j` 쪽에서 출발하는 이웃 조회가 `LightRAG` 를 놓친다.

```python
# practice/local_retriever.py 의 핵심 — depth 홉 이웃을 무방향으로 수집
def collect_neighbors(session, name: str, depth: int = 1, limit: int = 30) -> list[dict]:
    rows = session.run(
        f"MATCH p = (e:Mini {{name: $name}})-[*1..{depth}]-(nb:Mini) "
        "WITH nb, relationships(p) AS rels, length(p) AS d "
        "WITH DISTINCT nb, d, rels[-1] AS last_rel "
        "RETURN d AS hop, "
        "       startNode(last_rel).name AS src, type(last_rel) AS rel, "
        "       endNode(last_rel).name AS dst, "
        "       nb.name AS neighbor, nb.type AS ntype "
        "ORDER BY hop, neighbor LIMIT $limit",
        name=name, limit=limit,
    )
    return [dict(r) for r in rows]
```

수집한 이웃은 한 줄당 한 사실(`src -[REL]- dst`)로 직렬화해 프롬프트 근거 블록에 그대로 끼울 수 있게 한다. 컨텍스트 패킹과 토큰 예산을 본격적으로 다루는 건 4.4(Vector+Graph Fusion)의 몫이다. 여기서는 "이웃을 모아 문자열로 만든다"까지다.

## 4. Path 검색기 — 두 엔티티를 잇는 멀티홉 경로

Path 는 양 끝 엔티티를 **각각 링킹**한 뒤, 사이를 잇는 최단 경로를 찾는다. `shortestPath` 가 두 노드 사이 최단 경로를 한 번에 찾아 준다. 여기서도 가변 길이에는 상한이 필수다.

```python
# practice/path_retriever.py 의 핵심 — 양끝 링킹 후 최단 경로
def path_retrieve(session, mention_a: str, mention_b: str) -> str:
    a = link(session, mention_a)
    b = link(session, mention_b)
    if a.name is None or b.name is None:        # 한쪽이라도 실패면 시작 못 함
        ...
    path = shortest_path(session, a.name, b.name)
    ...

def shortest_path(session, start_name: str, end_name: str) -> list[str] | None:
    rec = session.run(
        "MATCH (a:Mini {name: $start}), (b:Mini {name: $end}), "
        f"p = shortestPath((a)-[*..{MAX_HOPS}]-(b)) "   # 상한 MAX_HOPS=6 — 경로 폭발 방지
        "RETURN [n IN nodes(p) | n.name] AS hops, "
        "       [r IN relationships(p) | type(r)] AS rels",
        start=start_name, end=end_name,
    ).single()
    ...
```

`MAX_HOPS` 상한이 핵심이다. `-[*]-` 처럼 상한 없이 쓰면 큰 그래프에서 경로가 폭발해 타임아웃이 난다. 미니 그래프는 6 이면 충분하지만, 진짜 그래프(04~05 의 입력)에서는 더 낮춰 잡는다. 같은 최단 길이의 경로가 여럿일 때는 `allShortestPaths` 로 모두 가져와 근거를 보강할 수도 있다.

경로는 노드와 관계를 번갈아 끼워 `A -[REL]- B -[REL]- C` 형태의, 사람이 읽는 문장열로 바꾼다. 이게 LLM 에 줄 멀티홉 근거가 된다.

## 5. 결과 해석 — 직접 검색으로는 안 나오는 답

`python path_retriever.py` 를 돌리면 이렇게 나온다.

```
(링킹: 'Neo4j' → Neo4j [exact], 'RAG' → RAG [exact])
[Path 컨텍스트] Neo4j ↔ RAG 최단 경로 (길이 3 홉)
  Neo4j -[USES]- LightRAG -[IMPLEMENTS]- GraphRAG -[EXTENDS]- RAG
```

`Neo4j` 와 `RAG` 는 직접 연결이 없다. 그런데 `Neo4j → LightRAG → GraphRAG → RAG` 라는 3홉 경로가 나온다. 이게 Vector 검색이 못 하는 일이다. 두 엔티티가 같은 청크에 안 나오면 벡터 유사도로는 둘의 관계를 찾을 길이 없다. 그래프는 `LightRAG`·`GraphRAG` 라는 중간 노드를 거쳐 길을 잇는다. Phase 0 에서 무너졌던 멀티홉이 여기서 메워진다.

자연어로 양 끝을 줘도 똑같이 동작한다. `python path_retriever.py "light rag" "벡터 검색"` 은 `light rag`→LightRAG(alias), `벡터 검색`→vector search(alias)로 먼저 링킹한 뒤 3홉 경로를 잇는다. 링킹이 먼저, 경로가 다음. 이 순서가 Path 검색기의 골격이다.

Local·Path 를 한데 묶은 `LocalPathRetriever` 클래스(`practice/retriever.py`)는 다음 토픽이 import 할 진입점이다. 03(Global)·04(Fusion)이 "엔티티 링킹된 Local/Path 컨텍스트"를 바로 받아 쓴다.

---

## 🚨 자주 하는 실수

1. **엔티티 링킹을 건너뛰고 빈 결과를 그래프 탓으로 돌린다** — `MATCH (e:Mini {name: 'light rag'})` 는 노드 이름이 `LightRAG` 라서 빈 결과를 낸다. 이걸 "그래프가 비었다"고 오해하기 쉽다. 자연어 표현은 반드시 링킹(exact→alias→full-text)을 거쳐 정확한 노드 키로 바꾼 뒤 검색해야 한다. 빈 결과의 첫 의심처는 그래프가 아니라 링킹이다.
2. **가변 길이 경로에 상한을 안 둔다** — `shortestPath((a)-[*]-(b))` 처럼 상한 없는 `[*]` 는 미니 그래프에선 멀쩡해 보여도 진짜 그래프에선 경로가 폭발해 타임아웃 난다. `[*..6]` 처럼 상한을 반드시 둔다. 모르면 작게 잡고 늘린다.
3. **관계 방향을 강제해 무방향 연결을 놓친다** — `(a)-[r]->(nb)` 처럼 화살표를 박으면 `LightRAG -[USES]-> Neo4j` 를 `Neo4j` 쪽에서 조회할 때 이웃을 못 찾는다. 미니 그래프는 무방향처럼 읽어야 하므로 이웃·경로 모두 화살표 없는 `-[r]-` 로 훑는다. 방향이 의미를 가지는 진짜 스키마에서만 방향을 건다.

## 출처

- LightRAG — https://github.com/HKUDS/LightRAG
- Microsoft GraphRAG Docs — https://microsoft.github.io/graphrag/
- *From Local to Global: A Graph RAG Approach to Query-Focused Summarization*, arXiv 2404.16130 — https://arxiv.org/abs/2404.16130
- GraphRAG Survey, arXiv 2408.08921 — https://arxiv.org/abs/2408.08921
- Neo4j Cypher — shortestPath / 가변 길이 경로 — https://neo4j.com/docs/cypher-manual/current/patterns/variable-length-patterns/
- Neo4j — Full-text 인덱스 (`db.index.fulltext.queryNodes`) — https://neo4j.com/docs/cypher-manual/current/indexes/semantic-indexes/full-text-indexes/
- Awesome-GraphRAG (DEEP-PolyU) — https://github.com/DEEP-PolyU/Awesome-GraphRAG

## 다음 토픽

→ [03-global-retriever](../03-global-retriever/lesson.md)
