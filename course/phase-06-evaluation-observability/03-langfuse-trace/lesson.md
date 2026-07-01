# 6.3 Langfuse Trace — 검색 경로 · Tool Call · Cost · Latency 관측

> **Phase 6 · 토픽 03** · 점수가 "왜 그렇게 나왔는지"를 실행 흔적(trace)으로 들여다본다. 한 질문이 밟은 검색 경로(vector→graph)·Tool Call·스텝별 비용과 지연을 span 트리로 남기고, 02 Ragas 점수를 그 trace 에 붙여 평가와 관측을 잇는다.

## 학습 목표

이 토픽을 끝내면 다음을 할 수 있다.

- Langfuse(v3) 를 self-hosted docker-compose 로 띄우고, 계정·프로젝트·API 키를 발급받아 파이프라인을 서버에 연결한다.
- RAG/에이전트 파이프라인을 `@observe()` 데코레이터와 중첩 span 으로 계측해, 검색 경로(vector hit → graph 확장)와 각 Tool Call 을 span 트리로 남긴다.
- LLM 호출을 generation span 으로 기록해 model·usage_details(토큰)·cost_details(비용)·latency 를 한 스텝 단위로 측정한다.
- 02 Ragas 점수를 `score_current_trace` 로 trace 에 연결해, "이 실행의 faithfulness=0.92" 처럼 관측과 평가를 하나로 본다.

**완료 기준**: 한 질문의 trace 에 `retrieval → docs_search → graph_query → generate_answer` span 트리가 남고, generate_answer span 에 토큰·비용·지연이 붙고, 같은 trace 에 faithfulness 점수가 연결돼 보이면 완료.

---

## 1. 왜 필요한가 — 점수는 "얼마나 나쁜지"만 말한다

토픽 01 은 4계층 스코어카드로 무엇이 얼마나 좋은지 쟀고, 02 는 그 점수를 Ragas 로 LLM 이 채점하게 했다. 그런데 faithfulness 가 0.6 으로 낮게 나왔다고 하자. 답변이 근거를 안 지켰다는 건 알겠는데, 어디서 틀어졌을까. 검색이 엉뚱한 문서를 물어 왔나, 그래프 확장이 아예 안 됐나, 아니면 LLM 이 좋은 컨텍스트를 받고도 지어냈나. 점수 한 줄로는 못 짚는다.

느린 이유, 비싼 이유도 마찬가지다. 응답이 8초 걸렸을 때 그게 벡터 검색 탓인지, KG 질의 탓인지, LLM 생성 탓인지 숫자만 봐서는 모른다. 비용이 튀어도 어느 스텝이 토큰을 먹었는지 보이지 않는다.

이 공백을 trace 가 메운다. trace 는 한 요청이 남긴 스텝 트리다. 스텝 하나가 span 이고, span 마다 입력·출력·지연·토큰·비용이 붙는다. Langfuse 는 이 span 트리를 수집해 UI 로 보여 준다. 점수가 "결과"라면 trace 는 "과정"이다. 둘을 붙이면 낮은 점수의 원인을 스텝 단위로 되짚을 수 있다.

## 2. 핵심 개념 — trace = span 트리

trace 하나가 요청 하나다. 그 안에 span 이 트리로 쌓인다. 최상위 span 이 요청 전체(`answer_question`), 그 아래에 검색 단계(`retrieval`), 다시 그 아래에 개별 Tool Call(`docs_search`, `graph_query`)이 자식으로 들어간다. 부모-자식 관계가 곧 "무엇이 무엇 안에서 일어났는가"다.

span 은 종류가 나뉜다. 일반 스텝은 그냥 span 이고, LLM 호출은 **generation** span 으로 구분한다. generation span 에만 model·토큰·비용을 기록하는 자리가 따로 있어, UI 가 비용을 이 span 에서 집계한다. Tool Call 도 의미를 살리려고 tool 타입 span 으로 남긴다.

Langfuse v3 는 OpenTelemetry 기반이라 import 와 API 가 v2 와 다르다. 이 토픽은 v3 표기만 쓴다.

```python
from langfuse import observe, get_client   # v3: 이 두 개면 시작할 수 있다

langfuse = get_client()                     # 클라이언트는 get_client() 로 얻는다
```

> v2 방식(`Langfuse()` 직접 생성 후 `trace.span()`·`trace.generation()`)은 v3 에서 쓰지 않는다.

## 3. 실습 (1) — 함수를 span 으로: `@observe()` 와 중첩 span

가장 쉬운 계측은 함수에 데코레이터를 붙이는 것이다. `@observe()` 를 단 함수는 호출될 때마다 자동으로 span 이 되고, 안에서 부른 다른 계측 함수는 자식 span 이 된다. 최상위 진입점에 붙이면 그 함수 한 번이 trace 한 건이 된다.

```python
# practice/rag_pipeline.py 의 핵심 — 최상위 trace
@observe()
def answer_question(question: str) -> dict:
    tracer.update_current_trace(input={"question": question})
    r = retrieve(question)                          # 아래에서 중첩 span 을 만든다
    gen = call_llm(question, r["contexts"])         # generation span
    tracer.update_current_trace(output={"answer": gen["answer"]})
    return {"answer": gen["answer"], "cost": gen["cost"]}
```

검색 단계처럼 함수 하나 안에서 여러 스텝을 트리로 묶고 싶으면 수동 span 을 연다. `start_as_current_observation(...)` 를 `with` 로 쓰면 블록 하나가 span 하나이고, 중첩하면 트리가 된다. 검색 경로가 여기서 눈에 보이게 된다 — `retrieval` 부모 아래 vector 검색과 graph 확장이 순서대로 자식으로 들어간다.

```python
# practice/rag_pipeline.py 의 핵심 — 검색 경로를 중첩 span 으로
def retrieve(question: str) -> dict:
    with tracer.start_as_current_observation(
        name="retrieval", as_type="span", input={"question": question}
    ) as span:
        hits = docs_search(question, k=2)            # 자식 span: vector hit
        seeds = _entities_from_hits(hits)
        edges = graph_query(seeds)                   # 자식 span: graph 확장
        contexts = [h["text"] for h in hits] + [
            f"{e['head']} -{e['rel']}-> {e['tail']}" for e in edges
        ]
        span.update(output={"path": "vector→graph"})
        return {"contexts": contexts, "hit_ids": [h["doc_id"] for h in hits]}
```

`docs_search`·`graph_query` 도 각각 `start_as_current_observation(..., as_type="tool")` 로 감싼 Tool Call span 이다. latency 는 span 이 열리고 닫히는 시간으로 자동 계측된다.

## 4. 실습 (2) — LLM 호출은 generation span 으로: 토큰·비용 기록

LLM 호출은 generation span 으로 남기고, 응답을 받은 뒤 `update(...)` 로 model·usage_details·cost_details 를 채운다. 이 세 필드가 있어야 UI 가 비용을 집계한다.

```python
# practice/rag_pipeline.py 의 핵심 — generation span
def call_llm(prompt, contexts, real):
    model = "claude-3-5-sonnet-latest"
    with tracer.start_as_current_observation(
        name="generate_answer", as_type="generation", input={"prompt": prompt}
    ) as span:
        answer, pt, ct = _run_llm(prompt, contexts, real)   # 실제 호출 or 스텁
        span.update(
            output=answer,
            model=model,
            usage_details={"prompt_tokens": pt, "completion_tokens": ct},
            cost_details={"total_cost": _cost(model, pt, ct)},
        )
        return {"answer": answer, "cost": _cost(model, pt, ct)}
```

실제 Claude 호출이면 `usage.input_tokens`·`usage.output_tokens` 를 그대로 넣는다. 비용을 줄이려면 LLM 을 Ollama 로 바꿔도 된다 — model 이름만 로컬 모델로 두고 cost 를 `0.0` 으로 기록하면 계측 구조는 그대로다.

## 5. 실습 (3) — 점수를 trace 에 붙이기: 평가 ↔ 관측 연결

02 에서 잰 Ragas 점수를 이 trace 에 score 로 붙이면, "이 실행이 왜 이 점수인지" 를 한 화면에서 본다. 스텝별 지연·비용(관측)과 faithfulness·recall(평가)이 같은 trace 에 모인다.

```python
# 스크립트 끝 — 점수 연결 + flush
tracer.score_current_trace(name="faithfulness", value=0.92)   # 02 Ragas 결과
tracer.score_current_trace(name="context_recall", value=1.0)
tracer.flush()   # ★ 반드시 호출 — 안 하면 trace 가 서버로 안 가고 유실된다
```

여기서 실측되는 스텝 수·총 비용·총 지연이 01 피라미드의 **Agent 층 지표**다. 04 Regression Gate 는 이 비용·지연·점수를 baseline 과 비교해, 다음 변경이 더 느려지거나 비싸지거나 점수가 떨어지면 막는다.

> Langfuse 는 서버가 필요하다. **키·서버가 없어도** 파이프라인 구조를 확인할 수 있게, practice 의 `trace_util.py` 는 키가 있으면 실제 Langfuse 로, 없으면 같은 시그니처의 콘솔 트레이서로 갈아끼운다. 콘솔 트레이서는 span 트리·cost·latency 를 콘솔에 그대로 찍는다. 전체 코드와 self-host 절차는 [`practice/`](practice/) 와 [`labs/`](labs/) 참조.
> 비용을 줄이려면 LLM 을 Ollama, 임베딩을 `bge-m3` 로 바꿔도 파이프라인은 동일하게 동작한다(stack-conventions 규약).

## 6. 결과 해석 — trace 를 읽는 법

콘솔(또는 Langfuse UI)에서 이런 트리를 본다.

```
answer_question (trace)
  retrieval                 latency=2x ms   path=vector→graph
    docs_search  (tool)     latency=10 ms   hit_ids=[c2, c4]
    graph_query  (tool)     latency=10 ms   edges=[From Local to Global -USES-> Leiden]
  generate_answer (gen)     latency=… model=claude-3-5-sonnet-latest tokens=… cost=$0.00…
scores: faithfulness=0.92, context_recall=1.0
```

읽는 순서는 이렇다. 먼저 트리 모양으로 **검색 경로**를 본다 — `docs_search`(vector) 다음에 `graph_query`(graph) 가 왔으니 벡터로 후보를 잡고 그래프로 넓힌 경로다. 그다음 각 span 의 latency 를 훑어 **어디가 느린지** 짚고, generate_answer 의 tokens·cost 로 **어디가 비싼지** 본다. 마지막으로 trace 에 붙은 점수로 **이 실행이 얼마나 정확했는지** 확인한다. faithfulness 가 낮으면 generate_answer 의 입력 컨텍스트를 열어, 검색이 근거를 제대로 물어 왔는지부터 되짚는다. 점수만 봐서는 못 하던 일이다.

---

## 🚨 자주 하는 실수

1. **`flush()` 를 안 부른다** — 스크립트가 그냥 끝나면 큐에 쌓인 span 이 서버로 안 가고 사라진다. UI 에 trace 가 안 뜨는 사고의 대부분이 이것이다. 진입점 끝에 `tracer.flush()` 를 반드시 둔다.
2. **키가 없는데 왜 아무것도 안 뜨냐고 한다** — Langfuse SDK 는 키가 없으면 조용히 no-op 이 된다(전송·예외·출력 전부 없음). 서버 없이 구조를 보려면 이 저장소의 콘솔 트레이서 폴백을 써야 한다. "조용한 성공"을 성공으로 착각하지 않는다.
3. **v2 API 를 섞어 쓴다** — 검색하면 나오는 `Langfuse()` 직접 생성 후 `trace.span()`·`trace.generation()` 예제는 v2 다. v3 는 `get_client()` + `@observe()` + `start_as_current_observation` 이다. 두 방식을 섞으면 span 이 트리로 안 묶이거나 비용이 집계 안 된다.

## 출처

- Langfuse 문서 — https://langfuse.com/docs
- Langfuse self-hosting — https://langfuse.com/self-hosting
- Ragas 문서 — https://docs.ragas.io/
- GraphRAG Survey (Evaluation 파트) — arXiv 2408.08921, https://arxiv.org/abs/2408.08921

## 다음 토픽

→ [Ablation · A/B · Regression Gate](../04-ablation-ab-regression-gate/lesson.md)
