# 4.1 핸즈온 — Method Map 을 손으로 만져 보기

질문 → 검색 패턴 → LightRAG 모드 매핑을 코드로 확인한다. 두 갈래다.

- A. `routing_demo.py` — Neo4j 없이도 도는 라우팅 데모(LLM·키 불필요).
- B. 미니 그래프 위 Local/Path/Global 대표 Cypher — Neo4j 가 필요하다.

명령마다 **예상 출력**을 붙였다. 직접 돌려 결과를 대조하라. 숫자·이름은 환경에 따라 미세하게 다를 수 있다.

> 전제: Python 3.11+, Docker / Docker Compose. 실습 코드는 `../practice/` 에 있다.
> 비용 0 — 이 토픽은 LLM·임베딩 API 를 쓰지 않는다.

---

## A. 질문 라우팅 데모 (Neo4j 불필요)

### A-1. 내장 예시 질문 6개 분류

```bash
cd ../practice
python routing_demo.py
```

예상 출력(요지):

```
========================================================================
GraphRAG Method Map — 질문 → 검색 패턴 → LightRAG 모드 라우팅 데모
  (규칙 기반 휴리스틱. 실제로는 Phase 7 에서 LLM Router 로 대체)
========================================================================
  Q: RAG는 무엇이고 어떤 속성을 가지나?
     → 패턴: local     | LightRAG 모드: local  | 근거 신호: '무엇'
       ...
  Q: RAG와 GraphRAG는 어떻게 연결되는가?
     → 패턴: path      | LightRAG 모드: hybrid | 근거 신호: '어떻게 연결'
       ...
  Q: 이 코퍼스 전체에서 핵심 주제와 트렌드는 무엇인가?
     → 패턴: global    | LightRAG 모드: global | 근거 신호: '전체'
       ...
  Q: 검색 기법들은 어떤 그룹(클러스터)으로 나뉘나?
     → 패턴: community | LightRAG 모드: global | 근거 신호: '어떤 그룹'
       ...
  Q: 아까 그거 말고 다른 GraphRAG 프레임워크는 없나?
     → 패턴: memory    | LightRAG 모드: mix    | 근거 신호: '아까'
       ...
  Q: LightRAG는 누가 만들었나?
     → 패턴: local     | LightRAG 모드: local  | 근거 신호: '누가 만들'
       ...

[패턴 ↔ LightRAG 모드 요약]
  local     → local
  path      → hybrid
  global    → global
  community → global
  memory    → mix
```

여섯 질문이 5패턴에 골고루 떨어진다. 이게 이 토픽의 핵심 표를 코드로 옮긴 것이다.

### A-2. 임의 질문 1개 분류

```bash
python routing_demo.py "Neo4j와 LightRAG는 어떤 관계인가?"
```

예상 출력:

```
  Q: Neo4j와 LightRAG는 어떤 관계인가?
     → 패턴: path      | LightRAG 모드: hybrid | 근거 신호: '관계가'
       직관: 두 엔티티 사이 멀티홉 경로 추적 — 'A와 B는 어떻게 이어지나'
       메우는 RAG 실패: 멀티홉 실패 — Vector+BM25 는 중간 연결고리를 못 잇는다
```

직접 질문을 바꿔 가며 어디로 라우팅되는지 보라. 일부러 헷갈리는 질문을 넣어 규칙이 빗나가는 지점을 찾아보면, 왜 Phase 7 에서 이 자리를 LLM Router 로 바꾸는지 체감된다.

---

## B. 미니 그래프 위 Local / Path / Global (Neo4j 필요)

### B-1. Neo4j 기동 + 헬스체크

```bash
cd ../practice
docker compose up -d
docker compose ps
```

예상 출력(STATUS 가 `healthy` 가 될 때까지 30초쯤 걸린다):

```
NAME       IMAGE         STATUS                   PORTS
kb-neo4j   neo4j:5.26    Up 35 seconds (healthy)  0.0.0.0:7474->7474/tcp, 0.0.0.0:7687->7687/tcp
```

헬스체크가 `healthy` 로 바뀌면 Bolt(7687) 접속 준비가 끝난 것이다. `starting` 이면 좀 더 기다린다.

### B-2. 미니 그래프 적재 + 세 패턴 한 번에 실행 (Python)

```bash
pip install -r requirements.txt
export NEO4J_PASSWORD=testpassword1
python mini_graph_neo4j.py
```

예상 출력:

```
[load] 미니 그래프 적재 완료 — :Mini 노드 7개 + 관계 7개

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

세 블록이 이 토픽의 세 패턴이다. Local 은 `LightRAG` 이웃 3개, Path 는 `Neo4j → RAG` 3홉 경로(직접 검색으로는 절대 안 나오는 답), Global 은 community 2묶음이다.

### B-3. (대안) cypher-shell 로 같은 패턴 보기

Python 드라이버 없이 Cypher 만으로 같은 결과를 보려면 미니 그래프 Cypher 를 흘려 넣는다.

```bash
cat mini_graph_patterns.cypher | docker exec -i kb-neo4j cypher-shell -u neo4j -p testpassword1
```

예상 출력(마지막 세 쿼리의 결과만 발췌):

```
rel            neighbor    ntype
"DEVELOPED_BY" "HKUDS"     "Organization"
"IMPLEMENTS"   "GraphRAG"  "Method"
"USES"         "Neo4j"     "Database"

hops                                       hop_len
["Neo4j", "LightRAG", "GraphRAG", "RAG"]   3

community  size  members
0          4     ["RAG", "GraphRAG", "LightRAG", "multi-hop"]
1          3     ["Neo4j", "HKUDS", "Microsoft"]
```

members 배열의 순서는 적재 순서에 따라 다를 수 있다(집합이라 순서 보장 없음).

### B-4. 정리

```bash
python mini_graph_neo4j.py --reset      # 미니 그래프(:Mini)만 삭제
docker compose down                      # 컨테이너 종료(볼륨 유지)
```

예상 출력:

```
[reset] 미니 그래프(:Mini)를 삭제했다.
```

`:Mini` 라벨로 격리해 적재했으므로, Phase 3 의 진짜 그래프가 같은 DB 에 있어도 그건 건드리지 않는다.

---

## 체크포인트

- [ ] routing_demo 가 6개 예시 질문을 5패턴에 맞게 분류한다.
- [ ] Neo4j 컨테이너가 `healthy` 로 뜬다.
- [ ] 미니 그래프에서 Local(이웃 3) / Path(3홉) / Global(2 community)이 모두 나온다.
- [ ] 임의 Golden Question 하나를 골라 어떤 패턴·LightRAG 모드로 가야 하는지 말로 설명할 수 있다.
