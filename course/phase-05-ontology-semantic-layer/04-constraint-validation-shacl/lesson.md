# 5.4 Constraint Validation (Pydantic + SHACL-inspired Rule + Reject Reason)

> **Phase 5 · 토픽 04** · 03 까지 만든 canonical id·통제 어휘 위에, 그래프 적재 직전 노드·트리플을 검증하는 제약 엔진을 만든다. 정상은 PASS, 위반은 `rule_id`·`suggested_fix` 가 담긴 reject reason 으로 거른다.

## 학습 목표

이 토픽을 끝내면 다음을 할 수 있다.

- 그래프 제약을 SHACL 용어(NodeShape·PropertyShape·targetClass·minCount·class·in)에 맞춰 `shapes.yaml` 데이터 파일로 선언한다.
- Pydantic 으로 노드 레코드 스키마(타입·필수·형식·enum)를 인입 단계에서 검증하고, 위반을 구조화 reject reason 으로 남긴다.
- 경량 SHACL-inspired rule engine 으로 domain/range·미등록 관계·dangling 참조·카디널리티를 그래프 전역에서 검증한다.
- `(:Dataset)-[:USES]->(:Method)` 를 domain/range 위반으로 REJECT 하고, rule 별 위반 집계 리포트를 출력한다.

**완료 기준**: `shapes.yaml` 을 로드해 `(:Dataset)-[:USES]->(:Method)` 를 domain/range 위반으로 REJECT 하고 `rule_id`·`suggested_fix` 가 담긴 reject reason 을 출력하며, 정상 트리플은 PASS, 위반 집계 리포트가 나오면 완료.

---

## 1. 왜 필요한가 — 표기를 통제했다고 그래프가 옳은 건 아니다

02·03 을 지나며 어휘를 통제하고 canonical id 를 붙였다. `Self-RAG`·`SELF-RAG` 는 concept_id `self-rag` 로 접히고 `urn:kb:concept:self-rag` 라는 불변 ID 를 갖는다. 표기·식별 문제는 끝났다.

그런데 이런 트리플이 추출기에서 나온다.

```
(:Dataset {popqa})-[:USES]->(:Method {self-rag})
```

라벨도 등록돼 있고 관계 타입도 카탈로그 안이다. 구조만 보면 멀쩡하다. 그런데 의미가 틀렸다. `USES` 는 "Method 가 Dataset 을 쓴다"는 관계다. 여기선 Dataset 이 Method 를 쓴다고 말한다. 방향이 뒤집혔다. 01 에서 "구조는 정의하지만 의미는 통제 못한다"고 짚었던 바로 그 지점이다. 이 토픽이 그 실행판이다.

이런 게 그래프에 들어가면 GraphRAG 검색이 오염된다. "Self-RAG 가 어떤 데이터셋을 쓰나"를 물었을 때 엉뚱한 경로를 탄다. 그래서 **적재 직전에** 노드·트리플을 검증해 위반을 거른다. 걸린 것은 이유(reason)를 붙여 reject queue 로 보낸다. Phase 2 품질 게이트가 텍스트→추출 단계에서 하던 일을, 여기서는 그래프 스키마·공리 수준으로 끌어올린다.

## 2. SHACL — 그래프에 "지켜야 할 모양"을 선언한다

SHACL(Shapes Constraint Language)은 W3C 표준이다. 그래프가 지켜야 할 제약을 **Shape** 로 선언한다. 두 종류만 알면 된다.

- **NodeShape** — 특정 타입 노드가 지켜야 할 제약. "모든 Method 노드는 canonical_id 를 가져야 한다" 같은 것. `sh:targetClass` 로 대상 타입을 고르고, `sh:property` 로 속성 제약을 건다.
- **PropertyShape** — 속성 하나의 제약. `sh:minCount`(최소 개수), `sh:maxCount`, `sh:datatype`(타입), `sh:class`(참조 노드의 타입), `sh:in`(허용값 폐쇄 집합), `sh:pattern`(정규식).

domain/range 는 이걸로 표현한다. "USES 로 나가는 엣지의 대상(range)은 Dataset 이어야 한다"는 Method NodeShape 의 `sh:property [ sh:path USES; sh:class Dataset ]` 이다.

문제는 SHACL 이 RDF 위에서 돌게 설계됐다는 점이다. 우리 그래프는 LPG(Neo4j)다. 표준 pyshacl 을 쓰려면 그래프를 RDF 트리플로 변환해야 하고, 설치도 무겁다. 그래서 이 토픽은 **SHACL 의 핵심 구조를 경량 엔진으로 직접 구현**한다. 나중에 표준 SHACL 로 옮기기 쉽도록 `shapes.yaml` 의 키를 SHACL 용어에 1:1 대응하게 이름을 맞춰 뒀다. pyshacl 실제 사용법은 이 토픽 끝의 참고 박스와 `practice/pyshacl_reference.py` 에 짧게 둔다.

## 3. 두 트랙 — Pydantic 은 레코드, SHACL 은 그래프

검증을 어디서 하느냐로 두 트랙을 나눈다. 헷갈리기 쉬우니 역할을 먼저 못박는다.

| | Pydantic 트랙 | SHACL-inspired 트랙 |
|---|---|---|
| 보는 단위 | 레코드 **하나**(노드·트리플 1건) | 그래프 **전역**(노드·엣지 관계) |
| 잡는 것 | 타입·필수 필드·값 형식·enum·canonical 형식 | domain/range·카디널리티·미등록 관계·dangling |
| 언제 | 추출 파이프라인 인입 단계 | 적재 직전 배치 검증 |
| 대응 | JSON 스키마 검증 | SHACL Shape 검증 |

Pydantic 은 `no-canon`(canonical_id 빈 값)이나 `Framework`(카탈로그 밖 label)처럼 **레코드 하나만 봐도 알 수 있는** 오류를 막는다. 하지만 방향이 뒤집힌 `USES` 는 두 노드의 라벨을 함께 봐야 안다. Pydantic 은 옆 노드를 모른다. 그건 SHACL 트랙의 몫이다. 둘은 경쟁이 아니라 분업이다.

### 3-1. Pydantic 트랙 — 레코드 스키마

노드 하나를 Pydantic 모델로 검증한다. canonical_id 는 필수이고 `urn:kb:concept:` 형식이어야 한다. label 은 entity_types 카탈로그의 폐쇄 집합 안에 있어야 한다.

```python
# practice/pydantic_models.py 의 핵심
class NodeRecord(BaseModel):
    node_id: str
    label: str
    canonical_id: str
    concept_id: str

    @field_validator("canonical_id")
    @classmethod
    def _canonical_format(cls, v: str) -> str:
        if not v:
            raise ValueError("canonical_id 누락: 표준 ID 없이 그래프에 넣을 수 없다")
        if not v.startswith("urn:kb:concept:"):
            raise ValueError(f"canonical_id 형식 위반(urn:kb:concept: 접두어): {v!r}")
        return v

    @field_validator("label")
    @classmethod
    def _label_in_catalog(cls, v: str) -> str:
        if _ALLOWED_LABELS and v not in _ALLOWED_LABELS:
            raise ValueError(f"label {v!r} 은 entity_types 카탈로그 밖")
        return v
```

Pydantic 이 던진 `ValidationError` 를 우리 리포트 포맷(`RejectReason`)으로 옮긴다. 두 트랙이 같은 포맷을 써야 뒤 단계(reject queue·집계·05 답변 게이트)가 하나로 다룬다.

### 3-2. SHACL-inspired 트랙 — shapes.yaml

그래프 제약을 코드가 아니라 데이터 파일로 뺀다. 어휘를 YAML 로 뺀 것과 같은 이유다. 도메인 전문가가 규칙을 읽고 고칠 수 있어야 한다.

```yaml
# practice/shapes.yaml — RelationShape 한 조각 (domain=subject_class, range=object_class)
relation_shapes:
  - id: UsesShape
    target_relation: USES
    subject_class: Method     # domain
    object_class: Dataset     # range
    severity: violation
    message: "USES 는 (:Method)-[:USES]->(:Dataset) 여야 한다"
    suggested_fix: "주어/목적어 타입을 확인하라. 방향이 뒤집혔으면 subject/object 를 바꿔라"
```

`subject_class`/`object_class` 가 SHACL 의 domain/range 공리다. 01 의 `check_triple` 이 파이썬 딕셔너리에 박아 뒀던 공리를, 이제 데이터 파일로 승격했다. 카디널리티도 같은 방식으로 선언한다.

```yaml
# "모든 Method 노드는 최소 1개 Dataset 에서 EVALUATED_ON 관계를 가져야 한다"
cardinality_shapes:
  - id: MethodMustBeEvaluatedShape
    target_class: Method
    relation: EVALUATED_ON
    min_count: 1
    severity: warning      # 데이터가 깨진 게 아니라 덜 채워진 것일 수 있다 → 경고
```

`severity` 가 핵심이다. domain/range 위반은 데이터가 틀린 거라 `violation`(적재 거부)이다. 카디널리티 부족은 아직 추출이 덜 됐을 수도 있어 `warning`(적재는 하되 리포트에 남김)이다. 무엇을 막고 무엇을 흘려보낼지를 규칙마다 정한다.

### 3-3. rule engine — shapes + 그래프 → 위반 리포트

엔진은 `shapes.yaml` 과 그래프(nodes/triples)를 받아 위반을 뱉는다. domain/range 검사의 핵심은 이렇다.

```python
# practice/rule_engine.py — RelationShape 검사(미등록 관계 · dangling · domain/range)
for t in triples:
    subj, rel, obj = t["subject"], t["rel"], t["object"]
    # 1) dangling — 참조 노드가 그래프에 없다
    if subj not in by_id or obj not in by_id: ...      # DanglingReferenceShape
    # 2) 미등록 관계 — relation_types 카탈로그 밖
    if rel not in self.allowed_relations: ...          # UnknownRelationShape
    # 3) domain/range — subject/object 라벨이 Shape 와 다르다
    shape = rel_index.get(rel)
    if by_id[subj]["label"] != shape["subject_class"] \
       or by_id[obj]["label"] != shape["object_class"]:
        # UsesShape 등 domain/range 위반 → RejectReason
```

검사 순서가 의미가 있다. dangling 이면 노드가 없어 domain/range 를 볼 수 없으니 먼저 걸러낸다. 미등록 관계면 Shape 자체가 없으니 그다음이다. 둘 다 통과해야 domain/range 를 본다.

## 4. Reject Reason — 위반을 구조화해 남긴다

위반을 "틀렸다"로 끝내면 못 고친다. 무엇이·왜·어떻게 고치나를 함께 남긴다. 두 트랙이 공유하는 단일 포맷이다.

```python
# practice/reject_reason.py
class RejectReason(BaseModel):
    rule_id: str                       # 어떤 규칙이 걸었나(Shape id 또는 Pydantic 필드)
    severity: Literal["violation", "warning"] = "violation"
    target_kind: Literal["node", "triple"]
    target: str                        # 노드 id 또는 "subject-REL->object"
    message: str                       # 사람이 읽을 설명
    suggested_fix: str | None = None   # 어떻게 고치나
```

`ValidationReport` 가 이 위반들을 모아 rule 별로 집계하고, `passed`(violation 이 0건이면 True)로 적재 가능 여부를 판정한다. warning 은 통과를 막지 않는다. 이 리포트가 그대로 reject queue 로 흘러가고, 05 의 답변 시점 정책 체크가 같은 엔진을 답변 게이트로 재사용한다.

> 전체 코드와 실행 절차는 [`practice/`](practice/) 와 [`labs/`](labs/) 참조. 네 스크립트(`reject_reason`·`pydantic_models`·`rule_engine`·`pyshacl_reference`) 모두 마지막에 `assert` 로 완료 기준을 못박는다. API 키·Neo4j 불필요, 전부 로컬에서 돈다.

## 5. 결과 해석

`python rule_engine.py` 를 돌리면 이렇게 나온다(발췌).

```
[REJECT ] UsesShape          popqa-USES->self-rag  ... — 실제 (:Dataset)-[:USES]->(:Method)  fix: ...
[REJECT ] ReportsShape       paper-2310-REPORTS->popqa ... — 실제 (:Paper)-[:REPORTS]->(:Dataset)
[REJECT ] UnknownRelationShape self-rag-MENTIONS->popqa  관계 타입 'MENTIONS' 은 카탈로그 밖
[REJECT ] DanglingReferenceShape self-rag-USES->ghost   참조 노드 없음(dangling): ['ghost']
[WARN   ] MethodMustBeEvaluatedShape crag  ... 현재 0개(<1)

== 집계 ==
위반 7건, 경고 3건
  rule 별 집계:
    MethodMustBeEvaluatedShape 3건
    NodeCommonShape            2건
    UsesShape                  2건
    ...
적재 가능 여부(passed): False
```

정상 트리플 `self-rag-USES->popqa` 는 어떤 줄에도 안 나온다. PASS 다. 방향이 뒤집힌 `popqa-USES->self-rag` 는 `UsesShape` 로 걸리고, 메시지에 "실제 `(:Dataset)-[:USES]->(:Method)`"까지 찍혀 무엇이 틀렸는지 바로 안다.

`passed: False` 가 결론이다. violation 이 7건이라 이 배치는 그대로 적재하면 안 된다. 위반을 고치거나 reject queue 로 보낸 뒤 다시 검증한다. 경고 3건은 적재를 막지 않지만 리포트에 남아 "나중에 채워야 할 빈틈"을 알려 준다. rule 별 집계는 어떤 규칙에서 가장 많이 걸리는지 보여줘 데이터 품질의 약한 고리를 짚는다.

---

## 🚨 자주 하는 실수

1. **Pydantic 하나로 domain/range 까지 잡으려 한다.** Pydantic 은 레코드 한 개만 본다. `(:Dataset)-[:USES]->(:Method)` 방향 뒤집힘은 두 노드의 라벨을 함께 봐야 알 수 있어 Pydantic 이 못 잡는다. 그래프 전역 제약은 SHACL 트랙(rule engine)에 맡겨라. Pydantic 은 타입·필수·형식·enum 까지가 경계다.
2. **모든 위반을 violation 으로 막는다.** 카디널리티 부족("Method 인데 평가 데이터셋이 없다")까지 적재 거부로 처리하면, 아직 추출이 덜 된 정상 노드가 통째로 튕긴다. 데이터가 **틀린** 것(domain/range·미등록 관계)은 `violation`, 아직 **덜 채워진** 것(카디널리티)은 `warning` 으로 나눠라. severity 설계가 게이트의 핵심이다.
3. **reject reason 에 message 만 넣고 rule_id·suggested_fix 를 뺀다.** "USES 위반"만 남기면 어떤 규칙이 걸었는지, 어떻게 고치는지 알 수 없어 reject queue 가 쌓이기만 한다. `rule_id`(추적)·`target`(무엇이)·`suggested_fix`(어떻게)를 반드시 함께 남겨라. 그래야 위반→수정→재검증 루프가 돈다.
4. **경량 엔진을 버리고 처음부터 pyshacl 로 간다.** pyshacl 은 강력하지만 LPG 그래프를 RDF 로 변환해야 하고 설치가 무겁다. 학습·프로토타이핑 단계에서는 경량 엔진이 훨씬 투명하다(shapes.yaml 키가 SHACL 용어에 그대로 대응). RDF/트리플 스토어를 실제로 쓰는 팀이 됐을 때 표준 SHACL 로 옮기면 된다. `practice/pyshacl_reference.py` 로 그 형태만 미리 봐 둔다.

## 출처

- W3C SHACL 명세(Shapes Constraint Language: NodeShape·PropertyShape·sh:targetClass·sh:minCount·sh:class·sh:in) — https://www.w3.org/TR/shacl/
- pySHACL — https://github.com/RDFLib/pySHACL
- Pydantic(구조적 출력·검증) — https://docs.pydantic.dev/
- W3C SKOS Reference — https://www.w3.org/TR/skos-reference/
- *When Large Language Models Meet Knowledge Graphs for Question Answering: A Survey*, arXiv 2505.20099 — https://arxiv.org/abs/2505.20099

## 다음 토픽

→ [05-answer-time-policy-check — Answer-time Semantic · Access · Policy Check](../05-answer-time-policy-check/lesson.md)

