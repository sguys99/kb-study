# 2.6 품질 게이트와 증분 적재 — reject queue · MERGE · version · delete · Eval

> **Phase 2 · 토픽 06** · 05 가 관계 타입·방향·n-ary 를 정제했다. 깨끗해 보이지만 그대로 Neo4j 에 올리면 안 된다. 근거 0건짜리 엣지, canonical 집합에 없는 노드를 가리키는 엣지가 섞여 있다. 적재 전 마지막 관문(품질 게이트)에서 통과/거절을 분기하고, 통과분만 MERGE 로 증분 적재한다. 같은 입력을 두 번 넣어도 결과가 같고(idempotent), 소스가 철회되면 그 근거만 빼낸다. Phase 2 의 종착점이자 Phase 3 Neo4j 적재 직전이다.

## 학습 목표

이 토픽을 끝내면 다음을 할 수 있다.

- 정규화된 엣지를 적재 전에 점수화해 통과/거절로 분기하는 품질 게이트를 만든다 — support·provenance 완전성·canonical 소속·충돌 4종 신호로 reason code 를 붙이고, 거절분을 `reject_queue.jsonl` 로 분리한다.
- 같은 `(head,type,tail)` 키를 새로 만들지 않고 provenance 를 누적하는 MERGE 를 구현해, 같은 배치를 두 번 적재해도 엣지 수·support 가 변하지 않음(idempotent)을 증명한다.
- 적재마다 version 을 스탬프하고, 소스 철회 시 해당 provenance 만 제거해 근거가 0 이 된 엣지를 tombstone(soft-delete) 처리한다.
- gold 정답 엣지 집합 대비 precision/recall 과 적재 전후 그래프 통계를 계산하는 Construction Eval 을 돌려, 게이트의 false positive·false reject 를 숫자로 본다.

**완료 기준**: `ingest_incremental.py` 가 sample(또는 05 산출물)을 품질 게이트로 통과/거절 분기하고, MERGE 로 idempotent 증분 적재(2회 실행 시 `live_edges`·`total_support` 불변)하며, version 스탬프와 source 철회 delete(provenance 제거·tombstone)가 동작하고, `eval_construction.py` 가 gold 대비 precision/recall 을 숫자로 출력하면 완료.

---

## 1. 왜 필요한가 — 정제했어도 그대로 올리면 안 된다

05 까지 왔다. 엔티티는 04 가 canonical 로 합쳤고, 관계는 05 가 타입·방향·n-ary 를 정리했다. `normalized_relations.jsonl` 을 열면 엣지들이 꽤 깨끗하다. 이제 Neo4j 에 부으면 끝일까. 아니다.

`normalized_relations.jsonl` 에 두 줄이 더 있다. 하나는 `(CRAG)-[USES]->(LangChain)`. LangChain 은 04 의 canonical 엔티티 집합에 없다 — 04 가 만들지 않은 노드를 가리키는 엣지다. 그대로 적재하면 Neo4j 에 정체불명 노드 `LangChain` 이 생기고 04 가 보장한 "모든 노드는 해소된 canonical" 이라는 불변이 깨진다. 다른 하나는 `(LightRAG)-[IMPROVES]->(retrieval quality)`. provenance 가 빈 리스트다 — 어느 문서의 어느 문장이 이 주장을 떠받치는지 없다. 추적도 인용도 안 되는 엣지다.

이런 게 한둘이면 손으로 지우면 된다. 코퍼스가 50건에서 수천 건으로 늘면 손으로 못 막는다. 추출·정제 파이프라인은 결정적이지 않다 — LLM 이 가끔 엉뚱한 엣지를 만들고, 소스가 갱신되면 어제 맞던 근거가 오늘 사라진다. **적재 직전에 한 번 더 거르는 자동 관문**이 필요하다. 그게 품질 게이트다.

여기에 더해 적재 자체도 단순하지 않다. 코퍼스는 한 번에 완성되지 않는다. 오늘 50건, 다음 주에 30건이 더 들어온다. 새 배치에 어제 본 엣지가 또 있으면? 같은 엣지를 두 번 만들면 안 된다(중복 폭증). 소스 문서가 철회되면? 그 근거만 빼야 한다. 이 증분 적재의 의미론을 이번 토픽에서 결정적으로 손에 익힌다.

> 이 토픽은 Neo4j 를 직접 쓰지 않는다. Neo4j 실적재는 Phase 3 다. 대신 표준 라이브러리만으로 경량 그래프 스토어를 만들어 **MERGE·version·delete 의미론을 먼저 익힌다.** 여기서 정한 의미론이 Phase 3 에서 그대로 Neo4j 의 `MERGE` 와 `CONSTRAINT` 로 옮겨진다.

## 2. 품질 게이트 — 적재 전 마지막 관문

게이트는 엣지 하나하나를 점수화해 통과시킬지 거절할지 정한다. 신호 넷을 본다.

**support** — provenance(근거)가 몇 건인가. `support = len(provenances)`. 한 문서에서만 한 번 나온 엣지와 세 문서에서 나온 엣지는 신뢰도가 다르다. `min_support` 미만이면 보류한다.

**provenance 완전성** — 근거가 아예 없으면(`support == 0`) 추적 불가다. 거절한다.

**canonical 소속** — head/tail 이 04 의 canonical 엔티티 집합(name)에 있는가. 없으면 04 가 만들지 않은 노드를 가리키는 엣지다. 거절한다.

**충돌(conflict)** — 같은 `(head, type)` 에 모순되는 tail 이 둘 이상인가. 함수형 관계(한 head 당 tail 이 하나여야 자연스러운 관계, 예: `DEVELOPED_BY`)에서 한 모델이 두 조직에 의해 개발됐다고 찍히면 둘 중 하나는 틀렸다. 보류하고 사람이 본다.

이 게이트는 LLM 도 SHACL 엔진도 부르지 않는다. 입력은 Pydantic 으로 검증하고, 규칙은 순수 파이썬 함수로 돈다. SHACL 의 "그래프가 만족해야 할 제약을 선언적으로 적는다"는 발상을 빌리되, 라이선스·의존 부담 없이 함수로 옮겼다(pyshacl 은 RDF 그래프에 같은 일을 해 주는 표준 도구다 — 개념·선택 의존).

```python
# practice/quality_gate.py — 엣지 하나에 대한 거절 사유 판정
def _first_failing_reason(r, canonical_names, cfg, conflicted):
    if cfg.require_provenance and r.support == 0:
        return "NO_PROVENANCE"
    if r.support < cfg.min_support:
        return "LOW_SUPPORT"
    if r.head not in canonical_names:
        return "NON_CANONICAL_NODE"
    if r.tail not in canonical_names:
        return "NON_CANONICAL_NODE"
    if cfg.check_conflict and (r.head, r.type) in conflicted:
        return "CONFLICT"
    return None   # 다 통과
```

임계값은 코드가 아니라 `GateConfig` 설정으로 둔다. `min_support`, `require_provenance` 를 도메인마다 다르게 조일 수 있어야 한다. 의료 도메인이라면 support 2~3 건을 요구하고, 탐색적 분석이라면 1 건도 받는 식이다.

```python
# 임계값을 바꿔 가며 게이트를 조인다
cfg = GateConfig(min_support=2, require_provenance=True)
result = run_gate(relations, canonical_names, cfg)
```

## 3. reject queue — "왜 빠졌나"를 남긴다

거절한 엣지를 그냥 버리면 안 된다. 사유(reason code)와 근거를 붙여 `reject_queue.jsonl` 로 분리한다. 05 가 이미 걸러 둔 `reject_relations.jsonl`(self-loop·미등록 술어)과 합치면, "이 엣지가 왜 그래프에 없는가"를 한곳에서 추적할 수 있다.

```python
# practice/ingest_incremental.py — 거절분을 사유와 함께 누적
with REJECT_QUEUE.open("a", encoding="utf-8") as f:
    for item in rejected:
        f.write(json.dumps({**item, "batch": batch, "stage": "quality_gate"},
                           ensure_ascii=False) + "\n")
```

reject queue 는 쓰레기통이 아니라 **거버넌스 루프의 입구**다. `NON_CANONICAL_NODE` 로 빠진 `(CRAG)-[USES]->(LangChain)` 을 보고 사람이 판단한다 — LangChain 이 진짜 우리 그래프에 있어야 할 엔티티라면 04 의 canonical 집합에 추가하고 재투입한다. `NO_PROVENANCE` 가 자주 뜨면 추출 단계에서 근거 span 을 안 남기고 있다는 신호다. 게이트가 막은 항목이 스키마·vocab 을 고칠 단서가 된다. 막기만 하고 안 보면 같은 노이즈가 계속 들어온다.

## 4. MERGE — 같은 키는 새로 만들지 않고 근거를 쌓는다

통과한 엣지를 스토어에 넣는다. 핵심은 **MERGE**다. 같은 `(head, type, tail)` 키가 이미 있으면 새 엣지를 만들지 않고 기존 엣지에 provenance 만 누적한다. 없으면 새로 만든다. 이게 idempotent upsert 다.

```python
# practice/graph_store.py — MERGE 의 핵심
def merge_edge(self, rel, batch):
    key = edge_key(rel["head"], rel["type"], rel["tail"])
    existing = self.edges.get(key)
    if existing is None:
        self.edges[key] = { ... "provenances": list(rel["provenances"]),
                            "ingested_in": [batch], "tombstone": False }
        return "created"
    # 이미 있는 엣지 → provenance 를 (source_id,start,end) 로 중복 제거하며 누적
    seen = {_prov_id(p) for p in existing["provenances"]}
    for p in rel["provenances"]:
        if _prov_id(p) not in seen:
            existing["provenances"].append(p)
    existing["ingested_in"].append(batch)   # 이미 있으면 안 쌓음(실제 코드)
    return "accumulated"
```

왜 중요한가. 같은 배치를 두 번 적재해도 결과가 같아야 한다. 파이프라인은 중간에 죽고 재시작한다. CREATE 로 짰다면 재시작할 때마다 같은 엣지가 두 배, 세 배로 쌓인다. MERGE 면 키가 같아 새로 안 만들고, provenance 도 `(source_id, start, end)` 로 중복 제거하니 support 도 안 부푼다. **두 번 넣어도 카운트 불변** — 이걸 lab 에서 직접 확인한다.

```
[batch v1] 입력 9건 → 게이트 통과 7건 · 거절 2건
  MERGE 결과: created 7 · accumulated 0 · revived 0
  스토어 통계: nodes 8 · live_edges 7 · orphan 0 · total_support 10

# 같은 명령 재실행 — created 가 0, accumulated 가 7. 카운트는 그대로.
  MERGE 결과: created 0 · accumulated 7 · revived 0
  스토어 통계: nodes 8 · live_edges 7 · orphan 0 · total_support 10
```

## 5. version — 어느 배치가 무엇을 건드렸나

적재마다 version 라벨(`--batch v1`)을 붙이고, 엣지에 `first_seen_batch`·`last_seen_batch`·`ingested_in`(이 엣지를 건드린 배치 목록)을 스탬프한다. provenance 안에도 05 가 남긴 `version`(예 `v1@ab12cd34`)이 있어, 어느 소스의 어느 버전이 이 근거인지까지 추적된다.

2차 배치(v2)를 올리면 셋이 동시에 일어난다. 신규 엣지가 `created` 로 들어오고, 기존 엣지는 새 근거를 받아 `accumulated` 되며(support 증가), 저품질 엣지는 게이트에서 거절된다.

```
[batch v2] 입력 6건 → 게이트 통과 4건 · 거절 2건
  MERGE 결과: created 3 · accumulated 1 · revived 0
  스토어 통계: nodes 9 · live_edges 10 · orphan 0 · total_support 14
```

`accumulated 1` 이 `(LightRAG)-[USES]->(Neo4j)` 다. v1 에서 support 3 이던 엣지가 v2 의 새 근거를 받아 support 4 가 되고, `ingested_in` 이 `["v1","v2"]` 로 두 배치를 모두 기록한다. version 스탬프 덕에 "이 엣지는 v1 에서 생겨 v2 에서 보강됐다"를 나중에 읽을 수 있다.

## 6. delete — 소스가 철회되면 근거만 빼고 tombstone

증분 적재에서 가장 까다로운 게 delete 다. 추가는 쉽다 — MERGE 하면 된다. 삭제는 어렵다. 소스 문서 하나가 철회됐다고 그 문서에서 나온 엣지를 통째로 지우면, 그 엣지를 떠받치던 **다른** 근거까지 같이 날아간다. 또 엣지를 지우면 그 엣지만 가리키던 노드가 고아(orphan)가 되고, 그 노드를 지날 멀티홉 경로가 끊긴다.

그래서 delete 는 엣지가 아니라 **provenance 단위**로 한다. 철회된 source_id 의 provenance 만 모든 엣지에서 빼낸다. 그 결과 provenance 가 0 이 된 엣지만 tombstone 한다. tombstone 은 hard-delete(딕셔너리에서 제거)가 아니라 soft-delete — "언제 왜 죽었는지"를 남긴 채 비활성으로 표시한다.

```python
# practice/graph_store.py — provenance 단위 delete + tombstone
def delete_source(self, source_id, batch):
    for edge in self.edges.values():
        before = len(edge["provenances"])
        edge["provenances"] = [p for p in edge["provenances"]
                               if p.get("source_id") != source_id]
        if before > 0 and len(edge["provenances"]) == 0:
            edge["tombstone"] = True            # soft-delete: 흔적을 남긴다
            edge["tombstone_reason"] = f"source {source_id} withdrawn"
            edge["tombstone_batch"] = batch
```

`src-04-graphrag` 를 철회하면 이렇게 된다.

```
[batch v3] 소스 철회: src-04-graphrag
  provenance 제거: 3건 · tombstone 처리: 2건
  통계  before → after: live_edges 10→8 · tombstoned 0→2 · total_support 14→11
```

`(GraphRAG)-[IMPROVES]->(RAG)` 는 근거가 src-04 하나뿐이라 support 0 → tombstone. 반면 `(GraphRAG)-[COMPARES_TO]->(LightRAG)` 는 근거가 둘(src-04, src-06)이었다. src-04 만 빠지고 src-06 이 남아 **살아남는다**. 근거가 여럿이면 한 소스 철회로 엣지가 죽지 않는다 — provenance 를 리스트로 누적한 이유가 여기서 드러난다.

왜 hard-delete 가 아니라 tombstone 인가. tombstone 한 `(GraphRAG)-[DEVELOPED_BY]->(Microsoft)` 때문에 `Microsoft` 가 고아 노드가 된다. hard-delete 였다면 이 노드를 같이 지울지 즉석에서 판단해야 했고, 만약 다른 살아 있는 엣지가 Microsoft 를 가리켰다면 잘못 지워 그래프를 깨뜨렸을 것이다. tombstone 은 그 판단을 미뤄 둔다. 철회가 번복되면 같은 근거가 다시 들어올 때 `revived` 로 되살린다. Phase 3 에서 이 tombstone 은 노드 라벨이나 `valid_to` 속성으로 옮겨진다.

> 전체 코드와 실행 절차는 [`practice/`](practice/) 와 [`labs/`](labs/) 참조.
> 이 토픽은 LLM·임베딩을 부르지 않는다(Pydantic 검증 + 결정적 규칙·스토어). 키도 비용도 네트워크도 없다. 게이트를 더 빡빡하게 하려면 `--min-support 2` 로 임계값만 올린다.

## 7. Construction Eval — "좋아진 것 같다" 금지, 숫자로

게이트와 적재가 잘 됐는지 어떻게 아나. 눈으로 "깨끗해 보인다" 가 아니라 숫자로 본다. 이 토픽의 Eval 은 답변 품질이 아니라 **Construction(그래프 구축) 품질**이다. Ragas 같은 답변 평가는 Phase 6 소관이니 여기서 끌어오지 않는다.

작은 gold 정답 엣지 집합(`gold_edges.jsonl`)을 두고, 적재된 live 엣지와 결정적으로 대조한다.

```python
# practice/eval_construction.py — gold 대비 precision/recall
tp = predicted & gold          # 적재됐고 gold 인 것
fp = predicted - gold          # 적재됐지만 gold 아님(노이즈 유입)
fn = gold - predicted          # gold 인데 못 넣음
false_reject = gold & rejected # gold 인데 게이트가 거절(과도한 게이트)

precision = len(tp) / len(predicted)
recall = len(tp) / len(gold)
```

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

읽을 게 둘이다. `precision 0.88` — 적재된 8건 중 7건이 gold 다. 하나(`CRAG-COMPARES_TO-Self-RAG`)는 게이트를 통과했지만 gold 가 아니다(false positive). 게이트가 노이즈를 완벽히는 못 막는다. `recall 0.70` — gold 10건 중 7건만 들어왔다. 빠진 것 중 `(CRAG)-[USES]->(LangChain)` 은 사실 맞는 엣지인데 LangChain 이 canonical 집합에 없어 게이트가 거절했다(false reject). 04 의 엔티티 집합에 LangChain 을 넣으면 살아난다 — 정확히 reject queue 거버넌스 루프가 처리할 일이다.

이 숫자가 임계값 튜닝의 나침반이다. `min_support` 를 올리면 precision 은 오르고 recall 은 떨어진다. 그 균형을 감이 아니라 숫자로 잡는다. 이 결정적 Construction 지표가 Phase 6(평가·관측성)에서 golden question 회귀 게이트로 확장된다 — Phase 6 의 예고편이다.

마지막으로 산출물. `graph_snapshot.jsonl` 이 이 토픽의 최종 결과이자 Phase 2 전체의 종착물이다. 노드·엣지·provenance·version 메타가 정렬돼 담긴 이 스냅샷이 Phase 3 Neo4j Bulk Ingest 의 입력이 된다.

---

## 🚨 자주 하는 실수

1. **게이트 없이 다 적재한다** — "추출했으니 일단 다 넣자"가 그래프를 노이즈로 채운다. provenance 없는 엣지, canonical 아닌 노드를 가리키는 엣지가 그대로 들어가면 04·05 가 보장한 불변이 깨지고, Phase 4 GraphRAG 가 인용을 못 붙이며, 멀티홉이 정체불명 노드에서 샌다. 적재 직전 게이트는 선택이 아니다. 거절분은 버리지 말고 reject queue 에 사유와 함께 남겨 거버넌스 루프로 돌려라.
2. **MERGE 대신 CREATE 로 적재한다** — 같은 엣지를 볼 때마다 새로 만들면 재시작·재적재 한 번에 엣지가 두 배로 폭증하고, support 카운트가 의미를 잃는다(같은 근거가 N 번 쌓여 신뢰도가 가짜로 높아짐). 키를 `(head,type,tail)` 로 잡고 MERGE 로 provenance 만 누적하라. 같은 입력을 두 번 넣어 카운트가 그대로인지(idempotent) 반드시 확인하라 — 안 그러면 어딘가에서 새고 있는 것이다.
3. **hard-delete 로 엣지·노드를 통째로 지운다** — 소스 철회 시 엣지를 통째로 지우면 그 엣지를 떠받치던 다른 근거까지 날아가고, 그 노드만 가리키던 멀티홉 경로가 끊기며, 고아 노드가 양산된다. delete 는 provenance 단위로 하고, 근거가 0 이 된 엣지만 tombstone(soft-delete)하라. 흔적을 남겨야 철회 번복·감사 추적·고아 정리를 안전하게 미룰 수 있다.
4. **"좋아진 것 같다"로 끝낸다** — 게이트를 조이고 나서 눈으로 "깨끗해 보인다"는 평가가 아니다. gold 대비 precision/recall, false positive·false reject 수, 적재 전후 노드·엣지·고아 수를 숫자로 찍어라. 숫자가 없으면 임계값을 어느 방향으로 조일지 정할 수 없고, 다음 배치에서 품질이 떨어져도 모른다.

## 출처

- Pydantic — https://docs.pydantic.dev/
- Graph RAG Survey (Construction) — arXiv 2408.08921, https://arxiv.org/abs/2408.08921
- SHACL (Shapes Constraint Language, W3C) — https://www.w3.org/TR/shacl/
- pySHACL — https://github.com/RDFLib/pySHACL

## 다음 토픽

→ [Neo4j 실무 구조 (Phase 3 — Neo4j 그래프 데이터 엔지니어링으로 이어진다)](../../phase-03-neo4j-graph-engineering/01-neo4j-fundamentals/lesson.md)
