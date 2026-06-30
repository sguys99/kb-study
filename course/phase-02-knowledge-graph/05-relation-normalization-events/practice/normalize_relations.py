"""normalize_relations.py — 관계 타입 동의어 정규화 + 방향 정규화 + dedup.

LLM 추출은 같은 의미를 매번 다른 술어로 찍는다. 04 까지 와도 type 은 여전히
표면형(USES/UTILIZES/USED_BY/COMPARED_WITH ...)이다. 이 모듈이 마지막 정제다.

세 가지를 한다.
  1) 동의어 정규화 : surface predicate → vocab canonical type (relation_vocab.yaml).
                     미등록 술어는 reject 로 분리.
  2) 방향 정규화   : symmetric → (head,tail) 정렬 / asymmetric inverse → canonical 방향 flip.
                     self-loop(head==tail) 는 reject.
  3) dedup         : 정규화 후 같은 (head, type, tail) 을 한 엣지로 합치되 provenance 는 리스트로 보존.

전제: pyyaml + pydantic. 네트워크·API 키 불필요. 결정적(같은 입력 → 같은 출력).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from schema_adapter import NormalizedRelation, Provenance, Relation

HERE = Path(__file__).resolve().parent
VOCAB_PATH = HERE / "relation_vocab.yaml"


@dataclass
class RelationVocab:
    """relation_vocab.yaml 을 조회하기 쉬운 형태로 펼친 것."""

    # surface predicate(대문자) → canonical type
    synonym_to_canonical: dict[str, str] = field(default_factory=dict)
    # canonical type → symmetry("symmetric"|"asymmetric")
    symmetry: dict[str, str] = field(default_factory=dict)
    # canonical type → inverse canonical type(있으면)
    inverse: dict[str, str] = field(default_factory=dict)
    # flip 후 최종으로 살릴 방향(canonical_directions)
    canonical_directions: set[str] = field(default_factory=set)

    @classmethod
    def load(cls, path: Path = VOCAB_PATH) -> "RelationVocab":
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        v = cls()
        for canon, spec in data["relations"].items():
            v.symmetry[canon] = spec["symmetry"]
            if spec.get("inverse"):
                v.inverse[canon] = spec["inverse"]
            for syn in spec["synonyms"]:
                v.synonym_to_canonical[syn.upper()] = canon
        v.canonical_directions = set(data.get("canonical_directions", []))
        return v

    def canonical_type(self, surface: str) -> str | None:
        """표면형 술어 → canonical type. 미등록이면 None."""
        return self.synonym_to_canonical.get(surface.upper())


def _normalize_direction(
    rel: Relation, canon_type: str, vocab: RelationVocab
) -> tuple[str, str, str]:
    """방향을 통일한다. (head, canonical_type, tail) 를 돌려준다.

    - symmetric  : (head,tail) 을 이름순 정렬 → A~B 와 B~A 가 같은 키로 모인다.
    - asymmetric : 들어온 type 이 inverse 짝꿍(canonical_directions 에 없는 쪽)이면
                   head/tail 을 뒤집고 type 을 짝꿍의 canonical 방향으로 바꾼다.
                   예: Neo4j-[USED_BY]->LightRAG  →  LightRAG-[USES]->Neo4j
    """
    head, tail = rel.head, rel.tail
    symmetry = vocab.symmetry.get(canon_type, "asymmetric")

    if symmetry == "symmetric":
        # 정렬해 canonical 순서로. 대칭이라 head/tail 의미 구분이 없다.
        a, b = sorted([head, tail])
        return a, canon_type, b

    # asymmetric: canonical_directions 에 없는 타입이면 inverse 로 flip.
    final_type = canon_type
    if canon_type not in vocab.canonical_directions and canon_type in vocab.inverse:
        final_type = vocab.inverse[canon_type]  # 짝꿍의 canonical 방향
        head, tail = tail, head                 # 방향도 뒤집는다
    return head, final_type, tail


@dataclass
class NormalizeResult:
    normalized: list[NormalizedRelation]
    rejected: list[dict]  # {head,type,tail,reason,provenance}


def normalize_relations(
    relations: list[Relation], vocab: RelationVocab
) -> NormalizeResult:
    """동의어 정규화 → 방향 정규화 → dedup. reject 는 따로 모은다."""
    rejected: list[dict] = []
    # dedup 버킷: (head, type, tail) → NormalizedRelation
    bucket: dict[tuple[str, str, str], NormalizedRelation] = {}

    for rel in relations:
        # 1) 동의어 정규화. 미등록 술어는 reject.
        canon_type = vocab.canonical_type(rel.type)
        if canon_type is None:
            rejected.append(_reject(rel, "vocab 미등록 술어"))
            continue

        # 2) 방향 정규화. self-loop 는 reject.
        head, final_type, tail = _normalize_direction(rel, canon_type, vocab)
        if head == tail:
            rejected.append(_reject(rel, "self-loop(head==tail)"))
            continue

        symmetry = vocab.symmetry.get(final_type, "asymmetric")

        # 3) dedup + provenance 누적.
        key = (head, final_type, tail)
        if key in bucket:
            bucket[key].provenances.append(rel.provenance)
        else:
            bucket[key] = NormalizedRelation(
                head=head,
                type=final_type,
                tail=tail,
                direction=symmetry,
                provenances=[rel.provenance],
            )

    return NormalizeResult(normalized=list(bucket.values()), rejected=rejected)


def _reject(rel: Relation, reason: str) -> dict:
    """reject 한 줄을 만든다. 무엇이 왜 빠졌는지 근거까지 보존(2/06 품질 게이트로)."""
    return {
        "head": rel.head,
        "type": rel.type,
        "tail": rel.tail,
        "reason": reason,
        "provenance": rel.provenance.model_dump(),
    }
