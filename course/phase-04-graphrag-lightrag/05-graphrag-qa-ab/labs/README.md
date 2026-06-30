# 4.5 핸즈온 — GraphRAG Q&A A/B 리더보드 만들기

같은 골든 질문 위에 Vector·Local·Global·Hybrid 네 전략을 세우고, 정답 근거 포함률로 리더보드를 낸다. 각 명령에 **예상 출력**을 붙였다. 네 화면이 맞는지 대조하면서 따라가면 된다.

## 준비

작업 폴더는 `practice/` 다. 명령은 `python3` 기준이며, 환경에 따라 `python` 으로 바꿔도 된다.

```bash
cd course/phase-04-graphrag-lightrag/05-graphrag-qa-ab/practice
```

**과금 0 경로가 기본이다.** 골든셋·전략·지표·러너는 표준 라이브러리만으로 끝까지 돈다. 키도 설치도 필요 없다. Hybrid 전략은 4.4 의 `fusion_pipeline` 을 그대로 끌어 쓰는데, reranker 가 없으면 융합 점수를 그대로 쓰는 identity 폴백으로, `tiktoken` 이 없으면 char/4 근사로 떨어진다.

**상용 경로는 선택이다.** 더 정확한 재순위를 원하면 둘 중 하나를 켠다.

```bash
# (선택 A) 상용 reranker — rerank-2.5
export VOYAGE_API_KEY=...        # 키는 환경변수로. 코드에 하드코딩하지 않는다
pip install voyageai

# (선택 B) 로컬 reranker — 키 0
pip install sentence-transformers   # BAAI/bge-reranker-v2-m3 자동 다운로드
```

> 전제: 4.4 산출물(`../../04-vector-graph-fusion/practice/`)이 같은 위치에 있어야 한다. 05 의 코드가 그 폴더를 `sys.path` 에 올려 `candidates`·`fusion_pipeline` 등을 import 한다.

---

## 1단계 — 골든셋 확인

질문 수·type 분포·gold 라벨을 먼저 본다.

```bash
python3 goldenset.py
```

예상 출력:

```
[골든셋] 질문 9개
[type 분포] simple-fact=3, multi-hop=3, global-summary=3

  q1 [  simple-fact] gold=['q1_v1'] 풀(vec 3/graph 2)  VoyageAI 의 기본 임베딩 모델 이름은 무엇인가?…
  q2 [  simple-fact] gold=['q2_v1'] 풀(vec 3/graph 2)  LightRAG 를 만든 곳은 어디인가?…
  q3 [  simple-fact] gold=['q3_v1'] 풀(vec 3/graph 1)  RRF 의 평활 상수 k 로 흔히 쓰는 값은?…
  q4 [    multi-hop] gold=['q4_g1', 'q4_g2'] 풀(vec 3/graph 3)  Neo4j 와 RAG 는 어떻게 연결되며, 그 사이에서 Lig…
  q5 [    multi-hop] gold=['q5_g1', 'q5_g2'] 풀(vec 3/graph 3)  Ragas 로 측정한 점수는 결국 무엇과 비교되며, 그 기준선…
  q6 [    multi-hop] gold=['q6_g1'] 풀(vec 3/graph 2)  voyage-3.5 임베딩으로 만든 벡터는 어느 저장소에 인덱…
  q7 [global-summary] gold=['q7_g1'] 풀(vec 3/graph 3)  이 코퍼스에서 검색 기법 관련 개념들은 전체적으로 어떻게 묶이…
  q8 [global-summary] gold=['q8_g1'] 풀(vec 3/graph 2)  평가와 관측성 쪽 도구들은 전체적으로 어떤 그림을 이루나?…
  q9 [global-summary] gold=['q9_g1', 'q9_g2'] 풀(vec 2/graph 3)  이 코퍼스 전체를 큰 주제 묶음으로 나누면 어떻게 되나?…

[다음] python strategies.py 로 한 질문에 네 전략을 세워 본다.
```

확인 포인트: type 이 3개씩 균형 잡혀 있고, 멀티홉·요약 질문은 gold 가 graph 후보(`*_g*`)에, 단순 사실은 vector 후보(`*_v*`)에 걸려 있다.

## 2단계 — 지표 동작 확인

채점에 쓸 세 지표가 어떻게 계산되는지 작은 예시로 본다.

```bash
python3 metrics.py
```

예상 출력:

```
[예시] ranked=['g1', 'v2', 'g3', 'v1'], gold=['g1', 'v1'], k=3
  recall@3 = 0.500   (상위3 ['g1', 'v2', 'g3'] 안 gold 1/2)
  mrr      = 1.000   (첫 gold g1 이 1등 → 1/1)
  hit@3    = 1.000   (상위3 안에 gold 있음)

[다음] python ab_runner.py 로 전체 골든셋 × 네 전략에 이 지표를 적용한다.
```

## 3단계 — 한 질문에 네 전략 세우기

멀티홉 질문(q4)에 네 전략이 어떤 순위를 내는지 눈으로 본다. `★` 가 gold 근거다.

```bash
python3 strategies.py q4
```

예상 출력:

```
[질문 q4] Neo4j 와 RAG 는 어떻게 연결되며, 그 사이에서 LightRAG 는 무슨 역할을 하나?
[gold 근거] ['q4_g1', 'q4_g2']

[Vector] 상위 3개:
    1. q4_v1 [   vector] score= 0.80  LightRAG 는 검색 단계에서 벡터 인덱스와 그래프 인덱스를 함께 쓰는 R…
    2. q4_v2 [   vector] score= 0.74  RAG 는 외부 문서를 임베딩해 벡터 검색으로 top-k 청크를 가져와 LLM…
    3. q4_v3 [   vector] score= 0.70  Neo4j 는 LPG(레이블드 프로퍼티 그래프) 모델의 그래프 데이터베이스다.…

[Local] 상위 2개:
  ★ 1. q4_g1 [     path] score= 3.00  [Path] Neo4j -[USES]- LightRAG -[IMPLEMENTS…
  ★ 2. q4_g2 [    local] score= 0.92  [Local] LightRAG 의 1홉 이웃: LightRAG -[IMPLEM…

[Global] 상위 1개:
    1. q4_g3 [community] score= 5.00  [Community] 커뮤니티 0(검색 기법): RAG·GraphRAG·Lig…

[Hybrid] 상위 5개:
    1. q4_v1 [   vector] score= 0.80  LightRAG 는 검색 단계에서 벡터 인덱스와 그래프 인덱스를 함께 쓰는 R…
    2. q4_g3 [community] score= 5.00  [Community] 커뮤니티 0(검색 기법): RAG·GraphRAG·Lig…
    3. q4_v2 [   vector] score= 0.74  RAG 는 외부 문서를 임베딩해 벡터 검색으로 top-k 청크를 가져와 LLM…
  ★ 4. q4_g1 [     path] score= 3.00  [Path] Neo4j -[USES]- LightRAG -[IMPLEMENTS…
    5. q4_v3 [   vector] score= 0.70  Neo4j 는 LPG(레이블드 프로퍼티 그래프) 모델의 그래프 데이터베이스다.…

[해석] ★ 가 gold 근거다. 어느 전략이 ★ 를 위로 끌어올렸는지 본다.
[다음] python ab_runner.py 로 전체 골든셋 × 네 전략 리더보드를 낸다.
```

읽는 법: Vector 의 상위 3개에는 `★` 가 하나도 없다. 멀티홉 정답 근거가 graph 후보에 있는데 Vector 는 그걸 아예 못 본다. Local 은 `★` 둘을 1·2등으로 끌어올린다. Hybrid 는 vector·graph 를 섞다 보니 과금 0 폴백에서는 gold 가 4등으로 처진다 — 진짜 reranker 를 붙이면 위로 올라간다(5단계).

다른 질문도 같은 방식으로 본다. 단순 사실은 `python3 strategies.py q1`, 전체요약은 `python3 strategies.py q7`.

## 4단계 — A/B 리더보드

전체 골든셋 × 네 전략을 한 번에 돌려 리더보드를 낸다. 이 토픽의 결론이 여기서 나온다.

```bash
python3 ab_runner.py
```

예상 출력:

```
============================================
 GraphRAG Q&A A/B 리더보드  (k=3)
============================================

[전체 리더보드 (전략 × 지표)]
  전략        recall@3     mrr  hit_rate
  ------------------------------------
  Vector       0.333   0.333     0.333
  Local        0.333   0.333     0.333
  Global       0.333   0.333     0.333
  Hybrid       0.722   0.611     0.778
  → recall@3 최고: Hybrid

  [Baseline(Vector) 대비 Hybrid] recall@3: 0.333 → 0.722 (+0.389)

--------------------------------------------
 type별 분해 — 어느 모드가 어디서 이기나
--------------------------------------------

[simple-fact  (질문 3개)]
  전략        recall@3     mrr  hit_rate
  ------------------------------------
  Vector       1.000   1.000     1.000
  Local        0.000   0.000     0.000
  Global       0.000   0.000     0.000
  Hybrid       1.000   1.000     1.000
  → recall@3 최고: Vector

[multi-hop  (질문 3개)]
  전략        recall@3     mrr  hit_rate
  ------------------------------------
  Vector       0.000   0.000     0.000
  Local        1.000   1.000     1.000
  Global       0.000   0.000     0.000
  Hybrid       0.333   0.333     0.333
  → recall@3 최고: Local

[global-summary  (질문 3개)]
  전략        recall@3     mrr  hit_rate
  ------------------------------------
  Vector       0.000   0.000     0.000
  Local        0.000   0.000     0.000
  Global       1.000   1.000     1.000
  Hybrid       0.833   0.500     1.000
  → recall@3 최고: Global

[해석] Vector 는 simple-fact 에 강하고 multi-hop·global-summary 에서 무너진다.
       Local 은 multi-hop, Global 은 global-summary 에서 앞서고, Hybrid 가 종합 최고다.
[다음] → 06-why-lightrag: 이 네 전략을 LightRAG 5모드로 한 프레임워크에 담는다.
```

## 5단계 — type별 분해 해석 + 백엔드 바꿔 보기

4단계 표를 type 으로 읽는다.

- **simple-fact**: Vector 1.000, Hybrid 1.000. 답이 한 청크에 있으니 벡터 검색이 곧장 잡고, Hybrid 도 그걸 지킨다.
- **multi-hop**: Vector 0.000 으로 완전히 무너진다(Phase 0 의 실패). Local 이 1.000 으로 압도하고, Hybrid 가 0.333 으로 회복을 시작한다.
- **global-summary**: Vector 0.000, Global 1.000, Hybrid 0.833. 전체 조망은 Community 요약과 Hybrid 의 몫이다.

핵심은 마지막 줄이다 — **Baseline(Vector) 대비 Hybrid 가 +0.389**. 단일 모드는 한 type 에서만 강하지만, Hybrid 는 type 을 가로질러 살아남아 종합 최고가 된다.

k 를 늘리면 Hybrid 의 우위가 더 벌어진다.

```bash
python3 ab_runner.py --k 5
```

예상 출력(앞부분):

```
============================================
 GraphRAG Q&A A/B 리더보드  (k=5)
============================================

[전체 리더보드 (전략 × 지표)]
  전략        recall@5     mrr  hit_rate
  ------------------------------------
  Vector       0.333   0.333     0.333
  Local        0.333   0.333     0.333
  Global       0.333   0.333     0.333
  Hybrid       0.889   0.611     1.000
  → recall@5 최고: Hybrid

  [Baseline(Vector) 대비 Hybrid] recall@5: 0.333 → 0.889 (+0.556)
```

진짜 reranker 를 붙이면 멀티홉에서 graph 근거가 위로 올라가 Hybrid 점수가 더 오른다. 백엔드를 강제 지정해 본다(설치돼 있을 때).

```bash
python3 ab_runner.py --backend local      # 로컬 cross-encoder, 키 0
# 또는 VOYAGE_API_KEY 를 export 한 뒤
python3 ab_runner.py --backend voyage     # 상용 rerank-2.5
```

reranker 가 없는 환경에서 `--backend local` 을 주면 04 의 폴백 규약대로 identity 로 떨어진다. 위 4단계 표와 같은 숫자가 나오면 정상이다.

---

다 끝났다면 리더보드가 "Vector 는 단순 사실, Local 은 멀티홉, Global 은 요약, Hybrid 가 종합 최고"를 숫자로 말하는지 확인한다. 이게 Phase 1 기준선을 넘어선 증거다. 다음은 이 네 전략을 한 프레임워크로 묶는 LightRAG 다 → [06-why-lightrag](../../06-why-lightrag/lesson.md)
