"""eval_construction.py — 그래프 "구축" 품질을 숫자로 본다. "좋아진 것 같다" 금지.

이 토픽의 Eval 은 답변 품질이 아니라 Construction(그래프 구축) 품질이다.
Ragas(답변 평가)는 Phase 6 소관이니 여기서 끌어오지 않는다. 여기서는 적재 결과를
gold 정답 엣지 집합과 결정적으로 대조한다.

계산 지표:
  precision : 적재된(live) 엣지 중 gold 에 있는 비율 — 쓰레기를 얼마나 안 넣었나.
  recall    : gold 엣지 중 적재된 비율 — 맞는 걸 얼마나 안 놓쳤나.
  F1        : 둘의 조화평균.
  false positive : 적재됐지만 gold 에 없는 엣지(노이즈 유입).
  false reject   : gold 에 있는데 reject_queue 로 빠진 엣지(과도한 게이트로 정답을 버림).
  그래프 통계    : 노드·live 엣지·tombstone·고아 수.

전제: 표준 라이브러리만. 먼저 ingest_incremental.py 로 스냅샷을 만들어 둔다.
네트워크·API 키 불필요.
"""

from __future__ import annotations

import json
from pathlib import Path

from graph_store import GraphStore

HERE = Path(__file__).resolve().parent
SNAPSHOT = HERE / "graph_snapshot.jsonl"
REJECT_QUEUE = HERE / "reject_queue.jsonl"
GOLD = HERE / "gold_edges.jsonl"


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def triple(d: dict) -> tuple[str, str, str]:
    return (d["head"], d["type"], d["tail"])


def main() -> int:
    if not SNAPSHOT.exists():
        print("스냅샷이 없다. 먼저 `python ingest_incremental.py` 로 적재하라.")
        return 2

    store = GraphStore.load(SNAPSHOT)
    gold = {triple(d) for d in load_jsonl(GOLD)}
    predicted = {triple(e) for e in store.live_edges()}
    rejected = {triple(d) for d in load_jsonl(REJECT_QUEUE)}

    tp = predicted & gold
    fp = predicted - gold
    fn = gold - predicted
    false_reject = gold & rejected  # gold 인데 게이트가 거절한 것

    precision = len(tp) / len(predicted) if predicted else 0.0
    recall = len(tp) / len(gold) if gold else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

    stats = store.stats()

    print("=== Construction Eval (gold 대비) ===")
    print(f"gold {len(gold)}건 · predicted(live) {len(predicted)}건 · "
          f"교집합(TP) {len(tp)}건")
    print(f"precision {precision:.2f} · recall {recall:.2f} · F1 {f1:.2f}")
    print()
    print(f"false positive {len(fp)}건 (적재됐지만 gold 아님):")
    for h, t_, ta in sorted(fp):
        print(f"  + ({h})-[{t_}]->({ta})")
    print(f"false reject {len(false_reject)}건 (gold 인데 게이트가 거절):")
    for h, t_, ta in sorted(false_reject):
        print(f"  - ({h})-[{t_}]->({ta})")
    print()
    print("=== 그래프 통계 ===")
    print(f"nodes {stats['nodes']} · live_edges {stats['live_edges']} · "
          f"tombstoned {stats['tombstoned_edges']} · orphan_nodes {stats['orphan_nodes']} · "
          f"total_support {stats['total_support']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
