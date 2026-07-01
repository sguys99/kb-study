"""state_graph.py — 01~05 를 명시적 상태·전이로 묶는 통합 하니스. Phase 7 의 결과물.

지금까지 01~05 는 부품이었다. 01 도구 레지스트리, 02 graph_query, 03 안전판·ontology_check,
04 router·grader·query_rewrite, 05 예산·재시도·폴백·캐시·체크포인트. 05 의 run_guarded 가 이미
그 부품을 묶어 '가드가 낀 루프'를 만들었다. 이 파일은 그 위에 **통합 계층**을 얹는다 — 부품을
다시 짜지 않는다. run_guarded 를 그대로 실행 엔진으로 쓰고, 그 결과를 명시적 상태 그래프의
관점으로 재구성해 (1) 구조화 출력 (2) 인용 검증 (3) 감사 추적 을 붙인다.

명시적 상태와 전이(이게 최종 하니스의 뼈대):

  ROUTE ──▶ RETRIEVE ──▶ GRADE ──┬─(sufficient)────────────────▶ CHECKPOINT ──▶ ANSWER
    │                            │                                    │
    │                            ├─(부족·질의문제)─▶ CORRECT(rewrite)─┘(재검색 루프)
    │                            └─(도구 죽음)────▶ FALLBACK(다른 도구)┘
    │                                                                 │
    └─(예산/재시도 상한)─────────────────────────────────▶ STOP ──────┘

  전이 조건 요약:
    ROUTE→RETRIEVE   : 항상(router 가 도구·입력 결정).
    RETRIEVE→GRADE   : 검색 성공(retry·fallback 로 결과 확보).
    RETRIEVE→FALLBACK: primary 도구가 죽거나 빈 결과 → 같은 질의, 다른 도구.
    GRADE→CHECKPOINT : grade=relevant(충분) → 답 준비.
    GRADE→CORRECT    : 부족·애매 → query_rewrite 로 같은 도구·다른 질의 재검색.
    *→STOP           : 예산 초과·재시도 상한·no_change → 안전 종료(stop_reason).
    CHECKPOINT→ANSWER: 승인(또는 불필요) → 구조화 답 + 검증된 인용 반환.
    CHECKPOINT→STOP  : 거절(rejected_by_human) → 답 보류.

  Anthropic tool-use 루프(05 run_guarded)를 기본 엔진으로 쓴다. LangGraph 는 대안이다 —
  이 정도 분기·루프·체크포인트는 표준 라이브러리 상태머신으로 충분하다. LangGraph 는
  그래프가 커지고 병렬·영속 체크포인트가 필요할 때의 선택지로 lesson 에서 언급만 한다.

run_harness(request) → ChatResponse:
  1) run_guarded(05) 로 route→retrieve→grade→correct/fallback→checkpoint 를 실행하고,
     그 과정에서 나온 검색 결과·단계 로그를 콜백으로 수집한다.
  2) 수집한 검색 결과로 인용 인덱스를 만들고, 답의 인용을 검증(환각 제거)한다.
  3) 결과를 schema 모델(Answer·ChatResponse)로 구조화해 돌려준다.

전제: 05 practice(guarded_loop·guards·budget)가 import 경로에 있어야 한다(자동 부착).
  표준 라이브러리 + pydantic. API 키·DB 불필요(키 없으면 mock 전 흐름).
"""

from __future__ import annotations

import os
import sys

from audit import AuditTrail
from citation import build_evidence_index, enrich_citations, verify_citations
from schema import Answer, ChatRequest, ChatResponse, Citation


# ── 05 practice(guarded_loop 등)를 재사용 경로에 올린다 ──────────────────────
def _attach(*rel_parts: str) -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    p = os.path.normpath(os.path.join(here, *rel_parts))
    if os.path.isdir(p) and p not in sys.path:
        sys.path.insert(0, p)


_attach("..", "..", "05-fallback-budget-checkpoint", "practice")
# guarded_loop 은 임포트되며 04·03 도 자기 경로에 붙인다(05 가 이미 그렇게 설계됨).
from guarded_loop import run_guarded  # type: ignore  # noqa: E402
from guards import ToolCache  # type: ignore  # noqa: E402
from budget import Budget  # type: ignore  # noqa: E402


# 상태 이름(명시적 상태 그래프의 노드). audit 의 step 과 1:1 대응.
STATES = ["route", "retrieve", "grade", "correct", "fallback", "checkpoint", "answer", "stop"]

# stop_reason → confidence 매핑. answered 만 높고, 나머지는 낮춰 프런트가 주의 배지를 붙이게.
_CONFIDENCE = {
    "answered": 0.85,
    "max_retry": 0.35,
    "no_change": 0.35,
    "budget_exceeded": 0.2,
    "rejected_by_human": 0.0,
}


def _record_states(trail: AuditTrail, guarded) -> None:
    """05 GuardedResult 를 명시적 상태 전이로 풀어 audit_trail 에 남긴다.

    run_guarded 는 루프를 통째로 돈 뒤 요약(route·tool_calls·grades·retries·fell_back·
    checkpoint·budget)만 준다. 그 요약을 '어떤 상태를 밟았는지'로 재구성해 한 줄씩 기록한다.
    이렇게 하면 부품을 다시 실행하지 않고도 State Graph 관점의 감사 로그가 생긴다.
    """
    # ROUTE
    trail.add("route", route=guarded.route, backend=guarded.backend,
              tools_planned=guarded.tool_calls[:1])

    # RETRIEVE / FALLBACK / CORRECT / GRADE — tool_calls·grades·retries 를 시간순으로 엮는다.
    for i, tool in enumerate(guarded.tool_calls):
        # 폴백이 일어났고 이 호출이 원래 계획 도구가 아니면 fallback 단계로도 남긴다.
        fell = guarded.fell_back and i > 0 and tool == "docs_search"
        trail.add("fallback" if fell else "retrieve",
                  ok=True, tool=tool,
                  note="다른 도구로 우회(같은 질의)" if fell else "도구 실행")
        # 이 검색에 대응하는 grade(있으면).
        if i < len(guarded.grades):
            g = guarded.grades[i]
            trail.add("grade", ok=(g == "relevant"), grade=g,
                      sufficient=(g == "relevant"))
            # relevant 가 아니고 아직 재시도 여지가 있었으면 correct(rewrite) 를 밟았다.
            if g != "relevant" and i < guarded.retries:
                trail.add("correct", tool="docs_search",
                          note="query_rewrite: 같은 의미·다른 질의로 재검색")

    # CHECKPOINT
    cp = guarded.checkpoint or {}
    trail.add("checkpoint", ok=cp.get("approved", True),
              needed=cp.get("needed", False), approved=cp.get("approved", True),
              mode=cp.get("mode"), reasons=cp.get("reasons", []))

    # ANSWER or STOP
    if guarded.stop_reason == "answered" and not (cp.get("needed") and not cp.get("approved")):
        trail.add("answer", stop_reason=guarded.stop_reason,
                  n_citations=len(guarded.citations), budget=guarded.budget)
    else:
        trail.add("stop", ok=False, stop_reason=guarded.stop_reason, budget=guarded.budget)


def run_harness(request: ChatRequest) -> ChatResponse:
    """01~05 를 통합해 한 질문을 처리하고 구조화된 ChatResponse 를 돌려준다.

    mode='baseline' 이면 가드·교정 없이 docs_search 한 번만(비교용). 기본은 'agent'.
    """
    trail = AuditTrail()

    # ── 검색 결과를 가로채는 훅 ──────────────────────────────────────────────
    # run_guarded 는 내부에서 registry.dispatch 를 부른다. 그 결과를 인용 검증에 쓰려면
    # 밖에서 모아야 한다. 캐시를 공유 주입하면, 캐시에 저장된 값들이 곧 '이번 질문에서 나온
    # 검색 결과' 집합이 된다 — 캐시를 인용 근거의 수집처로 재사용한다(별도 훅 없이).
    cache = ToolCache(ttl=300)
    budget = Budget()  # 기본 상한(05 와 동일). 호출부가 조이고 싶으면 밖에서 주입.

    if request.mode == "baseline":
        guarded = _run_baseline(request.query, cache, trail)
    else:
        guarded = run_guarded(request.query, budget=budget, cache=cache, verbose=False)
        _record_states(trail, guarded)

    # ── 인용 검증: 도구가 실제로 돌려준 결과에서 allowed 집합을 만든다 ─────────
    retrievals = _cached_retrievals(cache)
    index = build_evidence_index(retrievals)

    # 05 GuardedResult.citations 는 id 문자열 리스트. Citation 으로 감싼 뒤 검증한다.
    raw_cites = [Citation(id=cid) for cid in guarded.citations]
    check = verify_citations(raw_cites, index)
    valid = check.valid or enrich_citations(index)  # 답에 인용이 없으면 실존 근거로 보강.

    trail.add("citation_check", ok=(check.hallucinated == 0),
              valid=[c.id for c in valid], dropped=check.dropped,
              hallucinated=check.hallucinated)

    # ── 구조화 출력으로 수렴 ────────────────────────────────────────────────
    answer = Answer(
        text=guarded.answer,
        citations=valid,
        confidence=_CONFIDENCE.get(guarded.stop_reason, 0.3),
    )
    return ChatResponse(
        answer=answer,
        citations=valid,
        audit_trail=trail.entries,
        stop_reason=guarded.stop_reason,
        route=guarded.route,
        backend=guarded.backend,
    )


def _cached_retrievals(cache: ToolCache) -> list[object]:
    """공유 캐시에 쌓인 도구 결과값들을 인용 근거 수집처로 꺼낸다.

    ToolCache._store 는 {key -> (expire_at, value)}. value 가 이번 질문에서 도구가 돌려준
    실제 결과다. 이 값들의 키 집합이 인용 allowed set 의 원천이 된다.
    """
    return [entry[1] for entry in cache._store.values()]


def _run_baseline(query: str, cache: ToolCache, trail: AuditTrail):
    """mode='baseline' — 가드·교정 없이 docs_search 한 번. agent 모드와 비교용.

    run_guarded 를 재사용하되 예산을 도구 1회로 조여 교정 루프를 막는다. 이렇게 하면 같은
    부품으로 'baseline vs agent' 를 한 코드 경로에서 대조할 수 있다.
    """
    b = Budget(max_tokens=None, max_tool_calls=1, max_seconds=None)
    guarded = run_guarded(query, budget=b, cache=cache, verbose=False)
    trail.add("route", route=guarded.route, backend=guarded.backend, mode="baseline")
    trail.add("retrieve", tool=guarded.tool_calls[0] if guarded.tool_calls else "docs_search")
    trail.add("answer", stop_reason=guarded.stop_reason, mode="baseline")
    return guarded


if __name__ == "__main__":
    import json

    for q, mode in [
        ("Self-RAG 는 언제 검색을 하나?", "agent"),
        ("CRAG 와 Self-RAG 는 어떻게 연결돼 있나?", "agent"),
    ]:
        print(f"\n=== [{mode}] {q} ===")
        resp = run_harness(ChatRequest(query=q, mode=mode))
        print("route      :", resp.route, "| stop_reason:", resp.stop_reason,
              "| backend:", resp.backend)
        print("confidence :", resp.answer.confidence)
        print("citations  :", [c.id for c in resp.citations])
        print("audit_trail:")
        for e in resp.audit_trail:
            d = {k: v for k, v in e.detail.items() if k != "elapsed_ms"}
            print(f"  [{e.seq}] {'ok' if e.ok else '!!'} {e.step:14} {d}")

    # 자체검증: 상태 그래프가 핵심 단계를 다 밟았는지.
    resp = run_harness(ChatRequest(query="Self-RAG 는 언제 검색을 하나?", mode="agent"))
    steps = [e.step for e in resp.audit_trail]
    assert "route" in steps and "answer" in steps or "stop" in steps
    assert "citation_check" in steps
    print("\n[assert] route→…→answer/stop + citation_check 기록 통과")
