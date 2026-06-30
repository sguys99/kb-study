"""validate_schema.py — CQ 로 스키마를 검증한다(커버리지 점검).

"질문이 스키마를 결정한다"의 실체다. competency_questions.yaml 의 각 CQ 가 요구하는
node_types / relation_types 가 graph_schema.py 의 enum 에 '모두' 존재하는지 대조한다.

  - 다 존재하면        → 그 CQ 는 PASS(스키마가 답할 수 있다).
  - 하나라도 없으면    → 그 CQ 는 REJECT, 빠진 타입을 찍는다.
                         (이게 Phase 2 품질 게이트의 가장 단순한 형태다.)

스키마는 추출 전에 굳혀야 한다. 추출하고 나서 "이 질문 답이 안 되네"를 발견하면 늦다.
CQ 커버리지로 '추출하기 전에' 빠진 타입·관계를 잡는다.

전제: 네트워크·API 키·LLM·DB 불필요. 순수 로컬.
의존: pydantic>=2, pyyaml. graph_schema.py 는 같은 폴더의 로컬 모듈.
실행: python validate_schema.py [competency_questions.yaml]
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

from graph_schema import NodeType, RelationType

# enum 값(문자열)들의 집합. CQ 가 적은 타입이 이 안에 있어야 한다.
ALLOWED_NODES = {t.value for t in NodeType}
ALLOWED_RELATIONS = {t.value for t in RelationType}


def load_cqs(path: Path) -> list[dict]:
    """competency_questions.yaml 을 읽어 CQ 목록을 돌려준다."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data.get("questions", [])


def check_cq(cq: dict) -> tuple[bool, list[str], list[str]]:
    """CQ 1건을 검사한다. (통과여부, 빠진 노드타입, 빠진 관계타입)."""
    need_nodes = cq.get("node_types", []) or []
    need_rels = cq.get("relation_types", []) or []
    missing_nodes = [n for n in need_nodes if n not in ALLOWED_NODES]
    missing_rels = [r for r in need_rels if r not in ALLOWED_RELATIONS]
    passed = not missing_nodes and not missing_rels
    return passed, missing_nodes, missing_rels


def main(path: Path) -> int:
    cqs = load_cqs(path)
    if not cqs:
        print(f"CQ 가 없다: {path}")
        return 1

    passed_ids: list[str] = []
    rejected: list[tuple[str, list[str], list[str]]] = []

    print(f"스키마 통제 어휘 — 노드 {len(ALLOWED_NODES)}종 / 관계 {len(ALLOWED_RELATIONS)}종")
    print(f"CQ {len(cqs)}건 커버리지 점검\n")

    for cq in cqs:
        cq_id = cq.get("id", "?")
        ok, miss_n, miss_r = check_cq(cq)
        if ok:
            passed_ids.append(cq_id)
            print(f"  [PASS]   {cq_id}  ({cq.get('type')})")
        else:
            rejected.append((cq_id, miss_n, miss_r))
            parts = []
            if miss_n:
                parts.append(f"missing node_types={miss_n}")
            if miss_r:
                parts.append(f"missing relation_types={miss_r}")
            print(f"  [REJECT] {cq_id}  ({cq.get('type')})  " + "; ".join(parts))

    coverage = 100.0 * len(passed_ids) / len(cqs)
    print(f"\n커버리지: {len(passed_ids)}/{len(cqs)} = {coverage:.0f}%")
    if rejected:
        print(f"미충족 CQ: {[r[0] for r in rejected]}")
        print("→ 스키마에 빠진 타입/관계를 추가하거나 CQ 를 조정하라(둘 중 하나).")
        return 2
    print("모든 CQ 가 현재 스키마로 답 가능 — 추출 단계로 넘어가도 된다.")
    return 0


if __name__ == "__main__":
    default = Path(__file__).with_name("competency_questions.yaml")
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else default
    raise SystemExit(main(target))
