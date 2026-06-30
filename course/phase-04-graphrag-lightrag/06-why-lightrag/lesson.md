# 4.6 왜 LightRAG인가 — 본 과정의 Main Framework와 5가지 Query Mode

> **Phase 4 · 토픽 06** · 4.2~4.5에서 손으로 짠 네 리트리버를, 매번 다시 짜는 대신 한 프레임워크로 받는다. LightRAG의 다섯 쿼리 모드가 그 자리에 1:1로 들어맞는 지점을 본다.

## 학습 목표

이 토픽을 끝내면 다음을 할 수 있다.

- LightRAG 5모드 `naive / local / global / hybrid / mix`를 각각 4.2~4.5의 직접 구현(Vector / Local·Path / Global / Fusion)과 1:1로 대응시켜 설명한다.
- `naive`가 Phase 1 Baseline에, `mix`가 Vector+Graph Fusion의 완성형에 대응함을 짚고, Core 권장 기본(mix)과 API 서버 무prefix 기본(hybrid)의 차이를 구분한다.
- 질문 type(`simple-fact / multi-hop / global-summary`)을 받아 권장 모드를 고르는 모드 선택기를 키 없이 결정론적으로 돌린다.
- LightRAG Core 최소 호출(`initialize_storages → ainsert → aquery(mode=...)`)의 모양을 읽고, 07에서 실제로 돌릴 준비를 한다.

**완료 기준**: 모드 선택기가 simple-fact→naive·multi-hop→local·global-summary→global을 결정론적으로 고르고, 5모드를 4.2~4.5의 직접 구현과 1:1로 대응시켜 설명할 수 있으면 완료.

---

## 1. 왜 프레임워크인가

4.2부터 4.5까지 학습자는 검색기를 직접 짰다. Local·Path로 엔티티 이웃을 긁고, Global로 커뮤니티 요약을 모으고, 4.4에서 Vector와 그래프 근거를 RRF로 융합하고 재순위까지 붙였다. 4.5에서는 그 넷을 같은 골든 질문 위에 세워 type별로 채점했다. 결론은 분명했다. Vector는 simple-fact에서, Local은 멀티홉에서, Global은 전체요약에서 각자 강했고, 셋 중 하나만으로는 type을 가로지르지 못했다. Hybrid만 살아남았다.

직접 짜 봤기 때문에 이제 안다. 검색 패턴 하나하나가 어떻게 도는지, 어디서 무너지는지. 그런데 매번 손으로 RRF를 짜고 토큰 예산을 맞추고 재순위 백엔드를 갈아 끼우는 건 학습용이지 운영용이 아니다. 인덱싱·저장·다섯 검색 경로·WebUI를 한 번에 묶어 주는 도구가 있으면, 우리가 4.2~4.5에서 배운 패턴을 그대로 쓰면서 반복 노동만 덜 수 있다.

그 도구가 LightRAG다. 핵심은 새 개념을 배우는 게 아니라는 것이다. **이미 만든 네 전략이 LightRAG의 모드 이름으로 그대로 옮겨 간다.** 06은 그 다리를 놓는다. 07에서 실제로 인덱싱해 5모드를 WebUI로 A/B하고, 08에서 Neo4j 백엔드로 운영한다.

## 2. 5모드 — 직접 구현과의 1:1 대응

LightRAG는 한 번 인덱싱한 그래프·벡터 저장소 위에서 다섯 갈래로 검색한다. 이름만 보면 새것 같지만, 4.2~4.5에서 만든 것과 거의 그대로 맞붙는다.

| mode | 무엇을 검색에 쓰나 | 대응(직접 구현) |
|------|------------------|----------------|
| `naive` | KG 없이 텍스트 청크 벡터검색만. 전통 RAG. | 4.1~4.5 Vector-only / **Phase 1 Baseline**(벡터 측) |
| `local` | 엔티티 중심. 로컬 문맥·이웃을 정밀 매칭. | 4.2 Local·Path Retriever |
| `global` | 커뮤니티 기반. 거시 주제·교차문서 추론. | 4.3 Global Retriever (Leiden·Map-Reduce) |
| `hybrid` | local + global 병합. | 4.4~4.5 Hybrid의 그래프 측 |
| `mix` | KG 검색 + vector 검색 통합. reranker와 함께 권장. | 4.4 Vector+Graph Fusion의 **완성형** |

두 칸만 기억하면 된다. `naive`는 Phase 1 Baseline이다 — KG를 안 쓰는 순수 벡터 RAG라서, 이후 모든 개선의 기준선이 곧 이 모드다. `mix`는 4.4에서 만든 융합 파이프라인의 완성형이다 — KG와 vector를 함께 검색해 묶는다. 4.5에서 Hybrid가 type을 가로질러 살아남았듯, `mix`도 type을 가리지 않고 가장 견고하다. 그래서 LightRAG Core README가 권장하는 기본 모드가 `mix`다.

여기서 헷갈리기 쉬운 디테일이 하나 있다. **기본 모드가 문맥에 따라 둘로 갈린다.** Core를 코드로 직접 부를 때 권장 기본은 `mix`다. 그런데 API 서버를 띄워 쓸 때, 쿼리 문자열 앞에 `/local /global /hybrid /naive /mix` 같은 prefix를 붙이지 않으면 서버 기본은 `hybrid`다. 둘을 같은 것으로 뭉뚱그리면 07에서 "왜 내 답이 기대와 다르지?"로 헤맨다.

## 3. 실습 — 모드 메타와 선택기

06은 LightRAG를 실제로 설치·인덱싱하지 않는다(그건 07). 대신 두 가지를 키 없이 결정론적으로 돌린다. 5모드의 의미·대응을 표로 찍고, 질문 type을 받아 권장 모드를 고른다. 둘 다 표준 라이브러리만 쓰므로 과금이 0이다.

먼저 5모드를 메타 사전으로 들고 표로 출력한다.

```python
# practice/query_modes.py 의 핵심 — 표준 라이브러리만
@dataclass(frozen=True)
class ModeSpec:
    mode: str          # naive / local / global / hybrid / mix (영문 소문자 고정)
    meaning: str       # 무엇을 검색에 쓰는지
    maps_to: str       # 4.2~4.5의 어떤 직접 구현에 대응하는가
    use_when: str      # 어떤 질문 type에 강한가

DEFAULT_CORE = "mix"            # Core README 권장 기본
DEFAULT_API_SERVER = "hybrid"  # API 서버 무prefix 기본
```

선택기는 4.5에서 갈린 결론을 규칙으로 굳힌 것이다. simple-fact는 `naive`, multi-hop은 `local`, global-summary는 `global`. type을 모르거나 섞였다고 보면 가장 견고한 `mix`로 떨군다.

```python
# practice/mode_selector.py 의 핵심
TYPE_TO_MODE = {
    "simple-fact": "naive",
    "multi-hop": "local",
    "global-summary": "global",
}
FALLBACK_MODE = "mix"  # type을 못 가리거나 섞이면 기본·권장으로

def select_mode(question, qtype=None):
    # 라벨이 있으면 그대로 매핑(권장 경로). 없으면 휴리스틱으로 type 추정.
    resolved = qtype if qtype else guess_type(question)
    return resolved, TYPE_TO_MODE.get(resolved, FALLBACK_MODE)
```

휴리스틱은 정밀한 분류기가 아니다. "전체·요약·한눈에" 같은 약한 신호로 type을 추정하는 보조 수단일 뿐이고, 라벨이 있으면 라벨이 이긴다. 운영에서는 4.5의 type 라벨이나 LLM 분류기를 앞에 두는 게 맞다.

> 전체 코드와 실행 절차는 [`practice/`](practice/) 와 [`labs/`](labs/) 참조.

07에서 실제로 돌릴 Core 호출의 모양은 이렇다. 한 번 인덱싱하면 다섯 모드가 같은 저장소를 공유하므로, A/B는 질문은 고정하고 `mode`만 바꾸는 루프가 된다.

```python
# practice/lightrag_quickstart.py — 06에서 실행하지 않는다(07에서 실행)
rag = LightRAG(working_dir="./rag_storage",
               llm_model_func=gpt_4o_mini_complete,  # 기본 스택은 Claude/Voyage로 교체
               embedding_func=openai_embed)
await rag.initialize_storages()   # REQUIRED — 빠뜨리면 AttributeError: __aenter__
await rag.ainsert("...", file_paths="intro.txt")
for mode in ["naive", "local", "global", "hybrid", "mix"]:
    answer = await rag.aquery("질문", param=QueryParam(mode=mode, top_k=60, chunk_top_k=20))
```

본 과정 기본 스택은 Claude + VoyageAI(`voyage-3.5`)다. 비용이 부담되면 임베딩을 `bge-m3`, LLM을 Ollama로 바꿔 `llm_model_func`/`embedding_func`만 교체하면 된다. 파이프라인 모양은 같고 품질만 달라진다.

## 4. 결과 해석

`python3 query_modes.py`는 5모드 대응표를 찍고, 끝에 두 줄을 박는다. 하나는 기본 모드가 문맥에 따라 mix·hybrid로 갈린다는 사실. 다른 하나는 손으로 짠 네 전략이 곧 네 모드라는 메시지다. 06의 결론은 이 두 줄이다.

`python3 mode_selector.py`는 예시 질문 8개에 모드를 붙인다.

```
VoyageAI의 기본 임베딩 모델 이름은?      simple-fact     naive    label
Neo4j와 RAG는 어떻게 이어지나?           multi-hop       local    label
이 코퍼스의 GraphRAG 연구 흐름을 전체 요약해줘.  global-summary  global   label
LightRAG와 Microsoft GraphRAG는 어떻게 이어지나?  multi-hop  local  heuristic
```

읽는 법은 이렇다. 라벨이 달린 질문 6개는 매핑 규칙대로 곧장 떨어진다 — simple-fact는 `naive`(4.5에서 Vector가 만점이던 자리), multi-hop은 `local`(Local이 1.000이던 자리), global-summary는 `global`(Community가 1.000이던 자리). 라벨이 없는 마지막 두 질문은 `heuristic` 경로로 type을 추정한 뒤 같은 매핑을 탄다. "어떻게 이어지나"는 관계 신호로 잡혀 `local`, "전체 요약해줘"는 거시 신호로 잡혀 `global`이 된다.

핵심은 선택기가 정답을 보장하지는 않는다는 데 있다. 이건 4.5의 type별 우열을 모드 선택 규칙으로 옮긴 것이고, 실제 질문이 type을 넘나들면 단일 모드보다 `mix`가 안전하다. 그래서 가릴 수 없을 때 `mix`로 떨어진다. 07에서 이 직관을 실제 LightRAG 답변으로 검증한다.

---

## 🚨 자주 하는 실수

1. **`mix`와 `hybrid`를 같은 것으로 본다.** `hybrid`는 local+global의 그래프 측 병합이고, `mix`는 거기에 vector 검색까지 통합한 완성형이다. 게다가 기본 모드도 갈린다 — Core 권장 기본은 `mix`, API 서버 무prefix 기본은 `hybrid`다. 07에서 prefix를 빠뜨리면 의도와 다른 모드로 답이 나온다.
2. **`naive`를 "성능 낮은 버전"으로 오해한다.** `naive`는 KG를 안 쓰는 순수 벡터 RAG, 곧 Phase 1 Baseline이다. 못난 모드가 아니라 simple-fact에서는 오히려 강하고, 무엇보다 모든 개선의 비교 기준선이다. naive를 빼고 A/B하면 "얼마나 좋아졌나"를 말할 잣대가 사라진다.
3. **모드 선택기를 정답 분류기로 착각한다.** 선택기는 4.5의 type별 우열을 규칙으로 굳힌 휴리스틱일 뿐이다. type이 섞인 질문에 단일 모드를 강제하면 한쪽 근거를 놓친다. 가릴 수 없으면 `mix`로 두는 게 안전하고, type 분류 자체는 라벨이나 LLM 분류기에 맡기는 게 맞다.

## 출처

- LightRAG (HKUDS) — https://github.com/HKUDS/LightRAG
- LightRAG API Server·WebUI — https://github.com/HKUDS/LightRAG/blob/main/docs/LightRAG-API-Server.md
- Microsoft GraphRAG Docs — https://microsoft.github.io/graphrag/
- *From Local to Global: A Graph RAG Approach to Query-Focused Summarization*, arXiv 2404.16130 — https://arxiv.org/abs/2404.16130
- Awesome-GraphRAG (DEEP-PolyU) — https://github.com/DEEP-PolyU/Awesome-GraphRAG

## 다음 토픽

→ [07-lightrag-indexing-webui](../07-lightrag-indexing-webui/lesson.md)
