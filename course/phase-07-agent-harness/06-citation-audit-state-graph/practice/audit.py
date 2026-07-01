"""audit.py — 한 질문 처리의 전 과정을 구조화해 남기는 Audit Trail 수집기.

05 는 stop_reason 으로 '왜 멈췄는지'를 남기기 시작했다. 하지만 그 한 줄로는 재현·디버깅이
안 된다. 왜 이 도구를 골랐나(route), 도구가 뭘 돌려줬나, grade 는 몇 점이었나, 재작성은 뭘로
했나, 폴백은 왜 일어났나, 예산은 얼마나 썼나, 체크포인트는 승인됐나 — 이 전부가 시간순으로
남아야 나중에 '그 답이 왜 그렇게 나왔는지'를 되짚을 수 있다.

AuditTrail 은 append-only 로그다. State Graph 의 각 전이가 한 줄씩 남긴다. 각 줄은
schema.AuditEntry(seq·step·ok·detail)로 직렬화된다. 이게 ChatResponse.audit_trail 로 나가고,
그대로 Langfuse(Phase 6/03) 의 span 으로 흘려보낼 수도 있다(연동 지점은 아래 to_langfuse 훅).

설계 원칙:
  - 값을 요약해 담는다. 도구가 뱉은 5000자 raw 를 통째로 넣지 않는다(개수·상위 id 만).
  - 어떤 단계도 조용히 빠지지 않는다 — route 부터 answer/stop 까지 다 남긴다.
  - 직렬화 가능해야 한다(dict/str/int/float/bool/list 만). 그래야 JSON 응답·Langfuse 로 나간다.

전제: 표준 라이브러리 + schema.AuditEntry. API 키·DB 불필요. Langfuse 연동은 선택(훅만).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from schema import AuditEntry


def _summarize(value: object) -> object:
    """detail 에 담을 값을 '요약'한다. 긴 텍스트·큰 결과를 로그가 감당할 크기로 줄인다."""
    if isinstance(value, str):
        return value if len(value) <= 200 else value[:200] + "…"
    if isinstance(value, dict):
        return {k: _summarize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_summarize(v) for v in value[:5]]  # 앞 5개만.
    return value


@dataclass
class AuditTrail:
    """append-only 감사 로그. State Graph 의 각 단계가 add() 로 한 줄씩 남긴다."""

    _entries: list[AuditEntry] = field(default_factory=list)
    _t0: float = field(default_factory=time.monotonic)

    def add(self, step: str, ok: bool = True, **detail: object) -> AuditEntry:
        """한 단계를 기록한다. seq 는 자동 증가, 경과 ms 를 자동으로 붙인다.

        예: trail.add("route", route="simple", tool="docs_search", reason="...").
        detail 의 값은 _summarize 로 요약해 담는다(로그 폭주 방지).
        """
        detail = {k: _summarize(v) for k, v in detail.items()}
        detail["elapsed_ms"] = round((time.monotonic() - self._t0) * 1000, 1)
        entry = AuditEntry(seq=len(self._entries), step=step, ok=ok, detail=detail)
        self._entries.append(entry)
        return entry

    @property
    def entries(self) -> list[AuditEntry]:
        return list(self._entries)

    def steps(self) -> list[str]:
        """기록된 단계 이름을 순서대로(labs 대조·테스트용)."""
        return [e.step for e in self._entries]

    def to_dicts(self) -> list[dict]:
        """JSON 직렬화용 dict 리스트(ChatResponse.audit_trail 로 나간다)."""
        return [e.model_dump() for e in self._entries]

    def pretty(self) -> str:
        """콘솔용 한 줄씩 요약(labs 에서 눈으로 볼 때)."""
        lines = []
        for e in self._entries:
            flag = "ok" if e.ok else "!!"
            d = {k: v for k, v in e.detail.items() if k != "elapsed_ms"}
            lines.append(f"  [{e.seq}] {flag} {e.step:10} {d}")
        return "\n".join(lines)

    # ── Langfuse 연동 지점(선택) — Phase 6/03 방식 ─────────────────────────────
    def to_langfuse(self, trace: object | None = None) -> None:
        """각 감사 항목을 Langfuse span 으로 흘려보낸다(선택).

        Phase 6/03 에서 만든 Langfuse trace 를 넘기면, 여기서 step 마다 span 을 연다.
        trace 가 None(기본)이면 아무것도 안 한다 — 관측성은 옵트인이다. 키·SDK 없이도
        하니스는 그대로 돈다. 실제 연결은 캡스톤·운영(Phase 8)에서 켠다.
        """
        if trace is None:
            return
        for e in self._entries:
            # 예: trace.span(name=e.step, input=..., output=e.detail, level="DEFAULT"|"ERROR")
            span = getattr(trace, "span", None)
            if callable(span):
                span(name=e.step, metadata=e.detail,
                     level="ERROR" if not e.ok else "DEFAULT")


if __name__ == "__main__":
    # 빠른 자기점검: 단계가 순서대로 쌓이고 직렬화되는지.
    trail = AuditTrail()
    trail.add("route", route="relation", tool="graph_query", reason="엔티티 2개")
    trail.add("retrieve", ok=False, tool="graph_query", error="타임아웃(주입)")
    trail.add("fallback", tool="docs_search", reason="graph_query 실패 → 우회")
    trail.add("grade", grade="relevant", score=0.67, n_rows=3)
    trail.add("checkpoint", needed=False, approved=True)
    trail.add("answer", stop_reason="answered", n_citations=2)

    print("단계 순서:", trail.steps())
    print(trail.pretty())
    print("\nJSON 직렬화(첫 항목):", trail.to_dicts()[0])

    assert trail.steps() == ["route", "retrieve", "fallback", "grade", "checkpoint", "answer"]
    assert trail.entries[1].ok is False  # retrieve 실패가 기록됨.
    print("\n[assert] 6단계 순서·실패 표시·직렬화 통과")
