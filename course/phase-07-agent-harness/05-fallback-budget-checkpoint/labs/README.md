# Labs — 05 Fallback · Budget · Checkpoint 가드 계층 핸즈온

04 의 adaptive_loop 위에 얹은 가드(예산·재시도·폴백·캐시·정지·사람 승인)가 실제로 동작하는지
네 시나리오로 확인한다. **API 키 없이 mock 으로 전 흐름을 재현**한다. 모든 실행 앞에
`AUTO_APPROVE` 를 설정해 비대화(사람 없이)로 돌린다.

## 0. 준비

```bash
cd course/phase-07-agent-harness/05-fallback-budget-checkpoint/practice

# 04 와 같은 가상환경을 재사용하면 추가 설치가 없다. 새로 만들 때만:
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 체크포인트를 비대화로: 자동 승인(기본과 동일)
export AUTO_APPROVE=1
```

가드 3종(budget·guards·checkpoint)은 표준 라이브러리만 쓴다. 상위 루프(guarded_loop)는
04(router·grader·query_rewrite)와 03(register_all_tools)을 import 경로에 자동으로 올린다.

### 헬스체크 — 가드 3종 단위 자기점검

```bash
python budget.py
python guards.py
AUTO_APPROVE=1 python checkpoint.py
```

예상 출력(요지):

```
# budget.py
초기: {'tokens': '0/1000', 'tool_calls': '0/2', 'seconds': '0.00/10'}
호출 1 통과: {'tokens': '50/1000', 'tool_calls': '1/2', 'seconds': '0.00/10'}
호출 2 통과: {'tokens': '100/1000', 'tool_calls': '2/2', 'seconds': '0.00/10'}
호출 3 중단 → BudgetExceeded(which=tool_calls, spent=3, limit=2)

# guards.py
  재시도 1회 (사유: 일시적 오류(호출 1)) — 0.010s 대기
  재시도 2회 (사유: 일시적 오류(호출 2)) — 0.020s 대기
retry 결과: 성공 (총 3회 호출)
cache: {'hits': 1, 'misses': 1, 'size': 1} 동일 결과: True

# checkpoint.py
저신뢰: CheckpointDecision(needed=True, approved=True, reasons=['저신뢰(score=0.20 < 0.5)'], mode='auto-approve')
위험  : CheckpointDecision(needed=True, approved=True, reasons=['쓰기·삭제 유사 표현 감지'], mode='auto-approve')
정상  : CheckpointDecision(needed=False, approved=True, reasons=[], mode='not-needed')
```

세 가드가 각각 예산 초과 감지 · 재시도 후 성공 · 캐시 hit · 저신뢰/위험 판정을 하면 준비 완료.

---

## 시나리오 1 — 예산을 낮추면 `budget_exceeded` 로 멈춘다

`max_tool_calls=1` 로 예산을 조인다. 첫 검색이 부실해 재시도로 가려는 순간, 다음 도구 호출이
상한을 넘길 것을 미리 감지하고 루프가 멈춘다.

```bash
python -c "
from budget import Budget
from guarded_loop import run_guarded
b = Budget(max_tokens=None, max_tool_calls=1, max_seconds=None)
r = run_guarded('Mamba 아키텍처는 무엇인가?', budget=b, verbose=True)
print('STOP_REASON =', r.stop_reason)
"
```

예상 출력:

```
[guarded] backend=rule/mock
[route] simple → docs_search (단순 사실·정의 질문 → docs_search 1회)
[try 1] tool=docs_search grade=irrelevant score=0.00 budget={'tokens': '1/None', 'tool_calls': '1/1', 'seconds': '0.00/None'}
[checkpoint] 승인(auto-approve) 사유=['저신뢰(score=0.30 < 0.5)']

[answer] (backend=mock, stop_reason=budget_exceeded)
'Mamba 아키텍처는 무엇인가?' 에 대한 답: 검색된 근거를 종합하면 아래와 같다. [근거 없음]
STOP_REASON = budget_exceeded
```

`tool_calls` 가 상한(1)에 닿자마자 재시도로 넘어가지 않고 `stop_reason=budget_exceeded` 로
안전하게 종료됐다. `Mamba`는 mock 코퍼스에 없는 엔티티라 검색이 계속 빈약해 재시도를 유발하는
질의로 골랐다. 예산이 없었다면 `max_retry` 까지 도구를 세 번 태웠을 것이다.

> `max_tool_calls=8`(기본)로 돌리면 이 질의는 `stop_reason=max_retry` 로 끝난다 — 예산이 아니라
> 재시도 상한이 먼저 걸리기 때문. 예산을 낮출수록 더 일찍 멈춘다.

---

## 시나리오 2 — 도구를 강제 실패시키면 retry 후 fallback 도구로 회복한다

`fail_tools={'graph_query'}` 로 `graph_query` 를 강제로 죽인다. retry(지수 백오프)가 세 번까지
버티다 소진되면, **같은 질의로 다른 도구**(`docs_search`)로 폴백해 답을 건진다.

```bash
python -c "
from guarded_loop import run_guarded
r = run_guarded('CRAG 와 Self-RAG 는 어떻게 연결돼 있나?', fail_tools={'graph_query'}, verbose=True)
print('fell_back =', r.fell_back, '| stop =', r.stop_reason)
"
```

예상 출력:

```
[guarded] backend=rule/mock
[route] relation → graph_query (관계·멀티홉 신호(엔티티 2개) → graph_query(template))
          retry 1회 (사유: graph_query 강제 실패(주입))
          retry 2회 (사유: graph_query 강제 실패(주입))
          fallback: graph_query 실패 → docs_search 로 우회(같은 질의)
[try 1] tool=docs_search grade=relevant score=0.67 budget={'tokens': '179/20000', 'tool_calls': '4/8', 'seconds': '0.00/30.0'}

[answer] (backend=mock, stop_reason=answered)
'CRAG 와 Self-RAG 는 어떻게 연결돼 있나?' 에 대한 답: 검색된 근거를 종합하면 아래와 같다. [doc-self-rag-01] [doc-crag-01] [doc-tool-contract-01]
fell_back = True | stop = answered
```

라우터는 관계 질문이라 `graph_query` 를 골랐지만 그게 죽었다. retry 두 번(3회 시도)이 실패한 뒤
`docs_search` 로 폴백해 `relevant` 근거를 찾고 `answered` 로 끝났다. `tool_calls` 예산이 4까지
오른 이유는 실패한 시도들도 호출로 세기 때문이다(운영에서 실패도 비용이다).

> **Fallback vs Rewrite** — 여기 폴백은 *다른 도구, 같은 질의*다. 04 의 Query Rewrite 는
> *같은 도구, 다른 질의*였다. 도구 자체가 안 되면 폴백, 질의어가 나쁘면 재작성.

---

## 시나리오 3 — 같은 질의를 두 번 부르면 2번째는 cache hit

캐시를 두 호출에 공유한다. 첫 호출은 miss(도구 실행), 둘째 호출은 hit(도구 안 태움).

```bash
python -c "
from guards import ToolCache
from guarded_loop import run_guarded
c = ToolCache(ttl=300)
q = 'Self-RAG 는 언제 검색을 하나?'
r1 = run_guarded(q, cache=c, verbose=False); print('1회차 cache:', r1.cache)
r2 = run_guarded(q, cache=c, verbose=False); print('2회차 cache:', r2.cache)
"
```

예상 출력:

```
1회차 cache: {'hits': 0, 'misses': 1, 'size': 1}
2회차 cache: {'hits': 1, 'misses': 1, 'size': 1}
```

첫 호출에서 `(docs_search, {query,k})` 결과가 캐시에 들어가고(miss=1), 둘째 호출은 같은 키라
도구를 안 태우고 캐시에서 준다(hit=1). 재시도·반복 질의가 많은 운영 루프에서 비용·지연이 준다.
`ttl` 을 넘긴 항목은 만료로 보고 다시 계산한다.

---

## 시나리오 4 — 저신뢰 답은 Human Checkpoint 승인을 거친다

교정을 다 소진해도 근거가 부실하면(저신뢰) 사람 승인 후크가 걸린다. 비대화 실행이라
`AUTO_APPROVE` 로 승인/거절을 자동화한다.

### 4a. 자동 승인(`AUTO_APPROVE=1`) — 승인 후 답 반환

```bash
AUTO_APPROVE=1 python -c "
from guarded_loop import run_guarded
r = run_guarded('완전히 무관한 외계어 질문 zzzxxx', verbose=True)
print('checkpoint =', r.checkpoint, '| stop =', r.stop_reason)
"
```

예상 출력(요지):

```
[try 3] tool=docs_search grade=irrelevant score=0.00 budget={'tokens': '3/20000', 'tool_calls': '3/8', 'seconds': '0.00/30.0'}
[checkpoint] 승인(auto-approve) 사유=['저신뢰(score=0.30 < 0.5)']

[answer] (backend=mock, stop_reason=max_retry)
'완전히 무관한 외계어 질문 zzzxxx' 에 대한 답: 검색된 근거를 종합하면 아래와 같다. [근거 없음]
checkpoint = {'needed': True, 'approved': True, 'mode': 'auto-approve', 'reasons': ['저신뢰(score=0.30 < 0.5)']} | stop = max_retry
```

`needed=True`(저신뢰라 승인 필요)인데 `approved=True`(자동 승인)라 답이 그대로 반환됐다.

### 4b. 자동 거절(`AUTO_APPROVE=0`) — `rejected_by_human` 으로 보류

```bash
AUTO_APPROVE=0 python -c "
from guarded_loop import run_guarded
r = run_guarded('완전히 무관한 외계어 질문 zzzxxx', verbose=False)
print('checkpoint =', r.checkpoint, '| stop =', r.stop_reason)
print('answer =', r.answer)
"
```

예상 출력:

```
checkpoint = {'needed': True, 'approved': False, 'mode': 'auto-reject', 'reasons': ['저신뢰(score=0.30 < 0.5)']} | stop = rejected_by_human
answer = '완전히 무관한 외계어 질문 zzzxxx' → 사람 승인 거절로 답을 보류한다. (사유: ['저신뢰(score=0.30 < 0.5)'])
```

거절되면 `stop_reason=rejected_by_human` 으로 답을 내보내지 않고 보류한다.

### 4c. 실제 콘솔 승인(`AUTO_APPROVE=ask`) — 사람이 y/N 입력

```bash
AUTO_APPROVE=ask python guarded_loop.py "완전히 무관한 외계어 질문 zzzxxx"
# [HUMAN CHECKPOINT] 사람 승인이 필요합니다.
#   - 사유: 저신뢰(score=0.30 < 0.5)
#   ...
#   진행할까요? [y/N]   ← 여기서 사람이 입력. y 면 반환, 그 외면 보류.
```

위험 신호(쓰기·삭제 동사·민감어)가 있을 때도 같은 체크포인트가 걸린다:

```bash
AUTO_APPROVE=0 python -c "
from guarded_loop import run_guarded
r = run_guarded('이 노드를 delete 하는 관계가 스키마상 맞나?', verbose=False)
print(r.checkpoint['reasons'], '| stop =', r.stop_reason)
"
# ['쓰기·삭제 유사 표현 감지'] 등 사유가 잡히고, 거절이면 rejected_by_human.
```

---

## 완료 체크

- [ ] 시나리오 1: 예산을 낮추면 `stop_reason=budget_exceeded` 로 멈춘다
- [ ] 시나리오 2: `graph_query` 강제 실패 → retry 후 `docs_search` 폴백으로 `answered` 회복 (`fell_back=True`)
- [ ] 시나리오 3: 같은 질의 2회차에서 cache `hits=1`
- [ ] 시나리오 4: 저신뢰 답이 checkpoint 승인(`AUTO_APPROVE=1`)을 거쳐 반환되고, 거절(`=0`)이면 `rejected_by_human`

네 가지가 모두 재현되면 이 토픽 완료다.
