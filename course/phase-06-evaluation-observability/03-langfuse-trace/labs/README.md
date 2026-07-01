# Lab 6.3 — Langfuse Trace 로 검색 경로·Cost·Latency 관측

한 질문이 파이프라인을 통과하는 흔적(trace)을 남기고, 그 트리를 읽는다.
두 갈래로 진행한다. **A: 키 없이 콘솔 트레이서로 구조 먼저 이해** → **B: Langfuse self-host 로 UI 에서 확인**.
서버가 부담되면 A 만으로도 이 토픽의 핵심(경로·비용·지연·점수 연결)은 전부 확인된다.

전제: Python 3.11+, (B 에서만) Docker / Docker Compose.

```bash
cd course/phase-06-evaluation-observability/03-langfuse-trace/practice
pip install -r requirements.txt
```

---

## A. 키 없이 — 콘솔 트레이서로 span 트리 읽기

### A-1. 스텁 LLM + 콘솔 트레이서 실행 (API 호출 0, 과금 0)

```bash
env -u LANGFUSE_PUBLIC_KEY -u LANGFUSE_SECRET_KEY -u LANGFUSE_HOST \
    python rag_pipeline.py
```

예상 출력(값은 latency 만 조금 다를 수 있다):

```
[trace_util] Langfuse 키 없음 → 콘솔 트레이서로 대체(전송 안 함).
┌─ [SPAN] retrieval  (input={'question': '커뮤니티 요약 기법은 어느 논문에서…)
  ┌─ [TOOL] docs_search  (input={'query': '커뮤니티 요약 기법은 어느 논문에서 …)
  └─ [TOOL] docs_search  latency=10.x ms  (output={'hit_ids': ['c2', 'c4']})
  ┌─ [TOOL] graph_query  (input={'seed_entities': ['community summary', …)
  └─ [TOOL] graph_query  latency=10.x ms  (output={'edges': [{'head': 'From Local…)
  ┌─ [GEN] generate_answer  (input={'prompt': '커뮤니티 요약 기법은 …)
  └─ [GEN] generate_answer  latency=0.x ms  model=claude-3-5-sonnet-latest  tokens={'prompt_tokens': …, 'completion_tokens': …, 'total_tokens': …}  cost=$0.0000xx  (output=커뮤니티 요약은 From Local to…)
└─ [SPAN] retrieval  latency=2x.x ms  (output={'n_contexts': 4, 'path': 'vector→graph'})
[SCORE] faithfulness = 0.92  # 02 Ragas 결과에서 가져옴
[SCORE] context_recall = 1.0
────────────────────────────────────────────────────────────
[TRACE] input : {'question': '커뮤니티 요약 기법은 어느 논문에서…}
[TRACE] output: {'answer': '커뮤니티 요약은 From Local to Global 이…}
[TRACE] spans=4  total_cost=$0.0000xx
[TRACE] scores: faithfulness=0.92, context_recall=1.0
(콘솔 트레이서: 실제 Langfuse 로 보내려면 세 키를 설정하고 다시 실행)

== 최종 답변 ==
커뮤니티 요약은 From Local to Global 이 제안했고 Leiden 알고리즘을 쓴다.
(tokens=…, cost=$0.0000xx)
```

읽는 법:
- 들여쓰기 = span 트리 깊이. `retrieval` 아래 `docs_search`(vector) → `graph_query`(graph) 순서가 **검색 경로**다.
- 각 `└─` 줄의 `latency` 가 스텝별 지연. `generate_answer` 의 `tokens`·`cost` 가 그 LLM 호출의 비용.
- 맨 아래 `[TRACE]` 요약이 이 요청 한 건의 총 span 수·총 비용, 그리고 붙인 점수다.
- 점수 두 줄이 02 Ragas 결과를 이 trace 에 연결한 것 — "이 실행의 faithfulness=0.92".

### A-2. 실제 LLM 만 켜기(과금, Langfuse 는 여전히 콘솔)

`ANTHROPIC_API_KEY` 가 있으면 답변만 실제 Claude 로 생성한다. `tokens`·`cost` 가 스텁 근사치가 아닌 실측치로 바뀐다.

```bash
export ANTHROPIC_API_KEY=sk-ant-...
python rag_pipeline.py --real-llm
```

예상: `generate_answer` span 의 `tokens={'prompt_tokens': <실측>, 'completion_tokens': <실측>, …}`, `cost` 가 실제 단가로 계산되고, 최종 답변 텍스트가 매 실행 조금씩 달라진다.

---

## B. Langfuse self-host — UI 에서 trace 확인

### B-1. 서버 기동

```bash
docker compose up -d
```

예상 출력(요약):

```
[+] Running 6/6
 ✔ Network …_default        Created
 ✔ Container …-postgres-1    Healthy
 ✔ Container …-clickhouse-1  Healthy
 ✔ Container …-redis-1       Healthy
 ✔ Container …-minio-1       Healthy
 ✔ Container …-langfuse-1    Started
```

### B-2. 헬스체크 — 기동 확인

```bash
docker compose ps
```

예상: 모든 서비스 `running`, 백엔드 4개(postgres·clickhouse·redis·minio)는 `(healthy)`. langfuse 는 마이그레이션에 20~60초 걸릴 수 있다.

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:3000/api/public/health
```

예상 출력:

```
200
```

`200` 이 아니면 아직 기동 중이다. `docker compose logs -f langfuse` 로 `Ready` 로그를 기다린다.

### B-3. 계정·프로젝트·API 키 발급

브라우저로 `http://localhost:3000` 접속 → 계정 생성 → 프로젝트 생성 → **Settings → API Keys** 에서 Public/Secret 키 발급. 발급 화면에 나오는 값을 환경변수로 내보낸다.

```bash
export LANGFUSE_HOST=http://localhost:3000
export LANGFUSE_PUBLIC_KEY=pk-lf-...
export LANGFUSE_SECRET_KEY=sk-lf-...
```

### B-4. 파이프라인을 실제 Langfuse 로 전송

```bash
python rag_pipeline.py           # 세 키가 있으면 자동으로 Langfuse 로 전송
```

예상 출력(콘솔은 짧아진다 — 트리는 서버로 감):

```
[trace_util] Langfuse 로 전송한다 → http://localhost:3000

== 최종 답변 ==
커뮤니티 요약은 From Local to Global 이 제안했고 Leiden 알고리즘을 쓴다.
(tokens=…, cost=$0.0000xx)
```

> `flush()` 가 스크립트 끝에서 호출돼야 서버로 전송된다. 콘솔에 트리가 안 보이는 건 정상 — 트리는 UI 에서 본다.

### B-5. UI 에서 trace 읽기

`http://localhost:3000` → **Tracing → Traces** 목록에서 방금 실행이 한 줄로 뜬다.

- 그 줄을 클릭하면 **span 트리**가 왼쪽에 나온다: `answer_question`(trace) 아래 `retrieval` → 그 아래 `docs_search`·`graph_query`, 그리고 `generate_answer`.
- 각 span 을 누르면 오른쪽에 **Latency**(ms), 입력/출력이 뜬다. `generate_answer` 에는 **Model·Usage(tokens)·Cost** 가 별도 표시된다.
- trace 헤더에서 이 요청의 **총 비용·총 지연**을 한눈에 본다.
- **Scores** 탭(또는 trace 우측)에 `faithfulness=0.92`, `context_recall=1.0` 이 붙어 있다 — 02 Ragas 점수와 이 실행이 연결된 지점이다.

### B-6. 정리

```bash
docker compose down          # 컨테이너 중지(데이터는 볼륨에 남음)
# docker compose down -v     # 볼륨까지 삭제(완전 초기화)
```

---

## 확인 체크리스트

- [ ] A-1 에서 `retrieval → docs_search → graph_query → generate_answer` 순서의 span 트리가 콘솔에 찍힌다.
- [ ] `generate_answer` span 에 model·tokens·cost 가 함께 나온다.
- [ ] `[TRACE]` 요약에 총 span 수·총 비용·연결된 점수(faithfulness·context_recall)가 보인다.
- [ ] (B) `curl .../api/public/health` 가 `200` 을 반환한다.
- [ ] (B) Langfuse UI Traces 에서 같은 트리와 Cost·Latency·Scores 를 확인한다.
