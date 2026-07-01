"""
ontology.py — 온톨로지(Ontology): 클래스 + 관계의 domain/range 공리

전제:
  - 순수 파이썬 경로는 외부 의존 없음. rdflib 는 선택(RDFS 트리플 보기용).
  - API 키·Neo4j 불필요. 로컬에서 돈다.

배우는 것:
  온톨로지는 "무엇이 존재하는가(클래스)"에 더해 "관계가 어떤 타입 사이에서만
  성립하는가(domain/range)"라는 의미 규칙(공리)을 담는다.
  예) USES 의 domain 은 Method, range 는 Dataset 이다.
     → (Dataset)-[:USES]->(Method) 트리플은 domain/range 위반으로 REJECT.
  Graph Schema(Phase 2)는 "USES 라는 관계 타입이 있다"까지만 안다.
  누가 주어이고 누가 목적어인지(의미)는 온톨로지가 통제한다.

주의:
  여기서는 domain/range 수준의 가벼운 검사만 한다.
  카디널리티·필수 속성·경로 제약 같은 본격 검증은 SHACL(5/04)에서 다룬다.
"""

from __future__ import annotations

from pydantic import BaseModel

# ---------------------------------------------------------------------------
# 클래스(엔티티 타입) — Phase 2 에서 뽑은 것과 같은 타입.
# ---------------------------------------------------------------------------
CLASSES: set[str] = {"Concept", "Method", "Dataset", "Metric", "Paper"}


class RelationDef(BaseModel):
    """관계 타입 정의. domain=주어 타입, range=목적어 타입."""

    name: str
    domain: str  # 주어(subject)가 가져야 할 클래스
    range: str   # 목적어(object)가 가져야 할 클래스


# 관계별 domain/range 공리. Phase 2 관계 타입에 "의미"를 붙였다.
RELATIONS: dict[str, RelationDef] = {
    "USES":         RelationDef(name="USES",         domain="Method", range="Dataset"),
    "EVALUATED_ON": RelationDef(name="EVALUATED_ON", domain="Method", range="Dataset"),
    "COMPARES":     RelationDef(name="COMPARES",     domain="Method", range="Method"),
    "PART_OF":      RelationDef(name="PART_OF",      domain="Concept", range="Concept"),
    "REPORTS":      RelationDef(name="REPORTS",      domain="Paper",  range="Metric"),
}


class Triple(BaseModel):
    """(subject_label)-[rel]->(object_label) 형태의 그래프 트리플.

    label 은 노드의 클래스(엔티티 타입). Neo4j 라벨과 같은 층위다.
    """

    subject_label: str
    rel: str
    object_label: str

    def __str__(self) -> str:
        return f"(:{self.subject_label})-[:{self.rel}]->(:{self.object_label})"


class Violation(BaseModel):
    """온톨로지 위반 1건. reject reason 을 담는다."""

    triple: str
    code: str    # UNKNOWN_CLASS | UNKNOWN_RELATION | DOMAIN_MISMATCH | RANGE_MISMATCH
    reason: str


def check_triple(t: Triple) -> list[Violation]:
    """트리플 하나를 온톨로지 공리로 검사한다. 위반이 없으면 빈 리스트."""
    v: list[Violation] = []

    # 1) 클래스가 온톨로지에 정의돼 있는가.
    for label in (t.subject_label, t.object_label):
        if label not in CLASSES:
            v.append(Violation(
                triple=str(t), code="UNKNOWN_CLASS",
                reason=f"온톨로지에 없는 클래스: {label!r}",
            ))

    # 2) 관계가 정의돼 있는가.
    rel_def = RELATIONS.get(t.rel)
    if rel_def is None:
        v.append(Violation(
            triple=str(t), code="UNKNOWN_RELATION",
            reason=f"온톨로지에 없는 관계: {t.rel!r}",
        ))
        return v  # 관계를 모르면 domain/range 를 볼 수 없다.

    # 3) domain(주어 타입) 위반.
    if t.subject_label != rel_def.domain:
        v.append(Violation(
            triple=str(t), code="DOMAIN_MISMATCH",
            reason=f"{t.rel} 의 domain 은 {rel_def.domain} 인데 주어가 {t.subject_label}",
        ))
    # 4) range(목적어 타입) 위반.
    if t.object_label != rel_def.range:
        v.append(Violation(
            triple=str(t), code="RANGE_MISMATCH",
            reason=f"{t.rel} 의 range 는 {rel_def.range} 인데 목적어가 {t.object_label}",
        ))
    return v


# ---------------------------------------------------------------------------
# (선택) 같은 온톨로지를 RDFS 트리플로 — rdflib 있을 때만.
# ---------------------------------------------------------------------------
def build_rdfs_graph():
    """rdflib 로 클래스·관계를 RDFS(rdfs:domain/range)로 선언한다."""
    from rdflib import Graph, Namespace, RDF, RDFS

    EX = Namespace("http://example.org/kb/")
    g = Graph()
    g.bind("ex", EX)
    g.bind("rdfs", RDFS)
    for cls in CLASSES:
        g.add((EX[cls], RDF.type, RDFS.Class))
    for rel in RELATIONS.values():
        g.add((EX[rel.name], RDF.type, RDF.Property))
        g.add((EX[rel.name], RDFS.domain, EX[rel.domain]))
        g.add((EX[rel.name], RDFS.range, EX[rel.range]))
    return g


if __name__ == "__main__":
    triples = [
        Triple(subject_label="Method", rel="USES", object_label="Dataset"),      # OK
        Triple(subject_label="Dataset", rel="USES", object_label="Method"),      # 뒤집힘
        Triple(subject_label="Method", rel="COMPARES", object_label="Method"),   # OK
        Triple(subject_label="Paper", rel="REPORTS", object_label="Dataset"),    # range 위반
        Triple(subject_label="Method", rel="INVENTED_BY", object_label="Paper"), # 관계 없음
        Triple(subject_label="Robot", rel="USES", object_label="Dataset"),       # 클래스 없음
    ]
    print("== ontology domain/range check ==")
    for t in triples:
        violations = check_triple(t)
        if not violations:
            print(f"  OK     {t}")
        else:
            for viol in violations:
                print(f"  REJECT {t}  [{viol.code}] {viol.reason}")

    print("\n== RDFS 트리플(rdflib, 선택) ==")
    try:
        g = build_rdfs_graph()
        print(f"  RDFS 그래프 생성됨 (총 트리플 수: {len(g)})")
    except ImportError:
        print("  rdflib 미설치 — 순수 파이썬 경로만 사용(정상).")
