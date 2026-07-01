"""
gates.py — 답변 시점 세 게이트(Semantic / Access / Policy)

전제:
  - Pydantic v2, PyYAML (requirements.txt). API 키·Neo4j 불필요. 로컬에서 돈다.
  - 04 산출물을 그대로 import 한다:
      controlled_vocabulary(개념 status 대조) · rule_engine(domain/range 재검증).
  - decision_log.PolicyDecision 으로 결과를 기록한다.

세 게이트의 역할 분담(입력은 같은 retrieved_context 항목, 관점이 다르다):
  - semantic_gate : "이 항목이 의미상 여전히 유효한가?"
      · 참조 개념이 vocabulary 에 있는가, status 가 deprecated 는 아닌가.
      · kind=triple 이면 04 rule_engine 으로 domain/range 를 답변 시점에 다시 검증.
        (적재 때 통과했어도, 검색이 뒤집힌 트리플을 끌어올 수 있다.)
  - access_gate   : "이 사용자가 이 항목을 볼 권한이 있는가?"
      · Phase 1 Document Data Contract 의 acl 과 principal(role/tenant)을 대조.
  - policy_gate   : "조직 정책상 답변에 인용해도 되는가?"
      · policy_rules.yaml — provenance 필수 / deprecated 배제 / min_confidence / 민감필드 마스킹.

각 게이트는 항목 하나를 받아 PolicyDecision(allow|deny|mask)을 돌려준다.
deny 면 그 항목은 이후 게이트를 볼 필요 없이 답변에서 빠진다(오케스트레이터가 단락).
"""

from __future__ import annotations

from pathlib import Path

import yaml
from controlled_vocabulary import ControlledVocabulary
from decision_log import PolicyDecision
from rule_engine import RuleEngine

POLICY_PATH = Path(__file__).with_name("policy_rules.yaml")


def load_policy_rules(path: Path = POLICY_PATH) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# (A) Semantic Gate — 의미 정합. vocabulary status + 04 rule_engine 재검증.
# --------------------------------------------------------------------------- #
class SemanticGate:
    def __init__(self, vocab: ControlledVocabulary, engine: RuleEngine,
                 nodes: list[dict]) -> None:
        self.vocab = vocab
        self.engine = engine
        self.nodes = nodes
        self._by_id = {n["node_id"]: n for n in nodes}

    def check(self, item: dict) -> PolicyDecision:
        item_id = item["item_id"]

        # 1) 참조 개념이 vocabulary 에 있고 active 인가.
        #    deprecated 는 여기서 곧장 막지 않고 "표시"만 해도 되지만(정책이 최종 결정),
        #    미등록 개념(어휘 밖)은 의미 검증 실패로 본다.
        for cid in item.get("concept_ids", []):
            entry = self._concept(cid)
            if entry is None:
                return PolicyDecision(
                    item_id=item_id, gate="semantic", decision="deny",
                    reason=f"UNKNOWN_CONCEPT: 개념 {cid!r} 가 vocabulary 에 없다",
                )

        # 2) triple 이면 04 rule_engine 으로 domain/range 를 답변 시점에 재검증.
        if item.get("kind") == "triple":
            triple = {"subject": item["subject"], "rel": item["rel"],
                      "object": item["object"]}
            reasons = self.engine.check_triples([triple], self.nodes)
            violations = [r for r in reasons if r.severity == "violation"]
            if violations:
                v = violations[0]
                return PolicyDecision(
                    item_id=item_id, gate="semantic", decision="deny",
                    reason=f"SEMANTIC_VIOLATION[{v.rule_id}]: {v.message}",
                )

        return PolicyDecision(item_id=item_id, gate="semantic", decision="allow")

    def _concept(self, concept_id: str):
        for c in self.vocab.concepts:
            if c.concept_id == concept_id:
                return c
        return None

    def is_deprecated(self, concept_id: str) -> bool:
        c = self._concept(concept_id)
        return c is not None and c.status == "deprecated"


# --------------------------------------------------------------------------- #
# (B) Access Gate — acl vs principal(role/tenant).
# --------------------------------------------------------------------------- #
class AccessGate:
    def __init__(self, rules: dict) -> None:
        acl = rules.get("acl", {})
        self.enabled = acl.get("enabled", True)
        self.public_marker = acl.get("public_marker", "public")
        self.reason_role = acl.get("reason_role", "ACL_ROLE_DENIED")
        self.reason_tenant = acl.get("reason_tenant", "ACL_TENANT_DENIED")

    def check(self, item: dict, principal: dict) -> PolicyDecision:
        item_id = item["item_id"]
        if not self.enabled:
            return PolicyDecision(item_id=item_id, gate="access", decision="allow")

        acl = item.get("acl") or {}
        visibility = acl.get("visibility", self.public_marker)

        # public 은 role 검사 생략. 단, tenant 격리가 걸려 있으면 tenant 는 본다.
        if visibility != self.public_marker:
            roles = acl.get("roles", [])
            if principal.get("role") not in roles:
                return PolicyDecision(
                    item_id=item_id, gate="access", decision="deny",
                    reason=f"{self.reason_role} (roles={roles}, "
                           f"principal.role={principal.get('role')!r})",
                )

        tenants = acl.get("tenants")
        if tenants and principal.get("tenant") not in tenants:
            return PolicyDecision(
                item_id=item_id, gate="access", decision="deny",
                reason=f"{self.reason_tenant} (tenants={tenants}, "
                       f"principal.tenant={principal.get('tenant')!r})",
            )

        return PolicyDecision(item_id=item_id, gate="access", decision="allow")


# --------------------------------------------------------------------------- #
# (C) Policy Gate — provenance / deprecated / min_confidence / mask.
#     deprecated 판정은 SemanticGate.is_deprecated 를 빌려 쓴다(어휘 진실은 한 곳).
# --------------------------------------------------------------------------- #
class PolicyGate:
    def __init__(self, rules: dict, semantic: SemanticGate) -> None:
        self.rules = rules
        self.semantic = semantic

    def check(self, item: dict) -> PolicyDecision:
        item_id = item["item_id"]

        # 1) require_provenance — 출처 없으면 deny.
        rp = self.rules.get("require_provenance", {})
        if rp.get("enabled") and not item.get("provenance"):
            return self._deny(item_id, rp["reason"])

        # 2) deny_deprecated — 폐기 개념 참조 시 deny.
        dd = self.rules.get("deny_deprecated", {})
        if dd.get("enabled"):
            for cid in item.get("concept_ids", []):
                if self.semantic.is_deprecated(cid):
                    return self._deny(item_id, f"{dd['reason']} (concept={cid})")

        # 3) min_confidence — 임계값 미만이면 deny.
        mc = self.rules.get("min_confidence", {})
        if mc.get("enabled"):
            conf = item.get("confidence", 1.0)
            if conf < mc["threshold"]:
                return self._deny(item_id,
                                  f"{mc['reason']} (confidence={conf} < {mc['threshold']})")

        # 4) mask_fields — 민감 필드가 있으면 mask 결정(항목은 인용하되 필드만 가림).
        mf = self.rules.get("mask_fields", {})
        if mf.get("enabled"):
            present = [f for f in mf.get("fields", []) if f in (item.get("fields") or {})]
            if present:
                return PolicyDecision(
                    item_id=item_id, gate="policy", decision="mask",
                    reason=mf["reason"], masked_fields=present,
                )

        return PolicyDecision(item_id=item_id, gate="policy", decision="allow")

    @staticmethod
    def _deny(item_id: str, reason: str) -> PolicyDecision:
        return PolicyDecision(item_id=item_id, gate="policy", decision="deny",
                              reason=reason)


def apply_mask(item: dict, masked_fields: list[str], mask_token: str = "***") -> dict:
    """mask 결정을 실제 데이터에 적용한다. 원본은 건드리지 않고 사본을 돌려준다."""
    masked = dict(item)
    fields = dict(masked.get("fields") or {})
    for f in masked_fields:
        if f in fields:
            fields[f] = mask_token
    masked["fields"] = fields
    return masked
