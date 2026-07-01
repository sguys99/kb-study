# Lab 7.4 — Adaptive · Corrective RAG 핸즈온

Router · Grader · Query Rewrite를 하나씩 돌려 보고, 마지막에 셋을 묶은 `adaptive_loop`로 적응형 + 교정형 흐름을 확인한다. 모두 **비용 0 mock 경로**로 동작한다(키가 없으면 규칙 폴백). 실제 LLM 판정을 보려면 `ANTHROPIC_API_KEY`를 설정하면 같은 흐름이 Claude 판정으로 바뀐다.

## 0. 준비

```bash
cd course/phase-07-agent-harness/04-adaptive-corrective-rag/practice
python3 -m pip install -r requirements.txt   # 표준 라이브러리 + (선택) anthropic
```

전제: 이 토픽은 03 harness(`../../03-cypher-safety-ontology-check/practice/register_all_tools.py`)를 import해 도구 3개를 재사용한다. 03 practice가 같은 저장소에 있어야 한다(경로는 `adaptive_loop.py`가 자동으로 잡는다).

## 1. Router 단독 — 질문 유형별로 도구가 갈리는지

```bash
python3 router.py
```

예상 출력(규칙 폴백):

```
[router] backend=rule

Q: Self-RAG 는 언제 검색을 하나?
   route=simple    tool=docs_search    reason=단순 사실·정의 질문 → docs_search 1회
   tool_input={"query": "Self-RAG 는 언제 검색을 하나?", "k": 3}

Q: CRAG 와 Self-RAG 는 어떻게 연결돼 있나?
   route=relation  tool=graph_query    reason=관계·멀티홉 신호(엔티티 2개) → graph_query(template)
   tool_input={"method": "template", "template": "path_between", "params": {"source": "CRAG", "target": "Self-RAG"}}

Q: GraphRAG 진영에는 어떤 것들이 있는지 전체를 요약해줘
   route=broad     tool=graph_query    reason=전체 요약·개괄 질문 → lightrag(global)
   tool_input={"method": "lightrag", "question": "...", "mode": "global"}

Q: Component 가 Method 를 USES 하는 관계는 스키마상 타당한가?
   route=schema    tool=ontology_check reason=스키마·온톨로지 타당성 질문 → ontology_check
   tool_input={"triples": [{"subject": "Component", "relation": "USES", "object": "Method"}]}
```

네 유형이 서로 다른 도구·입력으로 매핑되면 통과. 엔티티 2개짜리 관계 질문이 `path_between` template으로 가는 데 주목.

## 2. Grader 단독 — 충분/부족을 3등급으로

```bash
python3 grader.py
```

예상 출력:

```
[grader] backend=rule

정상 결과: {'grade': 'relevant', 'score': 1.0, 'reason': '질문 용어와 겹침 1.00 ≥ 0.5', 'n_rows': 1, 'backend': 'rule'}
빈 결과  : {'grade': 'irrelevant', 'score': 0.0, 'reason': '검색 결과가 비었다', 'n_rows': 0, 'backend': 'rule'}
빗나간 결과: {'grade': 'irrelevant', 'score': 0.0, 'reason': '질문 용어와 겹침 0.00 ≤ 0.15', 'n_rows': 1, 'backend': 'rule'}
```

빈 결과와 빗나간 결과가 모두 `irrelevant`로 떨어지면 교정 트리거가 제대로 걸린다는 뜻이다.

## 3. Query Rewrite 단독 — 질의를 검색 친화로

```bash
python3 query_rewrite.py
```

예상 출력:

```
[query_rewrite] backend=rule

원  : Self-RAG 는 도대체 언제 검색을 하는 건가요?
재작성: 'Self-RAG 검색'  (엔티티 중심 축약 + 조사·질문투 제거, changed=True)

원  : CRAG 와 Self-RAG 의 차이가 무엇인지 정리해줘
재작성: 'Self-RAG CRAG'  (엔티티 중심 축약 + 조사·질문투 제거, changed=True)

원  : 그건 어떻게 동작하나요?
재작성: '그건 어떻게 동작하나요?'  (조사·질문투 제거, changed=False)
```

엔티티가 없는 마지막 질문은 `changed=False` — 재작성해도 달라질 게 없으니 루프가 여기서 멈춘다.

## 4. 단순 질문 — Router가 docs_search 한 번으로 끝낸다

```bash
python3 adaptive_loop.py "Self-RAG 는 언제 검색을 하나?"
```

예상 출력(발췌):

```
[route] simple  →  docs_search  (단순 사실·정의 질문 → docs_search 1회)
[try 1] tool=docs_search query='Self-RAG 는 언제 검색을 하나?'
          grade=relevant score=1.00 (질문 용어와 겹침 1.00 ≥ 0.5)
[answer] ... [doc-self-rag-01] [doc-tool-contract-01] [doc-agentic-rag-01]
--- 요약 ---  route: simple  tool_calls: [docs_search]  retries: 0  grades: [relevant]
```

`retries: 0` — 첫 검색이 충분해 교정이 안 걸렸다.

## 5. 관계 질문 — Grade가 부족을 잡아 Rewrite로 회복

```bash
python3 adaptive_loop.py "Self-RAG 와 CRAG 는 무엇이 다른가?"
```

예상 출력(발췌):

```
[route] relation  →  graph_query
[try 1] tool=graph_query ...
          grade=ambiguous ... → rewrite: 'Self-RAG CRAG 다른' → docs_search 재검색
[try 2] tool=docs_search query='Self-RAG CRAG 다른'
          grade=relevant score=0.50 (질문 용어와 겹침 0.50 ≥ 0.5)
[answer] ... [doc-adaptive-rag-01] [doc-self-rag-01] [doc-crag-01]
--- 요약 ---
{
  "route": "relation",
  "tool_calls": ["graph_query", "docs_search"],
  "retries": 1,
  "grades": ["ambiguous", "relevant"],
  "citations": ["doc-adaptive-rag-01", "doc-self-rag-01", "doc-crag-01"]
}
```

`grades: [ambiguous, relevant]` + `retries: 1` — 첫 검색이 부족해 한 번 교정했고 회복됐다. **완료 기준 충족**: Router가 도구를 고르고, Grader가 불충분을 잡아 Query Rewrite로 재검색해 답을 회복하며, 재시도 상한 안에서 인용이 붙었다.

## 6. 스키마 질문 — 검증 경로는 verdict가 곧 답

```bash
python3 adaptive_loop.py "Component 가 Method 를 USES 하는 관계는 스키마상 타당한가?"
```

예상 출력(발췌):

```
[route] schema  →  ontology_check
[try 1] tool=ontology_check ...
          verdict ok=False violations=1
[answer] ... → 스키마 위반이다. 방향 위반: USES 는 (Method)-[USES]->(Component) 만 허용. ... (ontology_check ok=false)
--- 요약 ---  route: schema  retries: 0  grades: [relevant]
```

검증 경로는 Grader·Rewrite를 태우지 않는다(`retries: 0`). ontology_check의 verdict가 그대로 답이 된다.

## 헬스체크 표

| 확인 | 명령 | 통과 신호 |
|------|------|-----------|
| Router 4분기 | `python3 router.py` | simple/relation/broad/schema가 서로 다른 도구로 |
| Grader 3등급 | `python3 grader.py` | 빈/빗나간 결과가 `irrelevant` |
| Rewrite | `python3 query_rewrite.py` | 엔티티 질문 `changed=True`, 무엔티티 `changed=False` |
| 적응형 | 4번 lab | `route: simple`, `retries: 0` |
| 교정형 | 5번 lab | `grades: [ambiguous, relevant]`, `retries: 1` |
| 검증 경로 | 6번 lab | `route: schema`, verdict가 답 |

## 실제 LLM 경로로 바꾸기

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export HARNESS_MODEL=claude-sonnet-4-6   # 선택(기본값 동일)
python3 adaptive_loop.py "Self-RAG 와 CRAG 는 무엇이 다른가?"
```

backend가 `rule/mock` → `claude`로 바뀐다. 다섯 단계 제어 흐름과 인용 형식은 동일하고, Router·Grader·Rewrite 판정과 최종 답변의 질만 올라간다. 비용을 0으로 유지하려면 키 없이 위 mock 경로로 흐름만 익히면 된다.
