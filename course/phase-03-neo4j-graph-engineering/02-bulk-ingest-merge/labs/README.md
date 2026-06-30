# Lab 3.2 — Bulk Ingest & MERGE 핸즈온

`practice/` 의 코드를 순서대로 돌려 Phase 2 그래프를 Neo4j 에 대량 적재하고, 두 번 적재해도 카운트가 안 늘어나는지 확인한다. 각 단계에 **예상 출력**을 붙였다. 실제 출력과 대조하라.

전제: Docker / Docker Compose, Python 3.11+, `practice/` 디렉토리에서 실행. 이 토픽은 API 키가 필요 없다(로컬 Neo4j 만, 과금 없음).

```bash
cd ../practice    # 이 lab 기준 practice 로 이동
```

---

## 1단계 — Neo4j 5.26 기동 + 헬스체크

3/01 컨테이너(`kb-neo4j`)가 이미 떠 있으면 이 단계는 건너뛴다. 새로 띄우려면:

```bash
docker compose up -d
docker compose ps
```

예상 출력(요지):

```
NAME        IMAGE         STATUS                   PORTS
kb-neo4j    neo4j:5.26    Up (healthy)             0.0.0.0:7474->7474/tcp, 0.0.0.0:7687->7687/tcp
```

`STATUS` 가 `Up (healthy)` 가 될 때까지 기다린다(첫 기동은 30초~1분). 의존성 설치와 연결 확인:

```bash
pip install -r requirements.txt
python -c "from neo4j import GraphDatabase; import os; \
d=GraphDatabase.driver(os.environ.get('NEO4J_URI','bolt://localhost:7687'), \
auth=(os.environ.get('NEO4J_USER','neo4j'), os.environ.get('NEO4J_PASSWORD','testpassword1'))); \
d.verify_connectivity(); print('[OK] connectivity'); d.close()"
```

예상 출력:

```
[OK] connectivity
```

`ServiceUnavailable` 이 나오면 컨테이너가 아직 안 떴거나 포트를 7474 로 잘못 준 경우다. 드라이버는 Bolt 포트 7687 에 붙는다.

---

## 2단계 — 제약/인덱스 적용 (적재 전에 먼저)

```bash
cat constraints.cypher | docker exec -i kb-neo4j cypher-shell -u neo4j -p testpassword1
```

`SHOW CONSTRAINTS` 예상 출력(요지) — 엔티티·이벤트 유니크 제약 두 개가 보인다:

```
+-----------------------------------------------------------------------------+
| name                  | type         | labelsOrTypes | properties           |
+-----------------------------------------------------------------------------+
| "entity_canonical_id" | "UNIQUENESS" | ["Entity"]    | ["canonical_id"]     |
| "event_id"            | "UNIQUENESS" | ["Event"]     | ["event_id"]         |
+-----------------------------------------------------------------------------+
```

`SHOW INDEXES` 예상 출력(요지) — 제약이 만든 백킹 인덱스 두 개와 `entity_name` 인덱스가 함께 `ONLINE`:

```
| name                  | type    | labelsOrTypes | properties       | state    |
| "entity_canonical_id" | "RANGE" | ["Entity"]    | ["canonical_id"] | "ONLINE" |
| "event_id"            | "RANGE" | ["Event"]     | ["event_id"]     | "ONLINE" |
| "entity_name"         | "RANGE" | ["Entity"]    | ["name"]         | "ONLINE" |
```

`state` 가 `ONLINE` 이어야 쓸 준비가 된 것이다. (`ingest_bulk.py` 도 적재 직전에 같은 제약을 코드로 다시 실행하므로, 이 단계를 건너뛰어도 적재는 되지만 순서를 눈으로 익히는 게 목적이다.)

---

## 3단계 — 대량 적재

```bash
python ingest_bulk.py
```

예상 출력:

```
[INFO] 미해소 endpoint -> fallback 노드 생성: ['LangChain']
[OK] 적재 완료 — nodes=14 rels=11 events=2
```

카운트 내역:

- **노드 14** = 엔티티 11 + 미해소(LangChain) 1 + 이벤트 2
- **관계 11** = 타입 관계 9(`USES` 2, `IMPROVES` 4, `COMPARES_TO` 1, `DEVELOPED_BY` 2) + `ABOUT` 2
- **이벤트 2**

`LangChain` 은 entities 파일에 없는 endpoint 라 `ent-unresolved-langchain` 노드로 들어가고 `unresolved=true` 가 붙는다.

---

## 4단계 — idempotent 검증 (두 번 적재)

```bash
python verify_idempotent.py
```

예상 출력:

```
=== 1차 적재 ===
[INFO] 미해소 endpoint -> fallback 노드 생성: ['LangChain']
[OK] 적재 완료 — nodes=14 rels=11 events=2
=== 2차 적재 ===
[INFO] 미해소 endpoint -> fallback 노드 생성: ['LangChain']
[OK] 적재 완료 — nodes=14 rels=11 events=2

1차: nodes=14 rels=11 events=2
2차: nodes=14 rels=11 events=2
[OK] idempotent — 두 번 적재해도 카운트가 동일하다.
```

핵심은 1차와 2차 카운트가 같다는 것이다. MERGE 가 키로 노드·관계를 재사용하고 provenance dedup 이 결정적이라, 같은 스냅샷을 몇 번 넣어도 그래프가 안 부푼다. 카운트가 늘면 `[FAIL] idempotent 깨짐` 과 함께 어디가 늘었는지 찍히고 종료 코드 1 이 난다.

---

## 5단계 (선택) — Browser 에서 눈으로 확인

브라우저 `http://localhost:7474` 접속(`bolt://localhost:7687` / `neo4j` / `testpassword1`) 후:

```cypher
MATCH (n) RETURN n LIMIT 50
```

LightRAG·RAG·Neo4j·GraphRAG 등 엔티티 노드와 `USES`·`IMPROVES`·`COMPARES_TO`·`DEVELOPED_BY` 관계, 그리고 두 `Event` 노드가 `ABOUT` 으로 RAG·GraphRAG 에 연결된 모습이 보인다. 미해소 노드만 따로 보려면:

```cypher
MATCH (n:Entity {unresolved: true}) RETURN n.canonical_id, n.name
```

예상 결과 — `LangChain` 한 건:

```
+--------------------------------------------+
| n.canonical_id            | n.name         |
+--------------------------------------------+
| "ent-unresolved-langchain" | "LangChain"   |
+--------------------------------------------+
```

이 쿼리가 나중에 "표준 엔티티로 보강할 대상" 을 찾는 출발점이다.

---

## 정리

```bash
docker compose down       # 컨테이너 제거(볼륨 유지 — 데이터 보존)
# docker compose down -v  # 데이터까지 완전 삭제할 때만
```

완료 기준 재확인: `python ingest_bulk.py` 가 `nodes=14 rels=11 events=2` 를 찍고, `python verify_idempotent.py` 가 1차·2차 같은 카운트로 `[OK] idempotent` 를 찍었으면 이 토픽은 끝이다. 적재된 그래프는 다음 토픽 3/03 멀티홉 Cypher 의 입력이 된다.
