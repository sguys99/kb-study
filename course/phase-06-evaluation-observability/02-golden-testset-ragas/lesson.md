# 6.2 Golden Testset + Ragas + Graph-specific Metrics

> **Phase 6 · 토픽 02** · 손으로 만든 golden set 과 Ragas 자동 생성으로 평가셋을 만들고, 01 의 규칙 기반 recall/precision 을 LLM 기반 Ragas 지표로 대체·보강한 뒤, 그래프만의 축(멀티홉 경로·근거 연결·엔티티)을 커스텀 지표로 얹는다.

## 학습 목표

이 토픽을 끝내면 다음을 할 수 있다.

- 질문·정답·정답 근거(doc_id)를 담은 소형 golden set 을 JSONL 로 직접 만들고, Ragas `TestsetGenerator` 로 코퍼스에서 single-hop/multi-hop 질문을 자동 생성한다.
- RAG 출력 4요소(question, answer, contexts, reference)를 `EvaluationDataset` 으로 만들어 `evaluate()` 로 faithfulness·answer_relevancy·context_precision·context_recall 을 측정하고, 각 지표를 01 피라미드의 어느 층(Retrieval/Generation)인지 매핑한다.
- Ragas 로 안 잡히는 그래프 특화 지표(멀티홉 경로 적중률·그래프 근거 커버리지·엔티티 커버리지)를 커스텀으로 계산해, GraphRAG 가 vector-only 대비 무엇을 더 하는지 숫자로 보인다.

**완료 기준**: golden set 4문항(single-hop/multi-hop 혼합)에 대해 Ragas 4지표가 층 매핑과 함께 출력되고, 같은 멀티홉 질문에서 vector-only 의 `multihop_path_hit` 이 0.0, GraphRAG 가 1.0 으로 갈리면 완료.

---

## 1. 왜 필요한가 — 손으로 세던 recall 을 LLM 에게 넘긴다

토픽 01 에서 4계층 스코어카드를 순수 파이썬으로 만들었다. 거기서 `context_recall` 은 "검색된 id 집합 ∩ 정답 id 집합" 을 세는 규칙이었다. 정확하지만 한계가 뚜렷하다. 정답 근거의 id 를 사람이 미리 다 라벨링해야 하고, 답변이 근거를 실제로 얼마나 충실히 반영했는지(faithfulness)는 id 매칭으로 재지 못한다. 답변이 근거에 없는 말을 지어내도 규칙 기반 지표는 조용하다.

Ragas 는 이 판단을 LLM 에게 맡긴다. "이 답변의 각 문장이 검색된 컨텍스트로 뒷받침되는가"를 LLM 이 채점한다. 사람이 근거 id 를 일일이 붙이지 않아도, 정답 텍스트(reference)와 컨텍스트만 있으면 recall 을 추정한다. 01 의 규칙 기반 지표를 버리는 게 아니라, Retrieval·Generation 층을 LLM 기반으로 **대체·보강**하는 것이다. Construction·Agent 층은 01 의 규칙 지표를 그대로 쓴다.

그렇다고 Ragas 만으로 충분하지는 않다. Ragas 는 "텍스트 컨텍스트" 관점의 RAG 를 잰다. GraphRAG 가 진짜 그래프를 밟았는지, 2홉 질문에서 실제로 2홉을 이동했는지는 보지 못한다. 그 부분은 뒤에서 커스텀 지표로 채운다.

## 2. Golden Testset — 손으로 먼저, 그다음 자동

평가는 정답을 아는 질문셋에서 시작한다. 우선 소형 golden set 을 손으로 만든다. 정답을 우리가 알기 때문에, 지표가 이상하게 나오면 지표 쪽을 의심할 수 있다. JSONL 한 줄이 한 문항이다.

```json
{"question": "커뮤니티 요약 기법은 어느 논문에서 제안됐고, 그 논문이 쓰는 그래프 알고리즘은 무엇인가?",
 "reference": "커뮤니티 요약은 From Local to Global(arXiv 2404.16130)에서 제안됐고, Leiden 커뮤니티 탐지 알고리즘을 쓴다.",
 "reference_contexts": ["c2", "c4"], "hops": 2, "gold_entities": ["community summary", "From Local to Global", "Leiden"]}
```

`hops` 로 single-hop/multi-hop 을 구분하고, `gold_entities` 로 정답이 건드려야 할 엔티티를 라벨링한다. 이 두 필드가 뒤의 그래프 특화 지표에서 쓰인다. 전체 seed 는 [`practice/golden_seed.jsonl`](practice/golden_seed.jsonl).

코퍼스가 커지면 손으로는 못 따라간다. Ragas `TestsetGenerator` 가 문서에서 질문·정답을 뽑아 준다.

```python
# practice/gen_testset.py 의 핵심 — 실제 모드
from langchain_anthropic import ChatAnthropic
from langchain_voyageai import VoyageAIEmbeddings
from ragas.embeddings import LangchainEmbeddingsWrapper
from ragas.llms import LangchainLLMWrapper
from ragas.testset import TestsetGenerator

generator = TestsetGenerator(
    llm=LangchainLLMWrapper(ChatAnthropic(model="claude-sonnet-4-5", temperature=0)),
    embedding_model=LangchainEmbeddingsWrapper(VoyageAIEmbeddings(model="voyage-3.5")),
)
# 문서에서 바로 생성: 내부에서 KG 를 만들고 single-hop/multi-hop 질문을 뽑는다.
testset = generator.generate_with_langchain_docs(docs, testset_size=5)
```

자동 생성은 빠르지만 공짜가 아니다. 생성된 질문 중 일부는 애매하거나, 정답·근거가 어긋난다. **반드시 사람이 검수한다.** 스크립트는 자동 생성물마다 `_needs_review: true` 를 박아 검수를 강제한다. 키·과금 없이 흐름만 보려면 mock 모드가 seed 를 생성 결과처럼 돌려준다.

> 전체 코드와 실행 절차는 [`practice/`](practice/) 와 [`labs/`](labs/) 참조.
> 비용이 부담되면 LLM 을 Ollama, 임베딩을 `bge-m3` 로 바꾼다(코드 주석의 대안 분기). 파이프라인은 동일하다.

## 3. Ragas 로 평가 — 4요소를 EvaluationDataset 으로

RAG 파이프라인(우리 경우 Phase 4 의 LightRAG)을 돌려 질문마다 답과 컨텍스트를 받는다. 이걸 신형 스키마의 dict 로 모아 `EvaluationDataset` 을 만든다. 키는 `user_input` / `response` / `retrieved_contexts` / `reference` 다.

```python
# practice/eval_ragas.py 의 핵심 — 실제 모드
from ragas import EvaluationDataset, evaluate
from ragas.metrics import (
    answer_relevancy, context_precision, context_recall, faithfulness,
)

dataset = EvaluationDataset.from_list(samples)  # samples = dict 리스트
result = evaluate(
    dataset=dataset,
    metrics=[context_recall, context_precision,   # Retrieval 층
             faithfulness, answer_relevancy],     # Generation 층
    llm=evaluator_llm,           # ChatAnthropic 을 LangchainLLMWrapper 로 감싼 것
    embeddings=evaluator_embeddings,
)
```

지표는 소문자 싱글턴을 쓴다. 클래스형 대안(`Faithfulness`, `ResponseRelevancy`, `LLMContextPrecisionWithReference`, `LLMContextRecall`)도 있지만 이 강의는 싱글턴을 기본으로 한다. 옛 0.1 API(`from datasets import Dataset` + `question/answer/contexts/ground_truth` 컬럼)는 쓰지 않는다. 신형 `EvaluationDataset` 만 쓴다.

층 매핑이 핵심이다. `context_recall`·`context_precision` 은 01 피라미드의 **Retrieval** 층을 LLM 기반으로 대체하고, `faithfulness`·`answer_relevancy` 는 **Generation** 층을 채운다. 01 에서 손으로 세던 recall 이 여기서 LLM 판단으로 바뀌었을 뿐, 카드에서 차지하는 자리는 그대로다.

## 4. Graph-specific Metrics — Ragas 가 못 보는 축

Ragas 4지표를 다 재도 놓치는 게 있다. 2홉 질문에 답이 맞았다고 치자. 그 답이 그래프를 2홉 밟아서 나온 건지, vector 검색으로 우연히 두 근거가 같이 딸려와서 나온 건지 Ragas 는 구분하지 못한다. GraphRAG 를 쓰는 이유가 바로 멀티홉인데, 그걸 재지 않으면 GraphRAG 의 값어치를 증명할 길이 없다. 그래서 순수 파이썬 커스텀 지표를 얹는다(01 `metrics.py` 를 그래프 축으로 확장).

```python
# practice/graph_metrics.py 의 핵심
def multihop_path_hit(required_hops: int, traversed_edges) -> float:
    """정답이 요구하는 홉 수를 실제로 밟았는가. 2홉 필요한데 1홉만 밟으면 0.5."""
    if required_hops <= 0:
        return 1.0
    walked = len(traversed_edges)
    return min(1.0, walked / required_hops)
```

세 지표를 본다. `multihop_path_hit` 은 정답이 요구하는 홉 수를 실제 밟았는지, `graph_grounding_coverage` 는 정답 근거들이 그래프상 엣지로 이어져 하나의 서브그래프로 묶였는지, `entity_coverage` 는 정답 엔티티를 실제로 건드렸는지를 잰다. `entity_coverage` 는 표기 흔들림을 흡수하려고 소문자·strip 로 정규화해 비교한다. 엔티티 해소(Phase 2)가 잘 됐다면 이 값이 높게 나온다.

Ragas custom metric 으로 감싸고 싶다면, 위 순수 함수를 `SingleTurnMetric` 을 상속한 클래스의 `_single_turn_ascore` 안에서 호출해 `evaluate()` 의 `metrics` 리스트에 끼우면 된다. 다만 우리 그래프 지표는 검색 로그(밟은 엣지)를 입력으로 받아야 해서, Ragas 표준 샘플 스키마 밖의 데이터가 필요하다. 그래서 이 강의는 그래프 지표를 별도 파이썬으로 계산해 카드에 합치는 방식을 기본으로 삼는다.

## 5. 결과 해석

mock 카드는 이렇게 나온다.

```
[Ragas 지표  → 01 피라미드 층 매핑]
  context_recall        0.830   (Retrieval)
  context_precision     0.710   (Retrieval)
  faithfulness          0.900   (Generation)
  answer_relevancy      0.880   (Generation)

[Graph-specific 지표  → Ragas 로 안 잡히는 그래프 축]
  multihop_path_hit           1.000
  graph_grounding_coverage    1.000
  entity_coverage             1.000
```

같은 멀티홉 질문을 vector-only 로 풀면 `multihop_path_hit` 이 0.0 으로 떨어진다. 엣지를 하나도 밟지 않기 때문이다. `entity_coverage` 도 정답 엔티티 3개 중 1개만 잡아 0.333 이 된다. Ragas 의 faithfulness 는 답만 그럴듯하면 둘 다 높게 나올 수 있는데, 그래프 지표가 "GraphRAG 는 경로를 밟았고 vector-only 는 밟지 않았다"를 갈라 준다. 이 대비가 토픽 04 의 Ablation(그래프를 빼면 점수가 떨어진다)에서 그대로 쓰인다.

이 카드의 점수를 화면에서 trace·cost·latency 로 관측하는 건 토픽 03(Langfuse), baseline 대비 하락을 CI 에서 막는 회귀 게이트는 토픽 04 다. 여기서는 "숫자를 낸다"까지다.

---

## 🚨 자주 하는 실수

1. **자동 생성 testset 을 검수 없이 그대로 평가에 쓴다** — Ragas `TestsetGenerator` 는 애매하거나 정답·근거가 어긋난 질문을 섞어 낸다. 검수하지 않은 golden set 으로 잰 점수는 신뢰할 수 없다. 자동 생성물에는 `_needs_review` 를 붙여 사람이 반드시 거른다.
2. **Ragas 옛 0.1 API 로 데이터를 만든다** — `from datasets import Dataset` + `question/answer/contexts/ground_truth` 컬럼은 구식이다. 신형 `EvaluationDataset.from_list([...])` 에 `user_input/response/retrieved_contexts/reference` 키로 넣는다. 컬럼명이 틀리면 지표가 조용히 0 이 나오거나 에러가 난다.
3. **Ragas faithfulness 만 보고 GraphRAG 가 좋다고 결론 낸다** — faithfulness 는 답이 컨텍스트에 충실한지만 본다. 멀티홉을 실제로 밟았는지는 재지 못한다. 그래프 특화 지표(`multihop_path_hit` 등)를 같이 봐야 vector-only 와의 진짜 차이가 드러난다.

## 출처

- Ragas 문서 — https://docs.ragas.io/
- Ragas GitHub — https://github.com/explodinggradients/ragas
- GraphRAG Survey (Evaluation 파트) — arXiv 2408.08921, https://arxiv.org/abs/2408.08921

## 다음 토픽

→ [Langfuse Trace — 검색 경로·Tool Call·Cost·Latency 관측](../03-langfuse-trace/lesson.md)
