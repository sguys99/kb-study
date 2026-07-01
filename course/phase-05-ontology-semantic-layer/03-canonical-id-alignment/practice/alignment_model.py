"""
alignment_model.py — 정렬 매핑 테이블 Pydantic 검증 + 로더

전제:
  - Pydantic v2, PyYAML. 같은 폴더의 alignment.yaml, vocabulary.yaml 을 읽는다.

무엇을 검증하나:
  1) 스키마 — match_type 은 {exact, close, broad, narrow} 중 하나, confidence 는 0~1.
  2) 무결성 — 모든 매핑의 internal 은 vocabulary.yaml 의 concept_id 여야 한다.
  3) 품질 경고 — 같은 (concept, target_kb) 에 exactMatch 가 2개 이상이면 "모호한 정렬"로 경고.
     (한 개념이 한 외부 KB 에서 동시에 두 개와 "정확히 같다"는 건 보통 데이터 오류다.)

경고 vs 에러:
  - 스키마·무결성 위반은 에러(로드 실패). 데이터가 깨진 것이므로 멈춘다.
  - exactMatch 중복은 경고(로드는 되되 리포트에 남긴다). 사람이 판단할 문제라 자동으로 막지 않는다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from controlled_vocabulary import load_vocabulary
from pydantic import BaseModel, Field, field_validator, model_validator

ALIGN_PATH = Path(__file__).with_name("alignment.yaml")
VOCAB_PATH = Path(__file__).with_name("vocabulary.yaml")

MatchType = Literal["exact", "close", "broad", "narrow"]


class Mapping(BaseModel):
    """내부 concept_id 하나 → 외부 KB 개념 하나의 정렬."""

    internal: str = Field(..., description="vocabulary.yaml 의 concept_id")
    target_kb: str = Field(..., description="external_kbs 의 키(arxiv/wikidata/github ...)")
    external_id: str
    match_type: MatchType
    confidence: float = Field(..., ge=0.0, le=1.0)
    source: str = "manual"
    note: str | None = None


class ExternalKB(BaseModel):
    name: str
    id_pattern: str = ""
    url_template: str = ""


class AlignmentWarning(BaseModel):
    """로드는 됐지만 사람이 봐야 할 품질 이슈."""

    code: str          # 예: "MULTIPLE_EXACT"
    concept_id: str
    target_kb: str
    detail: str


class AlignmentTable(BaseModel):
    version: str
    external_kbs: dict[str, ExternalKB]
    mappings: list[Mapping]

    # 검증 산출(직렬화 제외)
    _warnings: list[AlignmentWarning] = []

    @field_validator("mappings")
    @classmethod
    def _non_empty(cls, v: list[Mapping]) -> list[Mapping]:
        if not v:
            raise ValueError("mappings 가 비었다")
        return v

    @model_validator(mode="after")
    def _check_kb_refs_and_exact_dupes(self) -> "AlignmentTable":
        # target_kb 가 external_kbs 에 선언돼 있는지
        for m in self.mappings:
            if m.target_kb not in self.external_kbs:
                raise ValueError(
                    f"매핑의 target_kb={m.target_kb!r} 가 external_kbs 에 없다 "
                    f"(internal={m.internal})"
                )

        # 같은 (concept, kb) 에 exactMatch 가 2개 이상이면 경고 수집
        warnings: list[AlignmentWarning] = []
        exact_count: dict[tuple[str, str], list[str]] = {}
        for m in self.mappings:
            if m.match_type == "exact":
                exact_count.setdefault((m.internal, m.target_kb), []).append(m.external_id)
        for (cid, kb), ext_ids in exact_count.items():
            if len(ext_ids) > 1:
                warnings.append(
                    AlignmentWarning(
                        code="MULTIPLE_EXACT",
                        concept_id=cid,
                        target_kb=kb,
                        detail=f"exactMatch {len(ext_ids)}개: {ext_ids} — 하나만 남기거나 close 로 낮춰라",
                    )
                )
        self._warnings = warnings
        return self

    @property
    def warnings(self) -> list[AlignmentWarning]:
        return self._warnings


def load_alignment(
    align_path: Path = ALIGN_PATH,
    vocab_path: Path = VOCAB_PATH,
) -> AlignmentTable:
    """alignment.yaml 을 검증해 로드한다.

    vocabulary.yaml 과 교차검증: 모든 internal 이 실제 concept_id 인지 확인(무결성).
    이 무결성 위반은 에러다 — 존재하지 않는 개념에 외부 ID 를 걸면 안 된다.
    """
    vocab = load_vocabulary(vocab_path)
    known = {c.concept_id for c in vocab.concepts}

    data = yaml.safe_load(align_path.read_text(encoding="utf-8"))
    table = AlignmentTable.model_validate(data)

    unknown = sorted({m.internal for m in table.mappings if m.internal not in known})
    if unknown:
        raise ValueError(
            f"alignment 의 internal 이 concept_id 카탈로그에 없다(무결성 위반): {unknown}"
        )
    return table


if __name__ == "__main__":
    table = load_alignment()
    print(f"== 정렬 테이블 로드 (version={table.version}) ==")
    print(f"  external KBs : {list(table.external_kbs)}")
    print(f"  mappings     : {len(table.mappings)}")

    print("\n== 매핑 목록 ==")
    for m in table.mappings:
        print(f"  {m.internal:12} -[{m.match_type:6}]-> {m.target_kb:9} "
              f"{m.external_id:16} (conf={m.confidence}, src={m.source})")

    print("\n== 품질 경고 ==")
    if table.warnings:
        for w in table.warnings:
            print(f"  [{w.code}] {w.concept_id}/{w.target_kb}: {w.detail}")
    else:
        print("  (경고 없음)")

    # 자체검증 — 정상 데이터는 경고가 없어야 한다.
    assert table.warnings == [], "기본 alignment.yaml 에는 경고가 없어야 한다"

    # confidence 범위 검증이 실제로 막는지.
    try:
        Mapping(internal="x", target_kb="arxiv", external_id="1",
                match_type="exact", confidence=1.5)
        raise AssertionError("confidence 범위 검증 실패")
    except Exception as e:
        assert "less than or equal to 1" in str(e) or "le" in str(e).lower()

    # match_type Literal 검증.
    try:
        Mapping(internal="x", target_kb="arxiv", external_id="1",
                match_type="samesame", confidence=1.0)  # type: ignore[arg-type]
        raise AssertionError("match_type 검증 실패")
    except Exception:
        pass

    # exactMatch 2건을 인위로 넣으면 경고가 뜨는지.
    dupe = table.model_copy(deep=True)
    dupe.mappings.append(
        Mapping(internal="self-rag", target_kb="arxiv", external_id="9999.99999",
                match_type="exact", confidence=0.5)
    )
    revalidated = AlignmentTable.model_validate(dupe.model_dump())
    assert any(w.code == "MULTIPLE_EXACT" and w.concept_id == "self-rag"
               for w in revalidated.warnings), "exactMatch 중복 경고가 떠야 한다"

    print("\n[assert] 모든 자체검증 통과")
