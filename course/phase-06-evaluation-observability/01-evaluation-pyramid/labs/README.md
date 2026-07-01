# Lab — 평가 피라미드 스코어카드 돌려 보기

표준 라이브러리만 쓴다. Neo4j·API 키·설치가 필요 없다. Python 3.11+ 만 있으면 된다.

작업 디렉토리는 `practice/`. 아래 명령은 모두 그 안에서 실행한다.

```bash
cd course/phase-06-evaluation-observability/01-evaluation-pyramid/practice
```

---

## 0단계. 파이썬 버전 확인

```bash
python --version
```

예상 출력:

```
Python 3.11.x     # 또는 그 이상
```

3.11 미만이면 `statistics.fmean` 은 3.8+ 라 동작하지만, 타입 힌트(`set[str]`)가 3.9+ 이므로 3.11+ 를 권장한다.

---

## 1단계. 지표 함수만 단독 확인 (선택)

스코어카드를 돌리기 전에 지표 하나가 어떻게 계산되는지 손으로 확인한다.

```bash
python -c "import metrics as M; print(round(M.context_recall(['c1','c3','c7'], ['c1','c3']), 3))"
```

예상 출력:

```
1.0
```

정답 `c1,c3` 을 모두 가져왔으니 recall = 1.0. 이번엔 precision:

```bash
python -c "import metrics as M; print(round(M.context_precision(['c1','c3','c7'], ['c1','c3']), 3))"
```

예상 출력:

```
0.667
```

3건 가져와 2건이 알짜라 precision = 2/3 ≈ 0.667. recall 은 높은데 precision 이 낮은 전형적인 "많이 긁어온" 검색이다.

---

## 2단계. 전체 스코어카드 출력

```bash
python scorecard.py
```

예상 출력:

```
====================================================
  GraphRAG Evaluation Pyramid — Scorecard
====================================================

[CONSTRUCTION]
  schema_conformance      0.667
  duplicate_rate          0.167 (낮을수록 좋음)
  orphan_rate             0.167 (낮을수록 좋음)

[RETRIEVAL]
  context_recall          0.833
  context_precision       0.444
  hit@3                   1.000

[GENERATION]
  citation_precision      0.750
  citation_recall         0.750
  citation_f1             0.750

[AGENT]
  tool_call_accuracy      0.667
  task_success_rate       0.500

====================================================
```

읽는 법:
- Construction 의 `schema_conformance 0.667` = 노드 6개 중 4개만 스키마를 지켰다. 나머지 2개는 필수 속성 누락(`arxiv_id`)과 허용 안 된 라벨(`Concept`).
- Retrieval 의 `context_precision 0.444` 가 낮다. 근거를 넉넉히 긁어오지만 노이즈가 섞였다는 뜻.
- Agent 의 `task_success_rate 0.500` = 태스크 2개 중 1개 실패. tool-call accuracy 도 0.667 로 낮다.

---

## 3단계. baseline 저장 (회귀 게이트의 씨앗)

지금 점수를 기준선으로 박아 둔다.

```bash
python scorecard.py --save
```

예상 출력(마지막 줄):

```
baseline 저장: .../practice/baseline.json
```

`baseline.json` 파일이 생긴다. 안을 열어 확인:

```bash
cat baseline.json
```

예상 출력(발췌):

```json
{
  "construction": {
    "schema_conformance": 0.6666666666666666,
    "duplicate_rate": 0.16666666666666666,
    "orphan_rate": 0.16666666666666666
  },
  ...
}
```

---

## 4단계. baseline 과 비교 (변화 없음)

방금 저장한 baseline 과 현재 점수를 비교한다. 코드를 안 바꿨으니 전부 OK 여야 한다.

```bash
python scorecard.py --compare
```

예상 출력(끝부분):

```
--- baseline 대비 변화 ---
  [OK  ] construction.schema_conformance: 0.667 -> 0.667 (+0.000)
  ...
  [OK  ] agent.task_success_rate: 0.500 -> 0.500 (+0.000)

회귀(하락) 의심 항목: 0건
```

---

## 5단계. 회귀를 일부러 만들어 게이트 확인

`sample_data.py` 에서 검색 결과를 나쁘게 바꿔 회귀가 잡히는지 본다.
예를 들어 두 번째 검색 케이스의 `retrieved` 에서 정답 `c2` 를 빼 보자.

`sample_data.py` 의 `RETRIEVAL_CASES` 두 번째 항목을 이렇게 고친다:

```python
    {
        "question": "커뮤니티 요약은 어느 논문에서 왔나? (멀티홉)",
        "retrieved": ["c5", "c8"],   # c2 를 제거 → recall 하락
        "relevant": ["c2", "c4"],
    },
```

다시 비교한다:

```bash
python scorecard.py --compare
```

예상 출력(발췌):

```
  [WARN] retrieval.context_recall: 0.833 -> 0.667 (-0.167)
  ...
회귀(하락) 의심 항목: 1건
→ 어느 계층이 무너졌는지부터 본다. Construction 이 흔들리면 위층 점수는 믿을 수 없다.
```

`WARN` 이 뜨면 "다음 변경이 점수를 떨어뜨렸다"는 신호다. 실제 CI 에서 이 신호로 빌드를 막는 게 회귀 게이트다 → 상세는 토픽 04.

실습을 마쳤으면 바꾼 `sample_data.py` 를 되돌리고, 생성된 `baseline.json` 은 지워도 된다.

```bash
rm -f baseline.json
```
