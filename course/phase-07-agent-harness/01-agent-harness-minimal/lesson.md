# 7.1 Agent Harness Minimal — Workflow vs Agent, Tool Contract + docs_search

> **Phase 7 · 토픽 01** · 검색을 "호출하는 주체"를 에이전트로 올린다. 도구 1개(`docs_search`)와 tool-use 루프만으로 최소 동작하는 Reference Harness 의 뼈대를 세운다.

## 학습 목표

이 토픽을 끝내면 다음을 할 수 있다.

- Workflow(고정 파이프라인)와 Agent(LLM 이 다음 행동을 결정하는 루프)를 코드 수준에서 구분해 설명한다.
- 도구를 Tool Contract(이름·설명·입력 스키마·출력 계약)로 정의하고, Anthropic tool-use 형식(`tools`, `tool_use`, `tool_result`)으로 등록한다.
- Phase 1 Baseline Hybrid RAG 검색기를 `docs_search` 도구로 감싸, 인용 가능한 청크(chunk_id·score·text)를 돌려주게 만든다.
- 최소 tool-use 루프를 구현해, 에이전트가 `docs_search` 를 호출하고 인용이 붙은 최종 답변을 반환하게 한다.

**완료 기준**: `python agent_loop.py "질문"` 실행 시 에이전트가 docs_search 를 최소 1회 호출하고, 인용 문서 id 가 붙은 최종 답변을 반환하면 완료.

---

## 1. 왜 필요한가 — 검색을 코드가 부르던 자리를 에이전트에게 넘긴다

Phase 1부터 Phase 4까지 우리는 검색기를 계속 좋게 만들었다. Vector+BM25 하이브리드(1/06), Neo4j 하이브리드(3/04), LightRAG 5모드(Phase 4)까지 왔다. 그런데 이 검색기들을 **부르는 쪽**은 늘 고정된 코드였다. "질문 받으면 → 검색하고 → 답한다." 순서가 박혀 있었다.

이 고정 파이프라인이 무너지는 지점이 있다. 멀티홉 질문이 그렇다. "CRAG 와 Self-RAG 는 무엇이 다른가"는 두 개념을 각각 찾아 비교해야 한다. 검색을 한 번만 도는 파이프라인은 둘 중 하나만 잡거나, 한 번의 검색으로 뭉뚱그린다. Phase 0에서 봤던 RAG 실패 4종 중 "멀티홉에서 무너짐"이 여기서 다시 나온다.

Self-RAG · CRAG · Adaptive-RAG 논문이 공통으로 말하는 해법은 하나다. **검색을 언제·몇 번·어떤 방식으로 할지를 모델이 스스로 정하게 하라.** 그러려면 검색을 "코드가 부르는 함수"가 아니라 "에이전트가 부르는 도구"로 승격한다. 그게 Agentic RAG 이고, 이 Phase의 출발점이다.

## 2. Workflow vs Agent — 누가 다음 행동을 정하는가

둘의 차이는 딱 한 가지다. **다음에 무엇을 할지를 코드가 정하느냐, LLM 이 정하느냐.**

Workflow 는 코드가 순서를 박아 둔 파이프라인이다. `검색() → 생성()` 처럼 개발자가 흐름을 고정한다. 예측 가능하고 디버깅이 쉽다. 대신 정해진 경로를 벗어나는 질문에 약하다.

Agent 는 루프 안에서 LLM 이 매 턴 다음 행동을 고른다. "지금 검색할까, 한 번 더 검색할까, 이제 답할까"를 모델이 결정한다. 유연하다. 대신 예측이 덜 되고 비용·중단 관리가 필요하다(그건 05에서 다룬다).

여기서 중요한 판단이 하나 있다. 처음부터 거창한 Agent 를 짜지 않는다. **도구 1개 + 루프**가 최소 단위다. 이 뼈대에 02가 `graph_query` 를, 03이 `ontology_check` 를, 04가 Router·Grader 를 얹어 나간다. 오늘은 뼈대만 정확히 세운다.

## 3. Tool Contract — 도구는 계약이다

에이전트가 도구를 쓰려면 도구가 무엇인지 알아야 한다. LLM 은 도구의 소스코드를 보지 않는다. **이름·설명·입력 스키마**만 본다. 이 셋이 Tool Contract 다.

- **name**: 도구를 부를 때 쓰는 식별자 (`docs_search`).
- **description**: 이 도구를 언제·어떻게 쓰는지. 모델이 읽는 사용 설명서다. 여기가 부실하면 도구를 안 부르거나 엉뚱하게 부른다.
- **input_schema**: 입력의 JSON Schema. 어떤 인자를 어떤 타입으로 넘겨야 하는지.
- **출력 계약**: 도구가 돌려주는 값의 모양. 우리는 인용 가능한 리스트(chunk_id·score·source_id·text)로 고정한다.

Anthropic tool-use 형식은 이 계약을 그대로 쓴다. 요청에 `tools=[{name, description, input_schema}]` 를 넣으면, 모델이 도구를 부를 때 응답 content 에 `type:"tool_use"` 블록(id·name·input)이 오고, `stop_reason` 이 `"tool_use"` 가 된다. 우리가 도구를 실행한 결과는 user role 의 `type:"tool_result"` 블록(tool_use_id·content)으로 되돌린다.

```python
# practice/tools.py 의 핵심 — docs_search 를 계약으로 등록
DOCS_SEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "검색할 자연어 질의."},
        "k": {"type": "integer", "description": "돌려받을 상위 청크 수. 기본 3.", "default": 3},
    },
    "required": ["query"],
}

reg.register(Tool(
    name="docs_search",
    description=(
        "문서 코퍼스에서 질의와 관련된 근거 청크를 검색한다. "
        "사실·정의·비교 질문에 답하기 전 반드시 이 도구로 근거를 찾아라. "
        "결과의 각 항목은 chunk_id·source_id·text 를 포함하므로 [chunk_id] 로 인용하라."
    ),
    input_schema=DOCS_SEARCH_SCHEMA,
    fn=_run_docs_search,
))
```

description 이 "먼저 검색하라, 그리고 chunk_id 로 인용하라"를 명시적으로 지시하는 점을 보라. 모델의 행동은 이 문장으로 좌우된다.

## 4. 실습 — docs_search 도구 + 최소 tool-use 루프

### docs_search: Phase 1 검색기를 도구로 감싼다

도구의 계약은 검색기 내부와 무관하다. `docs_search` 는 (query) → (인용 가능한 청크 리스트) 만 지킨다. 그래서 백엔드를 둘로 둔다. Phase 1/06 `HybridSearcher` 를 붙일 수 있으면 그걸 쓰고, 없으면 이 토픽 안의 작은 코퍼스 + 순수 BM25 로 돈다. 어느 쪽이든 도구가 뱉는 모양은 같다.

```python
# practice/docs_search.py 의 핵심 — 검색기가 무엇이든 출력 계약은 고정
def docs_search(query: str, k: int = 3) -> list[dict]:
    # 각 항목: {"chunk_id", "score", "source_id", "text"}  — 전부 인용 가능
    return _BACKEND.search(query=query, k=k)
```

이렇게 하면 Phase 7 을 앞 단계 없이 단독으로 돌린다. 상용 API·임베딩·외부 인덱스가 없어도 뼈대가 동작한다.

### 최소 tool-use 루프

루프의 뼈대는 네 줄로 외운다. `messages.create` 호출 → 응답을 대화에 붙임 → `stop_reason` 이 `tool_use` 가 아니면 종료(최종 답변) → 맞으면 도구 실행하고 `tool_result` 를 붙여 다시 호출.

```python
# practice/agent_loop.py 의 핵심 루프
messages = [{"role": "user", "content": question}]
for turn in range(1, MAX_TURNS + 1):
    content, stop_reason = _create(client, backend, registry, messages)
    messages.append({"role": "assistant", "content": content})

    if stop_reason != "tool_use":
        return {"answer": _extract_text(content), ...}   # 최종 답변

    tool_results = []
    for block in content:
        if block.type != "tool_use":
            continue
        result_str = registry.dispatch(block.name, block.input)   # 도구 실행
        tool_results.append(
            {"type": "tool_result", "tool_use_id": block.id, "content": result_str}
        )
    messages.append({"role": "user", "content": tool_results})     # 결과 붙여 재호출
```

순서를 코드가 정하지 않는 데 주목하라. 도구를 몇 번 부를지는 `stop_reason` 이 정한다. 멀티홉이면 여러 번, 단순 질문이면 한 번도 안 부른다. 이게 Workflow 와 갈리는 지점이다.

`MAX_TURNS` 로 상한을 둔 것도 의도적이다. 예산·중단 가드의 원형인데, 05에서 토큰·시간 예산까지 정교화한다. 지금은 무한 루프만 막는다.

> 전체 코드와 실행 절차는 [`practice/`](practice/) 와 [`labs/`](labs/) 참조.
> 비용을 줄이려면 키 없이 도는 mock 백엔드로 루프 구조를 먼저 확인하고, LLM 을 Ollama(로컬)로 바꾸려면 `_make_client` 만 교체한다(stack-conventions 규약).

## 5. 결과 해석

`python agent_loop.py "CRAG 와 Self-RAG 는 무엇이 다른가?"` 를 mock 백엔드로 돌리면 이렇게 나온다.

```
[turn 1] tool_use → docs_search({"query": "CRAG 와 Self-RAG 는 무엇이 다른가?", "k": 3})
[turn 2] 최종 답변(stop_reason=end_turn)
'...' 에 대한 답: 검색된 근거를 종합하면 아래와 같다. [doc-self-rag-01] [doc-crag-01] [doc-adaptive-rag-01]
--- 요약 ---  tool_calls : ['docs_search']   turns : 2
```

읽어야 할 신호는 두 개다. `tool_calls` 에 `docs_search` 가 들어 있으면 에이전트가 검색을 스스로 불렀다는 뜻이다. 답변 끝의 `[doc-...]` 는 그 답이 어느 청크에서 나왔는지 추적된다는 뜻이다. 인용이 붙으니 나중에 감사(Audit Trail, 06)로 이어진다.

Claude 실전 경로(키 설정)로 바꿔도 **루프 구조는 똑같다**. turn 1에서 도구를 부르고 turn 2에서 인용 답변이 온다. 바뀌는 건 답변 문장의 질뿐이다. 하니스 뼈대가 백엔드와 무관하게 동작한다는 게 이 토픽의 핵심 결과다.

---

## 🚨 자주 하는 실수

1. **`stop_reason` 을 확인하지 않고 텍스트만 뽑는다** — `stop_reason == "tool_use"` 인데 곧장 텍스트를 읽으면 도구 호출을 놓친다. 반드시 `stop_reason` 으로 분기해, tool_use 면 도구를 실행하고 결과를 붙여 **다시 호출**해야 답이 완성된다.
2. **어시스턴트의 tool_use 응답을 대화에 안 붙인다** — 도구 결과(`tool_result`)만 붙이고 직전 어시스턴트 응답(tool_use 블록 포함)을 messages 에 안 넣으면, `tool_use_id` 가 매칭되지 않아 API 가 에러를 낸다. tool_use 와 tool_result 는 짝이다. 둘 다 순서대로 붙인다.
3. **도구 description 을 사람용 문서처럼 쓴다** — description 은 모델이 읽고 "언제 부를지"를 판단하는 프롬프트다. "이 도구는 검색합니다" 정도로 두면 모델이 검색을 건너뛰고 바로 답해 버린다. "답하기 전에 반드시 검색하고 chunk_id 로 인용하라"처럼 **행동을 지시**해야 한다.

## 출처

- Anthropic Tool Use — https://docs.anthropic.com/en/docs/build-with-claude/tool-use
- LangGraph Agentic RAG 가이드 — https://docs.langchain.com/oss/python/langgraph/agentic-rag
- Self-RAG, arXiv 2310.11511 — https://arxiv.org/abs/2310.11511
- CRAG (Corrective RAG), arXiv 2401.15884 — https://arxiv.org/abs/2401.15884
- Adaptive-RAG, arXiv 2403.14403 — https://arxiv.org/abs/2403.14403

## 다음 토픽

→ [7.2 graph_query Tool — Template Cypher · Text-to-Cypher · LightRAG 도구화](../02-graph-query-tool/lesson.md)
