# 2.4 엔티티 해소 — alias·coreference·fuzzy·embedding 병합

> **Phase 2 · 토픽 04** · 2/02·2/03 이 표면형 그대로 찍어 둔 중복 점들을 하나로 합친다. alias → coreference → fuzzy → embedding 4단계로 병합 후보를 만들고, Union-Find 로 묶어 canonical 엔티티를 정한 뒤, 관계의 head/tail 을 canonical 이름으로 재배선한다. Self-RAG·CRAG 가 RAG 로 빨려 들어가지 않도록 substring 가드를 건다.

## 학습 목표

이 토픽을 끝내면 다음을 할 수 있다.

- 2/03 의 `entities.jsonl`·`relations.jsonl` 을 입력으로 받아 alias·coreference·fuzzy·embedding 4단계 엔티티 해소(Entity Resolution·ER) 파이프라인을 mock·VoyageAI·로컬 세 임베딩 백엔드로 만들고, 같은 인터페이스로 갈아끼운다.
- 병합 후보 쌍을 Union-Find 로 클러스터링하고, 빈도·길이 규칙으로 canonical 을 골라 `canonical_entities.jsonl`·`merge_map.json` 을 만들며, 관계의 head/tail 을 canonical 이름으로 재배선한다.
- `Self-RAG`·`CRAG` 처럼 `RAG` 를 부분문자열로 품은 다른 개체가 오병합되지 않도록 type 일치·substring 가드로 막고, 그 가드가 실제로 동작하는지 회귀 테스트로 검증한다.

**완료 기준**: `run_resolve.py` 가 mock 으로 19건 엔티티를 10개 canonical 로 병합해 `canonical_entities.jsonl`·`merge_map.json`·`relations.resolved.jsonl` 을 저장하고, `Self-RAG`·`CRAG`·`RAG` 가 서로 다른 canonical 로 남으며, `validate_resolution.py` 의 네 가지 검증(type 일관·오병합 가드·merge_map 1:1·dangling 없음)을 전부 통과하면 완료.

---

## 1. 왜 필요한가 — 같은 점이 여러 개다

2/02 에서 점을 찍고, 2/03 에서 선을 그었다. 문제는 점이 깨끗하지 않다는 데 있다. 2/03 이 만든 `entities.jsonl` 을 열어 보면 같은 개체가 여러 번 들어 있다. `LightRAG` 가 3건, `RAG` 가 3건, `GraphRAG` 가 3건. 전부 다른 문서, 다른 offset 에서 추출됐다. 추출기는 표면형(surface form)을 본 그대로 찍을 뿐, "이 LightRAG 와 저 LightRAG 가 같은 놈"이라는 걸 모른다.

이대로 Neo4j 에 적재하면 같은 개체가 노드 3개가 된다. 멀티홉 경로가 셋으로 쪼개지고, "LightRAG 를 쓰는 도구는?" 같은 질문에서 한 노드만 답을 알고 나머지 둘은 모른다. 카운트도 부풀려진다. 그래프 품질을 결정하는 건 추출이 아니라 정제다 — Phase 2 의 한 문장이 여기서 현실이 된다.

합치는 게 답이다. 하지만 합치기는 위험하다. `Self-RAG` 와 `CRAG` 는 둘 다 이름에 `RAG` 가 들어 있다. 순진하게 문자열만 보면 `RAG` 로 빨려 들어간다. 합쳐지는 순간 "Self-RAG 가 RAG 를 개선한다"는 사실이 "RAG 가 RAG 를 개선한다"는 헛소리가 된다. 합치는 것만큼 **안 합치는 것**이 중요하다.

이 토픽은 둘을 동시에 한다. 같은 건 합치고, 다른 건 끝까지 떼어 놓는다.

## 2. 4단계 ER — 싼 것부터 비싼 것 순으로

병합을 한 방에 하지 않는다. 비용과 정확도가 다른 네 단계를 쌓는다. 앞 단계가 확실한 걸 먼저 걷어내면, 뒤 단계는 어려운 것만 본다.

**1단계 alias 사전 병합.** 표면형을 정규화(normalize)해 키가 같으면 합친다. 소문자로 낮추고 하이픈·언더스코어를 공백으로 바꾼 다음 연속 공백을 하나로 누른다. `LightRAG` 가 세 문서에서 똑같이 `LightRAG` 면 키가 같으니 바로 묶인다. 2/02·2/03 에서 채운 `aliases` 필드도 키로 친다. 가장 싸고 가장 확실하다.

**2단계 coreference 해소.** 같은 문서(`source_id`) 안에서 같은 표면형은 같은 개체로 본다. 한 문서가 `RAG` 를 다섯 번 말하면 그건 같은 RAG 다(문서 내 일관성 가정). 1단계가 이미 잡는 경우가 많지만, coref 는 "문서 경계"를 근거로 한 번 더 못 박는다. 대명사·약어까지 푸는 LLM 보조 coref 는 키가 필요하니 여기선 룰 기반만 쓴다.

**3단계 fuzzy 매칭.** 정규화 키가 달라도 닮은 것을 문자열 유사도로 잡는다. `Light RAG`·`LightRag` 같은 표기 흔들림이 대상이다. rapidfuzz 의 `token_sort_ratio` 를 쓴다 — 임베딩 없이 저비용으로 오타를 흡수한다. 여기에 **substring 가드**가 붙는다. `CRAG` 와 `RAG` 는 점수가 높게 나오지만(86) 다른 모델이므로 막아야 한다.

**4단계 embedding 병합.** alias·fuzzy 가 못 잡는 의미 중복을 임베딩 코사인 유사도로 잡는다. `Knowledge Graph` ~ `KG` 처럼 표기가 전혀 달라도 뜻이 같은 경우다. 백엔드는 셋 중 하나를 고른다. 기본은 키가 필요 없는 mock(해시 기반 결정적 벡터), 상용은 VoyageAI `voyage-3.5`, 비용 0 로컬은 `bge-m3`.

```python
# practice/resolve_entities.py — 1단계 alias 병합의 핵심
def normalize(name: str) -> str:
    """표면형을 비교용 키로. NFKC → 소문자 → 하이픈·언더스코어→공백 → 공백 압축."""
    s = unicodedata.normalize("NFKC", name).strip().lower()
    s = re.sub(r"[-_]+", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s

def stage_alias(entities: list[Entity]) -> list[MergePair]:
    pairs, seen = [], {}
    for idx, e in enumerate(entities):
        keys = {normalize(e.name)} | {normalize(a) for a in e.aliases}
        matched = next((seen[(k, e.type.value)] for k in keys if (k, e.type.value) in seen), None)
        if matched is not None:
            pairs.append(MergePair(matched, idx, "alias"))
        for k in keys:
            seen.setdefault((k, e.type.value), idx)  # type 이 다르면 다른 키
    return pairs
```

`(키, type)` 를 함께 쓰는 게 중요하다. Model `RAG` 와 (가상의) Concept `rag` 는 정규화 키가 같아도 type 이 달라 묶이지 않는다. type 불일치는 모든 단계에서 가장 강한 가드다.

## 3. substring 가드 — Self-RAG·CRAG 를 RAG 에서 떼어 놓기

이 토픽에서 가장 위험한 코드다. `RAG` 는 `Self-RAG`·`CRAG`·`Adaptive RAG` 의 부분문자열이지만 전부 다른 모델이다. fuzzy 점수만 보면 임계값을 조금만 낮춰도 이들이 `RAG` 로 새어 들어간다.

함정을 명시적으로 잡아 후보에서 뺀다. 두 가지 모양을 본다.

```python
# practice/resolve_entities.py — substring 함정 가드
def _is_substring_trap(a: str, b: str) -> bool:
    sa, sb = sorted([a, b], key=len)   # sa = 짧은 쪽, sb = 긴 쪽
    if sa == sb:
        return False
    tb = sb.split(" ")
    # 1) 'rag' 가 토큰 {'self','rag'} 의 독립 토큰이고 긴 쪽이 토큰을 더 가짐 → 함정
    if " " not in sa and sa in tb and len(tb) > 1:
        return True
    # 2) 'rag' 가 'crag'·'selfrag' 에 붙어서 들어 있음(독립 토큰 아님) → 함정
    if sa in sb and sa not in tb:
        return True
    return False
```

`Self-RAG`(정규화 `self rag`)는 모양 1에 걸린다 — `rag` 가 독립 토큰인데 `self` 가 덧붙었다. `CRAG`(`crag`)는 모양 2에 걸린다 — `rag` 가 `crag` 안에 붙어 있다. 둘 다 함정으로 판정돼 fuzzy·embedding 후보에서 빠진다.

반대로 `Light RAG`(`light rag`) ~ `LightRAG`(`lightrag`)는 함정이 아니다. `light rag` 는 `lightrag` 의 부분문자열이 아니고, `rag` 도 `lightrag` 안의 독립 토큰이 아니다. 그래서 함정을 통과해 fuzzy 가 정상 병합한다. 합칠 건 합치고 뗄 건 뗀다 — 이 한 줄짜리 함수가 그 경계를 긋는다.

## 4. 실습 — 4단계를 묶고 canonical 로 재배선

각 단계는 "병합 후보 쌍"의 집합을 낸다. 네 단계를 다 돌린 뒤 모든 쌍을 **Union-Find(Disjoint Set)** 로 연결요소(클러스터)로 묶는다. 같은 클러스터에 든 표면형은 전부 한 개체다.

```python
# practice/resolve_entities.py — 쌍을 클러스터로, 클러스터에서 canonical 로
def cluster_entities(entities, pairs):
    uf = UnionFind(len(entities))
    for p in pairs:
        uf.union(p.i, p.j)                 # 후보 쌍을 전부 union
    clusters = []
    for _, idxs in uf.clusters().items():
        members = [entities[i] for i in idxs]
        canon = select_canonical(members)  # 빈도 → 길이 → 최초 등장
        cid = f"ent-{canon.type.value.lower()}-{_slug(canon.name)}"
        clusters.append(Cluster(cid, canon.name, canon.type.value, ...))
    return clusters
```

canonical 선정 규칙은 빈도 우선이다. 코퍼스가 가장 많이 쓰는 표기가 대표가 돼야 Neo4j 적재·GraphRAG 인용에서 자연스럽다. `LightRAG`(5회)가 `Light RAG`(1회)를 이긴다. 동률이면 더 긴(완전한) 표기를 택한다. 대표가 정해지면 나머지 표면형은 alias 로 흡수하고, 안정 `canonical_id`(`ent-{type}-{slug}`)를 붙인다.

마지막으로 관계를 다시 배선한다. `merge_map`(원본 표면형 → canonical 이름)으로 모든 relation 의 head/tail 을 바꾼다. `(Light RAG)-[USES]->(Neo4J)` 가 `(LightRAG)-[USES]->(Neo4j)` 가 된다.

```bash
python run_resolve.py        # mock 임베딩, 시연용 sample 입력 (키 불필요)
```

> 전체 코드와 실행 절차는 [`practice/`](practice/) 와 [`labs/`](labs/) 참조.
> 비용을 줄이려면 임베딩 백엔드를 `bge-m3`(로컬)로 바꾼다(`--embedding-backend local`). 결과 품질은 떨어질 수 있으나 파이프라인은 동일하게 동작한다.

## 5. 결과 해석

`run_resolve.py` 를 mock 으로 돌리면 다음이 찍힌다.

```
병합 결과: 19 엔티티 → 10 canonical (병합된 클러스터 4개)

병합 그룹(멤버 2개 이상):
  [Model] LightRAG  ←  {Light RAG, LightRAG, LightRag}  (빈도 5)  id=ent-model-lightrag
  [Tool]  Neo4j     ←  {Neo4J, Neo4j}                   (빈도 2)  id=ent-tool-neo4j

오병합 가드 확인 (서로 다른 canonical 이어야 정상):
  RAG        → RAG
  Self-RAG   → Self-RAG
  CRAG       → CRAG
  판정: PASS — Self-RAG·CRAG 가 RAG 로 안 합쳐졌다
```

여기서 세 가지를 읽는다. 첫째, `LightRAG` 클러스터가 표기 흔들림 셋(`LightRAG`/`Light RAG`/`LightRag`)을 다 흡수했다 — alias·fuzzy 가 일했다. 둘째, `Neo4J` 가 `Neo4j` 로 정규화돼 묶였다. 셋째, `RAG`·`Self-RAG`·`CRAG` 가 각자 따로 남았다 — substring 가드가 일했다.

`embedding` 단계가 0쌍인 건 정상이다. mock 임베딩은 의미를 모른다(같은 표면형이면 같은 벡터, 다르면 거의 직교). 1·2단계가 이미 잡은 것 외에 추가 병합이 안 난다. 의미 병합의 진짜 효과는 `voyage`·`local` 백엔드에서 본다. mock 은 키 없이 파이프라인 구조를 먼저 익히게 하려는, 의도된 한계다.

이제 `validate_resolution.py` 가 네 가지를 검증한다. (a) 한 canonical 에 type 이 하나만 — 서로 다른 type 이 섞이지 않았다. (b) `Self-RAG`·`CRAG`·`RAG` 가 서로 다른 canonical — 오병합 회귀 테스트. (c) `merge_map` 이 1:1 함수 — 한 표면형이 정확히 하나의 canonical 로. (d) dangling 없음 — `relations.resolved` 의 head/tail 이 전부 canonical 집합 안에. 전부 PASS 면 다음 토픽으로 넘어갈 자격이 생긴다.

산출물 셋(`canonical_entities.jsonl`·`merge_map.json`·`relations.resolved.jsonl`)이 2/05(관계 정규화·Event 모델링)와 2/06(품질 게이트·증분 적재)의 입력이다.

---

## 🚨 자주 하는 실수

1. **substring 만 보고 합친다** — `RAG` 가 `Self-RAG`·`CRAG` 안에 있다고 같은 개체로 합치면 거짓 사실이 생긴다("RAG 가 RAG 를 개선한다"). 부분문자열 포함은 동일성의 근거가 아니다. type 일치·단어경계·임계값을 함께 걸고, substring 가드로 명시적으로 막아라. labs 5단계에서 `--no-substring-guard` 로 `CRAG`→`RAG` 오병합을 일부러 재현한 뒤 가드로 막아 본다.
2. **fuzzy 임계값을 낮춰 재현율을 욕심낸다** — 임계값을 내리면 표기 흔들림은 더 잡지만, 닮은 다른 개체까지 빨려 들어온다. `token_sort_ratio` 90 아래로 내리면 `RAG`·`GraphRAG`·`CRAG` 가 서로 섞이기 시작한다. 정제는 재현율보다 정밀도다 — 잘못 합친 노드는 되돌리기 어렵다. 보수적으로 시작해 reject 를 보며 천천히 푼다.
3. **병합하고 검증을 건너뛴다** — ER 은 그래프에 비가역적으로 손을 댄다. 합친 뒤 검증하지 않으면 오병합이 그대로 Neo4j 까지 흘러간다. `validate_resolution.py` 의 오병합 가드·dangling 검사를 회귀 테스트로 고정하고, 새 데이터를 넣을 때마다 돌려라. 통과 못 하면 적재하지 않는다.

## 출처

- Pydantic Structured Output — https://docs.pydantic.dev/
- Graph RAG Survey (Construction) — arXiv 2408.08921, https://arxiv.org/abs/2408.08921
- rapidfuzz (문자열 유사도) — https://github.com/rapidfuzz/RapidFuzz
- VoyageAI Embeddings (`voyage-3.5`) — https://docs.voyageai.com/docs/embeddings
- BAAI/bge-m3 (로컬 임베딩 대안) — https://huggingface.co/BAAI/bge-m3

## 다음 토픽

→ [관계 정규화·이벤트 모델링](../05-relation-normalization-events/lesson.md)
