# 4.1 GraphRAG Method Map — Local · Global · Path · Community · Memory

> **Phase 4 · 토픽 01** · Phase 4 전체(02~08)를 한 장의 의사결정 지도로 펼친다. "어떤 질문에는 어떤 GraphRAG 검색 패턴을 쓰는가"를 5가지(Local·Global·Path·Community·Memory)로 정리하고, 각각을 대표 LightRAG 모드에 매핑한다.

## 학습 목표

이 토픽을 끝내면 다음을 할 수 있다.

- GraphRAG 검색의 5가지 패턴(Local·Global·Path·Community·Memory)을 질문 유형으로 **구분한다**.
- 주어진 Golden Question을 적합한 패턴과 대표 LightRAG 모드(`naive`/`local`/`global`/`hybrid`/`mix`)로 **라우팅한다**.
- Phase 1 Baseline(Vector+BM25)이 어디서 무너지고 어떤 패턴이 그 실패를 메우는지 **연결한다**.
- 미니 그래프 위에서 Local(이웃 조회)·Path(멀티홉 경로)·Global(커뮤니티 집계) 대표 Cypher를 직접 **돌려 본다**.

**완료 기준**: 5가지 검색 패턴 각각에 맞는 질문 유형을 구분하고, 주어진 Golden Question을 적합한 패턴(과 대표 LightRAG 모드)으로 라우팅할 수 있으면 완료.

---

## 1. 왜 필요한가 — 그래프는 다 만들었다, 이제 어떻게 검색할까

Phase 3까지 우리는 그래프를 **만들기만** 했다. 텍스트에서 엔티티·관계를 뽑고(Phase 2), Neo4j에 적재하고, Cypher로 멀티홉을 질의하고, 하이브리드 인덱스를 깔고, GDS로 PageRank 허브와 Leiden 커뮤니티까지 뽑았다(Phase 3/06). 재료는 다 갖췄다.

그런데 정작 "사용자 질문이 들어오면 이 그래프에서 무엇을, 어떻게 끌어올까"는 아직 정하지 않았다. 같은 그래프라도 질문에 따라 꺼내는 방식이 전혀 다르다. "LightRAG는 누가 만들었나"와 "이 코퍼스 전체의 핵심 흐름은 뭔가"는 같은 검색기로 답할 수 없다. 앞엣것은 노드 하나의 이웃만 보면 되고, 뒤엣것은 그래프 전체를 조망해야 한다.

여기서 다시 Phase 0을 떠올려 보자. 거기서 우리는 Baseline RAG가 무너지는 네 가지를 직접 재현했다. 멀티홉, 관계 추론, 전체 요약, 출처 연결. Vector+BM25는 의미가 가까운 청크 top-k를 잘 집어 오지만, 떨어진 두 사실을 잇거나(멀티홉) 코퍼스 전체를 종합하는(전체 요약) 일은 구조적으로 못 한다. GraphRAG 검색 패턴은 바로 그 빈자리를 메우려고 있다.

Phase 4는 그 패턴들을 하나씩 구현하는 여정이다. 02에서 Local·Path, 03에서 Global, 04에서 Fusion, 05에서 A/B, 06~08에서 메인 프레임워크 LightRAG. 이 토픽은 그 전체를 **한 장의 지도**로 먼저 펼친다. 길을 떠나기 전에 어디로 갈지 정하는 단계다.

## 2. 5가지 검색 패턴 — 질문이 패턴을 부른다

핵심 직관 하나로 시작하자. **검색 패턴은 질문의 모양이 결정한다.** 질문이 한 엔티티를 가리키면 그 주변만 보면 되고, 두 엔티티를 잇는 질문이면 경로를 추적해야 하고, "전체"를 묻는 질문이면 조망이 필요하다. 다섯 패턴을 이 관점으로 보자.

**Local — 한 엔티티의 이웃.** "이건 무엇이고 무엇과 직접 연결되나" 류 질문. 특정 엔티티를 그래프에서 찾아(엔티티 링킹) 그 1~2홉 이웃을 끌어온다. "LightRAG는 누가 만들었나"라면 `LightRAG` 노드의 `DEVELOPED_BY` 이웃을 보면 끝이다. LightRAG의 `local` 모드가 이 직관이다.

**Path — 두 엔티티 사이 경로.** "A와 B는 어떻게 연결되나" 류 질문. 두 엔티티를 양 끝점으로 잡고 사이를 잇는 멀티홉 경로를 추적한다. Vector 검색은 A와 B가 한 청크에 같이 안 나오면 둘의 관계를 못 찾는다. 그래프는 중간 노드들을 거쳐 길을 잇는다. Phase 0의 멀티홉 실패를 정면으로 메우는 패턴이다.

**Global — 커뮤니티 요약으로 전체 조망.** "코퍼스 전체에서 핵심 주제·트렌드는?" 류 전체 요약 질문. 개별 노드가 아니라 Leiden 커뮤니티(Phase 3/06에서 뽑은 그것)별로 요약을 만들고, 그 요약들을 Map-Reduce로 종합한다. top-k 청크 몇 개로는 절대 답이 안 나오는 질문이다. Microsoft의 *From Local to Global*이 정확히 이 아이디어고, LightRAG의 `global` 모드가 대응한다.

**Community — 커뮤니티 구조 자체를 검색 단위로.** Global의 토대이면서 별도 패턴이기도 하다. "검색 기법들은 어떤 묶음으로 나뉘나" 같은 질문은 답이 개별 노드가 아니라 **클러스터**다. Phase 3/06의 Leiden이 그어 둔 커뮤니티 경계가 여기서 검색의 단위가 된다. 대표 모드는 Global과 같은 `global` 계열이다.

**Memory — 대화·이전 결과를 상태로.** "아까 그거 말고 다른 건?" 같은 후속 질의. 단발 검색은 직전 턴을 기억하지 못한다. 대화 히스토리와 이전 검색 결과를 상태로 누적해 후속 질문에 활용하는 패턴이다. LightRAG의 conversation history나 `mix` 모드에서 이 맥락이 쓰인다. 멀티턴은 본격적으로 Phase 7 Agent Harness에서 다루므로, 여기서는 "이런 패턴이 하나 더 있다" 정도로 지도에 표시만 해 둔다.

### 한 장으로 보는 매핑

이 토픽의 하이라이트다. 질문 유형 → 적합 검색법 → 메우는 Baseline 실패 → 대표 LightRAG 모드를 한 표에 모은다.

| 질문 유형(예) | 검색 패턴 | 메우는 Baseline 실패(Phase 0) | 대표 LightRAG 모드 |
|---|---|---|---|
| "LightRAG는 무엇이고 누가 만들었나" | **Local** | (단일 사실은 Baseline도 되나 관계 맥락은 그래프가 정확) | `local` |
| "RAG와 GraphRAG는 어떻게 연결되나" | **Path** | 멀티홉 — 떨어진 두 사실을 못 잇는다 | `hybrid` |
| "이 코퍼스의 핵심 주제·트렌드는" | **Global** | 전체 요약 — top-k 청크로는 전체를 못 본다 | `global` |
| "검색 기법은 어떤 군집으로 나뉘나" | **Community** | 주제 구획 — 평면 검색은 묶음 구조를 못 본다 | `global` |
| "아까 그거 말고 다른 건" | **Memory** | 멀티턴 — 단발 검색은 직전 턴을 잊는다 | `mix` |

LightRAG 모드가 패턴과 1:1로 깔끔히 떨어지지는 않는다는 점도 봐 두자. Path를 `hybrid`에, Community를 `global`에 매핑한 건 "가장 가까운" 대응이지 정의가 아니다. LightRAG 5모드의 정확한 동작은 06~07에서 직접 A/B로 확인한다. `naive`는 그래프를 안 쓰는 순수 벡터 검색이라, 사실상 Phase 1 Baseline의 자리다.

## 3. 실습 ① — 질문을 패턴으로 라우팅하기

표를 코드로 옮겨 보자. 질문 문자열을 받아 5패턴 중 하나로 분류하고, 대응하는 LightRAG 모드를 출력한다. LLM 없이 키워드·질문형 규칙만으로 돈다. 개념을 손으로 만져 보는 게 목적이다.

```python
# practice/routing_demo.py 의 핵심 — 규칙 순서대로 검사하고 먼저 맞은 패턴을 택한다
def route(question: str) -> tuple[str, str]:
    low = question.lower()
    for key, signals in RULES:          # RULES: memory→global→community→path→local 순
        for sig in signals:
            if sig.strip().lower() in low:
                return key, sig.strip()  # 매칭된 패턴과 근거 신호어를 돌려준다
    return DEFAULT_KEY, "(기본값 — 매칭 신호어 없음)"
```

규칙 순서가 중요하다. 한국어 조사 '와/과'는 "A와 B"(연결, Path 신호)에도 "주제와 트렌드"(단순 나열)에도 똑같이 쓰여서, Path 신호로만 보면 너무 헐겁다. 그래서 더 또렷한 의도 신호(Memory·Global·Community)를 먼저 거르고, 애매한 연결 조사는 Path의 마지막 보루로만 남긴다.

> 전체 코드와 실행 절차는 [`practice/`](practice/) 와 [`labs/`](labs/) 참조.
> 이 토픽은 LLM·임베딩 API를 쓰지 않는다. 라우팅을 LLM으로 실험하고 싶으면 Claude(`ANTHROPIC_API_KEY`)나 비용 0의 Ollama(로컬)로 이 분류 함수를 LLM 호출로 바꾸면 된다.

## 4. 결과 해석 ① — 규칙의 한계가 곧 Phase 7의 동기

`python routing_demo.py`를 돌리면 내장 질문 6개가 이렇게 갈린다.

```
  Q: RAG는 무엇이고 어떤 속성을 가지나?       → 패턴: local     | LightRAG 모드: local
  Q: RAG와 GraphRAG는 어떻게 연결되는가?       → 패턴: path      | LightRAG 모드: hybrid
  Q: 이 코퍼스 전체에서 핵심 주제와 트렌드는?  → 패턴: global    | LightRAG 모드: global
  Q: 검색 기법들은 어떤 그룹(클러스터)으로?    → 패턴: community | LightRAG 모드: global
  Q: 아까 그거 말고 다른 GraphRAG 프레임워크?  → 패턴: memory    | LightRAG 모드: mix
  Q: LightRAG는 누가 만들었나?                 → 패턴: local     | LightRAG 모드: local
```

여섯 질문이 5패턴에 골고루 떨어진다. 표가 코드로 살아 움직이는 셈이다.

여기서 한 가지를 의도적으로 느껴 보길 바란다. 이 규칙은 **금세 한계에 부딪힌다.** 신호어를 살짝 비틀거나 의도가 섞인 질문을 던지면 엉뚱한 패턴으로 샌다. 직접 어려운 질문을 넣어 빗나가게 만들어 보라. 그 한계가 바로 "왜 Phase 7에서 이 자리를 LLM Router로 바꾸는가"의 답이다. 규칙 기반은 지도를 이해하기엔 좋지만, 운영에선 LLM이 질문 의도를 읽어 검색 도구를 고른다.

## 5. 실습 ② — 미니 그래프에서 세 패턴을 직접 본다

패턴이 Cypher로는 어떻게 생겼는지 봐야 손에 잡힌다. Phase 3의 진짜 그래프는 04~05에서 입력으로 쓰고, 여기서는 7개 노드짜리 미니 그래프를 직접 만들어(`:Mini` 라벨로 격리) Local·Path·Global을 한 번에 돌린다.

```python
# practice/mini_graph_neo4j.py 의 핵심 — 세 패턴의 대표 Cypher
def demo_path(session, start: str = "Neo4j", end: str = "RAG") -> None:
    # Path — 두 엔티티 사이 최단 멀티홉 경로. Baseline RAG 가 무너지던 자리다.
    record = session.run(
        "MATCH (a:Mini {name: $start}), (b:Mini {name: $end}), "
        "p = shortestPath((a)-[*..6]-(b)) "
        "RETURN [n IN nodes(p) | n.name] AS hops, length(p) AS hop_len",
        start=start, end=end,
    ).single()
    print(f"  {' → '.join(record['hops'])}  (길이 {record['hop_len']} 홉)")
```

`shortestPath`는 두 노드 사이 최단 경로를 한 번에 찾아 준다. Local은 `(e)-[r]-(nb)`로 한 엔티티의 이웃을, Global은 `e.community`로 묶어 `count`·`collect`로 커뮤니티별 집계를 낸다. 접속 정보는 `os.environ`에서 읽고(`NEO4J_PASSWORD` 등), 비밀번호를 코드에 박지 않는다.

## 6. 결과 해석 ② — 직접 검색으로는 안 나오는 답

`python mini_graph_neo4j.py`의 출력이다.

```
[Local] 'LightRAG' 의 직접 이웃 — 이 엔티티는 무엇과 바로 연결되나
  LightRAG -[DEVELOPED_BY]- HKUDS (Organization)
  LightRAG -[IMPLEMENTS]- GraphRAG (Method)
  LightRAG -[USES]- Neo4j (Database)

[Path] 'Neo4j' → 'RAG' 최단 경로 — A와 B는 몇 홉으로 어떻게 이어지나
  Neo4j → LightRAG → GraphRAG → RAG  (길이 3 홉)

[Global] community 단위 집계 — 코퍼스가 어떤 묶음으로 나뉘나
  community 0 (4개): GraphRAG, LightRAG, RAG, multi-hop
  community 1 (3개): HKUDS, Microsoft, Neo4j
```

Path 결과를 보자. `Neo4j → RAG`는 직접 연결이 없다. 그런데 `Neo4j → LightRAG → GraphRAG → RAG`라는 3홉 경로가 나온다. 이게 Vector 검색이 못 하는 일이다. `Neo4j`와 `RAG`가 같은 청크에 안 나오면 벡터 유사도로는 둘의 관계를 찾을 길이 없다. 그래프는 중간 노드를 디딤돌 삼아 길을 잇는다. Phase 0에서 무너졌던 멀티홉이 여기서 메워진다.

Global의 community 0/1 묶음은 Phase 3/06 Leiden이 그어 준 경계의 미니 버전이다. 검색 기법(RAG·GraphRAG·LightRAG·multi-hop)이 한 군집, 조직·도구(HKUDS·Microsoft·Neo4j)가 다른 군집으로 갈린다. 전체 요약 질문이 들어오면 Global Retriever(Phase 4/03)는 이 군집별로 요약을 만들어 종합한다.

## 7. 다음으로 — 이 지도가 Phase 4의 길잡이다

이제 지도가 생겼다. 02부터는 이 패턴들을 진짜로 구현한다. Phase 1 Baseline 점수가 그 모든 개선의 비교 기준선이라는 것도 잊지 말자. Phase 4/05의 A/B는 "Vector-only 대비 멀티홉·전체요약 정답률이 올랐는가"를 이 기준선과 견줘 숫자로 증명한다. 패턴을 막연히 "좋다"가 아니라 점수로 입증하는 게 이 과정의 규율이다.

---

## 🚨 자주 하는 실수

1. **모든 질문에 한 검색 패턴을 쓴다** — "그래프 검색은 멀티홉"이라며 전체 요약 질문까지 Path로 풀려 하면 답이 산으로 간다. 전체 요약은 개별 경로가 아니라 커뮤니티 요약(Global)의 일이다. 질문의 모양을 먼저 보고 패턴을 고른다. 그게 이 지도의 존재 이유다.
2. **규칙 기반 라우터를 운영에 쓰려 한다** — `routing_demo.py`의 키워드 매칭은 개념 이해용이다. 신호어만 살짝 비껴도 빗나간다. 운영 라우팅은 LLM이 질문 의도를 읽는다(Phase 7). 이 데모로 "규칙은 금방 한계가 온다"를 체감하는 게 정답이다.
3. **LightRAG 모드를 패턴과 1:1로 외운다** — 표의 매핑은 "가장 가까운 대응"이지 정의가 아니다. Path를 `hybrid`에, Community를 `global`에 붙인 건 직관을 잡기 위한 근사다. 5모드(`naive`/`local`/`global`/`hybrid`/`mix`)의 정확한 동작은 06~07에서 같은 코퍼스로 A/B를 돌려 직접 확인한다. `naive`가 그래프를 안 쓰는 벡터 검색, 즉 Baseline 자리라는 것도 그때 또렷해진다.

## 출처

- LightRAG — https://github.com/HKUDS/LightRAG
- LightRAG API Server·WebUI — https://github.com/HKUDS/LightRAG/blob/main/docs/LightRAG-API-Server.md
- Microsoft GraphRAG Docs — https://microsoft.github.io/graphrag/
- *From Local to Global: A Graph RAG Approach to Query-Focused Summarization*, arXiv 2404.16130 — https://arxiv.org/abs/2404.16130
- GraphRAG Survey, arXiv 2408.08921 — https://arxiv.org/abs/2408.08921
- Awesome-GraphRAG (DEEP-PolyU) — https://github.com/DEEP-PolyU/Awesome-GraphRAG

## 다음 토픽

→ [02-local-path-retriever](../02-local-path-retriever/lesson.md)
