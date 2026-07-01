"""guarded_loop.py — 04 adaptive_loop 을 05 의 가드들로 감싼 '운영 가능한' 상위 루프.

04 는 Route→Retrieve→Grade→Rewrite&Retry→Answer 로 '적응·교정'을 했다. 하지만 도구가
죽으면 그대로 멈추고, 예산 개념이 없고, 저신뢰 답도 그냥 내보냈다. 이 토픽은 그 위에 가드
계층을 얹어 루프를 '운영 가능하게' 만든다. 04 를 다시 짜지 않는다 — router/grader/query_rewrite
와 03 registry.dispatch 를 그대로 재사용하고, 그 사이사이에 가드를 끼운다.

가드가 낀 제어 흐름:
  1) Route             — router.route(q). (04 그대로)
  2) Cache 확인        — (도구,입력) 캐시에 있으면 도구를 안 태운다(ToolCache).
  3) Retrieve          — dispatch 를 retry(지수 백오프)로 감싸 실행. 계속 실패하면
                         run_with_fallback 로 '다른 도구'(graph_query→docs_search)로 우회.
  4) Grade             — grader.grade. 예산(토큰·호출)을 매 단계 누적·check.
  5) (부족시) Rewrite  — 04 처럼 질의 재작성 재시도. 단 stop 조건(예산/상한/반복)을 먼저 본다.
  6) Stop 판정         — sufficient / budget_exceeded / max_retry / repeated_state 중 하나로 종료.
  7) Human Checkpoint  — 저신뢰·위험이면 사람 승인. 거절이면 stop_reason=rejected_by_human.

stop_reason(반드시 하나 반환):
  answered / budget_exceeded / max_retry / no_change / rejected_by_human

Fallback vs Rewrite(04 와의 차이, 다시 강조):
  - Rewrite : 같은 도구 · 다른 질의(질의어가 나빠 못 찾음을 교정).
  - Fallback: 다른 도구 · 같은 질의(그 도구가 아예 안 됨을 우회).

두 경로:
  1) 기본  — ANTHROPIC_API_KEY 로 router/grader/rewrite 판정 + 최종 답 Claude. 예산은 usage 로.
  2) 폴백  — 키 없으면 규칙 판정 + mock 답. 예산은 estimate_tokens 로 근사. 키 없이 전 흐름 재현.

전제: 04 practice(router·grader·query_rewrite) + 03 registry 를 import 경로에 올린다.
  표준 라이브러리 + (선택) anthropic. 사용: python guarded_loop.py "질문"
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field

from budget import Budget, BudgetExceeded, estimate_tokens
from guards import ToolCache, ToolFailure, is_empty_or_error, retry, run_with_fallback
import checkpoint as checkpoint_mod


# ── 04 practice(router·grader·query_rewrite) + 03 registry 를 재사용 ─────────
def _attach(*rel_parts: str) -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    p = os.path.normpath(os.path.join(here, *rel_parts))
    if os.path.isdir(p) and p not in sys.path:
        sys.path.insert(0, p)


# 04(router/grader/query_rewrite)와 03(register_all_tools)을 모두 import 경로에 올린다.
# 04 는 자기 모듈이 직접 실행될 때만 03 을 붙이므로, 여기서 03 도 직접 붙여 준다.
_attach("..", "..", "04-adaptive-corrective-rag", "practice")
_attach("..", "..", "03-cypher-safety-ontology-check", "practice")
import router as router_mod  # type: ignore  # noqa: E402
from grader import grade  # type: ignore  # noqa: E402
from query_rewrite import rewrite  # type: ignore  # noqa: E402
from register_all_tools import build_registry_full  # type: ignore  # noqa: E402

MAX_RETRY = 2  # 04 와 동일. 이제는 예산 가드의 '한 축'일 뿐(budget 이 더 강한 상한).

LLM_MODEL = os.environ.get("HARNESS_MODEL", "claude-sonnet-4-6")

# 도구별 폴백 대상. '검색이 안 되면 docs_search 로' 라는 보편 규칙.
_FALLBACK_TOOL = {
    "graph_query": "docs_search",
    "ontology_check": "docs_search",
}


@dataclass
class GuardedResult:
    """가드 루프의 최종 산출물. 04 AdaptiveResult 에 stop_reason·가드 통계를 더한 것."""

    answer: str
    route: str
    stop_reason: str = "answered"     # answered/budget_exceeded/max_retry/no_change/rejected_by_human
    tool_calls: list[str] = field(default_factory=list)
    grades: list[str] = field(default_factory=list)
    citations: list[str] = field(default_factory=list)
    retries: int = 0
    fell_back: bool = False
    checkpoint: dict | None = None
    budget: dict | None = None
    cache: dict | None = None
    backend: str = "rule/mock"

    def summary(self) -> dict:
        return {
            "route": self.route,
            "stop_reason": self.stop_reason,
            "tool_calls": self.tool_calls,
            "grades": self.grades,
            "retries": self.retries,
            "fell_back": self.fell_back,
            "citations": self.citations,
            "checkpoint": self.checkpoint,
            "budget": self.budget,
            "cache": self.cache,
            "backend": self.backend,
        }


def _citations_from(result: object) -> list[str]:
    """도구 결과에서 인용 식별자(chunk_id/source)를 뽑는다(04 와 동일 계약)."""
    rows = result.get("rows") if isinstance(result, dict) else result
    if not isinstance(rows, list):
        return []
    ids: list[str] = []
    for r in rows:
        if isinstance(r, dict):
            if r.get("chunk_id"):
                ids.append(r["chunk_id"])
            elif r.get("source"):
                ids.append(str(r["source"]))
    return ids


def _dispatch_json(registry, tool: str, tool_input: dict, budget: Budget, fail_tools: set[str]):
    """registry.dispatch 를 retry 로 감싸 실행하고 JSON 을 파싱해 돌려준다.

    fail_tools 에 든 도구는 강제로 ToolFailure 를 던지게 한다(labs 에서 '도구 실패' 재현).
    호출마다 예산(도구 호출 수·추정 토큰)을 누적한다.
    """

    @retry(max_attempts=3, base_delay=0.05, sleep=lambda _: None,
           on_retry=lambda a, e, d: print(f"          retry {a}회 (사유: {e})"))
    def _call() -> object:
        budget.add_tool_call()
        if tool in fail_tools:
            raise ToolFailure(f"{tool} 강제 실패(주입)")
        raw = registry.dispatch(tool, tool_input)
        budget.add_tokens(estimate_tokens(raw))  # mock 경로용 근사 토큰.
        return json.loads(raw)

    return _call()


def _answer(question: str, result: object, citations: list[str], budget: Budget) -> tuple[str, str]:
    """최종 답. 키 있으면 Claude(usage 로 예산 가산), 없으면 근거 인용 요약(mock)."""
    cite = " ".join(f"[{c}]" for c in citations[:3]) or "[근거 없음]"
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            import anthropic

            client = anthropic.Anthropic()
            evidence = json.dumps(result, ensure_ascii=False)[:4000]
            resp = client.messages.create(
                model=LLM_MODEL, max_tokens=512,
                system=("너는 리서치 어시스턴트다. 근거만으로 한국어 3~5문장으로 답하고 "
                        "각 주장 끝에 [chunk_id]/[source] 를 인용한다."),
                messages=[{"role": "user", "content": f"질문: {question}\n근거: {evidence}"}],
            )
            # 실제 경로의 예산은 추정이 아니라 usage 로 정확히 센다.
            budget.add_tokens(resp.usage.input_tokens + resp.usage.output_tokens)
            text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
            return text.strip(), "claude"
        except Exception:
            pass
    return f"'{question}' 에 대한 답: 검색된 근거를 종합하면 아래와 같다. {cite}", "mock"


def run_guarded(
    question: str,
    *,
    budget: Budget | None = None,
    cache: ToolCache | None = None,
    fail_tools: set[str] | None = None,
    verbose: bool = True,
) -> GuardedResult:
    """04 의 적응·교정 루프에 예산·재시도·폴백·캐시·체크포인트 가드를 얹은 상위 루프.

    budget/cache 를 밖에서 주입하면 여러 질의에 걸쳐 예산·캐시를 공유한다(labs 의 반복 질의).
    fail_tools 로 특정 도구를 강제 실패시켜 retry→fallback 회복을 재현한다.
    """
    registry = build_registry_full()
    budget = budget or Budget()
    cache = cache or ToolCache()
    fail_tools = fail_tools or set()
    backend = "claude" if os.environ.get("ANTHROPIC_API_KEY") else "rule/mock"

    plan = router_mod.route(question)
    result = GuardedResult(answer="", route=plan.route, backend=backend)
    if verbose:
        print(f"[guarded] backend={backend}")
        print(f"[route] {plan.route} → {plan.tool} ({plan.reason})")

    cur_query = question
    tried_queries: list[str] = [question]
    tool = plan.tool
    tool_input = dict(plan.tool_input)
    fb_tool = _FALLBACK_TOOL.get(tool, "docs_search")
    best_retrieval: object = None
    final_retrieval: object = None

    try:
        for attempt_i in range(1, MAX_RETRY + 2):  # 최초 1회 + MAX_RETRY 재시도.
            # ── 2·3) Cache → Retrieve(retry) → 실패 시 Fallback ──────────────
            def _do(t: str, ti: dict):
                # 캐시 히트면 도구·예산 소모 없이 결과 재사용.
                return cache.get_or_call(
                    t, ti, lambda: _dispatch_json(registry, t, ti, budget, fail_tools)
                )

            fb = run_with_fallback(tool, fb_tool, lambda t: _do(t, tool_input if t == tool
                                                                else {"query": cur_query, "k": 3}))
            retrieval = fb.result
            final_retrieval = retrieval
            result.tool_calls.append(fb.tool)
            if fb.fell_back:
                result.fell_back = True
                if verbose:
                    print(f"          fallback: {tool} 실패 → {fb.tool} 로 우회(같은 질의)")

            budget.check()  # 검색 후 예산 점검.

            # ── 4) Grade ─────────────────────────────────────────────────────
            g = grade(cur_query, retrieval)
            result.grades.append(g.grade)
            if verbose:
                print(f"[try {attempt_i}] tool={fb.tool} grade={g.grade} "
                      f"score={g.score:.2f} budget={budget.snapshot()}")

            if best_retrieval is None or (g.grade == "relevant"):
                best_retrieval, best_score = retrieval, g.score

            if g.sufficient:
                result.stop_reason = "answered"
                break

            # ── 6) Stop 판정: 재시도 상한/예산을 '재시도 전에' 확인 ──────────
            if attempt_i >= MAX_RETRY + 1:
                result.stop_reason = "max_retry"
                break
            if budget.would_exceed_tool_calls(extra=1):
                result.stop_reason = "budget_exceeded"
                break

            # ── 5) Rewrite(같은 의미, 다른 질의) 재시도 ──────────────────────
            rw = rewrite(cur_query, grade_reason=g.reason, tried=tried_queries)
            result.retries += 1
            if not rw.changed and tool == "docs_search":
                result.stop_reason = "no_change"
                if verbose:
                    print("          재작성이 원 질의와 같아 중단(no_change)")
                break
            cur_query = rw.query
            tried_queries.append(cur_query)
            tool = "docs_search"  # 교정 재시도는 질의를 바꿔 docs_search 로(04 와 동일).
            tool_input = {"query": cur_query, "k": 3}
            fb_tool = "docs_search"
            if verbose:
                print(f"          → rewrite: {cur_query!r} → docs_search 재검색")

    except BudgetExceeded as e:
        # 어느 단계에서든 예산이 터지면 여기로. 안전하게 정리한다.
        result.stop_reason = "budget_exceeded"
        if verbose:
            print(f"[stop] BudgetExceeded(which={e.which}, spent={e.spent}, limit={e.limit})")

    # ── 답 생성(예산 초과로 검색을 못 했으면 근거 없이도 정직하게) ──────────
    chosen = best_retrieval if best_retrieval is not None else final_retrieval
    result.citations = _citations_from(chosen) if chosen is not None else []
    if result.stop_reason == "budget_exceeded" and chosen is None:
        result.answer = f"'{question}' → 예산 초과로 충분히 검색하지 못했다. 재시도가 필요하다."
        ans_backend = "none"
    else:
        result.answer, ans_backend = _answer(question, chosen, result.citations, budget)

    # ── 7) Human Checkpoint: 저신뢰·위험이면 사람 승인 ──────────────────────
    last_score = 1.0 if result.stop_reason == "answered" else 0.3  # 교정 소진/예산초과면 저신뢰로.
    decision = checkpoint_mod.request_approval(question, result.answer, score=last_score)
    result.checkpoint = {"needed": decision.needed, "approved": decision.approved,
                         "mode": decision.mode, "reasons": decision.reasons}
    if decision.needed and not decision.approved:
        result.stop_reason = "rejected_by_human"
        result.answer = f"'{question}' → 사람 승인 거절로 답을 보류한다. (사유: {decision.reasons})"
        if verbose:
            print(f"[checkpoint] 거절됨 → stop_reason=rejected_by_human")
    elif decision.needed and verbose:
        print(f"[checkpoint] 승인({decision.mode}) 사유={decision.reasons}")

    result.budget = budget.snapshot()
    result.cache = cache.stats()
    if verbose:
        print(f"\n[answer] (backend={ans_backend}, stop_reason={result.stop_reason})\n{result.answer}")
    return result


if __name__ == "__main__":
    q = sys.argv[1] if len(sys.argv) > 1 else "Self-RAG 는 언제 검색을 하나?"
    res = run_guarded(q)
    print("\n--- 요약 ---")
    print(json.dumps(res.summary(), ensure_ascii=False, indent=2))
