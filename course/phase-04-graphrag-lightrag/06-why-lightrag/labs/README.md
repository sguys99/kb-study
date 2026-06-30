# Lab 4.6 — LightRAG 5모드 대응표와 모드 선택기 (키 0)

06은 개념·선택 기준 토픽이다. 여기서는 LightRAG를 실제로 설치·인덱싱하지 않는다(그건 07).
대신 5모드의 의미·대응을 표로 찍어 보고, 질문 type → 권장 모드를 결정론적으로 골라 본다.
모두 표준 라이브러리만 쓰므로 키·네트워크·과금이 없다.

전제: Python 3.11+. 설치할 패키지 없음.

---

## 0단계 — 위치 확인

```bash
cd course/phase-04-graphrag-lightrag/06-why-lightrag/practice
ls
```

예상 출력:

```
lightrag_quickstart.py  mode_selector.py  query_modes.py  requirements.txt
```

---

## 1단계 — 5모드 대응표 출력

같은 그래프에서 5모드가 각각 무엇을 검색에 쓰는지, 4.2~4.5의 직접 구현과 어떻게 1:1로 대응하는지 표로 확인한다.

```bash
python3 query_modes.py
```

예상 출력:

```
=== LightRAG 5 Query Mode 대응표 ===

mode    의미                                                  대응(직접 구현)                                                 언제 쓰나                                        
-------------------------------------------------------------------------------------------------------------------------------------------------------------------
naive   KG 없이 텍스트 청크 벡터검색만. 전통 RAG 그대로.                     4.1~4.5 Vector-only / Phase 1 Baseline(Hybrid RAG의 벡터 측)  simple-fact (답이 한 청크에 통째로 들어 있는 단순 사실)       
local   엔티티 중심. 질문에 걸리는 엔티티의 로컬 문맥·이웃을 정밀 매칭.               4.2 Local·Path Retriever                                  multi-hop (두세 엔티티를 거쳐야 답이 나오는 관계 질문)         
global  커뮤니티 기반. 거시 주제·교차문서 추론을 위해 커뮤니티 요약을 모은다.            4.3 Global Retriever (Leiden Community·Map-Reduce 요약)     global-summary (코퍼스 전체를 조망해야 하는 요약 질문)       
hybrid  local + global 병합. 엔티티 정밀도와 커뮤니티 거시 시야를 함께 본다.      4.4~4.5 Hybrid의 그래프 측 (local+global 결합)                   multi-hop과 global-summary가 섞인 질문             
mix     KG 검색 + vector 검색 통합(세 검색 타입 결합). reranker와 함께 권장.  4.4 Vector+Graph Fusion의 완성형 (RRF·Rerank까지)               기본·권장 모드. type을 가리지 않고 가장 견고. naive보다 지연 약간 ↑

[기본 모드] Core README 권장 기본 = mix, API 서버 무prefix 기본 = hybrid
[메시지] 4.2~4.5에서 손으로 짠 vector_only/local/global/hybrid가 곧 LightRAG의 naive/local/global/hybrid 모드다.
         LightRAG는 거기에 KG+vector를 통합한 mix를 더해 다섯 모드를 한 프레임워크로 제공한다.
```

대조 포인트: `naive`가 Phase 1 Baseline(벡터 측)에 대응하고, `mix`가 Core 권장 기본이라는 두 줄이 보이면 통과.

---

## 2단계 — 질문 type → 모드 선택기

4.5에서 갈린 결론(simple-fact는 Vector, multi-hop은 Local, global-summary는 Global이 강하다)을 그대로 규칙으로 굳혀, 질문마다 권장 모드를 고른다. 라벨이 있으면 매핑으로, 없으면 휴리스틱으로 type을 추정한 뒤 같은 매핑을 쓴다.

```bash
python3 mode_selector.py
```

예상 출력:

```
=== 질문 type → LightRAG 권장 모드 선택기 ===

매핑 규칙: {'simple-fact': 'naive', 'multi-hop': 'local', 'global-summary': 'global'}  (그 외/섞임 → mix)

질문                                                    type            mode     경로
---------------------------------------------------------------------------------
VoyageAI의 기본 임베딩 모델 이름은?                              simple-fact     naive    label
LightRAG의 기본·권장 쿼리 모드는?                               simple-fact     naive    label
Neo4j와 RAG는 어떻게 이어지나?                                 multi-hop       local    label
Leiden 커뮤니티 탐지가 Global 검색과 어떤 관계인가?                   multi-hop       local    label
이 코퍼스의 GraphRAG 연구 흐름을 전체 요약해줘.                       global-summary  global   label
RAG 프레임워크들의 공통 설계를 한눈에 정리해줘.                          global-summary  global   label
LightRAG와 Microsoft GraphRAG는 어떻게 이어지나?               multi-hop       local    heuristic
Phase 4 전체를 요약해줘.                                     global-summary  global   heuristic

[핵심] type이 라벨돼 있으면 simple-fact→naive, multi-hop→local, global-summary→global으로 결정론적으로 떨어진다.
       라벨이 없으면 휴리스틱으로 type을 추정한 뒤 같은 매핑을 쓴다.
       어떤 type인지 가리기 어려우면 mix(기본·권장)가 가장 안전하다.
```

대조 포인트: 라벨 6개가 정확히 `naive/local/global`로 떨어지고, 마지막 라벨 없는 2개가 `heuristic` 경로로 각각 `local`·`global`로 추정되면 통과. 완료 기준 충족.

---

## 3단계 (선택) — LightRAG Core 호출 형태만 읽어 두기

`lightrag_quickstart.py`는 06에서 **실행하지 않는다**. 07에서 키·패키지를 갖춘 뒤 실제로 돌린다.
여기서는 문법만 확인하고 Core API 모양을 눈에 익힌다.

```bash
python3 -m py_compile lightrag_quickstart.py && echo "compile OK (실행은 07에서)"
```

예상 출력:

```
compile OK (실행은 07에서)
```

`initialize_storages()` 호출, `QueryParam(mode=...)`, 5모드를 같은 인덱스에서 순회하는 루프가 보이면 충분하다.

---

## 검증 체크리스트

- [ ] 1단계 표에 5모드가 모두 나오고, naive=Baseline·mix=Core 권장 기본 두 줄이 보인다.
- [ ] 2단계에서 라벨 질문 6개가 simple-fact→naive, multi-hop→local, global-summary→global으로 떨어진다.
- [ ] 2단계 라벨 없는 2개가 heuristic 경로로 분류된다.
- [ ] 3단계 `py_compile`이 에러 없이 통과한다(실제 LightRAG 실행은 07).
