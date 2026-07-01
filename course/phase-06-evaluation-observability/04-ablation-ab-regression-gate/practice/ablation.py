# ablation.py — Ablation(제거 실험): 구성을 하나씩 빼 보고 점수가 떨어지는지 표로 본다
#
# 하는 일:
#   full / vector_only / no_rerank 세 구성을 같은 골든셋으로 돌려 지표를 나란히 표로 찍고,
#   full 대비 각 구성의 하락폭(delta)을 함께 보여 준다.
#   "그래프를 빼면 multihop_path_hit·context_recall 이 떨어진다"를 실제 숫자로 확인하는 게 목적.
#   이 하락폭이 곧 Phase 1 Baseline 대비 GraphRAG(그래프·rerank)의 값어치다.
#
# 실행:
#   python ablation.py
#   python ablation.py --json    # 표 대신 JSON(다른 도구에 물릴 때)
#
# 전제: 외부 의존 없음(표준 라이브러리만). 점수는 configs.py 의 mock 로그에서 나온다.

from __future__ import annotations

import argparse
import json

from run_eval import METRIC_NAMES, run_config

# Ablation 대상 구성: 기준(full) → 그래프 제거 → rerank 제거
ABLATION_CONFIGS = ["full", "vector_only", "no_rerank"]
BASE = "full"   # 하락폭을 재는 기준


def run_ablation() -> dict[str, dict[str, float]]:
    """구성별 지표를 한 번에 계산해 {구성: {지표: 값}} 으로 돌려준다."""
    return {name: run_config(name) for name in ABLATION_CONFIGS}


def print_table(results: dict[str, dict[str, float]]) -> None:
    """지표 = 행, 구성 = 열. full 대비 delta 를 괄호로 붙인다."""
    base = results[BASE]
    header = f"{'metric':<20}" + "".join(f"{c:>16}" for c in ABLATION_CONFIGS)
    print("=" * len(header))
    print("  Ablation — 구성별 지표 (full 기준 하락폭)")
    print("=" * len(header))
    print(header)
    print("-" * len(header))
    for metric in METRIC_NAMES:
        row = f"{metric:<20}"
        for cfg in ABLATION_CONFIGS:
            val = results[cfg][metric]
            if cfg == BASE:
                cell = f"{val:.3f}"
            else:
                delta = val - base[metric]
                cell = f"{val:.3f}({delta:+.3f})"
            row += f"{cell:>16}"
        print(row)
    print("=" * len(header))

    # 결론 한 줄: 그래프 제거(vector_only)에서 멀티홉이 얼마나 무너졌나
    drop = base["multihop_path_hit"] - results["vector_only"]["multihop_path_hit"]
    print(f"\n결론: 그래프를 빼면 multihop_path_hit 이 {drop:+.3f} 만큼 떨어진다 "
          f"→ 멀티홉을 실제로 밟은 것이 GraphRAG 의 값어치.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Ablation 제거 실험")
    parser.add_argument("--json", action="store_true", help="JSON 으로 출력")
    args = parser.parse_args()

    results = run_ablation()
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print_table(results)


if __name__ == "__main__":
    main()
