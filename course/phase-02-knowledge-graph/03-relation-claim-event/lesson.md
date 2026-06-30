# 2.3 관계·클레임·이벤트 추출 — 근거·시간·수치 보존

> **Phase 2 · 토픽 03** · 2/02 가 찍은 점(Entity) 사이에 선(Relation)을 긋고, 근거·수치가 필요한 주장을 Claim 노드로, 시간·다자 사건을 Event 노드로 올린다. 근거·수치·시점은 source span 으로 검증해 환각을 막는다.

## 학습 목표

이 토픽을 끝내면 다음을 할 수 있다.

- 1/05 청크와 2/02 `entities.jsonl` 을 입력으로 받아 Relation·Claim·Event 후보를 추출하는 파이프라인을 mock·Anthropic tool-use·instructor 세 백엔드로 만들고, 같은 인터페이스로 갈아끼운다.
- Claim.value(수치)와 Event.time(시점)을 surface 그대로 보존하고, 그 값이 근거 quote 안에 실제로 있는지로 환각을 차단한다.
- RelationType enum 위반·span quote 불일치·수치/시점 환각·dangling 참조를 reject 또는 경고로 분리해 집계하고, 통과분만 `relations.jsonl`·`claims.jsonl`·`events.jsonl` 로 저장한다.

**완료 기준**: `run_extract_rce.py` 가 mock 으로 sample 청크에서 Relation·Claim·Event 를 뽑아 모든 span 의 quote 일치와 Claim.value 의 quote 내 존재를 통과시키고 `relations.jsonl`·`claims.jsonl`·`events.jsonl` 을 저장하며, enum 밖 관계·환각 수치·깨진 span 을 넣으면 reject 로 잡히면 완료.

---

## 1. 왜 필요한가 — 점만 있고 선이 없다

2/02 에서 점을 찍었다. `LightRAG`, `Neo4j`, `RAG`, `GraphRAG` 같은 엔티티가 `entities.jsonl` 에 쌓였고, 전부 body offset Provenance 를 달고 있다. 문제는 점들이 서로 떨어져 있다는 것이다. `LightRAG` 와 `Neo4j` 가 무슨 사이인지, `LightRAG` 가 `GraphRAG` 대비 무엇을 줄였는지, 그래프는 아무것도 모른다.

선을 그어야 한다. 그게 Relation 이다. `(LightRAG)-[USES]->(Neo4j)`. 멀티홉 질문("LightRAG 가 쓰는 DB는?")은 이 선을 타야 답이 나온다. 선이 없으면 그래프는 그냥 흩어진 점 무더기고, GraphRAG 의 검색 이점이 사라진다.

선만으로 부족한 게 두 가지 더 있다. 수치가 붙은 주장과 시점이 핵심인 사건이다.

"LightRAG 가 GraphRAG 대비 토큰 비용을 99% 줄였다." 이걸 엣지 `(LightRAG)-[REDUCES_COST]->(GraphRAG)` 로 표현하면 `99%` 라는 수치를 어디 둘까. 엣지 속성에 욱여넣을 수는 있다. 하지만 같은 주장을 다른 문서가 다시 언급하거나, 근거 문장을 함께 들고 다녀야 하거나, 수치만 따로 질의해야 할 때 흩어진다. 그래서 Claim 을 노드로 올린다. 주체·술어·대상·수치·근거를 한 덩어리로 묶는 것이다.

"RAG 가 2020년 NeurIPS 에서 발표됐다." 여기엔 참여자가 셋이다 — RAG, NeurIPS, 그리고 시점. 엣지 하나는 두 끝점만 잇는다. (발표 주체, 발표 장소, 발표 시점)을 동시에 담지 못한다. 이런 n-ary 관계와 시점 중심 사건은 Event 노드로 올린다. 2/01 의 `graph_schema.py` 도크스트링이 이 논리를 그대로 적어 뒀다.

정리하면 이 토픽은 세 가지를 한다. 점을 선으로 잇고(Relation), 수치 주장을 노드로 올리고(Claim), 시간·다자 사건을 노드로 올린다(Event). 셋 다 2/01 스키마에 이미 정의돼 있다. 우리는 채우기만 한다.

## 2. 왜 Claim·Event 를 노드로 올리나 — 근거·수치·시점의 자리

핵심은 "엣지 속성에 욱여넣으면 흩어진다"는 한 문장이다.

Relation 은 두 엔티티의 단순 사이를 말한다. `USES`, `IMPROVES`, `CITES`. 방향과 타입만 있으면 충분하다. 그런데 주장에는 **수치**가, 사건에는 **시점과 다자 참여자**가 따라온다. 이것들을 엣지 속성에 넣기 시작하면 같은 주장을 재참조하기 어렵고, 근거 문장과 수치가 따로 놀고, 시점 질의가 꼬인다.

노드로 올리면 셋이 한 곳에 모인다. Claim 노드는 `subject·predicate·object·value·provenance` 를 한 객체로 들고 있고, Event 노드는 `name·participants·time·provenance` 를 들고 있다. 둘 다 Provenance 가 필수다. "이 수치, 이 시점, 어느 문장에서?"라는 질문에 항상 답할 수 있다.

그리고 모든 것의 바닥에 근거 보존이 깔린다. Relation·Claim·Event 전부 Provenance 를 필수로 매단다. 관계의 근거는 "head 와 tail 이 같이 나타난 그 span" 이다. 2/02 에서 배운 로컬 offset → body offset 환산과 quote 검증 사슬을 그대로 적용한다. 달라진 건 추출 대상이 점에서 선·주장·사건으로 늘었다는 것뿐이다.

## 3. 실습 — 근거 span 을 그대로 들고, 수치·시점을 surface 로 보존한다

추출기 시그니처는 2/02 와 같은 모양이다. 입력에 엔티티 집합이 하나 더 붙는다.

```python
def extract_relations_claims_events(
    chunk: dict, entities: list[Entity], backend: str = "mock"
) -> dict:   # {"relations": [Relation], "claims": [Claim], "events": [Event]}
    ...
```

`mock` 은 도메인 트리거(규칙) 기반이다. 키·네트워크·LLM 이 필요 없다. 기본 경로이고, labs 의 모든 학습자가 이걸로 돈다. `anthropic` 은 Claude tool-use 를 강제하고, `instructor` 는 `response_model` 로 Pydantic 응답을 직접 받는다. 둘 다 `ANTHROPIC_API_KEY` 가 필요한 선택 경로다. 비용이 부담되면 LLM 을 Ollama 로컬 모델로 바꿔도 파이프라인은 같다. 품질만 차이 난다.

### 관계의 근거는 "head 와 tail 이 같이 나타난 구간"

관계를 뽑을 때 위치 순서가 중요하다. `head` 를 찾고, 그 뒤에서 트리거를, 다시 그 뒤에서 `tail` 을 찾는다. 순서를 안 보면 함정에 빠진다. `GraphRAG was proposed by Microsoft. ... LightRAG compares to GraphRAG` 같은 문장에서 `GraphRAG` 는 맨 앞(주어)에도 나온다. 트리거 뒤에서 `tail` 을 찾아야 진짜 비교 대상 위치를 잡는다.

```python
# practice/extract_relations.py — 관계 근거 span 을 순서대로 잡는다
for head, trigger, tail, rtype in relation_rules:
    hs = _find_span(text, head)                       # head (단어 경계)
    if hs is None:
        continue
    ti = text.find(trigger, hs[1])                    # head 뒤에서 트리거
    if ti < 0:
        continue
    ts = _find_span(text, tail, ti + len(trigger))    # 트리거 뒤에서 tail
    if ts is None:
        continue
    # 근거 span = head 시작부터 tail 끝까지. 이 구간이 "둘이 같이 나타난" 증거다.
    prov = _to_body_provenance(chunk, hs[0], ts[1])
    relations.append(Relation(head=head, type=rtype, tail=tail, provenance=prov))
```

`_to_body_provenance` 는 2/02 와 글자 그대로 같다. 로컬 offset 에 `chunk.char_start` 를 더해 body offset 으로 바꾸고, quote 는 청크 text 에서 떠낸 사본을 넣는다. 관계든 엔티티든 근거 사슬은 같은 방식으로 잇는다.

### 수치는 변환하지 않는다 — surface 그대로

Claim.value 는 `99%` 를 받으면 `99%` 로 둔다. `0.99` 로 바꾸지 않는다. 반올림·단위 변환은 정보를 잃고, 나중에 근거 quote 와 대조할 수 없게 만든다.

```python
# practice/extract_relations.py — 수치 Claim. value 는 surface 보존
num_pattern = re.compile(r"\d+(?:\.\d+)?\s*%|\d+(?:\.\d+)?x")
subj_span = _find_span(text, "LightRAG")
if subj_span is not None and "reduces token cost" in text:
    cost_i = text.find("reduces token cost", subj_span[1])
    num_match = num_pattern.search(text, cost_i) if cost_i >= 0 else None
    if cost_i >= 0 and num_match is not None:
        # 근거 span = subject 시작부터 수치 끝까지. 수치를 quote 안에 포함시킨다.
        prov = _to_body_provenance(chunk, subj_span[0], max(cost_i + 18, num_match.end()))
        claims.append(Claim(
            subject="LightRAG", predicate="reduces_token_cost",
            object="GraphRAG", value=num_match.group(0).replace(" ", ""),  # surface
            provenance=prov,
        ))
```

근거 span 을 잡을 때 수치를 quote 안에 **포함시킨다**. 이게 검증의 핵심이다. quote 안에 `99%` 가 들어 있으면, 나중에 "value 가 quote 에 있나?"로 환각을 잡을 수 있다.

### 시점도 surface 그대로 — 지어내지 못하게

Event.time 도 마찬가지다. 텍스트에 `2020` 이 적혀 있으면 `2020` 을 넣는다. LLM 이 "아마 2021년쯤"이라고 추측하지 못하게, 근거 span 안에 연도가 실제로 있어야 한다.

```python
# practice/extract_relations.py — 시간 Event. time 은 근거 quote 안의 연도
year_pattern = re.compile(r"\b(1[89]\d{2}|20\d{2})\b")
actor_span = _find_span(text, "RAG was published")
if actor_span is not None and "published at" in text:
    year_match = year_pattern.search(text, actor_span[0])   # 사건 구간 뒤에서 연도
    venue_match = re.search(r"published at (\w+)", text)
    if year_match is not None:
        prov = _to_body_provenance(chunk, actor_span[0], year_match.end())
        participants = ["RAG"] + ([venue_match.group(1)] if venue_match else [])
        events.append(Event(
            name="RAG_publication", participants=participants,
            time=year_match.group(0), provenance=prov,   # surface 보존
        ))
```

LLM 백엔드에서도 위치·수치·시점을 LLM 에게 떠넘기지 않는다. 청크만 본 LLM 은 문서 body offset 을 모른다. 그래서 `local_start`·`local_end` 만 받고 body 환산은 코드가 한다. `value`·`time` 은 "텍스트에 적힌 표면형 그대로 써라"라고 도구 스키마와 프롬프트에 못 박고, 진짜인지는 추출 뒤 검증이 가린다. Anthropic 백엔드는 `tool_choice` 로 도구 호출을 강제하고, `relations.type` enum 을 `[t.value for t in RelationType]` 로 input_schema 에 박는다(2/01 통제 어휘).

> 전체 코드와 실행 절차는 [`practice/`](practice/) 와 [`labs/`](labs/) 참조.
> 기본 경로(mock)는 키 없이 돈다. 상용 분기는 `ANTHROPIC_API_KEY` 필요, 비용 대안은 Ollama + 로컬 모델(파이프라인 동일, 품질만 차이).

## 4. 결과 해석 — 추출했으면 다섯 가지로 검증한다

추출은 끝이 아니다. 2/02 의 두 게이트(enum·span quote)에 세 가지가 더 붙는다.

```
청크 4건 · 엔티티 16건 로드 — backend=mock
  src-05-lightrag::c012        → R 1 / C 0 / E 0
  src-02-self-rag::c003        → R 1 / C 0 / E 0
  src-04-graphrag::c008        → R 1 / C 0 / E 0
  src-05-lightrag::c021        → R 0 / C 1 / E 1

=== RCE 검증 리포트 ===
총 후보 5건 — accept 5 (R 3 / C 1 / E 1) / reject 0
--- relations (accepted) ---
  [OK] (LightRAG) -[USES]-> (Neo4j)  src=src-05-lightrag
  [OK] (Self-RAG) -[IMPROVES]-> (RAG)  src=src-02-self-rag
  [OK] (LightRAG) -[COMPARES_TO]-> (GraphRAG)  src=src-04-graphrag
--- claims (accepted) ---
  [OK] LightRAG reduces_token_cost value='99%'  src=src-05-lightrag
--- events (accepted) ---
  [OK] RAG_publication participants=['RAG', 'NeurIPS'] time='2020'  src=src-05-lightrag
--- warnings (다음 단계가 볼 것) ---
  [WARN] (event) dangling 참조: ['NeurIPS'] (raw=RAG_publication)

저장: relations.jsonl(3) claims.jsonl(1) events.jsonl(1) — 다음 토픽(2/04·2/05)의 입력
```

세 관계, 한 클레임, 한 이벤트가 통과했다. 검증은 다섯 가지를 본다.

첫째와 둘째는 2/02 그대로다. **RelationType enum 위반**(Pydantic 이 `Relation` 생성 시점에 막는다)과 **span quote 불일치**(`body[start:end] != quote` 면 근거 사슬이 깨진 것이라 버린다).

셋째, **수치 환각**. Claim.value 가 있으면 그 값이 근거 quote 안에 surface 그대로 있어야 한다. `99%` 라고 주장하면서 quote 에 `99%` 가 없으면 LLM 이 수치를 지어낸 것이다. 버린다.

넷째, **시점 환각**. Event.time 도 같다. `2020` 이라고 적으면서 quote 에 `2020` 이 없으면 시점을 지어낸 것이다. 버린다.

다섯째, **dangling 참조**. 관계의 head/tail 이나 이벤트 participant 가 2/02 엔티티 집합에 없으면 '매달린' 참조다. 위 출력에서 `NeurIPS` 가 그렇다 — 2/02 사전이 못 잡은 개체라 엔티티 집합에 없다. 기본은 이걸 reject 가 아니라 **경고**로 둔다. 엔티티 추출이 놓친 진짜 개체일 수 있고, 2/04 Entity Resolution 이 정리할 수도 있다. `--strict-dangling` 을 주면 reject 로 올라간다.

reject 된 후보는 그냥 버리지 않는다. 종류(relation/claim/event)와 사유를 함께 모아 둔다. 다음 Phase 의 reject queue 로 이어지는 복선이다(2/06 품질 게이트).

여기서 만든 `relations.jsonl`·`claims.jsonl`·`events.jsonl` 이 다음 토픽의 입력이다. 같은 `RAG` 가 여러 문서에서 잡혀 관계의 끝점이 됐다 — 이 중복을 하나로 합치는 엔티티 해소(Entity Resolution)는 2/04 의 일이고, 관계 타입 정규화와 Event 모델링 정교화는 2/05 가 맡는다.

---

## 🚨 자주 하는 실수

1. **수치·시점을 정규화해서 저장하기** — `99%` 를 `0.99` 로, `2020` 을 `2020-01-01T00:00:00Z` 로 "깔끔하게" 바꿔 넣는다. 그러면 근거 quote(`reduces token cost by 99%`)와 더 이상 1:1 로 대조되지 않아 환각 검증이 무력해진다. value·time 은 텍스트에 적힌 surface 그대로 보존하고, 단위 변환·ISO 변환은 2/05 정규화 단계로 미룬다.
2. **관계 근거 span 을 head/tail 표면형만으로 잡기** — `text.find("GraphRAG")` 처럼 첫 등장만 쓰면, 같은 표면형이 문장 앞(주어)에도 나올 때 엉뚱한 위치를 근거로 박는다. head 를 찾은 뒤 그 위치 **이후**에서 트리거를, 다시 그 이후에서 tail 을 찾아라. 단어 경계도 함께 봐야 `RAG` 가 `Self-RAG` 안에서 잡히지 않는다.
3. **dangling 참조를 조용히 통과시키기** — head/tail 이 엔티티 집합에 없는데 검사 없이 관계를 저장한다. 그러면 끝점이 비어 있는 관계가 Neo4j 적재(Phase 3) 단계에서 깨지거나 유령 노드를 만든다. 최소한 경고로 집계해 다음 단계가 보게 하고, 엄격히 가려야 하면 `--strict-dangling` 으로 reject 한다.

## 출처

- Pydantic — Structured Output·검증, https://docs.pydantic.dev/
- Anthropic Tool Use(구조적 추출), https://docs.anthropic.com/en/docs/build-with-claude/tool-use
- Graph RAG Survey(Construction 파트), arXiv 2408.08921, https://arxiv.org/abs/2408.08921

## 다음 토픽

→ [엔티티 해소(Entity Resolution)](../04-entity-resolution/lesson.md)
