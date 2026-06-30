# 2.2 엔티티 추출 — Structured Output·Pydantic

> **Phase 2 · 토픽 02** · 청크에서 Entity 후보를 실제로 뽑는다. LLM 출력을 2/01 스키마에 강제로 끼우고, 근거 사슬이 끊기지 않게 offset 을 환산한다.

## 학습 목표

이 토픽을 끝내면 다음을 할 수 있다.

- 1/05 청크에서 Entity 후보를 추출하는 파이프라인을 mock·Anthropic tool-use·instructor 세 백엔드로 만들고, 같은 인터페이스로 갈아끼운다.
- 청크 로컬 offset 을 문서 body offset 으로 환산해, 추출 엔티티의 Provenance 를 2/01·2/04 SourceSpan 과 호환되게 만든다.
- 추출 결과를 NodeType enum 위반과 span quote 불일치로 검증해 reject 카운트를 내고, 통과분만 `entities.jsonl` 로 저장한다.

**완료 기준**: `run_extract.py` 가 mock 으로 샘플 청크에서 Entity 후보를 뽑아 모든 후보의 `body[start:end] == quote` 를 통과시키고 `entities.jsonl` 을 저장하며, enum 밖 라벨·깨진 span 을 넣으면 reject 로 잡히면 완료.

---

## 1. 왜 필요한가 — 스키마는 있는데 채울 게 없다

2/01 에서 스키마를 못 박았다. NodeType 8종, 관계 7종, 모든 노드에 Provenance 강제. 설계도는 완성됐다. 그런데 노드가 한 개도 없다. 빈 스키마다.

채워야 한다. 입력은 멀리서 오지 않는다. Phase 1/05 에서 만든 section-aware 청크가 그대로 입력이다. 청크 한 건은 본문 한 조각(`text`)과 위치 정보(`char_start`, `char_end`)를 들고 있다. 이 텍스트에서 `LightRAG`, `Neo4j`, `RAG` 같은 개체를 골라 Entity 노드로 만드는 일이 이 토픽이다.

범위는 좁게 긋는다. 이 토픽은 **Entity 후보 추출만** 한다. 관계·클레임·이벤트는 다음 토픽(2/03)이 맡는다. 한 번에 다 뽑으려 들면 추출기가 헷갈리고 검증도 뭉개진다. 점부터 찍고 선은 나중에 긋는다.

핵심 함정도 미리 말해 둔다. 엔티티를 청크 text 안에서 찾으면 그 위치는 **청크 로컬 offset** 이다. 이걸 그대로 Provenance 에 넣으면 안 된다. 2/01 의 Provenance 는 **문서 body offset** 을 기대한다. 환산을 빠뜨리면 인용 사슬이 거기서 끊긴다. 추출보다 이 환산이 이 토픽의 진짜 주제다.

## 2. LLM Structured Output — 출력을 스키마에 가두기

LLM 한테 "엔티티 뽑아 줘"라고 하면 자유 텍스트가 돌아온다. 파싱이 지옥이다. 어떤 날은 JSON, 어떤 날은 불릿, 어떤 날은 `Framework` 같은 멋대로 라벨. 스키마가 무용지물이 된다.

Structured Output 은 출력을 **미리 정한 모양**으로 강제한다. 우리에겐 2/01 의 `Entity`·`NodeType` 이 그 모양이다. type 은 enum 8종 밖으로 못 나가고, 빠진 필드는 거부된다. LLM 이 무슨 말을 하든 결과는 검증된 Pydantic 객체이거나 검증 실패다. 중간 지대가 없다.

이 토픽은 추출 백엔드를 세 개 보여준다. 전부 같은 시그니처를 따른다.

```python
def extract_entities(chunk: dict, backend: str = "mock") -> list[Entity]:
    ...
```

`mock` 은 규칙(도메인 사전) 기반이다. LLM·키·네트워크가 필요 없다. 기본 경로이고, labs 의 모든 학습자가 이걸로 돈다. `anthropic` 은 Claude tool-use 를 강제하고, `instructor` 는 instructor 로 Pydantic 응답을 직접 받는다. 둘 다 `ANTHROPIC_API_KEY` 가 필요한 선택 경로다. 비용이 부담되면 LLM 을 Ollama 로컬 모델로 바꿔도 파이프라인은 같다. 품질만 차이 난다.

## 3. 실습 — 로컬 offset 을 body offset 으로 환산한다

추출 자체는 단순하다. text 를 스캔해 개체를 찾는다. 어려운 건 찾은 뒤다. 위치를 문서 기준으로 바꿔야 한다.

청크가 `char_start=1200` 에서 시작한다고 하자. text 안 8번째 글자에서 `LightRAG` 를 찾았다면, 문서 body 기준 위치는 `1200 + 0 = 1200` 부터다. 공식은 한 줄이다.

```python
# practice/extract_entities.py 의 핵심 — 로컬 offset → body offset
def _to_body_provenance(chunk: dict, local_start: int, local_end: int) -> Provenance:
    text: str = chunk["text"]
    return Provenance(
        source_id=chunk["source_id"],
        version=chunk["version"],
        start=chunk["char_start"] + local_start,  # 로컬 → body 환산
        end=chunk["char_start"] + local_end,
        quote=text[local_start:local_end],        # 검증용 사본
    )
```

`quote` 는 청크 text 에서 그대로 떠낸 사본이다. 나중에 원문 body 와 1:1 로 맞춰 본다. 이 한 번의 덧셈으로 "엔티티 → 청크 → 문서 → 원문" 인용 사슬이 이어진다. 2/01·2/04 의 SourceSpan 과 호환되는 것도 이 덕분이다.

mock 백엔드는 도메인 사전으로 text 를 스캔한다.

```python
# practice/extract_entities.py — mock 추출(키 불필요)
DOMAIN_LEXICON = {"LightRAG": NodeType.MODEL, "Neo4j": NodeType.TOOL, "RAG": NodeType.MODEL, ...}

def _extract_mock(chunk: dict) -> list[Entity]:
    text = chunk["text"]
    found = []
    for surface, node_type in DOMAIN_LEXICON.items():
        # 단어 경계로 찾는다. 'RAG' 가 'GraphRAG' 안에 박힌 경우는 걸러진다.
        pattern = rf"(?<![\w-]){re.escape(surface)}(?![\w-])"
        for m in re.finditer(pattern, text):
            prov = _to_body_provenance(chunk, m.start(), m.end())
            found.append(Entity(name=surface, type=node_type, provenance=prov))
    return found
```

LLM 백엔드도 위치를 LLM 에게 맡기지 않는다. 청크만 본 LLM 은 문서 전체 offset 을 알 수가 없다. 그래서 LLM 에게는 `local_start`·`local_end`(text 안 위치)만 받고, body offset 환산과 Provenance 조립은 우리가 한다. Anthropic 백엔드는 `tool_choice` 로 도구 호출을 강제한다.

```python
# practice/extract_entities.py — Claude tool-use 강제
tools = [{"type": "custom", "name": "emit_entities", "input_schema": _entity_list_input_schema()}]
message = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=1024,
    tools=tools,
    tool_choice={"type": "tool", "name": "emit_entities"},  # 강제
    messages=[{"role": "user", "content": f"text:\n{text}"}],
)
for block in message.content:
    if block.type == "tool_use" and block.name == "emit_entities":
        data = block.input  # 구조화 결과
```

`input_schema` 의 type 필드는 `[t.value for t in NodeType]` 로 enum 을 박는다. 2/01 통제 어휘가 그대로 LLM 에게 강제된다. instructor 백엔드는 같은 일을 `response_model=EntityList` 한 줄로 끝낸다(전체 코드는 practice 참조).

> 전체 코드와 실행 절차는 [`practice/`](practice/) 와 [`labs/`](labs/) 참조.
> 기본 경로(mock)는 키 없이 돈다. 상용 분기는 `ANTHROPIC_API_KEY` 필요, 비용 대안은 Ollama + 로컬 모델(파이프라인 동일, 품질만 차이).

## 4. 결과 해석 — 추출했으면 검증한다

추출은 끝이 아니다. 뽑은 후보가 믿을 만한지 두 가지로 검증한다. 2/06 품질 게이트의 가장 단순한 형태다.

첫째, **enum 위반**. LLM 이 `Framework` 같은 NodeType 밖 라벨을 내면 Pydantic 이 객체 생성 시점에 막는다. 막는 데서 끝내지 않고 reject 로 집계한다. 어떤 라벨이 밖이었는지 사유와 함께 남긴다.

둘째, **span quote 불일치**. `body[start:end] != quote` 면 근거 사슬이 깨진 것이다. 버린다. 이게 "근거 사슬 무결성" 게이트다. 이 토픽에선 원문 body 대신 출처 청크 text 로 검증한다. 청크가 `body[char_start:char_end] == text` 를 보장하니 동치다.

```
청크 3건 로드 — backend=mock
  src-05-lightrag::c012        → 후보 4건
  src-02-self-rag::c003        → 후보 4건
  src-04-graphrag::c008        → 후보 5건

=== 엔티티 검증 리포트 ===
총 후보 13건 — accept 13 / reject 0
저장: entities.jsonl (13건) — 다음 토픽(2/03·2/04)의 입력
```

13건이 통과해 `entities.jsonl` 로 저장됐다. 한 줄이 Entity 1건, 전부 body offset Provenance 를 달고 있다. 여기서 같은 `LightRAG` 가 두 문서(`src-05`, `src-04`)에서 각각 잡혔다. 지금은 별개 노드다. 이 둘을 하나로 합치는 엔티티 해소(Entity Resolution)는 2/04 의 일이다.

reject 된 후보는 그냥 버리지 않는다. 사유와 함께 모아 둔다. 다음 Phase 의 reject queue 로 이어지는 복선이다. labs step 4 에서 enum 밖 라벨과 깨진 quote 를 일부러 넣어 reject 가 잡히는 걸 직접 본다.

여기서 만든 `entities.jsonl` 이 다음 토픽의 입력이다. 2/03 이 이 엔티티들 사이의 Relation·Claim·Event 를 뽑고, 2/04 가 중복 엔티티를 합친다.

---

## 🚨 자주 하는 실수

1. **로컬 offset 을 그대로 Provenance 에 넣기** — text 안에서 찾은 위치(`m.start()`)를 `char_start` 더하지 않고 그대로 저장한다. 그러면 인용이 문서 전체에서 엉뚱한 곳을 가리키고, 2/04·GraphRAG 단계에서 답변→원문 역추적이 끊긴다. `prov.start = chunk.char_start + local_start` 환산을 절대 빠뜨리지 마라. quote 로 즉시 검증하면 환산 누락이 바로 드러난다.
2. **위치 계산을 LLM 에게 맡기기** — "이 엔티티의 문서 offset 도 같이 내줘"라고 LLM 에 시킨다. 청크만 본 LLM 은 문서 body offset 을 알 수 없어 자릿수를 지어낸다. LLM 에게는 청크 안 로컬 위치만 받고(또는 표면형만 받아 우리가 `text.find` 로 위치를 잡고), body 환산은 코드가 한다.
3. **reject 를 조용히 버리기** — enum 위반·깨진 span 을 `try/except` 로 삼켜 카운트도 안 남긴다. 그러면 추출기가 얼마나 헛소리를 하는지 모르고, 다음 Phase 의 reject queue 도 못 만든다. reject 는 사유와 함께 보존하고, 최소한 카운트·사유는 출력한다.

## 출처

- Pydantic — Structured Output·검증, https://docs.pydantic.dev/
- Anthropic Tool Use(구조적 추출), https://docs.anthropic.com/en/docs/build-with-claude/tool-use
- Graph RAG Survey(Construction 파트), arXiv 2408.08921, https://arxiv.org/abs/2408.08921

## 다음 토픽

→ [관계·클레임·이벤트 추출](../03-relation-claim-event/lesson.md)
