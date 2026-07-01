"""
pydantic_models.py — Pydantic 트랙: 단일 레코드(노드/트리플) 스키마 검증

전제:
  - Pydantic v2, PyYAML (requirements.txt). API 키·Neo4j 불필요.
  - 같은 폴더의 vocabulary.yaml 과 controlled_vocabulary.py 를 입력으로 받는다(02·03 산출물).

역할 분담(이 파일이 막는 것):
  - Pydantic 은 "레코드 하나가 스키마에 맞는가"를 인입 단계에서 막는다.
    타입(enum)·필수 필드·값 형식·concept_id 가 어휘에 있는가 수준.
  - "그래프 전역의 관계·카디널리티·domain/range 공리"는 Pydantic 이 못 본다.
    그건 rule_engine.py(SHACL-inspired 트랙)의 몫이다.
  - 두 트랙 모두 위반을 reject_reason.RejectReason 하나로 기록해 뒤 단계가 공유한다.

즉 추출 파이프라인의 첫 관문이다. 여기서 걸러야 깨진 레코드가 그래프 근처에도 못 간다.
"""

from __future__ import annotations

from pathlib import Path

from controlled_vocabulary import ControlledVocabulary, load_vocabulary
from pydantic import BaseModel, ValidationError, field_validator
from reject_reason import RejectReason

VOCAB_PATH = Path(__file__).with_name("vocabulary.yaml")

# entity_types 카탈로그의 label 폐쇄 집합(enum). vocabulary 에서 뽑아 쓴다.
# 로드 시점에 채워 넣는다(아래 build_node_validator).
_ALLOWED_LABELS: set[str] = set()
_KNOWN_CANONICAL: set[str] = set()


class NodeRecord(BaseModel):
    """노드 한 개의 스키마. Pydantic 이 필드 형식을 강제한다."""

    node_id: str
    label: str
    canonical_id: str
    concept_id: str

    @field_validator("node_id", "label", "concept_id")
    @classmethod
    def _nonempty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("빈 문자열은 허용되지 않는다(필수 필드)")
        return v

    @field_validator("canonical_id")
    @classmethod
    def _canonical_format(cls, v: str) -> str:
        # 필수 + 형식. 03 에서 발급한 urn:kb:concept:<slug> 형식이어야 한다.
        if not v:
            raise ValueError("canonical_id 누락: 표준 ID 없이 그래프에 넣을 수 없다")
        if not v.startswith("urn:kb:concept:"):
            raise ValueError(f"canonical_id 형식 위반(urn:kb:concept: 접두어): {v!r}")
        return v

    @field_validator("label")
    @classmethod
    def _label_in_catalog(cls, v: str) -> str:
        # entity_types 카탈로그(폐쇄 집합) 밖 라벨은 REJECT.
        if _ALLOWED_LABELS and v not in _ALLOWED_LABELS:
            raise ValueError(
                f"label {v!r} 은 entity_types 카탈로그 밖(허용: {sorted(_ALLOWED_LABELS)})"
            )
        return v


def load_allowed(vocab: ControlledVocabulary) -> None:
    """vocabulary 에서 허용 라벨·알려진 canonical id 집합을 채운다."""
    global _ALLOWED_LABELS, _KNOWN_CANONICAL
    _ALLOWED_LABELS = {e.label for e in vocab.entity_types}
    # 03 에서 concept 마다 canonical id 를 발급했다: urn:kb:concept:<concept_id>
    _KNOWN_CANONICAL = {f"urn:kb:concept:{c.concept_id}" for c in vocab.concepts}


def validate_node(raw: dict) -> tuple[NodeRecord | None, list[RejectReason]]:
    """raw dict 한 개를 NodeRecord 로 검증한다. 실패하면 RejectReason 리스트를 돌려준다."""
    reasons: list[RejectReason] = []
    try:
        node = NodeRecord.model_validate(raw)
    except ValidationError as e:
        # Pydantic 이 잡은 필드 오류를 우리 리포트 포맷으로 옮긴다.
        for err in e.errors():
            field = ".".join(str(p) for p in err["loc"]) or "(record)"
            reasons.append(RejectReason(
                rule_id=f"Pydantic:NodeRecord.{field}",
                severity="violation",
                target_kind="node",
                target=str(raw.get("node_id", "?")),
                message=err["msg"],
                suggested_fix="레코드 스키마(타입·필수·형식)를 맞춘 뒤 다시 넣어라",
            ))
        return None, reasons

    # 스키마는 통과했으나 canonical_id 가 어휘 레지스트리에 없는 경우(soft 무결성).
    # 형식은 맞지만 "우리가 발급한 적 없는" ID 다 → 위반.
    if _KNOWN_CANONICAL and node.canonical_id not in _KNOWN_CANONICAL:
        reasons.append(RejectReason(
            rule_id="Pydantic:NodeRecord.canonical_in_registry",
            severity="violation",
            target_kind="node",
            target=node.node_id,
            message=f"canonical_id {node.canonical_id!r} 가 발급 레지스트리에 없다",
            suggested_fix="canonical_id.py 로 이 concept 에 Canonical ID 를 먼저 발급하라",
        ))
        return None, reasons

    return node, reasons


if __name__ == "__main__":
    import json

    vocab = load_vocabulary(VOCAB_PATH)
    load_allowed(vocab)

    data = json.loads(Path(__file__).with_name("nodes.json").read_text(encoding="utf-8"))
    nodes = data["nodes"]

    print(f"== Pydantic 노드 검증 ({len(nodes)}개) ==")
    ok, bad = 0, 0
    for raw in nodes:
        node, reasons = validate_node(raw)
        if node is not None and not reasons:
            ok += 1
            print(f"  PASS   {raw['node_id']:12} [{raw['label']}]")
        else:
            bad += 1
            for r in reasons:
                print(f"  {r.line()}")

    print(f"\n결과: PASS {ok}건, REJECT {bad}건")

    # 자체검증 — Pydantic 트랙이 무엇을 잡아야 하는지 못박는다.
    # 1) 정상 노드는 통과.
    good, rs = validate_node(
        {"node_id": "self-rag", "label": "Method",
         "canonical_id": "urn:kb:concept:self-rag", "concept_id": "self-rag"})
    assert good is not None and rs == []

    # 2) canonical_id 누락은 REJECT.
    _, rs = validate_node(
        {"node_id": "no-canon", "label": "Method",
         "canonical_id": "", "concept_id": "no-canon"})
    assert any("canonical_id" in r.message for r in rs)

    # 3) 카탈로그 밖 label(Framework)은 REJECT.
    _, rs = validate_node(
        {"node_id": "bad-label", "label": "Framework",
         "canonical_id": "urn:kb:concept:bad-label", "concept_id": "bad-label"})
    assert any("카탈로그" in r.message for r in rs)

    print("\n[assert] 모든 자체검증 통과")
