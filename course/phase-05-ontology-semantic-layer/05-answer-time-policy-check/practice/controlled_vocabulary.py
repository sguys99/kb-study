"""
controlled_vocabulary.py — 정식 통제 어휘(Controlled Vocabulary) 로더 + 검증 + resolve

전제:
  - Pydantic v2, PyYAML 필요(requirements.txt). API 키·Neo4j 불필요. 로컬에서 돈다.
  - 같은 폴더의 vocabulary.yaml 을 읽는다.

01 대비 무엇이 달라졌나:
  - 01: 어휘를 파이썬 리터럴(VOCABULARY 리스트)로 하드코딩했다.
  - 02: 어휘를 vocabulary.yaml(데이터 파일)로 분리하고, Entity Type 카탈로그 +
        Relation Type 카탈로그 + 개념 레지스트리(definition 포함)를 함께 담는다.
        Pydantic 로더가 로드 시점에 규약(슬러그 형식·중복 금지·타입 참조 무결성)을 강제한다.
  - 정규화(normalize)가 더 세졌다: 하이픈·언더스코어·공백·대소문자에 더해
    RAG 같은 약어 표기 흔들림(Graph RAG / graph-rag / 그래프RAG)까지 흡수한다.

산출물의 쓰임:
  - concept_id 는 03(canonical-id-alignment)이 외부 ID(위키데이터 등)에 정렬할 씨앗이다.
  - Entity/Relation Type 카탈로그는 normalize_extraction.py 가 raw 추출 결과를
    "매핑하거나 REJECT" 하는 기준으로 쓴다.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

VOCAB_PATH = Path(__file__).with_name("vocabulary.yaml")

_SLUG_MSG = "id/concept_id 는 소문자·숫자·하이픈 슬러그여야 한다"


def _is_slug(v: str) -> bool:
    """소문자·숫자·하이픈만 허용. 표기 흔들림을 id 단계에서 막는다."""
    return bool(v) and all(c.islower() or c.isdigit() or c == "-" for c in v)


# --------------------------------------------------------------------------- #
# 스키마 — YAML 한 항목이 아래 모델로 강제된다.
# --------------------------------------------------------------------------- #
class EntityType(BaseModel):
    id: str = Field(..., description="슬러그 id(예: method)")
    label: str = Field(..., description="Neo4j 라벨 표기(예: Method)")
    definition: str = ""
    alt_labels: list[str] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def _slug(cls, v: str) -> str:
        if not _is_slug(v):
            raise ValueError(f"{_SLUG_MSG}: {v!r}")
        return v


class RelationType(BaseModel):
    id: str
    label: str = Field(..., description="관계 타입 표기(예: USES)")
    definition: str = ""
    domain: str | None = None  # 참고용. 본격 검증은 5/04 SHACL.
    range: str | None = None
    alt_labels: list[str] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def _slug(cls, v: str) -> str:
        if not _is_slug(v):
            raise ValueError(f"{_SLUG_MSG}: {v!r}")
        return v


class ConceptEntry(BaseModel):
    concept_id: str
    entity_type: str = Field(..., description="entity_types 의 id 를 참조")
    preferred_label: str
    alt_labels: list[str] = Field(default_factory=list)
    definition: str = ""
    # 05(answer-time)에서 추가한 필드. 개념의 수명주기 상태를 담는다.
    #   active(기본) : 정상. 답변에 인용 가능.
    #   deprecated   : 폐기된 개념. 어휘엔 남기되 답변 시점 semantic 게이트가 배제한다.
    # SKOS 의 concept 상태(예: skos:Concept 에 부여하는 상태 속성)에 대응한다.
    status: str = "active"

    @field_validator("concept_id")
    @classmethod
    def _slug(cls, v: str) -> str:
        if not _is_slug(v):
            raise ValueError(f"{_SLUG_MSG}: {v!r}")
        return v


# --------------------------------------------------------------------------- #
# 정규화 — 비교용 키. 01보다 흡수 범위를 넓혔다.
# --------------------------------------------------------------------------- #
def normalize(term: str) -> str:
    """비교용 정규화 키.

    흡수하는 표기 차이:
      - 대소문자:            'SELF-RAG' == 'self-rag'
      - 하이픈/언더스코어:    'graph-rag' == 'graph_rag' == 'graph rag'
      - 연속·앞뒤 공백:       'Self  RAG ' == 'self rag'
      - 한글 사이에 붙은 약어: '그래프RAG' -> '그래프 rag' (경계 분리)

    'Self-Reflective RAG', 'self reflective rag', 'SELF-REFLECTIVE  RAG'
      -> 모두 'self reflective rag' 로 접힌다.
    """
    s = term.strip().lower()
    # 하이픈·언더스코어를 공백으로
    for ch in ("-", "_", "/"):
        s = s.replace(ch, " ")
    # 한글과 라틴 문자가 맞붙은 경계에 공백을 넣어 '그래프rag' -> '그래프 rag'
    out: list[str] = []
    for i, c in enumerate(s):
        if i > 0:
            prev = s[i - 1]
            hangul_prev = "가" <= prev <= "힣"
            hangul_cur = "가" <= c <= "힣"
            latin = c.isascii() and c.isalnum()
            latin_prev = prev.isascii() and prev.isalnum()
            if (hangul_prev and latin) or (hangul_cur and latin_prev):
                out.append(" ")
        out.append(c)
    s = "".join(out)
    return " ".join(s.split())


class ResolveResult(BaseModel):
    """resolve() 결과. 성공/실패를 명시적으로 담는다."""

    input_term: str
    resolved: bool
    concept_id: str | None = None
    preferred_label: str | None = None
    entity_type: str | None = None
    matched_on: str | None = None  # "preferred" | "alt" | None
    reason: str | None = None      # 실패 사유(REJECT)
    status: str | None = None      # 05: 매칭된 개념의 status(active/deprecated)


class TypeResult(BaseModel):
    """entity/relation 타입 매핑 결과."""

    input_term: str
    resolved: bool
    type_id: str | None = None
    label: str | None = None
    matched_on: str | None = None
    reason: str | None = None


# --------------------------------------------------------------------------- #
# ControlledVocabulary — 로드 + 무결성 검증 + resolve/맵핑을 한 객체로.
# --------------------------------------------------------------------------- #
class ControlledVocabulary(BaseModel):
    version: str
    entity_types: list[EntityType]
    relation_types: list[RelationType]
    concepts: list[ConceptEntry]

    # 내부 색인(직렬화 제외)
    _concept_index: dict[str, tuple[ConceptEntry, str]] = {}
    _etype_index: dict[str, tuple[EntityType, str]] = {}
    _rtype_index: dict[str, tuple[RelationType, str]] = {}

    @model_validator(mode="after")
    def _validate_and_index(self) -> "ControlledVocabulary":
        # 1) id 중복 금지
        self._reject_dupes([e.id for e in self.entity_types], "entity_type.id")
        self._reject_dupes([r.id for r in self.relation_types], "relation_type.id")
        self._reject_dupes([c.concept_id for c in self.concepts], "concept_id")

        # 2) concept.entity_type 이 실제 entity_types 를 참조하는지(무결성)
        etype_ids = {e.id for e in self.entity_types}
        for c in self.concepts:
            if c.entity_type not in etype_ids:
                raise ValueError(
                    f"concept {c.concept_id!r} 의 entity_type={c.entity_type!r} 가 "
                    f"entity_types 카탈로그에 없다"
                )

        # 3) 색인 구축(동의어 먼저 → 표준을 덮어써 preferred 우선)
        self._concept_index = self._build_index(
            self.concepts, lambda c: c.preferred_label, lambda c: c.alt_labels
        )
        self._etype_index = self._build_index(
            self.entity_types, lambda e: e.label, lambda e: e.alt_labels
        )
        self._rtype_index = self._build_index(
            self.relation_types, lambda r: r.label, lambda r: r.alt_labels
        )
        return self

    @staticmethod
    def _reject_dupes(ids: list[str], what: str) -> None:
        seen: set[str] = set()
        for i in ids:
            if i in seen:
                raise ValueError(f"{what} 중복: {i!r}")
            seen.add(i)

    @staticmethod
    def _build_index(items, pref_of, alts_of):
        index: dict[str, tuple[object, str]] = {}
        for it in items:
            for alt in alts_of(it):
                index[normalize(alt)] = (it, "alt")
        for it in items:  # 표준 표기를 나중에 등록 → 충돌 시 preferred 우선
            index[normalize(pref_of(it))] = (it, "preferred")
        return index

    # --- 개념 resolve --------------------------------------------------------
    def resolve(self, term: str) -> ResolveResult:
        """자유 표기 term 을 표준 concept_id 로 정규화한다. 없으면 REJECT."""
        hit = self._concept_index.get(normalize(term))
        if hit is None:
            return ResolveResult(
                input_term=term,
                resolved=False,
                reason="NOT_IN_VOCABULARY: 개념 레지스트리에 없는 용어(신규 후보로 검토)",
            )
        entry, matched_on = hit  # type: ignore[misc]
        return ResolveResult(
            input_term=term,
            resolved=True,
            concept_id=entry.concept_id,
            preferred_label=entry.preferred_label,
            entity_type=entry.entity_type,
            matched_on=matched_on,
            status=entry.status,
        )

    # --- 타입 매핑 -----------------------------------------------------------
    def resolve_entity_type(self, raw: str) -> TypeResult:
        return self._resolve_type(raw, self._etype_index, "ENTITY_TYPE")

    def resolve_relation_type(self, raw: str) -> TypeResult:
        return self._resolve_type(raw, self._rtype_index, "RELATION_TYPE")

    @staticmethod
    def _resolve_type(raw: str, index, kind: str) -> TypeResult:
        hit = index.get(normalize(raw))
        if hit is None:
            return TypeResult(
                input_term=raw,
                resolved=False,
                reason=f"NOT_IN_{kind}_CATALOG: 카탈로그에 없는 타입(REJECT)",
            )
        it, matched_on = hit
        return TypeResult(
            input_term=raw,
            resolved=True,
            type_id=it.id,
            label=it.label,
            matched_on=matched_on,
        )


def load_vocabulary(path: Path = VOCAB_PATH) -> ControlledVocabulary:
    """vocabulary.yaml 을 읽어 검증된 ControlledVocabulary 로 만든다.

    규약 위반(잘못된 슬러그·중복 id·깨진 타입 참조)이 있으면 여기서 예외로 멈춘다.
    """
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return ControlledVocabulary.model_validate(data)


if __name__ == "__main__":
    vocab = load_vocabulary()
    print(f"== 통제 어휘 로드 (version={vocab.version}) ==")
    print(f"  entity types  : {len(vocab.entity_types)}")
    print(f"  relation types: {len(vocab.relation_types)}")
    print(f"  concepts      : {len(vocab.concepts)}")

    print("\n== 개념 resolve ==")
    for term in ["Self-RAG", "Self-Reflective RAG", "SELF-RAG", "self rag",
                 "Corrective RAG", "그래프RAG", "FancyRAG"]:
        r = vocab.resolve(term)
        if r.resolved:
            print(f"  OK     {term!r:22} -> {r.concept_id:12} "
                  f"({r.preferred_label}, type={r.entity_type}, matched={r.matched_on})")
        else:
            print(f"  REJECT {term!r:22} -> {r.reason}")

    print("\n== relation type 매핑 ==")
    for raw in ["USES", "USE", "using", "evaluated on", "PROPOSED_BY", "MENTIONS"]:
        r = vocab.resolve_relation_type(raw)
        if r.resolved:
            print(f"  OK     {raw!r:16} -> {r.label} ({r.type_id}, matched={r.matched_on})")
        else:
            print(f"  REJECT {raw!r:16} -> {r.reason}")

    # 자체검증(assert) — 완료 기준을 코드로 못박는다.
    assert vocab.resolve("Self-Reflective RAG").concept_id == "self-rag"
    assert vocab.resolve("SELF-RAG").concept_id == "self-rag"
    assert vocab.resolve("그래프RAG").concept_id == "graphrag"
    assert vocab.resolve("FancyRAG").resolved is False
    assert vocab.resolve_relation_type("USES").type_id == "uses"
    assert vocab.resolve_relation_type("USE").type_id == "uses"      # alias
    assert vocab.resolve_relation_type("MENTIONS").resolved is False  # 미등록 REJECT
    print("\n[assert] 모든 자체검증 통과")
