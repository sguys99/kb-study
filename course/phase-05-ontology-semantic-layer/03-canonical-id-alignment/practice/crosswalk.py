"""
crosswalk.py — 크로스워크 조회 + 정렬 커버리지 리포트

전제:
  - alignment_model.py, canonical_id.py, controlled_vocabulary.py 와 두 YAML 필요.
  - API 키·Neo4j 불필요. 로컬에서 돈다.

무엇을 하나:
  1) resolve_to_external(concept_id, target_kb) — 우리 개념을 외부 KB ID(+URL)로 조회.
     같은 개념에 여러 매핑이 있으면 match_type 우선순위(exact>close>broad>narrow),
     동순위면 confidence 로 최선의 하나를 고른다.
  2) coverage_report() — concept 중 몇 %가 외부 KB 에 정렬됐나. KB별·전체 커버리지.
     "어디가 아직 외딴 섬인가"를 계기판으로 보여준다.

이 조회 함수가 04(constraint-validation)의 입력이 된다: 04 는 canonical id·타입을 제약 대상으로
삼고, 필요하면 이 crosswalk 로 외부 근거를 붙인다.
"""

from __future__ import annotations

from pathlib import Path

from alignment_model import AlignmentTable, Mapping, load_alignment
from controlled_vocabulary import ControlledVocabulary, load_vocabulary
from pydantic import BaseModel

VOCAB_PATH = Path(__file__).with_name("vocabulary.yaml")

# match_type 우선순위(작을수록 강함). 크로스워크에서 "가장 확실한 매핑"을 고를 때 쓴다.
_MATCH_RANK = {"exact": 0, "close": 1, "broad": 2, "narrow": 3}


class ExternalRef(BaseModel):
    """crosswalk 조회 결과 한 건."""

    concept_id: str
    target_kb: str
    external_id: str
    match_type: str
    confidence: float
    url: str


def _build_url(table: AlignmentTable, m: Mapping) -> str:
    tmpl = table.external_kbs[m.target_kb].url_template
    return tmpl.format(id=m.external_id) if tmpl else m.external_id


def resolve_to_external(
    table: AlignmentTable,
    concept_id: str,
    target_kb: str,
) -> ExternalRef | None:
    """concept_id 를 특정 외부 KB 의 최선 매핑으로 조회한다.

    여러 후보가 있으면 (match_type 우선순위, -confidence) 로 정렬해 가장 강한 하나를 고른다.
    매핑이 없으면 None(아직 그 KB 에는 정렬 안 됨).
    """
    cands = [
        m for m in table.mappings
        if m.internal == concept_id and m.target_kb == target_kb
    ]
    if not cands:
        return None
    best = min(cands, key=lambda m: (_MATCH_RANK[m.match_type], -m.confidence))
    return ExternalRef(
        concept_id=concept_id,
        target_kb=target_kb,
        external_id=best.external_id,
        match_type=best.match_type,
        confidence=best.confidence,
        url=_build_url(table, best),
    )


def all_external_refs(table: AlignmentTable, concept_id: str) -> list[ExternalRef]:
    """concept_id 가 정렬된 모든 외부 KB 를 KB별 최선 매핑으로 반환."""
    kbs = sorted({m.target_kb for m in table.mappings if m.internal == concept_id})
    refs = [resolve_to_external(table, concept_id, kb) for kb in kbs]
    return [r for r in refs if r is not None]


class CoverageReport(BaseModel):
    total_concepts: int
    aligned_concepts: int          # 외부 KB 하나 이상에 정렬된 개념 수
    overall_pct: float
    per_kb_pct: dict[str, float]   # KB별 커버리지(%)
    unaligned: list[str]           # 어떤 외부 KB 에도 정렬 안 된 concept_id


def coverage_report(
    vocab: ControlledVocabulary,
    table: AlignmentTable,
) -> CoverageReport:
    """정렬 커버리지 계산."""
    all_cids = [c.concept_id for c in vocab.concepts]
    total = len(all_cids)

    aligned_by_kb: dict[str, set[str]] = {kb: set() for kb in table.external_kbs}
    aligned_any: set[str] = set()
    for m in table.mappings:
        aligned_by_kb.setdefault(m.target_kb, set()).add(m.internal)
        aligned_any.add(m.internal)

    per_kb = {
        kb: round(100.0 * len(cids) / total, 1)
        for kb, cids in aligned_by_kb.items()
    }
    unaligned = sorted(c for c in all_cids if c not in aligned_any)

    return CoverageReport(
        total_concepts=total,
        aligned_concepts=len(aligned_any),
        overall_pct=round(100.0 * len(aligned_any) / total, 1),
        per_kb_pct=per_kb,
        unaligned=unaligned,
    )


if __name__ == "__main__":
    vocab = load_vocabulary(VOCAB_PATH)
    table = load_alignment()

    print("== crosswalk 조회 ==")
    for cid, kb in [("self-rag", "arxiv"), ("self-rag", "wikidata"),
                    ("crag", "arxiv"), ("graphrag", "github"),
                    ("accuracy", "wikidata")]:
        ref = resolve_to_external(table, cid, kb)
        if ref:
            print(f"  {cid:10} @ {kb:9} -> {ref.external_id:14} "
                  f"[{ref.match_type}] {ref.url}")
        else:
            print(f"  {cid:10} @ {kb:9} -> (미정렬)")

    print("\n== self-rag 의 모든 외부 정렬 ==")
    for ref in all_external_refs(table, "self-rag"):
        print(f"  {ref.target_kb:9} {ref.external_id:14} [{ref.match_type}] conf={ref.confidence}")

    print("\n== 정렬 커버리지 리포트 ==")
    rep = coverage_report(vocab, table)
    print(f"  전체: {rep.aligned_concepts}/{rep.total_concepts} = {rep.overall_pct}%")
    for kb, pct in rep.per_kb_pct.items():
        print(f"  {kb:9}: {pct}%")
    print(f"  미정렬 개념: {rep.unaligned}")

    # 자체검증 — 완료 기준을 코드로 못박는다.
    # 1) self-rag 의 arXiv exactMatch 가 crosswalk 로 조회된다.
    r = resolve_to_external(table, "self-rag", "arxiv")
    assert r is not None and r.external_id == "2310.11511" and r.match_type == "exact"
    assert r.url == "https://arxiv.org/abs/2310.11511"

    # 2) self-rag 는 wikidata 에는 broad 로 정렬(exact 아님).
    rw = resolve_to_external(table, "self-rag", "wikidata")
    assert rw is not None and rw.match_type == "broad"

    # 3) accuracy 는 어떤 KB 에도 정렬 안 됨 → None + unaligned 목록에 포함.
    assert resolve_to_external(table, "accuracy", "wikidata") is None
    assert "accuracy" in rep.unaligned and "hybrid-rag" in rep.unaligned

    # 4) 커버리지는 0~100 사이, 전체 개념 수와 정합.
    assert 0.0 <= rep.overall_pct <= 100.0
    assert rep.total_concepts == len(vocab.concepts)

    print("\n[assert] 모든 자체검증 통과")
