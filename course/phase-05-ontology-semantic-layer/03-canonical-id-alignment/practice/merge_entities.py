"""
merge_entities.py — Entity Resolution 산출(여러 raw 노드) → Canonical ID 로 병합

전제:
  - canonical_id.py, controlled_vocabulary.py, vocabulary.yaml, raw_nodes.json 필요.
  - API 키·Neo4j 불필요. 로컬에서 돈다.

무엇을 하나:
  Phase 2 Entity Resolution 을 거쳐도 같은 실체가 표기·출처가 달라 여러 노드로 남는다
  (Self-RAG / Self-Reflective RAG / SELF-RAG 는 한 실체). 02 의 resolve() 로 각 raw 노드를
  concept_id 로 접고, 03 의 canonical id 로 "하나의 표준 노드"에 병합(merge)한다.
  병합하면서 각 raw 표기·출처를 alias 테이블에 보존한다 — 프로비넌스(어디서 왔나)를 잃지 않는다.

핵심:
  - 병합 후에도 raw 표기를 버리지 않는다. "n001=Self-RAG, n003=SELF-RAG 가 이 canonical 로 접혔다"
    는 근거가 있어야 나중에 감사(audit)·롤백이 된다.
  - resolve 안 되는 raw 노드(FancyRAG)는 병합하지 않고 unresolved 로 따로 남긴다(신규 후보).
"""

from __future__ import annotations

import json
from pathlib import Path

from canonical_id import CanonicalRegistry, issue_from_vocabulary
from controlled_vocabulary import ControlledVocabulary, load_vocabulary
from pydantic import BaseModel, Field

RAW_PATH = Path(__file__).with_name("raw_nodes.json")
VOCAB_PATH = Path(__file__).with_name("vocabulary.yaml")


class AliasEntry(BaseModel):
    """canonical 노드로 접힌 raw 표기 하나의 근거."""

    raw_id: str
    surface: str          # 원래 표기
    raw_type: str         # 아직 정리 전 타입 표기
    source_doc: str       # 출처(프로비넌스)


class CanonicalNode(BaseModel):
    """병합 결과 노드 하나. 표준 ID + 병합된 raw 들의 alias 근거."""

    canonical_id: str
    concept_id: str
    preferred_label: str
    entity_type: str
    aliases: list[AliasEntry] = Field(default_factory=list)

    @property
    def merged_count(self) -> int:
        return len(self.aliases)


class MergeResult(BaseModel):
    nodes: list[CanonicalNode]
    unresolved: list[AliasEntry]  # 어휘에 없어 병합 못 한 raw(신규 후보)

    @property
    def raw_total(self) -> int:
        return sum(n.merged_count for n in self.nodes) + len(self.unresolved)


def merge_raw_nodes(
    raw_nodes: list[dict],
    vocab: ControlledVocabulary,
    registry: CanonicalRegistry,
) -> MergeResult:
    """raw 노드들을 concept_id 로 resolve → canonical id 로 묶는다."""
    # canonical_id -> CanonicalNode 를 지연 생성
    bucket: dict[str, CanonicalNode] = {}
    unresolved: list[AliasEntry] = []

    for raw in raw_nodes:
        alias = AliasEntry(
            raw_id=raw["raw_id"],
            surface=raw["surface"],
            raw_type=raw["raw_type"],
            source_doc=raw["source_doc"],
        )
        res = vocab.resolve(raw["surface"])
        if not res.resolved:
            unresolved.append(alias)
            continue

        rec = registry.get(res.concept_id)  # 발급된 canonical 레코드
        assert rec is not None  # 어휘에 있으면 canonical 도 발급돼 있다
        node = bucket.get(rec.canonical_id)
        if node is None:
            node = CanonicalNode(
                canonical_id=rec.canonical_id,
                concept_id=rec.concept_id,
                preferred_label=rec.preferred_label,
                entity_type=rec.entity_type,
            )
            bucket[rec.canonical_id] = node
        node.aliases.append(alias)

    # 결정론적 순서로 정렬(concept_id 기준)
    nodes = sorted(bucket.values(), key=lambda n: n.concept_id)
    return MergeResult(nodes=nodes, unresolved=unresolved)


if __name__ == "__main__":
    vocab = load_vocabulary(VOCAB_PATH)
    registry = issue_from_vocabulary(vocab)
    raw = json.loads(RAW_PATH.read_text(encoding="utf-8"))["nodes"]

    result = merge_raw_nodes(raw, vocab, registry)

    print(f"== 병합 결과 ==  raw {result.raw_total}개 -> "
          f"canonical {len(result.nodes)}개 + unresolved {len(result.unresolved)}개")
    for node in result.nodes:
        surfaces = ", ".join(a.surface for a in node.aliases)
        print(f"\n  {node.canonical_id}")
        print(f"    preferred : {node.preferred_label} [{node.entity_type}]")
        print(f"    merged {node.merged_count}건: {surfaces}")

    if result.unresolved:
        print("\n== unresolved(신규 후보) ==")
        for a in result.unresolved:
            print(f"  {a.raw_id} {a.surface!r} ({a.source_doc}) — 어휘에 없음")

    # 자체검증 — 완료 기준을 코드로 못박는다.
    by_cid = {n.concept_id: n for n in result.nodes}

    # 1) Self-RAG 표기 3종(n001/n002/n003)이 하나의 canonical 로 병합된다.
    self_rag = by_cid["self-rag"]
    assert self_rag.canonical_id == "urn:kb:concept:self-rag"
    assert self_rag.merged_count == 3
    assert {a.raw_id for a in self_rag.aliases} == {"n001", "n002", "n003"}

    # 2) 병합해도 raw 표기·출처(프로비넌스)가 보존된다.
    assert {a.surface for a in self_rag.aliases} == {"Self-RAG", "Self-Reflective RAG", "SELF-RAG"}
    assert "arxiv:2310.11511" in {a.source_doc for a in self_rag.aliases}

    # 3) 그래프RAG(한글) + Graph RAG 가 graphrag 로 함께 접힌다.
    graphrag = by_cid["graphrag"]
    assert {a.surface for a in graphrag.aliases} == {"Graph RAG", "그래프RAG"}

    # 4) FancyRAG 는 병합되지 않고 unresolved 로 남는다.
    assert any(a.surface == "FancyRAG" for a in result.unresolved)
    assert all(a.surface != "FancyRAG"
               for n in result.nodes for a in n.aliases)

    # 5) raw 총합이 보존된다(병합 + unresolved = 입력 개수).
    assert result.raw_total == len(raw)

    print("\n[assert] 모든 자체검증 통과")
