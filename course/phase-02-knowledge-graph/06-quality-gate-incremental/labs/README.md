# Lab 2.6 — 품질 게이트 + 증분 적재 핸즈온

05 가 내놓은 정규화 엣지·이벤트를 품질 게이트로 거른 뒤, 경량 그래프 스토어에
MERGE 로 증분 적재한다. idempotency·version·delete·Construction Eval 까지 직접 확인한다.

이 실습은 키도 네트워크도 없이 결정적으로 돈다. 아래 명령의 출력 숫자가 그대로 재현된다.

## 0. 준비

```bash
cd practice
pip install -r requirements.txt   # pydantic 하나면 충분
```

`practice/` 에는 05 산출물과 같은 스키마의 sample 이 들어 있다. 05 없이도 단독으로 돈다.

- `normalized_relations.jsonl` — 1차 배치(v1). 05 의 7 엣지 + 게이트가 걸러 낼 2 엣지.
- `batch2_relations.jsonl` — 2차 배치(v2). 일부 중복(MERGE), 일부 신규, 일부 저품질.
- `events.normalized.jsonl` · `batch2_events.jsonl` — 이벤트 sample.
- `sample_canonical_entities.jsonl` — 04 산출물. head/tail 검증의 기준(name 집합).
- `gold_edges.jsonl` — Construction Eval 용 정답 엣지.

---

## 1. 1차 배치(v1) 적재 — 게이트 통과/거절

```bash
python ingest_incremental.py --reset
```

예상 출력:

```
리셋: graph_snapshot.jsonl, reject_queue.jsonl 삭제
[batch v1] 입력 9건 → 게이트 통과 7건 · 거절 2건
  거절 사유: {'NON_CANONICAL_NODE': 1, 'NO_PROVENANCE': 1}
  MERGE 결과: created 7 · accumulated 0 · revived 0
  스토어 통계: nodes 8 · live_edges 7 · orphan 0 · total_support 10 (tombstoned 0)
  스냅샷 저장: graph_snapshot.jsonl (Phase 3 Neo4j 적재의 입력)
```

읽을 것: 입력 9건 중 7건만 통과했다. `(CRAG)-[USES]->(LangChain)` 은 LangChain 이
canonical 집합에 없어 `NON_CANONICAL_NODE`, `(LightRAG)-[IMPROVES]->(retrieval quality)`
는 provenance 가 0건이라 `NO_PROVENANCE` 로 빠졌다. 거절분은 `reject_queue.jsonl` 에 사유와
함께 쌓인다.

거절 큐 확인:

```bash
cat reject_queue.jsonl
```

예상 출력(각 줄 JSON):

```
{"head": "CRAG", "type": "USES", "tail": "LangChain", "reason": "NON_CANONICAL_NODE", ...}
{"head": "LightRAG", "type": "IMPROVES", "tail": "retrieval quality", "reason": "NO_PROVENANCE", ...}
```

---

## 2. idempotency 증명 — 같은 배치를 두 번 적재해도 카운트 불변

```bash
python ingest_incremental.py
```

예상 출력:

```
[batch v1] 입력 9건 → 게이트 통과 7건 · 거절 2건
  거절 사유: {'NON_CANONICAL_NODE': 1, 'NO_PROVENANCE': 1}
  MERGE 결과: created 0 · accumulated 7 · revived 0
  스토어 통계: nodes 8 · live_edges 7 · orphan 0 · total_support 10 (tombstoned 0)
  스냅샷 저장: graph_snapshot.jsonl (Phase 3 Neo4j 적재의 입력)
```

핵심: `created 0 · accumulated 7`. 같은 키를 다시 본 MERGE 가 새 엣지를 만들지 않았다.
`live_edges 7` 와 `total_support 10` 이 1차와 똑같다. provenance 는 (source_id,start,end)
로 중복 제거되므로 같은 근거를 두 번 쌓지도 않는다 — support 도 안 부푼다. 이게 idempotent
적재다. CREATE 였다면 엣지가 14개로 폭증했을 것이다.

> idempotency 만 다시 확인하려면 `--reset` 후 같은 명령을 두 번 실행하고 두 출력의
> `live_edges`·`total_support` 가 같은지 본다.

---

## 3. 2차 배치(v2) 증분 적재 — 신규 + 누적 + 저품질 reject

먼저 스토어를 초기 상태(v1만)로 되돌린 뒤 v2 를 올린다.

```bash
python ingest_incremental.py --reset
python ingest_incremental.py --batch v2 --relations batch2_relations.jsonl
```

두 번째 명령의 예상 출력:

```
[batch v2] 입력 6건 → 게이트 통과 4건 · 거절 2건
  거절 사유: {'NON_CANONICAL_NODE': 1, 'NO_PROVENANCE': 1}
  MERGE 결과: created 3 · accumulated 1 · revived 0
  스토어 통계: nodes 9 · live_edges 10 · orphan 0 · total_support 14 (tombstoned 0)
  스냅샷 저장: graph_snapshot.jsonl (Phase 3 Neo4j 적재의 입력)
```

읽을 것이 셋이다.

- `created 3` — 신규 엣지 3건(`GraphRAG-USES-Neo4j`, `CRAG-COMPARES_TO-Self-RAG`,
  `GraphRAG-IMPROVES-multi-hop`). `live_edges` 가 7→10 으로 늘었다.
- `accumulated 1` — `(LightRAG)-[USES]->(Neo4j)` 가 v2 의 새 근거를 받아 provenance 가
  누적됐다. support 가 3→4 로 올랐다(`total_support` 10→14: +3 신규 +1 누적).
- 거절 2건 — `(LightRAG)-[USES]->(VoyageAI)` 는 VoyageAI 가 canonical 아님,
  `(RAG)-[IMPROVES]->(retrieval quality)` 는 provenance 0건.

support 누적 확인:

```bash
python -c "import json; [print(json.loads(l)['head'], len(json.loads(l)['provenances'])) for l in open('graph_snapshot.jsonl') if json.loads(l).get('kind')=='edge' and json.loads(l)['type']=='USES' and json.loads(l)['head']=='LightRAG']"
```

예상 출력:

```
LightRAG 4
```

`ingested_in` 도 `["v1","v2"]` 로 두 배치를 모두 기록한다.

---

## 4. delete 시연 — 소스 철회 → provenance 제거 → tombstone

위 v2 상태에서 `src-04-graphrag` 문서가 철회됐다고 가정한다.

```bash
python ingest_incremental.py --batch v3 --delete-source src-04-graphrag
```

예상 출력:

```
[batch v3] 소스 철회: src-04-graphrag
  provenance 제거: 3건 · tombstone 처리: 2건
  통계  before → after: live_edges 10→8 · tombstoned 0→2 · total_support 14→11
```

읽을 것: `src-04-graphrag` 가 떠받치던 provenance 3건이 빠졌다.

- `(GraphRAG)-[IMPROVES]->(RAG)` 와 `(GraphRAG)-[DEVELOPED_BY]->(Microsoft)` 는 근거가
  src-04 하나뿐이라 support 가 0 이 됐다 → tombstone(soft-delete).
- `(GraphRAG)-[COMPARES_TO]->(LightRAG)` 는 근거가 둘(src-04, src-06)이었다. src-04 만
  빠지고 src-06 이 남아 support=1 로 **살아남는다**. 근거가 여럿이면 한 소스 철회로
  엣지가 죽지 않는다 — provenance 누적이 이래서 중요하다.

tombstone 한 엣지 때문에 `Microsoft` 가 고아 노드가 된다(다음 단계 Eval 에서 `orphan_nodes 1`
로 확인). hard-delete 였다면 이 노드를 같이 지울지 말지 즉석에서 판단해야 했을 것이다.
tombstone 은 그 판단을 미루고 흔적을 남긴다.

---

## 5. Construction Eval — gold 대비 precision/recall

```bash
python eval_construction.py
```

예상 출력:

```
=== Construction Eval (gold 대비) ===
gold 10건 · predicted(live) 8건 · 교집합(TP) 7건
precision 0.88 · recall 0.70 · F1 0.78

false positive 1건 (적재됐지만 gold 아님):
  + (CRAG)-[COMPARES_TO]->(Self-RAG)
false reject 1건 (gold 인데 게이트가 거절):
  - (CRAG)-[USES]->(LangChain)

=== 그래프 통계 ===
nodes 9 · live_edges 8 · tombstoned 2 · orphan_nodes 1 · total_support 11
```

읽을 것:

- `precision 0.88` — 적재된 live 엣지 8건 중 7건이 gold. 하나(`CRAG-COMPARES_TO-Self-RAG`)
  는 게이트는 통과했지만 gold 가 아니라 false positive 다. 게이트가 노이즈를 완벽히는
  못 막는다는 증거.
- `recall 0.70` — gold 10건 중 7건만 적재됐다. 빠진 셋 중 하나(`CRAG-USES-LangChain`)는
  사실 맞는 엣지인데 LangChain 이 canonical 집합에 없어 게이트가 거절했다 — **false reject**.
  04 의 엔티티 집합에 LangChain 을 추가하면 살아난다. 이게 거버넌스 루프의 신호다.
- `orphan_nodes 1` — delete 가 만든 고아(Microsoft).

"좋아진 것 같다" 가 아니라 숫자로 본다. 이 결정적 지표가 Phase 6(평가·관측성)에서
golden question 회귀 게이트로 확장된다.

---

## (선택) 게이트를 더 빡빡하게 — min_support 올리기

근거 2건 이상만 적재하고 싶으면:

```bash
python ingest_incremental.py --reset --min-support 2
```

support=1 인 엣지가 전부 `LOW_SUPPORT` 로 빠진다. 통과 엣지가 줄고 reject 가 는다.
임계값을 올릴수록 precision 은 오르고 recall 은 떨어진다 — 그 균형을 숫자로 보며 조인다.

---

## 정리

`graph_snapshot.jsonl` 이 이 토픽의 최종 산출물이자 Phase 3(Neo4j Bulk Ingest)의 입력이다.
여기서 손에 익힌 MERGE·version·tombstone 의미론이 Phase 3 에서 Neo4j 의 `MERGE` 와
`CONSTRAINT` 로 그대로 옮겨진다.
