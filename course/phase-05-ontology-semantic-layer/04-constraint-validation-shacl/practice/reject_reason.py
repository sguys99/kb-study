"""
reject_reason.py — 위반을 담는 구조화 리포트(Reject Reason)

전제:
  - Pydantic v2 (requirements.txt). API 키·Neo4j 불필요. 로컬에서 돈다.

왜 별도 모듈인가:
  - Pydantic 트랙(레코드 스키마 검증)과 SHACL-inspired 트랙(그래프 제약 검증)이
    "위반을 어떻게 기록하는가"를 하나의 포맷으로 공유해야, reject queue·집계·05
    답변 시점 게이트가 같은 리포트를 재사용할 수 있다.
  - Phase 2 품질 게이트의 reject queue 로 그대로 흘려보내는 게 목표다.

한 건의 위반은 다음을 반드시 담는다:
  - rule_id     : 어떤 규칙이 걸었나(shapes.yaml 의 Shape id 또는 Pydantic 필드)
  - severity    : violation(적재 거부) / warning(적재는 하되 남김)
  - target      : 무엇이 걸렸나(노드 id 또는 트리플 문자열)
  - message     : 사람이 읽을 위반 설명
  - suggested_fix : 어떻게 고치나(있으면)
"""

from __future__ import annotations

from collections import Counter
from typing import Literal

from pydantic import BaseModel, Field

Severity = Literal["violation", "warning"]


class RejectReason(BaseModel):
    """위반 한 건. 두 트랙이 공유하는 단일 포맷."""

    rule_id: str
    severity: Severity = "violation"
    target_kind: Literal["node", "triple"]
    target: str                      # 노드 id 또는 "subject-REL->object"
    message: str
    suggested_fix: str | None = None

    def line(self) -> str:
        """한 줄 표시용."""
        tag = "REJECT " if self.severity == "violation" else "WARN   "
        fix = f"  fix: {self.suggested_fix}" if self.suggested_fix else ""
        return f"[{tag}] {self.rule_id:26} {self.target:24} {self.message}{fix}"


class ValidationReport(BaseModel):
    """검증 한 회차의 결과. 위반 목록 + 집계."""

    reasons: list[RejectReason] = Field(default_factory=list)

    def add(self, r: RejectReason) -> None:
        self.reasons.append(r)

    def extend(self, rs: list[RejectReason]) -> None:
        self.reasons.extend(rs)

    @property
    def violations(self) -> list[RejectReason]:
        return [r for r in self.reasons if r.severity == "violation"]

    @property
    def warnings(self) -> list[RejectReason]:
        return [r for r in self.reasons if r.severity == "warning"]

    @property
    def passed(self) -> bool:
        """violation 이 하나도 없으면 통과. warning 은 통과를 막지 않는다."""
        return len(self.violations) == 0

    def by_rule(self) -> dict[str, int]:
        """rule_id 별 위반+경고 집계."""
        return dict(Counter(r.rule_id for r in self.reasons))

    def summary(self) -> str:
        v = len(self.violations)
        w = len(self.warnings)
        head = f"위반 {v}건, 경고 {w}건"
        if not self.reasons:
            return head + " — 모두 PASS"
        lines = [head, "  rule 별 집계:"]
        for rule_id, n in sorted(self.by_rule().items(), key=lambda kv: (-kv[1], kv[0])):
            lines.append(f"    {rule_id:26} {n}건")
        return "\n".join(lines)


if __name__ == "__main__":
    # 리포트 포맷 자체를 데모 + 자체검증.
    report = ValidationReport()
    report.add(RejectReason(
        rule_id="UsesShape", severity="violation", target_kind="triple",
        target="popqa-USES->self-rag",
        message="USES 는 (:Method)-[:USES]->(:Dataset) 여야 한다. 주어가 Dataset(popqa)",
        suggested_fix="방향이 뒤집혔으면 subject/object 를 바꿔라",
    ))
    report.add(RejectReason(
        rule_id="MethodMustBeEvaluatedShape", severity="warning", target_kind="node",
        target="graphrag",
        message="Method 노드는 최소 1개 Dataset 에서 EVALUATED_ON 관계를 가져야 한다",
        suggested_fix="평가 데이터셋 관계 추출 누락 여부를 확인하라",
    ))

    print("== reject reason 라인 ==")
    for r in report.reasons:
        print(r.line())

    print("\n== 요약 ==")
    print(report.summary())

    # 자체검증 — 리포트 로직을 코드로 못박는다.
    assert report.passed is False                     # violation 이 있으므로 실패
    assert len(report.violations) == 1
    assert len(report.warnings) == 1
    assert report.by_rule()["UsesShape"] == 1

    ok = ValidationReport()
    assert ok.passed is True                          # 빈 리포트는 통과
    ok.add(RejectReason(rule_id="X", severity="warning", target_kind="node",
                        target="n", message="m"))
    assert ok.passed is True                           # warning 만 있으면 여전히 통과

    print("\n[assert] 모든 자체검증 통과")
