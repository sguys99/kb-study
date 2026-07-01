# 5.1 Taxonomy · Vocabulary · Ontology — Graph Schema와 무엇이 다른가

> **Phase 5 · 토픽 01** · Phase 2에서 만든 Graph Schema로 그래프를 키워 왔다. 증분 적재로 규모가 커지자 용어가 흔들리고 관계가 뒤집힌다. 스키마만으로 왜 부족한지, 그리고 Taxonomy·Controlled Vocabulary·Ontology라는 의미 계층(Semantic Layer)이 각각 무엇을 통제하는지 코드로 대비한다.

## 학습 목표

이 토픽을 끝내면 다음을 할 수 있다.

- Taxonomy·Controlled Vocabulary·Ontology·Graph Schema 네 가지가 각각 **무엇을 통제하는지** 하나의 비교표로 구분한다.
- 코퍼스 도메인(AI/LLM 기술 문서)으로 mini taxonomy를 만들어 `self-rag`의 상위 개념 경로를 질의한다.
- 통제 어휘로 `resolve("Self-Reflective RAG")`가 표준 concept_id `self-rag`를 돌려주게 만들고, 어휘에 없는 용어는 REJECT 시킨다.
- 온톨로지의 domain/range 공리로 `(:Dataset)-[:USES]->(:Method)` 같은 트리플을 REJECT하고, 같은 트리플이 Graph Schema만으로는 통과하는 것을 대비 출력한다.

**완료 기준**: `controlled_vocabulary.resolve("Self-Reflective RAG")`가 표준 concept_id `self-rag`를 반환하고, `ontology.check_triple`이 `(:Dataset)-[:USES]->(:Method)`를 domain/range 위반으로 REJECT하며, `schema_vs_semantic`이 같은 트리플을 Graph Schema에서는 PASS·의미 계층에서는 REJECT로 갈라 출력하면 완료.

---

## 1. 왜 필요한가 — 스키마는 구조만 잡는다

Phase 2에서 텍스트를 그래프 스키마로 옮겼다. 엔티티 타입으로 Concept·Method·Dataset·Metric·Paper를 뽑고, 관계로 USES·EVALUATED_ON·COMPARES·PART_OF를 정했다. Phase 3에서 Neo4j에 라벨·관계 타입으로 적재하고, Phase 4에서 LightRAG로 5모드(`naive/local/global/hybrid/mix`) 검색까지 붙였다.

문제는 그래프가 멈춰 있지 않다는 데 있다. 코퍼스는 증분으로 자란다. 논문이 새로 들어오고, 추출기가 매번 조금씩 다른 표기를 뱉는다. 그렇게 몇 번 돌리고 나면 그래프가 이렇게 어긋난다.

- 같은 기법이 세 이름으로 흩어진다. 어떤 문서는 "Self-RAG", 어떤 곳은 "Self-Reflective RAG", 또 어떤 곳은 "SELF-RAG". 셋 다 노드가 따로 생긴다.
- 관계 타입이 난립한다. USES 하나면 될 것이 USE·USING으로 갈라진다.
- Concept과 Method의 경계가 흐려진다. 같은 대상이 어떤 문서에선 Concept, 어떤 문서에선 Method로 들어온다.

Phase 0에서 봤던 RAG 실패의 연장선이다. 그때는 검색이 근거를 놓쳤다면, 지금은 그래프 자체가 같은 개념을 여러 조각으로 쪼개 멀티홉을 끊어 놓는다. "Self-RAG를 쓰는 논문"을 물어도 세 노드로 나뉜 탓에 답이 절반만 나온다.

여기서 짚을 게 있다. Phase 2의 Graph Schema는 이걸 못 막는다. 스키마는 "Method라는 라벨이 있다", "USES라는 관계 타입이 있다"까지만 안다. 그 Method 노드의 이름이 표준인지, USES의 주어가 Method가 맞는지는 스키마의 관심 밖이다. **구조는 정의하지만 의미는 통제하지 않는다.** 그래서 의미 계층이 필요하다.

## 2. 네 가지를 한 표로 구분한다

의미 계층은 한 덩어리가 아니라 세 축으로 나뉜다. 여기에 Phase 2 Graph Schema를 나란히 두면 각자 무엇을 담당하는지 선명해진다.

| | 무엇을 통제하나 | 표현 형식 | 이 코퍼스 예시 | 한계 |
|---|---|---|---|---|
| **Graph Schema** (Phase 2, LPG) | 구조: 어떤 라벨·관계 타입·속성이 있는가 | Neo4j 라벨·관계 타입, Pydantic 모델 | `:Method`, `:Dataset`, `[:USES]` 등록 | 의미·표기·계층·공리는 강제 못 함 |
| **Taxonomy** (분류체계) | 계층: 무엇이 무엇의 상위/하위인가 | is-a, broader/narrower (SKOS) | self-rag → retrieval-method → method | 계층만. 표기·관계 공리는 모름 |
| **Controlled Vocabulary** (통제 어휘) | 어휘: 어떤 표기가 표준이고 무엇이 동의어인가 | preferred_label + alt_labels + concept_id | "Self-RAG"(표준), "Self-Reflective RAG"(alias) | 계층·관계 공리는 없음 |
| **Ontology** (온톨로지) | 의미·논리: 관계의 domain/range, 공리 | 클래스 + 속성 + domain/range (RDFS/OWL) | USES의 domain=Method, range=Dataset | 표현력이 큰 만큼 설계·검증 비용 |

넷의 관계는 이렇게 정리된다. Taxonomy는 통제 어휘가 담는 개념들 사이에 계층을 얹은 것에 가깝다(Taxonomy ⊂ Vocabulary 관점). Ontology는 이 둘을 포함하면서 관계의 의미 규칙까지 확장한다. 클래스와 계층(Taxonomy), 표준 표기(Vocabulary)를 흡수하고, 거기에 "USES는 Method가 주어여야 한다" 같은 공리를 더한다.

가장 흔한 오해가 바로 여기서 생긴다. **계층이 있으면 온톨로지라고 착각**하는 것이다. broader/narrower만 있으면 Taxonomy일 뿐이다. domain/range 같은 관계 공리가 있어야 온톨로지다. 반대로 **Graph Schema와 Ontology를 같은 것으로 취급**하는 착각도 잦다. Neo4j 라벨을 맞췄다고 의미가 맞는 건 아니다. 이 토픽의 4번 실습이 정확히 이 지점을 코드로 갈라 보여준다.

## 3. 실습 A — Taxonomy: 상위 개념 경로

먼저 계층부터. concept_id를 바로 위 개념(broader)에 매핑한 dict 하나면 mini taxonomy가 된다. `self-rag`에서 루트까지 올라가는 경로를 뽑아 본다.

```python
# practice/taxonomy.py 의 핵심 부분
BROADER: dict[str, str] = {
    "method": "concept",
    "retrieval-method": "method",
    "self-rag": "retrieval-method",   # self-rag 의 바로 위
    "crag": "retrieval-method",
    # ...
}

def broader_path(concept_id: str) -> list[str]:
    """루트까지 올라가는 상위 개념 경로. self-rag -> retrieval-method -> method -> concept"""
    path = [concept_id]
    current = concept_id
    while current in BROADER:      # 부모가 있는 동안 계속 올라간다
        current = BROADER[current]
        path.append(current)
    return path
```

`broader_path("self-rag")`는 `["self-rag", "retrieval-method", "method", "concept"]`를 돌려준다. rdflib가 있으면 같은 계층을 `skos:broader` 트리플로도 볼 수 있지만 선택이다. 계층은 이게 전부다. 표기가 표준인지, 관계가 올바른지는 아직 아무것도 모른다.

## 4. 실습 B — Controlled Vocabulary: alias를 표준으로

이제 표기 흔들림을 잡는다. 통제 어휘는 표준 표기 하나(`preferred_label`)와 동의어 목록(`alt_labels`), 그리고 표준 식별자(`concept_id`)로 한 항목을 만든다. Pydantic v2로 항목을 고정하고, 자유 표기를 concept_id로 접는 `resolve`를 둔다.

```python
# practice/controlled_vocabulary.py 의 핵심 부분
class ConceptEntry(BaseModel):
    concept_id: str          # 표준 식별자(Canonical ID) 씨앗. 소문자-하이픈.
    preferred_label: str     # 표준 표기(딱 하나)
    alt_labels: list[str] = []

def _normalize(term: str) -> str:
    # 대소문자·하이픈·연속 공백 차이를 흡수하는 비교 키
    return " ".join(term.replace("-", " ").split()).lower()

def resolve(term: str) -> ResolveResult:
    hit = _INDEX.get(_normalize(term))       # 표준·동의어 모두 색인돼 있음
    if hit is None:
        return ResolveResult(input_term=term, resolved=False,
                             reason="NOT_IN_VOCABULARY: 통제 어휘에 없는 용어")
    entry, matched_on = hit
    return ResolveResult(input_term=term, resolved=True,
                         concept_id=entry.concept_id, matched_on=matched_on)
```

`resolve("Self-Reflective RAG")`, `resolve("SELF-RAG")`, `resolve("self rag")`는 전부 `self-rag`를 돌려준다. 정규화 키가 대소문자·하이픈·공백 차이를 흡수하기 때문이다. 어휘에 없는 `FancyRAG`는 통과시키지 않고 REJECT한다. 통과냐 거부냐를 가르는 이 문턱이 "통제"의 본질이다. LLM이 추출한 라벨을 그대로 믿으면 동의어가 무한히 늘지만, 통제 어휘를 거치면 하나로 접힌다.

## 5. 실습 C — Ontology: domain/range 공리

마지막으로 관계의 의미. 온톨로지는 클래스에 더해 "관계가 어떤 타입 사이에서만 성립하는가"를 공리로 담는다. USES는 domain이 Method, range가 Dataset이다. 이 규칙으로 트리플을 검사한다.

```python
# practice/ontology.py 의 핵심 부분
RELATIONS: dict[str, RelationDef] = {
    "USES":    RelationDef(name="USES",    domain="Method", range="Dataset"),
    "REPORTS": RelationDef(name="REPORTS", domain="Paper",  range="Metric"),
    # ...
}

def check_triple(t: Triple) -> list[Violation]:
    rel_def = RELATIONS.get(t.rel)
    if rel_def is None:
        return [Violation(triple=str(t), code="UNKNOWN_RELATION", reason=...)]
    v = []
    if t.subject_label != rel_def.domain:   # 주어 타입 위반
        v.append(Violation(triple=str(t), code="DOMAIN_MISMATCH", reason=...))
    if t.object_label != rel_def.range:     # 목적어 타입 위반
        v.append(Violation(triple=str(t), code="RANGE_MISMATCH", reason=...))
    return v
```

`(:Method)-[:USES]->(:Dataset)`는 통과한다. 방향이 뒤집힌 `(:Dataset)-[:USES]->(:Method)`는 domain·range 양쪽이 걸려 REJECT된다. 여기서 하는 건 domain/range 수준의 가벼운 검사까지다. 카디널리티·필수 속성·경로 제약 같은 본격 제약 검증은 SHACL로 5/04에서 다룬다. 이 토픽에서 SHACL을 다 구현하려 들면 개념 구분이라는 본래 목적을 놓친다.

> 전체 코드와 실행 절차는 [`practice/`](practice/)와 [`labs/`](labs/) 참조.
> 이 토픽은 개념형이라 LLM·임베딩 호출이 없다. API 키 없이 로컬에서 전부 돈다. rdflib는 SKOS/RDFS 표준 표현을 보고 싶을 때만 선택으로 깐다.

## 6. 결과 해석 — 구조는 통과, 의미는 틀림

네 개를 나란히 세우는 `schema_vs_semantic.py`가 이 토픽의 결론이다. Graph Schema는 라벨과 관계 타입이 등록돼 있기만 하면 PASS를 준다. 같은 트리플을 의미 계층에 넣으면 결과가 갈린다.

```
== Graph Schema vs 의미 계층(온톨로지) 대비 ==
트리플                                          Schema   Semantic
----------------------------------------------------------------
(:Method)-[:USES]->(:Dataset)                  PASS       PASS
(:Dataset)-[:USES]->(:Method)                  PASS     REJECT
    └─ Schema는 통과, 의미 계층이 잡음: [DOMAIN_MISMATCH] USES 의 domain 은 Method 인데 주어가 Dataset
(:Paper)-[:REPORTS]->(:Dataset)                PASS     REJECT
    └─ Schema는 통과, 의미 계층이 잡음: [RANGE_MISMATCH] REPORTS 의 range 는 Metric 인데 목적어가 Dataset
```

`(:Dataset)-[:USES]->(:Method)`는 라벨(:Dataset, :Method)도 관계 타입(USES)도 다 등록돼 있다. 그래서 Graph Schema에선 PASS다. 방향이 뒤집힌 건 의미 계층에서만 잡힌다. 어휘 축도 마찬가지다. 노드 라벨이 :Method로 정상이면 Schema는 그 노드 이름이 "Self-RAG"든 "SELF-RAG"든 "FancyRAG"든 신경 쓰지 않는다. 표기를 하나로 접고 미등록 용어를 거르는 건 통제 어휘의 몫이다.

읽는 법은 간단하다. Schema=PASS인데 Semantic=REJECT인 줄이 하나라도 있으면, "Neo4j 라벨만 맞추면 된다"는 생각이 틀렸다는 증거다. 이 대비가 Phase 5 나머지 토픽의 출발점이다. 여기서 만든 mini taxonomy·vocabulary·ontology를 02에서 제대로 설계하고, 03에서 표준 식별자로 정렬하며, 04에서 SHACL로 검증하고, 05에서 답변 시점 게이트로 건다.

---

## 🚨 자주 하는 실수

1. **계층만 있으면 온톨로지라고 착각한다.** broader/narrower로 상위-하위를 줄 세운 건 Taxonomy다. 온톨로지는 거기에 관계의 domain/range 같은 의미 공리가 있어야 한다. "self-rag는 method의 하위"까지가 Taxonomy, "USES는 Method가 주어여야 한다"가 Ontology다. 이 둘을 뭉뚱그리면 실제로 잘못된 트리플을 잡지 못한다.
2. **통제 어휘 없이 LLM 추출 라벨을 그대로 믿는다.** 추출기는 매번 조금씩 다른 표기를 뱉는다. 통제 어휘 없이 그걸 노드 이름으로 쓰면 "Self-RAG"·"Self-Reflective RAG"·"SELF-RAG"가 각각 노드가 되어 멀티홉이 끊긴다. `resolve`로 표준 concept_id에 접고, 어휘에 없는 용어는 통과가 아니라 REJECT로 다뤄야 한다.
3. **Graph Schema(구조)와 Ontology(의미)를 같은 것으로 본다.** Neo4j 라벨·관계 타입을 맞췄다고 의미까지 맞는 건 아니다. `(:Dataset)-[:USES]->(:Method)`는 스키마를 통과하지만 의미는 틀렸다. 라벨만 검사하는 파이프라인은 이런 트리플을 그대로 적재한다.
4. **이 토픽에서 SHACL을 다 구현하려 한다.** 여기서는 세 계층을 구분하고 domain/range 수준까지만 본다. 카디널리티·필수 속성·경로 제약을 붙인 본격 제약 검증은 5/04(constraint-validation-shacl)의 몫이다. 개념 구분 토픽에서 검증 프레임워크까지 끌고 오면 초점이 흐려진다.

## 출처

- W3C SHACL 명세 — https://www.w3.org/TR/shacl/ · pySHACL — https://github.com/RDFLib/pySHACL
- Pydantic — https://docs.pydantic.dev/
- W3C SKOS Reference — https://www.w3.org/TR/skos-reference/ · RDF Schema (RDFS) — https://www.w3.org/TR/rdf-schema/
- rdflib — https://rdflib.readthedocs.io/
- *When Large Language Models Meet Knowledge Graphs for Question Answering: A Survey*, arXiv 2505.20099 — https://arxiv.org/abs/2505.20099
- *Graph Retrieval-Augmented Generation: A Survey*, arXiv 2408.08921 — https://arxiv.org/abs/2408.08921

## 다음 토픽

→ [02-controlled-vocabulary — Entity·Relation Type + Controlled Vocabulary 설계](../02-controlled-vocabulary/lesson.md)
