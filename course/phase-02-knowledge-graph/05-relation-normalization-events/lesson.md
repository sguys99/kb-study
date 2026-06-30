# 2.5 관계 정규화 — 방향·동의어·n-ary, 그리고 Event 모델링

> **Phase 2 · 토픽 05** · 04 가 head/tail 을 canonical 로 재배선했지만 관계 타입은 여전히 표면형이다. USES/UTILIZES/USED_BY 가 따로 놀고, COMPARES_TO 가 양방향으로 두 번 찍히고, "RAG 가 NeurIPS 에서 2020 년 발표됐다" 같은 3항 사실은 이항 엣지에 담기지 않는다. 통제 어휘로 타입을 정규화하고, 방향을 통일하고, dedup 하고, n-ary 를 Event 로 reify 한다. Neo4j 적재 전 마지막 정제다.

## 학습 목표

이 토픽을 끝내면 다음을 할 수 있다.

- 통제 어휘(`relation_vocab.yaml`)로 surface predicate(USES/UTILIZES/EMPLOYS ...)를 canonical relation type 으로 정규화하고, 미등록 술어를 reject queue 로 분리한다.
- 관계를 대칭(symmetric)·비대칭(asymmetric)으로 나눠 방향을 통일한다 — 대칭은 (head,tail) 정렬로 dedup, 비대칭은 inverse 정의로 한 방향으로 flip, self-loop 는 reject.
- 이항 엣지로 못 담는 3항 이상 사실을 Event 노드로 reify 하고, 밋밋한 `participants[]` 에 role 라벨을 부여해 `events.normalized.jsonl` 을 만든다.
- `validate_normalization.py` 의 4종 검증(vocab 소속·대칭 dedup·self-loop 없음·dangling 없음)으로 정규화 결과를 게이트한다.

**완료 기준**: `run_normalize.py` 가 sample(또는 04·03 산출물)의 관계를 vocab canonical type 으로 정규화하고, COMPARES_TO 대칭 정렬·USED_BY→USES inverse flip 으로 방향을 통일하며, n-ary 이벤트를 role 부여된 `events.normalized.jsonl` 로 reify 하고, `validate_normalization.py` 의 4종 검증(vocab 소속·대칭 dedup·self-loop 없음·dangling 없음)을 모두 통과하면 완료.

---

## 1. 왜 필요한가 — head/tail 은 깨끗한데 type 은 아직 더럽다

04 가 점을 합쳤다. `Light RAG`·`LightRag` 가 `LightRAG` 한 노드로 모였고, 관계의 head/tail 은 전부 canonical 이름으로 재배선됐다. 그런데 관계의 **타입**은 손대지 않았다. 04 의 `relations.resolved.jsonl` 을 열어 보면 타입이 여전히 추출기가 찍은 표면형 그대로다.

문제가 셋 보인다. 첫째, 같은 의미가 여러 술어로 흩어져 있다. "LightRAG 가 Neo4j 를 쓴다"는 사실이 `USES`·`UTILIZES`·`USED_BY` 세 가지로 찍혔다. Neo4j 에 그대로 올리면 같은 의미의 엣지가 타입만 달리해 세 개로 쪼개진다. "LightRAG 가 쓰는 도구는?" 이라는 멀티홉 질문에서 한 타입만 매칭되고 나머지는 샌다.

둘째, 방향이 뒤죽박죽이다. `Neo4j -[USED_BY]-> LightRAG` 와 `LightRAG -[USES]-> Neo4j` 는 같은 사실인데 방향이 반대다. `COMPARES_TO` 는 더 고약하다 — "A 가 B 와 비교된다"와 "B 가 A 와 비교된다"가 둘 다 참이라, 추출기가 양쪽을 다 찍어 한 비교가 두 엣지로 부푼다.

셋째, 이항 엣지로는 못 담는 사실이 있다. 03 이 만든 `events.jsonl` 에 "RAG was published at NeurIPS in 2020" 이 있다. 참여자가 셋이다 — RAG, NeurIPS, 그리고 2020 이라는 시간. `(head)-[type]->(tail)` 두 자리로는 셋을 못 앉힌다.

정규화하지 않으면 같은 사실이 여러 타입·여러 방향·여러 노드로 쪼개진다. 카운트는 부풀고 멀티홉은 끊긴다. 그래프 품질을 결정하는 건 추출이 아니라 정제다 — Phase 2 의 그 문장이 여기서 마지막으로 한 번 더 작동한다.

## 2. 통제 어휘 — 술어의 단일 기준

LLM 에게 "관계를 뽑아라"고 하면 매번 다른 동사를 쓴다. 막을 방법은 하나다. **canonical type 의 닫힌 목록**을 정하고, 표면형 술어를 거기로 매핑하는 표를 둔다. 이게 통제 어휘(Controlled Vocabulary)다.

`relation_vocab.yaml` 한 파일이 그 단일 기준이다. canonical type 마다 동의어 목록, 대칭/비대칭, inverse 짝꿍을 적는다.

```yaml
# practice/relation_vocab.yaml 의 일부
relations:
  USES:
    synonyms: [USES, UTILIZES, EMPLOYS, RELIES_ON, BUILT_ON, STORES_IN]
    symmetry: asymmetric
    inverse: USED_BY        # USED_BY 로 들어오면 USES 로 flip
  COMPARES_TO:
    synonyms: [COMPARES_TO, COMPARED_WITH, COMPARED_TO, VERSUS]
    symmetry: symmetric     # 비교는 양방향 — (head,tail) 정렬해 한 엣지로 dedup
canonical_directions: [USES, IMPROVES, DEVELOPED_BY]
```

`USES` 의 `synonyms` 에 `UTILIZES`·`EMPLOYS` 가 들어 있으니 이 표면형들은 전부 `USES` 가 된다. 목록에 없는 술어(예: `INSPIRED_BY`)는 매핑이 없다 — 자동으로 통과시키지 않고 reject 로 뺀다. 어휘를 닫아 두는 게 핵심이다. 새 술어가 필요하면 사람이 vocab 에 추가하는 결정을 내려야 하고, 그 결정이 로그로 남는다(2/06 품질 게이트로 이어진다).

매핑 자체는 단순하다. 표면형을 대문자로 올려 표를 조회한다.

```python
# practice/normalize_relations.py — 동의어 정규화의 핵심
def canonical_type(self, surface: str) -> str | None:
    """표면형 술어 → canonical type. 미등록이면 None."""
    return self.synonym_to_canonical.get(surface.upper())
```

04 가 엔티티 표기 흔들림을 fuzzy 로 잡았던 것과 달리, 관계 타입은 통제 어휘 정확 매칭으로 간다. 술어 종류는 엔티티보다 훨씬 적고, "어떤 타입을 허용할지"는 스키마 결정이라 사람이 명시적으로 쥐고 있어야 한다. 흔들림은 fuzzy 가 아니라 `synonyms` 목록으로 흡수한다.

## 3. 방향 정규화 — 대칭은 정렬, 비대칭은 flip

타입을 통일했으면 방향을 통일한다. 관계를 둘로 나눈다.

**대칭(symmetric)** 관계는 head/tail 의 구분이 의미가 없다. `COMPARES_TO`·`RELATED_TO` 가 그렇다. "A 가 B 와 비교된다"와 "B 가 A 와 비교된다"는 같은 사실이다. 그러니 (head, tail) 을 이름순으로 정렬해 한 방향으로만 저장한다. 그러면 두 표면형이 같은 키로 모여 한 엣지로 dedup 된다.

**비대칭(asymmetric)** 관계는 방향이 의미를 바꾼다. `USES`·`IMPROVES` 가 그렇다. "LightRAG 가 Neo4j 를 쓴다"와 "Neo4j 가 LightRAG 를 쓴다"는 전혀 다른 말이다. 문제는 추출기가 가끔 역방향 술어(`USED_BY`)로 찍는다는 것이다. vocab 의 `inverse` 정의를 보고, 역방향으로 들어온 엣지를 head/tail 을 뒤집어 canonical 방향으로 통일한다.

```python
# practice/normalize_relations.py — 방향 정규화
def _normalize_direction(rel, canon_type, vocab):
    head, tail = rel.head, rel.tail
    symmetry = vocab.symmetry.get(canon_type, "asymmetric")

    if symmetry == "symmetric":
        a, b = sorted([head, tail])        # 정렬 → A~B 와 B~A 가 같은 키로 모인다
        return a, canon_type, b

    # asymmetric: canonical_directions 에 없는 타입이면 inverse 로 flip
    final_type = canon_type
    if canon_type not in vocab.canonical_directions and canon_type in vocab.inverse:
        final_type = vocab.inverse[canon_type]   # 짝꿍의 canonical 방향(USES)
        head, tail = tail, head                  # 방향도 뒤집는다
    return head, final_type, tail
```

`Neo4j -[USED_BY]-> LightRAG` 가 들어오면 `USED_BY` 는 `canonical_directions` 에 없으니 inverse 인 `USES` 로 바꾸고 head/tail 을 뒤집는다. 결과는 `LightRAG -[USES]-> Neo4j`. 같은 사실을 다르게 찍은 세 표면형(`USES`/`UTILIZES`/`USED_BY`)이 이제 한 키로 모인다.

마지막으로 **self-loop**(head==tail)를 막는다. `LightRAG -[RELATED_TO]-> LightRAG` 같은 엣지는 추출 노이즈이거나 정규화 과정에서 양끝이 같은 canonical 로 모인 잔해다. 의미가 없으니 reject 로 뺀다.

## 4. dedup — 합치되 근거는 리스트로 살린다

정규화하면 서로 다른 표면형이 같은 `(head, canonical_type, tail)` 로 모인다. 이걸 한 엣지로 합친다. 단, **provenance 를 버리지 않고 리스트로 누적**한다. 카운트와 근거 quote 가 살아 있어야 2/06 품질 게이트가 "이 엣지는 근거 3건짜리"라고 판단하고, Phase 4 GraphRAG 가 인용을 붙인다.

```python
# practice/normalize_relations.py — dedup + provenance 누적
key = (head, final_type, tail)
if key in bucket:
    bucket[key].provenances.append(rel.provenance)   # 근거를 버리지 않고 쌓는다
else:
    bucket[key] = NormalizedRelation(
        head=head, type=final_type, tail=tail,
        direction=symmetry, provenances=[rel.provenance],
    )
```

`support = len(provenances)` 가 그 엣지를 떠받치는 근거 수다. `USES` 가 세 문서에서 나왔으면 `support=3`. 04 가 엔티티의 `member_count` 로 빈도를 남겼듯, 여기선 관계의 support 가 빈도다.

## 5. n-ary 관계 — Event 로 reify 한다

이항 엣지로 못 담는 사실은 어떻게 하나. W3C 의 n-ary relations note 는 답을 명확히 한다 — **관계 자체를 노드로 올려라(reify)**. 두 자리(head, tail)에 안 들어가는 셋 이상의 참여자를, 노드 하나에 role 슬롯으로 붙인다.

"RAG was published at NeurIPS in 2020" 을 Event 로 올리면 이렇게 된다. `PUBLICATION` 타입 노드 하나에 `published_work=RAG`, `venue=NeurIPS`, `year=2020`. 03 의 `events.jsonl` 은 참여자를 `["RAG", "NeurIPS"]` 라는 밋밋한 리스트로만 들고 있었다. 여기에 role 라벨을 붙이는 게 이번 일이다.

role 배정은 결정적인 휴리스틱으로 한다. event name 토큰으로 vocab event type 을 찾고, 시간 값은 `time_role`(year)에 박고, 나머지 participants 를 남은 role 슬롯에 순서대로 채운다.

```python
# practice/model_events.py — participants 에 role 부여
canon_type = _match_event_type(ev.name, synonym)   # "RAG_publication" → PUBLICATION
spec = vocab[canon_type]
roles: dict[str, str] = {}

# 1) time 값을 time_role(year) 슬롯에 먼저 박는다
remaining_roles = list(spec["roles"])
if ev.time and spec["time_role"] in remaining_roles:
    roles[spec["time_role"]] = ev.time
    remaining_roles.remove(spec["time_role"])

# 2) 남은 participants 를 남은 role 슬롯에 순서대로 채운다
for participant, role in zip(ev.participants, remaining_roles):
    roles[role] = participant
```

수치 클레임도 필요하면 Event 로 모델링한다. 03 의 `claims.jsonl` 에 `{subject:LightRAG, predicate:reduces_token_cost, object:GraphRAG, value:"99%"}` 가 있다. "얼마나(99%)"와 "무엇 대비(GraphRAG)"를 함께 담으려면 이항으로는 부족하다. `MEASUREMENT` Event 로 reify 하면 `subject=LightRAG, metric=reduces_token_cost, value=99%, baseline=GraphRAG` 가 한 노드에 앉는다(`--with-claims` 로 시연).

```bash
python run_normalize.py                 # 시연 sample (기본, 키 불필요)
python run_normalize.py --with-claims   # 수치 claim 도 MEASUREMENT Event 로
```

> 전체 코드와 실행 절차는 [`practice/`](practice/) 와 [`labs/`](labs/) 참조.
> 이 토픽은 LLM·임베딩을 부르지 않는다(통제 어휘 정확 매칭 + 결정적 휴리스틱). 그래서 키도 비용도 없다. 술어를 fuzzy 로도 묶고 싶으면 04 의 rapidfuzz 를 끌어와 `synonyms` 매칭 앞단에 붙일 수 있다.

## 6. 결과 해석

`run_normalize.py` 를 sample 로 돌리면 이렇게 찍힌다.

```
관계 정규화: 12건 → 7 canonical 엣지 (dedup 으로 3건 합쳐짐) · reject 2건

정규화된 엣지(근거 개수 = support):
  (GraphRAG)-[COMPARES_TO]->(LightRAG)  [symmetric, support=2]
  (GraphRAG)-[DEVELOPED_BY]->(Microsoft)  [asymmetric, support=1]
  (LightRAG)-[DEVELOPED_BY]->(HKUDS)  [asymmetric, support=1]
  (CRAG)-[IMPROVES]->(RAG)  [asymmetric, support=1]
  (GraphRAG)-[IMPROVES]->(RAG)  [asymmetric, support=1]
  (Self-RAG)-[IMPROVES]->(RAG)  [asymmetric, support=1]
  (LightRAG)-[USES]->(Neo4j)  [asymmetric, support=3]

reject(미등록 술어 / self-loop):
  (LightRAG)-[RELATED_TO]->(LightRAG)  — self-loop(head==tail)
  (Self-RAG)-[INSPIRED_BY]->(RAG)  — vocab 미등록 술어
```

읽을 게 넷이다. 첫째, `USES`·`UTILIZES`·`USED_BY` 세 표면형이 `(LightRAG)-[USES]->(Neo4j)` 한 엣지로 모였다(`support=3`). 동의어 정규화 + inverse flip + dedup 이 함께 일했다. 둘째, `COMPARES_TO` 가 (GraphRAG, LightRAG) 로 정렬돼 양방향 두 건이 한 엣지가 됐다(`support=2`). 셋째, `OUTPERFORMED_BY`(RAG 가 GraphRAG 에게)가 `IMPROVES`(GraphRAG 가 RAG 를)로 flip 됐다. `ENHANCES`·`CREATED_BY` 도 각각 `IMPROVES`·`DEVELOPED_BY` 로 흡수됐다. 넷째, self-loop 와 미등록 술어 `INSPIRED_BY` 가 reject 로 빠졌다 — 통과시키지 않고 근거까지 남겨 따로 보관한다.

Event 도 보자.

```
Event reification: 2건 → 2 reified Event (reject 0건)
  [PUBLICATION] evt-publication-rag-publication  {year=2020, published_work=RAG, venue=NeurIPS}
  [PUBLICATION] evt-publication-graphrag-release  {year=2024, published_work=GraphRAG, venue=Microsoft}
```

`["RAG", "NeurIPS"]` 라는 밋밋한 리스트가 `published_work=RAG, venue=NeurIPS, year=2020` 으로 role 을 얻었다. 이항 엣지로는 못 담던 3항 사실이 이제 노드 하나에 구조적으로 앉는다.

휴리스틱의 한계도 하나 드러난다. 두 번째 이벤트의 `venue=Microsoft` 는 사실 Microsoft 가 venue 가 아니라 개발 주체다. 순서 기반 role 배정이 "Microsoft 가 두 번째 참여자라서 두 번째 슬롯(venue)에 들어간" 결과다. 강의용으로는 결정적이고 단순해서 충분하지만, 실전에서는 참여자 타입 신호(Organization 이면 developer, Venue 면 venue)로 role 을 추론해야 한다. 정규화는 한 번에 완벽해지지 않는다 — vocab 과 role 규칙을 데이터를 보며 조여 가는 과정이다.

마지막으로 `validate_normalization.py` 가 4종을 검증한다. (a) 모든 relation type 이 vocab canonical 에 속하는가 — 미등록이 새어 들어오지 않았는가. (b) symmetric 엣지가 정렬·dedup 됐는가 — A~B 와 B~A 가 두 엣지로 남지 않았는가. (c) self-loop 가 없는가. (d) relation 의 head/tail 과 event 의 role 엔티티가 전부 canonical 집합 안에 있는가(시간 리터럴은 예외). 넷 다 PASS 면 Neo4j 적재(Phase 3) 전 마지막 게이트를 통과한 것이다.

산출물 셋(`normalized_relations.jsonl`·`events.normalized.jsonl`·`reject_relations.jsonl`)이 2/06(품질 게이트·증분 적재)의 입력이다.

---

## 🚨 자주 하는 실수

1. **vocab 에 없는 술어를 그냥 통과시킨다** — "모르는 술어니까 일단 넣고 보자"는 그래프를 술어 난장판으로 만든다. LLM 은 무한히 새 동사를 만들어 내고, 그걸 다 받으면 통제 어휘를 둔 의미가 없다. 미등록 술어는 반드시 reject 로 빼고 근거와 함께 로그에 남겨라. 진짜 필요한 타입이면 사람이 vocab 에 추가하는 결정을 내린다 — 그 결정이 곧 스키마 거버넌스다(2/06).
2. **모든 관계를 비대칭으로 취급한다** — `COMPARES_TO`·`RELATED_TO` 를 비대칭으로 두면 추출기가 찍은 양방향 두 건이 끝까지 두 엣지로 남는다. 카운트가 두 배로 부풀고 멀티홉이 헛돈다. 대칭 관계는 vocab 에서 `symmetric` 으로 명시하고 (head,tail) 을 정렬해 한 방향으로만 저장하라. 반대로 `USES` 를 대칭으로 잘못 두면 "Neo4j 가 LightRAG 를 쓴다"는 헛소리가 정렬돼 살아남는다 — 대칭/비대칭 분류는 신중히.
3. **n-ary 사실을 이항 엣지로 욱여넣는다** — "RAG 가 2020 년 NeurIPS 에서 발표됐다"를 `(RAG)-[PUBLISHED_AT]->(NeurIPS)` 로만 적으면 2020 이라는 시간이 증발한다. 시간·수치·조건처럼 두 자리 밖의 정보가 붙는 사실은 Event 로 reify 하라. 이항으로 욱여넣으면 그때그때는 편하지만, 나중에 "2020 년에 발표된 모델"을 묻는 시점 질의에서 답을 못 한다.

## 출처

- Graph RAG Survey (Construction) — arXiv 2408.08921, https://arxiv.org/abs/2408.08921
- Defining N-ary Relations on the Semantic Web (W3C Working Group Note) — https://www.w3.org/TR/swbp-n-aryRelations/
- Pydantic — https://docs.pydantic.dev/
- rapidfuzz (술어 fuzzy 매칭, 선택) — https://github.com/rapidfuzz/RapidFuzz

## 다음 토픽

→ [품질 게이트·증분 적재](../06-quality-gate-incremental/lesson.md)
