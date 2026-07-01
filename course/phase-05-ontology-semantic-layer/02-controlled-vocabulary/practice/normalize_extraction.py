"""
normalize_extraction.py — 추출기 raw 출력을 통제 어휘에 매핑하거나 REJECT + 커버리지 리포트

전제:
  - controlled_vocabulary.py, vocabulary.yaml, raw_extractions.json 이 같은 폴더에 있다.
  - Pydantic v2, PyYAML 필요. API 키·Neo4j 불필요.

하는 일:
  Phase 2 추출기는 매번 조금씩 다른 type/label 을 뱉는다(Method/Technique/Model,
  Self-RAG/Self-Reflective RAG/SELF-RAG). 그대로 적재하면 그래프가 조각난다.
  이 스크립트는 각 raw 항목을
    - entity: raw_type 을 Entity Type 카탈로그에, raw_label 을 개념 레지스트리에 매핑
    - relation: raw_type 을 Relation Type 카탈로그에 매핑
  하고, 매핑 실패는 통과가 아니라 REJECT 로 격리한다.
  마지막에 "raw 중 몇 %가 어휘에 매핑됐나"를 커버리지 리포트로 출력한다.
  이 리포트가 어휘의 빈틈(신규 후보)을 드러낸다.

산출물:
  매핑 성공 항목의 (concept_id, entity_type / relation type_id) 는
  03(canonical-id-alignment)이 표준 개념·외부 ID로 이어받는 입력이 된다.
"""

from __future__ import annotations

import json
from pathlib import Path

from controlled_vocabulary import ControlledVocabulary, load_vocabulary

RAW_PATH = Path(__file__).with_name("raw_extractions.json")


def normalize_entities(vocab: ControlledVocabulary, entities: list[dict]) -> dict:
    """엔티티 raw 를 (타입, 라벨) 두 축으로 매핑한다.

    타입과 라벨이 둘 다 매핑돼야 accepted. 하나라도 실패하면 rejected.
    """
    accepted, rejected = [], []
    for e in entities:
        t = vocab.resolve_entity_type(e["raw_type"])
        c = vocab.resolve(e["raw_label"])
        if t.resolved and c.resolved:
            accepted.append({
                "raw_type": e["raw_type"], "raw_label": e["raw_label"],
                "entity_type": t.type_id, "concept_id": c.concept_id,
                "preferred_label": c.preferred_label,
            })
        else:
            reasons = []
            if not t.resolved:
                reasons.append(f"type:{t.reason}")
            if not c.resolved:
                reasons.append(f"label:{c.reason}")
            rejected.append({
                "raw_type": e["raw_type"], "raw_label": e["raw_label"],
                "reasons": reasons,
            })
    return {"accepted": accepted, "rejected": rejected}


def normalize_relations(vocab: ControlledVocabulary, relations: list[dict]) -> dict:
    """관계 raw_type 을 Relation Type 카탈로그에 매핑한다."""
    accepted, rejected = [], []
    for r in relations:
        res = vocab.resolve_relation_type(r["raw_type"])
        if res.resolved:
            accepted.append({"raw_type": r["raw_type"],
                             "relation_type": res.type_id, "label": res.label})
        else:
            rejected.append({"raw_type": r["raw_type"], "reason": res.reason})
    return {"accepted": accepted, "rejected": rejected}


def coverage(result: dict) -> tuple[int, int, float]:
    """(accepted, total, 비율%) 반환."""
    a = len(result["accepted"])
    total = a + len(result["rejected"])
    pct = (a / total * 100) if total else 0.0
    return a, total, pct


def main() -> None:
    vocab = load_vocabulary()
    raw = json.loads(RAW_PATH.read_text(encoding="utf-8"))

    ent = normalize_entities(vocab, raw["entities"])
    rel = normalize_relations(vocab, raw["relations"])

    print("== 엔티티 매핑 ==")
    for a in ent["accepted"]:
        print(f"  OK     {a['raw_type']:12}/{a['raw_label']:22} "
              f"-> :{a['entity_type']:12} concept={a['concept_id']}")
    for r in ent["rejected"]:
        print(f"  REJECT {r['raw_type']:12}/{r['raw_label']:22} -> {'; '.join(r['reasons'])}")

    print("\n== 관계 매핑 ==")
    for a in rel["accepted"]:
        print(f"  OK     {a['raw_type']:16} -> {a['label']} ({a['relation_type']})")
    for r in rel["rejected"]:
        print(f"  REJECT {r['raw_type']:16} -> {r['reason']}")

    ea, et, ep = coverage(ent)
    ra, rt, rp = coverage(rel)
    print("\n== 커버리지 리포트 ==")
    print(f"  엔티티: {ea}/{et} 매핑  ({ep:.0f}%)")
    print(f"  관계  : {ra}/{rt} 매핑  ({rp:.0f}%)")
    print("  REJECT 된 raw 는 어휘의 빈틈이다 — 신규 개념/타입 후보로 리뷰 큐에 올린다.")

    # 자체검증(assert) — 완료 기준을 코드로 못박는다.
    accepted_concepts = {a["concept_id"] for a in ent["accepted"]}
    assert "self-rag" in accepted_concepts        # 표기 3종이 하나로 접힘
    assert "graphrag" in accepted_concepts         # 한글 약어 변형도 매핑
    rej_labels = {r["raw_label"] for r in ent["rejected"]}
    assert "FancyRAG" in rej_labels                # 미등록 개념 REJECT
    assert "Akari Asai" in rej_labels              # 미등록 타입(Person) REJECT
    accepted_rels = {a["raw_type"] for a in rel["accepted"]}
    assert "USE" in accepted_rels                  # alias 매핑
    rej_rels = {r["raw_type"] for r in rel["rejected"]}
    assert "MENTIONS" in rej_rels and "CITES" in rej_rels  # 미등록 관계 REJECT
    assert 0.0 < ep < 100.0                        # 커버리지가 0도 100도 아님(빈틈 존재)
    print("\n[assert] 모든 자체검증 통과")


if __name__ == "__main__":
    main()
