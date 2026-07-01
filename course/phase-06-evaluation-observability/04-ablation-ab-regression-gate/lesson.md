# 6.4 Ablation · A/B · Regression Gate (GraphRAG 개선을 정량 입증)

> **Phase 6 · 토픽 04** · 01의 스코어카드, 02의 Ragas 지표, 03의 Langfuse 관측을 하나로 묶어 "그래프가 정말 점수를 올렸는지" 제거 실험으로 증명하고, 다음 변경이 점수를 깎으면 CI가 자동으로 막게 만든다.

## 학습 목표

이 토픽을 끝내면 다음을 할 수 있다.

- 구성(configuration)을 하나씩 빼는 Ablation 실험을 돌려서 그래프·rerank가 어느 지표를 얼마나 올렸는지 표로 증명한다.
- 두 구성을 같은 골든셋으로 돌려 승패와 평균차로 A/B 비교한다(작은 표본을 과대해석하지 않으면서).
- baseline 대비 하락을 검출하는 회귀 게이트를 pytest로 만들고 GitHub Actions에 걸어서 회귀 PR의 merge를 차단한다.

**완료 기준**: `python ablation.py` 가 `vector_only` 의 `multihop_path_hit` 하락을 표로 보이고, `pytest` 8개가 통과하며, `vector_only` 를 baseline과 비교하면 게이트가 exit code 1을 내면 완료.

---

## 1. 왜 필요한가 — Phase 6를 닫는 안전망

01에서 4계층 스코어카드를 만들었고, 02에서 그 점수를 Ragas로 채점했고, 03에서 왜 그런 점수가 나왔는지 trace로 들여다봤다. 남은 질문은 두 개다. 하나, 그래프를 붙여서 점수가 오른 게 정말 그래프 덕인가? 둘, 다음 변경이 몰래 점수를 깎으면 어떻게 알아채나?

첫 질문에 답이 없으면 GraphRAG를 붙일 이유를 못 댄다. "느낌상 좋아졌다"는 리뷰를 통과하지 못한다. 그래서 그래프를 빼 보고 점수가 떨어지는지 확인한다. 이게 Ablation이다.

둘째 질문에 답이 없으면 3주 뒤 누군가 rerank를 끄는 커밋을 올려도 아무도 모른다. baseline을 박아 두고 새 점수가 그 아래로 떨어지면 자동으로 실패시킨다. 이게 Regression Gate다.

세 스크립트가 전부 같은 코어(`run_eval.py`)를 재사용한다. 구성 이름 하나를 받아 골든셋 전체를 돌리고 지표 dict를 돌려주는 함수다. 상용 API 없이 mock 로그로 돌아가니 로직부터 손에 익히고, 실제 Ragas·Langfuse 연결은 02·03 코드로 갈아 끼우면 된다.

## 2. Ablation — 빼 보면 값어치가 보인다

Ablation의 원리는 단순하다. 어떤 요소가 점수를 올렸다고 주장하려면 그 요소만 빼고 나머지는 똑같이 둔 채 점수가 떨어지는지 본다. 떨어진 만큼이 그 요소의 값어치다.

여기서는 세 구성을 비교한다. `full`(그래프 확장 + rerank 다 켠 GraphRAG), `vector_only`(그래프를 뗀 Phase 1 Baseline), `no_rerank`(그래프는 켜되 rerank만 뗀 구성). 각 구성이 질문마다 무엇을 검색하고 어떤 엣지를 밟았는지가 `configs.py`의 mock 로그에 들어 있다.

```python
# ablation.py 발췌 — full 대비 각 구성의 하락폭(delta)을 표로
ABLATION_CONFIGS = ["full", "vector_only", "no_rerank"]
BASE = "full"   # 하락폭을 재는 기준

def run_ablation() -> dict[str, dict[str, float]]:
    return {name: run_config(name) for name in ABLATION_CONFIGS}
```

```bash
python ablation.py          # 구성별 지표 표 + full 대비 delta
python ablation.py --json   # 표 대신 JSON (다른 도구에 물릴 때)
```

출력을 보면 `vector_only` 열에서 `multihop_path_hit` 이 `1.000 → 0.333` 으로 가장 크게 무너진다. 엣지를 안 밟으니 멀티홉 질문에서 부분 점수만 나온 것이다. `context_recall` 도 함께 떨어졌는데, 그래프로 이어질 근거를 놓쳤다는 신호다. 반면 `no_rerank` 는 `context_precision` 만 떨어진다. 노이즈 청크가 섞여 정밀도가 깎인 것이다. 요소마다 무너지는 지표가 다르다는 게 핵심이다.

## 3. A/B — 둘 중 무엇을 고를까

Ablation이 "이 요소가 값어치가 있나"를 묻는다면, A/B는 "두 후보 중 무엇이 나은가"를 묻는다. Phase 4에서 봤던 LightRAG `hybrid` vs `mix` 같은 선택이다.

두 구성을 같은 골든셋으로 돌려 지표별 평균차와 질문 단위 승/무/패를 센다.

```python
# ab_compare.py 발췌 — 질문 단위 승/무/패 카운트(A 기준)
def win_loss(a_name: str, b_name: str) -> dict[str, dict[str, int]]:
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
```

```bash
python ab_compare.py                            # hybrid vs mix
python ab_compare.py --a full --b vector_only   # 임의 두 구성
```

여기서 조심할 게 하나 있다. 골든셋이 3개뿐이면 평균차 0.1은 확정적 승리가 아니다. 승패 카운트를 보면 대부분 "무(tie)"로 나온다. 통계 검정을 붙일 만큼 표본이 크지도 않다. 그래서 결론은 "`mix` 가 멀티홉에서 유리해 보이나, 골든셋을 키워 재확인" 정도로 정직하게 적는다. 작은 표본에서 소수점을 놓고 승패를 단정하는 게 A/B에서 가장 흔한 자기기만이다.

## 4. Regression Gate — 회귀를 자동으로 막는다

이제 안전망이다. 01에서 baseline을 저장했던 걸 기억하자. 그 baseline을 기준으로 새 실행 점수가 임계값 이상 떨어지면 실패시킨다.

임계값은 두 축으로 설계한다. `abs_tol`(절대 하락 허용치)과 `rel_tol`(상대 하락 허용치) 중 더 관대한 쪽을 통과선으로 쓴다. 작은 baseline에서 상대 허용치만 쓰면 게이트가 너무 빡세지기 때문이다.

```python
# regression_gate.py 발췌 — baseline 대비 하락이 허용선을 넘으면 회귀
def allowed_drop(baseline_value: float, abs_tol: float, rel_tol: float) -> float:
    return max(abs_tol, baseline_value * rel_tol)

def check_regression(current, baseline=None, abs_tol=0.02, rel_tol=0.03) -> GateResult:
    if baseline is None:
        baseline = load_baseline()
    regressions = []
    for metric, base_val in baseline.items():
        cur_val = current[metric]
        drop = base_val - cur_val
        tol = allowed_drop(base_val, abs_tol, rel_tol)
        if drop > tol + _FP_EPS:
            regressions.append(Regression(metric, base_val, cur_val, drop, tol))
    return GateResult(passed=not regressions, regressions=regressions)
```

왜 허용치가 필요한가? LLM 기반 지표(Ragas faithfulness 등)는 같은 입력에도 실행마다 소수점이 흔들린다. 허용치 없이 "조금이라도 떨어지면 실패"로 하면 게이트가 노이즈에 계속 붉어진다(flaky). 그래서 허용 delta를 두고 시드를 고정한 뒤 여러 번 돌려 평균 낸 점수를 쓴다. 이 파일은 허용 delta를 담당한다.

게이트는 pytest로 굳힌다. `assert`로 표현되는 판정이니 별도 프레임워크가 필요 없다. 통과 케이스만 넣으면 안 된다. 회귀를 일부러 만들어 게이트가 잡는지 검증하는 실패 케이스가 진짜 목적이다.

```python
# test_regression_gate.py 발췌 — 회귀 실행은 반드시 걸려야 한다
def test_regressed_run_is_caught():
    regressed = run_config("vector_only")   # 그래프를 뗀 나쁜 구성
    result = check_regression(regressed)
    assert not result.passed, "회귀 실행인데 게이트를 통과했다 — 게이트가 고장난 것"
    dropped = {r.metric for r in result.regressions}
    assert "multihop_path_hit" in dropped   # 멀티홉이 반드시 무너져야
```

```bash
pytest -q                    # 8개 통과 (통과·노이즈 허용·회귀 검출·임계값 경계)
python regression_gate.py    # 현재 full = baseline → PASS, exit 0
```

CI 연결은 GitHub Actions 한 파일이면 된다. PR이 열릴 때마다 파이썬을 깔고 pytest를 돌린다. 회귀가 있으면 pytest가 실패하고, 그 체크를 브랜치 보호 규칙의 required check로 묶으면 붉은 체크가 실제로 merge를 막는다.

```yaml
# .github/workflows/eval-gate.yml 발췌
on:
  pull_request:
    branches: [main]
jobs:
  regression-gate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install -r requirements.txt
      - run: pytest -v   # 회귀 = pytest 실패 = 체크 붉어짐 = merge 차단
```

> 전체 코드와 단계별 실행은 [`practice/`](practice/) 와 [`labs/`](labs/) 참조.
> 이 토픽은 mock 로그로 돌아 상용 API가 필요 없다. 실제 점수를 넣으려면 02의 Ragas 채점 결과와 03의 Langfuse 관측치를 `run_config` 자리에 물리면 되고, 비용이 부담되면 그 단계에서 임베딩을 `bge-m3`(로컬), LLM을 Ollama로 바꿔도 게이트 로직은 그대로다.

## 5. 결과 해석

Ablation 표에서 봐야 할 것은 절대 점수가 아니라 하락폭이다.

```
metric                          full     vector_only       no_rerank
context_recall                 1.000   0.667(-0.333)   1.000(+0.000)
context_precision              1.000   0.667(-0.333)   0.667(-0.333)
multihop_path_hit              1.000   0.333(-0.667)   1.000(+0.000)
entity_coverage                1.000   0.611(-0.389)   1.000(+0.000)
```

`vector_only` 의 `multihop_path_hit` 이 `-0.667` 로 가장 크게 무너졌다. 이 숫자가 곧 "멀티홉을 실제로 밟은 것"의 값어치이고, Phase 1 Baseline 대비 GraphRAG를 붙일 이유의 정량 근거다. `no_rerank` 는 `context_precision` 만 `-0.333` 이니, rerank의 값어치는 정밀도에 있다고 짚을 수 있다.

게이트 쪽은 통과와 실패를 둘 다 봐야 신뢰가 생긴다. `full`(현재 = baseline)은 `PASS` 에 exit 0, `vector_only`(회귀 실행)는 다섯 지표가 전부 허용선(0.030)을 넘겨 `FAIL` 에 exit 1이 뜬다. exit 1이 CI를 붉게 만드는 그 신호다.

이걸로 Phase 6가 닫힌다. 이제 "좋아진 것 같다"가 아니라 이 표와 이 게이트가 통과·실패로 말한다. Phase 7에서 에이전트를 만들고 캡스톤으로 갈 때, 이 게이트가 회귀를 계속 막아 준다.

---

## 🚨 자주 하는 실수

1. **Ablation 없이 "그래프 붙였더니 좋아졌다"고 결론 낸다** — 그래프를 붙인 동시에 청킹·프롬프트·모델도 바꿨다면 무엇이 점수를 올렸는지 알 수 없다. 한 번에 하나만 빼고 나머지는 고정해야 하락폭이 그 요소의 값어치가 된다.
2. **작은 골든셋의 A/B 평균차를 확정적 승리로 읽는다** — 질문 3개에서 평균차 0.1은 노이즈일 수 있다. 승패 카운트가 대부분 무(tie)라면 "판정 보류, 골든셋 확대"가 정직한 결론이다.
3. **회귀 게이트를 허용치 없이 만든다** — "조금이라도 떨어지면 실패"로 하면 LLM 지표의 소수점 흔들림에 게이트가 계속 붉어져(flaky) 결국 다들 무시하게 된다. 허용 delta·시드 고정·반복 평균으로 노이즈를 흡수해야 게이트가 살아남는다.

## 출처

- Ragas 문서 — https://docs.ragas.io/
- Langfuse 문서 — https://langfuse.com/docs
- GraphRAG Survey (Evaluation 파트) — arXiv 2408.08921, https://arxiv.org/abs/2408.08921

## 다음 토픽

→ [Phase 7 · 01 Agent Harness 최소 구조](../../phase-07-agent-harness/01-agent-harness-minimal/lesson.md)
