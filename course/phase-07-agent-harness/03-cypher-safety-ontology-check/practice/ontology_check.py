"""ontology_check.py — 세 번째 하니스 도구. LLM 출력이 허용 온톨로지에 부합하는지 검증한다.

두 가지 입력을 받는다(둘 다 선택, 최소 하나):
  1) cypher   : 생성된 Cypher 문자열. 여기 등장하는 라벨(:Method)·관계타입([:USES])을 추출해 검사.
  2) triples  : 답변/추출이 주장하는 (subject_label, relation, object_label) 삼중항 리스트.
                예: [{"subject": "Method", "relation": "USES", "object": "Dataset"}]

검사 결과: 위반(violations) 리포트. 각 위반은 kind·item·reason 을 담는다.
  - unknown_label     : 온톨로지에 없는 라벨(:Dataset 을 하니스 스키마에 넣으면 위반).
  - unknown_relation  : 온톨로지에 없는 관계 타입([:MENTIONS] 등).
  - direction_violation: 관계는 있으나 domain/range 방향이 어긋남
                         (예: (:Component)-[:USES]->(:Method) — USES 는 Method->Component 여야 함).

이 도구가 Phase 5 를 어떻게 재사용하나:
  - ontology.py(=Phase 5 controlled_vocabulary 축약)의 resolve_label/resolve_relation 로
    자유 표기를 표준으로 접고, allowed 집합으로 존재 여부를 본다.
  - domain/range 방향 검사는 5/04 SHACL shapes(관계 제약)의 축약이다.

에이전트 관점:
  - graph_query(text2cypher) 가 만든 Cypher 를 실행하기 전/후에 "스키마상 타당한가"를 물어볼 수 있고,
  - 답변이 "A 는 B 를 USES 한다"고 주장할 때 그 관계 방향이 온톨로지에 맞는지 확인할 수 있다.
  - 도구 목록이 docs_search + graph_query + ontology_check 3개로 확장된다(register_all_tools.py).

전제: ontology.py + ontology.yaml(Pydantic v2·PyYAML). API 키·Neo4j 불필요.
"""

from __future__ import annotations

import re

from ontology import Ontology, load_ontology

# 온톨로지는 모듈 로드 시 한 번만 구성.
_ONTOLOGY: Ontology = load_ontology()

# Cypher 에서 라벨 추출: (n:Method), (:Framework), (x:Concept {name:...})
_LABEL_RE = re.compile(r"\(\s*[A-Za-z_][A-Za-z0-9_]*\s*:\s*([A-Za-z_][A-Za-z0-9_]*)|\(\s*:\s*([A-Za-z_][A-Za-z0-9_]*)")
# Cypher 에서 관계 타입 추출: -[:USES]->, -[r:IS_A]-, <-[:EXTENDS]-
_RELTYPE_RE = re.compile(r"\[\s*[A-Za-z_]*\s*:\s*([A-Za-z_][A-Za-z0-9_]*)")


def _extract_labels_from_cypher(cypher: str) -> list[str]:
    """Cypher 문자열에서 노드 라벨을 추출한다(중복 제거, 등장 순서 보존)."""
    found: list[str] = []
    for m in _LABEL_RE.finditer(cypher):
        lab = m.group(1) or m.group(2)
        if lab and lab not in found:
            found.append(lab)
    return found


def _extract_relations_from_cypher(cypher: str) -> list[str]:
    """Cypher 문자열에서 관계 타입을 추출한다(중복 제거, 등장 순서 보존)."""
    found: list[str] = []
    for m in _RELTYPE_RE.finditer(cypher):
        rel = m.group(1)
        if rel and rel not in found:
            found.append(rel)
    return found


def _check_label(raw: str) -> dict | None:
    """라벨 하나 검사. 위반이면 위반 dict, 통과면 None."""
    if _ONTOLOGY.resolve_label(raw) is None:
        return {
            "kind": "unknown_label",
            "item": raw,
            "reason": f"온톨로지에 없는 라벨: {raw!r}. 허용: {sorted(_ONTOLOGY.allowed_labels())}",
        }
    return None


def _check_relation(raw: str) -> dict | None:
    """관계 타입 하나 검사(방향은 보지 않음). 위반이면 위반 dict, 통과면 None."""
    if _ONTOLOGY.resolve_relation(raw) is None:
        return {
            "kind": "unknown_relation",
            "item": raw,
            "reason": f"온톨로지에 없는 관계 타입: {raw!r}. 허용: {sorted(_ONTOLOGY.allowed_relations())}",
        }
    return None


def _check_triple(subject: str, relation: str, obj: str) -> dict | None:
    """삼중항(subject_label, relation, object_label)의 관계 존재 + 방향(domain/range)까지 검사."""
    rel = _ONTOLOGY.resolve_relation(relation)
    if rel is None:
        return {
            "kind": "unknown_relation",
            "item": f"({subject})-[{relation}]->({obj})",
            "reason": f"온톨로지에 없는 관계 타입: {relation!r}",
        }
    sub_def = _ONTOLOGY.resolve_label(subject)
    obj_def = _ONTOLOGY.resolve_label(obj)
    if sub_def is None:
        return {"kind": "unknown_label", "item": subject,
                "reason": f"온톨로지에 없는 라벨(subject): {subject!r}"}
    if obj_def is None:
        return {"kind": "unknown_label", "item": obj,
                "reason": f"온톨로지에 없는 라벨(object): {obj!r}"}
    # 방향 검사: 표준화된 라벨이 관계의 domain/range 와 정확히 일치해야 한다.
    if not (sub_def.label == rel.domain and obj_def.label == rel.range):
        return {
            "kind": "direction_violation",
            "item": f"({sub_def.label})-[{rel.label}]->({obj_def.label})",
            "reason": (
                f"방향 위반: {rel.label} 는 ({rel.domain})-[{rel.label}]->({rel.range}) 만 허용. "
                f"주어진 ({sub_def.label})->({obj_def.label}) 는 어긋난다."
            ),
        }
    return None


def ontology_check(cypher: str | None = None, triples: list[dict] | None = None) -> dict:
    """ontology_check 도구 본체. cypher / triples 중 최소 하나를 받아 위반 리포트를 만든다.

    반환 계약:
      {
        "ok": bool,                 # 위반이 하나도 없으면 True
        "checked": {...},           # 무엇을 봤는지(라벨·관계·삼중항 수)
        "violations": [ {kind,item,reason}, ... ],
      }
    """
    if not cypher and not triples:
        return {"ok": False, "checked": {}, "violations": [
            {"kind": "bad_input", "item": None, "reason": "cypher 또는 triples 중 최소 하나가 필요하다"}
        ]}

    violations: list[dict] = []
    checked = {"labels": [], "relations": [], "triples": 0}

    if cypher:
        labels = _extract_labels_from_cypher(cypher)
        relations = _extract_relations_from_cypher(cypher)
        checked["labels"] = labels
        checked["relations"] = relations
        for lab in labels:
            v = _check_label(lab)
            if v:
                violations.append(v)
        for rel in relations:
            v = _check_relation(rel)
            if v:
                violations.append(v)

    if triples:
        checked["triples"] = len(triples)
        for t in triples:
            v = _check_triple(t.get("subject", ""), t.get("relation", ""), t.get("object", ""))
            if v:
                violations.append(v)

    return {"ok": len(violations) == 0, "checked": checked, "violations": violations}


if __name__ == "__main__":
    import json

    print("=== ontology_check: Cypher 검사 ===\n")
    good_cypher = "MATCH (m:Method)-[:USES]->(c:Component) RETURN m.name, c.name LIMIT 10"
    bad_cypher = "MATCH (m:Method)-[:MENTIONS]->(d:Dataset) RETURN m.name, d.name LIMIT 10"

    print("정상 Cypher:", good_cypher)
    print(json.dumps(ontology_check(cypher=good_cypher), ensure_ascii=False, indent=2))
    print("\n위반 Cypher(:Dataset 라벨 + :MENTIONS 관계):", bad_cypher)
    print(json.dumps(ontology_check(cypher=bad_cypher), ensure_ascii=False, indent=2))

    print("\n=== ontology_check: 삼중항 방향 검사 ===\n")
    triples = [
        {"subject": "Method", "relation": "USES", "object": "Component"},      # 정상
        {"subject": "Component", "relation": "USES", "object": "Method"},      # 방향 위반
        {"subject": "Framework", "relation": "IMPLEMENTS", "object": "Concept"},  # 정상
        {"subject": "Method", "relation": "CURES", "object": "Concept"},       # 미등록 관계
    ]
    print(json.dumps(ontology_check(triples=triples), ensure_ascii=False, indent=2))

    # 자체검증(assert) — 완료 기준을 코드로 못박는다.
    assert ontology_check(cypher=good_cypher)["ok"] is True
    bad = ontology_check(cypher=bad_cypher)
    assert bad["ok"] is False
    kinds = {v["kind"] for v in bad["violations"]}
    assert "unknown_label" in kinds and "unknown_relation" in kinds
    tri = ontology_check(triples=triples)
    assert tri["ok"] is False
    tri_kinds = {v["kind"] for v in tri["violations"]}
    assert "direction_violation" in tri_kinds and "unknown_relation" in tri_kinds
    print("\n[assert] ontology_check 자체검증 통과")
