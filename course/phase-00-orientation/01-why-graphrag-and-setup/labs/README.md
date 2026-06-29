# Lab 0.1 — RAG 실패 4종 재현 + 스택 헬스체크

`practice/` 의 코드를 단계대로 돌린다. 각 단계에는 **예상 출력**이 붙어 있으니 결과를 대조하라.
명령은 `practice/` 디렉토리에서 실행하는 것을 기준으로 한다.

```bash
cd course/phase-00-orientation/01-why-graphrag-and-setup/practice
```

---

## 0단계 — 가상환경 + 의존성 설치

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

예상 출력(끝부분):

```
Successfully installed anthropic-... voyageai-... neo4j-... lightrag-hku-... numpy-... python-dotenv-...
```

> `lightrag-hku` 설치가 의존성 때문에 길어질 수 있다. 끝까지 기다린다.

---

## 1단계 — .env 작성

```bash
cp .env.example .env
# 편집기로 .env 를 열어 ANTHROPIC_API_KEY, VOYAGE_API_KEY, NEO4J_PASSWORD 를 채운다.
```

`.env` 의 `NEO4J_PASSWORD` 와 `docker-compose.yml` 의 `NEO4J_AUTH=neo4j/...` 비밀번호를 **반드시 같게** 맞춘다.

> 비용을 줄이려면 `.env` 에 `USE_LOCAL_EMBEDDING=1` 을 두고 `pip install sentence-transformers` 를 추가로 설치한다. 임베딩이 로컬 `bge-m3` 로 분기한다.

---

## 2단계 — Neo4j 컨테이너 기동

```bash
docker compose up -d
docker compose ps
```

예상 출력(`ps`):

```
NAME        IMAGE         STATUS                   PORTS
kb-neo4j    neo4j:5.26    Up (healthy)             0.0.0.0:7474->7474/tcp, 0.0.0.0:7687->7687/tcp
```

`STATUS` 가 `Up (healthy)` 가 될 때까지 20~40초 걸린다. 그동안은 `Up (health: starting)` 으로 보인다.

브라우저로 `http://localhost:7474` 접속 → 로그인 화면이 뜨면 정상.
계정 `neo4j`, 비밀번호는 `.env` 에 넣은 값으로 로그인한다.

기동이 안 되면 로그를 본다:

```bash
docker compose logs neo4j | tail -20
```

---

## 3단계 — 헬스체크 (완료 기준)

```bash
python healthcheck.py
```

예상 출력:

```
[OK  ] Claude    | 응답='pong'
[OK  ] Voyage    | backend=voyage-3.5, dim=1024
[OK  ] Neo4j     | connected to bolt://localhost:7687
[OK  ] LightRAG  | import OK (LightRAG, QueryParam)
------------------------------------------------------------
ALL OK — 스택 4개 컴포넌트 정상. 다음 토픽으로 진행하라.
```

`USE_LOCAL_EMBEDDING=1` 로 돌리면 Voyage 줄은 다음처럼 바뀐다:

```
[OK  ] Voyage    | backend=bge-m3(local), dim=1024
```

한 줄이라도 `FAIL` 이면 그 줄의 메시지를 보고 고친다(키 미설정/컨테이너 미기동이 대부분).

```
[FAIL] Neo4j     | ServiceUnavailable: ... Connection refused
```

→ 2단계로 돌아가 컨테이너가 `healthy` 인지 확인한다.

---

## 4단계 — RAG 실패 4종 재현

```bash
python failure_demo.py
```

예상 출력(요약 — 실제 답변 문구는 매 실행마다 조금씩 달라진다):

```
코퍼스 8건 로드 완료. 임베딩 중...
임베딩 완료. 차원=1024, TOP_K=3

========================================================================
[1) 멀티홉 추론]
Q: Self-RAG 의 자기평가 아이디어를 검색 품질 보정으로 발전시킨 기법은 누가 몇 년에 냈는가?
검색된 문서(TOP_K=3): ['02-self-rag.md', '03-crag.md', '08-multihop.md']
A:
   ... (CRAG 를 짚더라도 저자/연도가 다른 문서에 흩어져 있어 누락·혼동이 나기 쉽다)
왜 빗나가나: Self-RAG → CRAG → 저자/연도. 세 문서를 엮어야 하는데 벡터검색은 표면 유사 조각만 가져온다.

========================================================================
[2) 관계 질문]
Q: LightRAG 와 Neo4j 는 서로 어떤 관계이며, LightRAG 는 어떤 도구의 비용 문제를 풀려고 나왔는가?
검색된 문서(TOP_K=3): ['05-lightrag.md', '06-neo4j.md', '04-graphrag-ms.md']
A:
   ... (관련 조각은 와도 "함께 쓰인다 / 비용을 푼다" 같은 엣지를 일관되게 잇지 못한다)
왜 빗나가나: 관계는 문서 사이 엣지로 존재한다. 벡터검색은 노드(조각)는 줘도 엣지는 못 준다.

========================================================================
[3) 전체(global) 요약]
Q: 이 코퍼스 전체를 관통하는 핵심 주제 한 문장과, 등장하는 기법들의 시간 순 흐름을 요약하라.
검색된 문서(TOP_K=3): ['01-rag.md', '04-graphrag-ms.md', '05-lightrag.md']
A:
   ... (TOP_K=3 만 봐서 8건 중 일부만 요약 — 2020 RAG → 2023 Self-RAG → 2024 CRAG/GraphRAG/LightRAG 흐름이 빠진다)
왜 빗나가나: global 요약은 코퍼스 전체를 봐야 한다. TOP_K=3 조각만 보면 일부만 요약하게 된다.

========================================================================
[4) 출처·근거]
Q: 위 답의 각 사실이 corpus 의 어느 파일에서 나왔는지 파일명으로 출처를 달아라.
검색된 문서(TOP_K=3): [...]
A:
   ... (가져온 조각을 합쳐 생성할 뿐, 문장별 출처 추적은 보장되지 않는다)
왜 빗나가나: 벡터 RAG 는 가져온 조각을 합쳐 생성할 뿐, 문장별 출처 추적(프로비넌스)은 보장하지 못한다.

========================================================================
4가지 실패를 확인했다면 이 토픽의 동기는 충분하다. healthcheck.py 로 스택을 점검하자.
```

각 블록의 "왜 빗나가나" 한 줄이 곧 **이 과정이 앞으로 고쳐 갈 문제 목록**이다.

> 검색된 문서 목록이 예시와 정확히 같지 않을 수 있다(임베딩 모델·버전에 따라 순서가 달라진다). 중요한 건 답이 매끄러워도 멀티홉/관계/전체요약/출처에서 **빈틈이 보인다**는 점이다.

---

## 정리(선택)

실습이 끝나면 컨테이너를 멈춘다. 데이터는 볼륨에 남는다(이후 Phase 에서 재사용).

```bash
docker compose stop          # 멈춤(데이터 유지)
# docker compose down -v      # 완전 삭제(볼륨까지) — 데이터가 지워지니 주의
```
