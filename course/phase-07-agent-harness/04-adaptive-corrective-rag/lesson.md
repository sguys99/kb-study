# 7.4 Adaptive · Corrective RAG — Router · Retrieval Grader · Query Rewrite

> **Phase 7 · 토픽 04** · 03까지 만든 3도구 harness 위에 "맞는 도구를 고르고(적응형), 검색이 부실하면 고쳐 다시 찾는(교정형)" 제어 계층을 얹는다. Self-RAG · CRAG · Adaptive-RAG 세 논문에서 실무에 필요한 세 조각만 꺼내 온다.

## 학습 목표

이 토픽을 끝내면 다음을 할 수 있다.

- Self-RAG · CRAG · Adaptive-RAG가 각각 무엇을 기여했는지 표로 정리하고, 그중 harness에 실제로 옮길 세 요소(Router · Grader · Query Rewrite)를 가려낸다.
- 질문 유형을 분류해 도구·검색 모드를 고르는 Router를 구현하고, 단순 질문은 docs_search 한 번, 관계 질문은 graph_query로 보낸다.
- 검색 결과를 relevant / ambiguous / irrelevant로 채점하는 Retrieval Grader를 만들고, 부족하면 Query Rewrite로 질의를 고쳐 재검색하는 교정 루프를 재시도 상한 안에서 돌린다.

**완료 기준**: Router가 질문 유형에 따라 도구를 고르고, Grader가 불충분한 검색을 잡아 Query Rewrite로 재검색해 답을 회복하며, 재시도 상한 안에서 인용 붙은 답변을 반환하면 완료.

---

## 1. 왜 필요한가 — 모델에게 도구만 쥐여주면 생기는 두 구멍

03까지 우리 harness는 도구 3개(docs_search · graph_query · ontology_check)를 갖췄고, 모델은 tool-use 루프 안에서 그중 하나를 골라 불렀다. 여기엔 구멍이 둘 있다.

하나, 모델이 매번 잘 고른다는 보장이 없다. "GraphRAG 진영에 뭐가 있나" 같은 광범위한 질문에 이웃 한 칸만 보는 template Cypher를 부르면 답이 얇아진다. 반대로 "Self-RAG가 뭐냐" 같은 단답형에 그래프 멀티홉을 굴리면 낭비다. 질문의 성격에 도구를 맞추는 판단이 루프 앞단에 필요하다. 이게 Router다.

둘, 검색이 부실하게 나와도 루프는 그냥 그 근거로 답해 버린다. 벡터 검색이 엉뚱한 청크를 물어 오면 그 위에 그럴듯한 오답이 쌓인다. Phase 0에서 봤던 "검색이 빗나가면 답도 빗나간다"가 여기서 재현된다. 결과가 충분한지 채점하고, 부족하면 질의를 고쳐 다시 찾는 교정 장치가 있어야 한다. 이게 Grader와 Query Rewrite다.

세 개념 모두 우리가 처음 발명하는 게 아니다. 이미 논문 세 편이 각도를 달리해 다뤘다.

## 2. 세 논문에서 무엇을 가져오나

| 논문 | 핵심 기여 | 우리가 가져오는 것 | 단순화한 것 |
|------|-----------|-------------------|-------------|
| **Adaptive-RAG** (2403.14403) | 질문 복잡도 분류기로 no-retrieval / single-step / multi-step 라우팅 | 질문 유형→도구·모드 라우팅(**Router**) | 복잡도 대신 우리 3도구에 맞춘 4분기(simple/relation/broad/schema) |
| **CRAG** (2401.15884) | 경량 retrieval evaluator로 correct/incorrect/ambiguous 판정 후 교정·웹 폴백 | 검색 결과 3등급 채점(**Grader**) | 웹 폴백 대신 재작성 재시도를 교정 행동으로 |
| **Self-RAG** (2310.11511) | reflection token으로 검색 필요성·근거성·유용성을 스스로 평가 | 부족하면 질의를 고쳐 재검색(**Query Rewrite**) | 학습된 반성 토큰 대신 프롬프트/규칙 재작성 |

세 논문을 그대로 재현하지 않는다. Self-RAG의 학습된 reflection token, CRAG의 웹 검색 폴백, Adaptive-RAG의 학습된 복잡도 분류기는 모두 코스 범위 밖이다. 실무에서 효과가 큰 세 조각만 꺼내 harness에 얹는다. 각 조각은 기본적으로 Claude가 판정하되, 키가 없으면 규칙 기반으로 폴백해 비용 0으로도 흐름을 재현한다.

## 3. Router — 질문을 보고 도구를 고른다

Router는 질문을 네 유형으로 분류하고, 각 유형을 03까지 만든 도구·모드로 매핑한다. `simple`은 docs_search 한 번, `relation`은 graph_query template(엔티티 2개면 경로, 1개면 이웃), `broad`는 LightRAG global, `schema`는 ontology_check.

```python
# router.py — 분류(LLM 또는 규칙)한 route 를 실제 도구 입력으로 변환
def route(question: str) -> RoutePlan:
    llm = _classify_llm(question)          # 키 있으면 Claude 가 route 를 JSON(enum) 판정
    if llm is not None:
        r, reason = llm; backend = "claude"
    else:
        r, reason = _classify_rule(question)   # 없으면 키워드·엔티티 개수로 규칙 분류
        backend = "rule"
    tool, tinput = _tool_input_for(r, question)  # route → 01~03 도구 스키마 그대로
    return RoutePlan(route=r, tool=tool, tool_input=tinput, reason=reason, backend=backend)
```

핵심은 `_tool_input_for`가 route를 02~03에서 고정한 도구 계약 그대로 바꿔 준다는 점이다. Router는 새 도구를 만들지 않는다. 기존 도구를 어디로 보낼지만 정한다.

```python
# router.py 발췌 — relation 은 엔티티 개수로 template 을 가른다
if route == "relation":
    if len(ents) >= 2:
        return "graph_query", {"method": "template", "template": "path_between",
                               "params": {"source": ents[0], "target": ents[1]}}
    return "graph_query", {"method": "template", "template": "neighbors",
                           "params": {"name": ents[0] if ents else "Self-RAG"}}
```

## 4. Retrieval Grader — 검색이 충분한지 채점한다

Grader는 질문과 검색 결과를 받아 세 등급을 매긴다. `relevant`(이 근거로 답할 수 있음) · `ambiguous`(일부만 관련) · `irrelevant`(무관하거나 빈 결과). `relevant`만 "충분"으로 통과시키고, 나머지는 교정을 튼다.

```python
# grader.py 발췌 — 규칙 폴백: 질문 용어와 근거의 어휘 겹침으로 3등급
def _grade_rule(question: str, rows: list[dict]) -> tuple[str, float, str]:
    if not rows:
        return "irrelevant", 0.0, "검색 결과가 비었다"
    q_terms = set(_tokenize(question))
    best = max((len(q_terms & set(_tokenize(_row_text(r)))) / len(q_terms)) for r in rows)
    if best >= RELEVANT_TH:     # 0.5
        return "relevant", best, f"질문 용어와 겹침 {best:.2f} ≥ {RELEVANT_TH}"
    if best <= IRRELEVANT_TH:   # 0.15
        return "irrelevant", best, f"질문 용어와 겹침 {best:.2f} ≤ {IRRELEVANT_TH}"
    return "ambiguous", best, f"겹침 {best:.2f} — 부분적으로만 관련"
```

도구마다 결과 모양이 다르므로(docs_search는 리스트, graph_query는 `{"rows":[...]}`) `normalize_rows`로 행 리스트로 맞춘 뒤 채점한다. 임계값 `RELEVANT_TH=0.5` · `IRRELEVANT_TH=0.15`는 규칙 폴백용 손잡이다. 실전에서는 Claude 채점기가 이 자리를 대신한다.

## 5. Query Rewrite — 부족하면 질의를 고쳐 다시 찾는다

Grader가 `relevant`를 주지 않으면 원 질문을 검색 친화적으로 다시 쓴다. 규칙 폴백은 엔티티는 살리고 조사·질문투를 걷어 핵심 검색어만 남긴다. "Self-RAG 는 도대체 언제 검색을 하는 건가요?"가 `'Self-RAG 검색'`으로 좁혀진다.

```python
# query_rewrite.py 발췌 — 엔티티는 앞세우고 군더더기 토큰은 버린다
if ents:
    new_q = (" ".join(ents) + (" " + " ".join(keywords) if keywords else "")).strip()
    strategy = "엔티티 중심 축약 + 조사·질문투 제거"
# 이미 시도한 질의와 같으면 동의 키워드를 덧붙여 한 번 더 흔든다(무의미한 재시도 방지)
if new_q in tried:
    new_q = (new_q + " 정의 개념").strip()
```

여기서 관건은 `changed` 필드다. 재작성이 원 질문과 똑같으면 재시도해 봐야 결과가 같다. 그래서 `changed=False`면 루프가 멈출 근거로 쓴다.

## 6. adaptive_loop — 다섯 단계로 묶기

세 조각을 한 제어 루프로 엮는다. Route → Retrieve → Grade → (부족하면) Rewrite & Retry → Answer. 03 harness는 다시 짜지 않는다. `build_registry_full()`(도구 3개)을 그대로 `dispatch`로 부른다.

```python
# adaptive_loop.py 발췌 — Grade 가 충분하지 않으면 교정 재시도
for attempt_i in range(1, MAX_RETRY + 2):      # 최초 1회 + MAX_RETRY(=2) 재시도
    retrieval = json.loads(registry.dispatch(tool, tool_input))
    g = grade(cur_query, retrieval)            # CRAG 채점
    if g.sufficient:                            # relevant → 교정 불필요
        break
    if attempt_i >= MAX_RETRY + 1:
        break                                   # 재시도 상한
    rw = rewrite(cur_query, grade_reason=g.reason, tried=tried_queries)  # Self-RAG/CRAG 교정
    if not rw.changed and tool == "docs_search":
        break                                   # 재작성이 그대로면 중단
    cur_query, tool = rw.query, "docs_search"   # 교정 재시도는 docs_search 로 질의를 바꿔 다시 찾는다
    tool_input = {"query": cur_query, "k": 3}
```

한 가지 설계 결정을 짚는다. `schema` 라우팅(ontology_check)은 "검색"이 아니라 "검증"이다. 어휘 겹침으로 채점하거나 질의를 고쳐 재검색할 대상이 아니다. 그래서 `_run_verification`으로 한 번 실행하고 그 verdict(ok/violations)를 그대로 답으로 삼는다. Grader·Rewrite는 검색 경로에만 건다.

`MAX_RETRY = 2`로 교정 재시도에 상한을 뒀다. 무한 교정 루프를 막는 최소 장치인데, 05에서 토큰·시간 예산 가드로 정교화한다.

## 7. 결과 해석

관계 질문을 던지면 적응형과 교정형이 한 번에 드러난다.

```
$ python adaptive_loop.py "Self-RAG 와 CRAG 는 무엇이 다른가?"
[route] relation  →  graph_query  (관계·멀티홉 신호(엔티티 2개) → graph_query(template))
[try 1] tool=graph_query ...
          grade=ambiguous score=... — 부분적으로만 관련
          → rewrite: 'Self-RAG CRAG 다른' (...) → docs_search 재검색
[try 2] tool=docs_search query='Self-RAG CRAG 다른'
          grade=relevant score=0.50 (질문 용어와 겹침 0.50 ≥ 0.5)
[answer] ... [doc-adaptive-rag-01] [doc-self-rag-01] [doc-crag-01]
--- 요약 ---  route: relation  retries: 1  grades: [ambiguous, relevant]
```

읽어야 할 신호가 셋이다. `route: relation`은 Router가 관계 질문으로 보고 graph_query로 보냈다는 뜻이다. `grades: [ambiguous, relevant]`는 첫 검색이 부족(ambiguous)해 교정이 걸렸고, 재검색이 충분(relevant)해졌다는 뜻이다. `retries: 1`은 그 교정이 한 번 돌았다는 뜻이다. 세 신호가 함께 나오면 적응형 + 교정형 루프가 제대로 작동한 것이다.

단순 질문은 교정 없이 한 번에 끝난다. `route: simple → docs_search`, `grades: [relevant]`, `retries: 0`. 반대로 스키마 질문은 ontology_check verdict가 그대로 답이 된다(`ok=false`면 "스키마 위반"). Router가 질문마다 다른 경로를 태우는 게 이 토픽의 핵심 결과다.

Claude 실전 경로(키 설정)로 바꿔도 제어 흐름은 똑같다. Router·Grader·Rewrite 판정만 규칙에서 Claude로 바뀌고, 다섯 단계 구조와 인용 형식은 그대로다.

---

## 🚨 자주 하는 실수

1. **재작성이 매번 같은 질의를 내놓아 재시도가 헛돈다** — Grader가 계속 부족을 외치는데 Query Rewrite가 원 질문과 같은 걸 돌려주면 재검색 결과도 같다. `changed` 플래그로 "안 바뀌었으면 중단", "이미 시도한 질의면 동의어 추가"를 반드시 걸어라. 상한(`MAX_RETRY`)만 믿으면 매 재시도가 낭비된다.
2. **Grader 임계값을 감으로 박아 정상 근거를 깎는다** — 어휘 겹침 채점에서 질문의 조사·의문사("어떻게·있나·차이")를 불용어로 빼지 않으면 분모가 커져 멀쩡한 근거도 ambiguous로 떨어진다. 임계값을 만지기 전에 무엇을 토큰으로 세는지부터 본다. 실전 채점은 LLM Grader로 넘기고 규칙은 폴백으로만 둔다.
3. **모든 route에 Grader·Rewrite를 똑같이 건다** — ontology_check처럼 "검증" 도구는 검색이 아니다. 어휘 겹침으로 채점하거나 질의를 재작성하면 엉뚱하게 동작한다. 검증 경로는 verdict를 그대로 답으로 삼고, 교정 루프는 검색 경로에만 걸어라.

## 출처

- Adaptive-RAG, arXiv 2403.14403 — https://arxiv.org/abs/2403.14403
- CRAG (Corrective RAG), arXiv 2401.15884 — https://arxiv.org/abs/2401.15884
- Self-RAG, arXiv 2310.11511 — https://arxiv.org/abs/2310.11511
- Anthropic Tool Use — https://docs.anthropic.com/en/docs/build-with-claude/tool-use
- LangGraph Agentic RAG 가이드 — https://docs.langchain.com/oss/python/langgraph/agentic-rag

## 다음 토픽

→ [7.5 Fallback · Budget · Checkpoint — Retry · Cache · Stop · Human Checkpoint](../05-fallback-budget-checkpoint/lesson.md)
