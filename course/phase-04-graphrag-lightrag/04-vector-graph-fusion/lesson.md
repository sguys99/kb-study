# 4.4 Vector + Graph Fusion — Rerank · Context Packing · Token Budget

> **Phase 4 · 토픽 04** · 4.2 의 Local·Path, 4.3 의 Community, 그리고 Phase 1 의 Vector 후보가 따로 놀고 있다. 셋을 하나의 후보 풀로 융합(fusion)하고, 재순위화로 정밀하게 줄 세운 뒤, 토큰 예산 안에 인용 가능한 컨텍스트로 패킹한다. 이 토픽의 산출물은 4.5(A/B)와 Phase 7 에이전트 도구의 입력이 된다.

## 학습 목표

이 토픽을 끝내면 다음을 할 수 있다.

- 출처가 다른 Vector·Graph 후보를 공통 스키마(`Candidate`)로 통일하고, 스케일이 다른 점수를 **RRF(Reciprocal Rank Fusion)로 하나의 순위로 융합한다**.
- 융합 후보를 cross-encoder reranker(VoyageAI `rerank-2.5` 또는 로컬 `bge-reranker-v2-m3`)로 질문-문서 쌍 점수로 **재순위화한다**.
- 토큰을 세어 예산을 정하고, 중복·다양성 가드를 건 그리디 패킹으로 인용 메타를 보존한 컨텍스트를 **만든다**.
- 융합 결과가 Vector-only 순위에 없던 그래프 근거(멀티홉 경로)를 상위로 끌어올림을 출력으로 **대비한다**.

**완료 기준**: Vector 후보와 Graph 후보를 RRF 로 융합·재순위해 지정 토큰 예산 안에 인용 가능한 컨텍스트로 패킹하고, 융합 결과가 Vector-only 순위에 없던 그래프 근거 후보(멀티홉 Path)를 예산 안으로 끌어올리면 완료.

---

## 1. 왜 융합인가 — 둘 다 반쪽짜리다

4.2·4.3 까지 오면 검색기가 셋이 됐다. Phase 1 의 Vector(Vector+BM25 하이브리드), 4.2 의 Local·Path, 4.3 의 Community. 각자 잘하는 게 다르다. 그리고 각자 못하는 것도 다르다.

Vector 후보는 의미적으로 가깝다. 질문과 표현이 닮은 청크를 잘 집어 온다. 약점은 구조다. "Neo4j 와 RAG 는 어떻게 연결되나" 같은 멀티홉 질문에서, 둘이 같은 청크에 없으면 관계를 못 본다. Phase 0 에서 무너지던 그 자리다.

Graph 후보는 거꾸로다. 근거가 또렷하다. `Neo4j → LightRAG → GraphRAG → RAG` 같은 3홉 경로를 들이민다. 약점은 표면이다. 그래프가 내놓는 `[Path] Neo4j -[USES]- LightRAG ...` 같은 문장은 질문의 자연어 표현과 잘 안 닮았다. 그래서 점수를 표면 유사도로만 매기면 정작 정답인 이 경로가 한참 밑으로 가라앉는다.

한쪽은 의미가 가깝지만 구조를 못 보고, 다른 쪽은 구조는 또렷하지만 표면이 어긋난다. 답은 뻔하다. 섞는다. Vector 가 놓친 구조를 Graph 가 메우고, Graph 의 표면 약점을 Vector 가 가린다. 이게 융합이다. 합쳐서 더 나은 컨텍스트를 만든 다음, LLM 에 줄 만큼만 추려 담는다.

순서는 넷이다. 후보를 한 풀로 모은다 → 점수를 섞을 수 있게 만든다(융합) → 질문 기준으로 다시 줄 세운다(재순위화) → 예산 안에 담는다(패킹). 하나씩 만든다.

## 2. 후보 융합 — 스케일이 다른 점수를 어떻게 섞나

먼저 출처가 다른 후보를 같은 모양으로 맞춘다. Vector 든 Graph 든 `Candidate(id, source, text, score, metadata)` 하나로 감싼다. 4.2/4.3 의 검색기 출력을 이 스키마로 두르기만 하면 된다.

```python
# practice/candidates.py 의 핵심 — 출처 무관 공통 후보 스키마
@dataclass
class Candidate:
    id: str
    source: str          # "vector" | "graph"
    text: str
    score: float         # 출처 안에서의 원점수(스케일이 출처마다 다르다)
    metadata: dict = field(default_factory=dict)
```

여기서 함정이 하나 있다. `score` 의 스케일이 출처마다 제멋대로다. Vector 는 코사인 유사도라 0~1 이다. Graph 는 그조차 아니다. Path 는 홉 수(3.0), Community 는 관련도(8.0), Local 은 또 다른 값이다. 이걸 그냥 한 리스트에 넣고 점수로 정렬하면? `community` 후보(8.0)가 `vector` 후보(0.83)를 항상 짓밟는다. 큰 숫자가 이기는 거지 좋은 후보가 이기는 게 아니다. 이건 융합이 아니다.

해법은 두 갈래다. 하나는 **정규화**. 출처 안에서 min-max 로 0~1 로 줄여 가중합한다. 스케일은 맞지만 가중치(alpha)를 손으로 정해야 하고 점수 분포에 휘둘린다. 다른 하나가 실무에서 더 자주 쓰이는 **RRF(Reciprocal Rank Fusion)**. 점수의 '값'을 버리고 '순위'만 본다. 1등이면 1등, 그게 0.83 이든 8.0 이든 상관없다. 스케일 문제가 통째로 사라진다.

$$\text{RRF}(d) = \sum_{\text{출처}} \frac{1}{k + \text{rank}_{\text{출처}}(d)}, \quad k \approx 60$$

각 출처 안에서 따로 순위를 매기고, 후보마다 순위의 역수를 더한다. 양쪽 출처에서 다 상위였던 후보가 가장 강해진다.

```python
# practice/fuse.py 의 핵심 — 출처별 순위만 보고 합치니 스케일이 무관하다
def fuse_rrf(pool: list[Candidate], k: int = 60) -> list[tuple[Candidate, float]]:
    ranks = {src: _rank_within_source(pool, src) for src in ("vector", "graph")}
    by_id = {c.id: c for c in pool}
    fused: dict[str, float] = {}
    for src, rank_map in ranks.items():
        for cid, r in rank_map.items():
            fused[cid] = fused.get(cid, 0.0) + 1.0 / (k + r)   # 순위 역수 합
    out = [(by_id[cid], s) for cid, s in fused.items()]
    out.sort(key=lambda t: t[1], reverse=True)
    return out
```

> 전체 코드와 실행 절차는 [`practice/`](practice/) 와 [`labs/`](labs/) 참조.
> 이 절(融合·패킹)은 표준 라이브러리만으로 키 없이 끝까지 돈다. 재순위화만 백엔드를 쓰는데, 그것도 키가 없으면 자동 폴백한다(다음 절).

## 3. 재순위화 — 질문과 후보를 같이 본다

RRF 까지 오면 한 줄로 합쳐진 순위가 나온다. 그런데 RRF 는 "각 후보가 자기 출처 안에서 몇 등이었나"만 봤다. 질문과 후보 본문을 **함께** 본 적이 없다. 재순위화(Rerank)가 그 일을 한다.

차이를 한 문장으로. **bi-encoder(임베딩)**는 질문과 문서를 따로 벡터로 만들어 코사인을 잰다. 빠르지만 둘의 상호작용을 못 본다. **cross-encoder(reranker)**는 (질문, 후보) 한 쌍을 통째로 모델에 넣어 "이 후보가 이 질문에 얼마나 답이 되나"를 직접 점수한다. 느리지만 정확하다. 그래서 1차로 넓게 뽑고(fuse) 상위 N개만 cross-encoder 로 정밀 재순위하는 2단 구조가 표준이다.

```python
# practice/rerank.py 의 핵심 — 키 없어도 끝까지 도는 3단 분기
def active_backend(explicit=None) -> str:
    if os.environ.get("VOYAGE_API_KEY"):
        try:
            import voyageai
            return "voyage"          # ① 상용: rerank-2.5
        except ImportError:
            pass
    try:
        import sentence_transformers
        return "local"               # ② 로컬 무료: bge-reranker-v2-m3
    except ImportError:
        return "identity"            # ③ 폴백: 융합 점수 그대로(데모용)
```

VoyageAI 호출부는 한 줄이다. `vo.rerank(query, documents, model="rerank-2.5", top_k=...)` 가 후보마다 관련도 점수를 매겨 돌려준다.

```python
# practice/rerank.py 의 핵심 — VoyageAI rerank-2.5 (키는 환경변수에서만 읽는다)
def _rerank_voyage(question, docs, top_k):
    vo = voyageai.Client()                      # VOYAGE_API_KEY 환경변수 사용
    res = vo.rerank(query=question, documents=docs,
                    model="rerank-2.5", top_k=top_k)
    return [(r.index, float(r.relevance_score)) for r in res.results]
```

비용이 부담되면 로컬 cross-encoder `BAAI/bge-reranker-v2-m3`(`sentence-transformers` 의 `CrossEncoder`)로 갈아끼운다. 키가 필요 없고 결과 품질만 조금 떨어질 뿐 파이프라인은 똑같다. 둘 다 없으면 `identity` 폴백이 융합 점수를 그대로 재순위 점수로 써서, 키 없이도 끝까지 돈다(품질은 RRF 수준).

## 4. Token Budget · Context Packing — 예산 안에 인용 가능하게 담기

재순위까지 끝났다고 다 끝난 게 아니다. 좋은 후보가 50개라도 LLM 컨텍스트 창에는 다 못 넣는다. 토큰을 세고, 예산을 정하고, 점수 높은 순으로 예산이 찰 때까지만 담는다.

토큰 카운트는 `tiktoken`(cl100k_base)이 있으면 정확히, 없으면 글자수/4 로 근사한다. 정확 카운트가 꼭 필요하면 Anthropic 의 `client.messages.count_tokens` 로 바꾼다. 실습은 외부 의존을 줄이려 근사를 기본으로 둔다.

패킹은 단순 그리디지만 가드 두 개가 핵심이다. **중복 제거** — 본문이 거의 같은 후보는 한 번만 담는다. **다양성** — 한 출처(vector/graph)가 자리를 다 차지하지 못하게 상한(`per_source_cap`)을 둔다. 이게 없으면 점수 높은 vector 청크가 예산을 독식해 정작 구조 근거인 graph 후보가 한 칸도 못 들어가는 사고가 난다. 융합해 놓고 패킹에서 다시 한쪽으로 쏠리면 융합한 의미가 없다.

```python
# practice/token_budget.py 의 핵심 — 그리디 패킹 + 중복/다양성 가드 + 예산 절단
def pack(reranked, budget_tokens, per_source_cap=3):
    packed, used, seen_keys, source_count = [], 0, set(), {}
    for c, score in reranked:
        key = _dedup_key(c.text)
        if key in seen_keys:                                  # 중복 가드
            continue
        if source_count.get(c.source, 0) >= per_source_cap:   # 다양성 가드
            continue
        t = count_tokens(c.text)
        if used + t > budget_tokens:                          # 예산 절단
            continue
        packed.append({"id": c.id, "source": c.source, "tokens": t,
                       "citation": f"[{c.id}·{c.source}:{c.metadata.get('span','')}]",
                       "text": c.text})
        used += t
        seen_keys.add(key)
        source_count[c.source] = source_count.get(c.source, 0) + 1
    return packed, used
```

인용 메타(`citation`)를 후보마다 끼워 둔 게 포인트다. 답변 생성 단계에서 어느 청크·어느 경로가 근거였는지 그대로 인용할 수 있다. Phase 6 의 평가·Phase 7 의 감사 추적이 이 메타를 받아 쓴다.

`fusion_pipeline.py` 가 네 단계를 묶어 `run(question, pool, budget_tokens)` 한 번으로 노출한다. 이게 이 토픽의 산출물이자 4.5·Phase 7 의 진입점이다.

## 5. 결과 해석 — Vector-only 가 못 보던 경로가 예산 안으로

`python fusion_pipeline.py --budget 512` 를 돌리면 이렇게 나온다(reranker 백엔드가 `identity` 폴백일 때 기준 — 키가 있으면 점수만 더 정밀해진다).

```
[1) RRF 융합 순위]
   1. v1 [vector]  2. g4 [ graph]  3. v2 [vector]  4. g5 [ graph]
   5. v3 [vector]  6. g1 [ graph]  ...

[3) 패킹 — 예산 512 토큰, 사용 161 토큰, 후보 6개]
    [v1·vector:L120-138]  [g4·graph:community]  [v2·vector:L40-55]
    [g5·graph:community]  [v3·vector:L88-101]   [g1·graph:path]
```

여기서 봐야 할 게 둘이다.

첫째, **융합이 두 출처를 번갈아 끼운다.** Vector-only 순위만 보면 g1(`Neo4j → LightRAG → GraphRAG → RAG` 3홉 경로)은 아예 없다. Vector 후보가 아니니까. 그 경로가 바로 "Neo4j 와 RAG 의 연결"이라는 질문의 정답인데도. RRF 가 두 출처를 한 줄로 합치면서 g1 이 6위로 올라오고, 512 토큰이라는 빠듯한 예산 안에서도 패킹에 들어간다. Vector 만 썼으면 통째로 놓쳤을 멀티홉 근거가 컨텍스트에 박힌 것이다. 완료 기준이 이 장면이다.

둘째, **다양성 가드가 작동한다.** 후보 10개 중 6개만 담겼다. `per_source_cap=3` 이라 vector 3개·graph 3개로 잘렸다. 점수만 보면 vector 가 더 담길 뻔했지만, 가드가 graph 자리를 지켰다. 예산을 1024 로 늘려도 결과가 같다 — 토큰이 남아도 가드가 출처 편식을 막기 때문이다. 예산을 더 풀고 싶으면 `per_source_cap` 을 같이 올려야 한다.

이렇게 패킹된 컨텍스트는 의미 근접 청크(Vector)와 구조 근거(Graph Path·Community)를 한 블록에 담고, 출처 인용까지 붙어 있다. 다음 토픽 4.5 는 이 융합 검색기를 Vector-only·Local·Global 과 나란히 세워, 같은 골든 질문에서 누가 더 잘 답하는지 A/B 로 잰다.

---

## 🚨 자주 하는 실수

1. **스케일이 다른 점수를 정규화 없이 그냥 더한다** — `community` 후보의 8.0 과 `vector` 후보의 0.83 을 한 리스트에서 점수로 정렬하면 큰 숫자가 무조건 이긴다. 좋은 후보가 아니라 스케일 큰 후보가 위로 간다. 출처 안에서 정규화하거나, 아예 값을 버리고 순위만 보는 RRF 를 쓴다. RRF 가 스케일 문제를 통째로 없애 줘서 실무에서 선호된다.
2. **재순위화를 임베딩 유사도로 대체한다** — bi-encoder(임베딩)는 질문과 문서를 따로 인코딩해 코사인만 잰다. 그래프가 내놓는 `[Path] Neo4j -[USES]- ...` 같은 후보는 질문과 표면이 안 닮아 코사인이 낮게 나온다. 정답인데 가라앉는다. 재순위화는 (질문, 후보)를 함께 보는 cross-encoder 여야 한다. 둘은 역할이 다르다 — 임베딩은 1차 후보 생성, cross-encoder 는 정밀 재순위.
3. **패킹에서 다양성 가드를 빼 한쪽 출처가 예산을 독식한다** — 점수 높은 vector 청크만 그리디로 담다 보면 예산이 다 차서 graph 의 멀티홉 근거가 한 칸도 못 들어간다. 융합해 놓고 패킹에서 다시 vector 쪽으로 쏠리면 융합한 의미가 사라진다. `per_source_cap` 같은 출처별 상한을 둬서 구조 근거의 자리를 지킨다.

## 출처

- LightRAG — https://github.com/HKUDS/LightRAG
- Microsoft GraphRAG Docs — https://microsoft.github.io/graphrag/
- *From Local to Global: A Graph RAG Approach to Query-Focused Summarization*, arXiv 2404.16130 — https://arxiv.org/abs/2404.16130
- GraphRAG Survey, arXiv 2408.08921 — https://arxiv.org/abs/2408.08921
- VoyageAI Reranker — https://docs.voyageai.com/docs/reranker
- VoyageAI Embeddings — https://docs.voyageai.com/docs/embeddings
- Awesome-GraphRAG (DEEP-PolyU) — https://github.com/DEEP-PolyU/Awesome-GraphRAG

## 다음 토픽

→ [05-graphrag-qa-ab](../05-graphrag-qa-ab/lesson.md)
