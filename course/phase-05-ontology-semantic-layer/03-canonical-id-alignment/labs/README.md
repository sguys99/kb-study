# Lab — Canonical ID · Ontology Alignment 핸즈온

02 에서 만든 `vocabulary.yaml`(concept_id 레지스트리)을 입력으로 받아, 개념마다 **불변 Canonical ID**를 발급하고 외부 KB(arXiv·Wikidata·GitHub)에 **정렬(alignment)**한다. 각 단계에 예상 출력을 붙였으니 결과를 대조하라.

## 준비

```bash
cd course/phase-05-ontology-semantic-layer/03-canonical-id-alignment/practice
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

이 폴더에는 02 산출물(`vocabulary.yaml`, `controlled_vocabulary.py`)이 이미 복사돼 있다. 실제 코스에서는 02 폴더를 가리켜도 된다. API 키·Neo4j·네트워크는 필요 없다. 전부 로컬에서 돈다.

> `pip`/venv 대신 `uv run --with "pydantic>=2.6" --with PyYAML python <파일>` 로 바로 실행해도 된다.

---

## 1단계 — Canonical ID 발급 (표기와 ID 분리)

concept_id 슬러그를 `urn:kb:concept:<slug>` URI 로 승격한다. 표기(`Self-RAG`)가 바뀌어도 이 URI 는 안 바뀐다.

```bash
python canonical_id.py
```

예상 출력:

```
== Canonical ID 발급 (8 concepts) ==
  self-rag     -> urn:kb:concept:self-rag      [method] aliases=5
  crag         -> urn:kb:concept:crag          [method] aliases=4
  graphrag     -> urn:kb:concept:graphrag      [method] aliases=4
  hybrid-rag   -> urn:kb:concept:hybrid-rag    [method] aliases=3
  rag          -> urn:kb:concept:rag           [concept] aliases=3
  popqa        -> urn:kb:concept:popqa         [dataset] aliases=3
  accuracy     -> urn:kb:concept:accuracy      [metric] aliases=3
  meta-ai      -> urn:kb:concept:meta-ai       [organization] aliases=4

== slugify 데모(표기 흔들림 흡수) ==
  'Self-Reflective RAG'  -> 'self-reflective-rag'
  'GraphRAG'             -> 'graphrag'
  'Corrective  RAG'      -> 'corrective-rag'
  '그래프RAG'               -> 'rag'

[assert] 모든 자체검증 통과
```

확인 포인트: 8개 concept 모두 `urn:kb:concept:` 접두어로 발급된다. 마지막 `[assert] 모든 자체검증 통과` 가 뜨면 결정론성·충돌검사가 다 통과한 것이다.

---

## 2단계 — 정렬 테이블 로드·검증

`alignment.yaml`(internal concept_id ↔ external_id + match_type + confidence + source)을 Pydantic 으로 검증하며 읽는다.

```bash
python alignment_model.py
```

예상 출력(발췌):

```
== 정렬 테이블 로드 (version=2025.07) ==
  external KBs : ['arxiv', 'wikidata', 'github']
  mappings     : 8

== 매핑 목록 ==
  self-rag     -[exact ]-> arxiv     2310.11511       (conf=1.0, src=manual)
  self-rag     -[broad ]-> wikidata  Q108048247       (conf=0.6, src=llm-suggested)
  crag         -[exact ]-> arxiv     2401.15884       (conf=1.0, src=manual)
  ...
  meta-ai      -[exact ]-> wikidata  Q94628726        (conf=0.85, src=manual)

== 품질 경고 ==
  (경고 없음)

[assert] 모든 자체검증 통과
```

정상 데이터에는 경고가 없다. `internal` 이 concept_id 카탈로그에 없으면(무결성 위반) 여기서 에러로 멈춘다.

---

## 3단계 — Entity Resolution 산출을 Canonical ID 로 병합

`raw_nodes.json` 은 Phase 2 Entity Resolution 이후에도 남은 raw 노드다(같은 실체가 표기·출처가 달라 여러 노드). concept_id 로 접고 canonical id 로 묶는다. 병합해도 raw 표기·출처는 alias 로 보존한다.

```bash
python merge_entities.py
```

예상 출력:

```
== 병합 결과 ==  raw 9개 -> canonical 4개 + unresolved 1개

  urn:kb:concept:crag
    preferred : CRAG [method]
    merged 2건: Corrective RAG, CRAG

  urn:kb:concept:graphrag
    preferred : GraphRAG [method]
    merged 2건: Graph RAG, 그래프RAG

  urn:kb:concept:popqa
    preferred : PopQA [dataset]
    merged 1건: PopQA

  urn:kb:concept:self-rag
    preferred : Self-RAG [method]
    merged 3건: Self-RAG, Self-Reflective RAG, SELF-RAG

== unresolved(신규 후보) ==
  n009 'FancyRAG' (blog:unknown) — 어휘에 없음

[assert] 모든 자체검증 통과
```

확인 포인트: `Self-RAG` / `Self-Reflective RAG` / `SELF-RAG` 3종이 **하나의** `urn:kb:concept:self-rag` 로 합쳐진다. `그래프RAG`(한글)와 `Graph RAG` 도 `graphrag` 로 함께 접힌다. 어휘에 없는 `FancyRAG` 는 병합하지 않고 신규 후보로 따로 남는다.

---

## 4단계 — 크로스워크 조회 + 커버리지 리포트

우리 개념을 외부 KB ID(+URL)로 조회하고, 개념 중 몇 %가 외부에 정렬됐는지 리포트한다.

```bash
python crosswalk.py
```

예상 출력:

```
== crosswalk 조회 ==
  self-rag   @ arxiv     -> 2310.11511     [exact] https://arxiv.org/abs/2310.11511
  self-rag   @ wikidata  -> Q108048247     [broad] https://www.wikidata.org/wiki/Q108048247
  crag       @ arxiv     -> 2401.15884     [exact] https://arxiv.org/abs/2401.15884
  graphrag   @ github    -> microsoft/graphrag [close] https://github.com/microsoft/graphrag
  accuracy   @ wikidata  -> (미정렬)

== self-rag 의 모든 외부 정렬 ==
  arxiv     2310.11511     [exact] conf=1.0
  wikidata  Q108048247     [broad] conf=0.6

== 정렬 커버리지 리포트 ==
  전체: 6/8 = 75.0%
  arxiv    : 50.0%
  wikidata : 37.5%
  github   : 12.5%
  미정렬 개념: ['accuracy', 'hybrid-rag']
```

확인 포인트: `self-rag` 는 arXiv 에는 `exact`, Wikidata 에는 `broad` 로 조회된다(같은 개념이라도 KB마다 정렬 강도가 다르다). `accuracy` 는 어디에도 정렬 안 돼 `(미정렬)` + `미정렬 개념` 목록에 뜬다. 전체 커버리지 75%.

---

## 5단계 — exactMatch 중복 경고 확인

한 개념이 한 외부 KB 에서 동시에 두 ID 와 "정확히 같다"는 건 보통 데이터 오류다. 인위로 넣어 경고가 뜨는지 본다.

```bash
python -c "
from alignment_model import load_alignment, AlignmentTable, Mapping
t = load_alignment()
d = t.model_copy(deep=True)
d.mappings.append(Mapping(internal='self-rag', target_kb='arxiv',
                          external_id='9999.99999', match_type='exact', confidence=0.5))
rv = AlignmentTable.model_validate(d.model_dump())
for w in rv.warnings:
    print(f'[{w.code}] {w.concept_id}/{w.target_kb}: {w.detail}')
"
```

예상 출력:

```
[MULTIPLE_EXACT] self-rag/arxiv: exactMatch 2개: ['2310.11511', '9999.99999'] — 하나만 남기거나 close 로 낮춰라
```

에러가 아니라 경고다(로드는 된다). 자동으로 막지 않고 사람이 판단하게 남긴다.

---

## 6단계 — 커버리지 올리기 (미정렬 개념 정렬)

4단계에서 `accuracy` 가 미정렬로 잡혔다. `alignment.yaml` 의 `mappings:` 아래에 한 줄 추가한다.

```yaml
  - internal: accuracy
    target_kb: wikidata
    external_id: "Q622425"          # (예시) accuracy 개념
    match_type: close
    confidence: 0.7
    source: manual
```

다시 `python crosswalk.py` 를 돌리면 커버리지가 오른다.

예상 변화:

```
== 정렬 커버리지 리포트 ==
  전체: 7/8 = 87.5%
  ...
  미정렬 개념: ['hybrid-rag']
```

75% → 87.5%. 리포트가 "다음에 무엇을 정렬할지"(`hybrid-rag`)를 정확히 짚어 준다. 커버리지 100%가 목표는 아니다. 외부 KB 에 대응 개념이 없으면 미정렬로 두는 게 맞다.

> 실습을 마쳤으면 6단계에서 추가한 줄을 되돌려도 되고, 그대로 두고 다음 토픽(04)으로 가도 된다.

---

## 자체검증 요약

`canonical_id.py` · `alignment_model.py` · `merge_entities.py` · `crosswalk.py` 는 모두 마지막에 `assert` 로 완료 기준을 못박는다. 네 파일 전부에서 `[assert] 모든 자체검증 통과` 가 뜨면 이 토픽 완료 기준을 만족한 것이다.
