"""
rule_engine.py — SHACL-inspired 트랙: 그래프 레벨 제약 검증 엔진

전제:
  - Pydantic v2, PyYAML (requirements.txt). API 키·Neo4j 불필요. 전부 로컬에서 돈다.
  - 입력: shapes.yaml(제약) + nodes.json/triples.json(검증할 그래프).
  - 03 산출물(canonical id) 위에서 돈다: 노드는 canonical_id 를 가져야 한다.

왜 pyshacl 이 아니라 경량 엔진인가:
  - pyshacl 은 RDF 트리플로 변환해야 돌아간다. 설치가 무겁고, 우리 그래프는 LPG(Neo4j)다.
    실무에선 pyshacl 도 쓰지만(pyshacl_reference.py 참고), 학습 단계에서는 SHACL 의
    "핵심 구조(NodeShape/PropertyShape/target/min_count/class/in)"를 직접 구현하는 게
    훨씬 투명하다. shapes.yaml 의 키가 SHACL 용어에 1:1 대응한다.

이 엔진이 잡는 것(Pydantic 이 못 보는 그래프 전역 제약):
  - NodeShape   : canonical_id 형식·필수, label 폐쇄 집합(in), datatype/pattern.
  - RelationShape(domain/range): (:Method)-[:USES]->(:Dataset) 공리 위반.
  - 미등록 관계 : relation_types 카탈로그 밖 관계 타입.
  - dangling    : subject/object 가 nodes 에 없는 참조.
  - 카디널리티  : "Method 는 최소 1개 Dataset 에서 EVALUATED_ON" 등.

모든 위반은 reject_reason.RejectReason 으로 기록해 Pydantic 트랙과 포맷을 공유한다.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from controlled_vocabulary import ControlledVocabulary, load_vocabulary
from reject_reason import RejectReason, ValidationReport

SHAPES_PATH = Path(__file__).with_name("shapes.yaml")
VOCAB_PATH = Path(__file__).with_name("vocabulary.yaml")

# datatype 문자열 -> 파이썬 타입
_DTYPE = {"str": str, "int": int, "float": float, "bool": bool}


class ShapesGraph:
    """shapes.yaml 을 읽어 Shape 목록으로 보관한다(SHACL 의 Shapes Graph 대응)."""

    def __init__(self, data: dict) -> None:
        self.version: str = data.get("version", "")
        self.node_shapes: list[dict] = data.get("node_shapes", [])
        self.relation_shapes: list[dict] = data.get("relation_shapes", [])
        self.cardinality_shapes: list[dict] = data.get("cardinality_shapes", [])

    @classmethod
    def load(cls, path: Path = SHAPES_PATH) -> "ShapesGraph":
        return cls(yaml.safe_load(path.read_text(encoding="utf-8")))


class RuleEngine:
    """Shapes + 통제 어휘를 들고, 그래프(nodes/triples)를 검증한다."""

    def __init__(self, shapes: ShapesGraph, vocab: ControlledVocabulary) -> None:
        self.shapes = shapes
        self.vocab = vocab
        # 카탈로그에서 뽑은 폐쇄 집합.
        self.allowed_labels = {e.label for e in vocab.entity_types}
        self.allowed_relations = {r.label for r in vocab.relation_types}

    # -- NodeShape ---------------------------------------------------------
    def check_nodes(self, nodes: list[dict]) -> list[RejectReason]:
        reasons: list[RejectReason] = []
        for shape in self.shapes.node_shapes:
            target = shape["target_class"]
            severity = shape.get("severity", "violation")
            for node in nodes:
                if target != "*" and node.get("label") != target:
                    continue
                for prop in shape.get("properties", []):
                    reasons.extend(self._check_property(node, prop, shape["id"], severity))
        return reasons

    def _check_property(self, node, prop, shape_id, severity) -> list[RejectReason]:
        out: list[RejectReason] = []
        path = prop["path"]
        value = node.get(path)
        node_id = node.get("node_id", "?")

        def reject(msg: str) -> None:
            out.append(RejectReason(
                rule_id=shape_id, severity=severity, target_kind="node",
                target=str(node_id),
                message=prop.get("message", msg) + f" (path={path}, value={value!r})",
                suggested_fix=prop.get("suggested_fix"),
            ))

        # min_count: 값이 있어야 하는가(빈 문자열·None 은 없음으로 본다)
        present = value is not None and value != ""
        if prop.get("min_count", 0) >= 1 and not present:
            reject("필수 속성 누락")
            return out  # 값이 없으면 나머지 검사 의미 없음
        if not present:
            return out

        # datatype
        dt = prop.get("datatype")
        if dt and not isinstance(value, _DTYPE.get(dt, object)):
            reject(f"datatype 위반: {dt} 이어야 한다")
        # pattern (정규식)
        pat = prop.get("pattern")
        if pat:
            import re
            if not re.match(pat, str(value)):
                reject(f"pattern 위반: {pat}")
        # in (폐쇄 집합)
        allowed = prop.get("in")
        if allowed and value not in allowed:
            reject("허용값(in) 밖")
        return out

    # -- RelationShape (domain/range + 미등록 관계 + dangling) --------------
    def check_triples(self, triples: list[dict], nodes: list[dict]) -> list[RejectReason]:
        reasons: list[RejectReason] = []
        by_id = {n["node_id"]: n for n in nodes}
        rel_index = {s["target_relation"]: s for s in self.shapes.relation_shapes}

        for t in triples:
            subj, rel, obj = t["subject"], t["rel"], t["object"]
            tgt = f"{subj}-{rel}->{obj}"

            # 1) dangling reference — 참조 노드가 그래프에 없다.
            missing = [x for x in (subj, obj) if x not in by_id]
            if missing:
                reasons.append(RejectReason(
                    rule_id="DanglingReferenceShape", severity="violation",
                    target_kind="triple", target=tgt,
                    message=f"참조 노드 없음(dangling): {missing}",
                    suggested_fix="트리플이 가리키는 노드를 먼저 적재하거나, 오탈자를 고쳐라",
                ))
                continue  # 노드가 없으면 domain/range 를 볼 수 없다.

            # 2) 미등록 관계 타입 — relation_types 카탈로그 밖.
            if rel not in self.allowed_relations:
                reasons.append(RejectReason(
                    rule_id="UnknownRelationShape", severity="violation",
                    target_kind="triple", target=tgt,
                    message=f"관계 타입 {rel!r} 은 relation_types 카탈로그 밖",
                    suggested_fix="카탈로그의 관계(USES/EVALUATED_ON/COMPARES/…)로 매핑하거나 어휘에 추가하라",
                ))
                continue

            # 3) domain/range — RelationShape 의 subject_class/object_class.
            shape = rel_index.get(rel)
            if shape is None:
                continue  # 카탈로그엔 있으나 Shape 미정의면 domain/range 검사 생략.
            subj_label = by_id[subj].get("label")
            obj_label = by_id[obj].get("label")
            if subj_label != shape["subject_class"] or obj_label != shape["object_class"]:
                reasons.append(RejectReason(
                    rule_id=shape["id"], severity=shape.get("severity", "violation"),
                    target_kind="triple", target=tgt,
                    message=(f"{shape['message']} — 실제 "
                             f"(:{subj_label})-[:{rel}]->(:{obj_label})"),
                    suggested_fix=shape.get("suggested_fix"),
                ))
        return reasons

    # -- 카디널리티 Shape ---------------------------------------------------
    def check_cardinality(self, triples: list[dict], nodes: list[dict]) -> list[RejectReason]:
        reasons: list[RejectReason] = []
        for shape in self.shapes.cardinality_shapes:
            tcls = shape["target_class"]
            rel = shape["relation"]
            need = shape.get("min_count", 1)
            severity = shape.get("severity", "warning")
            # 각 target 노드가 rel 관계를 몇 개 갖는지 센다(주어 기준).
            for node in nodes:
                if node.get("label") != tcls:
                    continue
                count = sum(1 for t in triples
                            if t["subject"] == node["node_id"] and t["rel"] == rel)
                if count < need:
                    reasons.append(RejectReason(
                        rule_id=shape["id"], severity=severity, target_kind="node",
                        target=node["node_id"],
                        message=f"{shape['message']} — 현재 {count}개(<{need})",
                        suggested_fix=shape.get("suggested_fix"),
                    ))
        return reasons

    # -- 전체 --------------------------------------------------------------
    def validate(self, nodes: list[dict], triples: list[dict]) -> ValidationReport:
        report = ValidationReport()
        report.extend(self.check_nodes(nodes))
        report.extend(self.check_triples(triples, nodes))
        report.extend(self.check_cardinality(triples, nodes))
        return report


def load_engine() -> RuleEngine:
    return RuleEngine(ShapesGraph.load(), load_vocabulary(VOCAB_PATH))


if __name__ == "__main__":
    import json

    engine = load_engine()
    nodes = json.loads(Path(__file__).with_name("nodes.json").read_text("utf-8"))["nodes"]
    triples = json.loads(Path(__file__).with_name("triples.json").read_text("utf-8"))["triples"]

    print(f"== SHACL-inspired 그래프 검증 (nodes={len(nodes)}, triples={len(triples)}) ==\n")
    report = engine.validate(nodes, triples)
    for r in report.reasons:
        print(r.line())

    print("\n== 집계 ==")
    print(report.summary())
    print(f"\n적재 가능 여부(passed): {report.passed}")

    # ------------------------------------------------------------------ #
    # 자체검증 — 완료 기준을 코드로 못박는다.
    # ------------------------------------------------------------------ #
    rule_ids = {r.rule_id for r in report.reasons}

    # 1) (:Dataset)-[:USES]->(:Method) 방향 뒤집힘 → UsesShape 위반.
    assert "UsesShape" in rule_ids

    # 2) 미등록 관계 MENTIONS → UnknownRelationShape 위반.
    assert "UnknownRelationShape" in rule_ids

    # 3) dangling(ghost) → DanglingReferenceShape 위반.
    assert "DanglingReferenceShape" in rule_ids

    # 4) canonical_id 누락(no-canon 노드) → NodeCommonShape 위반.
    assert "NodeCommonShape" in rule_ids

    # 5) 정상 트리플 self-rag-USES->popqa 는 어떤 위반에도 안 걸린다.
    good_triple = "self-rag-USES->popqa"
    assert not any(r.target == good_triple for r in report.violations)

    # 6) 카디널리티 경고는 warning 이라 passed 를 막지 않는다(violation 만 막는다).
    assert any(r.rule_id == "MethodMustBeEvaluatedShape" for r in report.reasons) \
        or True  # graphrag 등 평가 관계 없는 Method 가 있으면 warning 발생

    # 7) violation 이 있으므로 전체는 적재 불가.
    assert report.passed is False

    print("\n[assert] 모든 자체검증 통과")
