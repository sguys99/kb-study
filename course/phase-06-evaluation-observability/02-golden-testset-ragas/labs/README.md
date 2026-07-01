# Labs — Golden Testset + Ragas + Graph-specific Metrics

토픽 01 의 규칙 기반 스코어카드를, LLM 기반 Ragas 지표 + 그래프 특화 커스텀 지표로 확장한다.
아래 명령을 순서대로 실행하고 예상 출력과 대조한다.

전제:
- Python 3.11+.
- 그래프 특화 지표와 mock 경로는 **키·과금 없이** 표준 라이브러리만으로 돈다.
- 실제 Ragas(`--real`)는 `ANTHROPIC_API_KEY`, `VOYAGE_API_KEY` 가 필요하고 과금된다. 소량부터.

작업 디렉토리는 `practice/` 다.

```bash
cd course/phase-06-evaluation-observability/02-golden-testset-ragas/practice
```

---

## 0. (선택) 의존성 설치 — 실제 모드만 필요

mock/그래프 지표만 볼 거면 건너뛴다.

```bash
pip install -r requirements.txt
```

예상 출력 (요지):

```
Successfully installed ragas-0.2.x langchain-core-0.3.x langchain-anthropic-0.2.x ...
```

---

## 1. 손으로 만든 golden set 확인

자동 생성 전에, 정답을 아는 소형 golden set 을 눈으로 본다.

```bash
python -c "import json,sys; [print(json.loads(l)['question']) for l in open('golden_seed.jsonl')]"
```

예상 출력:

```
LightRAG 의 hybrid 모드는 무엇을 결합하나?
커뮤니티 요약 기법은 어느 논문에서 제안됐고, 그 논문이 쓰는 그래프 알고리즘은 무엇인가?
우리 코퍼스가 쓰는 arXiv 문서 규모는 얼마인가?
Self-RAG 와 CRAG 는 각각 무엇을 개선하려 했나?
```

single-hop(1홉)과 multi-hop(2홉) 질문이 섞여 있다. `hops` 필드로 구분된다.

---

## 2. 그래프 특화 지표 감 잡기 (키 불필요)

GraphRAG 가 엣지를 밟은 경우 vs vector-only 가 안 밟은 경우를 대비한다.

```bash
python graph_metrics.py
```

예상 출력:

```
GraphRAG 케이스 : {'multihop_path_hit': 1.0, 'graph_grounding_coverage': 1.0, 'entity_coverage': 1.0}
vector-only 케이스: {'multihop_path_hit': 0.0, 'graph_grounding_coverage': 0.0, 'entity_coverage': 0.3333333333333333}
평균           : {'multihop_path_hit': 0.5, 'graph_grounding_coverage': 0.5, 'entity_coverage': 0.6666666666666666}
```

핵심: 2홉 질문에서 vector-only 는 엣지를 안 밟아 `multihop_path_hit` 이 0.0 이다. 이게 Ragas 기본 지표로는 안 잡히는 GraphRAG 만의 차이다.

---

## 3. Golden Testset 자동 생성 — mock (키 불필요)

키 없이 흐름을 먼저 본다. mock 은 seed 를 "생성 결과인 척" 돌려준다.

```bash
python gen_testset.py
```

예상 출력:

```
[mock] 실제 생성 대신 seed 4건을 그대로 반환(과금 0). 실제 생성은 --real 로 실행하라.
저장: .../generated_testset.jsonl (4건)
⚠️ 검수 필요 4건 — 질문·정답·근거가 맞는지 사람이 확인할 것.
```

`generated_testset.jsonl` 이 생긴다. 각 줄에 `_needs_review: true` 가 붙는다 — 자동 생성물은 반드시 검수한다.

## 3-b. Golden Testset 자동 생성 — 실제 (키·과금)

코퍼스(`./corpus`, .md/.txt)를 두고 실행한다. 소량(size=5)부터.

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export VOYAGE_API_KEY=pa-...
python gen_testset.py --real --size 5 --corpus ./corpus
```

예상 출력 (요지):

```
저장: .../generated_testset.jsonl (5건)
⚠️ 검수 필요 5건 — 질문·정답·근거가 맞는지 사람이 확인할 것.
```

생성된 질문 중 절반쯤은 애매하거나 근거가 어긋난다. 검수해서 버릴 건 버린다.

---

## 4. Ragas 평가 — mock (키 불필요)

`(question, answer, contexts, reference)` 를 EvaluationDataset 으로 만들고, mock 점수로 카드를 그린다. Ragas 지표가 01 피라미드의 어느 층인지 함께 표시된다.

```bash
python eval_ragas.py
```

예상 출력:

```
[mock] EvaluationDataset 구성 생략(ModuleNotFoundError) — evaluate() 는 건너뜀(과금 0)
========================================================
  Ragas(LLM 기반) + Graph-specific — Scorecard
========================================================

[Ragas 지표  → 01 피라미드 층 매핑]
  context_recall        0.830   (Retrieval)
  context_precision     0.710   (Retrieval)
  faithfulness          0.900   (Generation)
  answer_relevancy      0.880   (Generation)

[Graph-specific 지표  → Ragas 로 안 잡히는 그래프 축]
  multihop_path_hit           1.000
  graph_grounding_coverage    1.000
  entity_coverage             1.000

========================================================
```

주의: `ragas` 가 설치돼 있으면 첫 줄이 `[mock] EvaluationDataset 구성 OK ...` 로 바뀐다. 이때는 EvaluationDataset 구성까지 진짜로 하고 `evaluate()` 만 건너뛴다. 미설치면 위처럼 구성 생략으로 뜬다. 두 경우 모두 과금은 0 이다.

## 4-b. Ragas 평가 — 실제 (키·과금)

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export VOYAGE_API_KEY=pa-...
python eval_ragas.py --real
```

예상 출력 (점수는 LLM 판단이라 실행마다 조금씩 다르다):

```
========================================================
  Ragas(LLM 기반) + Graph-specific — Scorecard
========================================================

[Ragas 지표  → 01 피라미드 층 매핑]
  context_recall        0.75x   (Retrieval)
  context_precision     0.6xx   (Retrieval)
  faithfulness          0.9xx   (Generation)
  answer_relevancy      0.8xx   (Generation)
...
```

키가 없으면 이렇게 막힌다:

```
ANTHROPIC_API_KEY 가 없다. mock 으로 돌리거나 키를 넣어라.
```

---

## 5. 헬스체크 — 무엇이 통과해야 하나

- [ ] `golden_seed.jsonl` 이 질문 4개(single-hop/multi-hop 혼합)로 읽힌다.
- [ ] `graph_metrics.py` 에서 vector-only 의 `multihop_path_hit` 이 0.0 으로 나온다.
- [ ] `gen_testset.py`(mock)가 `generated_testset.jsonl` 을 만들고 `_needs_review` 를 붙인다.
- [ ] `eval_ragas.py`(mock)가 4개 Ragas 지표에 Retrieval/Generation 층 태그를 붙여 출력한다.
- [ ] 실제 모드(`--real`)는 키가 없으면 명확한 메시지로 막힌다(과금 사고 방지).

다음: 이 점수를 화면에서 관측(trace·cost·latency)하는 건 토픽 03(Langfuse), baseline 대비 하락을 막는 회귀 게이트는 토픽 04.
