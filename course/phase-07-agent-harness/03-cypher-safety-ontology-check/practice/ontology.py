"""ontology.py — 허용 온톨로지 로더 + 라벨/관계 정규화. Phase 5 controlled_vocabulary 의 축약 재사용.

ontology_check 도구가 "이 라벨·관계가 스키마상 허용되는가"를 판정하려면, 먼저
'허용 집합'을 로드하고 자유 표기를 표준 label 로 접어야 한다. 그 두 가지를 여기서 한다.

Phase 5 와의 관계:
  - 5/02 controlled_vocabulary.py 의 normalize()·색인 구축·resolve 패턴을 그대로 이었다.
  - 5/04 shapes.yaml 의 domain/range 제약(관계 방향)을 relations 에 흡수했다.
  - 실전에서는 Phase 5 vocabulary.yaml/shapes.yaml 을 로드하면 된다. 여기선 하니스 mock KG 에
    맞춘 ontology.yaml 을 쓴다(라벨·관계 집합이 하니스 그래프와 1:1).

전제: Pydantic v2 + PyYAML(requirements.txt). API 키·Neo4j 불필요. 로컬에서 돈다.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

ONTOLOGY_PATH = Path(__file__).with_name("ontology.yaml")

_SLUG_MSG = "id 는 소문자·숫자·하이픈 슬러그여야 한다"


def _is_slug(v: str) -> bool:
    return bool(v) and all(c.islower() or c.isdigit() or c == "-" for c in v)


def normalize(term: str) -> str:
    """비교용 정규화 키. Phase 5 normalize 의 축약(라벨·관계 표기 흔들림 흡수).

      - 대소문자:          'USES' == 'uses'
      - 하이픈/언더스코어:   'IS_A' == 'is-a' == 'is a'
      - 연속·앞뒤 공백:     'BUILT  ON ' == 'built on'
    """
    s = term.strip().lower()
    for ch in ("-", "_", "/"):
        s = s.replace(ch, " ")
    return " ".join(s.split())


class LabelDef(BaseModel):
    id: str
    label: str = Field(..., description="Neo4j 라벨 표기(예: Method)")
    definition: str = ""
    alt_labels: list[str] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def _slug(cls, v: str) -> str:
        if not _is_slug(v):
            raise ValueError(f"{_SLUG_MSG}: {v!r}")
        return v


class RelationDef(BaseModel):
    id: str
    label: str = Field(..., description="관계 타입 표기(예: USES)")
    definition: str = ""
    domain: str  # 출발 노드 라벨(예: Method)
    range: str   # 도착 노드 라벨(예: Component)
    alt_labels: list[str] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def _slug(cls, v: str) -> str:
        if not _is_slug(v):
            raise ValueError(f"{_SLUG_MSG}: {v!r}")
        return v


class Ontology(BaseModel):
    """허용 라벨·관계 집합 + 방향. 로드 시 무결성 검증, 이후 정규화 조회를 제공한다."""

    version: str
    labels: list[LabelDef]
    relations: list[RelationDef]

    _label_index: dict[str, LabelDef] = {}
    _relation_index: dict[str, RelationDef] = {}

    @model_validator(mode="after")
    def _validate_and_index(self) -> "Ontology":
        # 1) id 중복 금지
        self._reject_dupes([x.id for x in self.labels], "label.id")
        self._reject_dupes([x.id for x in self.relations], "relation.id")

        # 2) 색인 구축(alt 먼저 → 표준 label 을 나중에 덮어써 우선)
        self._label_index = {}
        for lb in self.labels:
            for alt in lb.alt_labels:
                self._label_index[normalize(alt)] = lb
        for lb in self.labels:
            self._label_index[normalize(lb.label)] = lb

        self._relation_index = {}
        for r in self.relations:
            for alt in r.alt_labels:
                self._relation_index[normalize(alt)] = r
        for r in self.relations:
            self._relation_index[normalize(r.label)] = r

        # 3) 관계의 domain/range 가 실제 라벨 집합을 참조하는지(무결성)
        label_names = {lb.label for lb in self.labels}
        for r in self.relations:
            if r.domain not in label_names:
                raise ValueError(f"relation {r.id!r} domain={r.domain!r} 가 labels 에 없다")
            if r.range not in label_names:
                raise ValueError(f"relation {r.id!r} range={r.range!r} 가 labels 에 없다")
        return self

    @staticmethod
    def _reject_dupes(ids: list[str], what: str) -> None:
        seen: set[str] = set()
        for i in ids:
            if i in seen:
                raise ValueError(f"{what} 중복: {i!r}")
            seen.add(i)

    # --- 조회 API (ontology_check 가 쓴다) -----------------------------------
    def allowed_labels(self) -> set[str]:
        return {lb.label for lb in self.labels}

    def allowed_relations(self) -> set[str]:
        return {r.label for r in self.relations}

    def resolve_label(self, raw: str) -> LabelDef | None:
        """자유 표기 라벨을 표준 LabelDef 로 접는다. 없으면 None."""
        return self._label_index.get(normalize(raw))

    def resolve_relation(self, raw: str) -> RelationDef | None:
        """자유 표기 관계 타입을 표준 RelationDef 로 접는다. 없으면 None."""
        return self._relation_index.get(normalize(raw))


def load_ontology(path: Path = ONTOLOGY_PATH) -> Ontology:
    """ontology.yaml 을 읽어 검증된 Ontology 로 만든다. 규약 위반이면 여기서 멈춘다."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return Ontology.model_validate(data)


if __name__ == "__main__":
    onto = load_ontology()
    print(f"== 온톨로지 로드 (version={onto.version}) ==")
    print(f"  허용 라벨   : {sorted(onto.allowed_labels())}")
    print(f"  허용 관계   : {sorted(onto.allowed_relations())}")

    print("\n== 라벨 정규화 ==")
    for raw in ["Method", "method", "Technique", "Dataset"]:
        hit = onto.resolve_label(raw)
        print(f"  {raw!r:12} -> {hit.label if hit else 'REJECT(미등록 라벨)'}")

    print("\n== 관계 정규화 ==")
    for raw in ["USES", "use", "IS_A", "MENTIONS"]:
        hit = onto.resolve_relation(raw)
        print(f"  {raw!r:12} -> {hit.label if hit else 'REJECT(미등록 관계)'}")

    # 자체검증(assert) — 완료 기준을 코드로 못박는다.
    assert onto.resolve_label("Technique").label == "Method"      # alias
    assert onto.resolve_label("Dataset") is None                  # 하니스 스키마에 없음
    assert onto.resolve_relation("USES").label == "USES"
    assert onto.resolve_relation("use").label == "USES"           # alias
    assert onto.resolve_relation("MENTIONS") is None              # 미등록 관계
    print("\n[assert] 온톨로지 자체검증 통과")
