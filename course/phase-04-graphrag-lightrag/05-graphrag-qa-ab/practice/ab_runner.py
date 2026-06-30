"""4.5 ab_runner.py — 골든셋 전체 × 네 전략을 돌려 리더보드를 낸다.

Phase 4 의 결론을 숫자로 보여주는 하니스다.
  - 전체 골든 질문 × {Vector, Local, Global, Hybrid} 를 모두 돌린다.
  - 전략 × 지표(recall@k / mrr / hit_rate) 리더보드를 찍는다.
  - 같은 표를 질문 type(simple-fact / multi-hop / global-summary)별로 분해한다.

읽어야 할 결론:
  - Vector 는 simple-fact 에 강하다(Phase 1 기준선). 멀티홉·전체요약에서 무너진다(Phase 0 의 실패).
  - Local 은 멀티홉, Global 은 global-summary 에서 앞선다.
  - Hybrid 가 type 을 가로질러 종합 최고다 — Vector(기준선) 대비 멀티홉·요약 개선폭이 핵심.

표는 표준 라이브러리만으로 그린다(외부 의존 없음). Hybrid 의 reranker 만 선택적으로
VOYAGE_API_KEY 를 쓰고, 없으면 04 의 identity 폴백으로 떨어진다(과금 0).

전제: 없음(키 불필요, 과금 0). 키 하드코딩 금지.
실행:
    python ab_runner.py             # k=3 으로 전체 리더보드 + type별 분해
    python ab_runner.py --k 5       # top-k 변경
    python ab_runner.py --backend local   # Hybrid reranker 백엔드 지정
"""

from __future__ import annotations

import sys

from goldenset import load_golden, VALID_TYPES
from metrics import aggregate, evaluate_one
from strategies import STRATEGIES

METRIC_KEYS = ("recall@k", "mrr", "hit_rate")


def run_ab(k: int = 3, backend: str | None = None) -> dict:
    """골든셋 전체 × 네 전략을 평가해 질문별 행을 모은다.

    돌려주는 구조:
      {
        "k": k,
        "rows": [{"qid","type","strategy","recall@k","mrr","hit_rate"}, ...],
      }
    """
    items = load_golden()
    rows: list[dict] = []

    for it in items:
        for name, fn in STRATEGIES.items():
            # Hybrid 만 reranker 백엔드를 받는다(나머지는 시그니처가 받지 않음).
            if name == "Hybrid":
                ranked = fn(it["question"], it["pool"], backend=backend)
            else:
                ranked = fn(it["question"], it["pool"])
            m = evaluate_one(ranked, it["gold"], k=k)
            rows.append({"qid": it["qid"], "type": it["type"], "strategy": name, **m})

    return {"k": k, "rows": rows}


def _board(rows: list[dict]) -> dict[str, dict[str, float]]:
    """전략별 지표 평균 표를 만든다: {strategy: {metric: mean}}."""
    board: dict[str, dict[str, float]] = {}
    for name in STRATEGIES:
        srows = [r for r in rows if r["strategy"] == name]
        board[name] = {key: aggregate(srows, key) for key in METRIC_KEYS}
    return board


def _print_board(title: str, board: dict[str, dict[str, float]], k: int) -> None:
    print(f"[{title}]")
    print(f"  {'전략':<8} {'recall@' + str(k):>9} {'mrr':>7} {'hit_rate':>9}")
    print("  " + "-" * 36)
    for name in STRATEGIES:
        b = board[name]
        print(f"  {name:<8} {b['recall@k']:>9.3f} {b['mrr']:>7.3f} {b['hit_rate']:>9.3f}")
    # 종합 최고(recall 기준) 표시
    best = max(STRATEGIES, key=lambda n: board[n]["recall@k"])
    print(f"  → recall@{k} 최고: {best}")
    print()


def _delta_vs_baseline(board: dict[str, dict[str, float]], k: int) -> None:
    """Phase 1 Baseline(=Vector) 대비 Hybrid 개선폭을 한 줄로."""
    base = board["Vector"]["recall@k"]
    hyb = board["Hybrid"]["recall@k"]
    delta = hyb - base
    sign = "+" if delta >= 0 else ""
    print(f"  [Baseline(Vector) 대비 Hybrid] recall@{k}: "
          f"{base:.3f} → {hyb:.3f} ({sign}{delta:.3f})")


def main(argv: list[str]) -> None:
    k = int(argv[argv.index("--k") + 1]) if "--k" in argv else 3
    backend = argv[argv.index("--backend") + 1] if "--backend" in argv else None

    result = run_ab(k=k, backend=backend)
    rows = result["rows"]

    print("=" * 44)
    print(f" GraphRAG Q&A A/B 리더보드  (k={k})")
    print("=" * 44 + "\n")

    overall = _board(rows)
    _print_board("전체 리더보드 (전략 × 지표)", overall, k)
    _delta_vs_baseline(overall, k)
    print()

    print("-" * 44)
    print(" type별 분해 — 어느 모드가 어디서 이기나")
    print("-" * 44 + "\n")
    for qtype in VALID_TYPES:
        trows = [r for r in rows if r["type"] == qtype]
        n_q = len({r["qid"] for r in trows})
        _print_board(f"{qtype}  (질문 {n_q}개)", _board(trows), k)

    print("[해석] Vector 는 simple-fact 에 강하고 multi-hop·global-summary 에서 무너진다.")
    print("       Local 은 multi-hop, Global 은 global-summary 에서 앞서고, Hybrid 가 종합 최고다.")
    print("[다음] → 06-why-lightrag: 이 네 전략을 LightRAG 5모드로 한 프레임워크에 담는다.")


if __name__ == "__main__":
    main(sys.argv)
