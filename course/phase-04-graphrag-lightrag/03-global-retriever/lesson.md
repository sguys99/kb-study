# 4.3 Global Retriever — Leiden Community · Summary · Map-Reduce

> **Phase 4 · 토픽 03** · 4.2 의 Local·Path 는 한 엔티티에서 깊게 파고든다. 시작점이 없는 질문 — "이 코퍼스 전체의 핵심 주제는?" — 은 그 방식으로 못 푼다. 코퍼스를 Leiden 커뮤니티로 쪼개 미리 요약하고, 질문이 오면 map-reduce 로 종합하는 Global 검색기를 만든다.

## 학습 목표

이 토픽을 끝내면 다음을 할 수 있다.

- GDS Leiden 으로 `:Mini` 그래프를 커뮤니티로 나누고, 4.2 의 하드코딩 `community` 값을 탐지값으로 **덮어쓴다**.
- 커뮤니티별 멤버·내부 관계를 직렬화해 LLM 요약(Community Report)을 만들고 JSON 으로 **캐시한다**.
- 질문을 커뮤니티 요약마다 던지는 MAP, 부분답변을 종합하는 REDUCE 로 전역 검색기를 **구현한다**.
- 같은 전체요약 질문에서 Global 이 Local 보다 코퍼스를 넓게 커버함을 출력으로 **대비한다**.

**완료 기준**: 전체요약 질문에 Global 이 커뮤니티 2개 이상의 부분답변을 map-reduce 로 종합해 답하고, 같은 질문에서 Local 보다 코퍼스 커버리지가 넓으면 완료.

---

## 1. 왜 필요한가 — 시작점이 없는 질문

4.2 의 Local·Path 검색기는 강력했다. 단, 전제가 하나 있었다. **어디서 출발할지가 정해져 있어야** 한다. "Neo4j 와 RAG 는 어떻게 연결되나"는 `Neo4j`·`RAG` 두 엔티티를 링킹해 출발점을 잡고, 거기서 멀티홉 경로가 뻗어 나온다.

그런데 이런 질문은 어떤가. "이 코퍼스의 핵심 주제를 큰 그림으로 요약하면?" "GraphRAG 연구 지형을 한 단락으로 정리하면?" 시작 엔티티가 없다. 어느 노드에서 출발할지 고를 수가 없으니 Local 은 손도 못 댄다.

Vector RAG 도 사정이 다르지 않다. top-k 청크만 가져오니 코퍼스의 작은 조각만 본다. 전체를 관통하는 답은 top-k 안에 안 들어온다. Phase 0 에서 RAG 가 무너지던 자리 중 하나가 바로 이 '전역 요약' 질문이었다.

Global 은 발상을 뒤집는다. 질문이 올 때 코퍼스를 뒤지는 대신, **미리 코퍼스를 주제별로 쪼개 요약해 둔다.** 질문이 오면 그 요약들을 훑어 종합한다. 코퍼스를 한 번에 LLM 에 넣을 수는 없으니, 커뮤니티 단위로 쪼개 요약하고 map-reduce 로 합치는 셈이다. Microsoft *From Local to Global*(arXiv 2404.16130)의 핵심 파이프라인이 이것이다.

순서는 셋이다. 커뮤니티로 나눈다(Leiden) → 커뮤니티마다 요약한다(Community Report) → 질문을 map-reduce 로 종합한다. 하나씩 만들어 보자.

## 2. 커뮤니티 탐지 — 4.2 의 하드코딩을 Leiden 으로 교체

4.2 의 `:Mini` 그래프에는 `community` 속성이 0/1 로 손으로 박혀 있었다. 어디까지나 임시값이었다. 진짜 커뮤니티는 그래프 구조가 정한다. 서로 촘촘히 연결된 노드끼리가 한 무리다. 그 무리를 자동으로 찾는 게 커뮤니티 탐지(Community Detection)고, GDS 의 Leiden 이 그 일을 한다. modularity(군집성)를 최대화하는 방향으로 노드를 묶어 나간다.

여기서 4.2 와 달라지는 전제가 하나 생긴다. Leiden 은 GDS 프로시저다. 4.2 는 순수 Cypher 라 GDS 가 없어도 됐지만, **4.3 은 GDS 플러그인이 필수다**. `practice/docker-compose.yml` 이 GDS 를 켠 채로 띄운다.

`:Mini` 그래프를 그대로 쓰면 거의 한 덩어리라 커뮤니티가 1개로 뭉친다. 그래서 `graph_setup.py` 가 평가·관측 주제(Ragas·Langfuse·Baseline·evaluation·QA accuracy) 한 묶음을 더한다. 군집 내부는 빽빽하게 잇고, 검색 군집과는 다리 두 개로만 성기게 잇는다. 군집 안은 촘촘하게, 군집 사이는 성기게 — 이게 Leiden 이 경계를 또렷이 긋는 조건이다.

Leiden 에서 절대 빠뜨리면 안 되는 게 **무방향 투영**이다. Leiden 은 무방향 그래프에서만 돈다. 방향을 그대로 투영하면 에러가 난다. 3.6 에서 익힌 그 규칙을 `:Mini` 라벨로 그대로 옮기면 된다.

```python
# practice/community_detect.py 의 핵심 — UNDIRECTED 투영(빼면 Leiden 이 거부)
def project_mini_graph(driver, name: str):
    cypher = """
    CALL gds.graph.project(
      $name,
      'Mini',
      { ALL_REL: { type: '*', orientation: 'UNDIRECTED' } }
    )
    YIELD nodeCount, relationshipCount
    RETURN nodeCount, relationshipCount
    """
    with driver.session() as session:
        rec = session.run(cypher, name=name).single()
    return rec["nodeCount"], rec["relationshipCount"]
```

`--write` 를 주면 탐지값을 `e.community` 로 디스크에 기록한다. 4.2 의 임시 0/1 을 Leiden 이 실제로 찾은 값으로 덮어쓰는 단계다. 이 속성을 다음 단계가 읽는다.

```python
# practice/community_detect.py 의 핵심 — 탐지값을 e.community 로 기록
def run_leiden_write(driver, name: str):
    cypher = """
    CALL gds.leiden.write($name, { writeProperty: 'community' })
    YIELD communityCount, modularity, nodePropertiesWritten
    RETURN communityCount, modularity, nodePropertiesWritten
    """
    with driver.session() as session:
        return dict(session.run(cypher, name=name).single())
```

## 3. 커뮤니티 요약 — Community Report 만들기

커뮤니티를 찾았으면, 각 커뮤니티가 '무엇에 관한 묶음인지'를 한 단락으로 압축한다. 멤버 노드와 그들 사이 내부 관계를 텍스트로 직렬화해 LLM 에 주고, 짧은 요약을 받는다. 이 요약이 다음 단계의 검색 단위가 된다. 원문 전체를 LLM 에 넣는 대신 이 짧은 요약만 쓰는 것이 *From Local to Global* 의 절약 장치다.

```python
# practice/community_summarize.py 의 핵심 — 멤버 + 내부 관계를 직렬화해 요약
def serialize_community(members, relations) -> str:
    lines = ["[엔티티]"]
    lines += [f"  - {m['name']} ({m['type']})" for m in members]
    lines.append("[관계]")
    lines += [f"  - {s} -[{rel}]- {d}" for s, rel, d in relations] or ["  - (없음)"]
    return "\n".join(lines)
```

여기에 비용 함정이 하나 도사리고 있다. 요약을 **매 질문마다 새로 뽑으면 LLM 호출이 폭증**한다. 그래프가 안 바뀌면 요약도 안 바뀐다. 그러니 한 번 만들어 `community_reports.json` 에 캐시해 두고, 그다음부터는 파일만 읽는다. 다시 만드는 건 `--refresh` 를 줄 때뿐이다.

```python
# practice/community_summarize.py 의 핵심 — 캐시 우선, 없을 때만 LLM 호출
def summarize_communities(driver, refresh: bool = False) -> dict:
    if REPORTS_PATH.exists() and not refresh:
        cached = json.loads(REPORTS_PATH.read_text(encoding="utf-8"))
        print(f"[캐시] 재사용 — LLM 호출 0, 과금 0")
        return cached
    # ... 캐시 없으면 커뮤니티별로 LLM 요약 생성 후 JSON 저장 ...
```

LLM 호출부는 `llm_backend.py` 한 곳에 모았다. `ANTHROPIC_API_KEY` 가 있으면 Claude(`claude-sonnet-4-6`)로, 없으면 Ollama 로컬 모델로 알아서 떨어진다. 키 없이 비용 0 으로 돌리고 싶다면 `ollama serve` 를 띄우고 `ollama pull qwen2.5:7b` 만 하면 된다. 코드는 손댈 필요가 없다. 결과 품질만 다를 뿐 파이프라인은 똑같다.

```python
# practice/llm_backend.py 의 핵심 — 키 있으면 Claude, 없으면 Ollama 로 자동 분기
def active_backend() -> str:
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            import anthropic  # 설치 확인
            return "anthropic"
        except ImportError:
            pass
    return "ollama"
```

> 전체 코드와 실행 절차는 [`practice/`](practice/) 와 [`labs/`](labs/) 참조.
> 키가 부담되면 LLM 을 Ollama(`qwen2.5:7b`)로 바꿔도 같은 파이프라인이 돈다. 임베딩은 이 토픽에서 쓰지 않는다.

## 4. Map-Reduce — 부분답변을 모아 전역 답변으로

이제 질문을 받는다. Global 의 검색은 두 박자로 움직인다.

**MAP.** 질문을 커뮤니티 요약마다 따로 던진다. 각 요약이 질문에 얼마나 답이 되는지를 부분답변과 관련도 점수(0~10)로 받는다. 평가 군집은 "이 코퍼스 주제는?" 질문엔 점수가 낮게, "어떻게 평가하나?" 질문엔 점수가 높게 나온다. 이 점수로 무관한 커뮤니티를 가려낸다.

```python
# practice/global_retriever.py 의 핵심 — MAP: 요약 하나에 질문을 던져 부분답변+점수
def map_one(question: str, report: dict) -> dict:
    prompt = (
        "...먼저 'SCORE: <0~10>' 한 줄로 관련도를 매기고, "
        "그다음 이 커뮤니티 정보만으로 부분답변을 적어라...\n"
        f"[질문]\n{question}\n\n[커뮤니티 {report['community']} 요약]\n{report['summary']}"
    )
    raw = complete(prompt, max_tokens=300)
    return {"community": report["community"], "members": report["members"],
            "score": _parse_score(raw), "answer": _strip_score_line(raw)}
```

**REDUCE.** 점수 0 인 커뮤니티는 버리고, 남은 부분답변을 점수순으로 모아 하나의 전역 답변으로 종합한다. map 만 하고 reduce 를 빼면 부분답변 더미만 남는다. 그건 답이 아니다. reduce 까지 가야 Global 이 완성된다.

```python
# practice/global_retriever.py 의 핵심 — REDUCE: 관련도순 부분답변을 하나로 종합
def reduce_answers(question: str, partials: list[dict], top_k: int = 5) -> str:
    useful = sorted([p for p in partials if p["score"] > 0],
                    key=lambda p: p["score"], reverse=True)[:top_k]
    if not useful:
        return "[Global] 어떤 커뮤니티도 질문과 관련이 없다."
    block = "\n\n".join(f"[커뮤니티 {p['community']} · 관련도 {p['score']:.0f}]\n{p['answer']}"
                        for p in useful)
    prompt = f"...부분답변을 하나의 전역 답변으로 종합하라...\n[질문]\n{question}\n\n{block}"
    return complete(prompt, max_tokens=600)
```

`GlobalRetriever` 클래스가 `map_all` → `reduce` 를 묶어 `search()` 한 번으로 노출한다. 4.4(Vector+Graph Fusion)·4.5(A/B)가 이 클래스를 import 해서 전역 축을 가져다 쓴다.

## 5. 결과 해석 — Local 은 못 보는 전체 그림

`python global_retriever.py "이 코퍼스의 핵심 주제를 큰 그림으로 요약하면?"` 을 돌리면 이렇게 나온다(요약 본문은 LLM·시드에 따라 달라진다).

```
[MAP] 커뮤니티별 부분답변(관련도 점수):
  c0 (score 9, GraphRAG, LightRAG, RAG...): GraphRAG·LightRAG 가 RAG 의 멀티홉 한계를 ...
  c1 (score 6, Ragas, Langfuse, Baseline...): 평가·관측 도구로 Baseline 대비 정답률을 ...

[REDUCE] 전역 답변:
이 코퍼스는 크게 두 축이다. 하나는 RAG 를 그래프로 확장한 검색 기법(GraphRAG·LightRAG)
이고(커뮤니티 0), 다른 하나는 그 검색기를 어떻게 평가·관측하느냐(Ragas·Langfuse·Baseline)
다(커뮤니티 1). ...
```

핵심은 **여러 커뮤니티가 함께 답에 들어온다**는 점이다. 같은 질문을 4.2 의 Local 로 던지면 어떻게 될까. Local 은 시작 엔티티가 필요하다. "핵심 주제"라는 말에는 엔티티가 없으니 링킹이 빗나가거나, 억지로 한 노드에 꽂혀 그 노드 이웃만 본다. 결국 코퍼스의 절반(검색 군집)만 보고 평가 군집은 통째로 놓친다. 반면 Global 은 모든 커뮤니티를 훑어 두 축을 다 잡는다. 이 차이가 곧 커버리지 차이다.

Local 이 못나서가 아니다. 질문 종류가 다를 뿐이다. 시작점이 분명한 질문엔 Local 이 깊고 빠르다. 시작점이 없는 전역 질문엔 Global 이 맞다. 두 축은 4.4 에서 섞는다. 그게 다음 단계다.

---

## 🚨 자주 하는 실수

1. **Leiden 투영에서 무방향(UNDIRECTED)을 빼먹는다** — `gds.graph.project` 에 `orientation: 'UNDIRECTED'` 를 안 넣으면 Leiden 이 "graph must be UNDIRECTED" 류 에러로 멈춘다. Leiden 은 무방향에서만 돈다. 관계가 방향을 가져도 투영은 무방향으로 한다. 3.6 에서 한 번 데인 함정이 4.3 에서 다시 나온다.
2. **요약을 캐시 안 해 질문마다 LLM 을 다시 부른다** — 그래프가 안 바뀌면 커뮤니티 요약도 안 바뀐다. 그런데 매 질문마다 요약을 새로 뽑으면 호출이 커뮤니티 수만큼 쌓여 비용이 폭증한다. 한 번 만들어 `community_reports.json` 에 캐시하고, `global_retriever` 는 그 파일만 읽어야 한다. 요약 갱신은 `--refresh` 줄 때만.
3. **MAP 만 하고 REDUCE 를 빠뜨린다** — 커뮤니티별 부분답변을 뽑는 데서 멈추면, 학습자 손엔 답변 조각 더미만 남는다. 그건 전역 답변이 아니다. 점수 0 인 커뮤니티를 거르고 관련도순으로 모아 하나로 합치는 REDUCE 까지 가야 Global 이 완성된다. map-reduce 는 두 박자가 한 쌍이다.

## 출처

- *From Local to Global: A Graph RAG Approach to Query-Focused Summarization*, arXiv 2404.16130 — https://arxiv.org/abs/2404.16130
- Microsoft GraphRAG Docs — https://microsoft.github.io/graphrag/
- Neo4j GDS — Leiden (커뮤니티 탐지) — https://neo4j.com/docs/graph-data-science/current/algorithms/leiden/
- Neo4j GDS — Graph Catalog / Projection — https://neo4j.com/docs/graph-data-science/current/
- Awesome-GraphRAG (DEEP-PolyU) — https://github.com/DEEP-PolyU/Awesome-GraphRAG

## 다음 토픽

→ [04-vector-graph-fusion](../04-vector-graph-fusion/lesson.md)
