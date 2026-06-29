# 0.1 왜 GraphRAG인가 — RAG 실패 4종과 환경 세팅

> **Phase 0 · 토픽 01** · Vector-only RAG가 무너지는 4가지를 직접 재현해 동기를 잡고, Claude·VoyageAI·LightRAG·Neo4j 스택을 세워 헬스체크를 통과시킨다.

## 학습 목표

이 토픽을 끝내면 다음을 할 수 있다.

- 작은 코퍼스로 Vector-only RAG를 띄우고, 멀티홉·관계·전체요약·출처 네 가지 실패를 직접 재현한다.
- GraphRAG 도입 의사결정 매트릭스로 "우리 문제에 그래프가 필요한가"를 판단한다.
- Claude·VoyageAI·LightRAG·Neo4j 스택을 세우고 `healthcheck.py`로 4개 컴포넌트를 한 번에 검증한다.

**완료 기준**: Vector-only RAG가 4가지 실패(멀티홉·관계·전체요약·출처)를 재현하는 것을 직접 확인하고, `python practice/healthcheck.py`가 Claude·Voyage·Neo4j·LightRAG 4개 컴포넌트 전부 OK를 출력하면 완료.

---

## 1. 이 과정의 지도 — 원문에서 에이전트까지

지식그래프(Knowledge Graph, KG)는 "또 하나의 DB"가 아니다. RAG가 못 보던 관계·경로·전체 구조를 LLM에게 보여주는 렌즈다. 이 과정은 그 렌즈를 처음부터 끝까지 직접 깎아 본다.

하나의 코퍼스가 단계마다 진화한다.

```
원문  →  LLM Wiki(Source Layer)  →  KG 추출·정제  →  Neo4j  →  GraphRAG 검색  →  Agent  →  캡스톤
(0)      (Phase 1)                  (Phase 2)        (Phase 3)  (Phase 4)        (Phase 7)
```

지금 이 토픽에서 만드는 작은 코퍼스와 "RAG가 틀리는 순간"의 체감이 이후 모든 Phase의 동기가 된다. 다음 토픽은 바로 이 코퍼스를 신뢰 가능한 Source Layer로 정제하는 데서 출발한다.

먼저 무너지는 걸 봐야 한다. 동기 없이 그래프부터 만들면 지루하다. 실패를 본 뒤에 만들면 모든 단계가 "이걸 고치는 중"이 된다.

## 2. RAG가 무너지는 4가지 — 작은 코퍼스로 재현

검색 증강 생성(Retrieval-Augmented Generation, RAG)은 외부 문서를 검색해 LLM 생성에 근거를 붙인다. 표준 파이프라인은 청킹 → 임베딩 → 벡터 검색 → 생성이다. 여기까지는 익숙할 것이다.

문제는 벡터 검색이 **질문과 표면적으로 비슷한 조각**만 가져온다는 데 있다. 답이 여러 문서에 흩어져 있거나, 문서 *사이의 관계*에 답이 있거나, 코퍼스 *전체*를 봐야 하면 빗나간다.

`practice/corpus/`에 AI/LLM 기술 문서 8건을 두었다. RAG·Self-RAG·CRAG·Microsoft GraphRAG·LightRAG·Neo4j·임베딩·멀티홉을 다루되, **저자·연도·파생 관계를 일부러 여러 문서에 흩뿌렸다.** 그래서 아래 네 질문은 단일 조각 검색으로는 안 풀린다.

| 실패 | 질문이 노리는 것 | 왜 Vector RAG가 빗나가나 |
|------|------------------|--------------------------|
| 멀티홉(multi-hop) | Self-RAG → CRAG → 저자/연도를 잇기 | 세 문서를 엮어야 하는데 표면 유사 조각만 옴 |
| 관계 | LightRAG와 Neo4j의 관계, LightRAG가 푼 비용 문제 | 조각(노드)은 줘도 문서 사이 엣지는 못 줌 |
| 전체(global) 요약 | 코퍼스 전체 주제 + 기법의 시간 순 흐름 | `TOP_K=3`만 보면 8건 중 일부만 요약 |
| 출처·근거 | 각 사실이 어느 파일에서 나왔는지 | 조각을 합쳐 생성할 뿐, 문장별 프로비넌스 미보장 |

핵심 코드는 이렇게 생겼다. 순수 벡터 검색으로 상위 3건만 가져와 Claude에 컨텍스트로 준다.

```python
# practice/failure_demo.py 의 핵심 부분
def retrieve(query, docs, doc_matrix):
    qv = embed_query(query)                 # 질의 임베딩 (VoyageAI voyage-3.5, 또는 로컬 bge-m3)
    idxs = cosine_topk(qv, doc_matrix, TOP_K)  # 코사인 유사도 상위 TOP_K(=3)
    return [docs[i] for i in idxs]

def generate(query, retrieved):
    context = "\n\n".join(f"[{d['name']}]\n{d['text']}" for d in retrieved)
    prompt = "아래 컨텍스트만 근거로 답하라...\n" + context + "\n질문: " + query
    resp = client.messages.create(model="claude-sonnet-4-6", max_tokens=400,
                                  messages=[{"role": "user", "content": prompt}])
    return resp.content[0].text
```

`TOP_K=3`은 일부러 작게 뒀다. 한계가 잘 드러나라고. 멀티홉 질문에서는 단서 문서 중 하나가 상위 3건에서 빠지기 쉽고, 전체요약 질문에서는 8건 중 3건만 보고 답하니 시간 순 흐름이 통째로 누락된다.

> 전체 코드와 실행 절차는 [`practice/`](practice/) 와 [`labs/`](labs/) 참조.
> 비용이 부담되면 임베딩을 로컬 `bge-m3`로 바꾼다(`.env`에 `USE_LOCAL_EMBEDDING=1`). 파이프라인은 그대로 동작하고, 품질만 조금 떨어진다.

## 3. 결과 해석 — 빈틈을 읽는 법

`python failure_demo.py`를 돌리면 네 질문의 답이 나온다. 답이 매끄러워 보여도 속지 마라. 봐야 할 건 정답 여부가 아니라 **빈틈**이다.

멀티홉 답은 CRAG를 짚더라도 저자(Yan)·연도(2024)를 빠뜨리거나 다른 기법과 섞는다. 단서가 `02-self-rag.md`와 `03-crag.md`에 쪼개져 있는데, 둘을 잇는 추론을 벡터 거리가 대신해 주지 못하기 때문이다. 관계 질문은 "LightRAG가 Microsoft GraphRAG의 비용 문제를 푼다", "Neo4j를 백엔드로 붙인다" 같은 엣지를 일관되게 잇지 못한다. 전체요약은 2020 RAG → 2023 Self-RAG → 2024 CRAG/GraphRAG/LightRAG라는 흐름의 일부만 담는다. 출처 질문은 가져온 조각 안에서만 그럴듯하게 답할 뿐, 문장별로 어느 파일이 근거인지는 보장하지 못한다.

각 블록의 "왜 빗나가나" 한 줄이 곧 앞으로 고쳐 갈 문제 목록이다. 멀티홉과 관계는 그래프의 경로·엣지로(Phase 2~4), 전체요약은 커뮤니티 요약으로(Phase 4), 출처는 프로비넌스 레이어로(Phase 1) 메운다.

## 4. 언제 GraphRAG를 쓰고, 언제 쓰지 말아야 하는가

실패를 봤다고 무조건 그래프로 가는 건 아니다. 그래프는 추출·정제·운영 비용이 든다. 도입 판단은 네 축으로 본다.

| 축 | 그래프가 유리 | 벡터 RAG로 충분 |
|----|----------------|------------------|
| 데이터 구조성 | 엔티티·관계가 또렷함(인물·조직·사건·파생) | 평평한 FAQ·매뉴얼, 관계가 거의 없음 |
| 질문 유형 | 멀티홉·관계·경로·전체 요약이 많음 | 단발성 사실 조회가 대부분 |
| 비용 | 추출·인덱싱 비용을 감당할 가치가 있음 | 빠르고 싸게 끝내야 함 |
| 유지보수 | 스키마·엔티티 해소를 관리할 인력·체계 있음 | 운영 인력이 없음, 변경이 잦지 않음 |

**이럴 땐 쓰지 마라.** 질문이 대부분 "X가 뭐야?" 수준의 단발성 조회이거나, 문서가 서로 거의 안 엮이는 독립 FAQ이거나, 관계 추출·정제를 관리할 사람이 없다면 그래프는 과한 투자다. 잘 만든 하이브리드(Vector + BM25) RAG가 더 싸고 빠르다. GraphRAG는 "관계와 전체 구조에 답이 있는데 벡터로는 안 잡힌다"가 분명할 때 켠다.

우리 코퍼스는 인물·프레임워크·연도·파생 관계가 또렷하고 멀티홉·전체요약 질문이 자연스럽다. 그래프를 배우기에 좋은 케이스다.

## 5. 환경 세팅 + 헬스체크

스택은 네 조각이다. 생성은 Claude, 임베딩은 VoyageAI `voyage-3.5`(차원 1024), GraphRAG 프레임워크는 LightRAG(메인), 그래프 저장소는 Neo4j 5.26 LTS다. LightRAG는 이 토픽에선 import만 확인하고, 본격 인덱싱은 Phase 4에서 다룬다.

Neo4j는 Docker로 띄운다. `practice/docker-compose.yml`이 `neo4j:5.26`을 7474(브라우저)·7687(bolt)로 연다.

```bash
cd course/phase-00-orientation/01-why-graphrag-and-setup/practice
cp .env.example .env          # 키와 NEO4J_PASSWORD 채우기 (compose 비밀번호와 일치)
docker compose up -d          # Neo4j 기동 (healthy 까지 20~40초)
python healthcheck.py
```

`healthcheck.py`는 네 컴포넌트를 각각 가볍게 한 번씩 건드린다. Claude엔 5토큰짜리 ping을 던지고, Voyage(또는 로컬 bge-m3)엔 임베딩 1건을 요청하며, Neo4j는 `driver.verify_connectivity()`로, LightRAG는 import로 점검한다. 키와 접속 정보는 환경변수에서만 읽는다.

```python
# practice/healthcheck.py 의 Neo4j 점검 부분
from neo4j import GraphDatabase
driver = GraphDatabase.driver(uri, auth=(user, password))  # 값은 os.environ 에서
driver.verify_connectivity()   # bolt 연결 확인. 실패하면 예외 → FAIL
driver.close()
```

통과하면 이렇게 출력된다.

```
[OK  ] Claude    | 응답='pong'
[OK  ] Voyage    | backend=voyage-3.5, dim=1024
[OK  ] Neo4j     | connected to bolt://localhost:7687
[OK  ] LightRAG  | import OK (LightRAG, QueryParam)
ALL OK — 스택 4개 컴포넌트 정상. 다음 토픽으로 진행하라.
```

단계별 명령과 예상 출력, FAIL 대처는 [`labs/README.md`](labs/README.md)에 정리해 뒀다.

---

## 🚨 자주 하는 실수

1. **`docker-compose.yml`의 비밀번호와 `.env`의 `NEO4J_PASSWORD`가 다름** — Neo4j 인증은 컨테이너 첫 기동 시 볼륨에 굳는다. 나중에 비밀번호만 바꾸면 인증 실패가 계속된다. 두 값을 같게 맞추고, 꼬였으면 `docker compose down -v`로 볼륨을 지운 뒤 다시 올린다.
2. **컨테이너가 `healthy` 되기 전에 헬스체크를 돌림** — Neo4j는 기동에 20~40초 걸린다. `docker compose ps`가 `Up (healthy)`인지 보고 나서 `healthcheck.py`를 실행한다. `Connection refused`는 보통 기동 대기 문제다.
3. **실패 데모의 답이 그럴듯해서 "RAG 잘 되네"로 넘어감** — 답의 매끄러움이 아니라 멀티홉·관계·전체요약·출처의 **빈틈**을 봐야 한다. 저자/연도 누락, 엣지 누락, 시간 순 흐름 누락, 문장별 출처 부재가 이 과정이 고칠 문제다.

## 출처

- Peng et al., *Graph Retrieval-Augmented Generation: A Survey*, arXiv [2408.08921](https://arxiv.org/abs/2408.08921)
- Microsoft GraphRAG, *From Local to Global*, arXiv [2404.16130](https://arxiv.org/abs/2404.16130)
- LightRAG, GitHub: https://github.com/HKUDS/LightRAG
- Neo4j Docker 가이드: https://neo4j.com/docs/operations-manual/current/docker/
- VoyageAI 임베딩: https://docs.voyageai.com/docs/embeddings

## 다음 토픽

→ [LLM Wiki / Source Layer](../../phase-01-source-layer/01-llm-wiki-source-layer/lesson.md)
