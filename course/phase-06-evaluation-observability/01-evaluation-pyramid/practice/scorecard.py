# scorecard.py — 평가 피라미드 스코어카드 하니스 (표준 라이브러리만)
#
# 하는 일:
#   1) 4계층(Construction/Retrieval/Generation/Agent) 지표를 샘플 데이터로 계산
#   2) 계층별 점수 카드를 표로 출력
#   3) --save 로 baseline.json 저장, 재실행 시 저장된 baseline 과 비교(회귀 게이트의 씨앗)
#
# 실행:
#   python scorecard.py               # 점수만 계산·출력
#   python scorecard.py --save        # 현재 점수를 baseline.json 으로 저장
#   python scorecard.py --compare     # baseline.json 과 비교(하락 항목 경고)
#
# 회귀 게이트(Regression Gate) 자체 — 임계값 설정, CI 연동, 하락 시 빌드 실패 —
# 는 토픽 04 로 넘긴다. 여기서는 "저장하고 비교한다"는 뼈대만 심는다.

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

import metrics as M
import sample_data as D

BASELINE_PATH = Path(__file__).parent / "baseline.json"


def compute_scores() -> dict[str, dict[str, float]]:
    """4계층 지표를 모두 계산해 중첩 딕셔너리로 돌려준다."""

    # --- Construction ---
    construction = {
        "schema_conformance": M.schema_conformance(
            D.NODES, D.ALLOWED_LABELS, D.REQUIRED_PROPS
        ),
        # 중복률·고아율은 낮을수록 좋다. 카드에서는 값 그대로 보여주되
        # "낮을수록 좋음" 표시를 붙인다(아래 LOWER_IS_BETTER 참고).
        "duplicate_rate": M.duplicate_rate(D.NODE_CANONICAL_KEYS),
        "orphan_rate": M.orphan_rate(D.NODE_IDS, D.EDGES),
    }

    # --- Retrieval: 질문별로 계산 후 평균 ---
    recalls, precisions, hits = [], [], []
    for case in D.RETRIEVAL_CASES:
        recalls.append(M.context_recall(case["retrieved"], case["relevant"]))
        precisions.append(M.context_precision(case["retrieved"], case["relevant"]))
        hits.append(M.hit_at_k(case["retrieved"], case["relevant"], D.HIT_AT_K))
    retrieval = {
        "context_recall": statistics.fmean(recalls),
        "context_precision": statistics.fmean(precisions),
        f"hit@{D.HIT_AT_K}": statistics.fmean(hits),
    }

    # --- Generation: 인용 정확도(케이스 평균) ---
    cite_p, cite_r, cite_f1 = [], [], []
    for case in D.GENERATION_CASES:
        s = M.citation_accuracy(case["cited"], case["gold_support"])
        cite_p.append(s["precision"])
        cite_r.append(s["recall"])
        cite_f1.append(s["f1"])
    generation = {
        "citation_precision": statistics.fmean(cite_p),
        "citation_recall": statistics.fmean(cite_r),
        "citation_f1": statistics.fmean(cite_f1),
    }

    # --- Agent: tool-call accuracy(케이스 평균) + task success rate ---
    tool_acc = [
        M.tool_call_accuracy(c["predicted_tools"], c["gold_tools"])
        for c in D.AGENT_CASES
    ]
    agent = {
        "tool_call_accuracy": statistics.fmean(tool_acc),
        "task_success_rate": M.task_success_rate(D.AGENT_TASK_RESULTS),
    }

    return {
        "construction": construction,
        "retrieval": retrieval,
        "generation": generation,
        "agent": agent,
    }


# 값이 낮을수록 좋은 지표(비교/출력 시 방향을 뒤집어 해석한다).
LOWER_IS_BETTER = {"duplicate_rate", "orphan_rate"}


def print_scorecard(scores: dict[str, dict[str, float]]) -> None:
    """계층별 점수 카드를 표 형태로 출력한다."""
    print("=" * 52)
    print("  GraphRAG Evaluation Pyramid — Scorecard")
    print("=" * 52)
    for layer, table in scores.items():
        print(f"\n[{layer.upper()}]")
        for name, value in table.items():
            arrow = " (낮을수록 좋음)" if name in LOWER_IS_BETTER else ""
            print(f"  {name:<22} {value:6.3f}{arrow}")
    print("\n" + "=" * 52)


def save_baseline(scores: dict[str, dict[str, float]]) -> None:
    BASELINE_PATH.write_text(
        json.dumps(scores, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"baseline 저장: {BASELINE_PATH}")


def compare_baseline(scores: dict[str, dict[str, float]]) -> None:
    """저장된 baseline 과 현재 점수를 비교해 하락 항목을 경고한다.

    회귀 게이트의 씨앗: 여기서는 임계값 없이 '방향'만 본다.
    실제 게이트(임계값·CI 실패 처리)는 토픽 04.
    """
    if not BASELINE_PATH.exists():
        print("baseline.json 이 없다. 먼저 `python scorecard.py --save` 를 실행하라.")
        return
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    print("\n--- baseline 대비 변화 ---")
    regressions = 0
    for layer, table in scores.items():
        for name, value in table.items():
            old = baseline.get(layer, {}).get(name)
            if old is None:
                print(f"  [NEW] {layer}.{name} = {value:.3f}")
                continue
            delta = value - old
            # 낮을수록 좋은 지표는 delta 부호를 뒤집어 '개선/회귀'를 판단
            improved = (delta < 0) if name in LOWER_IS_BETTER else (delta > 0)
            regressed = (delta > 0) if name in LOWER_IS_BETTER else (delta < 0)
            tag = "OK  "
            if regressed and delta != 0:
                tag = "WARN"
                regressions += 1
            elif improved and delta != 0:
                tag = "UP  "
            print(f"  [{tag}] {layer}.{name}: {old:.3f} -> {value:.3f} ({delta:+.3f})")
    print(f"\n회귀(하락) 의심 항목: {regressions}건")
    if regressions:
        print("→ 어느 계층이 무너졌는지부터 본다. Construction 이 흔들리면 위층 점수는 믿을 수 없다.")


def main() -> None:
    parser = argparse.ArgumentParser(description="평가 피라미드 스코어카드")
    parser.add_argument("--save", action="store_true", help="현재 점수를 baseline 으로 저장")
    parser.add_argument("--compare", action="store_true", help="baseline 과 비교")
    args = parser.parse_args()

    scores = compute_scores()
    print_scorecard(scores)

    if args.save:
        save_baseline(scores)
    if args.compare:
        compare_baseline(scores)


if __name__ == "__main__":
    main()
