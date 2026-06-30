# 4.5 GraphRAG Q&A A/B — Vector vs Local vs Global vs Hybrid

> **Phase 4 · 토픽 05** · 같은 골든 질문 위에 네 검색 전략을 나란히 세워, 누가 어디서 이기는지 숫자로 가린다. Phase 1 Baseline 을 드디어 넘어서는 순간이다.

## 학습 목표

이 토픽을 끝내면 다음을 할 수 있다.

- 골든 질문셋을 `simple-fact / multi-hop / global-summary` 세 type 으로 분류하고, 각 질문에 정답 근거(gold) id 를 라벨링한다.
- Vector·Local·Global·Hybrid 네 전략을 공통 시그니처 `retrieve(question, pool)` 로 세우고, 4.4 융합 파이프라인을 Hybrid 전략으로 그대로 끌어 쓴다.
- `recall@k`·`mrr`·`hit_rate` 를 직접 계산해 전략 × 지표 리더보드를 내고, 질문 type 별로 분해해 우열을 가른다.
- Vector(Phase 1 기준선)가 멀티홉·전체요약에서 무너지는 지점과, Hybrid 가 그걸 회복하는 개선폭을 숫자로 읽는다.

**완료 기준**: 네 전략을 같은 골든 질문셋에 세워 type별 리더보드를 내고, Vector-only 대비 Hybrid 가 멀티홉·전체요약의 정답 근거 포함률(recall@k)에서 앞서면 완료.

---

## 1. 왜 A/B 인가

Phase 0 에서 RAG 가 무너지는 네 장면을 봤다. 멀티홉을 못 잇고, 전체를 요약하지 못하고, 근거 없이 그럴듯하게 답하고, 무엇이 더 나은지 비교할 잣대가 없었다. Phase 1 은 그중 마지막에 답했다 — Hybrid(Vector+BM25) 점수를 **기준선(Baseline)** 으로 박아 두는 것. 이후 모든 개선은 이 점수와 견줘 왔다.

Phase 4 는 그 약속을 회수하는 자리다. 4.2 에서 Local·Path 검색기를, 4.3 에서 Community 요약을, 4.4 에서 둘을 Vector 와 융합하는 파이프라인을 만들었다. 각각 따로 보면 다 그럴듯하다. 문제는 "그래서 어떤 게 낫냐"는 한마디에 숫자로 답하느냐다.

답하는 길은 하나뿐이다. 같은 질문 위에 다 세워 보는 것. 단, 질문을 한 덩어리로 뭉치면 안 된다. "VoyageAI 기본 임베딩 모델은?" 같은 단순 사실 질문과 "Neo4j 와 RAG 는 어떻게 이어지나?" 같은 멀티홉 질문은 이기는 전략이 다르다. 그래서 질문을 type 으로 나눠 따로 채점한다.

## 2. 평가 골격 — type · gold · 지표

세 가지를 먼저 정한다.

**질문 type.** 세 갈래로 나눈다. `simple-fact` 는 한 청크 안에 답이 있는 단순 사실이다. `multi-hop` 은 두세 엔티티를 거쳐야 답이 나오는 관계 질문이고, `global-summary` 는 코퍼스 전체를 조망해야 하는 요약 질문이다. type 마다 강한 전략이 갈리므로, 합산 평균만 보면 진실이 묻힌다.

**gold 라벨.** "좋아 보인다"로는 우열을 못 가린다. 질문마다 정답 근거가 되는 후보 id 를 미리 집합으로 박아 둔다. 채점은 이 gold 가 상위 k 안에 들어왔는지로만 한다.

**지표.** 핵심은 *정답 근거 포함률*이다. 세 가지로 본다.

```python
# practice/metrics.py 의 핵심 — 표준 라이브러리만 쓴다
def recall_at_k(ranked, gold, k=3):
    """상위 k 안에 잡힌 gold 비율. '정답 근거 포함률'의 핵심 지표."""
    if not gold:
        return 0.0
    topk = set(_ids(ranked)[:k])
    return len(topk & gold) / len(gold)

def mrr(ranked, gold):
    """첫 gold 의 순위 역수. 정답을 얼마나 위로 올렸나."""
    for i, cid in enumerate(_ids(ranked), 1):
        if cid in gold:
            return 1.0 / i
    return 0.0

def hit_rate(ranked, gold, k=3):
    """상위 k 안에 gold 가 하나라도 있으면 1.0."""
    topk = set(_ids(ranked)[:k])
    return 1.0 if (gold and topk & gold) else 0.0
```

골든셋은 4.4 의 `sample_candidates.json` 스타일을 그대로 확장했다. 질문 9개(type마다 3개), 각 질문에 vector/graph 후보 풀과 gold 를 동봉한다. 키 없이 결정론적으로 재현된다.

## 3. 네 전략 직접 세우기

전략을 같은 시그니처로 맞추는 게 A/B 의 전부다. `retrieve(question, pool) → ranked list[Candidate]`. 후보 스키마(`Candidate`)는 4.4 것을 그대로 import 해 쓴다. 같은 타입을 공유해야 Hybrid 가 4.4 파이프라인에 그대로 맞물린다.

```python
# practice/strategies.py 의 핵심 조각
LOCAL_KINDS = {"local", "path"}
GLOBAL_KINDS = {"community"}

def vector_only(question, pool):              # Vector = Phase 1 기준선
    cands = [c for c in pool if c.source == "vector"]
    return sorted(cands, key=lambda c: c.score, reverse=True)

def local(question, pool):                    # Local = 4.2 Local·Path 근거
    cands = [c for c in pool
             if c.source == "graph" and c.metadata.get("source_kind") in LOCAL_KINDS]
    return sorted(cands, key=lambda c: c.score, reverse=True)

def global_(question, pool):                  # Global = 4.3 Community 요약
    cands = [c for c in pool
             if c.source == "graph" and c.metadata.get("source_kind") in GLOBAL_KINDS]
    return sorted(cands, key=lambda c: c.score, reverse=True)
```

Hybrid 만 다르다. 새로 짜지 않는다. 4.4 의 `fusion_pipeline.run` 을 그대로 불러 RRF 융합 → 재순위 → 토큰 패킹을 거친 결과를 랭킹으로 쓴다. 04 의 practice 폴더를 `sys.path` 에 올려 import 한다.

```python
import fusion_pipeline   # 04-vector-graph-fusion/practice 를 sys.path 에 올려 import

def hybrid(question, pool, budget_tokens=1024, backend=None):
    result = fusion_pipeline.run(question, pool, budget_tokens=budget_tokens, backend=backend)
    by_id = {c.id: c for c in pool}
    ranked, seen = [], set()
    for p in result["packed"]:                # 토큰 예산 안에 실제로 담긴 근거 먼저
        if p["id"] not in seen:
            ranked.append(by_id[p["id"]]); seen.add(p["id"])
    for cid, _src, _s in result["reranked"]:  # 패킹에서 잘린 재순위 상위를 뒤에 잇는다(top-k 공정 비교)
        if cid not in seen:
            ranked.append(by_id[cid]); seen.add(cid)
    return ranked
```

04 가 키 없이 끝까지 도는 설계라 05 도 과금 0 경로가 기본이다. reranker 는 키·패키지가 없으면 융합 점수를 그대로 쓰는 identity 폴백으로 떨어지고, 토큰 카운트는 `tiktoken` 이 없으면 char/4 근사로 떨어진다. 비용이 부담되면 그대로 둬도 되고, 더 정확한 재순위가 필요하면 `VOYAGE_API_KEY`(상용 `rerank-2.5`)나 로컬 `bge-reranker-v2-m3`(키 0)로 백엔드만 바꾼다. 파이프라인 모양은 같고 품질만 달라진다.

> 전체 코드와 실행 절차는 [`practice/`](practice/) 와 [`labs/`](labs/) 참조.

## 4. 결과 해석 — 어느 모드가 어디서 이기나

`python3 ab_runner.py` 를 돌리면 전략 × 지표 리더보드가 먼저, 이어 type별 분해가 나온다. 전체 리더보드는 이렇다(k=3, 과금 0 폴백 기준).

```
[전체 리더보드 (전략 × 지표)]
  전략        recall@3     mrr  hit_rate
  ------------------------------------
  Vector       0.333   0.333     0.333
  Local        0.333   0.333     0.333
  Global       0.333   0.333     0.333
  Hybrid       0.722   0.611     0.778
  → recall@3 최고: Hybrid

  [Baseline(Vector) 대비 Hybrid] recall@3: 0.333 → 0.722 (+0.389)
```

합산만 보면 Hybrid 가 압도하고 나머지 셋은 똑같아 보인다. 여기서 멈추면 안 된다. 셋이 0.333 으로 같은 건 우연이고, type 으로 쪼개면 전혀 다른 그림이 나온다.

```
[simple-fact]   Vector 1.000 / Local 0.000 / Global 0.000 / Hybrid 1.000
[multi-hop]     Vector 0.000 / Local 1.000 / Global 0.000 / Hybrid 0.333
[global-summary] Vector 0.000 / Local 0.000 / Global 1.000 / Hybrid 0.833
```

읽는 법은 이렇다. **Vector 는 simple-fact 에서 만점(1.000)** 이다. 답이 한 청크에 통째로 들어 있으니 의미 근접 검색이 곧장 잡는다. 그런데 같은 Vector 가 **multi-hop·global-summary 에서 0.000** 으로 무너진다. 흩어진 청크 사이의 관계도, 코퍼스 전체의 묶음도 벡터 유사도로는 닿지 못한다. Phase 0 의 실패가 숫자로 재현된 셈이다.

**Local 은 멀티홉에서만 1.000**, **Global 은 전체요약에서만 1.000** 이다. 각자 자기 자리에서 강하고 다른 곳에선 0 이다. 한 모드만으로는 type 을 가로지르지 못한다.

**Hybrid 만 type 을 가로질러 살아남는다.** simple-fact 만점을 지키면서 multi-hop 을 0.000 → 0.333 으로, global-summary 를 0.000 → 0.833 으로 끌어올린다. Vector(Baseline) 대비 전체 recall@3 이 0.333 → 0.722, 폭으로는 +0.389 다. k 를 5 로 늘리면 Hybrid 는 0.889(+0.556)까지 간다. Phase 1 기준선을 넘어선다는 말의 실체가 이것이다.

멀티홉에서 Hybrid 가 1.000 이 아니라 0.333 인 건 과금 0 폴백(identity reranker) 탓이 크다. 융합 단계에서 graph 근거가 vector 근거에 밀려 상위 3 밖으로 처진다. 진짜 cross-encoder reranker(`rerank-2.5` 나 `bge-reranker-v2-m3`)를 붙이면 질문-문서 쌍을 직접 보고 graph 근거를 위로 올려 멀티홉 점수가 더 오른다. labs 에서 백엔드를 바꿔 직접 확인한다.

---

## 🚨 자주 하는 실수

1. **합산 평균 하나로 우열을 정한다.** 전체 리더보드만 보면 Vector·Local·Global 이 다 0.333 으로 똑같아 보인다. type 으로 쪼개야 Vector=simple-fact, Local=멀티홉, Global=요약으로 강점이 완전히 갈린다. 단일 지표·단일 질문으로 내린 결론은 거의 틀린다.
2. **gold 라벨 없이 "답이 좋아 보인다"로 채점한다.** 사람 눈으로는 어느 모드가 나은지 매번 다르게 보인다. 정답 근거 id 를 미리 박아 두고 recall@k 로 기계 채점해야 모드 간 비교가 재현되고 회귀(Phase 6)로 이어진다.
3. **Baseline 을 고정하지 않고 A/B 한다.** "Hybrid 가 0.722"는 그 자체로는 의미가 없다. Vector(Phase 1 기준선) 0.333 과 견줘 +0.389 라야 개선이다. 기준선을 먼저 박지 않으면 좋아졌는지조차 말할 수 없다.

## 출처

- LightRAG (HKUDS) — https://github.com/HKUDS/LightRAG
- Microsoft GraphRAG Docs — https://microsoft.github.io/graphrag/
- *From Local to Global: A Graph RAG Approach to Query-Focused Summarization*, arXiv 2404.16130 — https://arxiv.org/abs/2404.16130
- GraphRAG Survey, arXiv 2408.08921 — https://arxiv.org/abs/2408.08921
- Awesome-GraphRAG (DEEP-PolyU) — https://github.com/DEEP-PolyU/Awesome-GraphRAG
- VoyageAI Reranker — https://docs.voyageai.com/docs/reranker

## 다음 토픽

→ [06-why-lightrag](../06-why-lightrag/lesson.md)
