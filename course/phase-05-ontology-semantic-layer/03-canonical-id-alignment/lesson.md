# 5.3 Canonical ID · Ontology Alignment (alias → 표준 개념)

> **Phase 5 · 토픽 03** · 02 의 concept_id 에 불변 표준 ID(Canonical ID)를 발급하고, 우리 개념을 arXiv·Wikidata 같은 외부 온톨로지에 정렬(alignment)한다.

## 학습 목표

이 토픽을 끝내면 다음을 할 수 있다.

- concept_id 슬러그에서 불변·안정적인 **Canonical ID(URI)**를 발급하고, 표기(label)와 ID 를 분리한다.
- 내부 개념을 외부 KB(arXiv·Wikidata·GitHub)에 매핑하는 **정렬 테이블**을 SKOS mapping property(exact/close/broad/narrow) + confidence + source 로 설계하고 Pydantic 으로 검증한다.
- Entity Resolution 산출(같은 실체의 여러 raw 노드)을 하나의 Canonical ID 로 **병합**하면서 alias·출처를 보존한다.
- `resolve_to_external(concept_id, target_kb)` 크로스워크로 외부 ID·URL 을 조회하고, 정렬 **커버리지 리포트**로 빈틈을 계측한다.

**완료 기준**: `resolve` 로 얻은 concept_id `self-rag` 가 canonical URI `urn:kb:concept:self-rag` 로 발급되고, 정렬 테이블에서 arXiv exactMatch·Wikidata 정렬이 crosswalk 로 조회되며, 같은 concept 에 exactMatch 2건이 들어오면 경고가 뜨면 완료.

---

## 1. 왜 필요한가 — 표기를 접었다고 식별이 끝난 게 아니다

02 에서 표기(label) 표준화를 마쳤다. `Self-RAG` · `SELF-RAG` · `self rag` 가 전부 `resolve()` 를 거쳐 concept_id `self-rag` 로 접힌다. 여기까지가 "어휘 통제"다.

그런데 두 가지가 아직 남아 있다.

첫째, `self-rag` 라는 짧은 슬러그는 **우리 레지스트리 안에서만** 유일하다. Neo4j 에 넣고 RDF 로 내보내고 다른 팀·다른 KB 와 섞이는 순간, `self-rag` 같은 흔한 슬러그는 충돌하기 쉽다. 전역에서 유일하고 표기가 바뀌어도 안 흔들리는 **불변 식별자**가 필요하다. 그게 Canonical ID 다.

둘째, 우리 `self-rag` 가 실제로는 arXiv 논문 2310.11511 이고 Wikidata 의 어떤 개념과 같다는 사실을 기계가 알아야 한다. 그래야 외부 데이터와 통합하고 중복을 잡고 답변에 논문 링크를 붙인다. 이 매핑이 없으면 우리 KG 는 외딴 섬이다. 외부 표준에 개념을 이어 붙이는 작업이 Ontology Alignment 다.

02 가 "표기 문제"였다면 03 은 **식별(identity) 문제**다. 표기를 접었으니 개념당 한 번만 ID 를 발급하고, 한 번만 외부 정렬을 하면 된다.

## 2. Canonical ID — 표기와 ID를 분리한다

핵심 직관은 하나다. **표기는 바뀌고 ID 는 안 바뀐다.** 논문 저자가 기법 이름을 `Self-RAG` 에서 다른 이름으로 바꿔도 우리가 붙인 ID 는 그대로여야 한다. 그래야 이 ID 를 참조하던 모든 엣지·매핑·인용이 안 깨진다.

그래서 concept_id(슬러그)에 네임스페이스를 붙여 URI 로 승격한다.

```
self-rag  →  urn:kb:concept:self-rag
```

`urn:kb:concept:` 는 우리 KB 의 네임스페이스다. 이걸 붙이면 다른 KB 의 `self-rag` 와도 안 겹친다. 발급은 concept_id 에서 **결정론적**으로 파생하므로 재실행해도 같은 값이 나온다.

```python
# practice/canonical_id.py 의 핵심
CANONICAL_NS = "urn:kb:concept:"

def to_canonical_id(concept_id: str) -> str:
    """concept_id(슬러그) -> Canonical URI. 결정론적이라 재실행해도 같은 값."""
    if not _is_slug(concept_id):
        raise ValueError(f"concept_id 는 슬러그여야 한다: {concept_id!r}")
    return f"{CANONICAL_NS}{concept_id}"
```

발급기는 concept 마다 레코드를 만들고 **충돌을 검사**한다. 서로 다른 개념이 같은 URI 를 가지면 즉시 실패한다. 식별자가 겹치는 순간 그래프가 오염되기 때문이다.

```python
# 서로 다른 concept 이 같은 canonical_id 를 가지면 로드 자체가 실패한다
if rec.canonical_id in self._by_canonical:
    other = self._by_canonical[rec.canonical_id]
    raise ValueError(f"canonical_id 충돌: {rec.canonical_id!r} 를 "
                     f"{other.concept_id!r} 와 {rec.concept_id!r} 가 함께 가진다")
```

## 3. Ontology Alignment — 외부 표준에 개념을 잇는다

우리 개념 하나를 외부 KB 개념 하나에 매핑한다. 이때 "얼마나 같은가"를 등급으로 기록해야 한다. 완전히 같은 것과 비슷하지만 미묘하게 다른 것을 같은 취급하면, 나중에 데이터를 잘못 합친다. 등급은 **SKOS mapping property** 를 그대로 빌려 쓴다.

- `exact` (skos:exactMatch) — 사실상 동일. 교체 가능. KB별 1개가 이상적.
- `close` (skos:closeMatch) — 거의 같지만 미묘한 차이. 교체는 조심.
- `broad` (skos:broadMatch) — 외부가 더 넓은 상위 개념.
- `narrow` (skos:narrowMatch) — 외부가 더 좁은 하위 개념.

매핑마다 `confidence`(0~1)와 `source`(누가 만들었나)를 함께 남긴다. 사람이 확인했으면 1.0, LLM 이 제안했으면 낮게 준다. source 는 감사 추적용이다.

```yaml
# practice/alignment.yaml 의 한 조각
mappings:
  - internal: self-rag
    target_kb: arxiv
    external_id: "2310.11511"     # Self-RAG 원논문
    match_type: exact
    confidence: 1.0
    source: manual
  - internal: self-rag
    target_kb: wikidata
    external_id: "Q108048247"     # 위키데이터에 Self-RAG 전용 항목이 없어 상위 RAG 개념에 broad
    match_type: broad
    confidence: 0.6
    source: llm-suggested
```

같은 `self-rag` 라도 arXiv 에는 정확히 대응하는 논문이 있어 `exact`, Wikidata 에는 전용 항목이 없어 상위 개념에 `broad` 로 건다. KB마다 정렬 강도가 다른 게 정상이다.

이 테이블을 Pydantic 이 검증한다. `match_type` 은 네 값 중 하나여야 하고, `confidence` 는 0~1, 모든 `internal` 은 실제 concept_id 여야 한다(무결성). 여기에 품질 경고를 하나 더 얹는다.

```python
# practice/alignment_model.py — 같은 (concept, kb)에 exactMatch가 2개 이상이면 경고
exact_count: dict[tuple[str, str], list[str]] = {}
for m in self.mappings:
    if m.match_type == "exact":
        exact_count.setdefault((m.internal, m.target_kb), []).append(m.external_id)
for (cid, kb), ext_ids in exact_count.items():
    if len(ext_ids) > 1:
        warnings.append(AlignmentWarning(
            code="MULTIPLE_EXACT", concept_id=cid, target_kb=kb,
            detail=f"exactMatch {len(ext_ids)}개: {ext_ids} — 하나만 남기거나 close 로 낮춰라"))
```

한 개념이 한 KB 에서 동시에 두 ID 와 "정확히 같다"는 건 보통 데이터 오류다. 다만 이건 **에러가 아니라 경고**다. 로드는 되되 사람이 판단하도록 리포트에 남긴다. 스키마·무결성 위반은 데이터가 깨진 것이라 에러로 멈추지만, exactMatch 중복은 판단의 문제라 자동으로 막지 않는다.

> LLM 으로 정렬 후보를 뽑고 싶으면(source=`llm-suggested`), Claude 에 "이 개념에 맞는 Wikidata QID 후보를 confidence 와 함께 제시" 프롬프트를 태우면 된다. 비용이 부담되면 Ollama + `bge-m3` 임베딩으로 외부 개념 사전과 유사도 매칭해 후보를 제안해도 된다. 어느 쪽이든 **사람이 confidence 를 확정**하는 게 핵심이다.

## 4. Entity Resolution 산출을 Canonical ID로 병합

Phase 2 Entity Resolution 을 거쳐도 같은 실체가 표기·출처가 달라 여러 raw 노드로 남는다. `Self-RAG`(arXiv), `Self-Reflective RAG`(블로그), `SELF-RAG`(다른 논문) 는 한 실체다. 02 의 `resolve()` 로 각 raw 노드를 concept_id 로 접고, 03 의 canonical id 로 하나의 표준 노드에 병합한다.

병합할 때 raw 표기·출처를 **버리지 않고** alias 테이블에 보존하는 게 핵심이다. "n001=Self-RAG, n003=SELF-RAG 가 이 canonical 로 접혔다"는 근거가 있어야 나중에 감사·롤백이 된다. 프로비넌스(어디서 왔나)를 잃으면 병합이 블랙박스가 된다.

```python
# practice/merge_entities.py — resolve로 접고 canonical id로 묶되 alias를 남긴다
res = vocab.resolve(raw["surface"])
if not res.resolved:
    unresolved.append(alias)         # 어휘에 없으면 신규 후보로 따로
    continue
rec = registry.get(res.concept_id)   # 발급된 canonical 레코드
node = bucket.get(rec.canonical_id)  # 같은 canonical끼리 한 버킷에
if node is None:
    node = CanonicalNode(canonical_id=rec.canonical_id, concept_id=rec.concept_id,
                         preferred_label=rec.preferred_label, entity_type=rec.entity_type)
    bucket[rec.canonical_id] = node
node.aliases.append(alias)           # raw 표기·출처를 근거로 보존
```

어휘에 없는 raw(`FancyRAG`)는 병합하지 않고 `unresolved` 로 남긴다. 이건 실패가 아니라 신규 개념 후보다. 사람이 보고 진짜 개념이면 어휘에 넣고, 아니면 버린다.

## 5. 크로스워크 조회 + 커버리지 리포트

정렬 테이블이 있으면 개념을 외부 ID·URL 로 조회할 수 있다. 한 개념·한 KB 에 후보가 여럿이면 match_type 우선순위(exact>close>broad>narrow), 동순위면 confidence 로 최선을 고른다.

```python
# practice/crosswalk.py 의 핵심
_MATCH_RANK = {"exact": 0, "close": 1, "broad": 2, "narrow": 3}

def resolve_to_external(table, concept_id, target_kb):
    cands = [m for m in table.mappings
             if m.internal == concept_id and m.target_kb == target_kb]
    if not cands:
        return None                                   # 그 KB엔 아직 미정렬
    best = min(cands, key=lambda m: (_MATCH_RANK[m.match_type], -m.confidence))
    url = table.external_kbs[best.target_kb].url_template.format(id=best.external_id)
    return ExternalRef(concept_id=concept_id, target_kb=target_kb,
                       external_id=best.external_id, match_type=best.match_type,
                       confidence=best.confidence, url=url)
```

커버리지 리포트는 concept 중 몇 %가 외부에 정렬됐는지, 어떤 개념이 아직 외딴 섬인지 보여준다. "다음에 무엇을 정렬할지"를 알려주는 계기판이다.

## 6. 결과 해석

`python crosswalk.py` 를 돌리면 이렇게 나온다.

```
== crosswalk 조회 ==
  self-rag   @ arxiv     -> 2310.11511     [exact] https://arxiv.org/abs/2310.11511
  self-rag   @ wikidata  -> Q108048247     [broad] https://www.wikidata.org/wiki/Q108048247
  ...
== 정렬 커버리지 리포트 ==
  전체: 6/8 = 75.0%
  arxiv    : 50.0%
  wikidata : 37.5%
  github   : 12.5%
  미정렬 개념: ['accuracy', 'hybrid-rag']
```

`self-rag` 는 arXiv 에는 `exact`, Wikidata 에는 `broad` 로 조회된다. 같은 개념이라도 KB마다 정렬 강도가 다르다는 걸 그대로 담는다. 전체 커버리지 75% 는 8개 중 6개가 외부 KB 하나 이상에 걸렸다는 뜻이다.

여기서 75% 를 어떻게 읽느냐가 중요하다. 100% 가 목표가 아니다. 미정렬로 잡힌 `accuracy`·`hybrid-rag` 중 외부에 대응 개념이 있는 것만 골라 정렬한다(labs 6단계에서 `accuracy` 를 넣어 87.5% 로 올린다). 대응 개념이 없으면 미정렬로 두는 게 맞다. 커버리지 리포트는 "어디를 이을지"와 "무엇을 남길지"를 함께 알려 준다.

> 전체 코드와 실행 절차는 [`practice/`](practice/) 와 [`labs/`](labs/) 참조. 네 스크립트 모두 마지막에 `assert` 로 완료 기준을 못박는다.

---

## 🚨 자주 하는 실수

1. **concept_id 를 그대로 Canonical ID 로 쓰고 네임스페이스를 안 붙인다.** `self-rag` 라는 슬러그는 우리 레지스트리 안에서만 유일하다. Neo4j·RDF·다른 팀과 섞이면 흔한 슬러그는 충돌한다. `urn:kb:concept:` 같은 네임스페이스를 붙여 전역에서 유일한 URI 로 승격해야 한다. 그래야 다른 KB 의 동명 개념과 안 겹친다.
2. **exactMatch 를 남발한다.** "비슷하니까 exact" 로 다 붙이면 나중에 외부 데이터를 잘못 합친다. Wikidata 에 Self-RAG 전용 항목이 없는데 상위 RAG 개념에 `exact` 를 걸면, 두 개념을 동일 취급해 오염된다. 상위/하위/근사는 각각 `broad`/`narrow`/`close` 로 낮춰라. 한 개념·한 KB 에 exactMatch 는 하나가 이상적이고, 둘 이상이면 경고가 뜬다.
3. **병합하면서 raw 표기·출처를 버린다.** `Self-RAG`·`SELF-RAG` 를 canonical 하나로 합칠 때 원래 표기와 source_doc 을 alias 로 남기지 않으면, 나중에 "이 노드가 어디서 왔나"를 추적할 수 없다. 병합은 되돌릴 수 있어야 한다. 프로비넌스를 alias 테이블에 보존해라.
4. **커버리지 100% 를 목표로 억지 매핑을 넣는다.** 리포트가 75% 라고 남은 개념을 전부 외부에 밀어 넣으면 안 된다. `hybrid-rag` 처럼 특정 외부 KB 에 정확한 대응이 없으면 미정렬로 두는 게 맞다. 억지로 걸면 confidence 낮은 매핑이 쌓여 crosswalk 품질이 떨어진다. 미정렬은 실패가 아니라 "정렬 안 하기로 한 결정"일 수 있다.

## 출처

- W3C SHACL 명세 — https://www.w3.org/TR/shacl/ · pySHACL — https://github.com/RDFLib/pySHACL
- W3C SKOS Reference(mapping properties: exactMatch·closeMatch·broadMatch·narrowMatch) — https://www.w3.org/TR/skos-reference/
- Pydantic — https://docs.pydantic.dev/
- Wikidata(외부 식별자·QID 체계) — https://www.wikidata.org
- *When Large Language Models Meet Knowledge Graphs for Question Answering: A Survey*, arXiv 2505.20099 — https://arxiv.org/abs/2505.20099

## 다음 토픽

→ [04-constraint-validation-shacl — Pydantic + SHACL-inspired Rule + Reject Reason](../04-constraint-validation-shacl/lesson.md)

