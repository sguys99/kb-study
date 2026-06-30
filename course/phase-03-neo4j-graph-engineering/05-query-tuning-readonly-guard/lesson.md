# 3.5 Query Tuning(EXPLAIN · PROFILE) + Read-only Guard

> **Phase 3 · 토픽 05** · 04 까지 만든 같은 그래프를 대상으로, 03/04 질의를 PROFILE 로 들여다보고 인덱스로 빠르게 만든 뒤, 에이전트가 던질 Cypher 를 읽기 전용으로 강제하는 가드를 만든다.

## 학습 목표

이 토픽을 끝내면 다음을 할 수 있다.

- 03/04 의 실제 질의를 EXPLAIN/PROFILE 로 들여다보고, 플랜 연산자(`NodeByLabelScan`·`NodeIndexSeek` 등)와 db hits 로 병목을 읽어 낸다.
- `name`·`canonical_id` 에 제약·인덱스를 추가해 같은 질의의 db hits 가 줄고 연산자가 `NodeIndexSeek` 으로 바뀌는 것을 before/after 로 측정한다.
- LLM·에이전트가 만든 Cypher 를 EXPLAIN 플랜 검사 + 키워드 deny-list + `execute_read` 3층으로 막는 `ReadOnlyGuard` 를 만들어, 읽기는 통과시키고 쓰기는 모두 거부한다.

**완료 기준**: 04에서 쓰던 질의를 PROFILE로 본 db hits가 인덱스·제약 추가 후 눈에 띄게 줄고, ReadOnlyGuard가 정상 읽기 질의는 통과시키고 CREATE/MERGE/SET/DELETE 등 쓰기 시도는 모두 거부하면 완료.

---

## 1. 왜 필요한가 — "돌아간다"와 "빠르고 안전하다"는 다르다

03 과 04 는 질의를 돌아가게 만들었다. 멀티홉으로 경로를 뽑고 벡터·풀텍스트·그래프를 융합했다. 노드가 14개뿐이라 전부 즉시 끝났다. 그래서 한 가지를 놓쳤다. **어떻게** 끝났는지를.

같은 질의가 노드 수만 개짜리 그래프에서도 빠를까. 장담 못 한다. `MATCH (e:Entity {name: "LightRAG"})` 는 그럴듯해 보이지만, 인덱스가 없으면 Neo4j 는 Entity 라벨을 가진 노드를 **전부 훑어** name 을 비교한다. 14개면 안 느껴진다. 5만 개면 매 질의마다 5만 번 비교다.

문제는 또 있다. Phase 4 의 GraphRAG retriever 와 Phase 7 의 Agent Harness 는 사람이 손으로 쓴 Cypher 만 받지 않는다. **LLM 이 만든 Cypher** 를 받아 실행한다(Text-to-Cypher). LLM 이 실수로, 혹은 프롬프트 인젝션에 휘말려 `MATCH (n) DETACH DELETE n` 을 내놓으면? 검색하려다 그래프를 통째로 지운다.

이 토픽은 두 빈자리를 메운다. 질의를 **빠르게**(PROFILE 로 들여다보고 인덱스로 튜닝), 그리고 **안전하게**(읽기 전용 가드). roadmap 의 조언 그대로다. "Cypher 를 외우지 마세요. EXPLAIN/PROFILE 로 질의를 들여다보고, Text-to-Cypher 는 항상 Safety Guard 로 감싸세요."

## 2. EXPLAIN vs PROFILE — 질의를 들여다보는 두 렌즈

`EXPLAIN` 은 질의를 **실행하지 않고** 플랜만 컴파일해 보여준다. 각 연산자에 추정 행수(estimated rows)가 붙는다. 데이터를 읽지도 바꾸지도 않으니 안전하다. 뒤에서 read/write 판별에 쓸 수 있는 것도 이 성질 덕이다.

`PROFILE` 은 질의를 **실제로 실행**하고, 연산자별 **db hits**(데이터베이스 접근 횟수)와 실제 행수를 보여준다. db hits 가 비용의 핵심 지표다. 같은 답을 내도 db hits 가 작은 플랜이 빠르다.

플랜은 연산자 트리다. 자주 보게 될 연산자만 추린다.

- `AllNodesScan` — 라벨 무시하고 모든 노드를 훑는다. 거의 항상 나쁜 신호.
- `NodeByLabelScan` — 한 라벨의 노드를 전부 훑는다. 시작점 인덱스가 없을 때 나온다.
- `NodeIndexSeek` / `NodeIndexScan` — 인덱스를 타고 노드를 짚는다. 좋은 신호.
- `Expand(All)` — 관계를 따라 이웃으로 퍼진다. 멀티홉의 본체.
- `Filter` — 조건으로 거른다. `NodeByLabelScan` 뒤에 붙으면 "훑고 거른다"는 뜻.
- `CartesianProduct` — 두 패턴이 안 묶였다(보통 WHERE 누락). 경고 신호.

## 3. 실습 ① — 인덱스 전/후를 PROFILE 로 대조

03/04 가 시작점을 잡던 `(:Entity {name: ...})` 질의를 PROFILE 로 본다. 인덱스가 없으면 라벨을 훑는다.

```python
# practice/profile_demo.py 의 핵심 — PROFILE 플랜을 트리로 출력하고 db hits 총합을 낸다
def run_profile(driver, cypher: str, params: dict, label: str, explain_only: bool) -> int:
    kw = "EXPLAIN" if explain_only else "PROFILE"
    with driver.session() as session:
        result = session.run(f"{kw} {cypher}", **params)
        for _ in result:          # PROFILE 의 db hits 는 결과를 끝까지 읽어야 집계된다
            pass
        summary = result.consume()
    plan = summary.profile if summary.profile is not None else summary.plan
    return _print_plan(label, plan)   # 연산자·est_rows·dbHits 를 들여쓰기로 출력
```

`name`·`canonical_id` 에 제약·인덱스를 더한다. 유니크 제약은 range 인덱스를 같이 깔아 준다.

```cypher
// practice/indexes_constraints.cypher 의 핵심
CREATE CONSTRAINT entity_canonical_id IF NOT EXISTS
FOR (e:Entity) REQUIRE e.canonical_id IS UNIQUE;   // canonical_id 등호 조회 → NodeIndexSeek

CREATE INDEX entity_name IF NOT EXISTS
FOR (e:Entity) ON (e.name);                        // name 은 유니크가 아닐 수 있어 인덱스만
```

> 전체 코드와 실행 절차는 [`practice/`](practice/) 와 [`labs/`](labs/) 참조.
> 이 토픽은 임베딩·API 키가 필요 없다. EXPLAIN/PROFILE 과 가드는 Cypher·드라이버만으로 돈다.

## 4. 결과 해석 ① — db hits 가 말해 주는 것

인덱스 추가 전후로 같은 name 조회를 PROFILE 하면 이렇게 바뀐다.

```
[인덱스 전]                              [인덱스 후]
Filter            dbHits=14              NodeIndexSeek   dbHits=2
  NodeByLabelScan dbHits=15
db hits 총합: 29                         db hits 총합: 2
```

`NodeByLabelScan + Filter` 두 연산자가 `NodeIndexSeek` 하나로 줄었다. 라벨을 다 훑던 일을 인덱스가 이름으로 바로 짚어서다. 14개 그래프에서도 db hits 가 29에서 2로 떨어진다. 노드가 많아질수록 이 격차는 벌어진다.

가변 길이 경로는 다르다. `*1..2` 를 `*1..3` 으로 한 칸 늘리면 db hits 가 몇 배로 뛴다. 탐색 공간 자체가 커져서라, 인덱스로는 못 잡는다. 그래서 03 에서 상한을 `*1..2` 로 박은 게 중요했다. 인덱스는 **시작점**을 빨리 잡게 하고, 경로 폭증은 **상한·방향**으로 잡는다. 둘은 다른 손잡이다.

## 5. 실습 ② — ReadOnlyGuard, 단일 메커니즘에 의존하지 않는다

에이전트가 만든 Cypher 를 실행 직전에 거른다. 핵심은 **단일 방어선에 기대지 않는 것**이다. 3층으로 쌓는다.

1층은 정적 검증이고, 주 신뢰 경계다. EXPLAIN 으로 플랜을 컴파일해 쓰기 연산자(`CreateNode`·`Merge`·`Delete`·`SetProperty`…)가 있는지 본다. EXPLAIN 은 실행을 안 하니 이 검사 자체가 안전하다. 보조로 키워드 deny-list 와 세미콜론 다중 구문 차단을 둔다. 단순 정규식만 쓰면 `WHERE e.name CONTAINS 'CREATE'` 같은 문자열 리터럴의 `CREATE` 에 오탐한다. 그래서 플랜 검사가 주, 키워드가 보조다.

```python
# practice/readonly_guard.py 의 핵심 — EXPLAIN 플랜에서 쓰기 연산자를 찾는다
def _explain_is_write(self, cypher: str) -> tuple[bool, str]:
    with self._driver.session() as session:
        result = session.run(f"EXPLAIN {cypher}")   # 실행 안 함 → 안전
        summary = result.consume()
    plan = summary.plan                              # EXPLAIN 은 .plan, PROFILE 만 .profile
    if plan is None:
        return True, "플랜 미수신(보수적 거부)"
    found = self._find_write_operator(plan)          # CreateNode/Merge/Delete/Set... 탐색
    return (found is not None), (found or "")
```

2층은 읽기 트랜잭션이다. 가드를 통과한 질의를 `session.execute_read(...)` 로 실행한다. 자동 재시도가 붙는다. 3층은 권한이다. 읽기 전용 Neo4j 사용자·역할(RBAC, Enterprise)이나 별도 read 계정을 코드 밖에서 건다. 인프라 차원의 최후 방어선이다.

여기서 흔히 헛디딘다. `driver.session(default_access_mode=neo4j.READ_ACCESS)` 면 안전하다고 믿는 것. 아니다. access mode 는 **클러스터 라우팅 힌트일 뿐 접근 제어를 강제하지 않는다.** 공식 문서가 명시한 대로, read 세션에서도 서버가 write 를 허용할 수 있다. 그러니 access mode 만 믿지 마라. 주 신뢰 경계는 1층, EXPLAIN 기반 정적 검증이다.

## 6. 결과 해석 ② — 읽기는 통과, 쓰기는 거부

`readonly_guard.py` 의 자가 테스트는 통과해야 할 읽기 질의와 거부돼야 할 쓰기/우회 시도를 함께 던진다.

```
[PASS] 리터럴 속 키워드  → allowed=True   읽기 전용 확인
[PASS] CREATE           → allowed=False  쓰기 연산자 'CreateNode' 가 플랜에 있음(정적 검증 1층)
[PASS] 다중 구문 우회    → allowed=False  다중 구문(세미콜론) 감지 — 단일 읽기 질의만 허용
[PASS] 주석 뒤 쓰기      → allowed=False  쓰기 연산자 'CreateNode' 가 플랜에 있음(정적 검증 1층)
```

`'CREATE'` 가 문자열 안에 있는 읽기 질의는 통과한다. 단순 정규식이라면 여기서 오탐했을 자리다. 플랜 검사는 그 질의의 실제 동작이 읽기임을 알기에 통과시킨다. 반대로 주석 뒤에 숨긴 `CREATE`, 세미콜론으로 이어 붙인 두 번째 구문은 모두 막힌다. 이 가드가 `guarded_query.py` 에서 Agent 도구의 축소판으로 쓰인다. 통과하면 결과를, 거부하면 사유를 돌려준다. 거부된 질의는 그래프에 손도 못 댄다. 이게 Phase 7 graph_query 도구의 Cypher Safety Guard 로 이어진다.

---

## 🚨 자주 하는 실수

1. **`default_access_mode=READ_ACCESS` 면 안전하다고 믿는다** — access mode 는 클러스터 라우팅 힌트지 접근 제어가 아니다. read 세션에서도 서버가 write 를 허용할 수 있다. 주 방어선은 EXPLAIN 기반 정적 검증(1층)이고, access mode 와 권한은 보조·최후 방어선이다.
2. **정규식 키워드 매칭만으로 가드를 만든다** — `WHERE e.name CONTAINS 'CREATE'` 같은 문자열 리터럴이나 `// CREATE` 같은 주석에 오탐하고, 변형된 쓰기 구문은 놓친다. EXPLAIN 으로 플랜을 컴파일해 쓰기 연산자가 있는지 보는 게 1순위다. 키워드는 이중 안전망으로만 둔다.
3. **PROFILE 결과를 끝까지 안 읽고 db hits 가 0 이라고 본다** — PROFILE 은 결과 행을 끝까지 소비해야 db hits 가 집계된다. 드라이버에서 `for _ in result: pass` 후 `consume()` 해야 정확한 수치가 나온다. 그래서 db hits 비교는 PROFILE(실제 실행)로, read/write 판별은 EXPLAIN(실행 안 함)으로 나눠 쓴다.

## 출처

- Neo4j Documentation — https://neo4j.com/docs/
- Neo4j Python Driver Manual(세션·`execute_read`·access mode) — https://neo4j.com/docs/python-manual/current/
- Cypher Manual — Planning and tuning(EXPLAIN/PROFILE·execution plans·인덱스) — https://neo4j.com/docs/cypher-manual/current/planning-and-tuning/

## 다음 토픽

→ [GDS PageRank · Leiden + Graph Quality Dashboard](../06-gds-pagerank-leiden/lesson.md)

