"""extract_relations.py — 청크 1건에서 Relation·Claim·Event 후보를 뽑는다. 백엔드 3종.

2/02 가 Entity(점)만 뽑았다. 이 토픽은 그 점들 사이에 선을 긋고(Relation),
근거·수치가 필요한 주장을 노드로 올리고(Claim), 시간·다자 사건을 노드로 올린다(Event).

세 백엔드가 전부 같은 시그니처를 따른다(2/02 와 동일 구조):

    extract_relations_claims_events(
        chunk: dict, entities: list[Entity], backend: str = "mock"
    ) -> dict   # {"relations": [Relation], "claims": [Claim], "events": [Event]}

  - mock      : 규칙(도메인 트리거) 기반. 키·네트워크·LLM 불필요. 기본 경로다.
                labs 의 모든 학습자가 키 없이 이걸로 돈다.
  - anthropic : Claude tool-use 강제 호출. ANTHROPIC_API_KEY 필요(선택 의존).
  - instructor: instructor + Anthropic. 같은 키 필요(선택 의존).

핵심 교육 포인트 — 2/02 의 환산·검증 사슬을 Relation·Claim·Event 로 그대로 확장한다:

  1) 로컬 offset → body offset 환산(2/02 와 동일 공식). 관계의 근거는
     "head 와 tail 이 같이 나타난 그 span" 이다. Claim 의 근거는 "주장·수치가
     적힌 그 span", Event 의 근거는 "사건·시점이 적힌 그 span" 이다.

         prov.start = chunk.char_start + local_start
         prov.end   = chunk.char_start + local_end
         prov.quote = text[local_start:local_end]

  2) 수치·시간은 surface 그대로 보존한다. Claim.value 는 '99%' 를 '0.99' 로
     바꾸지 않는다. Event.time 은 '2020' 을 그대로 둔다. 반올림·단위 변환 금지.
     이게 진짜인지(환각이 아닌지)는 quote 안에 그 수치·시점이 실제로 있는지로
     validate_rce 가 검증한다.

  3) LLM 에게는 로컬 offset 만 받는다. 청크만 본 LLM 은 문서 body offset 을
     알 수 없다(2/02 와 동일 원칙). body 환산·Provenance 조립은 코드가 한다.

전제:
  - mock 경로: 외부 의존 0. pydantic>=2 만 필요.
  - anthropic/instructor 경로: ANTHROPIC_API_KEY 환경변수 + 해당 패키지 설치(선택).
    키는 os.environ 에서 읽고 하드코딩하지 않는다.
  - 비용 대안: LLM 을 Ollama 로컬 모델로 바꿔도 파이프라인은 동일하다(품질만 차이).
"""

from __future__ import annotations

import re

from schema_adapter import Claim, Entity, Event, Provenance, Relation, RelationType

# 현행 Claude 모델 id. 빠르게 바뀌므로 작성 시점 기준값이다.
ANTHROPIC_MODEL = "claude-sonnet-4-6"


def _to_body_provenance(chunk: dict, local_start: int, local_end: int) -> Provenance:
    """청크 로컬 offset 을 문서 body offset 으로 환산해 Provenance 를 만든다(2/02 와 동일).

    여기가 근거 사슬의 심장이다. 청크 안 위치(local_start..local_end)를
    chunk.char_start 만큼 밀어 문서 전체 기준 offset 으로 바꾼다.
    quote 는 청크 text 에서 그대로 떠낸 사본이라, 나중에 원문 body 로 1:1 검증된다.
    """
    text: str = chunk["text"]
    return Provenance(
        source_id=chunk["source_id"],
        version=chunk["version"],
        start=chunk["char_start"] + local_start,  # 로컬 → body 환산
        end=chunk["char_start"] + local_end,
        quote=text[local_start:local_end],        # 검증용 사본
    )


def _find_span(text: str, needle: str, start: int = 0) -> tuple[int, int] | None:
    """text[start:] 안에서 needle 을 단어 경계로 찾아 로컬 offset 으로 돌려준다.

    단어 경계가 중요하다. 'RAG' 는 'Self-RAG'·'GraphRAG' 안에도 박혀 있어서,
    경계를 안 보면 표면형 'RAG' 를 엉뚱한 위치(다른 단어 내부)에서 잡는다(2/02 와 같은 함정).
    앞뒤가 영숫자·하이픈이 아니어야 한 단어로 친다.
    """
    pattern = rf"(?<![\w-]){re.escape(needle)}(?![\w-])"
    m = re.search(pattern, text[start:])
    if m is None:
        return None
    return start + m.start(), start + m.end()


# ─────────────────────────────────────────────────────────────────────────────
# 백엔드 1: mock(규칙 기반). 기본 경로. 키·네트워크 불필요.
#
# 도메인 트리거: 청크 text 에 특정 동사·패턴이 보이면 그 근접 구간을 근거로
# Relation·Claim·Event 를 만든다. LLM 이 아니라 규칙이라 한계가 분명하다(문맥 못 봄).
# 그래도 키 없이 돌고, '근거·수치·시간을 어떻게 보존·검증하나'를 배우는 데 충분하다.
# 품질을 올리려면 anthropic 백엔드로.
# ─────────────────────────────────────────────────────────────────────────────


def _extract_mock(chunk: dict, entities: list[Entity]) -> dict:
    """도메인 트리거로 청크 text 를 스캔해 Relation·Claim·Event 후보를 만든다.

    각 후보의 근거 span 은 'head 와 tail(또는 주장·수치·시점)이 같이 나타난 구간'이다.
    그 구간을 _to_body_provenance 로 환산해 Provenance 를 매단다.
    """
    text: str = chunk["text"]
    relations: list[Relation] = []
    claims: list[Claim] = []
    events: list[Event] = []

    # ── Relation 트리거 ──────────────────────────────────────────────────────
    # 패턴: (head 표면형) ... (트리거 동사) ... (tail 표면형) 가 한 구간에 보이면
    # 그 둘을 품는 최소 span 을 근거로 Relation 을 만든다. RelationType 은 2/01 enum.
    relation_rules: list[tuple[str, str, str, RelationType]] = [
        # (head, 트리거(검증용·근거 구간 판단), tail, 관계 타입)
        ("Self-RAG", "improves", "RAG", RelationType.IMPROVES),
        ("LightRAG", "compares to", "GraphRAG", RelationType.COMPARES_TO),
        ("LightRAG", "stores entities in", "Neo4j", RelationType.USES),
    ]
    for head, trigger, tail, rtype in relation_rules:
        # 순서대로 찾는다: head → (head 뒤) trigger → (trigger 뒤) tail.
        # '뒤에서 찾기'가 핵심이다. 'GraphRAG' 는 문장 앞(주어)에도 또 나오므로,
        # trigger('compares to') 뒤에서 tail 을 찾아야 진짜 대상 위치를 잡는다.
        # 이 순서 제약이 곧 "head 와 tail 이 한 관계로 같이 나타난 구간"의 정의다.
        hs = _find_span(text, head)
        if hs is None:
            continue
        ti = text.find(trigger, hs[1])  # trigger 는 다중 단어라 단어 경계 대신 위치만 본다.
        if ti < 0:
            continue
        ts = _find_span(text, tail, ti + len(trigger))
        if ts is None:
            continue
        # 근거 span = head 시작부터 tail 끝까지. "둘이 같이 나타난 그 구간"이 관계의 근거다.
        local_start, local_end = hs[0], ts[1]
        prov = _to_body_provenance(chunk, local_start, local_end)
        relations.append(Relation(head=head, type=rtype, tail=tail, provenance=prov))

    # ── Claim 트리거(수치 보존) ──────────────────────────────────────────────
    # 패턴: (subject) reduces token cost ... (수치) → Claim(value=수치).
    # 수치는 surface 그대로 보존한다('99%' → '99%'). 근거 quote 안에 그 수치가 있어야
    # 한다(없으면 validate_rce 가 환각으로 reject).
    num_pattern = re.compile(r"\d+(?:\.\d+)?\s*%|\d+(?:\.\d+)?x")
    subj_span = _find_span(text, "LightRAG")
    if subj_span is not None and "reduces token cost" in text:
        cost_i = text.find("reduces token cost", subj_span[1])
        num_match = num_pattern.search(text, cost_i) if cost_i >= 0 else None
        if cost_i >= 0 and num_match is not None:
            # 근거 span = subject 시작부터 수치 끝까지. 수치를 quote 안에 포함시킨다.
            local_start = subj_span[0]
            local_end = max(cost_i + len("reduces token cost"), num_match.end())
            prov = _to_body_provenance(chunk, local_start, local_end)
            value = num_match.group(0).replace(" ", "")  # '99 %' 같은 표기도 '99%' 로
            claims.append(
                Claim(
                    subject="LightRAG",
                    predicate="reduces_token_cost",
                    object="GraphRAG" if "GraphRAG" in text else None,
                    value=value,             # surface 보존. 반올림·단위 변환 금지.
                    provenance=prov,
                )
            )

    # ── Event 트리거(시간 보존) ──────────────────────────────────────────────
    # 패턴: (X) was published at (Y) in (연도) → Event(participants=[X, Y], time=연도).
    # 참여자가 둘을 넘고 시점이 핵심이라 엣지가 아니라 노드로 올린다(2/01 도크스트링 논리).
    year_pattern = re.compile(r"\b(1[89]\d{2}|20\d{2})\b")
    # "RAG was published at NeurIPS in 2020" — 발표 주체·장소를 participants 로 잡는다.
    actor_span = _find_span(text, "RAG was published")
    if actor_span is not None and "published at" in text:
        year_match = year_pattern.search(text, actor_span[0])  # 사건 구간 뒤에서 연도를 찾는다.
        venue_match = re.search(r"published at (\w+)", text)
        if year_match is not None:
            local_start = actor_span[0]
            local_end = year_match.end()
            prov = _to_body_provenance(chunk, local_start, local_end)
            participants = ["RAG"]
            if venue_match is not None:
                participants.append(venue_match.group(1))  # 예: NeurIPS
            events.append(
                Event(
                    name="RAG_publication",
                    participants=participants,
                    time=year_match.group(0),  # surface 보존(예: '2020').
                    provenance=prov,
                )
            )

    return {"relations": relations, "claims": claims, "events": events}


# ─────────────────────────────────────────────────────────────────────────────
# 백엔드 2: Anthropic 네이티브 tool-use(강제 도구 호출).
# ─────────────────────────────────────────────────────────────────────────────


def _rce_input_schema() -> dict:
    """emit_rce 도구의 input_schema. LLM 이 채울 JSON 모양을 못 박는다.

    relations.type 은 [t.value for t in RelationType] 로 2/01 enum 을 강제한다.
    위치는 전부 local_start/local_end(주어진 text 안 offset)만 받는다 —
    body offset 환산·Provenance 조립은 우리가 한다(청크만 본 LLM 은 body offset 을 모른다).
    수치(claims.value)·시점(events.time)은 surface 문자열 그대로 받는다.
    """
    span = {
        "local_start": {"type": "integer"},
        "local_end": {"type": "integer"},
    }
    return {
        "type": "object",
        "properties": {
            "relations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "head": {"type": "string"},
                        "type": {
                            "type": "string",
                            "enum": [t.value for t in RelationType],  # 2/01 통제 어휘
                        },
                        "tail": {"type": "string"},
                        **span,
                    },
                    "required": ["head", "type", "tail", "local_start", "local_end"],
                },
            },
            "claims": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "subject": {"type": "string"},
                        "predicate": {"type": "string"},
                        "object": {"type": ["string", "null"]},
                        # 수치는 surface 문자열 그대로. 예: '99%', '2x'. 숫자형으로 받지 않는다.
                        "value": {"type": ["string", "null"]},
                        **span,
                    },
                    "required": ["subject", "predicate", "local_start", "local_end"],
                },
            },
            "events": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "participants": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 1,
                        },
                        # 시점도 surface 문자열 그대로. 예: '2020'. 지어내지 말 것.
                        "time": {"type": ["string", "null"]},
                        **span,
                    },
                    "required": ["name", "participants", "local_start", "local_end"],
                },
            },
        },
        "required": ["relations", "claims", "events"],
    }


def _extract_anthropic(chunk: dict, entities: list[Entity]) -> dict:
    """Claude 에게 tool-use 를 강제해 Relation·Claim·Event 후보를 받는다.

    전제: ANTHROPIC_API_KEY 환경변수 + `pip install anthropic`.
    """
    from anthropic import Anthropic  # 선택 의존. mock 경로에선 import 되지 않는다.

    client = Anthropic()  # 키는 ANTHROPIC_API_KEY 에서 자동으로 읽는다.
    text: str = chunk["text"]
    known_names = sorted({e.name for e in entities})

    tools = [
        {
            "type": "custom",
            "name": "emit_rce",
            "description": (
                "청크 텍스트에서 그래프 Relation·Claim·Event 후보를 뽑는다. "
                "relations.type 은 허용 enum 중 하나여야 한다. 모든 항목의 "
                "local_start/local_end 는 주어진 text 안에서의 offset 이며, head·tail·"
                "수치·시점이 실제로 그 구간에 나타나야 한다. claims.value 와 events.time 은 "
                "텍스트에 실제로 적힌 표면형 그대로 써라(반올림·단위 변환·날짜 추측 금지)."
            ),
            "input_schema": _rce_input_schema(),
        }
    ]

    message = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=2048,
        tools=tools,
        tool_choice={"type": "tool", "name": "emit_rce"},  # 도구 호출 강제
        messages=[
            {
                "role": "user",
                "content": (
                    "다음 청크에서 Relation·Claim·Event 후보를 emit_rce 로 내보내라. "
                    "head·tail 은 가능하면 다음 엔티티 이름을 써라: "
                    f"{known_names}.\n\ntext:\n{text}"
                ),
            }
        ],
    )

    data: dict | None = None
    for block in message.content:
        if block.type == "tool_use" and block.name == "emit_rce":
            data = block.input  # 도구 입력 = 우리가 받을 구조화 결과
            break
    if data is None:
        return {"relations": [], "claims": [], "events": []}

    return _assemble_from_llm(chunk, data)


# ─────────────────────────────────────────────────────────────────────────────
# 백엔드 3: instructor 패턴.
# ─────────────────────────────────────────────────────────────────────────────


def _extract_instructor(chunk: dict, entities: list[Entity]) -> dict:
    """instructor 로 Pydantic 응답 모델을 직접 받는다.

    전제: ANTHROPIC_API_KEY + `pip install instructor anthropic`.
    instructor 가 tool-use·검증·재시도를 감싸 준다. response_model 로 바로 받는다.
    """
    import instructor
    from anthropic import Anthropic
    from pydantic import BaseModel, Field

    # 신형 대안 한 줄:
    #   client = instructor.from_provider("anthropic/claude-sonnet-4-6", mode=instructor.Mode.TOOLS)
    client = instructor.from_anthropic(Anthropic())

    # LLM 에게 받는 1차 형태. body offset 은 우리가 환산하므로 로컬 offset 만 받는다.
    class _LLMRelation(BaseModel):
        head: str
        type: RelationType  # enum. instructor 가 enum 밖 값을 재시도로 걸러 준다.
        tail: str
        local_start: int = Field(..., ge=0)
        local_end: int = Field(..., gt=0)

    class _LLMClaim(BaseModel):
        subject: str
        predicate: str
        object: str | None = None
        value: str | None = None  # 수치 surface 보존
        local_start: int = Field(..., ge=0)
        local_end: int = Field(..., gt=0)

    class _LLMEvent(BaseModel):
        name: str
        participants: list[str] = Field(..., min_length=1)
        time: str | None = None  # 시점 surface 보존
        local_start: int = Field(..., ge=0)
        local_end: int = Field(..., gt=0)

    class _RCE(BaseModel):
        relations: list[_LLMRelation] = Field(default_factory=list)
        claims: list[_LLMClaim] = Field(default_factory=list)
        events: list[_LLMEvent] = Field(default_factory=list)

    text: str = chunk["text"]
    known_names = sorted({e.name for e in entities})
    resp = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=2048,
        response_model=_RCE,
        messages=[
            {
                "role": "user",
                "content": (
                    "다음 청크에서 Relation·Claim·Event 후보를 뽑아라. "
                    "head·tail 은 가능하면 이 엔티티 이름을 써라: "
                    f"{known_names}. local_start/local_end 는 text 안 offset. "
                    "value·time 은 텍스트에 적힌 표면형 그대로.\n\n"
                    f"text:\n{text}"
                ),
            }
        ],
    )
    raw = {
        "relations": [r.model_dump() for r in resp.relations],
        "claims": [c.model_dump() for c in resp.claims],
        "events": [e.model_dump() for e in resp.events],
    }
    return _assemble_from_llm(chunk, raw)


def _assemble_from_llm(chunk: dict, raw: dict) -> dict:
    """LLM 이 준 로컬 offset 후보를 body offset Provenance 가 달린 모델로 조립한다.

    LLM 이 enum 밖 RelationType 을 내면 Pydantic 이 여기서 ValidationError 로 막는다.
    이 토픽은 그걸 잡아서 죽이지 않고 그대로 던진다 — validate_rce 가 reject 로 집계한다.
    (2/02 _assemble_from_llm 과 같은 철학: 막되 숨기지 않는다.)
    """
    relations: list[Relation] = []
    for r in raw.get("relations", []):
        prov = _to_body_provenance(chunk, r["local_start"], r["local_end"])
        relations.append(
            Relation(head=r["head"], type=r["type"], tail=r["tail"], provenance=prov)
        )

    claims: list[Claim] = []
    for c in raw.get("claims", []):
        prov = _to_body_provenance(chunk, c["local_start"], c["local_end"])
        claims.append(
            Claim(
                subject=c["subject"],
                predicate=c["predicate"],
                object=c.get("object"),
                value=c.get("value"),  # surface 그대로. 변환하지 않는다.
                provenance=prov,
            )
        )

    events: list[Event] = []
    for e in raw.get("events", []):
        prov = _to_body_provenance(chunk, e["local_start"], e["local_end"])
        events.append(
            Event(
                name=e["name"],
                participants=e["participants"],
                time=e.get("time"),  # surface 그대로.
                provenance=prov,
            )
        )

    return {"relations": relations, "claims": claims, "events": events}


# ─────────────────────────────────────────────────────────────────────────────
# 공통 진입점.
# ─────────────────────────────────────────────────────────────────────────────

_BACKENDS = {
    "mock": _extract_mock,
    "anthropic": _extract_anthropic,
    "instructor": _extract_instructor,
}


def extract_relations_claims_events(
    chunk: dict, entities: list[Entity], backend: str = "mock"
) -> dict:
    """청크 1건 → {relations, claims, events}. backend 로 추출기를 고른다(기본 mock).

    entities 는 head·tail·participants 가 가리킬 '알려진 엔티티' 집합이다(2/02 출력).
    mock 은 도메인 트리거로, LLM 백엔드는 프롬프트 힌트로 이 집합을 활용한다.
    """
    if backend not in _BACKENDS:
        raise ValueError(f"알 수 없는 backend={backend!r}. 가능: {list(_BACKENDS)}")
    return _BACKENDS[backend](chunk, entities)


if __name__ == "__main__":
    # 키 없이 도는 빠른 점검: 마지막 샘플 청크(수치·연도 포함)를 mock 으로 뽑아 본다.
    import json
    from pathlib import Path

    here = Path(__file__).resolve().parent
    chunks = [
        json.loads(l)
        for l in (here / "sample_chunks.jsonl").read_text(encoding="utf-8").splitlines()
        if l.strip()
    ]
    cost_chunk = next(c for c in chunks if c["chunk_id"] == "src-05-lightrag::c021")
    out = extract_relations_claims_events(cost_chunk, entities=[], backend="mock")
    print(f"청크 {cost_chunk['chunk_id']} 에서 mock 추출:")
    for r in out["relations"]:
        p = r.provenance
        print(f"  REL    ({r.head}) -[{r.type.value}]-> ({r.tail}) body[{p.start}:{p.end}] quote={p.quote!r}")
    for c in out["claims"]:
        p = c.provenance
        print(f"  CLAIM  {c.subject} {c.predicate} value={c.value!r} body[{p.start}:{p.end}] quote={p.quote!r}")
    for e in out["events"]:
        p = e.provenance
        print(f"  EVENT  {e.name} participants={e.participants} time={e.time!r} body[{p.start}:{p.end}] quote={p.quote!r}")
