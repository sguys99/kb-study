# 4.7 LightRAG Indexing · WebUI · 5모드 A/B

> **Phase 4 · 토픽 07** · 06에서 개념으로 묶었던 5모드를 실제로 돌린다. 러닝 코퍼스를 LightRAG로 한 번 인덱싱하고, 같은 골든 질문을 `naive/local/global/hybrid/mix`로 던져 WebUI로 들여다본다. 그리고 Phase 1 Baseline(=naive) 대비 멀티홉·전체요약이 얼마나 나아지는지를 수치로 본다.

## 학습 목표

이 토픽을 끝내면 다음을 할 수 있다.

- LightRAG를 설치하고 러닝 코퍼스(AI/LLM 기술 문서)를 `ainsert`로 인덱싱해, 청킹·엔티티/관계 추출·KG+벡터 저장이 한 번에 끝나는 파이프라인을 직접 돌린다.
- 같은 골든 질문 셋을 5모드 `naive/local/global/hybrid/mix`로 `aquery`해 답과 인용을 표/JSON으로 비교한다.
- API 서버를 띄워 `http://localhost:9621/webui`에서 그래프와 검색 경로를 시각화하고, 무prefix 기본(`hybrid`)과 Core 직접 호출 기본(`mix`)의 차이를 손으로 확인한다.
- multi-hop·global-summary 질문에서 `local/global/mix`가 `naive`(=Phase 1 Baseline)보다 나은 답을 내는지 정량으로 판정한다.

**완료 기준**: WebUI에서 같은 질문을 5모드로 던져 그래프·검색 경로가 보이고, multi-hop·global-summary 질문에서 `local/global/mix`가 `naive`(=Phase 1 Baseline)보다 나은 답을 내면 완료.

---

## 1. 왜 인덱싱을 실제로 돌리나

06은 다리만 놓았다. 4.2~4.5에서 손으로 짠 네 전략이 LightRAG의 다섯 모드 이름으로 그대로 옮겨 간다는 것, `naive`가 Phase 1 Baseline이고 `mix`가 융합의 완성형이라는 것까지. 거기서 멈췄다. 모드 선택기는 키 없이 결정론적으로 돌았지만, 실제 답은 한 줄도 만들어 보지 않았다.

이제 진짜로 돌린다. 06의 표는 "이 모드가 이런 질문에 강할 것"이라는 가설이다. 가설을 검증하려면 같은 코퍼스를 인덱싱하고, 같은 질문을 다섯 갈래로 던져 답을 눈으로 대조해야 한다. 특히 확인하고 싶은 건 하나다. 멀티홉과 전체요약에서, KG를 쓰는 모드가 정말 Baseline 벡터 RAG보다 나은가.

확인 방법은 06에서 이미 정해 뒀다. 한 번 인덱싱하면 다섯 모드가 같은 저장소를 공유하니, A/B는 질문을 고정하고 `mode`만 바꾸는 루프다. 인덱싱은 한 번, 질의는 다섯 번. 이게 07의 골격이다.

## 2. LightRAG 인덱싱 파이프라인 — `ainsert` 한 번이 전부다

직접 짤 때를 떠올려 보자. 청킹하고, 임베딩하고, LLM으로 엔티티·관계를 뽑고, 그래프에 넣고, 벡터 인덱스를 따로 만들었다. 단계마다 따로 코드를 짰다. LightRAG는 이걸 `ainsert` 한 호출로 묶는다.

```
ainsert(text)
  → 청킹
  → LLM이 엔티티·관계 추출
  → KG 저장(엔티티·관계)
  → 벡터 저장(청크·엔티티 임베딩)
```

여기서 핵심은 **저장소가 하나로 합쳐진다**는 점이다. KG와 벡터가 같은 `working_dir` 아래 함께 쌓인다. 그래서 인덱싱이 끝나면 다섯 모드가 같은 데이터를 본다. `naive`는 벡터 쪽만, `local`은 엔티티 이웃을, `global`은 커뮤니티를, `mix`는 KG+벡터를 함께 — 전부 같은 인덱스 위에서 갈래만 다를 뿐이다.

Core 호출의 모양은 06에서 미리 본 그대로다. 한 가지만 다시 강조한다. `initialize_storages()`를 빠뜨리면 안 된다.

```python
# practice/index_corpus.py 의 핵심 — 본 과정 기본 스택(Claude + VoyageAI)
rag = LightRAG(
    working_dir="./rag_storage",
    llm_model_func=llm_model_func,        # Claude (anthropic). 비용0 분기는 Ollama로 교체
    embedding_func=embedding_func,         # VoyageAI voyage-3.5. 비용0 분기는 bge-m3
)
await rag.initialize_storages()            # REQUIRED — 빠뜨리면 AttributeError: __aenter__
for path, text in load_corpus("./corpus"):
    await rag.ainsert(text, file_paths=path)   # 청킹→추출→KG+벡터 저장이 한 번에
await rag.finalize_storages()
```

LLM과 임베딩은 함수 두 개를 갈아 끼우면 백엔드가 바뀐다. 기본은 Claude + VoyageAI(`voyage-3.5`)다. 비용이 부담되면 LLM을 Ollama로, 임베딩을 `bge-m3`로 바꾼다. 그러면 키 없이 로컬에서 돌고, 파이프라인 모양은 같은 채 품질만 달라진다. 키는 `.env`/`os.environ`에서 읽고, 절대 하드코딩하지 않는다.

> 전체 코드와 실행 절차는 [`practice/`](practice/) 와 [`labs/`](labs/) 참조.

## 3. 5모드 A/B — 질문은 고정, 모드만 바꾼다

인덱싱이 끝났으면 A/B는 단순하다. 골든 질문을 type별로 몇 개 고정해 두고, 각 질문을 다섯 모드로 던진다.

```python
# practice/ab_query_modes.py 의 핵심
MODES = ["naive", "local", "global", "hybrid", "mix"]   # 영문 소문자 고정

for q in golden_questions:
    for mode in MODES:
        answer = await rag.aquery(
            q["question"],
            param=QueryParam(
                mode=mode,
                top_k=60,            # KG 엔티티/관계 상한
                chunk_top_k=20,      # 텍스트 청크 상한
                enable_rerank=True,  # mix는 reranker와 함께 권장
            ),
        )
```

`QueryParam`의 `mode`만 바꾸고 나머지는 그대로 둔다. 그래야 모드 차이만 깨끗하게 비교된다. `top_k`는 KG에서 끌어올 엔티티·관계 상한, `chunk_top_k`는 텍스트 청크 상한이다. `enable_rerank`는 가져온 근거를 재순위화하는데, `mix`는 reranker와 함께 쓸 때 효과가 가장 크다(리랭커가 없으면 `RERANK_BINDING`이 비어 있어 무시되니, 있으면 켠다).

**Core 코드로 직접 부를 때 권장 기본은 `mix`다.** 06에서 예고한 함정이 여기서 실제로 갈린다 — 잠시 뒤 WebUI 절에서 다시 짚는다.

## 4. API 서버 + WebUI — 그래프와 검색 경로를 본다

답만 보면 "왜 이 답이 나왔나"를 알 수 없다. 어떤 엔티티를 거쳐 어떤 청크를 끌어왔는지, 그 경로를 봐야 모드 차이가 손에 잡힌다. 그래서 API 서버를 띄우고 WebUI로 들여다본다.

설치는 `[api]` extra가 붙는다. Core만 쓸 땐 `lightrag-hku`, API 서버·WebUI까지면 `lightrag-hku[api]`다.

```bash
pip install "lightrag-hku[api]"
lightrag-server        # 기본 PORT 9621
```

Docker로 띄워도 된다. `practice/docker-compose.yml`을 두었다.

```bash
docker compose up -d
curl http://localhost:9621/health      # {"status":"healthy",...}
```

헬스체크가 통과하면 브라우저에서 `http://localhost:9621/webui`로 들어간다. 문서를 업로드해 인덱싱하고, 같은 질문을 5모드로 던지고, 그래프를 시각적으로 돌려볼 수 있다. multi-hop 질문을 `local`로 던지면 질문에 걸린 엔티티에서 이웃으로 뻗는 경로가 보이고, `global`로 던지면 커뮤니티 단위로 묶인 요약이 보인다. 같은 질문이라도 갈래가 다르다는 게 화면에서 드러난다.

여기서 06의 함정이 실제로 터진다. **WebUI/API 서버에서 쿼리 문자열에 prefix를 안 붙이면 기본이 `hybrid`다.** prefix는 `/local /global /hybrid /naive /mix`(+ `/...context`로 검색 컨텍스트만, `/bypass`로 검색 없이). 그러니까 같은 질문이라도 Core 코드로 부르면 `mix`로, WebUI에서 prefix 없이 던지면 `hybrid`로 답이 나온다. 둘을 같은 거라 뭉뚱그리면 "왜 답이 다르지?"로 헤맨다. WebUI에서 `mix`로 보고 싶으면 질문 앞에 `/mix`를 붙인다.

```
/local  Neo4j와 RAG는 어떻게 이어지나?       ← local 모드로 강제
/global 이 코퍼스의 GraphRAG 흐름을 요약해줘.   ← global 모드로 강제
        (prefix 없으면 hybrid)
```

## 5. 결과 해석 — Baseline(naive) 대비 무엇이 좋아졌나

`ab_query_modes.py`는 질문 × 모드 표를 JSON과 콘솔로 찍는다. 읽는 기준은 06의 가설 그대로다. simple-fact는 `naive`로 충분한가, multi-hop은 `local`이 더 나은가, global-summary는 `global`이 코퍼스를 더 잘 조망하는가.

예상되는 그림은 이렇다. simple-fact("VoyageAI 기본 임베딩 모델 이름은?")는 `naive`도 정답을 낸다 — 답이 한 청크에 통째로 들어 있으니 KG가 없어도 된다. 그런데 multi-hop("Neo4j와 RAG는 어떻게 이어지나?")로 가면 `naive`는 한 청크 안에서 답을 못 찾고 흐릿해진다. 두세 엔티티를 거쳐야 하는데 벡터검색은 그 다리를 못 놓는다. `local`은 엔티티 이웃을 따라가 관계를 끌어온다. global-summary("이 코퍼스의 GraphRAG 연구 흐름을 전체 요약해줘")는 차이가 더 크다. `naive`는 상위 몇 청크만 보고 부분 요약에 그치지만, `global`은 커뮤니티 요약을 모아 전체를 조망한다.

```
question(type)              naive   local   global  hybrid  mix
--------------------------------------------------------------------
임베딩 모델 이름(simple-fact)   ✓       ✓       △       ✓       ✓
Neo4j↔RAG(multi-hop)         △       ✓       △       ✓       ✓
GraphRAG 흐름(global-summary)  △       △       ✓       ✓       ✓
```

판정의 핵심은 한 줄이다. **`naive`(=Phase 1 Baseline)가 simple-fact에선 멀쩡한데 multi-hop·global-summary에서 무너지고, 그 자리를 `local/global/mix`가 메운다면, KG를 도입한 값을 한 것이다.** `mix`가 type을 가리지 않고 가장 견고하게 나오는 것도 확인 포인트다. 4.5에서 Hybrid가 type을 가로질러 살아남았던 결론이 LightRAG 위에서 재현되는지를 보는 셈이다.

수치는 코퍼스·모델·질문에 따라 달라진다. 절대값이 아니라 **모드 간 상대 우열**을 본다. 정답 채점은 다음 단계(Phase 6)에서 Ragas로 자동화한다. 07에서는 답과 인용을 눈으로 대조하는 수준으로 충분하다.

---

## 🚨 자주 하는 실수

1. **WebUI 무prefix 기본을 `mix`로 착각한다.** Core 코드로 `aquery`하면 권장 기본이 `mix`지만, API 서버/WebUI에서 prefix 없이 질문하면 기본은 `hybrid`다. `mix`로 보고 싶으면 질문 앞에 `/mix`를 붙여야 한다. 이걸 모르면 Core로 본 답과 WebUI로 본 답이 달라 "버그인가" 하고 헤맨다.
2. **인덱싱마다 새로 다 만든다고 생각한다.** `ainsert`는 청킹·엔티티/관계 추출·KG 저장·벡터 저장을 한 번에 끝낸다. 다섯 모드는 그 하나의 저장소를 공유한다. 모드를 바꾼다고 다시 인덱싱할 필요가 없다 — 인덱싱은 한 번, 질의만 다섯 번이다. (재인덱싱·증분 적재·삭제 운영은 08에서 다룬다.)
3. **`initialize_storages()`를 빠뜨린다.** Core를 직접 부를 때 `LightRAG(...)` 생성 직후 `await rag.initialize_storages()`를 호출하지 않으면 `AttributeError: __aenter__`로 죽는다. 저장 백엔드가 초기화되기 전에 `ainsert/aquery`를 부른 탓이다. 생성 → `initialize_storages` → 작업 → `finalize_storages` 순서를 지킨다.

## 출처

- LightRAG (HKUDS) — https://github.com/HKUDS/LightRAG
- LightRAG API Server·WebUI — https://github.com/HKUDS/LightRAG/blob/main/docs/LightRAG-API-Server.md
- Microsoft GraphRAG Docs — https://microsoft.github.io/graphrag/
- *From Local to Global: A Graph RAG Approach to Query-Focused Summarization*, arXiv 2404.16130 — https://arxiv.org/abs/2404.16130
- Awesome-GraphRAG (DEEP-PolyU) — https://github.com/DEEP-PolyU/Awesome-GraphRAG

## 다음 토픽

→ [08-lightrag-neo4j-ops](../08-lightrag-neo4j-ops/lesson.md)
