# Lab — Query Tuning(EXPLAIN · PROFILE) + Read-only Guard

04 까지 적재·임베딩·인덱싱된 같은 그래프를 대상으로, 03/04 질의를 PROFILE 로 들여다보고 인덱스로 튜닝한 뒤,
에이전트가 던질 Cypher 를 막는 ReadOnlyGuard 를 테스트한다. 각 명령 아래 **예상 출력**이 있다. 대조하며 따라간다.

> 실제 실행·과금 검증은 학습자 몫이다(roadmap 방침). 아래 출력은 동봉 데이터(nodes≈14)를 기준으로 한 예시다.
> db hits 절댓값은 데이터·버전에 따라 달라질 수 있다. **인덱스 전/후로 db hits 가 줄고 연산자가 바뀌는 방향**이 맞는지를 본다.

## 0. 전제 확인

- Neo4j 5.26 가 떠 있고 02 적재가 끝나 있어야 한다(03/04 와 같은 그래프).
- 이 토픽은 임베딩·API 키가 필요 없다. EXPLAIN/PROFILE 과 가드는 Cypher·드라이버만으로 돈다.

## 1. 컨테이너 기동 + 그래프 존재 확인

```bash
cd practice
docker compose up -d
docker compose ps
```

예상 출력(요지):

```
NAME        IMAGE         STATUS                   PORTS
kb-neo4j    neo4j:5.26    Up (healthy)             0.0.0.0:7474->7474/tcp, 0.0.0.0:7687->7687/tcp
```

그래프가 비어 있지 않은지 확인한다.

```bash
docker exec -i kb-neo4j cypher-shell -u neo4j -p testpassword1 \
  "MATCH (n) RETURN count(n) AS nodes;"
```

예상 출력:

```
nodes
14
```

`0` 이 나오면 먼저 02 적재를 끝낸다.

```bash
cd ../../02-bulk-ingest-merge/practice && python ingest_bulk.py && cd -
```

## 2. 의존성 설치

```bash
pip install -r requirements.txt
```

예상 출력(요지): `Successfully installed neo4j-5.x ...`

## 3. 인덱스 추가 *전* PROFILE — 병목을 눈으로 본다

아직 `name`/`canonical_id` 에 인덱스가 없는 상태에서 03/04 질의의 플랜을 본다.

```bash
python profile_demo.py
```

예상 출력(A 부분 — 인덱스 전, 점수는 근삿값):

```
================================================================
A. 이름으로 시작점 잡기 — (e:Entity {name: 'LightRAG'})
================================================================
  인덱스가 없으면 NodeByLabelScan+Filter, entity_name 인덱스가 있으면 NodeIndexSeek.

[name 조회]
  ProduceResults          est_rows=1      dbHits=0
    Filter                est_rows=1      dbHits=14
      NodeByLabelScan     est_rows=14     dbHits=15
  └─ db hits 총합: 29
```

해석: `NodeByLabelScan` 으로 Entity 14개를 다 훑고(`dbHits=15`), `Filter` 로 name 을 거른다(`dbHits=14`).
노드가 14개라 작아 보이지만, 이 패턴은 노드 수에 비례해 커진다. 수만 노드면 그대로 병목이다.

예상 출력(B 부분 — 가변 길이 경로 상한):

```
================================================================
B. 가변 길이 경로 상한의 비용 — *1..2 vs *1..3
================================================================
[경로 *1..2]
  ...
  └─ db hits 총합: 약 90~150

[경로 *1..3]
  ...
  └─ db hits 총합: 약 300~600

  → 상한을 2에서 3으로 늘리자 db hits 90 → 350 (약 3.9배). 상한을 박아야 하는 이유다.
```

해석: 상한을 한 칸 늘리면 탐색 공간이 곱으로 커진다. 03 에서 `*1..2` 처럼 상한을 박은 게 이래서 중요하다.

## 4. 제약·인덱스 추가

```bash
docker exec -i kb-neo4j cypher-shell -u neo4j -p testpassword1 < indexes_constraints.cypher
```

예상 출력(마지막 SHOW INDEXES — 04 인덱스까지 함께 보인다):

```
name                   type        state     labelsOrTypes   properties
"entity_canonical_id"  "RANGE"     "ONLINE"  ["Entity"]      ["canonical_id"]
"entity_embedding"     "VECTOR"    "ONLINE"  ["Entity"]      ["embedding"]
"entity_fulltext"      "FULLTEXT"  "ONLINE"  ["Entity"]      ["name","description"]
"entity_name"          "RANGE"     "ONLINE"  ["Entity"]      ["name"]
"entity_type"          "RANGE"     "ONLINE"  ["Entity"]      ["type"]
```

`state` 가 `POPULATING` 이면 몇 초 뒤 다시 `SHOW INDEXES` 로 `ONLINE` 을 확인한 뒤 넘어간다.

## 5. 인덱스 추가 *후* PROFILE — db hits 비교

같은 명령을 다시 돌린다.

```bash
python profile_demo.py
```

예상 출력(A 부분 — 인덱스 후):

```
[name 조회]
  ProduceResults          est_rows=1      dbHits=0
    NodeIndexSeek         est_rows=1      dbHits=2
  └─ db hits 총합: 2
```

해석: `NodeByLabelScan + Filter` 가 `NodeIndexSeek` 하나로 바뀌었다. db hits 가 `29 → 2` 로 떨어졌다.
인덱스가 이름으로 노드를 바로 짚어서다. 이게 "Cypher 를 외우지 말고 PROFILE 로 들여다보라" 의 실체다.

### before/after 요약 표

| 질의 | 인덱스 전 | 인덱스 후 | 연산자 변화 |
|------|-----------|-----------|-------------|
| `(:Entity {name:...})` 조회 | db hits ≈ 29 | db hits ≈ 2 | NodeByLabelScan+Filter → NodeIndexSeek |
| 경로 `*1..2` | (변화 작음) | (변화 작음) | 시작점 인덱스로 진입만 빨라짐 |
| 경로 `*1..3` | db hits 큼 | 여전히 큼 | 상한이 비용을 지배 — 상한을 박아라 |

> 핵심: 인덱스는 **시작점을 빨리 잡게** 해 준다. 경로 폭증은 인덱스가 아니라 **상한·방향**으로 잡는다.

## 6. ReadOnlyGuard 자가 테스트 — 읽기 통과 / 쓰기 거부

```bash
python readonly_guard.py
```

예상 출력:

```
============================================================
통과해야 하는 읽기 질의
============================================================
  [PASS] 단순 조회          → allowed=True   읽기 전용 확인
  [PASS] 집계               → allowed=True   읽기 전용 확인
  [PASS] 멀티홉             → allowed=True   읽기 전용 확인
  [PASS] 리터럴 속 키워드    → allowed=True   읽기 전용 확인

============================================================
거부돼야 하는 쓰기/우회 시도
============================================================
  [PASS] CREATE             → allowed=False  쓰기 연산자 'CreateNode' 가 플랜에 있음(정적 검증 1층)
  [PASS] MERGE              → allowed=False  쓰기 연산자 'Merge' 가 플랜에 있음(정적 검증 1층)
  [PASS] SET                → allowed=False  쓰기 연산자 'SetProperty' 가 플랜에 있음(정적 검증 1층)
  [PASS] DETACH DELETE      → allowed=False  쓰기 연산자 'DetachDelete' 가 플랜에 있음(정적 검증 1층)
  [PASS] REMOVE             → allowed=False  쓰기 연산자 'RemoveProperty' 가 플랜에 있음(정적 검증 1층)
  [PASS] 다중 구문 우회      → allowed=False  다중 구문(세미콜론) 감지 — 단일 읽기 질의만 허용
  [PASS] 주석 뒤 쓰기        → allowed=False  쓰기 연산자 'CreateNode' 가 플랜에 있음(정적 검증 1층)

------------------------------------------------------------
[OK] 모든 케이스 기대대로 동작(읽기 통과, 쓰기 거부).
```

> 연산자명(`CreateNode`/`Merge`/`SetProperty` 등)의 정확한 표기는 서버 버전에 따라 조금 다를 수 있다.
> "리터럴 속 키워드" 케이스가 통과하는 게 핵심이다. 단순 정규식이라면 `'CREATE'` 라는 문자열에 오탐했을 텐데,
> 플랜 검사는 실제 동작이 읽기임을 알기에 통과시킨다.

## 7. 가드를 거친 질의 실행 — Agent 도구의 축소판

```bash
python guarded_query.py
```

예상 출력(발췌):

```
============================================================
1) 읽기 질의 — 통과
Cypher: MATCH (e:Entity) RETURN e.type AS type, count(*) AS c ORDER BY c DESC
============================================================
{
  "ok": true,
  "rows": [
    { "type": "Model", "c": 6 },
    { "type": "Tool", "c": 4 },
    ...
  ],
  "count": 5
}

============================================================
2) 쓰기 질의 — 거부(실행 안 됨)
Cypher: MATCH (e:Entity {name:'RAG'}) SET e.hacked = true RETURN e
============================================================
{
  "ok": false,
  "error": "쓰기 연산자 'SetProperty' 가 플랜에 있음(정적 검증 1층)"
}

[OK] 가드 데모 완료. 거부된 질의는 그래프에 아무 영향도 주지 않았다.
```

거부된 쓰기 질의가 그래프를 건드리지 않았는지 직접 확인한다.

```bash
docker exec -i kb-neo4j cypher-shell -u neo4j -p testpassword1 \
  "MATCH (e:Entity {name:'RAG'}) RETURN e.hacked AS hacked;"
```

예상 출력(`hacked` 속성이 생기지 않았다 = 가드가 막았다):

```
hacked
NULL
```

## 8. 임의 질의 투입(선택)

```bash
python guarded_query.py --cypher "MATCH (a:Entity {name:'RAG'})-[*1..2]-(b) RETURN DISTINCT b.name LIMIT 5"
python guarded_query.py --cypher "CREATE (x:Hacker)"
```

첫 질의는 `"ok": true` 로 결과가, 둘째는 `"ok": false` 로 거부 사유가 나오면 성공이다(= 완료 기준 충족).

## 정리(선택)

```bash
docker compose down        # 컨테이너만 제거(볼륨 유지 → 그래프·인덱스 보존)
# docker compose down -v   # 데이터까지 삭제(다시 02 적재부터 해야 함)
```
