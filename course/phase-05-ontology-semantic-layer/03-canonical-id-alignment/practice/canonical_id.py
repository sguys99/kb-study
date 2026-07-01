"""
canonical_id.py — Canonical ID 발급/관리 (내부 표준 식별자)

전제:
  - Pydantic v2, PyYAML (requirements.txt). API 키·Neo4j 불필요. 로컬에서 돈다.
  - 같은 폴더의 vocabulary.yaml 을 입력으로 받는다(02 산출물을 그대로 복사해 왔다).

02 대비 무엇이 달라졌나 — 여기서부터가 "식별(identity)" 문제다:
  - 02: 표기(label) 표준화 — 자유 표기를 preferred_label 로 접고 resolve() 가 concept_id 를 돌려줬다.
  - 03: 그 concept_id 에 "불변·안정적인 표준 ID(Canonical ID)"를 발급한다.
        표기(label)와 ID 를 분리한다. Self-RAG 라는 표기가 나중에 바뀌어도 URI 는 안 바뀐다.

왜 URI 형태인가:
  - concept_id 'self-rag' 는 우리 레지스트리 안에서만 유일하다. 외부(Neo4j·RDF·다른 팀)와 섞이면
    'self-rag' 라는 짧은 슬러그는 충돌하기 쉽다. 네임스페이스(kb:)를 붙여 전역에서 유일한 URI 로 승격한다.
  - urn:kb:concept:self-rag  형태. 표기가 바뀌어도, 다른 KB 의 self-rag 와도 안 겹친다.

핵심 규칙:
  1) Canonical ID 는 concept_id(슬러그)에서 결정론적으로 파생된다 → 재실행해도 같은 ID.
  2) 한번 발급하면 불변(immutable). 표기가 바뀌어도 ID 는 유지한다.
  3) 발급 시 충돌을 검사한다(같은 URI 를 서로 다른 concept 이 가지면 즉시 실패).
"""

from __future__ import annotations

from pathlib import Path

from controlled_vocabulary import ControlledVocabulary, load_vocabulary, normalize
from pydantic import BaseModel, Field, field_validator

# 내부 네임스페이스. 우리 KB 가 발급하는 개념 URI 의 접두어.
CANONICAL_NS = "urn:kb:concept:"

VOCAB_PATH = Path(__file__).with_name("vocabulary.yaml")


def _is_slug(v: str) -> bool:
    return bool(v) and all(c.islower() or c.isdigit() or c == "-" for c in v)


def slugify(text: str) -> str:
    """자유 표기를 안정적인 슬러그로 정규화한다.

    'Self-Reflective RAG' -> 'self-reflective-rag'
    'GraphRAG'            -> 'graphrag'   (02 normalize 규칙과 일관)
    공백/언더스코어/슬래시 -> 하이픈, 소문자, 앞뒤·연속 하이픈 정리.
    """
    # 02 의 normalize 로 표기 흔들림을 먼저 흡수(대소문자·구분자·한글경계) → 공백을 하이픈으로.
    base = normalize(text).replace(" ", "-")
    # 슬러그에 허용되지 않는 문자 제거(라틴 소문자·숫자·하이픈만 남긴다)
    kept = [c for c in base if c.islower() or c.isdigit() or c == "-"]
    slug = "".join(kept)
    # 연속·앞뒤 하이픈 정리
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-")


def to_canonical_id(concept_id: str) -> str:
    """concept_id(슬러그) -> Canonical URI. 결정론적이라 재실행해도 같은 값."""
    if not _is_slug(concept_id):
        raise ValueError(f"concept_id 는 슬러그여야 한다: {concept_id!r}")
    return f"{CANONICAL_NS}{concept_id}"


class CanonicalRecord(BaseModel):
    """개념 하나의 표준 식별 레코드. 표기와 ID 를 명시적으로 분리해 담는다."""

    concept_id: str
    canonical_id: str            # urn:kb:concept:<slug> — 불변
    preferred_label: str         # 표시용 표기 — 바뀔 수 있다
    entity_type: str
    aliases: list[str] = Field(default_factory=list)  # 이 개념으로 접히는 모든 표기

    @field_validator("concept_id")
    @classmethod
    def _slug(cls, v: str) -> str:
        if not _is_slug(v):
            raise ValueError(f"concept_id 슬러그 위반: {v!r}")
        return v

    @field_validator("canonical_id")
    @classmethod
    def _uri(cls, v: str) -> str:
        if not v.startswith(CANONICAL_NS):
            raise ValueError(f"canonical_id 는 {CANONICAL_NS} 로 시작해야 한다: {v!r}")
        return v


class CanonicalRegistry(BaseModel):
    """Canonical ID 레지스트리. 발급·조회·충돌검사를 한 객체로."""

    records: list[CanonicalRecord]

    # 색인(직렬화 제외)
    _by_concept: dict[str, CanonicalRecord] = {}
    _by_canonical: dict[str, CanonicalRecord] = {}

    def model_post_init(self, __context) -> None:
        self._by_concept = {}
        self._by_canonical = {}
        for rec in self.records:
            # concept_id 충돌
            if rec.concept_id in self._by_concept:
                raise ValueError(f"concept_id 중복 발급: {rec.concept_id!r}")
            # canonical_id 충돌 — 서로 다른 개념이 같은 URI 를 가지면 즉시 실패
            if rec.canonical_id in self._by_canonical:
                other = self._by_canonical[rec.canonical_id]
                raise ValueError(
                    f"canonical_id 충돌: {rec.canonical_id!r} 를 "
                    f"{other.concept_id!r} 와 {rec.concept_id!r} 가 함께 가진다"
                )
            self._by_concept[rec.concept_id] = rec
            self._by_canonical[rec.canonical_id] = rec

    def get(self, concept_id: str) -> CanonicalRecord | None:
        return self._by_concept.get(concept_id)

    def canonical_id_of(self, concept_id: str) -> str | None:
        rec = self._by_concept.get(concept_id)
        return rec.canonical_id if rec else None


def issue_from_vocabulary(vocab: ControlledVocabulary) -> CanonicalRegistry:
    """통제 어휘의 concept 마다 Canonical ID 를 발급한다.

    - concept_id 는 이미 슬러그이므로 그대로 URI 로 승격한다.
    - alias 는 preferred_label + alt_labels 를 합쳐 alias 테이블로 보존한다.
      (나중에 raw 노드를 이 개념으로 merge 할 때, 어떤 표기가 이 canonical 로 접히는지 근거가 된다.)
    """
    records: list[CanonicalRecord] = []
    for c in vocab.concepts:
        aliases = [c.preferred_label, *c.alt_labels]
        records.append(
            CanonicalRecord(
                concept_id=c.concept_id,
                canonical_id=to_canonical_id(c.concept_id),
                preferred_label=c.preferred_label,
                entity_type=c.entity_type,
                aliases=aliases,
            )
        )
    return CanonicalRegistry(records=records)


if __name__ == "__main__":
    vocab = load_vocabulary(VOCAB_PATH)
    reg = issue_from_vocabulary(vocab)

    print(f"== Canonical ID 발급 ({len(reg.records)} concepts) ==")
    for rec in reg.records:
        print(f"  {rec.concept_id:12} -> {rec.canonical_id:28} "
              f"[{rec.entity_type}] aliases={len(rec.aliases)}")

    print("\n== slugify 데모(표기 흔들림 흡수) ==")
    for text in ["Self-Reflective RAG", "GraphRAG", "Corrective  RAG", "그래프RAG"]:
        print(f"  {text!r:22} -> {slugify(text)!r}")

    # 자체검증 — 완료 기준을 코드로 못박는다.
    # 1) resolve 로 얻은 concept_id 가 canonical URI 로 발급된다.
    self_rag_cid = vocab.resolve("Self-Reflective RAG").concept_id
    assert self_rag_cid == "self-rag"
    assert reg.canonical_id_of("self-rag") == "urn:kb:concept:self-rag"

    # 2) 결정론성 — 같은 concept_id 는 재실행해도 같은 URI.
    assert to_canonical_id("self-rag") == to_canonical_id("self-rag")

    # 3) slugify 안정성.
    assert slugify("Self-Reflective RAG") == "self-reflective-rag"
    assert slugify("GraphRAG") == "graphrag"
    assert slugify("그래프RAG") == "rag"  # 한글은 슬러그에서 빠지고 'rag' 만 남는다

    # 4) canonical 충돌 검사가 실제로 작동하는지(같은 URI 두 번 넣으면 실패해야 한다).
    dup = CanonicalRecord(
        concept_id="self-rag", canonical_id="urn:kb:concept:self-rag",
        preferred_label="dup", entity_type="method",
    )
    try:
        CanonicalRegistry(records=[*reg.records, dup])
        raise AssertionError("충돌을 잡지 못했다")
    except ValueError as e:
        assert "중복" in str(e) or "충돌" in str(e)

    print("\n[assert] 모든 자체검증 통과")
