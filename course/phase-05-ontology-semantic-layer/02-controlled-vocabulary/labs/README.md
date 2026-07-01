# 5.2 Labs — Controlled Vocabulary 설계 핸즈온

01에서 파이썬 리터럴로 맛본 어휘를 정식 레지스트리(`vocabulary.yaml`)로 승격한다. Entity Type 카탈로그 + Relation Type 카탈로그 + 개념 레지스트리를 한 파일에 담고, Pydantic 로더로 검증하고, 추출기 raw 출력을 이 어휘에 매핑하거나 REJECT 하며 커버리지 리포트를 뽑는다.

이 토픽도 개념형이다. **API 키·Neo4j·인터넷 없이** 로컬에서 전부 돈다. 의존은 Pydantic v2 + PyYAML 둘뿐.

> 작업 폴더는 `practice/` 다. 아래 명령은 모두 `practice/` 에서 실행한다.
> `python` 명령이 없으면 `python3` 로 바꿔 실행한다.

---

## 0단계 — 설치

```bash
cd practice
pip install -r requirements.txt
```

**예상 출력**

```
Successfully installed pydantic-2.x PyYAML-6.x ...   (이미 있으면 "already satisfied")
```

---

## 1단계 — 레지스트리 로드 + 무결성 검증

`vocabulary.yaml` 을 읽어 규약(슬러그 형식·id 중복 금지·concept.entity_type 참조 무결성)을 통과하는지 확인한다.

```bash
python controlled_vocabulary.py
```

**예상 출력**

```
== 통제 어휘 로드 (version=2025.07) ==
  entity types  : 6
  relation types: 6
  concepts      : 8

== 개념 resolve ==
  OK     'Self-RAG'             -> self-rag     (Self-RAG, type=method, matched=preferred)
  OK     'Self-Reflective RAG'  -> self-rag     (Self-RAG, type=method, matched=alt)
  OK     'SELF-RAG'             -> self-rag     (Self-RAG, type=method, matched=preferred)
  OK     'self rag'             -> self-rag     (Self-RAG, type=method, matched=preferred)
  OK     'Corrective RAG'       -> crag         (CRAG, type=method, matched=alt)
  OK     '그래프RAG'              -> graphrag     (GraphRAG, type=method, matched=alt)
  REJECT 'FancyRAG'             -> NOT_IN_VOCABULARY: 개념 레지스트리에 없는 용어(신규 후보로 검토)

== relation type 매핑 ==
  OK     'USES'           -> USES (uses, matched=preferred)
  OK     'USE'            -> USES (uses, matched=alt)
  OK     'using'          -> USES (uses, matched=alt)
  OK     'evaluated on'   -> EVALUATED_ON (evaluated-on, matched=alt)
  OK     'PROPOSED_BY'    -> PROPOSED_BY (proposed-by, matched=preferred)
  REJECT 'MENTIONS'       -> NOT_IN_RELATION_TYPE_CATALOG: 카탈로그에 없는 타입(REJECT)

[assert] 모든 자체검증 통과
```

`Self-RAG`·`SELF-RAG`·`Self-Reflective RAG`·`self rag` 가 전부 `self-rag` 로 접힌다. `matched` 가 `preferred` 면 표준 표기에, `alt` 면 동의어에 맞았다는 뜻이다. 관계 축에서도 `USE`·`using` 같은 흔들림이 `USES` 하나로 접히고, 카탈로그에 없는 `MENTIONS` 는 REJECT 된다. 마지막 `[assert]` 줄이 뜨면 완료 기준의 절반(resolve·REJECT)이 코드로 검증된 것이다.

> **규약 위반을 일부러 내 본다.** `vocabulary.yaml` 에서 아무 `concept_id` 를 `Self-RAG`(대문자·하이픈)로 바꾸고 다시 실행하면 로드 단계에서 `ValidationError ... concept_id 는 소문자-하이픈 슬러그여야 한다` 로 멈춘다. 잘못된 어휘가 파이프라인에 흘러들기 전에 걸린다.

---

## 2단계 — 추출기 raw 출력을 어휘에 매핑 + 커버리지 리포트

`raw_extractions.json`(추출기가 뱉었다고 가정한 제각각의 type/label)을 통제 어휘에 매핑하거나 REJECT 하고, 몇 %가 매핑됐는지 리포트한다.

```bash
python normalize_extraction.py
```

**예상 출력**

```
== 엔티티 매핑 ==
  OK     Method      /Self-RAG               -> :method       concept=self-rag
  OK     Technique   /Self-Reflective RAG    -> :method       concept=self-rag
  OK     Model       /SELF-RAG               -> :method       concept=self-rag
  OK     Approach    /Corrective RAG         -> :method       concept=crag
  OK     Method      /그래프RAG                -> :method       concept=graphrag
  OK     Benchmark   /PopQA                  -> :dataset      concept=popqa
  OK     Dataset     /pop-qa                 -> :dataset      concept=popqa
  OK     Metric      /정확도                   -> :metric       concept=accuracy
  OK     Org         /Meta AI                -> :organization concept=meta-ai
  OK     Company     /FAIR                   -> :organization concept=meta-ai
  OK     Concept     /RAG                    -> :concept      concept=rag
  REJECT Method      /FancyRAG               -> label:NOT_IN_VOCABULARY: 개념 레지스트리에 없는 용어(신규 후보로 검토)
  REJECT Person      /Akari Asai             -> type:NOT_IN_ENTITY_TYPE_CATALOG: 카탈로그에 없는 타입(REJECT); label:NOT_IN_VOCABULARY: 개념 레지스트리에 없는 용어(신규 후보로 검토)

== 관계 매핑 ==
  OK     USES             -> USES (uses)
  OK     USE              -> USES (uses)
  OK     using            -> USES (uses)
  OK     EVALUATED_ON     -> EVALUATED_ON (evaluated-on)
  OK     eval on          -> EVALUATED_ON (evaluated-on)
  OK     COMPARES         -> COMPARES (compares)
  OK     PROPOSED_BY      -> PROPOSED_BY (proposed-by)
  OK     introduced by    -> PROPOSED_BY (proposed-by)
  OK     REPORTS          -> REPORTS (reports)
  REJECT MENTIONS         -> NOT_IN_RELATION_TYPE_CATALOG: 카탈로그에 없는 타입(REJECT)
  REJECT CITES            -> NOT_IN_RELATION_TYPE_CATALOG: 카탈로그에 없는 타입(REJECT)

== 커버리지 리포트 ==
  엔티티: 11/13 매핑  (85%)
  관계  : 9/11 매핑  (82%)
  REJECT 된 raw 는 어휘의 빈틈이다 — 신규 개념/타입 후보로 리뷰 큐에 올린다.

[assert] 모든 자체검증 통과
```

같은 개념이 `Method`/`Technique`/`Model` 세 타입, `Self-RAG`/`Self-Reflective RAG`/`SELF-RAG` 세 표기로 흩어져 들어와도 전부 `:method` + `concept=self-rag` 하나로 접힌다. `Meta AI` 와 `FAIR` 도 `meta-ai` 로 모인다. 반대로 카탈로그에 없는 `Person` 타입, 레지스트리에 없는 `FancyRAG`·`Akari Asai`, 미등록 관계 `MENTIONS`·`CITES` 는 통과하지 못하고 REJECT 로 격리된다.

커버리지 85%·82% 라는 숫자가 이 토픽의 핵심 산출물이다. 100%가 아니라는 게 정상이다 — REJECT 된 15%·18% 가 곧 어휘가 아직 못 담은 빈틈이고, `Akari Asai`(Person 타입 필요)·`CITES`(신규 관계 후보) 같은 항목이 다음 어휘 확장의 근거가 된다.

---

## 3단계 — 어휘를 확장해 커버리지를 올린다 (선택)

리포트가 가리킨 빈틈을 메워 본다. `vocabulary.yaml` 에 `person` entity type 과 `cites` relation type 을 추가한다.

`entity_types:` 아래에 추가:

```yaml
  - id: person
    label: Person
    definition: "저자·연구자 개인."
    alt_labels: ["Author", "Researcher"]
```

`relation_types:` 아래에 추가:

```yaml
  - id: cites
    label: CITES
    definition: "Paper 가 다른 Paper 를 인용한다."
    domain: Paper
    range: Paper
    alt_labels: ["CITE", "references"]
```

`concepts:` 아래에 추가(Akari Asai 를 person 개념으로):

```yaml
  - concept_id: akari-asai
    entity_type: person
    preferred_label: Akari Asai
    alt_labels: []
    definition: "Self-RAG 논문 제1저자."
```

다시 실행한다.

```bash
python normalize_extraction.py
```

**예상 출력**(끝부분)

```
== 커버리지 리포트 ==
  엔티티: 12/13 매핑  (92%)
  관계  : 10/11 매핑  (91%)
```

`Akari Asai`(엔티티)와 `CITES`(관계)가 이제 매핑되어 커버리지가 오른다. 남는 1건은 여전히 `FancyRAG` 다 — 실존하지 않는 기법이라 어휘에 넣지 않는 게 맞다. 어휘 확장은 이렇게 리포트가 가리킨 실제 빈틈만 골라 메우는 일이다. 무작정 alias 를 늘리는 게 아니다.

> 3단계에서 `akari-asai` assert 는 넣지 않았으므로, 확장 후에도 2단계 스크립트의 `[assert]` 는 그대로 통과한다(REJECT 집합만 줄어든다). 만약 자체검증까지 갱신하려면 `normalize_extraction.py` 의 assert 를 새 커버리지에 맞춰 고친다.

---

## 검증 체크리스트

- [ ] 1단계에서 `resolve('Self-Reflective RAG')` 가 `self-rag` 를 반환하고 `FancyRAG` 는 REJECT 된다.
- [ ] 1단계에서 미등록 관계 `MENTIONS` 가 REJECT 되고, `USE`·`using` 은 `USES` 로 접힌다.
- [ ] `vocabulary.yaml` 의 concept_id 를 대문자로 바꾸면 로드 단계에서 ValidationError 로 멈춘다.
- [ ] 2단계에서 엔티티 커버리지 11/13(85%), 관계 9/11(82%) 리포트가 출력된다.
- [ ] 2단계에서 `Akari Asai`(미등록 타입)·`CITES`(미등록 관계)가 REJECT 로 격리된다.
- [ ] (선택) 3단계에서 어휘를 확장하면 커버리지가 92%·91% 로 오른다.
