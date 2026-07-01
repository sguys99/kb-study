# test_regression_gate.py — 회귀 게이트를 pytest 로 굳힌다 (통과 케이스 + 실패 케이스)
#
# 왜 pytest 인가:
#   게이트는 "assert 로 표현되는 판정"이다. pytest 가 이 assert 를 CI 에서 돌려,
#   실패하면 exit code 로 merge 를 막는다. 별도 프레임워크가 필요 없다.
#
# 이 파일은 두 가지를 다 보여 준다:
#   1) 통과: 현재 full 구성 점수는 baseline 과 같으므로 게이트를 통과해야 한다.
#   2) 실패: 일부러 점수를 떨어뜨린 '회귀 실행'을 넣으면 게이트가 잡아야 한다.
#      → 회귀를 잡는 것이 이 파일의 진짜 목적이므로, 실패를 '기대'로 검증한다
#        (게이트가 통과해 버리면 그게 버그다).
#
# 실행:
#   pip install -r requirements.txt
#   pytest -v
#
# 전제: 외부 의존은 pytest 뿐. LLM/Ragas/Langfuse 없이 mock 로그로 돈다.

from __future__ import annotations

import pytest

from regression_gate import check_regression, load_baseline
from run_eval import run_config


# --------------------------------------------------------------------------
# 1) 통과 케이스 — 회귀가 없어야 게이트가 초록불
# --------------------------------------------------------------------------

def test_baseline_file_loads():
    """baseline.json 이 읽히고 기대한 지표 키를 담고 있다."""
    baseline = load_baseline()
    assert "multihop_path_hit" in baseline
    assert 0.0 <= baseline["multihop_path_hit"] <= 1.0


def test_full_config_passes_gate():
    """현재 full 구성 점수는 baseline 대비 회귀가 없어야 한다(게이트 통과)."""
    current = run_config("full")
    result = check_regression(current)
    assert result.passed, f"회귀가 잡혔다(예상 밖): {result.regressions}"


def test_tiny_noise_within_tolerance_passes():
    """허용치 안쪽의 미세 하락(노이즈)은 통과해야 한다 — flaky 방지의 핵심."""
    baseline = load_baseline()
    # 모든 지표를 0.01 씩 낮춘 실행: abs_tol=0.02 안쪽 → 통과
    noisy = {m: max(0.0, v - 0.01) for m, v in baseline.items()}
    result = check_regression(noisy, baseline, abs_tol=0.02, rel_tol=0.03)
    assert result.passed, f"노이즈 수준 하락인데 회귀로 잡힘: {result.regressions}"


# --------------------------------------------------------------------------
# 2) 실패 케이스 — 회귀를 '만들어' 게이트가 잡는지 검증
# --------------------------------------------------------------------------

def make_regressed_run() -> dict[str, float]:
    """그래프를 뗀 것과 같은 회귀 실행을 흉내 낸다(vector_only 점수).

    실전에서 이런 값은 '나쁜 PR' 이 만든다: rerank 를 끄거나 그래프 확장을 빠뜨리면
    multihop_path_hit·context_recall 이 baseline 아래로 떨어진다.
    """
    return run_config("vector_only")


def test_regressed_run_is_caught():
    """회귀 실행은 게이트에서 반드시 걸려야 한다(passed=False)."""
    regressed = make_regressed_run()
    result = check_regression(regressed)
    assert not result.passed, "회귀 실행인데 게이트를 통과했다 — 게이트가 고장난 것"
    # 어떤 지표가 무너졌는지도 확인: 멀티홉이 반드시 끼어야 한다
    dropped = {r.metric for r in result.regressions}
    assert "multihop_path_hit" in dropped


def test_regressed_run_would_fail_ci():
    """CI 에서 실제로 빌드를 세우는 것은 이 assert 다.

    '회귀면 실패'를 CI 관점으로 다시 쓴 것: 회귀 실행에 대해 이 assert 는 실패한다.
    (여기서는 그 실패를 pytest.raises 로 감싸 '실패가 나는 것'을 검증한다.
     .github/workflows/eval-gate.yml 에서는 감싸지 않고 그대로 두어 CI 를 붉게 만든다.)
    """
    regressed = make_regressed_run()
    result = check_regression(regressed)
    with pytest.raises(AssertionError):
        assert result.passed, "회귀 감지 — merge 를 막는다"


# --------------------------------------------------------------------------
# 3) 임계값 경계 — abs/rel 허용치가 의도대로 동작하나 (파라미터화)
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "drop, abs_tol, expect_pass",
    [
        (0.01, 0.02, True),    # 허용 안쪽 → 통과
        (0.02, 0.02, True),    # 허용선 정확히 → 통과(초과가 아님)
        (0.05, 0.02, False),   # 허용 초과 → 회귀
    ],
)
def test_threshold_boundary(drop, abs_tol, expect_pass):
    """단일 지표를 정해진 만큼 떨어뜨려 허용치 경계 동작을 고정한다."""
    baseline = {"context_recall": 0.90}
    current = {"context_recall": 0.90 - drop}
    result = check_regression(current, baseline, abs_tol=abs_tol, rel_tol=0.0)
    assert result.passed is expect_pass
