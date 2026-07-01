"""
schema_vs_semantic.py — Graph Schema(구조) vs 의미 계층(Taxonomy·Vocabulary·Ontology)

전제:
  - 같은 폴더의 controlled_vocabulary.py / ontology.py 를 import 한다.
  - Pydantic v2 필요. API 키·Neo4j 불필요. 로컬에서 돈다.

이 파일이 토픽의 결론이다.
  Phase 2 Graph Schema 는 "라벨·관계 타입이 등록돼 있는가"라는 구조만 본다.
  그래서 구조는 멀쩡하지만 의미가 틀린 트리플을 그대로 통과시킨다.
  같은 트리플을 의미 계층(어휘 정규화 + domain/range 공리)에 통과시키면 잡힌다.
  "Neo4j 라벨만 맞추면 된다"가 왜 부족한지를 대비 출력으로 보여준다.
"""

from __future__ import annotations

from pydantic import BaseModel

from controlled_vocabulary import resolve
from ontology import Triple, check_triple


# ---------------------------------------------------------------------------
# Phase 2 스타일 LPG Graph Schema — 라벨 집합 + 관계 타입 집합만 안다.
#   (구조만 정의. 어떤 라벨끼리 어떤 관계가 되는지는 강제하지 않는다.)
# ---------------------------------------------------------------------------
NODE_LABELS: set[str] = {"Concept", "Method", "Dataset", "Metric", "Paper"}
REL_TYPES: set[str] = {"USES", "EVALUATED_ON", "COMPARES", "PART_OF", "REPORTS"}


class SchemaResult(BaseModel):
    passed: bool
    reason: str


def schema_check(t: Triple) -> SchemaResult:
    """Graph Schema 검사: 라벨과 관계 타입이 '등록된 것'이기만 하면 통과."""
    if t.subject_label not in NODE_LABELS:
        return SchemaResult(passed=False, reason=f"미등록 라벨: {t.subject_label}")
    if t.object_label not in NODE_LABELS:
        return SchemaResult(passed=False, reason=f"미등록 라벨: {t.object_label}")
    if t.rel not in REL_TYPES:
        return SchemaResult(passed=False, reason=f"미등록 관계 타입: {t.rel}")
    return SchemaResult(passed=True, reason="라벨·관계 타입 모두 등록됨")


def semantic_check(t: Triple) -> tuple[bool, list[str]]:
    """의미 계층 검사: domain/range 공리(온톨로지)로 트리플의 '의미'를 본다."""
    violations = check_triple(t)
    reasons = [f"[{v.code}] {v.reason}" for v in violations]
    return (len(violations) == 0, reasons)


# ---------------------------------------------------------------------------
# 대비 케이스 — 구조는 통과하지만 의미가 틀린 사례를 섞는다.
# ---------------------------------------------------------------------------
CASES: list[Triple] = [
    # 1) 완전 정상: 구조 OK, 의미 OK
    Triple(subject_label="Method", rel="USES", object_label="Dataset"),
    # 2) 방향 뒤집힘: 라벨·관계는 등록돼 있어 구조는 통과, 의미는 domain/range 위반
    Triple(subject_label="Dataset", rel="USES", object_label="Method"),
    # 3) range 오류: Paper-REPORTS-Dataset. 구조 통과, 의미는 range 위반(REPORTS→Metric)
    Triple(subject_label="Paper", rel="REPORTS", object_label="Dataset"),
]


def demo_schema_vs_semantic() -> None:
    print("== Graph Schema vs 의미 계층(온톨로지) 대비 ==")
    print(f"{'트리플':42} {'Schema':>8} {'Semantic':>10}")
    print("-" * 64)
    for t in CASES:
        s = schema_check(t)
        ok_sem, reasons = semantic_check(t)
        s_mark = "PASS" if s.passed else "FAIL"
        sem_mark = "PASS" if ok_sem else "REJECT"
        print(f"{str(t):42} {s_mark:>8} {sem_mark:>10}")
        if s.passed and not ok_sem:
            for r in reasons:
                print(f"    └─ Schema는 통과, 의미 계층이 잡음: {r}")


def demo_vocab_gap() -> None:
    """어휘(Vocabulary) 축의 사각지대: 라벨은 맞지만 비표준 용어."""
    print("\n== Graph Schema vs 통제 어휘 대비 ==")
    # 노드 라벨은 Method 로 정상이라 Graph Schema 관점에선 문제가 없다.
    # 하지만 노드가 담은 이름 값은 표기가 흔들린다.
    node_names = ["Self-RAG", "SELF-RAG", "Self-Reflective RAG", "FancyRAG"]
    for name in node_names:
        r = resolve(name)
        # Graph Schema 는 라벨(:Method)만 보므로 이름 값은 검사 범위 밖 → 항상 통과로 간주.
        schema_view = "PASS(:Method 라벨만 봄)"
        if r.resolved:
            vocab_view = f"정규화 -> {r.concept_id} ({r.preferred_label})"
        else:
            vocab_view = f"REJECT ({r.reason})"
        print(f"  name={name!r:24} | Schema: {schema_view} | Vocab: {vocab_view}")
    print("  => 같은 개념이 3가지 표기로 흩어져도 Schema 는 못 잡는다. "
          "통제 어휘가 하나('self-rag')로 접는다.")


if __name__ == "__main__":
    demo_schema_vs_semantic()
    demo_vocab_gap()
