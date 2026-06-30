# Lab 2.4 — 엔티티 해소 4단계 핸즈온

2/03 이 만든 중복 엔티티를 4단계 ER 로 병합하고, Self-RAG·CRAG 가 RAG 로 새지 않는지 검증한다. 기본 경로는 키·네트워크 없이 mock 임베딩으로 돈다.

전제: Python 3.11+. `practice/` 디렉토리에서 실행한다. 아래 명령은 모두 `practice/` 기준이다.

```bash
cd course/phase-02-knowledge-graph/04-entity-resolution/practice
```

---

## 1단계 — 의존 설치

```bash
python -m venv .venv && source .venv/bin/activate     # 선택: 가상환경
pip install -r requirements.txt
```

기본 경로는 `pydantic>=2` 와 `rapidfuzz>=3` 만 쓴다. `voyageai`·`sentence-transformers` 는 선택(4단계 백엔드 교체 시).

**예상 출력**

```
Successfully installed pydantic-2.x rapidfuzz-3.x ...
```

설치 확인:

```bash
python -c "import rapidfuzz, pydantic; print('rapidfuzz', rapidfuzz.__version__, '| pydantic', pydantic.__version__)"
```

```
rapidfuzz 3.14.5 | pydantic 2.13.4
```

---

## 2단계 — 임베딩 백엔드 자기점검 (mock)

mock 임베딩이 결정적인지(같은 표면형 → cos 1.0000), 그리고 의미를 모른다는 걸 먼저 확인한다.

```bash
python embedding_provider.py
```

**예상 출력**

```
mock 임베딩 4건, 차원=64
cos(LightRAG, LightRAG) = 1.0000  (결정적이면 1.0000)
cos(Self-RAG, RAG)      = 0.1345  (mock 은 의미 모름)
```

`cos(Self-RAG, RAG)` 가 낮은 건 mock 이 문자열을 해시로만 보기 때문이다. 의미 병합은 `voyage`·`local` 백엔드의 몫이다(4단계 참고).

---

## 3단계 — 4단계 ER 실행 (mock, 시연용 sample)

19건 엔티티(2/03 원본 16건 + 표기 흔들림 케이스 3건)를 병합한다.

```bash
python run_resolve.py
```

**예상 출력**

```
입력: sample_entities.jsonl 엔티티 19건 · sample_relations.jsonl 관계 4건 — embedding=mock, fuzzy_threshold=90

단계별 병합 후보 쌍:
  alias      9 쌍
  coref      3 쌍
  fuzzy      4 쌍
  embedding  0 쌍

병합 결과: 19 엔티티 → 10 canonical (병합된 클러스터 4개)

병합 그룹(멤버 2개 이상):
  [Model] LightRAG  ←  {Light RAG, LightRAG, LightRag}  (빈도 5)  id=ent-model-lightrag
  [Model] RAG  ←  {RAG}  (빈도 3)  id=ent-model-rag
  [Model] GraphRAG  ←  {GraphRAG}  (빈도 3)  id=ent-model-graphrag
  [Tool] Neo4j  ←  {Neo4J, Neo4j}  (빈도 2)  id=ent-tool-neo4j

오병합 가드 확인 (서로 다른 canonical 이어야 정상):
  RAG        → RAG
  Self-RAG   → Self-RAG
  CRAG       → CRAG
  판정: PASS — Self-RAG·CRAG 가 RAG 로 안 합쳐졌다

저장: canonical_entities.jsonl(10) merge_map.json(13 매핑) relations.resolved.jsonl(4) — 다음 토픽(2/05·2/06)의 입력
```

읽을 것: `LightRAG` 클러스터가 표기 흔들림 셋을 흡수했고, `Neo4J`→`Neo4j` 가 묶였고, `RAG`·`Self-RAG`·`CRAG` 가 각자 따로 남았다. `embedding 0 쌍` 은 mock 이 의미를 몰라서 정상이다.

산출물 확인:

```bash
head -2 canonical_entities.jsonl
```

```
{"canonical_id": "ent-model-lightrag", "name": "LightRAG", "type": "Model", "aliases": ["Light RAG", "LightRag"], "member_count": 5}
{"canonical_id": "ent-model-rag", "name": "RAG", "type": "Model", "aliases": [], "member_count": 3}
```

---

## 4단계 — 병합 결과 검증 (회귀 게이트)

네 가지 검증을 돌린다. 전부 PASS 여야 다음 토픽으로 넘어갈 자격이 생긴다.

```bash
python validate_resolution.py
echo "exit=$?"
```

**예상 출력**

```
검증 입력: canonical 10건 · relations 4건 · merge_map 13 매핑

[PASS] (a) type 일관 / canonical 존재
       모든 매핑 대상이 canonical 집합에 존재
[PASS] (b) 오병합 가드 (Self-RAG·CRAG·RAG 분리)
       RAG→RAG, Self-RAG→Self-RAG, CRAG→CRAG
[PASS] (c) merge_map 1:1 (안정점)
       모든 canonical 이 자기 자신으로 매핑(안정점)
[PASS] (d) dangling 없음
       모든 head/tail 이 canonical

결과: 전부 통과
exit=0
```

`exit=0` 이면 게이트 통과. 하나라도 FAIL 이면 `exit=1` 로 떨어진다 — CI 회귀 게이트로 쓸 수 있다.

---

## 5단계 — substring 함정 깨보고 가드로 막기

가드가 진짜 일하는지 확인한다. 가드를 끄고 fuzzy 임계값을 내리면 `CRAG`(점수 86)가 `RAG` 로 빨려 들어간다.

먼저 **가드를 끄고** 오병합을 재현한다:

```bash
python run_resolve.py --fuzzy-threshold 80 --no-substring-guard
echo "exit=$?"
```

**예상 출력 (오병합 재현 — FAIL)**

```
⚠️  substring 가드 OFF — 오병합 재현 모드(labs 5단계). 실전에서 쓰지 마라.
...
병합 그룹(멤버 2개 이상):
  [Model] LightRAG  ←  {Light RAG, LightRAG, LightRag}  (빈도 5)  id=ent-model-lightrag
  [Model] RAG  ←  {CRAG, RAG}  (빈도 4)  id=ent-model-rag
  ...
오병합 가드 확인 (서로 다른 canonical 이어야 정상):
  RAG        → RAG
  Self-RAG   → Self-RAG
  CRAG       → RAG
  판정: FAIL — 오병합 발생!
exit=1
```

`CRAG → RAG` — 가드가 없으니 다른 모델이 합쳐졌다. 이게 ER 의 가장 흔한 사고다.

이제 **가드를 켠 채** 같은 낮은 임계값으로 돌린다(가드가 막아야 한다):

```bash
python run_resolve.py --fuzzy-threshold 80
echo "exit=$?"
```

**예상 출력 (가드가 막음 — PASS)**

```
오병합 가드 확인 (서로 다른 canonical 이어야 정상):
  RAG        → RAG
  Self-RAG   → Self-RAG
  CRAG       → CRAG
  판정: PASS — Self-RAG·CRAG 가 RAG 로 안 합쳐졌다
exit=0
```

같은 임계값인데 가드 하나로 결과가 갈린다. 정밀도는 임계값이 아니라 가드가 지킨다.

> 실습 뒤에는 기본값으로 한 번 더 돌려 산출물을 원래대로 되돌려 둔다: `python run_resolve.py`

---

## 6단계 (선택) — 상용/로컬 임베딩 백엔드로 4단계 비교

mock 은 의미를 모른다. 실제 의미 병합을 보려면 백엔드를 바꾼다.

VoyageAI(`voyage-3.5`) — 키 필요:

```bash
export VOYAGE_API_KEY=...                       # 본인 키
pip install 'voyageai>=0.3'
python run_resolve.py --embedding-backend voyage
```

로컬 `bge-m3`(비용 0) — sentence-transformers 필요:

```bash
pip install 'sentence-transformers>=3'
python run_resolve.py --embedding-backend local
```

**무엇이 달라지나**: mock 에서 `embedding 0 쌍` 이던 단계가, 의미 임베딩에서는 표기가 전혀 다른 동의어(예: `Knowledge Graph` ~ `KG`)까지 후보로 잡을 수 있다. 백엔드만 한 줄 바꾼다 — alias·coref·fuzzy·Union-Find·재배선·검증은 그대로다.

---

## 7단계 (선택) — 2/03 원본 16건으로 돌리기

시연용 sample 대신 2/03 이 실제로 만든 `entities.jsonl`·`relations.jsonl` 로 돌린다.

```bash
python run_resolve.py --input entities
```

**예상 출력**

```
입력: entities.jsonl 엔티티 16건 · relations.jsonl 관계 3건 — embedding=mock, fuzzy_threshold=90
...
병합 결과: 16 엔티티 → 10 canonical (병합된 클러스터 3개)
...
  판정: PASS — Self-RAG·CRAG 가 RAG 로 안 합쳐졌다
저장: canonical_entities.jsonl(10) merge_map.json(10 매핑) relations.resolved.jsonl(3) — 다음 토픽(2/05·2/06)의 입력
```

원본 16건에는 표기 흔들림이 없어 fuzzy 가 0쌍이지만, alias·coref 만으로 9건 중복이 정리된다.
