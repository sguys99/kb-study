"""
answer_time_check.py — 답변 시점 게이트 파이프라인 오케스트레이터

전제:
  - Pydantic v2, PyYAML (requirements.txt). API 키·Neo4j 불필요. 전부 로컬에서 돈다.
  - 같은 폴더의 04 산출물(controlled_vocabulary·rule_engine·reject_reason·shapes.yaml)과
    05 산출물(policy_rules.yaml·gates·decision_log·vocabulary.yaml·retrieved_context.json)을 쓴다.

무엇을 하나:
  retrieved_context(검색이 끌어온 문서·트리플 + 각 항목의 acl/provenance/concept_id/confidence)
  와 principal(user role/tenant)을 받아, 세 게이트를 순차 적용한다.

  순서: semantic → access → policy.
    - 앞 게이트에서 deny 가 나면 즉시 단락(short-circuit)하고 blocked 로 보낸다.
    - policy 게이트가 mask 를 내면, 항목은 allowed 로 가되 지정 필드는 *** 로 가린다.
    - 세 게이트를 모두 통과(또는 mask)하면 allowed 로 넣는다.

  결과: AnswerTimeResult
    - allowed[]      : 답변에 인용해도 되는 항목(마스킹 적용된 사본).
    - blocked[]      : 배제된 항목 + 사유(reason).
    - decision_log   : 항목×게이트 결정 전체(감사용). Phase 6/7 이 그대로 재사용.

  답변 생성기는 allowed 만 인용한다. blocked 는 인용하지 않되 감사 로그에 남는다.
"""

from __future__ import annotations

import json
from pathlib import Path

from controlled_vocabulary import load_vocabulary
from decision_log import DecisionLog, PolicyDecision
from gates import AccessGate, PolicyGate, SemanticGate, apply_mask, load_policy_rules
from pydantic import BaseModel, Field
from rule_engine import RuleEngine, ShapesGraph

HERE = Path(__file__).parent


class BlockedItem(BaseModel):
    item_id: str
    gate: str      # 어느 게이트에서 막혔나
    reason: str


class AnswerTimeResult(BaseModel):
    allowed: list[dict] = Field(default_factory=list)   # 마스킹 적용된 항목
    blocked: list[BlockedItem] = Field(default_factory=list)
    decision_log: DecisionLog = Field(default_factory=DecisionLog)

    def allowed_ids(self) -> list[str]:
        return [i["item_id"] for i in self.allowed]

    def blocked_ids(self) -> list[str]:
        return [b.item_id for b in self.blocked]


class AnswerTimeChecker:
    """세 게이트를 들고, 컨텍스트를 걸러 allowed/blocked 로 나눈다."""

    def __init__(self, nodes: list[dict]) -> None:
        vocab = load_vocabulary(HERE / "vocabulary.yaml")
        rules = load_policy_rules(HERE / "policy_rules.yaml")
        # rule_engine 은 04 shapes.yaml + 05 vocabulary 로 구성(어휘 진실은 한 곳).
        engine = RuleEngine(ShapesGraph.load(HERE / "shapes.yaml"), vocab)

        self.semantic = SemanticGate(vocab, engine, nodes)
        self.access = AccessGate(rules)
        self.policy = PolicyGate(rules, self.semantic)
        self.mask_token = rules.get("mask_fields", {}).get("mask_token", "***")

    def run(self, items: list[dict], principal: dict) -> AnswerTimeResult:
        result = AnswerTimeResult()

        for item in items:
            # --- 게이트를 순서대로. deny 가 나오면 단락. ---
            for gate_name, decision in self._pipeline(item, principal):
                result.decision_log.add(decision)

                if decision.decision == "deny":
                    result.blocked.append(BlockedItem(
                        item_id=item["item_id"], gate=gate_name,
                        reason=decision.reason or "",
                    ))
                    break  # 이후 게이트는 볼 필요 없다.

                if decision.decision == "mask":
                    masked = apply_mask(item, decision.masked_fields, self.mask_token)
                    result.allowed.append(masked)
                    break  # policy 가 마지막 게이트다.
            else:
                # for 가 break 없이 끝났다 = 모든 게이트 allow.
                result.allowed.append(item)

        return result

    def _pipeline(self, item: dict, principal: dict):
        """항목 하나에 대해 (게이트명, 결정)을 순서대로 만들어 흘려보낸다(제너레이터)."""
        yield "semantic", self.semantic.check(item)
        yield "access", self.access.check(item, principal)
        yield "policy", self.policy.check(item)


def answer_time_check(context: dict, principal: dict) -> AnswerTimeResult:
    """공개 진입점. retrieved_context dict + principal dict → AnswerTimeResult."""
    checker = AnswerTimeChecker(nodes=context["nodes"])
    items = [i for i in context["items"] if not str(i.get("item_id", "")).startswith("_")]
    return checker.run(items, principal)


def _load_json(name: str) -> dict:
    return json.loads((HERE / name).read_text(encoding="utf-8"))


if __name__ == "__main__":
    context = _load_json("retrieved_context.json")
    principal = _load_json("principal.json")

    print(f"== answer-time check (principal: role={principal['role']}, "
          f"tenant={principal['tenant']}) ==\n")

    result = answer_time_check(context, principal)

    print("-- allowed (답변에 인용 가능) --")
    for item in result.allowed:
        fields = item.get("fields")
        extra = f"  fields={fields}" if fields else ""
        print(f"  ALLOW {item['item_id']:8} {item.get('text','')}{extra}")

    print("\n-- blocked (배제 + 사유) --")
    for b in result.blocked:
        print(f"  DENY  {b.item_id:8} [{b.gate}] {b.reason}")

    print("\n-- decision_log --")
    for d in result.decision_log.decisions:
        print("  " + d.line())
    print()
    print(result.decision_log.summary())

    # ------------------------------------------------------------------ #
    # 자체검증 — 완료 기준을 코드로 못박는다.
    # answer_time_check(context, principal={role:'analyst', tenant:'team-a'}) 가
    #   internal 문서 → access,
    #   deprecated 개념 · provenance 없는 트리플 · 저신뢰 → policy,
    #   방향 뒤집힌 트리플 → semantic
    # 사유로 blocked 에 넣고, 통과분만 allowed 로 반환하며 decision_log 를 낸다.
    # ------------------------------------------------------------------ #
    allowed = set(result.allowed_ids())
    blocked = {b.item_id: b for b in result.blocked}

    # 통과: ctx-01(정상 triple), ctx-07(마스킹되어 통과).
    assert allowed == {"ctx-01", "ctx-07"}, allowed

    # ctx-02: internal·admin 전용 → access deny.
    assert blocked["ctx-02"].gate == "access"

    # ctx-08: role 은 맞으나 tenant 불일치 → access deny.
    assert blocked["ctx-08"].gate == "access"

    # ctx-03: deprecated(naive-rag) → policy deny.
    assert blocked["ctx-03"].gate == "policy"
    assert "DEPRECATED" in blocked["ctx-03"].reason

    # ctx-04: provenance 없음 → policy deny.
    assert blocked["ctx-04"].gate == "policy"
    assert "PROVENANCE" in blocked["ctx-04"].reason

    # ctx-05: confidence 0.42 < 0.60 → policy deny.
    assert blocked["ctx-05"].gate == "policy"
    assert "LOW_CONFIDENCE" in blocked["ctx-05"].reason

    # ctx-06: 방향 뒤집힌 USES → semantic deny.
    assert blocked["ctx-06"].gate == "semantic"

    # ctx-07: 민감 필드가 *** 로 가려진 채 allowed.
    masked_item = next(i for i in result.allowed if i["item_id"] == "ctx-07")
    assert masked_item["fields"]["raw_score"] == "***"
    assert masked_item["fields"]["author_email"] == "***"

    # decision_log 집계에 access/deny·policy/deny·semantic/deny·policy/mask 가 모두 있다.
    counts = result.decision_log.by_gate_decision()
    assert counts[("access", "deny")] == 2
    assert counts[("policy", "deny")] == 3
    assert counts[("semantic", "deny")] == 1
    assert counts[("policy", "mask")] == 1

    print("\n[assert] 모든 자체검증 통과")
