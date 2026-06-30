# 2.1 텍스트 → 그래프 스키마 (Entity·Relation·Claim·Event + Competency Question)

> **Phase 2 · 토픽 01** · 텍스트를 무엇으로 쪼갤지 설계한다. 추출하기 전에 "무엇을 추출할지"를 코드로 못 박는다.

## 학습 목표

이 토픽을 끝내면 다음을 할 수 있다.

- 엔티티·관계·클레임·이벤트 네 요소를 구분하고, 각각이 RAG 청크와 무엇이 다른지 설명한다.
- 클레임·이벤트를 단순 엣지가 아니라 별도 노드로 승격하는 이유를 근거·수치·시간·다자관계로 정당화한다.
- Phase 1 골든 질문을 능력 질문(Competency Question)으로 옮겨 적고, 거기서 그래프 스키마(노드 라벨·관계 타입·속성)를 역설계한다.
- 스키마를 Pydantic v2 모델로 고정하고, CQ 커버리지 검증기로 빠진 타입·관계를 추출 전에 잡아낸다.

**완료 기준**: `validate_schema.py` 가 competency_questions.yaml 의 모든 CQ에 대해 PASS를 내고 커버리지 100%를 출력하며, 스키마에 없는 관계 타입을 넣은 CQ는 REJECT로 잡히면 완료.

---

## 1. 왜 필요한가 — 청크는 "문장 덩어리"만 안다

Phase 1에서 만든 건 section-aware 청크다. 각 청크는 본문 한 조각과 `provenance`를 들고 있고, 벡터로 색인돼 유사도로 검색된다. single-hop 질문에는 잘 맞는다. "임베딩은 텍스트를 무엇으로 바꾸나?" 같은 질문은 한 문서 한 조각에 답이 다 들어 있다.

멀티홉에서 무너진다. gq08을 보자.

> "Self-RAG 와 CRAG 는 검색 품질 문제를 각각 어떻게 보정하나?"

답은 `src-02-self-rag`와 `src-03-crag` 두 문서에 흩어져 있다. 벡터 검색은 질문과 가장 비슷한 청크를 끌어올 뿐, "이 두 기법을 나란히 놓고 비교하라"는 구조를 모른다. 두 문서가 같은 문제(검색 품질)를 다룬다는 연결이 텍스트 표면에는 안 적혀 있기 때문이다. 사람은 안다. 벡터는 모른다.

연결을 명시적으로 저장하면 된다. Self-RAG도 CRAG도 같은 `Concept`(검색 품질 보정)에 걸려 있고, 각자 다른 `Method`를 쓴다고 그래프에 적어 두면, "둘을 비교"는 그래프를 두 홉 타고 가는 일이 된다. 그러려면 텍스트를 점(엔티티)과 선(관계)으로 바꿔야 한다. 이 토픽은 그 변환의 설계도를 그린다.

한 가지 선을 긋자. 이 토픽은 **무엇을 추출할지 정의**하는 단계다. LLM으로 실제 문서에서 엔티티를 뽑는 추출 실행은 다음 토픽(02-entity-extraction-pydantic)의 몫이다. 설계 없이 추출부터 하면, 추출기가 매번 다른 라벨을 토해내고 나중에 정제 비용만 폭발한다.

## 2. 네 요소 — Entity·Relation·Claim·Event

텍스트를 그래프로 바꿀 때 쓰는 단위는 넷이다. RAG 청크와 비교하면 차이가 분명하다.

**엔티티(Entity)** 는 그래프의 점이다. `RAG`, `Neo4j`, `임베딩` 같은 개체. 청크가 "문장 덩어리"라면 엔티티는 그 덩어리 안에서 추려낸 "고유한 것"이다. 같은 개체가 여러 문서에 나와도 그래프에서는 노드 하나로 모인다(이 합치기, 즉 엔티티 해소(Entity Resolution)는 뒤 토픽 몫이다).

**관계(Relation)** 는 두 엔티티를 잇는 방향 있는 선이다. `(LightRAG)-[USES]->(Neo4j)`. 청크에는 "LightRAG가 Neo4j를 쓴다"가 문장으로 묻혀 있지만, 그래프에서는 엣지로 떠올라 두 홉, 세 홉 타고 갈 수 있는 길이 된다.

**클레임(Claim)** 과 **이벤트(Event)** 는 한 단계 더 들어간다. 둘 다 "엣지 하나로는 담기지 않는 것"을 노드로 끌어올린 것이다. 왜 그래야 하는지가 이 토픽의 핵심 직관이다.

### 클레임을 왜 노드로 승격하나

"LightRAG가 GraphRAG 대비 토큰 비용을 99% 줄였다." 이 문장을 엣지 하나로 적으면 `(LightRAG)-[REDUCES_COST]->(GraphRAG)`가 된다. 그런데 99%는? 어느 문장이 근거인가? 엣지에 속성으로 욱여넣을 수는 있지만, 주체·대상·수치·근거가 흩어진다. 같은 주장을 다른 곳에서 참조하기도 어렵다.

클레임은 이걸 한 노드로 묶는다. `subject=LightRAG`, `predicate=reduces_token_cost`, `object=GraphRAG`, `value=99%`, 그리고 `provenance`로 "이 문장에서 나왔다"를 매단다. 주장 하나가 일급 시민이 되는 셈이다. 나중에 "근거 없는 주장 거르기" 같은 품질 게이트도 클레임 단위로 건다.

### 이벤트를 왜 노드로 승격하나

"2020년 RAG가 NeurIPS에서 발표됐다." 참여자가 둘을 넘고(RAG, NeurIPS), 시점(2020)이 핵심이다. 엣지 하나로는 (발표 주체, 발표 장소, 발표 시점)을 동시에 못 담는다. 이런 다자(n-ary) 관계나 시간성이 중요한 사건은 이벤트 노드로 올린다. `participants=[RAG, NeurIPS]`, `time=2020`.

정리하면 엔티티·관계는 그래프의 뼈대고, 클레임·이벤트는 근거·수치·시간·다자관계를 잃지 않으려고 추가로 승격하는 노드다. 러닝 코퍼스(AI/LLM 문서)에서는 엔티티·관계가 대부분이고, 정량 비교 주장에 클레임, 발표·릴리스 같은 사건에 이벤트가 붙는다.

## 3. CQ에서 스키마를 역설계한다

스키마를 손가락 가는 대로 그리면 안 된다. 출발점은 질문이다. **그래프가 답해야 할 질문이 스키마를 결정한다.** 이 질문 묶음을 능력 질문(Competency Question, CQ)이라고 부른다.

절차는 단순하다. 골든 질문을 CQ로 옮긴다 → 그 답이 어떤 모양인지 본다 → 답을 내려면 어떤 노드 타입·관계 타입·속성이 있어야 하는지 적는다 → 스키마로 환원한다.

cq08(앞의 gq08)로 해 보자. 답은 "Self-RAG와 CRAG가 각각 쓰는 Method, 그리고 둘의 비교"다. 그러려면 `Model`(Self-RAG, CRAG)과 `Method` 노드, 그 둘을 잇는 `USES`, 두 모델을 잇는 `COMPARES_TO`가 필요하다. 이걸 CQ 메타로 적는다.

```yaml
# practice/competency_questions.yaml 의 한 항목
- id: cq08
  question: "Self-RAG 와 CRAG 는 검색 품질 문제를 각각 어떤 기법으로 보정하며, 둘은 어떻게 비교되나?"
  type: multi-hop
  source_gq: gq08            # Phase 1 골든 질문에서 파생(A/B 비교 일관성 유지)
  node_types: ["Model", "Method"]
  relation_types: ["USES", "COMPARES_TO"]
  answer_shape: "두 Model 의 Method 비교(경로)"
```

골든 질문에는 없던 `node_types`·`relation_types`·`answer_shape`가 붙었다. 이게 역설계의 산물이다. 멀티홉 CQ가 요구하는 관계(`COMPARES_TO`, `IMPROVES` 같은)가 곧 그래프가 벌어야 할 값이다. Vector-only가 약했던 바로 그 지점이다.

CQ를 다 적으면 거기 등장한 타입의 합집합이 스키마의 후보가 된다. 코퍼스 8문서에서 실제로 답이 되는 것만 추리면 노드 8종, 관계 7종으로 충분하다.

이제 그 스키마를 코드로 굳힌다. Pydantic v2를 쓴다. 허용 타입을 enum으로 통제하면 추출기가 제멋대로 라벨을 만들지 못한다. 다음 Phase의 통제 어휘(Controlled Vocabulary)의 씨앗이다.

```python
# practice/graph_schema.py 의 핵심 부분
from enum import Enum
from pydantic import BaseModel, Field, model_validator


class NodeType(str, Enum):
    METHOD = "Method"; MODEL = "Model"; DATASET = "Dataset"; METRIC = "Metric"
    PAPER = "Paper"; CONCEPT = "Concept"; ORGANIZATION = "Organization"; TOOL = "Tool"


class RelationType(str, Enum):
    PROPOSES = "PROPOSES"; IMPROVES = "IMPROVES"; EVALUATED_ON = "EVALUATED_ON"
    MEASURED_BY = "MEASURED_BY"; COMPARES_TO = "COMPARES_TO"; USES = "USES"; CITES = "CITES"


class Provenance(BaseModel):
    """04 SourceSpan 호환. 모든 노드·관계·클레임이 매단다 — "이 사실, 어느 문장에서?"."""
    source_id: str
    version: str                      # 04 포맷 v{n}@{hash}
    start: int = Field(..., ge=0)
    end: int = Field(..., gt=0)
    quote: str

    @model_validator(mode="after")
    def _check(self):
        if self.start >= self.end:
            raise ValueError("span 은 start < end 여야 한다")
        return self


class Claim(BaseModel):
    """근거·수치를 보존하는 주장 노드. 엣지가 아니라 노드인 이유는 본문 2장 참고."""
    subject: str
    predicate: str
    object: str | None = None
    value: str | None = None          # 정량 값. 예: "99%"
    provenance: Provenance            # 필수 — 근거 없는 주장은 만들지 않는다
```

`Entity`, `Relation`, `Event` 모델도 같은 방식이다. 전부 `provenance`를 필수로 매단다. 04의 `SourceSpan`(source_id, start, end, quote)에 version을 더한 형태라, Neo4j 적재·GraphRAG 인용 단계에서 답변→원문 역추적이 끊기지 않는다.

> 전체 코드와 실행 절차는 [`practice/`](practice/) 와 [`labs/`](labs/) 참조. 스키마를 사람이 읽는 표로는 [`practice/schema_card.md`](practice/schema_card.md)에 정리했다.
> 이 토픽은 LLM·DB가 없어 키 없이 로컬에서 돈다. 상용 API(Claude/Voyage) 또는 로컬 대안(Ollama + `bge-m3`) 분기는 실제 추출이 등장하는 다음 토픽에서 다룬다.

## 4. 결과 해석 — CQ로 스키마를 되받아 검증한다

스키마를 다 짰으면 한 번 더 묻는다. "이 스키마로 모든 CQ에 답할 수 있나?" `validate_schema.py`가 각 CQ의 `node_types`·`relation_types`가 enum에 다 있는지 대조한다.

```
스키마 통제 어휘 — 노드 8종 / 관계 7종
CQ 12건 커버리지 점검

  [PASS]   cq08  (multi-hop)
  ...
커버리지: 12/12 = 100%
모든 CQ 가 현재 스키마로 답 가능 — 추출 단계로 넘어가도 된다.
```

100%는 "스키마가 모든 CQ를 받아낸다"는 뜻이다. 빠진 게 있으면 REJECT로 떨어지고 어떤 타입이 없는지 찍힌다(labs step 4에서 일부러 깨뜨려 본다). 이게 Phase 2 품질 게이트의 가장 단순한 형태다. 빠진 타입을 발견하면 선택지는 둘이다. 스키마에 타입을 추가하거나, 그 CQ를 범위 밖으로 빼거나. 어느 쪽이든 **추출을 시작하기 전에** 정한다.

여기서 만든 `graph_schema.py`와 `competency_questions.yaml`이 다음 토픽의 입력이다. 02-entity-extraction-pydantic이 이 스키마를 추출 타깃으로 받아, LLM Structured Output으로 실제 문서에서 엔티티를 뽑는다.

---

## 🚨 자주 하는 실수

1. **스키마부터 그리고 질문은 나중에** — 답해야 할 질문 없이 "있어 보이는" 노드·관계를 잔뜩 만든다. 그러면 추출은 화려한데 정작 골든 질문엔 답이 안 된다. 순서를 뒤집지 마라. CQ가 먼저, 스키마는 그 결과물이다. 빈 칸(어떤 CQ도 안 쓰는 타입)은 의심하라.
2. **클레임·수치를 엣지 속성에 욱여넣기** — "99% 절감" 같은 정량 주장을 `COMPARES_TO` 엣지의 속성으로 처리하면 근거·수치가 흩어지고 재사용이 안 된다. 근거를 보존해야 하는 주장은 Claim 노드로 승격한다. 시간·다자관계가 핵심이면 Event로.
3. **provenance 없는 노드를 허용하기** — "나중에 붙이지" 하고 근거 없이 노드를 만들면, 다음 Phase에서 답변에 인용을 못 붙이고 역추적이 끊긴다. 04 SourceSpan과 호환되는 provenance를 처음부터 필수 필드로 둔다(Pydantic이 누락을 막게).

## 출처

- Pydantic — Structured Output·검증, https://docs.pydantic.dev/
- Anthropic Tool Use(구조적 추출), https://docs.anthropic.com/en/docs/build-with-claude/tool-use
- Graph RAG Survey(Construction 파트), arXiv 2408.08921, https://arxiv.org/abs/2408.08921

## 다음 토픽

→ [엔티티 추출 — Structured Output·Pydantic](../02-entity-extraction-pydantic/lesson.md)
