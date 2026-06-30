# 4.3 Labs — Global Retriever 핸즈온

4.2 의 `:Mini` 그래프를 이어받아 커뮤니티를 탐지하고, 요약을 만들고, map-reduce 로
전역 질문에 답하기까지 한 단계씩 돌린다. 각 명령에 **예상 출력**을 붙였으니 대조하라.

> 출력의 숫자(커뮤니티 수·modularity)와 요약 본문은 GDS 버전·랜덤 시드·LLM 에 따라
> 달라질 수 있다. **형태와 흐름**이 맞으면 정상이다.

## 사전 준비

```bash
cd course/phase-04-graphrag-lightrag/03-global-retriever/practice
pip install -r requirements.txt
export NEO4J_PASSWORD=testpassword1
```

LLM 백엔드는 둘 중 하나를 고른다.

- **Claude(기본)**: `export ANTHROPIC_API_KEY=sk-...` 하고 `pip install anthropic`.
- **Ollama(비용 0)**: 키를 넣지 않으면 자동으로 이 경로. 미리 띄워 둔다.
  ```bash
  ollama serve &              # 별도 터미널이면 & 없이
  ollama pull qwen2.5:7b      # 가벼운 예시 모델. export OLLAMA_MODEL 로 바꿔도 됨
  ```
  키가 없고 ollama 도 안 떠 있으면 3·4단계(요약·global)가 LLM 호출에서 실패한다.
  1·2단계(그래프 적재·커뮤니티 탐지)는 LLM 없이 돈다.

---

## 1단계 — Neo4j + GDS 기동

```bash
docker compose up -d
docker compose logs --tail 5 neo4j
```

**예상 출력** (마지막 줄에 Started 가 보이면 기동 완료):

```
kb-neo4j  | ... INFO  Started.
```

GDS 가 실제로 깔렸는지 확인한다. 4.3 은 GDS 가 필수다.

```bash
docker exec kb-neo4j cypher-shell -u neo4j -p testpassword1 "RETURN gds.version() AS gds"
```

**예상 출력**:

```
gds
"2.13.2"
```

> 버전 숫자는 이미지에 따라 다르다. 값이 나오면 GDS 설치 완료다.
> `there is no procedure with the name gds.version` 가 나오면 GDS 미설치 —
> `docker-compose.yml` 의 `NEO4J_PLUGINS` 를 확인하고 컨테이너를 다시 띄운다.

---

## 2단계 — :Mini 그래프 적재(4.2 보강판)

```bash
python graph_setup.py
```

**예상 출력**:

```
[load] 보강된 미니 그래프 적재 완료 — :Mini 노드 14개 + 관계 16개
[index] full-text 인덱스 'miniNameFulltext' 준비 완료 (name + aliases)
[다음] python community_detect.py --write 로 Leiden 커뮤니티를 탐지·기록한다.
```

> 4.2 는 9개 노드 + 9개 관계였다. 4.3 은 평가·관측 주제 5개 노드 + 7개 관계를 더해
> 14개 노드 + 16개 관계다. 이 보강이 커뮤니티를 갈리게 한다.

---

## 3단계 — Leiden 커뮤니티 탐지 + 기록

먼저 멤버만 본다(그래프엔 안 씀).

```bash
python community_detect.py
```

**예상 출력**(커뮤니티 분할은 예시 — 2~3개로 갈리면 정상):

```
[투영] miniGraph_leiden — nodes=14 rels=16 (UNDIRECTED, Leiden 필수)

[Leiden] 커뮤니티 2개 — 서로 촘촘히 연결된 :Mini 무리
  community 0 (9개): GraphRAG, HKUDS, LightRAG, Microsoft, Neo4j, RAG, VoyageAI, multi-hop, vector search
  community 1 (5개): Baseline, Langfuse, QA accuracy, Ragas, evaluation

[정리] miniGraph_leiden drop 완료(인메모리 투영만 제거, 디스크 그래프는 유지).

[해석] 작은 그래프라 커뮤니티가 1~2개로 뭉쳐도 정상이다.
       이 커뮤니티 분할이 community_summarize / global_retriever 의 입력이 된다.
```

이제 `e.community` 에 탐지값을 기록한다(4.2 의 하드코딩 값을 덮어쓴다).

```bash
python community_detect.py --write
```

**예상 출력**(끝부분):

```
[write] e.community 덮어쓰기 완료 — communityCount=2 modularity=0.42... nodePropertiesWritten=14
  확인: MATCH (e:Mini) RETURN e.community, collect(e.name)
  다음: python community_summarize.py 로 커뮤니티별 요약(Community Report)을 만든다.
```

> 커뮤니티가 1개로만 나오면 그래프가 한 덩어리로 묶인 것이다. 그래도 다음 단계는
> 그대로 돈다(요약 1건 → map-reduce). 1개 정상.
> `must be UNDIRECTED` 에러면 투영 방향 문제다(흔한 실수 1번).

---

## 4단계 — 커뮤니티 요약(Community Report) 생성·캐시

```bash
python community_summarize.py
```

**예상 출력**(요약 본문은 LLM 에 따라 다름):

```
[백엔드] LLM = anthropic  (요약 생성에 실제 호출 발생)
  community 0: 9개 멤버 요약 완료
  community 1: 5개 멤버 요약 완료
[캐시] community_reports.json 저장 완료 — 커뮤니티 2개. global_retriever 가 이 파일을 읽어 map-reduce 를 돌린다.

[미리보기]
  c0 (GraphRAG, HKUDS, LightRAG...): 이 군집은 RAG 와 그 그래프 확장(GraphRAG·LightRAG)을 ...
  c1 (Baseline, Langfuse, QA accuracy...): 평가·관측 도구(Ragas·Langfuse)로 검색 품질을 ...
```

> `[백엔드] LLM = ollama` 로 찍히면 키 없이 로컬로 도는 중이다(정상).
> 다시 돌리면 캐시를 재사용해 LLM 을 안 부른다 — 비용 0:

```bash
python community_summarize.py
```

```
[캐시] community_reports.json 재사용 — 커뮤니티 2개 (LLM 호출 0, 과금 0). 다시 만들려면 --refresh.
```

---

## 5단계 — Global(Map-Reduce)로 전체요약 질문

```bash
python global_retriever.py "이 코퍼스의 핵심 주제를 큰 그림으로 요약하면?"
```

**예상 출력**(점수·본문은 예시):

```
[백엔드] LLM = anthropic
[질문] 이 코퍼스의 핵심 주제를 큰 그림으로 요약하면?

[MAP] 커뮤니티별 부분답변(관련도 점수):
  c0 (score 9, GraphRAG, HKUDS, LightRAG...): GraphRAG·LightRAG 가 RAG 의 멀티홉 한계를 그래프로 메운다 ...
  c1 (score 6, Baseline, Langfuse, QA accuracy...): 평가·관측 도구로 Baseline 대비 검색 품질을 측정한다 ...

[REDUCE] 전역 답변:
이 코퍼스는 크게 두 축이다. 하나는 RAG 를 그래프로 확장한 검색 기법(GraphRAG·LightRAG, 커뮤니티 0),
다른 하나는 그 검색기를 평가·관측하는 도구(Ragas·Langfuse·Baseline, 커뮤니티 1)다. ...
```

**확인 포인트**(완료 기준 대조):

- `[MAP]` 에 커뮤니티가 **2개 이상** 부분답변으로 등장하는가.
- `[REDUCE]` 전역 답변이 **여러 커뮤니티를 함께** 언급하는가(검색 축 + 평가 축).

다른 질문도 던져 점수가 어떻게 갈리는지 본다.

```bash
python global_retriever.py "GraphRAG 의 검색 품질은 어떻게 평가하나?"
```

**예상 출력**(이 질문은 평가 군집 점수가 높아진다):

```
[MAP] 커뮤니티별 부분답변(관련도 점수):
  c1 (score 9, Baseline, Langfuse, QA accuracy...): Ragas 로 정답률을, Langfuse 로 추적을 ...
  c0 (score 4, GraphRAG, HKUDS, LightRAG...): 검색 기법 자체는 평가 대상이지만 평가 방법은 ...
...
```

> 질문에 따라 커뮤니티 점수가 갈리는 게 핵심이다. MAP 의 점수가 무관한 커뮤니티를
> REDUCE 에서 걸러 낸다.

---

## 6단계 — Local 과 대비(선택)

같은 전체요약 질문을 4.2 의 Local 로 던져 본다(4.2 디렉토리에서).

```bash
cd ../../02-local-path-retriever/practice
python local_retriever.py "핵심 주제"
```

**예상 출력**(Local 은 시작점이 없어 빈약하다):

```
(링킹: '핵심 주제' → :Mini(None) [none], depth=1)
[Local 컨텍스트] '핵심 주제' 를 그래프 노드로 링크하지 못했다. 검색을 시작할 수 없다 ...
```

> Local 은 "핵심 주제"를 노드로 링킹하지 못해 출발조차 못 한다. 시작 엔티티가 있는
> 질문(`python local_retriever.py "LightRAG"`)에선 Local 이 강하다. 질문 종류가 다를 뿐이다.
> Global 은 이 빈자리를 메운다. 4.4 에서 두 축을 섞는다.

---

## 정리(끝났으면)

```bash
cd ../../03-global-retriever/practice
docker compose down        # 컨테이너만 제거(볼륨 유지)
# docker compose down -v    # 데이터까지 삭제(주의)
```

`community_reports.json` 은 다음 토픽(4.4)이 재사용할 수 있으니 남겨 둬도 된다.
