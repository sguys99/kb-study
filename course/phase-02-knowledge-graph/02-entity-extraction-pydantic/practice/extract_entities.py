"""extract_entities.py — 청크 1건에서 Entity 후보를 뽑는다. 백엔드 3종, 같은 인터페이스.

이 토픽의 본체다. 2/01 에서 '무엇을 추출할지' 정의했고, 여기서 '실제로 추출'한다.
다만 추출 타깃은 Entity 뿐이다. Relation·Claim·Event 는 다음 토픽(2/03)의 몫이다.

세 백엔드가 전부 같은 시그니처를 따른다:

    extract_entities(chunk: dict, backend: str = "mock") -> list[Entity]

  - mock      : 규칙(도메인 사전) 기반. 키·네트워크·LLM 불필요. 기본 경로다.
                labs 의 모든 학습자가 키 없이 이걸로 돌린다.
  - anthropic : Claude tool-use 강제 호출. ANTHROPIC_API_KEY 필요(선택 의존).
  - instructor: instructor + Anthropic. 같은 키 필요(선택 의존).

핵심 교육 포인트 — 로컬 offset → body offset 환산:
  청크 text 안에서 엔티티를 찾으면 그 위치는 '청크 로컬' offset 이다.
  이를 '문서 body' offset 으로 환산해야 Provenance 가 2/01·2/04 SourceSpan 과 호환된다.

      prov.start = chunk.char_start + local_start
      prov.end   = chunk.char_start + local_end
      prov.quote = text[local_start:local_end]

  이 환산으로 "엔티티 → 청크 → 문서 → 원문" 인용 사슬이 끊기지 않는다.
  quote 는 검증용 사본이다. 추출 뒤 body[start:end] == quote 를 반드시 확인한다(2/06 복선).

전제:
  - mock 경로: 외부 의존 0. pydantic>=2 만 필요.
  - anthropic/instructor 경로: ANTHROPIC_API_KEY 환경변수 + 해당 패키지 설치(선택).
    키는 os.environ 에서 읽고 하드코딩하지 않는다.
  - 비용 대안: LLM 을 Ollama 로컬 모델로 바꿔도 파이프라인은 동일하다(품질만 차이).
    instructor 는 OpenAI 호환 엔드포인트로 Ollama 를 붙일 수 있다(주석 참고).
"""

from __future__ import annotations

import os
import re

from schema_adapter import Entity, NodeType, Provenance

# 현행 Claude 모델 id. 빠르게 바뀌므로 작성 시점 기준값이다.
ANTHROPIC_MODEL = "claude-sonnet-4-6"

# ─────────────────────────────────────────────────────────────────────────────
# 코퍼스 도메인 사전 — mock 백엔드가 청크 text 를 스캔할 때 쓰는 표면형→NodeType 맵.
#
# 러닝 코퍼스(AI/LLM 8문서)에서 실제로 자주 나오는 표면형만 골랐다. LLM 이 아니라
# 사전이라 한계가 분명하다(동의어·문맥 못 봄). 그래도 키 없이 돌고, '추출 결과를
# 어떻게 검증·환산하나'를 배우는 데는 충분하다. 품질을 올리려면 anthropic 백엔드로.
# ─────────────────────────────────────────────────────────────────────────────

DOMAIN_LEXICON: dict[str, NodeType] = {
    "LightRAG": NodeType.MODEL,
    "Self-RAG": NodeType.MODEL,
    "CRAG": NodeType.MODEL,
    "GraphRAG": NodeType.MODEL,
    "RAG": NodeType.MODEL,
    "Neo4j": NodeType.TOOL,
    "Microsoft": NodeType.ORGANIZATION,
    "HKUDS": NodeType.ORGANIZATION,
    "embedding": NodeType.CONCEPT,
    "multi-hop": NodeType.CONCEPT,
    "retrieval quality": NodeType.CONCEPT,
}


def _to_body_provenance(chunk: dict, local_start: int, local_end: int) -> Provenance:
    """청크 로컬 offset 을 문서 body offset 으로 환산해 Provenance 를 만든다.

    여기가 이 토픽의 심장이다. 청크 안 위치(local_start..local_end)를
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


# ─────────────────────────────────────────────────────────────────────────────
# 백엔드 1: mock(규칙 기반). 기본 경로. 키·네트워크 불필요.
# ─────────────────────────────────────────────────────────────────────────────


def _extract_mock(chunk: dict) -> list[Entity]:
    """도메인 사전으로 청크 text 를 스캔해 매칭 span 마다 Entity 를 만든다."""
    text: str = chunk["text"]
    found: list[Entity] = []
    seen: set[tuple[str, int]] = set()  # (표면형, body_start) 중복 방지

    for surface, node_type in DOMAIN_LEXICON.items():
        # 단어 경계로 찾는다. 'RAG' 가 'GraphRAG' 안에 박힌 경우는 경계로 걸러진다.
        # (?<![\w-]) ... (?![\w-]) : 앞뒤가 영숫자·하이픈이 아니어야 한 단어로 친다.
        pattern = rf"(?<![\w-]){re.escape(surface)}(?![\w-])"
        for m in re.finditer(pattern, text):
            local_start, local_end = m.start(), m.end()
            prov = _to_body_provenance(chunk, local_start, local_end)
            key = (surface, prov.start)
            if key in seen:
                continue
            seen.add(key)
            found.append(Entity(name=surface, type=node_type, provenance=prov))

    # 안정적 순서: 등장 위치(body start) 순.
    found.sort(key=lambda e: e.provenance.start)
    return found


# ─────────────────────────────────────────────────────────────────────────────
# 백엔드 2: Anthropic 네이티브 tool-use(강제 도구 호출).
# ─────────────────────────────────────────────────────────────────────────────


def _entity_list_input_schema() -> dict:
    """emit_entities 도구의 input_schema. LLM 이 채울 JSON 모양을 못 박는다.

    name·type·local_start·local_end 만 LLM 에게 받는다. body offset 환산과
    Provenance 조립은 우리가 한다 — LLM 에게 문서 전체 offset 을 맡기지 않는다
    (청크만 본 LLM 은 문서 body offset 을 알 수 없다). type 은 enum 으로 강제.
    """
    return {
        "type": "object",
        "properties": {
            "entities": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "type": {
                            "type": "string",
                            "enum": [t.value for t in NodeType],  # 2/01 통제 어휘
                        },
                        "local_start": {"type": "integer"},
                        "local_end": {"type": "integer"},
                    },
                    "required": ["name", "type", "local_start", "local_end"],
                },
            }
        },
        "required": ["entities"],
    }


def _extract_anthropic(chunk: dict) -> list[Entity]:
    """Claude 에게 tool-use 를 강제해 Entity 후보를 받는다.

    전제: ANTHROPIC_API_KEY 환경변수 + `pip install anthropic`.
    """
    from anthropic import Anthropic  # 선택 의존. mock 경로에선 import 되지 않는다.

    client = Anthropic()  # 키는 ANTHROPIC_API_KEY 에서 자동으로 읽는다.
    text: str = chunk["text"]

    tools = [
        {
            "type": "custom",
            "name": "emit_entities",
            "description": (
                "청크 텍스트에서 그래프 엔티티 후보를 뽑는다. type 은 허용 enum 중 하나여야 하고, "
                "local_start/local_end 는 주어진 text 문자열 안에서의 offset 이다(text[local_start:local_end] 가 표면형)."
            ),
            "input_schema": _entity_list_input_schema(),
        }
    ]

    message = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=1024,
        tools=tools,
        tool_choice={"type": "tool", "name": "emit_entities"},  # 도구 호출 강제
        messages=[
            {
                "role": "user",
                "content": (
                    "다음 청크에서 엔티티 후보를 emit_entities 로 내보내라.\n\n"
                    f"text:\n{text}"
                ),
            }
        ],
    )

    data: dict | None = None
    for block in message.content:
        if block.type == "tool_use" and block.name == "emit_entities":
            data = block.input  # 도구 입력 = 우리가 받을 구조화 결과
            break
    if data is None:
        return []

    return _assemble_from_llm(chunk, data.get("entities", []))


# ─────────────────────────────────────────────────────────────────────────────
# 백엔드 3: instructor 패턴.
# ─────────────────────────────────────────────────────────────────────────────


def _extract_instructor(chunk: dict) -> list[Entity]:
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

    class _LLMEntity(BaseModel):
        # LLM 에게 받는 1차 형태. body offset 은 우리가 환산하므로 로컬 offset 만 받는다.
        name: str
        type: NodeType
        local_start: int = Field(..., ge=0)
        local_end: int = Field(..., gt=0)

    class _EntityList(BaseModel):
        entities: list[_LLMEntity] = Field(default_factory=list)

    text: str = chunk["text"]
    resp = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=1024,
        response_model=_EntityList,
        messages=[
            {
                "role": "user",
                "content": (
                    "다음 청크에서 엔티티 후보를 뽑아라. type 은 허용 enum 중 하나. "
                    "local_start/local_end 는 text 안에서의 offset.\n\n"
                    f"text:\n{text}"
                ),
            }
        ],
    )
    return _assemble_from_llm(chunk, [e.model_dump() for e in resp.entities])


def _assemble_from_llm(chunk: dict, raw_entities: list[dict]) -> list[Entity]:
    """LLM 이 준 로컬 offset 후보를 body offset Provenance 가 달린 Entity 로 조립한다.

    LLM 이 enum 밖 type 을 내면 Pydantic 이 여기서 ValidationError 로 막는다(2/01 통제 어휘).
    이 토픽은 그걸 막아서 죽이지 않고 그대로 던진다 — validate_entities 가 reject 로 집계한다.
    """
    out: list[Entity] = []
    for raw in raw_entities:
        prov = _to_body_provenance(chunk, raw["local_start"], raw["local_end"])
        # type 이 enum 밖이면 Entity(...) 가 ValidationError 를 던진다. 일부러 잡지 않는다.
        out.append(Entity(name=raw["name"], type=raw["type"], provenance=prov))
    return out


# ─────────────────────────────────────────────────────────────────────────────
# 공통 진입점.
# ─────────────────────────────────────────────────────────────────────────────

_BACKENDS = {
    "mock": _extract_mock,
    "anthropic": _extract_anthropic,
    "instructor": _extract_instructor,
}


def extract_entities(chunk: dict, backend: str = "mock") -> list[Entity]:
    """청크 1건 → Entity 후보 리스트. backend 로 추출기를 고른다(기본 mock)."""
    if backend not in _BACKENDS:
        raise ValueError(f"알 수 없는 backend={backend!r}. 가능: {list(_BACKENDS)}")
    return _BACKENDS[backend](chunk)


if __name__ == "__main__":
    # 키 없이 도는 빠른 점검: 첫 샘플 청크를 mock 으로 추출해 본다.
    import json
    from pathlib import Path

    sample_path = Path(__file__).resolve().parent / "sample_chunks.jsonl"
    first = json.loads(sample_path.read_text(encoding="utf-8").splitlines()[0])
    ents = extract_entities(first, backend="mock")
    print(f"청크 {first['chunk_id']} 에서 mock 으로 엔티티 {len(ents)}건 추출:")
    for e in ents:
        p = e.provenance
        print(f"  - {e.name:<10} {e.type.value:<12} body[{p.start}:{p.end}] quote={p.quote!r}")
