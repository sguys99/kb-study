# 5.2 Entity·Relation Type + Controlled Vocabulary 설계

> **Phase 5 · 토픽 02** · 01에서 파이썬 리터럴로 맛본 통제 어휘를 정식 레지스트리로 승격한다. Entity Type 카탈로그·Relation Type 카탈로그·개념 레지스트리를 데이터 파일로 설계하고, 추출기가 뱉은 raw 출력을 어휘에 매핑하거나 REJECT 하는 파이프라인을 만든다.

## 학습 목표

이 토픽을 끝내면 다음을 할 수 있다.

- 코퍼스(AI/LLM 기술 문서)용 Entity Type 카탈로그(Concept/Method/Dataset/Metric/Paper/Organization)와 Relation Type 카탈로그(USES/EVALUATED_ON/COMPARES/PART_OF/PROPOSED_BY/REPORTS)를 `vocabulary.yaml` 로 설계한다.
- 각 개념에 `preferred_label`·`alt_labels`·`definition`·`concept_id` 를 붙인 레지스트리를 만들고, Pydantic 로더로 슬러그 형식·id 중복·타입 참조 무결성을 로드 시점에 강제한다.
- 대소문자·하이픈·공백·약어 흔들림을 흡수하는 `normalize` 를 붙여 `resolve('Self-Reflective RAG')` 가 `self-rag` 를 돌려주게 만들고, 어휘에 없는 용어는 REJECT 시킨다.
- 추출기 raw 출력을 카탈로그에 매핑하거나 REJECT 하는 normalizer 를 만들어, "raw 중 몇 %가 어휘에 매핑됐나"를 커버리지 리포트로 뽑는다.

**완료 기준**: `vocabulary.yaml` 을 로드해 `resolve('Self-Reflective RAG')` 가 `self-rag` 를 반환하고, 미등록 relation `MENTIONS` 는 REJECT 되며, normalizer 가 코퍼스 raw type 의 매핑 커버리지 리포트(엔티티 85%·관계 82%)를 출력하면 완료.

---

## 1. 왜 필요한가 — 맛보기 어휘로는 운영이 안 된다

01에서 세 계층(Taxonomy·Vocabulary·Ontology)을 구분하며 통제 어휘를 맛봤다. `resolve("Self-Reflective RAG")` 가 `self-rag` 를 돌려주는 걸 확인했다. 다만 그 어휘는 파이썬 파일 안에 리터럴로 박혀 있었고, 개념 이름과 동의어 몇 개가 전부였다.

운영으로 넘어가면 세 가지가 부족하다.

어휘가 코드에 박혀 있으면 도메인 전문가가 못 고친다. 새 논문이 들어와 "이 표기도 Self-RAG 다"를 추가하려면 매번 파이썬을 열어야 한다. 어휘는 코드가 아니라 **데이터**여야 리뷰·확장이 열린다.

01은 개념 표기만 통제했다. 그런데 추출기는 라벨만 흔드는 게 아니다. **타입도 흔든다.** 같은 기법을 어떤 문서는 `Method`, 어떤 곳은 `Technique`, 또 어떤 곳은 `Model` 로 뱉는다. 관계도 마찬가지다. `USES` 하나면 될 것을 `USE`·`USING` 으로 쪼갠다. 개념 어휘만 있고 타입 어휘가 없으면 이 흔들림을 못 잡는다.

무엇이 매핑되고 무엇이 빠졌는지 셀 수가 없었다. 어휘가 코퍼스를 얼마나 덮는지 모르면 어디를 보강해야 할지도 모른다. **커버리지**라는 계기판이 필요하다.

이 토픽은 이 셋을 메운다. 어휘를 YAML 로 빼고, Entity/Relation Type 카탈로그를 정식으로 세우고, raw 출력의 매핑 커버리지를 리포트한다.

## 2. 무엇을 설계하나 — 세 카탈로그

통제 어휘 하나가 세 부분으로 나뉜다. 셋이 한 파일(`vocabulary.yaml`)에 산다.

**Entity Type 카탈로그**는 노드에 붙을 수 있는 라벨의 폐쇄 집합(closed set)이다. Concept·Method·Dataset·Metric·Paper·Organization 여섯 개만 허용한다. 추출기가 `Technique` 를 뱉으면 `Method` 의 동의어로 접고, `Person` 처럼 카탈로그 밖이면 REJECT 한다. 폐쇄 집합이라는 게 핵심이다 — 무엇이든 새 라벨이 되는 게 아니라, 정한 것만 통과한다.

**Relation Type 카탈로그**는 엣지 타입의 폐쇄 집합이다. USES·EVALUATED_ON·COMPARES·PART_OF·PROPOSED_BY·REPORTS. 각 관계에 `domain`·`range` 힌트를 적어 두지만, 여기서는 기록만 한다. domain/range 위반을 실제로 REJECT 하는 본격 제약 검증은 5/04 SHACL 의 몫이다. 이 토픽에서 관계 어휘가 하는 일은 "미등록 관계 타입 REJECT"까지다.

**개념 레지스트리**는 실제 개체다. `self-rag`·`crag`·`popqa` 같은 concept 하나하나가 `concept_id`(표준 식별자)·`preferred_label`(표준 표기 하나)·`alt_labels`(관측된 동의어)·`definition`(짧은 정의)를 갖는다. 각 개념은 자기 `entity_type` 을 위 카탈로그의 id 로 가리킨다.

```yaml
# practice/vocabulary.yaml 의 핵심 부분
entity_types:
  - id: method
    label: Method
    alt_labels: ["Technique", "Approach", "Algorithm", "Model", "Framework"]

relation_types:
  - id: uses
    label: USES
    domain: Method
    range: Dataset          # 참고용 기록. 위반 REJECT 는 5/04 SHACL.
    alt_labels: ["USE", "USING", "USED", "utilizes", "employs"]

concepts:
  - concept_id: self-rag
    entity_type: method     # entity_types 의 id 를 참조
    preferred_label: Self-RAG
    alt_labels: ["Self-Reflective RAG", "SELF-RAG", "self rag", "SelfRAG"]
    definition: "검색·생성·비평을 스스로 반복하며 근거를 자기 평가하는 기법."
```

## 3. 실습 A — 레지스트리를 로드하고 검증한다

어휘가 데이터 파일이 되면 새 위험이 생긴다. YAML 은 아무 문자열이나 받는다. `concept_id: Self-RAG`(대문자·하이픈)처럼 규약을 어긴 값이 슬쩍 들어와도 파일만 봐선 모른다. 그래서 로드 시점에 Pydantic 이 규약을 강제한다.

```python
# practice/controlled_vocabulary.py 의 핵심 부분
class ConceptEntry(BaseModel):
    concept_id: str
    entity_type: str          # entity_types 의 id 를 참조
    preferred_label: str
    alt_labels: list[str] = Field(default_factory=list)
    definition: str = ""

    @field_validator("concept_id")
    @classmethod
    def _slug(cls, v: str) -> str:
        if not _is_slug(v):   # 소문자·숫자·하이픈만
            raise ValueError(f"{_SLUG_MSG}: {v!r}")
        return v


class ControlledVocabulary(BaseModel):
    version: str
    entity_types: list[EntityType]
    relation_types: list[RelationType]
    concepts: list[ConceptEntry]

    @model_validator(mode="after")
    def _validate_and_index(self) -> "ControlledVocabulary":
        # id 중복 금지 + concept.entity_type 이 실제 카탈로그를 가리키는지(무결성)
        self._reject_dupes([c.concept_id for c in self.concepts], "concept_id")
        etype_ids = {e.id for e in self.entity_types}
        for c in self.concepts:
            if c.entity_type not in etype_ids:
                raise ValueError(f"{c.concept_id} 의 entity_type={c.entity_type} 가 카탈로그에 없다")
        ...  # 색인 구축
        return self
```

로더가 로드 시점에 막는 건 세 가지다. 잘못된 슬러그, 중복된 id, 그리고 존재하지 않는 타입을 가리키는 개념. 이 셋 중 하나라도 걸리면 `load_vocabulary()` 가 예외로 멈춘다. 잘못된 어휘가 파이프라인에 흘러들기 전에 잡자는 것이다.

## 4. 실습 B — 정규화를 넓히고 resolve 를 승격한다

01의 `_normalize` 는 대소문자·하이픈·공백까지 흡수했다. 코퍼스를 더 돌려 보면 한글 사이에 라틴 약어가 붙은 표기(`그래프RAG`)가 나온다. 정규화가 이 경계도 갈라 줘야 `그래프 rag` 로 접힌다.

```python
# practice/controlled_vocabulary.py 의 normalize
def normalize(term: str) -> str:
    s = term.strip().lower()
    for ch in ("-", "_", "/"):
        s = s.replace(ch, " ")       # 하이픈·언더스코어·슬래시 → 공백
    # 한글↔라틴 경계에 공백 삽입: '그래프rag' → '그래프 rag'
    out = []
    for i, c in enumerate(s):
        if i > 0:
            prev = s[i - 1]
            boundary = (("가" <= prev <= "힣") and c.isascii() and c.isalnum()) or \
                       (("가" <= c <= "힣") and prev.isascii() and prev.isalnum())
            if boundary:
                out.append(" ")
        out.append(c)
    return " ".join("".join(out).split())
```

색인은 동의어를 먼저 등록하고 표준 표기를 나중에 덮어쓴다. 정규화 키가 겹칠 때 `preferred` 가 이기게 하려는 것이다. `resolve` 는 이 색인 하나를 조회한다.

```python
def resolve(self, term: str) -> ResolveResult:
    hit = self._concept_index.get(normalize(term))
    if hit is None:
        return ResolveResult(input_term=term, resolved=False,
                             reason="NOT_IN_VOCABULARY: 개념 레지스트리에 없는 용어(신규 후보로 검토)")
    entry, matched_on = hit
    return ResolveResult(input_term=term, resolved=True, concept_id=entry.concept_id,
                         preferred_label=entry.preferred_label,
                         entity_type=entry.entity_type, matched_on=matched_on)
```

`resolve("Self-Reflective RAG")`·`resolve("SELF-RAG")`·`resolve("그래프RAG")` 는 각각 `self-rag`·`self-rag`·`graphrag` 를 돌려준다. `matched_on` 이 `preferred` 인지 `alt` 인지를 보면 표준에 맞았는지 동의어에 맞았는지 구분된다. 타입 축도 같은 구조다 — `resolve_relation_type("USE")` 는 `uses` 로 접히고, 카탈로그에 없는 `MENTIONS` 는 REJECT 된다.

## 5. 실습 C — raw 출력을 매핑하고 커버리지를 잰다

이제 실전이다. Phase 2 추출기가 뱉었다고 가정한 `raw_extractions.json` 을 어휘에 통과시킨다. 엔티티는 타입과 라벨 두 축을 **둘 다** 매핑해야 accepted 다. 하나라도 실패하면 rejected 로 격리한다.

```python
# practice/normalize_extraction.py 의 핵심 부분
def normalize_entities(vocab, entities):
    accepted, rejected = [], []
    for e in entities:
        t = vocab.resolve_entity_type(e["raw_type"])   # 타입 축
        c = vocab.resolve(e["raw_label"])              # 라벨 축
        if t.resolved and c.resolved:
            accepted.append({"entity_type": t.type_id, "concept_id": c.concept_id, ...})
        else:
            rejected.append({"raw_type": e["raw_type"], "raw_label": e["raw_label"], ...})
    return {"accepted": accepted, "rejected": rejected}


def coverage(result):
    a = len(result["accepted"])
    total = a + len(result["rejected"])
    return a, total, (a / total * 100 if total else 0.0)
```

> 전체 코드와 실행 절차는 [`practice/`](practice/)와 [`labs/`](labs/) 참조.
> 이 토픽도 개념형이라 LLM·임베딩 호출이 없다. API 키 없이 로컬에서 전부 돈다. 의존은 Pydantic v2 + PyYAML 둘뿐. (만약 alias 후보를 LLM 으로 제안받고 싶다면 Claude 대신 Ollama + `bge-m3` 로 바꿔도 파이프라인은 동일하다. 다만 이 토픽은 사람이 어휘를 큐레이션하는 게 요점이라 LLM 없이 진행한다.)

## 6. 결과 해석 — 100%가 아닌 게 정상이다

normalizer 를 돌리면 같은 개념이 세 타입·세 표기로 흩어져 들어와도 하나로 접힌다.

```
== 엔티티 매핑 ==
  OK     Method      /Self-RAG               -> :method       concept=self-rag
  OK     Technique   /Self-Reflective RAG    -> :method       concept=self-rag
  OK     Model       /SELF-RAG               -> :method       concept=self-rag
  ...
  REJECT Method      /FancyRAG               -> label:NOT_IN_VOCABULARY: ...
  REJECT Person      /Akari Asai             -> type:NOT_IN_ENTITY_TYPE_CATALOG: ...; label:...

== 커버리지 리포트 ==
  엔티티: 11/13 매핑  (85%)
  관계  : 9/11 매핑  (82%)
```

`Method`/`Technique`/`Model` 세 타입, `Self-RAG`/`Self-Reflective RAG`/`SELF-RAG` 세 표기가 전부 `:method` + `concept=self-rag` 하나로 모인다. 반대로 `Person` 타입, 레지스트리에 없는 `FancyRAG`·`Akari Asai`, 미등록 관계 `MENTIONS`·`CITES` 는 REJECT 로 빠진다.

여기서 85%·82% 라는 숫자를 어떻게 읽느냐가 중요하다. 100%가 목표가 아니다. REJECT 된 15%·18% 는 실패가 아니라 **어휘가 아직 못 담은 빈틈의 지도**다. `Akari Asai` 는 Person 타입이 없어서 걸렸고, `CITES` 는 신규 관계 후보다. 리포트가 이 둘을 콕 집어 주면 다음 어휘 확장을 근거 있게 할 수 있다(labs 3단계에서 실제로 넣어 92%·91%로 올린다). 반대로 `FancyRAG` 는 실존하지 않는 기법이라 넣지 않는 게 맞다. 커버리지 리포트는 "어디를 보강할지"와 "무엇을 무시할지"를 동시에 알려 주는 계기판이다.

여기서 만든 concept_id 레지스트리가 03(canonical-id-alignment)의 입력이다. 03은 이 `self-rag`·`crag` 같은 표준 식별자를 위키데이터 같은 외부 온톨로지의 ID에 정렬한다. 어휘가 표기를 하나로 접었으니, 03은 개념당 한 번만 외부 정렬을 하면 된다.

---

## 🚨 자주 하는 실수

1. **개념 어휘만 만들고 타입 어휘를 빼먹는다.** 추출기는 라벨(`Self-RAG` vs `SELF-RAG`)만 흔드는 게 아니라 타입(`Method` vs `Technique` vs `Model`)도 흔든다. 개념 레지스트리만 있고 Entity/Relation Type 카탈로그가 없으면 타입 흔들림을 못 잡아 `:Method` 와 `:Technique` 노드가 갈라진다. 두 축을 다 통제해야 매핑이 하나로 모인다.
2. **커버리지 100%를 목표로 alias 를 무작정 늘린다.** 리포트가 85%라고 남은 15%를 전부 어휘에 밀어 넣으면 안 된다. `FancyRAG` 처럼 실존하지 않는 표기까지 등록하면 오히려 잘못된 개념이 표준으로 굳는다. REJECT 는 "빈틈 후보"일 뿐, 자동 승격 대상이 아니다. 사람이 리뷰해 진짜 개념(`Akari Asai`)만 골라 넣는다.
3. **domain/range 위반까지 이 토픽에서 REJECT 하려 한다.** `vocabulary.yaml` 에 `domain`·`range` 를 적어 뒀지만 여기서는 기록만 한다. `(:Dataset)-[:USES]->(:Method)` 처럼 방향이 뒤집힌 트리플을 실제로 걸러내는 카디널리티·경로 제약 검증은 5/04(constraint-validation-shacl)의 몫이다. 이 토픽에서 SHACL 을 끌어오면 "어휘 통제"라는 초점이 흐려진다.
4. **concept_id 를 표기(preferred_label)와 뒤섞는다.** `concept_id` 는 소문자-하이픈 슬러그(`self-rag`)여야 하고, 표시용 표기(`Self-RAG`)와 분리해야 한다. id 에 대문자·공백을 쓰면 표기가 바뀔 때마다 id 도 흔들려 03의 외부 정렬이 깨진다. Pydantic 로더가 이 규약을 강제하는 이유다.

## 출처

- W3C SKOS Reference(통제어휘·시소러스 표준) — https://www.w3.org/TR/skos-reference/
- Pydantic — https://docs.pydantic.dev/
- PyYAML — https://pyyaml.org/wiki/PyYAMLDocumentation
- W3C SHACL 명세 — https://www.w3.org/TR/shacl/ · pySHACL — https://github.com/RDFLib/pySHACL
- *When Large Language Models Meet Knowledge Graphs for Question Answering: A Survey*, arXiv 2505.20099 — https://arxiv.org/abs/2505.20099

## 다음 토픽

→ [03-canonical-id-alignment — Canonical ID · Ontology Alignment(alias → 표준 개념)](../03-canonical-id-alignment/lesson.md)

