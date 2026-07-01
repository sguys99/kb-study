# 6.1 GraphRAG Evaluation Pyramid (Construction · Retrieval · Generation · Agent)

> **Phase 6 · 토픽 01** · GraphRAG 시스템을 4개 계층으로 나눠 "어디를, 왜, 어떤 지표로" 재는지 지도를 그린다. 그리고 표준 라이브러리만으로 계층별 점수를 뽑는 스코어카드를 만든다.

## 학습 목표

이 토픽을 끝내면 다음을 할 수 있다.

- GraphRAG 평가를 Construction·Retrieval·Generation·Agent 4계층으로 **나눠 설명한다**.
- 각 계층이 무너지면 위층이 왜 같이 흔들리는지 **인과로 설명한다**.
- 계층별 대표 지표(스키마 준수율·context recall/precision·인용 정확도·tool-call accuracy)를 순수 파이썬으로 **직접 계산한다**.
- 계층별 점수를 한 장의 스코어카드로 출력하고, baseline 으로 저장해 다음 실행과 **비교한다**.

**완료 기준**: `python scorecard.py` 가 4계층 점수 카드를 출력하고, `--save` 로 저장한 baseline 을 `--compare` 로 다시 읽어 하락 항목에 `WARN` 을 띄우면 완료.

---

## 1. 왜 필요한가 — "좋아진 것 같다"의 함정

지금까지 코퍼스는 여러 단계를 거쳤다. Phase 1 에서 Baseline Hybrid RAG 를 세웠고, Phase 2 에서 그래프를 뽑았다. Phase 4 에서 LightRAG 5모드(`naive`/`local`/`global`/`hybrid`/`mix`)로 GraphRAG 검색을 붙였고, Phase 5 에서 Semantic Layer 로 어휘를 정리했다.

단계마다 "더 나아진 느낌"이 들었을 것이다. 문제는 느낌이 증거가 아니라는 데 있다. `mix` 모드 답변이 그럴듯해 보여도, 정말 Vector-only 보다 멀티홉 정답률이 올랐는지는 숫자로 봐야 안다. 그러지 않으면 다음 변경이 몰래 점수를 깎아도 아무도 모른다.

여기서 흔히 실수한다. 최종 답변 품질(faithfulness 하나)만 재는 것이다. 답이 틀렸을 때 원인이 어디인지 이 숫자 하나로는 못 짚는다. 그래프 추출이 엉망이라 근거 자체가 없었나? 근거는 있는데 검색이 못 찾았나? 근거를 찾았는데 LLM 이 무시했나? 에이전트가 엉뚱한 도구를 불렀나? 원인 계층이 다르면 고칠 곳도 다르다.

그래서 평가를 **계층으로 나눈다**. 이게 Evaluation Pyramid 다.

## 2. 핵심 개념 — 4계층 피라미드

아래에서 위로 쌓인다. 아래층이 무너지면 위층 점수는 믿을 수 없다.

```
        ┌─────────────────────────┐
        │  Agent (에이전트 품질)    │  ← 맨 위
        ├─────────────────────────┤
        │  Generation (생성 품질)   │
        ├─────────────────────────┤
        │  Retrieval (검색 품질)    │
        ├─────────────────────────┤
        │  Construction (구축 품질) │  ← 토대
        └─────────────────────────┘
```

핵심 직관은 하나다. **아래가 흔들리면 위가 다 흔들린다.** 그래프 구축이 부실하면(고아 노드 천지, 중복 미해소) 검색이 멀티홉 경로를 못 탄다. 검색이 근거를 못 가져오면 생성이 아무리 좋아도 답이 틀린다. 생성이 못 미더우면 에이전트가 그걸 도구로 엮어도 결과가 안 나온다. 그래서 답이 틀렸을 때는 **맨 아래층부터** 의심한다.

각 계층이 재는 것은 이렇다.

### 2.1 Construction — 그래프 구축 품질 (토대)

Phase 2 산출물, 즉 텍스트에서 뽑아 정제한 그래프 자체의 품질이다. 대표 질문은 "추출이 정확한가, 엔티티 해소가 됐는가, 스키마를 지키는가".

- **스키마 준수율(schema conformance)**: 노드·엣지가 정해진 라벨·필수 속성을 지키는 비율. Phase 5 Semantic Layer 에서 확정한 스키마 기준.
- **중복률(duplicate rate)**: 엔티티 해소가 덜 돼 같은 대상이 여러 노드로 갈라진 비율. 낮을수록 좋다.
- **고아 노드 비율(orphan rate)**: 어떤 엣지에도 안 걸린 노드 비율. 높으면 관계 추출이 빈약해 멀티홉이 막힌다. 낮을수록 좋다.
- **커버리지**: 원문의 핵심 사실이 그래프에 얼마나 담겼나.

여기가 무너지면 위층은 전부 허수다. Phase 2 의 "추출보다 정제" 원칙이 여기서 점수로 드러난다.

### 2.2 Retrieval — 검색 품질

Phase 4 GraphRAG 검색이 근거를 제대로 가져오는지 본다. Vector-only 대비 GraphRAG 의 이점이 **드러나는 층**이다.

- **context recall**: 전체 정답 근거 중 실제로 가져온 비율. 놓치면 답할 재료가 없다.
- **context precision**: 가져온 근거 중 알짜 비율. 낮으면 노이즈가 LLM 을 흔든다.
- **hit@k**: 상위 k개 안에 정답 근거가 들어왔는지.
- **멀티홉 경로 적중**: 여러 홉을 건너야 답이 나오는 질문에서 그 경로를 짚었는지. GraphRAG 가 Vector-only 를 이기는 지점.

### 2.3 Generation — 생성 품질

가져온 근거로 LLM 이 만든 답변의 품질이다.

- **faithfulness(근거 충실도)**: 답변 문장이 근거에 실제로 뒷받침되는가. 환각(hallucination)을 잡는 핵심 지표.
- **answer relevancy**: 답이 질문에 맞게 붙었는가.
- **인용 정확도(citation accuracy)**: 답변이 붙인 인용이 진짜 근거였는가(헛인용 탐지), 진짜 근거를 빠뜨리지 않았는가(누락 탐지).

faithfulness·answer relevancy 는 LLM 판단이 필요하다. 이 토픽에서는 규칙으로 셀 수 있는 **인용 정확도만** 손으로 계산하고, LLM 기반 지표는 → 상세는 토픽 02(Ragas).

### 2.4 Agent — 에이전트 품질 (맨 위)

Phase 7 에서 검색을 호출하는 주체가 에이전트로 올라간다. 그 에이전트의 행동 품질이다.

- **tool-call accuracy**: 스텝마다 올바른 도구(docs_search·graph_query·ontology_check 등)를 불렀는가.
- **라우팅 정확도**: 질문을 맞는 경로로 보냈는가.
- **스텝 수 · 비용 · 지연**: 같은 답을 더 적은 스텝·비용으로 냈는가. 이건 관측 대상 → 상세는 토픽 03(Langfuse).
- **태스크 성공률**: 결국 태스크를 해냈는가.

## 3. 실습 — 계층별 지표를 손으로 계산하는 스코어카드

Ragas·Langfuse 를 붙이기 전에, 지표가 실제로 **어떤 계산인지** 순수 파이썬으로 짚는다. LLM 판단이 필요한 지표(faithfulness 등)는 여기서 빼고, 규칙으로 셀 수 있는 지표만 구현한다. 의존성 없이 `python` 단독으로 돈다.

지표는 `practice/metrics.py` 에, 샘플 데이터는 `practice/sample_data.py` 에 있다. 아래는 계층별 대표 지표 두 개의 핵심 조각이다.

```python
# practice/metrics.py 발췌 — Construction: 스키마 준수율
def schema_conformance(nodes, allowed_labels, required_props):
    if not nodes:
        return 0.0
    ok = 0
    for n in nodes:
        label = n.get("label")
        if label not in allowed_labels:          # 허용 안 된 라벨 → 위반
            continue
        needed = required_props.get(label, set())
        props = set(n.get("props", {}).keys())
        if needed.issubset(props):               # 필수 속성 다 있어야 준수
            ok += 1
    return ok / len(nodes)
```

```python
# practice/metrics.py 발췌 — Retrieval: context recall / precision
def context_recall(retrieved, relevant):
    relevant_set = set(relevant)
    if not relevant_set:
        return 0.0
    hit = sum(1 for r in set(retrieved) if r in relevant_set)
    return hit / len(relevant_set)               # 정답을 얼마나 안 놓쳤나

def context_precision(retrieved, relevant):
    retrieved_set = set(retrieved)
    if not retrieved_set:
        return 0.0
    hit = sum(1 for r in retrieved_set if r in set(relevant))
    return hit / len(retrieved_set)              # 가져온 게 얼마나 알짜였나
```

Generation 은 인용 정확도(precision/recall/f1), Agent 는 tool-call accuracy 와 task success rate 를 같은 방식으로 계산한다. 전체는 `practice/metrics.py` 참고.

`scorecard.py` 는 이 지표들을 샘플 데이터에 물려 4계층 카드를 찍고, baseline 으로 저장·비교한다.

```bash
python scorecard.py            # 점수 카드 출력
python scorecard.py --save     # 현재 점수를 baseline.json 으로 저장
python scorecard.py --compare  # baseline 과 비교, 하락 항목에 WARN
```

> 전체 코드와 단계별 실행은 [`practice/`](practice/) 와 [`labs/`](labs/) 참조.
> 이 토픽은 LLM·임베딩 API 를 부르지 않아 API 키가 필요 없다. LLM 기반 지표를 붙이는 토픽 02 부터는 Claude/VoyageAI 를 쓰며, 비용이 부담되면 임베딩을 `bge-m3`(로컬), LLM 을 Ollama 로 바꿔도 파이프라인은 동일하게 돈다(stack-conventions 규약).

## 4. 결과 해석

`python scorecard.py` 출력을 읽어 본다.

```
[CONSTRUCTION]
  schema_conformance      0.667
  duplicate_rate          0.167 (낮을수록 좋음)
  orphan_rate             0.167 (낮을수록 좋음)

[RETRIEVAL]
  context_recall          0.833
  context_precision       0.444
  hit@3                   1.000
```

Construction 의 `0.667` 은 노드 6개 중 4개만 스키마를 지켰다는 뜻이다. `arxiv_id` 를 빠뜨린 논문 하나, 허용 안 된 라벨(`Concept`) 하나가 감점됐다. 이 토대가 흔들리면 아래에서 위로 다 흔들리므로, 답이 틀릴 때 여기부터 본다.

Retrieval 에서 눈에 띄는 건 `context_precision 0.444` 다. recall(0.833)은 높은데 precision 이 낮다. 근거를 넉넉히 긁어오지만 노이즈가 많이 섞였다는 신호다. 이런 조합이면 검색량을 줄이거나 재순위화(rerank)를 고려한다.

`--save` 로 이 점수를 baseline 에 박아 두면, 다음 실행에서 `--compare` 가 계층별로 변화를 짚는다. 검색을 건드려 recall 이 떨어지면 `[WARN] retrieval.context_recall: 0.833 -> 0.667` 처럼 하락을 잡아낸다. 이게 회귀 게이트(Regression Gate)의 씨앗이다. 임계값 설정과 CI 연동 → 상세는 토픽 04.

이 스코어카드 하나가 앞으로의 뼈대다. 토픽 02 는 여기 recall·faithfulness 를 LLM 기반 Ragas 지표로 대체하고, 토픽 03 은 Agent 층의 스텝·비용·지연을 Langfuse 로 관측하며, 토픽 04 는 이 baseline 비교를 진짜 게이트로 만든다.

---

## 🚨 자주 하는 실수

1. **최종 답변 하나(faithfulness)만 재고 끝낸다** — 답이 틀렸을 때 원인이 Construction 인지 Retrieval 인지 Generation 인지 구분 못 한다. 계층을 나눠 재야 고칠 곳을 짚는다.
2. **아래층을 안 보고 위층 점수를 믿는다** — 스키마 준수율·고아율이 엉망인데 Retrieval·Generation 점수가 높게 나오면 그 점수는 우연이거나 측정이 잘못된 것이다. 토대부터 확인한다.
3. **recall 과 precision 을 한 덩어리로 본다** — "검색 점수 0.8" 같은 단일 숫자는 위험하다. recall 이 높고 precision 이 낮은 경우와 그 반대는 처방이 정반대다. 두 축을 따로 본다.

## 출처

- Ragas 문서 — https://docs.ragas.io/
- Ragas GitHub — https://github.com/explodinggradients/ragas
- Langfuse 문서 — https://langfuse.com/docs
- GraphRAG Survey (Evaluation 파트) — arXiv 2408.08921, https://arxiv.org/abs/2408.08921

## 다음 토픽

→ [Golden Testset + Ragas + Graph-specific Metrics](../02-golden-testset-ragas/lesson.md)
