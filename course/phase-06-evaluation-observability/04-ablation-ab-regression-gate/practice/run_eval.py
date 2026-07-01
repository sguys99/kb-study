# run_eval.py — 한 구성(configuration)을 골든셋으로 돌려 평균 지표를 계산하는 공용 코어
#
# Ablation·A/B·Regression Gate 세 스크립트가 전부 이 함수를 재사용한다.
# "구성 이름 하나를 받아 → 골든셋 전체를 돌려 → 지표 dict 하나를 돌려준다."
#
# 지표(모두 높을수록 좋음, 0.0~1.0):
#   context_recall     : 놓친 근거가 있나 (01)
#   context_precision  : 가져온 근거가 알짜였나 (01)
#   citation_f1        : 답변 인용이 골든 근거와 맞나 (01)
#   multihop_path_hit  : 정답이 요구하는 홉을 실제로 밟았나 (02) — 그래프의 값어치 핵심
#   entity_coverage    : 정답 엔티티를 건드렸나 (02)
#
# 전제: 외부 의존 없음. LLM/Ragas/Langfuse 없이 mock 로그로 계산한다.
#   실제 Ragas(faithfulness 등) 연결은 02, trace 연결은 03 참조.

from __future__ import annotations

import statistics

import configs as C
import eval_metrics as M

# 지표 이름 → 계산 함수 목록(케이스 하나당 한 값)
METRIC_NAMES = [
    "context_recall",
    "context_precision",
    "citation_f1",
    "multihop_path_hit",
    "entity_coverage",
]


def score_case(gold: dict, log: dict) -> dict[str, float]:
    """질문 하나: 골든 라벨(gold) + 구성의 검색 로그(log) → 지표 dict."""
    return {
        "context_recall": M.context_recall(log["retrieved"], gold["relevant"]),
        "context_precision": M.context_precision(log["retrieved"], gold["relevant"]),
        "citation_f1": M.citation_f1(log["cited"], gold["gold_support"]),
        "multihop_path_hit": M.multihop_path_hit(
            gold["required_hops"], log["traversed_edges"]
        ),
        "entity_coverage": M.entity_coverage(
            gold["gold_entities"], log["retrieved_entities"]
        ),
    }


def run_config(config_name: str) -> dict[str, float]:
    """구성 이름 하나를 골든셋 전체로 돌려 지표별 평균을 돌려준다."""
    if config_name not in C.CONFIGS:
        raise KeyError(f"모르는 구성: {config_name} (가능: {list(C.CONFIGS)})")
    logs = C.CONFIGS[config_name]

    per_metric: dict[str, list[float]] = {name: [] for name in METRIC_NAMES}
    for qid in C.QUESTION_IDS:
        case = score_case(C.GOLDEN[qid], logs[qid])
        for name in METRIC_NAMES:
            per_metric[name].append(case[name])

    return {name: statistics.fmean(vals) for name, vals in per_metric.items()}


if __name__ == "__main__":
    # 빠른 확인: full 구성 점수를 찍어 본다.
    scores = run_config("full")
    print("full 구성 점수:")
    for name, value in scores.items():
        print(f"  {name:<20} {value:.3f}")
