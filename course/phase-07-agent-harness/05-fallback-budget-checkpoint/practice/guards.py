"""guards.py — Retry(지수 백오프) · Fallback(대체 도구) · Cache(결과 캐싱)의 세 가드.

04 의 교정 재시도(Query Rewrite)는 '같은 도구, 다른 질의'였다. 여기서 다루는 세 가드는
결이 다르다. 셋 다 표준 라이브러리 + 작은 래퍼로 짠다(무거운 프레임워크 없음).

  1) Retry    — 일시적 오류(타임아웃·429·네트워크 흔들림)에 지수 백오프로 다시 시도.
                내용 문제가 아니라 '한 번 더 하면 될' 오류에만 건다. 재작성과 무관.
  2) Fallback — 도구가 실패하거나 빈 결과를 주면 '다른 도구'로 갈아탄다.
                예: graph_query 가 죽으면 docs_search 로. 같은 질의, 다른 도구.
  3) Cache    — (도구, 입력) 키로 결과를 저장. 같은 질의를 다시 부르면 도구를 안 태우고
                캐시에서 준다. 재시도·반복 질의의 비용·지연을 줄인다. TTL 로 만료.

Fallback vs Rewrite(반드시 구분):
  - Rewrite(04) : 같은 도구 · 다른 질의. "질의어가 나빠서 못 찾았다"를 고친다.
  - Fallback(05): 다른 도구 · 같은 질의. "이 도구가 아예 안 된다"를 우회한다.

전제: 표준 라이브러리(time·functools·dataclasses)만. tenacity 같은 라이브러리는 대안일 뿐,
  이 코스는 백오프 로직을 눈으로 보려고 직접 짠다.
"""

from __future__ import annotations

import functools
import time
from dataclasses import dataclass, field
from typing import Callable


class ToolFailure(Exception):
    """도구 실행이 일시적으로 실패했음을 알리는 예외. Retry 가 이걸 잡고 재시도한다.

    영구 오류(잘못된 입력 등)와 구분하려고 전용 예외를 둔다. 여기 잡히는 것만 재시도한다.
    """


# ── 1) Retry — 지수 백오프 데코레이터 ────────────────────────────────────────
def retry(
    max_attempts: int = 3,
    base_delay: float = 0.2,
    factor: float = 2.0,
    exceptions: tuple[type[Exception], ...] = (ToolFailure, TimeoutError, ConnectionError),
    sleep: Callable[[float], None] = time.sleep,
    on_retry: Callable[[int, Exception, float], None] | None = None,
):
    """일시적 오류에 지수 백오프로 재시도하는 데코레이터.

    delay = base_delay * factor**(attempt-1). max_attempts 회까지 시도하고, 마지막까지
    실패하면 마지막 예외를 그대로 올린다(상위에서 Fallback 이 받도록).

    sleep 을 주입 가능하게 둔 이유: 테스트·labs 에서 lambda _: None 을 넣어 실제로 안 자게.
    on_retry(attempt, err, delay) 훅으로 재시도 로그를 남길 수 있다(감사용).
    """
    def deco(fn: Callable):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            last: Exception | None = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return fn(*args, **kwargs)
                except exceptions as e:  # 지정한 '일시적' 예외만 잡는다.
                    last = e
                    if attempt >= max_attempts:
                        break  # 상한 도달 — 더 안 잔다.
                    delay = base_delay * (factor ** (attempt - 1))
                    if on_retry is not None:
                        on_retry(attempt, e, delay)
                    sleep(delay)
            assert last is not None
            raise last
        return wrapper
    return deco


# ── 2) Fallback — 대체 도구로 갈아타기 ───────────────────────────────────────
def is_empty_or_error(result: object) -> bool:
    """도구 결과가 '실패·빈 결과'인지 판정한다. 폴백을 켤지 결정하는 기준.

    docs_search=리스트, graph_query={"rows":[...]} 등 여러 모양을 넓게 받는다.
    error/blocked 플래그가 있거나 행이 0건이면 폴백 대상으로 본다.
    """
    if result is None:
        return True
    if isinstance(result, dict):
        if result.get("error") or result.get("blocked"):
            return True
        rows = result.get("rows")
        if isinstance(rows, list):
            return len(rows) == 0
        # rows 키가 없는 dict(ontology_check 등)는 '결과 있음'으로 본다.
        return False
    if isinstance(result, list):
        return len(result) == 0
    return False


@dataclass
class FallbackResult:
    """폴백 실행 결과. 어느 도구가 최종 답을 줬는지, 폴백이 실제로 일어났는지 담는다."""

    tool: str
    result: object
    fell_back: bool
    tried: list[str] = field(default_factory=list)


def run_with_fallback(
    primary_tool: str,
    fallback_tool: str,
    call: Callable[[str], object],
) -> FallbackResult:
    """primary_tool 을 부르고, 실패·빈 결과면 fallback_tool 로 같은 질의를 다시 부른다.

    call(tool_name) 은 '그 도구를 (같은 질의로) 실행해 결과를 돌려주는' 클로저다. 상위 루프가
    질의·입력을 캡처해 넘긴다. 여기서는 '어떤 도구를 부를지'만 결정한다(같은 질의, 다른 도구).

    primary 가 예외로 죽어도(재시도까지 소진) 폴백으로 넘어간다.
    """
    tried = [primary_tool]
    try:
        primary = call(primary_tool)
        # 폴백 대상이 primary 와 같으면(예: docs_search→docs_search) 갈아탈 이유가 없다.
        # 빈 결과여도 '다른 도구'가 아니므로 그대로 primary 결과를 돌려준다(무의미한 재호출 방지).
        if primary_tool == fallback_tool or not is_empty_or_error(primary):
            return FallbackResult(tool=primary_tool, result=primary, fell_back=False, tried=tried)
    except Exception:
        primary = None  # 예외로 죽어도 폴백을 시도한다.
        if primary_tool == fallback_tool:
            raise  # 같은 도구뿐이면 폴백이 없다 — 예외를 그대로 올린다.

    # 여기까지 왔으면 primary 가 실패·빈결과·예외 → 대체 도구로.
    tried.append(fallback_tool)
    fb = call(fallback_tool)
    return FallbackResult(tool=fallback_tool, result=fb, fell_back=True, tried=tried)


# ── 3) Cache — (도구, 입력) 키 결과 캐시 + TTL ───────────────────────────────
def _freeze(obj: object) -> object:
    """dict/list 를 해시 가능한 형태로 얼려 캐시 키에 쓴다(입력을 통째로 키로)."""
    if isinstance(obj, dict):
        return tuple(sorted((k, _freeze(v)) for k, v in obj.items()))
    if isinstance(obj, (list, tuple)):
        return tuple(_freeze(x) for x in obj)
    return obj


@dataclass
class ToolCache:
    """(도구 이름, 입력) → 결과 캐시. 같은 질의 반복·재시도에서 도구를 안 태운다.

    functools.lru_cache 를 쓰지 않는 이유: dict 입력은 해시 불가라 직접 얼려 키를 만들고,
    TTL(만료)과 hit 통계를 눈으로 보이게 하려는 것. 프로세스 메모리 캐시라 재시작하면 비워진다.
    """

    ttl: float = 300.0  # 초. 이 시간이 지난 항목은 만료로 보고 다시 계산.
    _store: dict = field(default_factory=dict)  # key -> (expire_at, value)
    hits: int = 0
    misses: int = 0

    def key(self, tool: str, tool_input: dict) -> tuple:
        return (tool, _freeze(tool_input))

    def get_or_call(self, tool: str, tool_input: dict, call: Callable[[], object]) -> object:
        """캐시에 있으면 그걸 주고(hit), 없거나 만료면 call() 로 계산해 저장한다(miss)."""
        k = self.key(tool, tool_input)
        now = time.monotonic()
        hit = self._store.get(k)
        if hit is not None and hit[0] > now:
            self.hits += 1
            return hit[1]
        self.misses += 1
        value = call()
        self._store[k] = (now + self.ttl, value)
        return value

    def stats(self) -> dict:
        return {"hits": self.hits, "misses": self.misses, "size": len(self._store)}


if __name__ == "__main__":
    # 빠른 자기점검: 3번에 2번 실패하는 도구를 retry 로 살려낸다 + 캐시 hit 확인.
    calls = {"n": 0}

    @retry(max_attempts=3, base_delay=0.01, sleep=lambda _: None,
           on_retry=lambda a, e, d: print(f"  재시도 {a}회 (사유: {e}) — {d:.3f}s 대기"))
    def flaky() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise ToolFailure(f"일시적 오류(호출 {calls['n']})")
        return "성공"

    print("retry 결과:", flaky(), f"(총 {calls['n']}회 호출)")

    cache = ToolCache(ttl=60)
    def slow() -> dict:
        return {"rows": [{"x": 1}]}
    a = cache.get_or_call("docs_search", {"query": "q", "k": 3}, slow)
    b = cache.get_or_call("docs_search", {"query": "q", "k": 3}, slow)  # 같은 키 → hit
    print("cache:", cache.stats(), "동일 결과:", a == b)
