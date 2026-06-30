# 핸즈온 — 청크에서 Relation·Claim·Event 추출

2/02 가 만든 `entities.jsonl`(점)과 1/05 청크를 입력으로 받아, 점 사이의 Relation(선)과
근거·수치를 보존하는 Claim, 시간·다자 사건을 담는 Event 를 뽑는다. 기본 경로는 mock(규칙
기반)이라 API 키·네트워크 없이 로컬에서 돈다. Claude 백엔드는 선택이다.

## 사전 준비

```bash
cd course/phase-02-knowledge-graph/03-relation-claim-event/practice
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

`requirements.txt` 의 필수는 `pydantic>=2` 뿐이다. anthropic·instructor 는 LLM 백엔드를
쓸 때만 설치한다(파일 주석 참고).

이 토픽은 2/01 의 `graph_schema.py` 를 import 로 재사용한다(스키마 재정의 금지). 디렉토리
구조가 그대로면 `schema_adapter.py` 가 `../../01-text-to-graph-schema/practice/` 를 자동으로 찾는다.
`sample_chunks.jsonl` 과 `entities.jsonl` 은 자립 실행용으로 동봉돼 있어(2/02 출력과 호환),
앞 토픽을 돌리지 않아도 이 디렉토리만으로 끝까지 실행된다.

---

## step 1 — 스키마 재사용 + RCE 모델 import 확인

스키마를 새로 만들지 않았다. 2/01 것에서 Relation·Claim·Event 까지 끌어왔는지 본다.

```bash
python3 -c "from schema_adapter import Relation, RelationType, Claim, Event; print([t.value for t in RelationType])"
```

예상 출력:

```
['PROPOSES', 'IMPROVES', 'EVALUATED_ON', 'MEASURED_BY', 'COMPARES_TO', 'USES', 'CITES']
```

관계 7종이 그대로 나오면 2/01 통제 어휘가 정상 import 된 것이다. 여기서 타입을 다시 정의하지 않는다.

---

## step 2 — 단일 청크 mock 추출(수치·시점 보존 확인)

`extract_relations.py` 를 직접 실행하면 수치·연도를 담은 샘플 청크 1건을 mock 으로 뽑는다.

```bash
python3 extract_relations.py
```

예상 출력:

```
청크 src-05-lightrag::c021 에서 mock 추출:
  CLAIM  LightRAG reduces_token_cost value='99%' body[3000:3034] quote='LightRAG reduces token cost by 99%'
  EVENT  RAG_publication participants=['RAG', 'NeurIPS'] time='2020' body[3057:3093] quote='RAG was published at NeurIPS in 2020'
```

두 가지를 확인한다. `value='99%'` 는 `0.99` 로 변환되지 않고 surface 그대로다. `time='2020'`
도 그대로다. 그리고 둘 다 근거 quote 안에 그 값(`99%`, `2020`)이 실제로 들어 있다 — 이게
다음 단계 환각 검증의 발판이다. `body[...]` 는 청크 로컬이 아니라 문서 body offset 으로
환산돼 있다(`char_start=3000` 만큼 밀렸다).

---

## step 3 — 전체 파이프라인: 추출 → 검증 → 3개 jsonl 저장

```bash
python3 run_extract_rce.py
```

예상 출력:

```
청크 4건 · 엔티티 16건 로드 — backend=mock
  src-05-lightrag::c012        → R 1 / C 0 / E 0
  src-02-self-rag::c003        → R 1 / C 0 / E 0
  src-04-graphrag::c008        → R 1 / C 0 / E 0
  src-05-lightrag::c021        → R 0 / C 1 / E 1

=== RCE 검증 리포트 ===
총 후보 5건 — accept 5 (R 3 / C 1 / E 1) / reject 0
--- relations (accepted) ---
  [OK] (LightRAG) -[USES]-> (Neo4j)  src=src-05-lightrag
  [OK] (Self-RAG) -[IMPROVES]-> (RAG)  src=src-02-self-rag
  [OK] (LightRAG) -[COMPARES_TO]-> (GraphRAG)  src=src-04-graphrag
--- claims (accepted) ---
  [OK] LightRAG reduces_token_cost value='99%'  src=src-05-lightrag
--- events (accepted) ---
  [OK] RAG_publication participants=['RAG', 'NeurIPS'] time='2020'  src=src-05-lightrag
--- warnings (다음 단계가 볼 것) ---
  [WARN] (event) dangling 참조: ['NeurIPS'] (raw=RAG_publication)

저장: relations.jsonl(3) claims.jsonl(1) events.jsonl(1) — 다음 토픽(2/04·2/05)의 입력
```

세 관계 + 한 클레임 + 한 이벤트가 통과했다. `NeurIPS` 는 2/02 엔티티 집합에 없어 dangling
경고가 떴다(reject 아님 — 기본 정책). 세 파일이 생겼는지 본다.

```bash
cat relations.jsonl
```

예상 출력(키 순서는 다를 수 있다):

```
{"head":"LightRAG","type":"USES","tail":"Neo4j","provenance":{"source_id":"src-05-lightrag","version":"v1@ab12cd34","start":1200,"end":1342,"quote":"LightRAG is a graph-based RAG framework from HKUDS. It supports naive, local, global, hybrid, mix retrieval modes and stores entities in Neo4j"}}
{"head":"Self-RAG","type":"IMPROVES","tail":"RAG","provenance":{"source_id":"src-02-self-rag","version":"v1@77aa00bb","start":640,"end":661,"quote":"Self-RAG improves RAG"}}
{"head":"LightRAG","type":"COMPARES_TO","tail":"GraphRAG","provenance":{"source_id":"src-04-graphrag","version":"v1@deadbeef","start":2138,"end":2167,"quote":"LightRAG compares to GraphRAG"}}
```

```bash
cat claims.jsonl events.jsonl
```

예상 출력:

```
{"subject":"LightRAG","predicate":"reduces_token_cost","object":"GraphRAG","value":"99%","provenance":{"source_id":"src-05-lightrag","version":"v1@ab12cd34","start":3000,"end":3034,"quote":"LightRAG reduces token cost by 99%"}}
{"name":"RAG_publication","participants":["RAG","NeurIPS"],"time":"2020","provenance":{"source_id":"src-05-lightrag","version":"v1@ab12cd34","start":3057,"end":3093,"quote":"RAG was published at NeurIPS in 2020"}}
```

모든 항목이 body offset Provenance 를 달고 있다. Claim 의 quote 에 `99%` 가, Event 의
quote 에 `2020` 이 실제로 들어 있는 것을 눈으로 확인한다 — 이게 근거 사슬의 핵심이다.

---

## step 4 — 일부러 깨뜨려 품질 게이트 체감

검증기가 enum 위반·깨진 span·수치 환각·시점 환각을 잡아내는지 본다. `validate_rce.py` 의
자체 점검을 실행한다. 정상 1건 + enum 밖 관계(`BEATS`) 1건 + 수치 환각(`50%`) 1건 +
깨진 span(시점) 1건을 넣어 두었다.

```bash
python3 validate_rce.py
```

예상 출력:

```
=== RCE 검증 리포트 ===
총 후보 4건 — accept 1 (R 0 / C 1 / E 0) / reject 3
--- claims (accepted) ---
  [OK] LightRAG reduces_token_cost value='99%'  src=src-05-lightrag
--- rejected (reject queue 로 보존) ---
  [REJECT] (relation) enum 위반: type='BEATS' (허용 ['PROPOSES', 'IMPROVES', 'EVALUATED_ON', 'MEASURED_BY', 'COMPARES_TO', 'USES', 'CITES'])
  [REJECT] (claim) 수치 환각: value='50%' 가 근거 quote 에 없음
  [REJECT] (event) span quote 불일치(body[start:end] != quote)
```

세 가지가 걸러졌다. `BEATS` 는 RelationType enum 에 없어 Pydantic 이 막았고(통제 어휘),
`50%` 는 근거 quote(`...by 99%`)에 없는 수치라 환각으로 버렸고, quote 가 원문과 안 맞는
이벤트는 근거 사슬이 깨진 것이라 버렸다. reject 는 종류·사유와 함께 보존된다.

dangling 을 reject 로 올리고 싶으면 파이프라인에 `--strict-dangling` 을 준다.

```bash
python3 run_extract_rce.py --strict-dangling
```

예상 출력(요약):

```
총 후보 5건 — accept 4 (R 3 / C 1 / E 0) / reject 1
--- rejected (reject queue 로 보존) ---
  [REJECT] (event) dangling 참조(엔티티 미존재): ['NeurIPS']
```

`NeurIPS` 가 엔티티 집합에 없으니 strict 모드에선 이벤트가 reject 됐다(종료 코드 1).
기본 모드는 같은 상황을 경고로만 남긴다 — 추출이 놓친 개체일 수 있어서다.

---

## step 5 (선택) — Claude 백엔드로 같은 청크 추출해 mock 과 비교

`ANTHROPIC_API_KEY` 가 있으면 LLM 백엔드로 같은 청크를 돌려 mock 과 비교할 수 있다.
규칙이 못 잡는 관계·주장을 LLM 이 더 잡거나, 반대로 enum 밖 관계 타입을 내서 reject
되는 걸 관찰한다.

```bash
export ANTHROPIC_API_KEY=sk-ant-...   # 키는 환경변수로만. 코드에 넣지 않는다.
pip install "anthropic>=0.40"
python3 run_extract_rce.py --backend anthropic
```

예상 동작:

- R/C/E 건수가 mock 과 달라질 수 있다(LLM 이 더/덜 잡는다).
- LLM 이 enum 밖 `type` 을 내면 검증에서 `[REJECT] (relation) enum 위반` 으로 집계된다.
- LLM 이 수치·시점을 지어내면 `수치 환각`·`시점 환각` 으로 reject 된다(근거 quote 대조).
- 모든 accept 항목은 여전히 body offset Provenance + quote 무결성을 통과한다(환산·검증은 백엔드와 무관).

instructor 백엔드도 동일하다.

```bash
pip install "instructor>=1.5" "anthropic>=0.40"
python3 run_extract_rce.py --backend instructor
```

> 비용이 부담되면 LLM 을 Ollama 로컬 모델로 바꿔도 파이프라인은 동일하게 동작한다(품질만 차이).
> 어느 경우든 **기본 경로(mock)는 키 없이 돌아간다** — step 1~4 는 키가 전혀 필요 없다.
