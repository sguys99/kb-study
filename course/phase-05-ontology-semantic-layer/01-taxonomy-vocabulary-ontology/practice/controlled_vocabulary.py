"""
controlled_vocabulary.py — 통제 어휘(Controlled Vocabulary)

전제:
  - Pydantic v2 필요(requirements.txt). API 키·Neo4j 불필요. 로컬에서 돈다.

배우는 것:
  통제 어휘는 "허용된 표준 용어(preferred_label) + 그 동의어(alt_labels)" 집합이다.
  concept_id 는 표준 식별자(Canonical ID)의 씨앗이다.
  증분 적재로 "Self-RAG", "Self-Reflective RAG", "SELF-RAG" 가 뒤섞여 들어와도
  resolve() 가 전부 하나의 concept_id('self-rag')로 정규화한다.
  어휘에 없는 용어는 통과시키지 않고 flag/reject 한다 — 이게 통제(controlled)의 핵심.

주의:
  여기서는 개념 씨앗까지만 만든다. concept_id 를 실제 Neo4j 노드에 붙이고
  외부 온톨로지에 정렬(alignment)하는 일은 5/03(canonical-id-alignment)에서 한다.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class ConceptEntry(BaseModel):
    """통제 어휘의 한 항목. 표준 표기 1개 + 동의어 N개."""

    concept_id: str = Field(..., description="표준 식별자(Canonical ID) 씨앗. 소문자-하이픈.")
    preferred_label: str = Field(..., description="표준 표기(딱 하나).")
    alt_labels: list[str] = Field(default_factory=list, description="동의어·표기 변형.")

    @field_validator("concept_id")
    @classmethod
    def _id_is_slug(cls, v: str) -> str:
        # concept_id 는 소문자·숫자·하이픈만. 표기 흔들림을 애초에 막는다.
        if not v or any(c.isspace() or c.isupper() for c in v):
            raise ValueError(f"concept_id 는 소문자-하이픈 슬러그여야 한다: {v!r}")
        return v


def _normalize(term: str) -> str:
    """비교용 정규화 키. 대소문자·앞뒤 공백·연속 공백·하이픈 차이를 흡수한다.

    'Self-Reflective RAG', 'self reflective rag', 'SELF-REFLECTIVE  RAG'
    -> 모두 같은 키 'self reflective rag' 로 접힌다.
    """
    return " ".join(term.replace("-", " ").split()).lower()


# 코퍼스(AI/LLM 기술 문서)용 mini 통제 어휘.
# 실제 코퍼스에서 관측된 표기 변형을 alt_labels 에 모았다.
VOCABULARY: list[ConceptEntry] = [
    ConceptEntry(
        concept_id="self-rag",
        preferred_label="Self-RAG",
        alt_labels=["Self-Reflective RAG", "SELF-RAG", "self rag", "SelfRAG"],
    ),
    ConceptEntry(
        concept_id="crag",
        preferred_label="CRAG",
        alt_labels=["Corrective RAG", "Corrective Retrieval-Augmented Generation"],
    ),
    ConceptEntry(
        concept_id="graphrag",
        preferred_label="GraphRAG",
        alt_labels=["Graph RAG", "graph-rag", "그래프RAG"],
    ),
    ConceptEntry(
        concept_id="hybrid-rag",
        preferred_label="Hybrid RAG",
        alt_labels=["Hybrid Search RAG", "hybrid retrieval"],
    ),
]


class ResolveResult(BaseModel):
    """resolve() 결과. 정규화 성공/실패를 명시적으로 담는다."""

    input_term: str
    resolved: bool
    concept_id: str | None = None
    preferred_label: str | None = None
    matched_on: str | None = None  # "preferred" | "alt" | None
    reason: str | None = None      # 실패 사유(REJECT)


def _build_index(vocab: list[ConceptEntry]) -> dict[str, tuple[ConceptEntry, str]]:
    """정규화 키 -> (항목, 매칭종류) 색인. 표준·동의어 모두 등록한다."""
    index: dict[str, tuple[ConceptEntry, str]] = {}
    # 동의어 먼저 등록하고 표준을 나중에 덮어써, 같은 키면 "preferred" 가 이긴다.
    for entry in vocab:
        for alt in entry.alt_labels:
            index[_normalize(alt)] = (entry, "alt")
    for entry in vocab:
        index[_normalize(entry.preferred_label)] = (entry, "preferred")
    return index


_INDEX = _build_index(VOCABULARY)


def resolve(term: str) -> ResolveResult:
    """자유 표기 term 을 표준 concept_id 로 정규화한다.

    - 표준/동의어 어느 쪽에 맞아도 같은 concept_id 를 돌려준다.
    - 어휘에 없으면 resolved=False + reason 으로 REJECT(통과시키지 않는다).
    """
    key = _normalize(term)
    hit = _INDEX.get(key)
    if hit is None:
        return ResolveResult(
            input_term=term,
            resolved=False,
            reason="NOT_IN_VOCABULARY: 통제 어휘에 없는 용어(신규 후보로 검토 필요)",
        )
    entry, matched_on = hit
    return ResolveResult(
        input_term=term,
        resolved=True,
        concept_id=entry.concept_id,
        preferred_label=entry.preferred_label,
        matched_on=matched_on,
    )


if __name__ == "__main__":
    samples = [
        "Self-RAG",            # 표준 그대로
        "Self-Reflective RAG",  # 동의어 → 표준으로 접혀야 함
        "SELF-RAG",            # 대문자 변형
        "self rag",            # 하이픈 없는 변형
        "Corrective RAG",      # crag 동의어
        "그래프RAG",            # graphrag 동의어
        "FancyRAG",            # 어휘에 없음 → REJECT
    ]
    print("== controlled vocabulary resolve ==")
    for term in samples:
        r = resolve(term)
        if r.resolved:
            print(f"  OK     {term!r:26} -> {r.concept_id:12} "
                  f"({r.preferred_label}, matched={r.matched_on})")
        else:
            print(f"  REJECT {term!r:26} -> {r.reason}")
