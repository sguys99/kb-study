# regression_gate.py — 회귀 게이트(Regression Gate): baseline 대비 하락을 검출한다
#
# 하는 일:
#   baseline.json(01 에서 저장한 기준선의 이 토픽용 평면 버전)을 읽고, 새 실행 점수와 비교해
#   "임계값 이상 떨어진 지표"가 하나라도 있으면 회귀(regression)로 판정한다.
#   pytest·CI 가 이 판정을 assert 로 받아 merge 를 막는다.
#
# 임계값 설계(두 축):
#   abs_tol : 절대 하락 허용치. 예 0.02 → baseline 0.90 이면 0.88 까지는 봐준다.
#   rel_tol : 상대 하락 허용치. 예 0.03 → baseline 대비 3% 하락까지 봐준다.
#   두 허용치 중 "더 관대한 쪽"을 통과선으로 쓴다(작은 baseline 에서 rel 이 너무 빡세지지 않게).
#
# 왜 허용치가 필요한가(노이즈 대응):
#   LLM 기반 지표(Ragas faithfulness 등)는 같은 입력에도 실행마다 소수점이 흔들린다.
#   허용치 없이 "조금이라도 떨어지면 실패"로 하면 게이트가 노이즈에 계속 붉어진다(flaky).
#   그래서 (a) 허용 delta 를 두고, (b) 시드를 고정하고, (c) 여러 번 돌려 평균 낸 점수를 쓴다.
#   이 파일은 (a) 를 담당한다. (b)(c) 는 golden set 생성·측정 쪽(02/03)에서 처리한다.
#
# 전제: 외부 의존 없음(표준 라이브러리만). baseline.json 은 같은 폴더.

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

BASELINE_PATH = Path(__file__).parent / "baseline.json"

# 부동소수 오차 여유. 0.90-0.02 가 0.02000...018 로 계산돼 허용선을 '아슬하게'
# 넘는 것을 방지한다. 허용선과 사실상 같은 하락은 통과로 본다.
_FP_EPS = 1e-9


@dataclass
class Regression:
    """회귀 1건: 어떤 지표가 얼마나 떨어졌고 허용선은 얼마였나."""
    metric: str
    baseline: float
    current: float
    drop: float          # baseline - current (양수면 하락)
    allowed_drop: float  # 이만큼까지는 봐준다


@dataclass
class GateResult:
    passed: bool
    regressions: list[Regression] = field(default_factory=list)


def load_baseline(path: Path = BASELINE_PATH) -> dict[str, float]:
    """baseline.json 의 metrics 블록을 평면 dict 로 돌려준다."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["metrics"]


def allowed_drop(baseline_value: float, abs_tol: float, rel_tol: float) -> float:
    """이 지표에서 허용하는 최대 하락폭 = max(절대 허용, 상대 허용)."""
    return max(abs_tol, baseline_value * rel_tol)


def check_regression(current: dict[str, float],
                     baseline: dict[str, float] | None = None,
                     abs_tol: float = 0.02,
                     rel_tol: float = 0.03) -> GateResult:
    """새 점수(current)를 baseline 과 비교해 회귀 여부를 판정한다.

    baseline 에 있는 지표만 검사한다(신규 지표는 게이트 대상 아님).
    하락폭이 허용선을 '초과'하면 회귀로 본다(허용선 정확히 같으면 통과).
    """
    if baseline is None:
        baseline = load_baseline()

    regressions: list[Regression] = []
    for metric, base_val in baseline.items():
        if metric not in current:
            # 지표가 사라졌다 = 파이프라인이 그 지표를 안 냈다 → 회귀로 취급
            regressions.append(Regression(metric, base_val, float("nan"),
                                          drop=base_val, allowed_drop=0.0))
            continue
        cur_val = current[metric]
        drop = base_val - cur_val
        tol = allowed_drop(base_val, abs_tol, rel_tol)
        if drop > tol + _FP_EPS:
            regressions.append(Regression(metric, base_val, cur_val, drop, tol))

    return GateResult(passed=not regressions, regressions=regressions)


def format_report(result: GateResult) -> str:
    """게이트 결과를 사람이 읽을 문자열로. CI 로그·assert 메시지에 그대로 쓴다."""
    if result.passed:
        return "PASS — baseline 대비 회귀 없음."
    lines = ["FAIL — 회귀 감지:"]
    for r in result.regressions:
        lines.append(
            f"  - {r.metric}: {r.baseline:.3f} -> {r.current:.3f} "
            f"(하락 {r.drop:+.3f}, 허용 {r.allowed_drop:.3f})"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    # 데모: full 구성을 지금 돌린 점수로 게이트를 통과하는지 본다.
    from run_eval import run_config

    current = run_config("full")
    result = check_regression(current)
    print(format_report(result))
    # CLI 로 쓸 때는 실패 시 exit code 1 을 내보내 CI 가 붉게 뜨게 한다.
    raise SystemExit(0 if result.passed else 1)
