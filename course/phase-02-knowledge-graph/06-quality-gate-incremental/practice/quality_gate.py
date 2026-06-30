"""quality_gate.py — 적재 전 마지막 관문. 정규화된 엣지·이벤트를 점수화해 통과/거절한다.

05 가 관계 타입·방향·n-ary 를 정제했다. 깨끗해 보이지만, 그래도 그대로 Neo4j 에
올리면 안 된다. 근거 0건짜리 엣지, canonical 집합에 없는 엔티티를 가리키는 엣지,
같은 (head,type) 에 모순되는 tail 이 섞여 들어올 수 있다. 적재 전에 한 번 더 막는다.

이 게이트는 LLM 도 SHACL 엔진도 부르지 않는다. 순수 파이썬 규칙 + Pydantic 검증으로
결정적으로 돈다. SHACL(https://www.w3.org/TR/shacl/) 의 "그래프가 만족해야 할 제약을
선언적으로 적는다"는 발상을 그대로 빌리되, 라이선스·의존 부담 없이 규칙 함수로 옮겼다.
pyshacl 은 RDF 그래프에 같은 일을 해 주는 표준 도구다(개념·선택 의존, 본문 참조).

점수 신호 4종(거절 사유 reason code):
  - NO_PROVENANCE      : provenance(근거)가 0건. quote/span 이 없으면 추적 불가.
  - LOW_SUPPORT        : support(근거 수) < min_support. 근거가 빈약한 엣지는 보류.
  - NON_CANONICAL_NODE : head/tail 이 canonical 엔티티 집합에 없음(04 산출물 기준).
  - CONFLICT           : 같은 (head,type) 에 모순되는 tail 이 둘 이상(asymmetric 함수형 관계).

임계값(min_support, require_provenance, conflict_check)은 GateConfig 로 조정한다.

전제: pydantic>=2. 네트워크·API 키 불필요.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel, Field

# ── 함수형(functional) asymmetric 관계: 한 head 당 tail 이 하나여야 자연스러운 관계.
#    여기에 같은 head 로 서로 다른 tail 이 둘 이상 오면 모순으로 본다.
#    (USES·COMPARES_TO 처럼 head 당 tail 이 여럿이어도 정상인 관계는 제외.)
FUNCTIONAL_TYPES = frozenset({"DEVELOPED_BY"})


# ────────────────────────────── 입력 모델 (Pydantic) ──────────────────────────────
class Provenance(BaseModel):
    """근거 1건. 어느 소스의 어느 구간이 이 엣지를 떠받치는가."""

    source_id: str
    version: str
    start: int
    end: int
    quote: str


class Relation(BaseModel):
    """05 가 내놓은 정규화 엣지. provenances 길이가 support 다."""

    head: str
    type: str
    tail: str
    direction: str = "asymmetric"
    provenances: list[Provenance] = Field(default_factory=list)

    @property
    def support(self) -> int:
        return len(self.provenances)

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.head, self.type, self.tail)


# ────────────────────────────── 게이트 설정 ──────────────────────────────
@dataclass
class GateConfig:
    """임계값은 코드가 아니라 설정으로 둔다. 도메인마다 다르게 조일 수 있어야 한다."""

    min_support: int = 1            # support 가 이 미만이면 LOW_SUPPORT
    require_provenance: bool = True  # provenance 0건이면 NO_PROVENANCE
    check_conflict: bool = True      # 함수형 관계의 tail 모순을 검사할지


@dataclass
class GateResult:
    """게이트 통과/거절 분기 결과."""

    passed: list[Relation] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)  # {head,type,tail,reason,provenance?}

    def reject_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for r in self.rejected:
            counts[r["reason"]] = counts.get(r["reason"], 0) + 1
        return counts


# ────────────────────────────── 게이트 본체 ──────────────────────────────
def run_gate(
    relations: list[Relation],
    canonical_names: set[str],
    config: GateConfig | None = None,
) -> GateResult:
    """엣지 리스트를 점수화해 통과/거절로 분기한다.

    canonical_names 는 04 산출물(canonical_entities)의 name 집합이다.
    head/tail 이 이 집합에 없으면 NON_CANONICAL_NODE 로 거절한다.
    """
    cfg = config or GateConfig()
    result = GateResult()

    # 충돌 검사를 위해 먼저 (head,type) → {tail} 를 모은다.
    functional_tails: dict[tuple[str, str], set[str]] = {}
    if cfg.check_conflict:
        for r in relations:
            if r.type in FUNCTIONAL_TYPES:
                functional_tails.setdefault((r.head, r.type), set()).add(r.tail)
    conflicted = {
        k for k, tails in functional_tails.items() if len(tails) > 1
    }

    for r in relations:
        reason = _first_failing_reason(r, canonical_names, cfg, conflicted)
        if reason is None:
            result.passed.append(r)
        else:
            # 거절 항목에도 근거를 붙여 둔다. "왜 빠졌나"를 사람이 추적할 수 있게.
            first_prov = r.provenances[0].model_dump() if r.provenances else None
            result.rejected.append(
                {
                    "head": r.head,
                    "type": r.type,
                    "tail": r.tail,
                    "reason": reason,
                    "provenance": first_prov,
                }
            )
    return result


def _first_failing_reason(
    r: Relation,
    canonical_names: set[str],
    cfg: GateConfig,
    conflicted: set[tuple[str, str]],
) -> str | None:
    """엣지 하나에 대해 첫 번째로 걸리는 거절 사유를 반환. 다 통과면 None."""
    if cfg.require_provenance and r.support == 0:
        return "NO_PROVENANCE"
    if r.support < cfg.min_support:
        return "LOW_SUPPORT"
    if r.head not in canonical_names:
        return "NON_CANONICAL_NODE"
    if r.tail not in canonical_names:
        return "NON_CANONICAL_NODE"
    if cfg.check_conflict and (r.head, r.type) in conflicted:
        return "CONFLICT"
    return None


def load_canonical_names(rows: list[dict]) -> set[str]:
    """canonical_entities 행에서 name 집합을 뽑는다. head/tail 검증의 기준."""
    return {row["name"] for row in rows}
