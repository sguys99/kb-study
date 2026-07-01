# 7.5 Fallback · Budget · Checkpoint — 루프를 운영 가능하게

> **Phase 7 · 토픽 05** · 04 의 적응·교정 루프 위에 예산·재시도·폴백·캐시·정지·사람 승인 가드를 얹어 "운영해도 되는" 루프로 만든다.

## 학습 목표

이 토픽을 끝내면 다음을 할 수 있다.

- 토큰·도구호출·wall-clock 상한을 누적 추적하는 Budget 가드를 만들고, 초과 시 `BudgetExceeded` 로 루프를 안전하게 멈춘다.
- 일시적 오류에 지수 백오프로 재시도하는 `retry` 데코레이터와, 도구가 죽으면 다른 도구로 갈아타는 Fallback 헬퍼를 구현한다.
- Fallback(다른 도구·같은 질의)과 04 의 Query Rewrite(같은 도구·다른 질의)를 구분해 설명한다.
- 저신뢰·위험 상황에서 사람 승인을 받는 Human Checkpoint 후크를 만들고, `AUTO_APPROVE` 로 비대화 실행까지 지원한다.
- 04 `run_adaptive` 를 다시 짜지 않고, 그 부품(router·grader·query_rewrite·registry)을 재사용해 가드를 끼운 상위 루프 `run_guarded` 로 감싼다.

**완료 기준**: 예산을 낮추면 루프가 `budget_exceeded` stop_reason 으로 안전하게 멈추고, 도구 실패 시 retry 후 fallback 도구로 회복하며, 저신뢰 답변은 Human Checkpoint 승인을 거쳐 반환되면 완료.

---

## 1. 왜 필요한가 — 04 루프는 아직 "운영"할 수 없다

04 까지 우리는 Router·Grader·Query Rewrite 로 적응·교정 루프를 만들었다. 데모로는 훌륭하다.
그런데 이걸 그대로 서비스에 올리면 어떻게 될까.

`graph_query` 로 라우팅됐는데 그 도구가 타임아웃으로 죽으면? 04 루프는 거기서 멈춘다. 재작성을
반복하다 토큰이 계속 새면? 04 에는 예산 개념이 없다. Grader 가 근거가 부실하다고 계속 말하는데도
루프는 최선의(그래봤자 부실한) 답을 그냥 내보낸다. 삭제·결제 같은 위험한 질의도 아무 제동 없이
지나간다.

04 의 `MAX_RETRY=2` 는 이 문제의 절반짜리 답이었다. "재시도 횟수"라는 축 하나만 막았을 뿐이다.
운영 루프는 여러 축을 동시에 지켜야 한다. 이 토픽은 그 위에 **가드 계층**을 얹는다. 04 를 다시
짜지 않는다 — router·grader·query_rewrite 와 03 registry 를 그대로 부품으로 쓰고, 그 사이사이에
가드를 끼운다.

여섯 가드를 다룬다.

| 가드 | 무엇을 막나 | 어떻게 |
|------|------------|--------|
| Fallback | 도구가 아예 안 됨 | 같은 질의를 다른 도구로 우회 |
| Retry | 일시적 오류(타임아웃·429) | 지수 백오프 재시도 |
| Cache | 반복 질의·재시도의 낭비 | (도구,입력) 키로 결과 캐싱 + TTL |
| Budget | 토큰·호출·시간 폭주 | 누적 추적하다 초과 시 `BudgetExceeded` |
| Stop | 끝나지 않는 루프 | 명시적 종료 조건 + `stop_reason` 반환 |
| Human Checkpoint | 저신뢰·위험 답 방류 | 사람 승인 후크(비대화 지원) |

## 2. Budget — 세 축을 하나로 묶어 추적한다

예산은 세 축이다. 토큰(LLM 이 쓴 input+output), 도구 호출 수, 경과 시간. 매 단계 뒤에
`check()` 를 부르고, 어느 하나라도 상한을 넘으면 예외를 던진다. 예외를 쓰는 이유는 예산 초과가
"정상 흐름의 분기"가 아니라 "어디서든 즉시 중단"이어야 하기 때문이다.

```python
# practice/budget.py 의 핵심
class BudgetExceeded(Exception):
    def __init__(self, which: str, spent: float, limit: float) -> None:
        self.which, self.spent, self.limit = which, spent, limit
        super().__init__(f"budget exceeded: {which} {spent} > {limit}")

@dataclass
class Budget:
    max_tokens: int | None = 20_000
    max_tool_calls: int | None = 8
    max_seconds: float | None = 30.0
    # ... 누계 필드 ...

    def check(self) -> None:
        if self.max_tokens is not None and self.spent_tokens > self.max_tokens:
            raise BudgetExceeded("tokens", self.spent_tokens, self.max_tokens)
        if self.max_tool_calls is not None and self.spent_tool_calls > self.max_tool_calls:
            raise BudgetExceeded("tool_calls", self.spent_tool_calls, self.max_tool_calls)
        if self.max_seconds is not None and self.elapsed() > self.max_seconds:
            raise BudgetExceeded("wall_clock", round(self.elapsed(), 2), self.max_seconds)
```

토큰은 어떻게 세나. 실제 경로에서는 Anthropic 응답의 `response.usage.input_tokens` +
`output_tokens` 를 그대로 더한다. 키가 없는 mock 경로에는 usage 가 없으니 문자 길이로 근사한다
(`estimate_tokens`, 대략 4자=1토큰). 정확한 과금이 목적이 아니라 "토큰이 쌓여 예산이 준다"는
흐름을 키 없이 재현하는 게 목적이다.

## 3. Retry · Fallback · Cache — 표준 라이브러리로 짜는 세 가드

무거운 프레임워크는 안 쓴다. 백오프 로직을 눈으로 보려고 직접 짠다.

**Retry** 는 일시적 오류에만 건다. 내용이 나빠서가 아니라 "한 번 더 하면 될" 오류(타임아웃·429·
커넥션 흔들림)에 지수 백오프로 다시 시도한다.

```python
# practice/guards.py — retry 데코레이터
def retry(max_attempts=3, base_delay=0.2, factor=2.0,
          exceptions=(ToolFailure, TimeoutError, ConnectionError),
          sleep=time.sleep, on_retry=None):
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            last = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return fn(*args, **kwargs)
                except exceptions as e:      # 지정한 '일시적' 예외만 잡는다
                    last = e
                    if attempt >= max_attempts:
                        break
                    delay = base_delay * (factor ** (attempt - 1))  # 지수 백오프
                    if on_retry: on_retry(attempt, e, delay)
                    sleep(delay)
            raise last
        return wrapper
    return deco
```

`sleep` 을 주입 가능하게 뒀다. 테스트·labs 에서 `sleep=lambda _: None` 을 넣으면 실제로 안 자고도
백오프 흐름을 확인한다. (프로덕션에서 재시도 정책이 복잡해지면 `tenacity` 같은 라이브러리로
바꾸면 되지만, 이 코스는 로직을 직접 보인다.)

**Fallback** 은 도구가 재시도까지 다 실패하거나 빈 결과를 주면 **다른 도구**로 갈아탄다. 같은
질의, 다른 도구. `graph_query` 가 죽으면 `docs_search` 로.

```python
# practice/guards.py — 폴백 헬퍼
def run_with_fallback(primary_tool, fallback_tool, call):
    tried = [primary_tool]
    try:
        primary = call(primary_tool)
        if primary_tool == fallback_tool or not is_empty_or_error(primary):
            return FallbackResult(primary_tool, primary, fell_back=False, tried=tried)
    except Exception:
        primary = None                       # 예외로 죽어도 폴백을 시도
        if primary_tool == fallback_tool:
            raise
    tried.append(fallback_tool)
    return FallbackResult(fallback_tool, call(fallback_tool), fell_back=True, tried=tried)
```

### Fallback vs Rewrite — 헷갈리지 마라

04 의 Query Rewrite 와 05 의 Fallback 은 자주 혼동된다. 둘 다 "실패했으니 다시"지만 축이 다르다.

| | 바꾸는 것 | 언제 | 어디서 |
|---|---------|------|--------|
| **Query Rewrite** (04) | 같은 도구, **다른 질의** | 질의어가 나빠 못 찾음 | Grader 가 `relevant` 아님 |
| **Fallback** (05) | **다른 도구**, 같은 질의 | 그 도구가 아예 안 됨 | 도구 실패·빈 결과 |

질의어를 다듬어 해결될 문제면 재작성, 도구 자체가 죽은 문제면 폴백이다. 실제 루프에서는 폴백으로
도구를 바꾼 뒤, 거기서도 부족하면 재작성으로 질의를 다듬는다 — 둘은 배타가 아니라 층이 다르다.

**Cache** 는 `(도구, 입력)` 을 키로 결과를 저장한다. 같은 질의를 다시 부르면 도구를 안 태우고
캐시에서 준다. 재시도·반복 질의가 많은 루프에서 비용·지연이 준다. `functools.lru_cache` 대신
직접 짠 이유는, dict 입력은 해시가 안 되니 얼려서 키를 만들고 TTL(만료)과 hit 통계를 눈에
보이게 하려는 것이다.

## 4. Human Checkpoint — 기계가 단독으로 넘기면 안 되는 순간

지금까지 가드는 기계가 알아서 멈추거나 우회했다. 하지만 어떤 상황은 사람이 봐야 한다. 저신뢰
(Grader score 가 낮은데 답을 내보내려 함)와 위험(삭제·쓰기 유사, 결제·개인정보 같은 민감어)이다.

```python
# practice/checkpoint.py — 승인 후크
LOW_CONFIDENCE_TH = 0.5

def assess(question, answer, score) -> list[str]:
    reasons = []
    if score < LOW_CONFIDENCE_TH:
        reasons.append(f"저신뢰(score={score:.2f} < {LOW_CONFIDENCE_TH})")
    blob = f"{question}\n{answer}"
    if _WRITE_LIKE.search(blob):  reasons.append("쓰기·삭제 유사 표현 감지")
    if _SENSITIVE.search(blob):   reasons.append("민감어(개인정보·자격증명) 감지")
    return reasons
```

승인을 어떻게 받나. 콘솔에서 사람에게 물어보는 게 기본이지만, CI·테스트·labs 는 `input()` 을
받을 수 없다. 그래서 `AUTO_APPROVE` 환경변수로 비대화 실행을 반드시 지원한다.

- `AUTO_APPROVE` 미설정 또는 `1`/`yes` → 자동 승인(테스트 기본)
- `AUTO_APPROVE=0`/`no` → 자동 거절 → `stop_reason=rejected_by_human`
- `AUTO_APPROVE=ask` → 콘솔 `input()` 으로 실제 사람에게 y/N

기본을 자동 승인으로 둬서 키·터미널 없이도 전 흐름이 막히지 않고 돈다.

## 5. 가드를 끼운 상위 루프 — `run_guarded`

이제 부품을 조립한다. `guarded_loop.py` 는 04 의 흐름(Route→Retrieve→Grade→Rewrite&Retry→
Answer)에 가드를 끼운다. 도구 실행은 `retry` 로 감싸고, 실패하면 `run_with_fallback` 으로
우회하며, 캐시를 먼저 보고, 매 단계 예산을 누적해 `check()` 하고, 종료 시 `stop_reason` 을 반환하며,
마지막에 저신뢰·위험이면 체크포인트를 태운다.

```python
# practice/guarded_loop.py — 검색 한 단계(캐시 → retry → fallback)
def _do(t, ti):
    return cache.get_or_call(t, ti,
        lambda: _dispatch_json(registry, t, ti, budget, fail_tools))  # retry 는 _dispatch_json 안

fb = run_with_fallback(tool, fb_tool,
    lambda t: _do(t, tool_input if t == tool else {"query": cur_query, "k": 3}))
retrieval = fb.result
budget.check()                          # 검색 후 예산 점검

g = grade(cur_query, retrieval)         # 04 grader 재사용
if g.sufficient:
    result.stop_reason = "answered"; break
if attempt_i >= MAX_RETRY + 1:
    result.stop_reason = "max_retry"; break
if budget.would_exceed_tool_calls(extra=1):
    result.stop_reason = "budget_exceeded"; break   # 다음 호출이 예산을 넘길 것을 미리 감지
```

`stop_reason` 은 반드시 하나를 반환한다: `answered` / `budget_exceeded` / `max_retry` /
`no_change` / `rejected_by_human`. 04 가 "왜 멈췄는지" 를 남기지 않고 끝났다면, 05 는 종료 이유를
명시한다 — 이게 다음 토픽(06)의 감사 추적으로 이어진다.

> 전체 코드와 실행 절차는 [`practice/`](practice/) 와 [`labs/`](labs/) 참조.
> 비용을 줄이려면 임베딩을 `bge-m3`(로컬), LLM 을 Ollama 로 바꿔도 된다. 결과 품질은 떨어질 수
> 있으나 가드 흐름은 동일하다. 키가 아예 없으면 mock 경로로 전 시나리오가 그대로 돈다.

## 6. 결과 해석

labs 의 네 시나리오가 각 가드를 하나씩 증명한다.

- **예산**: `max_tool_calls=1` 로 조이면, 재시도로 넘어가려는 순간 다음 호출이 상한을 넘길 것을
  감지해 `stop_reason=budget_exceeded` 로 멈춘다. 예산이 없었다면 `max_retry` 까지 도구를 세 번
  더 태웠을 것이다.
- **폴백**: `graph_query` 를 강제로 죽이면 retry 두 번(3회 시도)이 실패한 뒤 `docs_search` 로
  폴백해 `relevant` 근거를 찾고 `answered` 로 끝난다. `fell_back=True`. 실패한 시도도 호출로
  세어 `tool_calls` 가 4까지 오른다 — 운영에서 실패도 비용이다.
- **캐시**: 같은 질의 2회차는 `hits=1`. 도구를 안 태우고 캐시에서 답한다.
- **체크포인트**: 근거가 계속 부실한 저신뢰 답은 `needed=True` 로 승인을 요구한다. `AUTO_APPROVE=1`
  이면 승인되어 답이 나가고, `=0` 이면 `rejected_by_human` 으로 보류된다.

이 네 가지가 재현되면, 04 의 데모 루프가 "멈출 줄 알고, 우회할 줄 알고, 사람에게 물어볼 줄 아는"
운영 루프가 됐다는 뜻이다.

---

## 🚨 자주 하는 실수

1. **모든 예외를 재시도한다** — `retry` 가 아무 예외나 잡으면, 잘못된 입력이나 인증 실패처럼
   "다시 해도 똑같이 실패할" 영구 오류까지 지수 백오프로 반복하며 시간·예산을 태운다. 재시도 대상은
   `ToolFailure`·`TimeoutError` 같은 **일시적** 예외로 좁혀야 한다. 그래서 전용 `ToolFailure` 예외를 뒀다.

2. **Fallback 과 Rewrite 를 뒤섞는다** — 도구가 죽었는데 질의만 재작성하면 죽은 도구를 계속 부르고,
   질의어가 나쁜 건데 도구만 바꾸면 다른 도구에서도 같은 나쁜 질의로 헛돈다. "도구가 안 됨 → 폴백",
   "질의어가 나쁨 → 재작성" 을 구분하라. 폴백은 *다른 도구·같은 질의*, 재작성은 *같은 도구·다른 질의*다.

3. **Human Checkpoint 를 `input()` 로만 만든다** — 콘솔 입력만 있으면 CI·테스트·배치 실행에서
   루프가 입력을 기다리다 멈춰버린다(EOFError 나 무한 대기). 반드시 `AUTO_APPROVE` 같은 비대화
   경로를 기본으로 두고, 실제 사람 승인은 `ask` 모드로 옵트인하게 한다.

## 출처

- Self-RAG: arXiv [2310.11511](https://arxiv.org/abs/2310.11511) — 반성 토큰 기반 검색·정지 판단
- CRAG(Corrective RAG): arXiv [2401.15884](https://arxiv.org/abs/2401.15884) — 검색 평가 후 교정·폴백
- Adaptive-RAG: arXiv [2403.14403](https://arxiv.org/abs/2403.14403) — 질문 복잡도별 경로 선택
- Anthropic Messages API — `usage`(input/output tokens): https://docs.anthropic.com/en/api/messages
- Anthropic tool-use(도구 루프): https://docs.anthropic.com/en/docs/build-with-claude/tool-use
- (대안) tenacity — 재시도·백오프 라이브러리: https://github.com/jd/tenacity

## 다음 토픽

→ [Citation · Audit Trail + 통합 State Graph](../06-citation-audit-state-graph/lesson.md)
