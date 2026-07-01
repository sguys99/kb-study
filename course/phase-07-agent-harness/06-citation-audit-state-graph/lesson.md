# 7.6 Structured Output · Citation · Audit Trail + 통합 State Graph — Reference Harness 완성

> **Phase 7 · 토픽 06** · 01~05 의 부품을 명시적 State Graph 로 묶고, 구조화 출력·인용 검증·감사 추적을 얹어 도메인 중립 Reference Harness 를 완성한다. FastAPI `/chat` 로 노출한다.

## 학습 목표

이 토픽을 끝내면 다음을 할 수 있다.

- 최종 답을 자유 텍스트가 아니라 Pydantic 모델(`{answer, citations[], confidence}`)로 강제하는 Structured Output 계약을 만든다.
- 답변이 단 인용이 실제 검색 결과에 존재하는지 대조해, 지어낸(환각) 인용을 자동으로 제거하는 검증기를 구현한다.
- route·retrieve·grade·correct·fallback·checkpoint·answer 를 append-only 로 기록하는 Audit Trail 을 만들어 재현·디버깅·감사를 가능하게 한다.
- 01~05 를 명시적 상태·전이로 묶는 통합 State Graph 를 짜되, 부품을 다시 짜지 않고 05 `run_guarded` 를 실행 엔진으로 재사용한다.
- 완성된 하니스를 FastAPI `/chat` 엔드포인트로 노출해 `curl` 한 방으로 답변·인용·Audit Trail 을 받는다.

**완료 기준**: `curl -X POST localhost:8000/chat -d '{"query":"멀티홉 질문","mode":"agent"}'` 가 200 OK + 구조화 답변 + 검증된 인용 + 단계별 Audit Trail 을 반환하고, 환각 인용은 자동 제거되면 완료.

---

## 1. 왜 필요한가 — 부품은 다 있는데, "합쳐진 결과물"이 없다

05 까지 우리는 부품을 만들었다. 01 도구 레지스트리, 02 graph_query, 03 안전판·ontology_check,
04 router·grader·query_rewrite, 05 예산·재시도·폴백·캐시·체크포인트. `run_guarded` 는 이 부품을
묶어 가드가 낀 루프를 돌린다. 데모로는 충분하다.

그런데 이걸 그대로 서비스에 올리면 세 구멍이 보인다.

첫째, 출력이 느슨하다. `run_guarded` 는 자유 형태 dataclass 를 돌려준다. `answer` 가 문자열이든
`None` 이든 통과하고, 인용이 빠져도 아무도 안 막는다. 캡스톤 3개(금융·의료·연구)가 이 하니스
하나를 공유하려면 응답의 모양이 스키마로 고정돼야 한다.

둘째, 인용을 검증하지 않는다. LLM 은 "이 주장은 `[doc-xyz-99]` 에 근거한다"고 써 놓고 정작
`doc-xyz-99` 는 검색된 적이 없을 수 있다. 근거가 있는 척하는 이 환각 인용이 RAG 신뢰를 가장
크게 무너뜨린다(Phase 0 의 실패 4종 중 하나).

셋째, 왜 그 답이 나왔는지 되짚을 수 없다. 05 가 `stop_reason` 하나는 남기지만, 어떤 도구를 왜
골랐고 grade 가 몇 점이었고 폴백이 왜 일어났는지는 사라진다. 재현·디버깅·감사가 안 된다.

이 토픽은 세 구멍을 메우고, 01~05 를 명시적 State Graph 로 묶어 Phase 7 의 결과물인
Reference Harness 를 완성한다. 핵심은 이거다 — 부품을 다시 짜지 않는다. `run_guarded` 를
실행 엔진으로 그대로 쓰고, 그 위에 통합 계층만 얹는다.

## 2. 통합 State Graph — 01~05 가 여기서 하나로 합쳐진다

지금까지 흐름은 코드 속에 암묵적으로 흩어져 있었다. 이제 상태를 이름 붙여 밖으로 꺼낸다.
상태를 명시하면 전이 조건이 분명해지고, 각 전이가 감사 로그 한 줄이 된다.

```
ROUTE ──▶ RETRIEVE ──▶ GRADE ──┬─(relevant)──────────────────▶ CHECKPOINT ──▶ ANSWER
  │                            │                                    │
  │                            ├─(부족·질의문제)─▶ CORRECT(rewrite)─┘(재검색 루프)
  │                            └─(도구 죽음)────▶ FALLBACK(다른 도구)┘
  │                                                                 │
  └─(예산/재시도 상한)─────────────────────────────────▶ STOP ──────┘
```

| 전이 | 조건 | 담당 부품 |
|------|------|-----------|
| ROUTE → RETRIEVE | 항상 | 04 `router.route` |
| RETRIEVE → GRADE | 검색 성공(retry·fallback 로 결과 확보) | 03 registry + 05 guards |
| RETRIEVE → FALLBACK | primary 도구가 죽거나 빈 결과 → 같은 질의, 다른 도구 | 05 `run_with_fallback` |
| GRADE → CHECKPOINT | grade=relevant(충분) | 04 `grader.grade` |
| GRADE → CORRECT | 부족·애매 → 같은 도구, 다른 질의로 재검색 | 04 `query_rewrite` |
| \* → STOP | 예산 초과·재시도 상한·no_change | 05 `Budget` |
| CHECKPOINT → ANSWER | 승인(또는 불필요) → 구조화 답 반환 | 05 `checkpoint` + 이 토픽 schema |
| CHECKPOINT → STOP | 거절 → `rejected_by_human` | 05 `checkpoint` |

기본 엔진은 Anthropic tool-use 루프(05 `run_guarded`)다. LangGraph 는 대안이다. 이 정도 분기·
루프·체크포인트는 표준 라이브러리 상태머신으로 충분하다. 그래프가 커지고 병렬 실행이나 영속
체크포인트가 필요해지면 LangGraph 로 옮기면 되지만, 지금은 굳이 프레임워크를 들이지 않는다.

통합 계층은 `run_guarded` 를 실행하고, 그 결과(GuardedResult)를 State Graph 관점으로 재구성해
감사 로그를 남긴다.

```python
# practice/state_graph.py — 05 결과를 명시적 상태 전이로 풀어 audit 에 남긴다
def _record_states(trail: AuditTrail, guarded) -> None:
    trail.add("route", route=guarded.route, backend=guarded.backend,
              tools_planned=guarded.tool_calls[:1])
    for i, tool in enumerate(guarded.tool_calls):
        fell = guarded.fell_back and i > 0 and tool == "docs_search"
        trail.add("fallback" if fell else "retrieve", tool=tool,
                  note="다른 도구로 우회(같은 질의)" if fell else "도구 실행")
        if i < len(guarded.grades):
            g = guarded.grades[i]
            trail.add("grade", ok=(g == "relevant"), grade=g, sufficient=(g == "relevant"))
            if g != "relevant" and i < guarded.retries:
                trail.add("correct", note="query_rewrite: 같은 의미·다른 질의로 재검색")
    # ... checkpoint → answer 또는 stop ...
```

## 3. Structured Output — 답을 스키마로 못박는다

자유 텍스트 답은 파싱할 수 없고 검증할 수 없다. 최종 답을 Pydantic 모델로 강제한다.

```python
# practice/schema.py — 응답 계약
class Citation(BaseModel):
    id: str                                   # chunk_id / 그래프 경로 키 / source_id
    kind: Literal["chunk", "graph", "source"] = "chunk"
    source: str | None = None
    snippet: str | None = None

class Answer(BaseModel):
    text: str
    citations: list[Citation] = Field(default_factory=list)
    confidence: float = Field(0.0, ge=0.0, le=1.0)

class ChatResponse(BaseModel):
    answer: Answer
    citations: list[Citation] = Field(default_factory=list)
    audit_trail: list[AuditEntry] = Field(default_factory=list)
    stop_reason: str = "answered"
    route: str = ""
    backend: str = "rule/mock"
```

스키마를 강제하는 방법은 둘이다. 하나는 Pydantic 검증 + 재시도 — LLM 이 뱉은 JSON 을
`model_validate` 로 검증하고, 깨지면 다시 시킨다. 다른 하나는 Anthropic tool-use — "최종 답
형식"을 tool 하나로 정의해 API 가 스키마 준수를 강제하게 한다. 어느 쪽이든 최종 산출은 위
`ChatResponse` 로 수렴한다. 이 코스는 (1)을 기본으로 쓴다. 입력에도 스키마가 걸려서, 빈 `query`
나 잘못된 `mode` 는 FastAPI 가 자동으로 422 로 막는다.

`confidence` 는 `stop_reason` 에서 유도한다. `answered` 면 높고, `budget_exceeded`·`max_retry`
면 낮춰 프런트가 "주의" 배지를 붙이게 한다.

## 4. Citation — 지어낸 인용을 걸러낸다

방어는 단순하다. 이번 질문에서 도구가 실제로 돌려준 근거의 id 집합(allowed set)을 만들고,
답이 단 인용 중 그 집합에 없는 것을 지운다.

```python
# practice/citation.py — 인용 검증
def verify_citations(answer_citations, index):
    allowed = set(index.keys())          # 실제 검색으로 나온 id 집합
    check = CitationCheck(allowed_ids=sorted(allowed))
    for c in answer_citations:
        if c.id in allowed:
            check.valid.append(index[c.id])   # 실존 — 정본으로 교체
        else:
            check.dropped.append(c.id)        # 환각 — 제거
    return check
```

한 가지 함정이 있다. 같은 근거를 부품마다 다른 이름으로 부른다. 05 `run_guarded` 는 그래프
행의 인용을 `source`(예: `e-agentic-rag`)로 뽑는데, 표시용 인용은 경로 키(`CRAG -[IS_A]->
Agentic RAG`)로 만든다. 둘 다 같은 행을 가리킨다. 그래서 `build_evidence_index` 는 그래프 행을
두 키 모두 allowed 로 등록한다 — 그러지 않으면 진짜 인용이 환각으로 오인돼 지워진다.

```python
# practice/citation.py — 한 행을 여러 키로 색인(경로 키 + source 별칭)
def _citations_from_row(row):
    if row.get("chunk_id"):
        return [Citation(id=row["chunk_id"], kind="chunk", ...)]   # 청크는 chunk_id 하나
    out = []
    gk = _graph_key(row)                       # 'CRAG -[IS_A]-> Agentic RAG'
    if gk: out.append(Citation(id=gk, kind="graph", source=row.get("source")))
    if row.get("source"):                       # 같은 근거를 source 이름으로도 등록
        out.append(Citation(id=row["source"], kind="graph" if gk else "source", ...))
    return out
```

## 5. Audit Trail — 전 과정을 되짚을 수 있게 남긴다

`AuditTrail` 은 append-only 로그다. State Graph 의 각 전이가 한 줄씩 남긴다. 값은 요약해 담는다
— 도구가 뱉은 5000자 raw 를 통째로 넣지 않고 개수·상위 id 만 남긴다.

```python
# practice/audit.py — 감사 로그 수집기
@dataclass
class AuditTrail:
    def add(self, step, ok=True, **detail):
        detail = {k: _summarize(v) for k, v in detail.items()}   # 긴 값은 잘라 담는다
        detail["elapsed_ms"] = round((time.monotonic() - self._t0) * 1000, 1)
        entry = AuditEntry(seq=len(self._entries), step=step, ok=ok, detail=detail)
        self._entries.append(entry)
        return entry
```

각 줄은 `AuditEntry(seq, step, ok, detail)` 로 직렬화돼 `ChatResponse.audit_trail` 로 나간다.
관측성을 켜고 싶으면 `to_langfuse(trace)` 훅으로 각 단계를 Langfuse(Phase 6/03) span 으로
흘려보낼 수 있다. 기본은 아무것도 안 한다 — 관측성은 옵트인이고, 키·SDK 없이도 하니스는 돈다.

## 6. FastAPI `/chat` — 캡스톤의 공통 진입점

이제 하니스를 HTTP 로 노출한다. `app.py` 는 얇은 어댑터다. 실제 일은 `run_harness` 가 다 한다.

```python
# practice/app.py
@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    return run_harness(request)   # route→…→citation_check 전부 여기서
```

`run_harness` 는 `run_guarded` 를 캐시 공유로 실행하고, 캐시에 쌓인 도구 결과를 인용 근거의
수집처로 재사용한다(별도 훅 없이). 그 결과로 인용 인덱스를 만들고, 답의 인용을 검증한 뒤
`ChatResponse` 로 구조화해 돌려준다.

```python
# practice/state_graph.py — run_harness 의 통합 골자
guarded = run_guarded(request.query, budget=budget, cache=cache, verbose=False)
_record_states(trail, guarded)                       # audit_trail 채우기
retrievals = _cached_retrievals(cache)               # 캐시 = 인용 근거 수집처
index = build_evidence_index(retrievals)
check = verify_citations([Citation(id=c) for c in guarded.citations], index)
valid = check.valid or enrich_citations(index)       # 인용 없으면 실존 근거로 보강
return ChatResponse(answer=Answer(text=guarded.answer, citations=valid,
                                  confidence=_CONFIDENCE.get(guarded.stop_reason, 0.3)),
                    citations=valid, audit_trail=trail.entries,
                    stop_reason=guarded.stop_reason, route=guarded.route, backend=guarded.backend)
```

> 전체 코드와 실행 절차는 [`practice/`](practice/) 와 [`labs/`](labs/) 참조.
> 키 없이 mock 백엔드로 전 흐름이 돈다. `ANTHROPIC_API_KEY` 를 넣으면 같은 코드가
> `backend='claude'` 로 바뀌고 엔드포인트 계약은 그대로다. 비용을 줄이려면 임베딩을 `bge-m3`,
> LLM 을 Ollama 로 바꿔도 파이프라인은 동일하다.

## 7. 결과 해석

`curl -X POST localhost:8000/chat -d '{"query":"Self-RAG 는 언제 검색을 하나?","mode":"agent"}'`
를 던지면 200 과 함께 세 가지가 온다. `answer`(text·citations·confidence 구조), 상위
`citations`(검증 통과한 것만), `audit_trail`(route→retrieve→grade→checkpoint→answer→
citation_check 6단계). 여기서 `citation_check` 의 `hallucinated=0` 은 이번 답의 모든 인용이 실제
검색 결과에 존재한다는 뜻이다.

멀티홉 질문으로 바꾸면 `route` 가 `relation` 으로 바뀌고 인용이 그래프 경로 근거로 붙는다.
예산을 조이면 마지막 단계가 `answer` 가 아니라 `stop`(`budget_exceeded`)으로 남고 `confidence`
가 0.2 로 떨어진다. 체크포인트 거절이면 `rejected_by_human` 으로 답이 보류된다. 무엇이 일어났든
audit_trail 이 그 경로를 그대로 담는다 — 이게 운영·감사·캡스톤 확장의 토대다.

이 여섯 단계가 재현되면 Phase 7 이 닫힌다. 01~05 의 부품이 하나의 State Graph 로 합쳐졌고,
그 위에 구조화 출력·인용 검증·감사 추적이 얹혔다. 캡스톤 3개는 이 하니스 하나를 공유하고
도메인 데이터·온톨로지·평가만 갈아 끼운다.

---

## 🚨 자주 하는 실수

1. **인용 검증을 문자열 포함 여부로 한다** — 답 본문에 `[doc-01]` 이라는 글자가 있는지만 보고
   "인용 있음"으로 판정하면, LLM 이 없는 id 를 써 넣어도 통과한다. 반드시 *실제 검색 결과의 id
   집합*과 대조해야 한다. 그리고 부품마다 인용 id 를 다르게 부르므로(05 는 `source`, 표시용은
   경로 키), 같은 근거를 여러 키로 색인하지 않으면 진짜 인용이 환각으로 오인돼 지워진다.

2. **통합 계층에서 부품을 다시 짠다** — State Graph 를 만든다며 router·grader·guards 를 새로
   구현하면, 04·05 와 로직이 갈라지고 두 벌을 유지해야 한다. 이 토픽은 통합 계층이다.
   `run_guarded` 를 실행 엔진으로 재사용하고 그 결과를 상태·인용·감사 관점으로 재구성만 하라.

3. **Audit Trail 에 raw 결과를 통째로 담는다** — 도구가 뱉은 수천 자 결과를 감사 로그에 그대로
   넣으면 응답이 폭주하고 Langfuse 로 흘릴 때도 비싸진다. 개수·상위 id·grade·예산 스냅샷처럼
   *요약*을 남겨라. 원문이 필요하면 citations 의 snippet(200자 제한)으로 충분하다.

## 출처

- Self-RAG: arXiv [2310.11511](https://arxiv.org/abs/2310.11511) · CRAG: arXiv [2401.15884](https://arxiv.org/abs/2401.15884) · Adaptive-RAG: arXiv [2403.14403](https://arxiv.org/abs/2403.14403)
- Anthropic Tool Use(도구·structured output 강제): https://docs.anthropic.com/en/docs/build-with-claude/tool-use
- LangGraph Agentic RAG 가이드(대안 상태그래프): https://docs.langchain.com/oss/python/langgraph/agentic-rag
- Pydantic(Structured Output 검증): https://docs.pydantic.dev/
- FastAPI: https://fastapi.tiangolo.com/ · Langfuse(감사·관측 연동): https://langfuse.com/docs

## 다음 토픽

→ [하나의 Reference Harness, 세 개의 Domain Adapter](../../phase-08-operations/01-reference-harness-adapters/lesson.md)
