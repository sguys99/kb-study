# Lab 3.1 — Neo4j Fundamentals 핸즈온

`practice/`의 코드를 순서대로 돌려 본다. 각 단계에 **예상 출력**을 붙였다. 실제 출력과 대조하라.

전제: Docker / Docker Compose, Python 3.11+, `practice/` 디렉토리에서 실행.

```bash
cd ../practice    # 이 lab 기준 practice 로 이동
```

---

## 1단계 — Neo4j 5.26 기동

```bash
docker compose up -d
docker compose ps
```

예상 출력(요지):

```
NAME        IMAGE         STATUS                   PORTS
kb-neo4j    neo4j:5.26    Up (healthy)             0.0.0.0:7474->7474/tcp, 0.0.0.0:7687->7687/tcp
```

`STATUS`가 `Up (healthy)`가 될 때까지 기다린다(첫 기동은 30초~1분). 로그로 확인하려면:

```bash
docker compose logs neo4j | grep -i started
```

예상 출력:

```
kb-neo4j  | ... INFO  Started.
```

`(healthy)`가 안 뜨면 헬스체크가 아직 통과 못 한 것이다. 잠시 더 기다리거나 `docker compose logs neo4j`로 오류를 본다.

---

## 2단계 — Browser 접속 확인

브라우저에서 `http://localhost:7474` 접속. 로그인 화면에 입력:

- Connect URL: `bolt://localhost:7687`
- Username: `neo4j`
- Password: `testpassword1`

로그인되면 빈 그래프 화면이 뜬다. `NEO4J_AUTH`를 미리 줬으므로 비밀번호 강제 변경 화면은 나오지 않는다.

---

## 3단계 — Python Driver 연결

```bash
pip install -r requirements.txt
python connect.py
```

예상 출력:

```
[OK] connected to bolt://localhost:7687 as neo4j
[OK] query result: pong
[INFO] Neo4j Kernel 5.26.x (community)
```

`[FAIL] ... ServiceUnavailable`이 나오면 컨테이너가 아직 안 떴거나 포트를 7474로 잘못 준 경우다.

---

## 4단계 — MERGE 적재 + idempotent 확인

```bash
python transactions.py
```

예상 출력:

```
[1회차] nodes=5 rels=3
[2회차] nodes=5 rels=3
[OK] idempotent 확인 — 두 번 적재해도 노드·관계 수가 동일하다.
```

핵심은 1회차와 2회차 수가 같다는 것이다. 스크립트를 다시 돌려도(`python transactions.py`) 여전히 `nodes=5 rels=3`이다. MERGE가 키로 노드를 재사용하기 때문이다. Browser에서 확인:

```cypher
MATCH (n:Entity) RETURN n
```

LightRAG·Neo4j·RAG·Self-RAG·CRAG 5개 노드와 `USES`·`IMPROVES` 관계가 보인다.

---

## 5단계 — 제약/인덱스 생성과 확인

cypher-shell로 한 번에 실행:

```bash
cat indexes.cypher | docker exec -i kb-neo4j cypher-shell -u neo4j -p testpassword1
```

`SHOW CONSTRAINTS` 예상 출력(요지):

```
+----------------------------------------------------------------------------+
| name                  | type       | labelsOrTypes | properties        |
+----------------------------------------------------------------------------+
| "entity_canonical_id" | "UNIQUENESS" | ["Entity"]  | ["canonical_id"]  |
+----------------------------------------------------------------------------+
```

`SHOW INDEXES` 예상 출력(요지) — 제약이 만든 백킹 인덱스와 `entity_name` 인덱스가 함께 보인다:

```
| name                  | type    | labelsOrTypes | properties       | state    |
| "entity_canonical_id" | "RANGE" | ["Entity"]    | ["canonical_id"] | "ONLINE" |
| "entity_name"         | "RANGE" | ["Entity"]    | ["name"]         | "ONLINE" |
```

`state`가 `ONLINE`이어야 쓸 준비가 된 것이다.

---

## 6단계 — GDS 개요 확인

```bash
cat gds_overview.cypher | docker exec -i kb-neo4j cypher-shell -u neo4j -p testpassword1
```

`gds.version()` 예상 출력(요지):

```
+---------------+
| gds_version   |
+---------------+
| "2.x.x"       |
+---------------+
```

버전 문자열이 찍히면 GDS 플러그인이 정상 활성화된 것이다. 카탈로그에서는 `gds.pageRank.*`·`gds.leiden.*` 같은 항목이 보인다. 이 알고리즘들을 실제로 돌리는 건 토픽 06이다.

값이 안 나오고 `Unknown function 'gds.version'` 오류가 나면 `NEO4J_PLUGINS` 설정이 안 먹은 것이다. `docker compose down && docker compose up -d`로 재기동한다.

---

## 정리

```bash
docker compose down       # 컨테이너 제거(볼륨 유지 — 데이터 보존)
# docker compose down -v  # 데이터까지 완전 삭제할 때만
```

완료 기준 재확인: 컨테이너가 healthy로 뜨고, `connect.py`가 pong을 받고, `transactions.py`가 두 번 다 `nodes=5 rels=3`을 찍었으면 이 토픽은 끝이다.
