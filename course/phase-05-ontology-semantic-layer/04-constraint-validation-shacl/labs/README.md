# Lab — Constraint Validation (Pydantic + SHACL-inspired Rule + Reject Reason) 핸즈온

03 에서 발급한 canonical id 와 02 의 통제 어휘 위에, 그래프에 넣기 직전 트리플·노드를 검증하는 **제약 엔진**을 돌린다. 정상은 PASS, 위반은 `rule_id`·`suggested_fix` 가 담긴 **reject reason** 으로 거른다. 각 단계에 예상 출력을 붙였으니 결과를 대조하라.

## 준비

```bash
cd course/phase-05-ontology-semantic-layer/04-constraint-validation-shacl/practice
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

이 폴더에는 02·03 산출물(`vocabulary.yaml`, `controlled_vocabulary.py`)이 이미 복사돼 있다. API 키·Neo4j·네트워크는 필요 없다. 전부 로컬에서 돈다.

> `pip`/venv 대신 `uv run --with "pydantic>=2.6" --with PyYAML python <파일>` 로 바로 실행해도 된다.

검증 대상 그래프는 `nodes.json`(9개 노드) + `triples.json`(9개 트리플)이다. 통과 케이스와 위반 케이스를 일부러 섞어 뒀다.

---

## 1단계 — Reject Reason 포맷 확인

두 트랙(Pydantic·SHACL-inspired)이 공유할 위반 리포트 포맷을 먼저 본다.

```bash
python reject_reason.py
```

예상 출력:

```
== reject reason 라인 ==
[REJECT ] UsesShape                  popqa-USES->self-rag     USES 는 (:Method)-[:USES]->(:Dataset) 여야 한다. 주어가 Dataset(popqa)  fix: 방향이 뒤집혔으면 subject/object 를 바꿔라
[WARN   ] MethodMustBeEvaluatedShape graphrag                 Method 노드는 최소 1개 Dataset 에서 EVALUATED_ON 관계를 가져야 한다  fix: 평가 데이터셋 관계 추출 누락 여부를 확인하라

== 요약 ==
위반 1건, 경고 1건
  rule 별 집계:
    MethodMustBeEvaluatedShape 1건
    UsesShape                  1건

[assert] 모든 자체검증 통과
```

한 위반은 `rule_id` / `severity` / `target` / `message` / `suggested_fix` 를 담는다. `violation` 은 적재를 막고, `warning` 은 적재는 되되 리포트에 남는다.

---

## 2단계 — Pydantic 트랙: 노드 레코드 스키마 검증

추출 파이프라인 인입 단계. 노드 한 개가 스키마(타입·필수·형식)에 맞는지 본다. `canonical_id` 누락, 카탈로그 밖 label 을 REJECT 한다.

```bash
python pydantic_models.py
```

예상 출력:

```
== Pydantic 노드 검증 (9개) ==
  PASS   self-rag     [Method]
  PASS   crag         [Method]
  PASS   graphrag     [Method]
  PASS   popqa        [Dataset]
  PASS   accuracy     [Metric]
  PASS   paper-2310   [Paper]
  PASS   meta-ai      [Organization]
  [REJECT ] Pydantic:NodeRecord.canonical_id no-canon                 Value error, canonical_id 누락: 표준 ID 없이 그래프에 넣을 수 없다  fix: 레코드 스키마(타입·필수·형식)를 맞춘 뒤 다시 넣어라
  [REJECT ] Pydantic:NodeRecord.label  bad-label                Value error, label 'Framework' 은 entity_types 카탈로그 밖(허용: ['Concept', 'Dataset', 'Method', 'Metric', 'Organization', 'Paper'])  fix: 레코드 스키마(타입·필수·형식)를 맞춘 뒤 다시 넣어라

결과: PASS 7건, REJECT 2건

[assert] 모든 자체검증 통과
```

Pydantic 은 **레코드 하나**만 본다. `no-canon`(canonical_id 빈 값), `bad-label`(Framework 는 카탈로그 밖)이 여기서 걸린다. 하지만 관계 방향이 뒤집혔는지 같은 **그래프 전역** 문제는 Pydantic 이 못 본다. 그건 3단계 몫이다.

---

## 3단계 — SHACL-inspired 트랙: 그래프 제약 검증(핵심)

`shapes.yaml` 을 로드해 그래프 전역 제약을 건다. domain/range, 미등록 관계, dangling 참조, canonical 필수, 카디널리티를 한 번에 본다.

```bash
python rule_engine.py
```

예상 출력:

```
== SHACL-inspired 그래프 검증 (nodes=9, triples=9) ==

[REJECT ] NodeCommonShape            no-canon                 canonical_id 는 03 에서 발급한 urn:kb:concept:<slug> 형식이어야 한다 (path=canonical_id, value='')  fix: canonical_id.py 로 concept_id 에 Canonical ID 를 발급해 채워라
[REJECT ] NodeCommonShape            bad-label                label 은 entity_types 카탈로그의 폐쇄 집합 안에 있어야 한다 (path=label, value='Framework')  fix: Framework/Technique 같은 raw type 을 카탈로그 라벨(Method 등)로 매핑하라
[REJECT ] UsesShape                  popqa-USES->self-rag     USES 는 (:Method)-[:USES]->(:Dataset) 여야 한다 — 실제 (:Dataset)-[:USES]->(:Method)  fix: 주어/목적어 타입을 확인하라. 방향이 뒤집혔으면 subject/object 를 바꿔라
[REJECT ] ReportsShape               paper-2310-REPORTS->popqa REPORTS 는 (:Paper)-[:REPORTS]->(:Metric) 여야 한다 — 실제 (:Paper)-[:REPORTS]->(:Dataset)  fix: 보고 주체는 Paper, 보고 대상은 Metric 이어야 한다
[REJECT ] UnknownRelationShape       self-rag-MENTIONS->popqa 관계 타입 'MENTIONS' 은 relation_types 카탈로그 밖  fix: 카탈로그의 관계(USES/EVALUATED_ON/COMPARES/…)로 매핑하거나 어휘에 추가하라
[REJECT ] UsesShape                  self-rag-USES->no-canon  USES 는 (:Method)-[:USES]->(:Dataset) 여야 한다 — 실제 (:Method)-[:USES]->(:Method)  fix: 주어/목적어 타입을 확인하라. 방향이 뒤집혔으면 subject/object 를 바꿔라
[REJECT ] DanglingReferenceShape     self-rag-USES->ghost     참조 노드 없음(dangling): ['ghost']  fix: 트리플이 가리키는 노드를 먼저 적재하거나, 오탈자를 고쳐라
[WARN   ] MethodMustBeEvaluatedShape crag                     Method 노드는 최소 1개 Dataset 에서 EVALUATED_ON 관계를 가져야 한다 — 현재 0개(<1)  ...
[WARN   ] MethodMustBeEvaluatedShape graphrag                 ... 현재 0개(<1)  ...
[WARN   ] MethodMustBeEvaluatedShape no-canon                 ... 현재 0개(<1)  ...

== 집계 ==
위반 7건, 경고 3건
  rule 별 집계:
    MethodMustBeEvaluatedShape 3건
    NodeCommonShape            2건
    UsesShape                  2건
    DanglingReferenceShape     1건
    ReportsShape               1건
    UnknownRelationShape       1건

적재 가능 여부(passed): False

[assert] 모든 자체검증 통과
```

무엇을 대조하나:

- `self-rag-USES->popqa`(정상)는 **어떤 줄에도 안 나온다** → PASS.
- `popqa-USES->self-rag` → **domain/range 위반**(`UsesShape`). 방향이 뒤집혔다.
- `paper-2310-REPORTS->popqa` → **range 위반**(`ReportsShape`). REPORTS 의 대상은 Metric 인데 Dataset 을 가리킨다.
- `self-rag-MENTIONS->popqa` → **미등록 관계**(`UnknownRelationShape`). MENTIONS 는 카탈로그 밖.
- `self-rag-USES->ghost` → **dangling**(`DanglingReferenceShape`). ghost 노드가 없다.
- `no-canon` 노드 → **canonical_id 누락**(`NodeCommonShape`).
- `bad-label` 노드 → **label 폐쇄 집합 밖**(`NodeCommonShape`).
- `crag`·`graphrag` → **카디널리티 경고**(`MethodMustBeEvaluatedShape`). Method 인데 평가 관계가 없다. 경고라 적재를 막지는 않는다.

`적재 가능 여부(passed): False` — violation 이 7건이라 이 배치는 그대로 적재하면 안 된다. 위반을 고치거나 reject queue 로 보낸 뒤 다시 검증한다.

---

## 4단계 — 위반을 고치면 PASS 로 바뀌는지 확인

방향이 뒤집힌 트리플 하나를 고쳐 본다. `triples.json` 을 열어 `popqa-USES->self-rag` 를 정상 방향으로 바꾼다(예: object 를 `popqa`, subject 를 `self-rag` 로 이미 있는 정상 트리플이므로, 위반 트리플 줄을 지우거나 방향을 바꾼다). 그리고 다시 3단계를 돌린다.

한 줄만 고쳐도 집계의 `UsesShape` 위반 수가 줄어드는 것을 확인하라. 이렇게 **위반→수정→재검증** 루프가 그래프 품질 게이트다(Phase 2 품질 게이트와 같은 흐름).

> 실습 확인용: 위반 트리플을 전부 지우고 돌리면 `위반 0건`(경고는 남을 수 있음), `적재 가능 여부(passed): True` 가 나온다.

---

## 5단계 (선택) — 진짜 SHACL(pyshacl)로 같은 range 제약 걸기

경량 엔진이 메인이다. 실무에서 RDF/트리플 스토어를 쓰면 표준 SHACL 로 넘어간다. 그 형태를 참고로 본다. **설치가 무거우니 선택이다.**

```bash
pip install "pyshacl>=0.26" "rdflib>=7.0"
python pyshacl_reference.py
```

예상 출력(설치했을 때):

```
conforms(모든 제약 통과 여부): False
== pyshacl Validation Report ==
Validation Report
Conforms: False
Results (1):
Constraint Violation in ClassConstraintComponent (...#ClassConstraintComponent):
	Severity: sh:Violation
	Focus Node: ex:self-rag
	Value Node: ex:crag
	Result Path: ex:USES
	Message: USES 의 대상은 Dataset 이어야 한다(range 위반)

[assert] pyshacl 이 range 위반을 잡았다
```

미설치 상태로 실행하면 안내만 출력하고 조용히 끝난다:

```
pyshacl 미설치. 이 파일은 참고용이다.
설치: pip install "pyshacl>=0.26" "rdflib>=7.0"
메인 경량 엔진은 rule_engine.py 를 실행하라.
```

경량 엔진의 `RelationShape(subject_class/object_class)` 가 표준 SHACL 의 `sh:NodeShape + sh:property + sh:path + sh:class` 에 그대로 대응한다. 용어를 맞춰 뒀으니 나중에 표준 SHACL 로 옮기기 쉽다.

---

## 완료 체크

- [ ] 3단계에서 정상 트리플 `self-rag-USES->popqa` 는 PASS(출력에 안 나옴).
- [ ] `popqa-USES->self-rag` 가 `UsesShape` domain/range 위반으로 REJECT 되고 `suggested_fix` 가 붙는다.
- [ ] `no-canon` 노드가 canonical_id 누락으로 REJECT 된다.
- [ ] 카디널리티 위반이 `warning` 으로 집계되되 적재를 막지는 않는다.
- [ ] `report.summary()` 가 rule 별 위반 집계를 낸다.
- [ ] 네 스크립트 모두 마지막에 `[assert] 모든 자체검증 통과` 를 출력한다.
