"""adaptive_loop.py — Router + Grader + Query Rewrite 를 하나의 제어 루프로 묶는다.

03 까지 만든 것은 '도구 3개 + tool-use 루프(모델이 도구를 고름)'였다. 이 토픽은 그 위에
'적응형(맞는 도구 선택) + 교정형(부족하면 고쳐 재시도)' 제어 계층을 얹는다.
03 harness 를 다시 짜지 않는다 — build_registry_full()(도구 3개)을 그대로 dispatch 로 부른다.

제어 흐름(외우면 되는 5단계):
  1) Route    — router.route(q) 로 어떤 도구/모드로 보낼지 결정(Adaptive-RAG).
  2) Retrieve — registry.dispatch(tool, tool_input) 로 그 도구를 실행(01~03 계약).
  3) Grade    — grader.grade(q, result) 로 결과가 충분한지 채점(CRAG).
  4) Correct  — 부족하면 query_rewrite.rewrite() 로 질의를 고쳐 2)로 재시도(Self-RAG/CRAG).
                재시도는 MAX_RETRY 회로 상한. relevant 가 되거나 상한이면 멈춘다.
  5) Answer   — 마지막(최선) 검색 결과의 근거로 인용 붙은 답을 만든다.

교정 대상: 여기서는 'docs_search 로 라우팅된 경우'에만 재작성 재시도를 건다.
  질의어를 바꾸는 교정이 가장 효과적인 경로이기 때문이다. relation/broad/schema 는
  라우팅이 이미 도구를 특정했으므로, 부족하면 재작성 대신 docs_search 로 폴백 재시도한다.

두 경로:
  1) 기본 — ANTHROPIC_API_KEY 로 Router/Grader/Rewrite 판정 + 최종 답 생성까지 Claude.
  2) 폴백(비용 0) — 키 없으면 Router/Grader/Rewrite 는 규칙, 최종 답은 근거 인용 요약(mock).

전제: 03 register_all_tools(build_registry_full) 를 import 경로에 올린다(_attach_phase7_03).
  Router/Grader/Rewrite 는 같은 practice 폴더. 기본 경로만 ANTHROPIC_API_KEY.
사용: python adaptive_loop.py "질문"
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field

import router as router_mod
from grader import grade
from query_rewrite import rewrite

# ── 03 harness(도구 3개 레지스트리)를 재사용 ────────────────────────────────
def _attach_phase7_03() -> None:
    """03 practice 를 sys.path 에 올려 build_registry_full 을 import 가능하게 한다."""
    here = os.path.dirname(os.path.abspath(__file__))
    p03 = os.path.normpath(
        os.path.join(here, "..", "..", "03-cypher-safety-ontology-check", "practice")
    )
    if os.path.isdir(p03) and p03 not in sys.path:
        sys.path.insert(0, p03)


_attach_phase7_03()
from register_all_tools import build_registry_full  # type: ignore  # noqa: E402

MAX_RETRY = 2  # Query Rewrite 재검색 상한. 무한 교정을 막는다(05 에서 예산 가드로 정교화).

LLM_MODEL = os.environ.get("HARNESS_MODEL", "claude-sonnet-4-6")

_ANSWER_SYSTEM = (
    "너는 문서·지식그래프 기반 리서치 어시스턴트다. 아래 근거만으로 질문에 한국어 3~5문장으로 "
    "간결히 답한다. 각 주장 끝에 근거의 [chunk_id] 또는 [source] 를 대괄호로 인용한다. "
    "근거가 부족하면 모른다고 답한다."
)


@dataclass
class Attempt:
    """한 번의 Route→Retrieve→Grade 시도 기록(감사·labs 대조용)."""

    query: str
    route: str
    tool: str
    grade: str
    score: float
    reason: str


@dataclass
class AdaptiveResult:
    answer: str
    route: str
    tool_calls: list[str] = field(default_factory=list)
    attempts: list[Attempt] = field(default_factory=list)
    citations: list[str] = field(default_factory=list)
    retries: int = 0
    backend: str = "rule"

    def summary(self) -> dict:
        return {
            "route": self.route,
            "tool_calls": self.tool_calls,
            "retries": self.retries,
            "grades": [a.grade for a in self.attempts],
            "citations": self.citations,
            "backend": self.backend,
        }


def _citations_from(result: object) -> list[str]:
    """도구 결과에서 인용 식별자(chunk_id 또는 source)를 뽑는다. 여러 도구 형태를 넓게 받는다."""
    rows = result.get("rows") if isinstance(result, dict) else result
    if not isinstance(rows, list):
        return []
    ids: list[str] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        if r.get("chunk_id"):
            ids.append(r["chunk_id"])
        elif r.get("source"):
            ids.append(str(r["source"]))
    return ids


def _answer(question: str, result: object, citations: list[str]) -> tuple[str, str]:
    """최종 답 생성. 키 있으면 Claude, 없으면 근거 인용 요약(mock). (answer, backend)."""
    cite = " ".join(f"[{c}]" for c in citations[:3]) or "[근거 없음]"
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            import anthropic

            client = anthropic.Anthropic()
            evidence = json.dumps(result, ensure_ascii=False)[:4000]
            resp = client.messages.create(
                model=LLM_MODEL, max_tokens=512, system=_ANSWER_SYSTEM,
                messages=[{"role": "user", "content": f"질문: {question}\n근거: {evidence}"}],
            )
            text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
            return text.strip(), "claude"
        except Exception:
            pass
    return f"'{question}' 에 대한 답: 검색된 근거를 종합하면 아래와 같다. {cite}", "mock"


def _run_verification(question, plan, registry, result: AdaptiveResult, verbose: bool) -> AdaptiveResult:
    """schema 라우팅 전용: ontology_check 를 한 번 실행하고 verdict 를 답으로 삼는다.

    검색 경로가 아니므로 Grader(어휘 겹침)·Rewrite 를 태우지 않는다. verdict 자체가 답이다:
      ok=True  → 관계가 스키마상 타당(relevant 로 표기).
      ok=False → 위반이 발견됨(도구는 '정상 동작', 답은 '타당하지 않다').
    """
    verdict = json.loads(registry.dispatch(plan.tool, plan.tool_input))
    result.tool_calls.append(plan.tool)
    ok = bool(verdict.get("ok"))
    grade_label = "relevant" if ok else "relevant"  # 도구가 답을 줬으므로 재시도 대상 아님.
    result.attempts.append(Attempt(
        query=question, route=plan.route, tool=plan.tool,
        grade=grade_label, score=1.0,
        reason="ontology_check verdict(ok=%s)" % ok,
    ))
    if verbose:
        print(f"[try 1] tool={plan.tool} query={question!r}")
        print(f"          verdict ok={ok} violations={len(verdict.get('violations', []))}")

    if ok:
        result.answer = f"'{question}' → 스키마상 타당한 관계다. (ontology_check ok=true)"
    else:
        vs = "; ".join(v.get("reason", "") for v in verdict.get("violations", []))
        result.answer = f"'{question}' → 스키마 위반이다. {vs} (ontology_check ok=false)"
    if verbose:
        print(f"\n[answer] (answer_backend=verdict)\n{result.answer}")
    return result


def run_adaptive(question: str, *, verbose: bool = True) -> AdaptiveResult:
    """Route → Retrieve → Grade → (부족시)Rewrite&Retry → Answer. 03 harness 를 감싼다."""
    registry = build_registry_full()  # 03: docs_search + graph_query + ontology_check
    backend = "claude" if os.environ.get("ANTHROPIC_API_KEY") else "rule/mock"

    # 1) Route — 어떤 도구/모드로 보낼지 결정.
    plan = router_mod.route(question)
    if verbose:
        print(f"[adaptive] backend={backend}")
        print(f"[route] {plan.route}  →  {plan.tool}  ({plan.reason})")

    result = AdaptiveResult(answer="", route=plan.route, backend=backend)

    # schema 라우팅(ontology_check)은 '검색'이 아니라 '검증' 도구다.
    # 어휘 겹침으로 채점하거나 Query Rewrite 로 교정할 대상이 아니다 — 한 번 실행하고
    # 그 verdict(ok/violations)를 그대로 답으로 삼는다. Grader/Rewrite 는 검색 경로에만 건다.
    if plan.tool == "ontology_check":
        return _run_verification(question, plan, registry, result, verbose)

    cur_query = question
    tried_queries: list[str] = [question]
    tool = plan.tool
    tool_input = dict(plan.tool_input)
    best_retrieval: object = None
    best_grade = None

    # 2~4) Retrieve → Grade → (부족시) 교정 재시도.
    for attempt_i in range(1, MAX_RETRY + 2):  # 최초 1회 + MAX_RETRY 재시도.
        retrieval = json.loads(registry.dispatch(tool, tool_input))
        result.tool_calls.append(tool)

        g = grade(cur_query, retrieval)
        result.attempts.append(Attempt(
            query=cur_query, route=plan.route, tool=tool,
            grade=g.grade, score=g.score, reason=g.reason,
        ))
        if verbose:
            print(f"[try {attempt_i}] tool={tool} query={cur_query!r}")
            print(f"          grade={g.grade} score={g.score:.2f} ({g.reason})")

        # 최선의 결과를 보관(재시도가 더 나빠질 수도 있으니 relevant 를 우선 기억).
        if best_grade is None or (g.grade == "relevant" and best_grade != "relevant"):
            best_retrieval, best_grade = retrieval, g

        if g.sufficient:
            break  # 충분 → 교정 불필요.
        if attempt_i >= MAX_RETRY + 1:
            break  # 재시도 상한 도달.

        # 4) Correct — 질의를 재작성해 재검색. docs_search 경로면 재작성, 아니면 docs_search 폴백.
        rw = rewrite(cur_query, grade_reason=g.reason, tried=tried_queries)
        result.retries += 1
        if not rw.changed and tool == "docs_search":
            if verbose:
                print("          재작성이 원 질의와 같아 재시도 중단")
            break
        cur_query = rw.query
        tried_queries.append(cur_query)
        # 라우팅이 특정 도구를 골랐어도, 교정 재시도는 docs_search 로 질의어를 바꿔 다시 찾는다.
        tool = "docs_search"
        tool_input = {"query": cur_query, "k": 3}
        if verbose:
            print(f"          → rewrite: {cur_query!r} ({rw.strategy}) → docs_search 재검색")

    # 5) Answer — 최선 결과의 근거로 인용 답변.
    final_retrieval = best_retrieval if best_grade and best_grade.grade == "relevant" else retrieval
    result.citations = _citations_from(final_retrieval)
    result.answer, ans_backend = _answer(question, final_retrieval, result.citations)
    if verbose:
        print(f"\n[answer] (answer_backend={ans_backend})\n{result.answer}")
    return result


if __name__ == "__main__":
    q = sys.argv[1] if len(sys.argv) > 1 else "Self-RAG 는 언제 검색을 하나?"
    res = run_adaptive(q)
    print("\n--- 요약 ---")
    print(json.dumps(res.summary(), ensure_ascii=False, indent=2))
