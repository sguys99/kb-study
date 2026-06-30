# 핸즈온 — 청크에서 Entity 후보 추출

2/01 에서 정의한 스키마를 추출 타깃으로 받아, 1/05 청크에서 Entity 후보를 뽑는다.
기본 경로는 mock(규칙 기반)이라 API 키·네트워크 없이 로컬에서 돈다. Claude 백엔드는 선택이다.

## 사전 준비

```bash
cd course/phase-02-knowledge-graph/02-entity-extraction-pydantic/practice
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

`requirements.txt` 의 필수는 `pydantic>=2` 뿐이다. anthropic·instructor 는 LLM 백엔드를 쓸 때만 설치한다(파일 주석 참고).

이 토픽은 2/01 의 `graph_schema.py` 를 import 로 재사용한다. 디렉토리 구조가 그대로면
`schema_adapter.py` 가 `../../01-text-to-graph-schema/practice/` 를 자동으로 찾는다.

---

## step 1 — 스키마 재사용 확인

스키마를 새로 만들지 않았다. 2/01 것을 그대로 끌어왔는지 본다.

```bash
python3 -c "from schema_adapter import Entity, NodeType, Provenance; print([t.value for t in NodeType])"
```

예상 출력:

```
['Method', 'Model', 'Dataset', 'Metric', 'Paper', 'Concept', 'Organization', 'Tool']
```

노드 8종이 그대로 나오면 2/01 스키마가 정상 import 된 것이다. 여기서 타입을 다시 정의하지 않는다.

---

## step 2 — 단일 청크 mock 추출(로컬 offset → body offset 환산 확인)

`extract_entities.py` 를 직접 실행하면 첫 샘플 청크 1건을 mock 으로 뽑는다.

```bash
python3 extract_entities.py
```

예상 출력:

```
청크 src-05-lightrag::c012 에서 mock 으로 엔티티 4건 추출:
  - LightRAG   Model        body[1200:1208] quote='LightRAG'
  - RAG        Model        body[1226:1229] quote='RAG'
  - HKUDS      Organization body[1245:1250] quote='HKUDS'
  - Neo4j      Tool         body[1337:1342] quote='Neo4j'
```

`body[...]` 가 핵심이다. 청크 안 로컬 위치가 아니라 **문서 body offset** 으로 환산돼 있다
(`char_start=1200` 만큼 밀렸다). quote 는 그 위치에서 떠낸 사본이라, 나중에 원문으로 1:1 검증된다.
`RAG` 가 `GraphRAG` 안에 박힌 경우는 단어 경계로 걸러져 잡히지 않는다.

---

## step 3 — 전체 파이프라인: 추출 → entities.jsonl → 검증 리포트

```bash
python3 run_extract.py
```

예상 출력:

```
청크 3건 로드 — backend=mock
  src-05-lightrag::c012        → 후보 4건
  src-02-self-rag::c003        → 후보 4건
  src-04-graphrag::c008        → 후보 5건

=== 엔티티 검증 리포트 ===
총 후보 13건 — accept 13 / reject 0
--- accepted ---
  [OK]     LightRAG   Model        src=src-05-lightrag
  [OK]     RAG        Model        src=src-05-lightrag
  [OK]     HKUDS      Organization src=src-05-lightrag
  [OK]     Neo4j      Tool         src=src-05-lightrag
  [OK]     Self-RAG   Model        src=src-02-self-rag
  [OK]     RAG        Model        src=src-02-self-rag
  [OK]     CRAG       Model        src=src-02-self-rag
  [OK]     retrieval quality Concept      src=src-02-self-rag
  [OK]     GraphRAG   Model        src=src-04-graphrag
  [OK]     Microsoft  Organization src=src-04-graphrag
  [OK]     LightRAG   Model        src=src-04-graphrag
  [OK]     GraphRAG   Model        src=src-04-graphrag
  [OK]     multi-hop  Concept      src=src-04-graphrag

저장: entities.jsonl (13건) — 다음 토픽(2/03·2/04)의 입력
```

`entities.jsonl` 이 생겼다. 한 줄이 Entity 1건이다.

```bash
head -1 entities.jsonl
```

예상 출력(키 순서는 다를 수 있다):

```
{"name":"LightRAG","type":"Model","aliases":[],"provenance":{"source_id":"src-05-lightrag","version":"v1@ab12cd34","start":1200,"end":1208,"quote":"LightRAG"}}
```

모든 Entity 가 body offset Provenance(`source_id`/`version`/`start`/`end`/`quote`)를 달고 있다.
이게 "엔티티 → 청크 → 문서 → 원문" 인용 사슬의 시작점이다. 같은 `LightRAG` 가 두 문서에서
각각 잡힌 걸 확인한다 — 이 둘을 노드 하나로 합치는 엔티티 해소는 2/04 의 몫이다.

---

## step 4 — 일부러 깨뜨려 품질 게이트 체감

검증기가 enum 위반과 깨진 span 을 잡아내는지 본다. `validate_entities.py` 의 자체 점검을 실행한다.
정상 1건 + enum 밖 라벨(`Framework`) 1건 + quote 불일치 1건을 넣어 두었다.

```bash
python3 validate_entities.py
```

예상 출력:

```
=== 엔티티 검증 리포트 ===
총 후보 3건 — accept 1 / reject 2
--- accepted ---
  [OK]     LightRAG   Model        src=src-05-lightrag
--- rejected (reject queue 로 보존) ---
  [REJECT] LightRAG   enum 위반 또는 구조 오류: type='Framework' (허용 ['Method', 'Model', 'Dataset', 'Metric', 'Paper', 'Concept', 'Organization', 'Tool'])
  [REJECT] LightRAG   span quote 불일치(body[start:end] != quote)
```

두 가지가 걸러졌다. `Framework` 는 NodeType enum 에 없어 Pydantic 이 막았고(통제 어휘),
quote 가 원문과 안 맞는 후보는 근거 사슬이 깨진 것이라 버렸다. reject 는 사유와 함께
보존된다 — 다음 Phase 의 reject queue 로 이어진다.

---

## step 5 (선택) — Claude 백엔드로 같은 청크 추출해 mock 과 비교

`ANTHROPIC_API_KEY` 가 있으면 LLM 백엔드로 같은 청크를 돌려 mock 과 비교할 수 있다.
규칙 사전이 못 잡는 표면형(문맥 의존 개념 등)을 LLM 이 더 잡거나, 반대로 enum 밖 라벨을
내서 reject 되는 걸 관찰한다.

```bash
export ANTHROPIC_API_KEY=sk-ant-...   # 키는 환경변수로만. 코드에 넣지 않는다.
pip install "anthropic>=0.40"
python3 run_extract.py --backend anthropic
```

예상 동작:

- 후보 건수가 mock 과 달라질 수 있다(LLM 이 더/덜 잡는다).
- LLM 이 enum 밖 type 을 내면 검증에서 `[REJECT] ... enum 위반` 으로 집계된다.
- 모든 accept 엔티티는 여전히 body offset Provenance + quote 무결성을 통과한다(환산·검증은 백엔드와 무관).

instructor 백엔드도 동일하다.

```bash
pip install "instructor>=1.5" "anthropic>=0.40"
python3 run_extract.py --backend instructor
```

> 비용이 부담되면 LLM 을 Ollama 로컬 모델로 바꿔도 파이프라인은 동일하게 동작한다(품질만 차이).
> 어느 경우든 **기본 경로(mock)는 키 없이 돌아간다** — step 1~4 는 키가 전혀 필요 없다.
