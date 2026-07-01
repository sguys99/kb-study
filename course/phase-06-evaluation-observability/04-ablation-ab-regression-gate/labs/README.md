# Labs — Ablation · A/B · Regression Gate 핸즈온

이 실습은 상용 API 없이 mock 로그로 돈다. `pytest` 하나만 설치하면 된다.
각 단계에서 무엇이 출력돼야 하는지 함께 적어 두었으니, 네 화면과 대조하라.

## 0. 준비

```bash
cd course/phase-06-evaluation-observability/04-ablation-ab-regression-gate/practice
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

예상 출력(마지막 줄만):

```
Successfully installed ... pytest-8.x.x ...
```

> API 키 불필요. 실제 Ragas 채점·Langfuse 관측은 토픽 02·03 을 참고한다.

---

## 1. 한 구성 돌려 보기 — 지표의 형태 익히기

```bash
python run_eval.py
```

예상 출력:

```
full 구성 점수:
  context_recall       1.000
  context_precision    1.000
  citation_f1          1.000
  multihop_path_hit    1.000
  entity_coverage      1.000
```

`full` 구성(그래프 + rerank 다 켬)은 mock 골든셋에서 모든 지표가 만점이다. 이 값이 baseline.json 과 같다.

---

## 2. Ablation — 요소를 빼면 점수가 떨어지는가

```bash
python ablation.py
```

예상 출력:

```
====================================================================
  Ablation — 구성별 지표 (full 기준 하락폭)
====================================================================
metric                          full     vector_only       no_rerank
--------------------------------------------------------------------
context_recall                 1.000   0.667(-0.333)   1.000(+0.000)
context_precision              1.000   0.667(-0.333)   0.667(-0.333)
citation_f1                    1.000   0.778(-0.222)   1.000(+0.000)
multihop_path_hit              1.000   0.333(-0.667)   1.000(+0.000)
entity_coverage                1.000   0.611(-0.389)   1.000(+0.000)
====================================================================

결론: 그래프를 빼면 multihop_path_hit 이 +0.667 만큼 떨어진다 → 멀티홉을 실제로 밟은 것이 GraphRAG 의 값어치.
```

읽는 법. `vector_only`(그래프 제거) 열을 보면 `multihop_path_hit` 이 1.000 → 0.333 으로 가장 크게 무너졌다. 엣지를 안 밟으니 멀티홉 질문에서 부분 점수만 나온 것이다. `context_recall` 도 떨어졌다 — 그래프로 이어질 근거를 놓쳤다는 뜻. 반면 `no_rerank`(rerank 제거)는 `context_precision` 만 떨어진다. 노이즈 청크가 섞여 정밀도가 깎인 것이다. 이 하락폭이 Phase 1 Baseline 대비 GraphRAG 각 요소의 값어치다.

JSON 으로 뽑아 다른 도구에 물리려면:

```bash
python ablation.py --json
```

---

## 3. A/B — 두 구성 중 무엇을 고를까

```bash
python ab_compare.py
```

예상 출력:

```
=========================================================================
  A/B — A=lightrag_hybrid  vs  B=lightrag_mix  (승/무/패는 A 기준, 질문 단위)
=========================================================================
metric              lightrag_hybrid  lightrag_mix      Δ(A-B)       승/무/패
-------------------------------------------------------------------------
context_recall               1.000         1.000      +0.000       0/3/0
context_precision            1.000         0.889      +0.111       1/2/0
citation_f1                  0.889         1.000      -0.111       0/2/1
multihop_path_hit            0.833         1.000      -0.167       0/2/1
entity_coverage              0.833         1.000      -0.167       0/2/1
=========================================================================

지표 평균 기준: A 우세 1개 / B 우세 3개
```

읽는 법. `mix` 가 멀티홉·엔티티·인용에서 앞선다(전역 요약을 섞어 q3 의 2홉을 다 밟았다). `hybrid` 는 정밀도만 근소 우세. 골든셋이 단 3개라 평균차 0.1 대는 확정적 승리가 아니다 — 승패 카운트도 대부분 "무(tie)"다. 결정은 "mix 가 멀티홉에서 유리해 보이나, 골든셋을 키워 재확인" 정도로 적는다.

임의의 두 구성을 붙여 볼 수도 있다(그래프 값어치를 A/B 로도 확인):

```bash
python ab_compare.py --a full --b vector_only
```

---

## 4. Regression Gate — 통과와 실패를 둘 다 재현

### 4-1. 통과 (현재 full = baseline)

```bash
python regression_gate.py
echo "exit code: $?"
```

예상 출력:

```
PASS — baseline 대비 회귀 없음.
exit code: 0
```

### 4-2. pytest 로 게이트 굳히기

```bash
pytest -q
```

예상 출력:

```
........                                                                 [100%]
8 passed in 0.0Xs
```

8개 테스트에는 통과 케이스(회귀 없음·노이즈 허용), 실패를 '기대'로 검증하는 케이스(회귀 실행이 잡히는지), 임계값 경계 3종이 들어 있다.

### 4-3. 실패 재현 — 회귀를 만들어 게이트가 잡는지 본다

`vector_only`(그래프를 뗀 나쁜 구성)를 baseline 과 비교하면 게이트가 붉어져야 한다.

```bash
python -c "from regression_gate import check_regression, format_report; from run_eval import run_config; import sys; r=check_regression(run_config('vector_only')); print(format_report(r)); sys.exit(0 if r.passed else 1)"
echo "exit code: $?"
```

예상 출력:

```
FAIL — 회귀 감지:
  - context_recall: 1.000 -> 0.667 (하락 +0.333, 허용 0.030)
  - context_precision: 1.000 -> 0.667 (하락 +0.333, 허용 0.030)
  - citation_f1: 1.000 -> 0.778 (하락 +0.222, 허용 0.030)
  - multihop_path_hit: 1.000 -> 0.333 (하락 +0.667, 허용 0.030)
  - entity_coverage: 1.000 -> 0.611 (하락 +0.389, 허용 0.030)
exit code: 1
```

exit code 1 이 곧 CI 를 붉게 만드는 신호다. "그래프를 빼는 PR" 이 이런 exit 1 을 내면 merge 가 막힌다.

---

## 5. CI 연결 — PR 마다 게이트를 돌린다

`practice/.github/workflows/eval-gate.yml` 을 저장소 루트의 `.github/workflows/` 로 옮기면(또는 루트에 같은 내용으로 만들면), PR 이 열릴 때마다 GitHub Actions 가 이 순서로 돈다.

1. `actions/checkout@v4` 로 코드를 받는다.
2. `actions/setup-python@v5` 로 Python 3.11 을 깐다.
3. `pip install -r requirements.txt` 로 pytest 를 설치한다.
4. `pytest -v` 를 돌린다. 회귀가 있으면 pytest 가 실패하고, 이 체크가 붉어진다.

마지막으로 GitHub 저장소 설정에서 브랜치 보호 규칙(Branch protection rules)의 "Require status checks to pass before merging" 에 `eval-gate / regression-gate` 를 required 로 지정한다. 그래야 붉은 체크가 실제로 merge 를 막는다.

로컬에서 CI 와 같은 명령을 미리 돌려 확인:

```bash
pytest -v
```

예상 출력(발췌):

```
test_regression_gate.py::test_baseline_file_loads PASSED
test_regression_gate.py::test_full_config_passes_gate PASSED
test_regression_gate.py::test_tiny_noise_within_tolerance_passes PASSED
test_regression_gate.py::test_regressed_run_is_caught PASSED
test_regression_gate.py::test_regressed_run_would_fail_ci PASSED
test_regression_gate.py::test_threshold_boundary[0.01-0.02-True] PASSED
test_regression_gate.py::test_threshold_boundary[0.02-0.02-True] PASSED
test_regression_gate.py::test_threshold_boundary[0.05-0.02-False] PASSED
8 passed in 0.0Xs
```

---

## 정리 체크리스트

- [ ] Ablation 표에서 `vector_only` 의 `multihop_path_hit` 하락을 눈으로 확인했다.
- [ ] A/B 결과를 "승패 카운트 + 평균차"로 읽고, 작은 표본을 과대해석하지 않았다.
- [ ] 게이트가 full 에서 통과(exit 0), vector_only 에서 실패(exit 1) 하는 것을 둘 다 봤다.
- [ ] `pytest` 8개가 모두 통과했다.
- [ ] `eval-gate.yml` 을 루트로 옮기고 required check 로 지정하면 회귀가 merge 를 막는다는 것을 이해했다.
