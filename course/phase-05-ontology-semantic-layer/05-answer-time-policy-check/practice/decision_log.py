"""
decision_log.py — 답변 시점 정책 결정 로그(Policy Decision Log)

전제:
  - Pydantic v2 (requirements.txt). API 키·Neo4j 불필요. 로컬에서 돈다.

왜 별도 모듈인가:
  - 04 의 reject_reason.RejectReason 은 "적재 시점" 위반 기록이다(node/triple 대상, allow/deny 없음).
  - 05 는 "답변 시점" 결정을 감사(audit) 가능하게 남겨야 한다. 한 항목이 어느 게이트에서
    allow / deny / mask 중 무엇을 받았고, 그 사유가 무엇인지를 한 줄로 기록한다.
  - 이 로그 포맷을 Phase 6(관측성)·Phase 7(Agent 정책 도구)이 그대로 재사용한다.

한 건의 결정은 다음을 담는다:
  - item_id  : 어떤 컨텍스트 항목인가(retrieved_context 의 item_id)
  - gate     : 어느 게이트가 결정했나(semantic / access / policy)
  - decision : allow / deny / mask
  - reason   : 사유 코드 + 설명(deny/mask 일 때)
"""

from __future__ import annotations

from collections import Counter
from typing import Literal

from pydantic import BaseModel, Field

Gate = Literal["semantic", "access", "policy"]
Decision = Literal["allow", "deny", "mask"]


class PolicyDecision(BaseModel):
    """정책 결정 한 건. 감사 로그의 최소 단위."""

    item_id: str
    gate: Gate
    decision: Decision
    reason: str | None = None
    # mask 결정일 때, 어떤 필드를 가렸는지 남긴다(감사용).
    masked_fields: list[str] = Field(default_factory=list)

    def line(self) -> str:
        tag = {"allow": "ALLOW", "deny": "DENY ", "mask": "MASK "}[self.decision]
        extra = ""
        if self.masked_fields:
            extra = f"  fields={self.masked_fields}"
        why = f"  {self.reason}" if self.reason else ""
        return f"[{tag}] {self.item_id:8} gate={self.gate:8}{why}{extra}"


class DecisionLog(BaseModel):
    """답변 한 회차의 결정 모음 + 집계."""

    decisions: list[PolicyDecision] = Field(default_factory=list)

    def add(self, d: PolicyDecision) -> None:
        self.decisions.append(d)

    def for_item(self, item_id: str) -> list[PolicyDecision]:
        return [d for d in self.decisions if d.item_id == item_id]

    def denied_item_ids(self) -> set[str]:
        return {d.item_id for d in self.decisions if d.decision == "deny"}

    def by_gate_decision(self) -> dict[tuple[str, str], int]:
        """(gate, decision) 별 집계."""
        return dict(Counter((d.gate, d.decision) for d in self.decisions))

    def summary(self) -> str:
        counts = self.by_gate_decision()
        lines = ["== decision_log 집계 (gate × decision) =="]
        for (gate, decision), n in sorted(counts.items()):
            lines.append(f"  {gate:8} {decision:5} {n}건")
        return "\n".join(lines)


if __name__ == "__main__":
    log = DecisionLog()
    log.add(PolicyDecision(item_id="ctx-01", gate="policy", decision="allow"))
    log.add(PolicyDecision(item_id="ctx-02", gate="access", decision="deny",
                           reason="ACL_ROLE_DENIED: analyst 는 admin 문서 접근 불가"))
    log.add(PolicyDecision(item_id="ctx-07", gate="policy", decision="mask",
                           reason="SENSITIVE_FIELD", masked_fields=["raw_score"]))

    for d in log.decisions:
        print(d.line())
    print()
    print(log.summary())

    # 자체검증
    assert log.denied_item_ids() == {"ctx-02"}
    assert log.by_gate_decision()[("access", "deny")] == 1
    assert log.for_item("ctx-07")[0].masked_fields == ["raw_score"]
    print("\n[assert] 모든 자체검증 통과")
