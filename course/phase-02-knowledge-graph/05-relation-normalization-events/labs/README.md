# Lab 2.5 — 관계 정규화 & Event 모델링 핸즈온

04 가 head/tail 을 canonical 로 재배선한 관계를 받아, 타입을 통제 어휘로 정규화하고 방향을 통일하고 dedup 한 뒤, n-ary 사실을 Event 로 reify 한다. 키도 네트워크도 필요 없다(결정적).

```bash
cd course/phase-02-knowledge-graph/05-relation-normalization-events/practice
python -m venv .venv && source .venv/bin/activate   # 선택
pip install -r requirements.txt                     # pydantic, pyyaml
```

> 입력은 기본적으로 동봉 sample(`sample_relations.resolved.jsonl`·`sample_events.jsonl`·`sample_canonical_entities.jsonl`)을 쓴다. 04·03 실제 산출물을 쓰려면 그 파일들을 이 `practice/` 로 복사한 뒤 `--input resolved` 를 준다.

---

## ① 입력 확인

```bash
wc -l sample_relations.resolved.jsonl sample_events.jsonl sample_canonical_entities.jsonl
head -3 sample_relations.resolved.jsonl
```

예상 출력(줄 수와 첫 줄 형태):

```
 12 sample_relations.resolved.jsonl
  2 sample_events.jsonl
 11 sample_canonical_entities.jsonl
 25 total
{"head":"LightRAG","type":"USES","tail":"Neo4j",...}
{"head":"LightRAG","type":"UTILIZES","tail":"Neo4j",...}
{"head":"Neo4j","type":"USED_BY","tail":"LightRAG",...}
```

관계 12건 안에 동의어(UTILIZES·ENHANCES·CREATED_BY), 역방향(USED_BY·OUTPERFORMED_BY·COMPARED_WITH), self-loop(RELATED_TO LightRAG→LightRAG), 미등록 술어(INSPIRED_BY)가 일부러 섞여 있다.

---

## ② `run_normalize.py` 실행 — 전체 파이프라인

```bash
python run_normalize.py
```

예상 출력(요약 줄):

```
입력: sample_relations.resolved.jsonl 관계 12건 · sample_events.jsonl 이벤트 2건

관계 정규화: 12건 → 7 canonical 엣지 (dedup 으로 3건 합쳐짐) · reject 2건
...
Event reification: 2건 → 2 reified Event (reject 0건)
...
저장: normalized_relations.jsonl(7) events.normalized.jsonl(2) reject_relations.jsonl(2) — 다음 토픽(2/06)의 입력
```

12건이 정규화·dedup 을 거쳐 7 canonical 엣지가 되고, self-loop·미등록 술어 2건이 reject 로 빠진다.

---

## ③ 동의어 정규화 결과 확인 — UTILIZES·USED_BY → USES

```bash
python -c "import json;[print(json.loads(l)['head'],json.loads(l)['type'],json.loads(l)['tail'],'support='+str(len(json.loads(l)['provenances']))) for l in open('normalized_relations.jsonl') if json.loads(l)['type']=='USES']"
```

예상 출력:

```
LightRAG USES Neo4j support=3
```

`USES`·`UTILIZES`·`USED_BY` 세 표면형이 한 엣지(`support=3`)로 모였다. `ENHANCES`→`IMPROVES`, `CREATED_BY`→`DEVELOPED_BY` 도 같은 방식으로 흡수됐다(전체 엣지는 `run_normalize.py` 요약에서 확인).

---

## ④ 방향 정규화 확인 — COMPARES_TO 정렬 dedup, USED_BY→USES flip

```bash
grep -o '"head":"[^"]*","type":"COMPARES_TO","tail":"[^"]*"' normalized_relations.jsonl
```

예상 출력(양방향 두 건이 정렬돼 한 엣지로):

```
"head":"GraphRAG","type":"COMPARES_TO","tail":"LightRAG"
```

`LightRAG COMPARES_TO GraphRAG` 와 `GraphRAG COMPARED_WITH LightRAG` 가 (GraphRAG, LightRAG) 순서로 정렬돼 한 엣지가 됐다. USED_BY 의 flip 은 ③에서 본 `USES support=3` 이 증거다 — `Neo4j USED_BY LightRAG` 가 `LightRAG USES Neo4j` 로 뒤집혀 합쳐졌다.

---

## ⑤ n-ary Event reify 결과 확인 — role 부여

```bash
cat events.normalized.jsonl
```

예상 출력(밋밋한 participants 가 role 을 얻음):

```
{"event_id":"evt-publication-rag-publication","type":"PUBLICATION","roles":{"year":"2020","published_work":"RAG","venue":"NeurIPS"},"time":"2020",...}
{"event_id":"evt-publication-graphrag-release","type":"PUBLICATION","roles":{"year":"2024","published_work":"GraphRAG","venue":"Microsoft"},"time":"2024",...}
```

`["RAG","NeurIPS"]` 가 `published_work=RAG, venue=NeurIPS, year=2020` 으로 구조화됐다. 수치 클레임까지 Event 로 보려면:

```bash
python run_normalize.py --with-claims
grep MEASUREMENT events.normalized.jsonl
```

예상 출력:

```
{"event_id":"evt-measurement-lightrag-reduces-token-cost","type":"MEASUREMENT","roles":{"subject":"LightRAG","metric":"reduces_token_cost","value":"99%","baseline":"GraphRAG"},...}
```

---

## ⑥ `validate_normalization.py` — 4종 게이트 통과

```bash
python validate_normalization.py
echo "exit=$?"
```

예상 출력:

```
검증 입력: relations 7건 · events 2건 · canonical 11건

[PASS] (a) vocab 소속
       모든 type 이 vocab canonical
[PASS] (b) 대칭 dedup
       symmetric 엣지가 모두 정렬·dedup 됨
[PASS] (c) self-loop 없음
       self-loop 없음
[PASS] (d) dangling 없음
       모든 엔티티 참조가 canonical

결과: 전부 통과
exit=0
```

> `--with-claims` 로 MEASUREMENT Event 를 추가했다면 events 가 3건으로 나온다. 4종 모두 PASS·`exit=0` 이면 정규화 게이트 통과다.

---

## ⑦ (의도적 실패 재현) 미등록 술어가 reject 로 빠지는지 확인

sample 에 이미 미등록 술어 `INSPIRED_BY` 가 들어 있다. reject 파일을 직접 본다.

```bash
cat reject_relations.jsonl
```

예상 출력(self-loop + 미등록 술어가 근거와 함께 분리됨):

```
{"head":"LightRAG","type":"RELATED_TO","tail":"LightRAG","reason":"self-loop(head==tail)",...}
{"head":"Self-RAG","type":"INSPIRED_BY","tail":"RAG","reason":"vocab 미등록 술어",...}
```

직접 새 미등록 술어를 넣어 재현하려면, sample 에 한 줄을 추가한 뒤 다시 돌린다.

```bash
echo '{"head":"LightRAG","type":"MENTIONS","tail":"RAG","provenance":{"source_id":"x","version":"v1@0","start":0,"end":1,"quote":"q"}}' >> sample_relations.resolved.jsonl
python run_normalize.py 2>&1 | grep -A4 'reject('
```

예상 출력(추가한 `MENTIONS` 가 reject 로):

```
reject(미등록 술어 / self-loop):
  (LightRAG)-[RELATED_TO]->(LightRAG)  — self-loop(head==tail)
  (Self-RAG)-[INSPIRED_BY]->(RAG)  — vocab 미등록 술어
  (LightRAG)-[MENTIONS]->(RAG)  — vocab 미등록 술어
```

`MENTIONS` 를 정말 허용하려면 `relation_vocab.yaml` 의 적절한 canonical type 의 `synonyms` 에 추가하거나 새 canonical type 을 만든다 — 그게 스키마를 사람이 통제한다는 뜻이다(2/06 품질 게이트로 이어진다). 실험을 끝냈으면 추가한 줄을 되돌린다.

```bash
git checkout sample_relations.resolved.jsonl   # 추가한 MENTIONS 줄 원복
```

---

## 산출물

| 파일 | 내용 | 다음 입력처 |
|------|------|-------------|
| `normalized_relations.jsonl` | 정규화·방향통일·dedup 된 관계 엣지(+ provenance 리스트) | 2/06 품질 게이트·증분 적재 |
| `events.normalized.jsonl` | role 부여된 reified Event | 2/06, Phase 3 적재 |
| `reject_relations.jsonl` | 미등록 술어·self-loop(근거 포함) | 2/06 품질 게이트 검토 |
