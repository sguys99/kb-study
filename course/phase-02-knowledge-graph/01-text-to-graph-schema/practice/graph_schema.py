"""graph_schema.py — 텍스트에서 뽑을 그래프 스키마를 Pydantic v2 로 고정한다.

이 토픽의 본체다. 아직 LLM 으로 '추출'하지 않는다. 무엇을 추출할지 '정의'만 한다.
다음 토픽(02-entity-extraction-pydantic)이 여기서 정의한 모델을 추출 타깃으로 쓴다.

스키마가 코드로 박히면 두 가지가 따라온다.
  1) 허용 타입이 enum 으로 통제된다 — 추출기가 제멋대로 라벨을 만들지 못한다.
     (Phase 5 통제 어휘(Controlled Vocabulary)의 씨앗이다.)
  2) 모든 노드·관계·클레임이 provenance 를 강제로 매단다 — "이 사실, 어느 문장에서?"
     라는 질문에 항상 답할 수 있다. 04 SourceSpan 과 호환된다.

4요소(Entity / Relation / Claim / Event)를 왜 나누나:
  - Entity   : 그래프의 노드. 'RAG', 'Neo4j' 같은 개체.
  - Relation : 노드 사이의 엣지. (LightRAG)-[USES]->(Neo4j).
  - Claim    : 근거를 보존해야 하는 '주장' 단위. 누가/무엇을/(언제)/(수치)를
               source span 과 함께 노드로 승격한다. 단순 엣지로는 근거·수치를 못 담는다.
  - Event    : 시간·다자(n-ary) 관계. "2020년 RAG 가 NeurIPS 에서 발표됐다" 처럼
               참여자가 셋 이상이거나 시점이 핵심이면 엣지 하나로 표현이 깨진다 → 노드로.

provenance(04 SourceSpan 호환):
  source_id / start / end / quote + version.
  start<end, quote 는 검증용 사본. (원문 본문을 아는 쪽이 quote 일치를 확인한다.)

전제: 네트워크·API 키·LLM·DB 전부 불필요. 순수 로컬에서 키 없이 실행된다.
      (LLM 추출 분기 — Claude/Voyage 또는 Ollama+bge-m3 — 는 다음 토픽에서 등장한다.)
의존: pydantic>=2.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, model_validator

# ─────────────────────────────────────────────────────────────────────────────
# 통제 어휘 — 허용 노드 타입 / 관계 타입을 enum 으로 못 박는다.
#
# 러닝 코퍼스(AI/LLM 기술 문서 8건: RAG·Self-RAG·CRAG·GraphRAG·LightRAG·Neo4j·
# Embedding·Multi-hop)에서 '실제로 답이 되는' 것만 골랐다. 욕심내서 타입을 늘리면
# 추출기가 헷갈리고 정제 비용만 커진다. 골든 질문이 요구하는 만큼만 둔다.
# ─────────────────────────────────────────────────────────────────────────────


class NodeType(str, Enum):
    """허용 노드 라벨. CQ 가 답으로 요구하는 개체 종류만 둔다."""

    METHOD = "Method"          # 기법·알고리즘. 예: Self-Reflection, Corrective Retrieval
    MODEL = "Model"            # 시스템·프레임워크. 예: RAG, Self-RAG, LightRAG
    DATASET = "Dataset"        # 평가·학습 데이터셋
    METRIC = "Metric"          # 평가 지표. 예: Recall, Faithfulness
    PAPER = "Paper"            # 논문·문서 자체
    CONCEPT = "Concept"        # 개념. 예: 임베딩, 멀티홉, 커뮤니티 요약
    ORGANIZATION = "Organization"  # 기관. 예: Microsoft, HKUDS
    TOOL = "Tool"              # 구현 도구·DB. 예: Neo4j


class RelationType(str, Enum):
    """허용 관계(엣지) 타입. 방향·도메인·레인지는 schema_card.md 에 표로 적었다."""

    PROPOSES = "PROPOSES"          # Paper/Org -> Method/Model. 무엇을 제안했나.
    IMPROVES = "IMPROVES"          # Method/Model -> Method/Model. 무엇을 개선했나.
    EVALUATED_ON = "EVALUATED_ON"  # Model -> Dataset. 어디서 평가됐나.
    MEASURED_BY = "MEASURED_BY"    # Model/Method -> Metric. 무엇으로 측정했나.
    COMPARES_TO = "COMPARES_TO"    # Model -> Model. 무엇과 비교했나.
    USES = "USES"                  # Model -> Tool/Method. 무엇을 쓰나.
    CITES = "CITES"                # Paper -> Paper. 무엇을 인용했나.


# ─────────────────────────────────────────────────────────────────────────────
# Provenance — 04 SourceSpan 과 호환되는 근거 메타. 모든 노드·관계·클레임에 붙는다.
# ─────────────────────────────────────────────────────────────────────────────


class Provenance(BaseModel):
    """근거(provenance). "이 사실이 어느 문서·어느 문장에서 나왔나"를 못 박는다.

    04 SourceSpan(source_id, start, end, quote)에 version 을 더한 형태다.
    그래프 노드·엣지·클레임이 전부 이걸 매달아야 다음 Phase(Neo4j 적재, GraphRAG 인용)
    에서 답변→원문 역추적 사슬이 끊기지 않는다.
    """

    source_id: str = Field(..., description="근거 문서 stable ID. 예: src-01-rag.")
    version: str = Field(..., description="문서 version. 04 포맷 v{n}@{hash}. 예: v1@ab12cd34.")
    start: int = Field(..., ge=0, description="원문 시작 문자 offset(포함).")
    end: int = Field(..., gt=0, description="원문 끝 문자 offset(미포함). text[start:end].")
    quote: str = Field(..., description="검증용 인용 사본. text[start:end] 와 일치해야 한다.")

    @model_validator(mode="after")
    def _check_span(self) -> Provenance:
        if self.start >= self.end:
            raise ValueError(f"span 은 start < end 여야 한다: start={self.start}, end={self.end}")
        if not self.source_id.startswith("src-"):
            raise ValueError(f"source_id 는 'src-' 로 시작해야 한다: {self.source_id!r}")
        return self


# ─────────────────────────────────────────────────────────────────────────────
# 4요소 모델. 전부 provenance 를 필수로 매단다.
# ─────────────────────────────────────────────────────────────────────────────


class Entity(BaseModel):
    """엔티티(노드) 1건. 그래프의 점."""

    name: str = Field(..., description="표면형 이름. 정규화·엔티티 해소는 다음 토픽들의 몫.")
    type: NodeType = Field(..., description="허용 노드 타입 중 하나.")
    aliases: list[str] = Field(default_factory=list, description="같은 개체의 다른 표기.")
    provenance: Provenance = Field(..., description="이 엔티티를 어디서 봤나.")


class Relation(BaseModel):
    """관계(엣지) 1건. 두 엔티티를 잇는다. 방향 있음(head -> tail)."""

    head: str = Field(..., description="출발 엔티티 이름. (head)-[type]->(tail).")
    type: RelationType = Field(..., description="허용 관계 타입 중 하나.")
    tail: str = Field(..., description="도착 엔티티 이름.")
    provenance: Provenance = Field(..., description="이 관계를 어디서 봤나.")


class Claim(BaseModel):
    """클레임 1건. 근거·수치를 보존해야 하는 '주장'을 노드로 승격한다.

    왜 엣지가 아니라 노드인가: "LightRAG 가 GraphRAG 대비 토큰 비용을 99% 줄였다"
    같은 문장은 주체·대상·수치·근거를 한 덩어리로 묶어야 의미가 산다. 엣지 속성에
    욱여넣으면 수치·근거가 흩어지고, 같은 주장을 여러 곳에서 참조하기도 어렵다.
    """

    subject: str = Field(..., description="주장의 주체 엔티티 이름.")
    predicate: str = Field(..., description="주장 술어. 예: reduces_token_cost.")
    object: str | None = Field(default=None, description="주장 대상(있으면). 엔티티 이름 또는 값.")
    value: str | None = Field(default=None, description="수치·정량 값(있으면). 예: '99%'.")
    provenance: Provenance = Field(..., description="이 주장이 나온 source span. 필수.")


class Event(BaseModel):
    """이벤트 1건. 시간·다자(n-ary) 관계를 노드로 승격한다.

    "2020년 RAG 가 NeurIPS 에서 발표됐다"는 참여자가 둘을 넘고 시점이 핵심이다.
    엣지 하나로는 (발표 주체, 발표 장소, 발표 시점)을 동시에 담지 못한다 → 노드로.
    """

    name: str = Field(..., description="이벤트 이름. 예: RAG_publication.")
    participants: list[str] = Field(..., min_length=1, description="참여 엔티티 이름 목록(다자).")
    time: str | None = Field(default=None, description="발생 시점(ISO8601 권장). 예: 2020.")
    provenance: Provenance = Field(..., description="이 이벤트가 나온 source span. 필수.")


class GraphSchemaSample(BaseModel):
    """추출 결과 한 묶음의 형태. 다음 토픽의 LLM 추출 타깃 스키마이기도 하다."""

    entities: list[Entity] = Field(default_factory=list)
    relations: list[Relation] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    events: list[Event] = Field(default_factory=list)


if __name__ == "__main__":
    # 빠른 자기점검: 샘플 노드/관계/클레임/이벤트를 인스턴스화·검증하고 JSON 으로 찍는다.
    # 실제 추출이 아니라, 스키마가 '말이 되는지' 손으로 채워 보는 단계다.
    prov_lightrag = Provenance(
        source_id="src-05-lightrag",
        version="v1@ab12cd34",
        start=120,
        end=168,
        quote="LightRAG supports naive, local, global, hybrid, mix",
    )

    ent_lightrag = Entity(name="LightRAG", type=NodeType.MODEL, provenance=prov_lightrag)
    ent_neo4j = Entity(name="Neo4j", type=NodeType.TOOL, provenance=prov_lightrag)

    rel_uses = Relation(
        head="LightRAG",
        type=RelationType.USES,
        tail="Neo4j",
        provenance=prov_lightrag,
    )

    claim_cost = Claim(
        subject="LightRAG",
        predicate="reduces_token_cost",
        object="GraphRAG",
        value="99%",
        provenance=Provenance(
            source_id="src-05-lightrag",
            version="v1@ab12cd34",
            start=300,
            end=360,
            quote="reduces token cost by 99% compared to GraphRAG",
        ),
    )

    event_pub = Event(
        name="RAG_publication",
        participants=["RAG", "NeurIPS"],
        time="2020",
        provenance=Provenance(
            source_id="src-01-rag",
            version="v1@deadbeef",
            start=10,
            end=55,
            quote="RAG was published at NeurIPS in 2020",
        ),
    )

    sample = GraphSchemaSample(
        entities=[ent_lightrag, ent_neo4j],
        relations=[rel_uses],
        claims=[claim_cost],
        events=[event_pub],
    )

    print("=== 허용 노드 타입 ===")
    print(", ".join(t.value for t in NodeType))
    print("=== 허용 관계 타입 ===")
    print(", ".join(t.value for t in RelationType))
    print("=== 샘플 추출 묶음 검증 OK — JSON ===")
    print(sample.model_dump_json(indent=2))
