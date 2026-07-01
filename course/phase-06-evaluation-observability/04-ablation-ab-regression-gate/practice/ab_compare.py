# ab_compare.py — A/B 비교: 두 구성을 같은 골든셋으로 돌려 승패를 센다
#
# 하는 일:
#   기본은 LightRAG hybrid vs mix. 두 구성을 같은 골든셋으로 돌려
#   (1) 지표별 평균차, (2) 질문 단위 승/무/패 카운트를 낸다.
#   Phase 4 의 5모드 A/B 와 연결되는 결정 근거다.
#
#   ⚠️ 유의성: 골든셋이 작을 때 평균차 0.02 를 "이겼다"고 과대해석하면 안 된다.
#   여기서는 통계 검정 대신 승패 카운트 + 평균차 "감각"만 본다. 표본이 3~수십 개면
#   이 정도가 정직하다. 더 엄밀히 가려면 골든셋을 키우고 시드를 고정한 뒤 반복 측정한다.
#
# 실행:
#   python ab_compare.py                              # hybrid vs mix
#   python ab_compare.py --a full --b vector_only     # 임의 두 구성
#
# 전제: 외부 의존 없음(표준 라이브러리만).

from __future__ import annotations

import argparse

import configs as C
from run_eval import METRIC_NAMES, run_config, score_case

EPS = 1e-9   # 부동소수 동점 판정 여유


def per_question_scores(config_name: str) -> dict[str, dict[str, float]]:
    """질문별 지표를 그대로 돌려준다(승패 카운트에 필요)."""
    logs = C.CONFIGS[config_name]
    return {qid: score_case(C.GOLDEN[qid], logs[qid]) for qid in C.QUESTION_IDS}


def win_loss(a_name: str, b_name: str) -> dict[str, dict[str, int]]:
    """지표별로 질문 단위 승/무/패(A 기준)를 센다."""
    a_scores = per_question_scores(a_name)
    b_scores = per_question_scores(b_name)
    tally = {m: {"win": 0, "tie": 0, "loss": 0} for m in METRIC_NAMES}
    for qid in C.QUESTION_IDS:
        for m in METRIC_NAMES:
            diff = a_scores[qid][m] - b_scores[qid][m]
            if diff > EPS:
                tally[m]["win"] += 1
            elif diff < -EPS:
                tally[m]["loss"] += 1
            else:
                tally[m]["tie"] += 1
    return tally


def print_ab(a_name: str, b_name: str) -> None:
    a_avg = run_config(a_name)
    b_avg = run_config(b_name)
    tally = win_loss(a_name, b_name)

    header = f"{'metric':<20}{a_name:>14}{b_name:>14}{'Δ(A-B)':>12}{'승/무/패':>12}"
    print("=" * len(header))
    print(f"  A/B — A={a_name}  vs  B={b_name}  (승/무/패는 A 기준, 질문 단위)")
    print("=" * len(header))
    print(header)
    print("-" * len(header))
    a_wins = b_wins = 0
    for m in METRIC_NAMES:
        delta = a_avg[m] - b_avg[m]
        wlt = tally[m]
        if delta > EPS:
            a_wins += 1
        elif delta < -EPS:
            b_wins += 1
        wlt_str = f"{wlt['win']}/{wlt['tie']}/{wlt['loss']}"
        print(f"{m:<20}{a_avg[m]:>14.3f}{b_avg[m]:>14.3f}{delta:>+12.3f}{wlt_str:>12}")
    print("=" * len(header))

    print(f"\n지표 평균 기준: A 우세 {a_wins}개 / B 우세 {b_wins}개")
    print("주의: 골든셋이 작다. 평균차가 근소하면 '무승부'로 보고 골든셋을 키운 뒤 다시 잰다.")


def main() -> None:
    parser = argparse.ArgumentParser(description="A/B 구성 비교")
    parser.add_argument("--a", default="lightrag_hybrid", help="구성 A 이름")
    parser.add_argument("--b", default="lightrag_mix", help="구성 B 이름")
    args = parser.parse_args()
    print_ab(args.a, args.b)


if __name__ == "__main__":
    main()
