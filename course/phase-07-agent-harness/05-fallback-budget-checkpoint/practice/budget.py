"""budget.py — 루프의 예산(토큰·도구호출 수·wall-clock)을 누적 추적하고 상한을 넘으면 멈춘다.

04 의 MAX_RETRY=2 는 '재시도 횟수' 하나만 막는 원시적 가드였다. 운영 루프는 그것만으로
부족하다. 교정을 반복하다 보면 토큰이 새고, 도구 호출이 쌓이고, 시간이 흐른다. 어느 하나라도
상한을 넘으면 루프를 안전하게 끊어야 한다 — 그게 Budget 가드다.

세 가지 축을 하나의 추적기로 묶는다:
  - tokens      : LLM 이 쓴 입력+출력 토큰 누계. 실제 경로는 Anthropic usage
                  (response.usage.input_tokens / output_tokens)로 센다.
  - tool_calls  : registry.dispatch 호출 횟수 누계.
  - wall_clock  : 루프 시작부터의 경과 초(time.monotonic 기준).

핵심: 매 단계 뒤 check() 를 부른다. 초과했으면 BudgetExceeded 를 던져 상위 루프가 잡고
stop_reason='budget_exceeded' 로 정리한다. 예외를 쓰는 이유는, 예산 초과는 '정상 흐름의
분기'가 아니라 '어디서든 즉시 중단'이어야 하기 때문이다.

mock 경로(키 없음)에는 실제 usage 가 없다. 이때는 add_tokens(estimate_tokens(text))로
문자 길이 기반 추정 토큰을 센다. 정확한 과금이 목적이 아니라 '예산이 준다'는 흐름을 키 없이
재현하는 게 목적이다.

전제: 표준 라이브러리(time·dataclasses)만. 외부 의존 없음.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


class BudgetExceeded(Exception):
    """예산 축(tokens/tool_calls/wall_clock) 중 하나라도 상한을 넘겼을 때 던진다.

    which 로 어떤 축이 터졌는지, spent/limit 로 얼마나 넘었는지 담는다(감사·로그용).
    """

    def __init__(self, which: str, spent: float, limit: float) -> None:
        self.which = which
        self.spent = spent
        self.limit = limit
        super().__init__(f"budget exceeded: {which} {spent} > {limit}")


def estimate_tokens(text: str) -> int:
    """mock 경로용 거친 토큰 추정. 한국어·코드 섞인 텍스트를 대략 4자=1토큰으로 본다.

    실제 토크나이저가 아니다. 상용 API 없이도 '토큰이 쌓여 예산이 준다'를 보이기 위한 근사다.
    실제 경로에서는 이 대신 response.usage 값을 add_tokens 로 넣는다.
    """
    return max(1, len(text) // 4)


@dataclass
class Budget:
    """토큰·도구호출·시간 상한을 들고 누적을 추적하는 예산 가드.

    상한 인자에 None 을 주면 그 축은 검사하지 않는다(무제한). 세 축을 독립적으로 켜고 끈다.
    """

    max_tokens: int | None = 20_000
    max_tool_calls: int | None = 8
    max_seconds: float | None = 30.0

    spent_tokens: int = 0
    spent_tool_calls: int = 0
    _t0: float = field(default_factory=time.monotonic)

    # ── 누적 기록 ────────────────────────────────────────────────────────────
    def add_tokens(self, n: int) -> None:
        """LLM 토큰 사용량을 누계에 더한다. 실제 경로는 usage, mock 은 estimate_tokens."""
        self.spent_tokens += int(n)

    def add_tool_call(self, n: int = 1) -> None:
        """도구 호출 횟수를 누계에 더한다. dispatch 한 번마다 1."""
        self.spent_tool_calls += n

    def elapsed(self) -> float:
        """루프 시작 이후 경과 초."""
        return time.monotonic() - self._t0

    # ── 상한 검사 ────────────────────────────────────────────────────────────
    def check(self) -> None:
        """세 축을 모두 검사한다. 하나라도 넘었으면 BudgetExceeded 를 던진다.

        매 단계(라우팅·검색·채점·재작성) 뒤에 부른다. 넘기 전에는 조용히 통과한다.
        """
        if self.max_tokens is not None and self.spent_tokens > self.max_tokens:
            raise BudgetExceeded("tokens", self.spent_tokens, self.max_tokens)
        if self.max_tool_calls is not None and self.spent_tool_calls > self.max_tool_calls:
            raise BudgetExceeded("tool_calls", self.spent_tool_calls, self.max_tool_calls)
        if self.max_seconds is not None and self.elapsed() > self.max_seconds:
            raise BudgetExceeded("wall_clock", round(self.elapsed(), 2), self.max_seconds)

    def would_exceed_tool_calls(self, extra: int = 1) -> bool:
        """다음 호출을 '하기 전에' 미리 물어본다 — 호출하면 상한을 넘는가?

        check() 는 이미 쓴 뒤 사후 판정이라, 비싼 도구 호출을 아끼려면 사전 확인이 유용하다.
        stop 조건 판정(loop 이 계속 돌지 말지)에 쓴다.
        """
        if self.max_tool_calls is None:
            return False
        return self.spent_tool_calls + extra > self.max_tool_calls

    def snapshot(self) -> dict:
        """현재 소비 상태를 딕셔너리로(감사·labs 대조용)."""
        return {
            "tokens": f"{self.spent_tokens}/{self.max_tokens}",
            "tool_calls": f"{self.spent_tool_calls}/{self.max_tool_calls}",
            "seconds": f"{self.elapsed():.2f}/{self.max_seconds}",
        }


if __name__ == "__main__":
    # 빠른 자기점검: 도구 호출 상한을 낮게 잡고 넘겨 본다.
    b = Budget(max_tokens=1000, max_tool_calls=2, max_seconds=10)
    print("초기:", b.snapshot())
    for i in range(1, 5):
        b.add_tool_call()
        b.add_tokens(estimate_tokens("가" * 200))
        try:
            b.check()
            print(f"호출 {i} 통과:", b.snapshot())
        except BudgetExceeded as e:
            print(f"호출 {i} 중단 → BudgetExceeded(which={e.which}, spent={e.spent}, limit={e.limit})")
            break
