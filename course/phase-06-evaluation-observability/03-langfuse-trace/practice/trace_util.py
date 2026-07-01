# trace_util.py — Langfuse 클라이언트를 얻거나, 없으면 콘솔 트레이서로 폴백한다.
#
# 왜 필요한가:
#   Langfuse SDK(v3)는 키가 없으면 조용히 no-op 이 된다 — 전송도, 예외도, 출력도 없다.
#   그러면 학습자는 "내 span 트리가 어떻게 생겼는지" 확인할 방법이 없다.
#   그래서 키가 없을 때는 Langfuse 와 '같은 시그니처'를 가진 경량 콘솔 트레이서로 갈아끼운다.
#   파이프라인 코드(rag_pipeline.py)는 트레이서가 진짜인지 가짜인지 몰라도 되게 만든다.
#
# 노출하는 트레이서 인터페이스(둘 다 동일):
#   tracer.start_as_current_observation(name, as_type="span", input=None) -> context manager
#       └ with 블록 안에서 span.update(output=, model=, usage_details=, cost_details=, metadata=)
#   tracer.update_current_trace(input=, output=)     # 최상위 trace 의 입출력
#   tracer.score_current_trace(name=, value=, comment=None)   # 02 Ragas 점수 붙이기
#   tracer.flush()                                   # 스크립트 끝에 반드시 호출
#
# ── 전제(키) ────────────────────────────────────────────────────────────────
#   LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY / LANGFUSE_HOST 가 셋 다 있으면 진짜 Langfuse.
#   하나라도 없으면 콘솔 트레이서. (self-host 는 LANGFUSE_HOST=http://localhost:3000)

from __future__ import annotations

import os
import time
from contextlib import contextmanager


def langfuse_keys_present() -> bool:
    """세 키가 모두 있으면 실제 Langfuse 로 보낼 수 있다."""
    return all(
        os.environ.get(k)
        for k in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST")
    )


# ---------------------------------------------------------------------------
# 1) 콘솔 트레이서 — Langfuse 없이도 span 트리 / cost / latency 를 눈으로 본다.
# ---------------------------------------------------------------------------
class _ConsoleSpan:
    """with 블록 하나 = span 하나. 들여쓰기 깊이로 트리 구조를 표현한다."""

    def __init__(self, tracer: "ConsoleTracer", name: str, as_type: str, inp):
        self.tracer = tracer
        self.name = name
        self.as_type = as_type  # "span" | "generation" | "tool"
        self.input = inp
        self.output = None
        self.model = None
        self.usage = None          # {"prompt_tokens":.., "completion_tokens":..}
        self.cost = None           # {"total_cost": ..}
        self.metadata = None
        self.t0 = 0.0
        self.ms = 0.0

    def update(self, output=None, model=None, usage_details=None,
               cost_details=None, metadata=None):
        # Langfuse span.update(...) 와 같은 키워드를 그대로 받는다.
        if output is not None:
            self.output = output
        if model is not None:
            self.model = model
        if usage_details is not None:
            self.usage = usage_details
        if cost_details is not None:
            self.cost = cost_details
        if metadata is not None:
            self.metadata = metadata


class ConsoleTracer:
    def __init__(self):
        self._depth = 0
        self._trace_io = {"input": None, "output": None}
        self._scores: list[dict] = []
        self._total_cost = 0.0
        self._spans_seen = 0

    @contextmanager
    def start_as_current_observation(self, name: str, as_type: str = "span", input=None):
        span = _ConsoleSpan(self, name, as_type, input)
        indent = "  " * self._depth
        tag = {"generation": "GEN", "tool": "TOOL"}.get(as_type, "SPAN")
        print(f"{indent}┌─ [{tag}] {name}  (input={_short(input)})")
        self._depth += 1
        span.t0 = time.perf_counter()
        try:
            yield span
        finally:
            span.ms = (time.perf_counter() - span.t0) * 1000.0
            self._depth -= 1
            self._spans_seen += 1
            parts = [f"latency={span.ms:.1f}ms"]
            if span.model:
                parts.append(f"model={span.model}")
            if span.usage:
                parts.append(f"tokens={span.usage}")
            if span.cost:
                c = span.cost.get("total_cost", 0.0)
                self._total_cost += c
                parts.append(f"cost=${c:.6f}")
            print(f"{indent}└─ [{tag}] {name}  " + "  ".join(parts)
                  + f"  (output={_short(span.output)})")

    def update_current_trace(self, input=None, output=None):
        if input is not None:
            self._trace_io["input"] = input
        if output is not None:
            self._trace_io["output"] = output

    def score_current_trace(self, name: str, value, comment: str | None = None):
        self._scores.append({"name": name, "value": value, "comment": comment})
        c = f"  # {comment}" if comment else ""
        print(f"[SCORE] {name} = {value}{c}")

    def flush(self):
        print("─" * 60)
        print(f"[TRACE] input : {_short(self._trace_io['input'])}")
        print(f"[TRACE] output: {_short(self._trace_io['output'])}")
        print(f"[TRACE] spans={self._spans_seen}  total_cost=${self._total_cost:.6f}")
        if self._scores:
            joined = ", ".join(f"{s['name']}={s['value']}" for s in self._scores)
            print(f"[TRACE] scores: {joined}")
        print("(콘솔 트레이서: 실제 Langfuse 로 보내려면 세 키를 설정하고 다시 실행)")


def _short(x, n: int = 60) -> str:
    s = str(x)
    return s if len(s) <= n else s[: n - 1] + "…"


# ---------------------------------------------------------------------------
# 2) Langfuse 어댑터 — 진짜 클라이언트를 콘솔 트레이서와 같은 시그니처로 감싼다.
#    (Langfuse v3 도 start_as_current_observation / flush 를 제공하지만,
#     update_current_trace / score_current_trace 이름을 통일하려고 얇게 감싼다.)
# ---------------------------------------------------------------------------
class LangfuseTracer:
    def __init__(self, client):
        self._c = client

    def start_as_current_observation(self, name: str, as_type: str = "span", input=None):
        # Langfuse v3: as_type 은 "span" | "generation" | "tool" 등을 받는다.
        return self._c.start_as_current_observation(name=name, as_type=as_type, input=input)

    def update_current_trace(self, input=None, output=None):
        # v3 는 trace 입출력을 update_current_trace 로 설정한다.
        self._c.update_current_trace(input=input, output=output)

    def score_current_trace(self, name: str, value, comment: str | None = None):
        # 버전에 따라 이름이 다를 수 있어 create_score 를 기본으로 시도한다.
        try:
            self._c.score_current_trace(name=name, value=value, comment=comment)
        except AttributeError:
            # 폴백: 현재 trace_id 를 얻어 create_score 로 붙인다.
            trace_id = self._c.get_current_trace_id()
            self._c.create_score(trace_id=trace_id, name=name, value=value, comment=comment)

    def flush(self):
        self._c.flush()


def get_tracer():
    """키가 있으면 Langfuse, 없으면 콘솔 트레이서를 돌려준다."""
    if langfuse_keys_present():
        from langfuse import get_client  # v3 API: 클라이언트는 get_client() 로 얻는다.
        client = get_client()
        print("[trace_util] Langfuse 로 전송한다 →", os.environ["LANGFUSE_HOST"])
        return LangfuseTracer(client)
    print("[trace_util] Langfuse 키 없음 → 콘솔 트레이서로 대체(전송 안 함).")
    return ConsoleTracer()
