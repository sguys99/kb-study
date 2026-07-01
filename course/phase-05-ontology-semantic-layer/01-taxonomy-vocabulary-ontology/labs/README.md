# 5.1 Labs — Taxonomy·Vocabulary·Ontology 핸즈온

세 개의 의미 계층을 각각 만들어 보고, 마지막에 Phase 2 Graph Schema 와 나란히 세워 "구조는 통과하지만 의미는 틀린" 사례를 대비 출력한다.

이 토픽은 개념형이다. **API 키·Neo4j·인터넷 없이** 전부 로컬에서 돈다. 필수 의존은 Pydantic v2 하나뿐. rdflib(SKOS/RDFS 표준 표현 보기)는 선택이다.

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
Successfully installed pydantic-2.x ...   (이미 있으면 "already satisfied")
```

rdflib 는 기본 주석 처리돼 있어 깔리지 않는다. 표준 트리플(SKOS/RDFS)을 보고 싶으면 `requirements.txt` 의 `rdflib` 줄 주석을 풀고 다시 설치한다. 안 깔아도 모든 실습은 순수 파이썬 경로로 그대로 돈다.

---

## 1단계 — Taxonomy: 상위 개념 경로 질의

`self-rag` 가 어떤 상위 개념들에 속하는지 broader/narrower 로 확인한다.

```bash
python taxonomy.py
```

**예상 출력**

```
== broader path (self-rag 의 상위 경로) ==
Self-RAG -> Retrieval Method -> Method -> Concept

== narrower (retrieval-method 의 직속 하위) ==
  - CRAG  (crag)
  - GraphRAG  (graphrag)
  - Hybrid RAG  (hybrid-rag)
  - Self-RAG  (self-rag)

== is-a 판정 ==
  is_a('self-rag', 'method') = True
  is_a('self-rag', 'dataset') = False
  is_a('popqa', 'dataset') = True

== SKOS 트리플(rdflib, 선택) ==
  rdflib 미설치 — 순수 파이썬 경로만 사용(정상). 보려면 requirements.txt 의 rdflib 주석을 푼다.
```

`self-rag` 에서 루트 `concept` 까지 계층이 한 줄로 이어진다. `is_a` 는 이 경로 안에 상위가 있는지로 판정한다. rdflib 를 깔았다면 마지막 블록에서 `ex:self-rag skos:broader ...` 트리플과 총 트리플 수가 대신 찍힌다.

---

## 2단계 — Controlled Vocabulary: alias 정규화

표기가 흔들리는 용어들을 하나의 표준 concept_id 로 접는다. 어휘에 없는 용어는 REJECT.

```bash
python controlled_vocabulary.py
```

**예상 출력**

```
== controlled vocabulary resolve ==
  OK     'Self-RAG'                 -> self-rag     (Self-RAG, matched=preferred)
  OK     'Self-Reflective RAG'      -> self-rag     (Self-RAG, matched=alt)
  OK     'SELF-RAG'                 -> self-rag     (Self-RAG, matched=preferred)
  OK     'self rag'                 -> self-rag     (Self-RAG, matched=preferred)
  OK     'Corrective RAG'           -> crag         (CRAG, matched=alt)
  OK     '그래프RAG'                   -> graphrag     (GraphRAG, matched=alt)
  REJECT 'FancyRAG'                 -> NOT_IN_VOCABULARY: 통제 어휘에 없는 용어(신규 후보로 검토 필요)
```

`Self-RAG`·`SELF-RAG`·`Self-Reflective RAG`·`self rag` 가 전부 `self-rag` 로 접힌다. 대소문자·하이픈·공백 차이는 정규화 키가 흡수한다. `matched` 는 표준 표기에 붙었는지(preferred) 동의어에 붙었는지(alt)를 알려 준다. 어휘에 없는 `FancyRAG` 는 통과하지 못하고 REJECT 된다 — 이게 "통제(controlled)"다.

---

## 3단계 — Ontology: domain/range 위반 검출

관계의 주어·목적어 타입 공리(domain/range)로 트리플을 검사한다.

```bash
python ontology.py
```

**예상 출력**

```
== ontology domain/range check ==
  OK     (:Method)-[:USES]->(:Dataset)
  REJECT (:Dataset)-[:USES]->(:Method)  [DOMAIN_MISMATCH] USES 의 domain 은 Method 인데 주어가 Dataset
  REJECT (:Dataset)-[:USES]->(:Method)  [RANGE_MISMATCH] USES 의 range 는 Dataset 인데 목적어가 Method
  OK     (:Method)-[:COMPARES]->(:Method)
  REJECT (:Paper)-[:REPORTS]->(:Dataset)  [RANGE_MISMATCH] REPORTS 의 range 는 Metric 인데 목적어가 Dataset
  REJECT (:Method)-[:INVENTED_BY]->(:Paper)  [UNKNOWN_RELATION] 온톨로지에 없는 관계: 'INVENTED_BY'
  REJECT (:Robot)-[:USES]->(:Dataset)  [UNKNOWN_CLASS] 온톨로지에 없는 클래스: 'Robot'
  REJECT (:Robot)-[:USES]->(:Dataset)  [DOMAIN_MISMATCH] USES 의 domain 은 Method 인데 주어가 Robot
```

`(:Dataset)-[:USES]->(:Method)` 는 방향이 뒤집혀 domain·range 양쪽이 걸린다. `REPORTS` 는 목적어가 Metric 이어야 하는데 Dataset 이라 range 위반이다. 여기까지가 온톨로지가 하는 일. 카디널리티나 필수 속성 같은 더 무거운 제약은 SHACL(5/04)에서 다룬다.

---

## 4단계 — Schema vs 의미 계층: 대비 출력

같은 트리플을 Graph Schema(구조)와 의미 계층(온톨로지·어휘)에 각각 통과시켜 차이를 본다.

```bash
python schema_vs_semantic.py
```

**예상 출력**

```
== Graph Schema vs 의미 계층(온톨로지) 대비 ==
트리플                                          Schema   Semantic
----------------------------------------------------------------
(:Method)-[:USES]->(:Dataset)                  PASS       PASS
(:Dataset)-[:USES]->(:Method)                  PASS     REJECT
    └─ Schema는 통과, 의미 계층이 잡음: [DOMAIN_MISMATCH] USES 의 domain 은 Method 인데 주어가 Dataset
    └─ Schema는 통과, 의미 계층이 잡음: [RANGE_MISMATCH] USES 의 range 는 Dataset 인데 목적어가 Method
(:Paper)-[:REPORTS]->(:Dataset)                PASS     REJECT
    └─ Schema는 통과, 의미 계층이 잡음: [RANGE_MISMATCH] REPORTS 의 range 는 Metric 인데 목적어가 Dataset

== Graph Schema vs 통제 어휘 대비 ==
  name='Self-RAG'               | Schema: PASS(:Method 라벨만 봄) | Vocab: 정규화 -> self-rag (Self-RAG)
  name='SELF-RAG'               | Schema: PASS(:Method 라벨만 봄) | Vocab: 정규화 -> self-rag (Self-RAG)
  name='Self-Reflective RAG'    | Schema: PASS(:Method 라벨만 봄) | Vocab: 정규화 -> self-rag (Self-RAG)
  name='FancyRAG'               | Schema: PASS(:Method 라벨만 봄) | Vocab: REJECT (NOT_IN_VOCABULARY: 통제 어휘에 없는 용어(신규 후보로 검토 필요))
  => 같은 개념이 3가지 표기로 흩어져도 Schema 는 못 잡는다. 통제 어휘가 하나('self-rag')로 접는다.
```

`(:Dataset)-[:USES]->(:Method)` 는 Graph Schema 기준으론 라벨·관계 타입이 다 등록돼 있으니 PASS 다. 의미 계층에서만 REJECT 로 잡힌다. 아래 어휘 대비에서도 라벨(:Method)만 보는 Schema 는 표기 흔들림을 전혀 못 본다. 이 대비가 이 토픽의 결론이다 — 구조를 맞추는 것과 의미를 맞추는 것은 다른 일이다.

---

## 검증 체크리스트

- [ ] 1단계에서 `Self-RAG -> Retrieval Method -> Method -> Concept` 경로가 출력된다.
- [ ] 2단계에서 `Self-Reflective RAG` 가 `self-rag` 로 정규화되고 `FancyRAG` 는 REJECT 된다.
- [ ] 3단계에서 `(:Dataset)-[:USES]->(:Method)` 가 DOMAIN_MISMATCH·RANGE_MISMATCH 로 REJECT 된다.
- [ ] 4단계에서 같은 트리플이 Schema=PASS, Semantic=REJECT 로 갈리는 대비가 출력된다.
