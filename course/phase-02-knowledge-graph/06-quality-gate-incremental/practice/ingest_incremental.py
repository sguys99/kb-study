"""ingest_incremental.py — Phase 2 의 종착 엔트리포인트. 게이트 → MERGE 적재 → version 스탬프.

05 산출물(정규화된 엣지·이벤트)을 읽어 품질 게이트로 통과/거절을 분기하고,
통과분만 경량 그래프 스토어에 MERGE 로 증분 적재한다. 같은 입력을 두 번 적재해도
카운트가 변하지 않는다(idempotent). 두 번째 배치는 신규 추가 + 기존 엣지 provenance
누적으로 들어간다. 소스 철회(delete)도 시연한다.

스토어 스냅샷(graph_snapshot.jsonl)이 Phase 3(Neo4j Bulk Ingest)의 입력이다.

사용:
  python ingest_incremental.py                          # 1차 배치(v1) 적재
  python ingest_incremental.py                          # 같은 명령 재실행 → 카운트 불변(idempotent)
  python ingest_incremental.py --batch v2 \\
      --relations batch2_relations.jsonl                # 2차 배치 증분 적재
  python ingest_incremental.py --batch v3 \\
      --delete-source src-04-graphrag                   # 소스 철회 → provenance 제거·tombstone
  python ingest_incremental.py --reset                  # 스냅샷 삭제 후 처음부터

전제: pydantic>=2(quality_gate 가 사용). graph_store 는 표준 라이브러리만.
네트워크·API 키 불필요.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from graph_store import GraphStore
from quality_gate import GateConfig, Relation, load_canonical_names, run_gate

HERE = Path(__file__).resolve().parent
SNAPSHOT = HERE / "graph_snapshot.jsonl"
REJECT_QUEUE = HERE / "reject_queue.jsonl"
CANON = HERE / "sample_canonical_entities.jsonl"  # 04 산출물(시연은 sample)


def load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def append_reject_queue(rejected: list[dict], batch: str) -> None:
    """게이트가 거절한 항목을 사유·근거와 함께 reject_queue 에 누적한다.

    05 가 이미 걸러 둔 reject_relations.jsonl 과 합쳐 "왜 빠졌나"를 한곳에서 추적한다.
    사람이 검토 후 vocab/스키마를 고쳐 재투입하는 거버넌스 루프의 입구다.
    """
    with REJECT_QUEUE.open("a", encoding="utf-8") as f:
        for item in rejected:
            f.write(json.dumps({**item, "batch": batch, "stage": "quality_gate"},
                               ensure_ascii=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="품질 게이트 + 증분 적재")
    parser.add_argument("--batch", default="v1", help="이 적재의 version 라벨(예: v1, v2)")
    parser.add_argument("--relations", default="normalized_relations.jsonl",
                        help="적재할 정규화 엣지 JSONL")
    parser.add_argument("--delete-source", default=None,
                        help="이 source_id 의 provenance 를 철회(delete 시연)")
    parser.add_argument("--min-support", type=int, default=1,
                        help="이 미만 support 는 LOW_SUPPORT 로 거절")
    parser.add_argument("--reset", action="store_true",
                        help="스냅샷·reject_queue 를 지우고 처음부터")
    args = parser.parse_args()

    if args.reset:
        for p in (SNAPSHOT, REJECT_QUEUE):
            p.unlink(missing_ok=True)
        print(f"리셋: {SNAPSHOT.name}, {REJECT_QUEUE.name} 삭제")

    canon_rows = load_jsonl(CANON)
    canonical_names = load_canonical_names(canon_rows)
    node_labels = {row["name"]: row["type"] for row in canon_rows}

    store = GraphStore.load(SNAPSHOT)
    before = store.stats()

    # ── delete 모드: 소스 철회만 하고 끝낸다. ──
    if args.delete_source:
        result = store.delete_source(args.delete_source, args.batch)
        store.save(SNAPSHOT)
        after = store.stats()
        print(f"[batch {args.batch}] 소스 철회: {args.delete_source}")
        print(f"  provenance 제거: {result['provenances_removed']}건 · "
              f"tombstone 처리: {result['tombstoned']}건")
        print(f"  통계  before → after: "
              f"live_edges {before['live_edges']}→{after['live_edges']} · "
              f"tombstoned {before['tombstoned_edges']}→{after['tombstoned_edges']} · "
              f"total_support {before['total_support']}→{after['total_support']}")
        return 0

    # ── 적재 모드: 게이트 → MERGE. ──
    raw = load_jsonl(HERE / args.relations)
    relations = [Relation.model_validate(r) for r in raw]

    cfg = GateConfig(min_support=args.min_support)
    gate = run_gate(relations, canonical_names, cfg)
    append_reject_queue(gate.rejected, args.batch)

    passed_dicts = [r.model_dump() for r in gate.passed]
    counts = store.ingest_batch(passed_dicts, node_labels, args.batch)
    store.save(SNAPSHOT)
    after = store.stats()

    print(f"[batch {args.batch}] 입력 {len(relations)}건 → "
          f"게이트 통과 {len(gate.passed)}건 · 거절 {len(gate.rejected)}건")
    if gate.rejected:
        print(f"  거절 사유: {gate.reject_counts()}")
    print(f"  MERGE 결과: created {counts['created']} · "
          f"accumulated {counts['accumulated']} · revived {counts['revived']}")
    print(f"  스토어 통계: nodes {after['nodes']} · live_edges {after['live_edges']} · "
          f"orphan {after['orphan_nodes']} · total_support {after['total_support']} "
          f"(tombstoned {after['tombstoned_edges']})")
    print(f"  스냅샷 저장: {SNAPSHOT.name} (Phase 3 Neo4j 적재의 입력)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
