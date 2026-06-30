"""ReadOnlyGuard — 에이전트/LLM 이 만든 Cypher 를 그래프에 던지기 전 "읽기 전용" 임을 보장한다.

왜 필요한가:
  Phase 4 GraphRAG retriever, Phase 7 Agent Harness 의 graph_query 도구는 LLM 이 만든 Cypher 를
  실행한다(Text-to-Cypher). LLM 이 실수로(또는 프롬프트 인젝션으로) `MATCH (n) DETACH DELETE n` 을
  내놓으면 그래프가 통째로 날아간다. 그래서 실행 직전에 "이건 읽기 질의가 맞는가" 를 강제하는 가드가 필요하다.

단일 메커니즘에 의존하지 않는다. 3층으로 막는다:

  1층 정적 검증(주 신뢰 경계):
     EXPLAIN 으로 플랜을 컴파일해 쓰기 연산자(CreateNode/MergeNode/DeleteNode/SetProperty/...)가
     있는지 검사한다. EXPLAIN 은 실행하지 않으므로 이 검사 자체는 안전하다. 이게 1순위 판별이다.
     보조로 키워드 deny-list(CREATE/MERGE/DELETE/SET/REMOVE/...)와 다중 구문(세미콜론) 차단을 둔다.
     단순 정규식만으로는 문자열 리터럴·주석 안의 키워드에 오탐/누락이 나기 때문에, "플랜 검사를 주,
     키워드를 보조" 로 둔다.

  2층 읽기 트랜잭션(심층 방어):
     session.execute_read(...) 로 실행한다. 자동 재시도가 붙는다.

  3층 권한(가능하면, 인프라 최후 방어선):
     읽기 전용 Neo4j 사용자/역할(RBAC, Enterprise) 또는 별도 read 계정. 코드 밖에서 건다.

⚠️ 흔한 오해 — access mode 로는 못 막는다:
     driver.session(default_access_mode=neo4j.READ_ACCESS) 는 클러스터 라우팅 힌트일 뿐
     접근 제어를 강제하지 않는다(공식 문서 명시). read 세션에서도 서버가 write 를 허용할 수 있다.
     그러므로 access mode 만 믿으면 안 된다. 1층(EXPLAIN 기반 정적 검증)이 주 신뢰 경계가 되어야 한다.

전제:
  - Neo4j 5.26 기동 + 02 적재(03/04 와 같은 그래프).
  - pip install -r requirements.txt
  - 접속 정보 환경변수(02/03/04 규약과 동일):
      NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD (기본 bolt://localhost:7687 / neo4j / testpassword1)
  - API 키·임베딩 불필요.

실행:
  python readonly_guard.py            # 통과/거부 케이스 자가 테스트(서버 연결 필요)
"""

import os
import re
import sys
from dataclasses import dataclass

from neo4j import GraphDatabase

# --- 접속 정보(02/03/04 규약과 동일) ----------------------------------------
URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
AUTH = (
    os.environ.get("NEO4J_USER", "neo4j"),
    os.environ.get("NEO4J_PASSWORD", "testpassword1"),
)

# 플랜에 이 연산자들이 하나라도 보이면 쓰기 질의다. 대소문자 무시로 부분 일치 검사한다.
# (Neo4j 플랜 연산자명: CreateNode, CreateRelationship, MergeNode, Merge, Delete, DetachDelete,
#  SetProperty, SetLabels, RemoveProperty, RemoveLabels, Foreach, LoadCSV, EmptyResult 등)
WRITE_PLAN_OPERATORS = (
    "create",
    "merge",
    "delete",
    "set",        # SetProperty / SetLabels
    "remove",
    "foreach",
    "loadcsv",    # LOAD CSV
)

# 보조 deny-list. 단어 경계로 매칭한다. 플랜 검사가 주, 이건 보조(이중 안전망)다.
# CALL ... 의 쓰기 프로시저(db.create.*, apoc.* write, dbms.*, gds.*.write 등)도 막는다.
WRITE_KEYWORDS = (
    "create", "merge", "delete", "detach", "set", "remove",
    "foreach", "load csv", "drop",
)
WRITE_PROCEDURE_PATTERNS = (
    r"\bdbms\.",                      # dbms.* (관리)
    r"\bdb\.create",                  # db.create.* (라벨/타입 생성)
    r"\bapoc\.(create|merge|refactor|periodic)\.",  # apoc 쓰기 계열
    r"\bgds\.\w+\.write\b",           # gds.*.write 모드
)


@dataclass
class GuardResult:
    """가드 판정 결과. allowed=False 면 reason 에 거부 사유가 담긴다."""
    allowed: bool
    reason: str = ""


def _strip_comments(cypher: str) -> str:
    """// 한 줄 주석과 /* */ 블록 주석을 지운 사본을 만든다(키워드 검사 오탐 방지용).

    플랜 검사가 주 신뢰 경계라 주석 우회는 1층 플랜에서 이미 막히지만,
    보조 키워드 검사도 주석에 속지 않게 정리해 둔다.
    """
    no_block = re.sub(r"/\*.*?\*/", " ", cypher, flags=re.DOTALL)
    no_line = re.sub(r"//[^\n]*", " ", no_block)
    return no_line


def _has_multiple_statements(cypher: str) -> bool:
    """세미콜론으로 구문을 둘 이상 이어 붙였는지 본다(읽기 질의 + 숨긴 쓰기 질의 패턴 차단).

    문자열 리터럴 안의 ; 는 무시한다. 끝의 단일 ; 하나는 허용한다.
    """
    stripped = _strip_comments(cypher)
    # 따옴표 안 내용을 placeholder 로 치환해 리터럴 속 ; 를 무시한다.
    no_strings = re.sub(r"'(?:[^'\\]|\\.)*'", "''", stripped)
    no_strings = re.sub(r'"(?:[^"\\]|\\.)*"', '""', no_strings)
    parts = [p for p in no_strings.split(";") if p.strip()]
    return len(parts) > 1


def _keyword_denylist_hit(cypher: str) -> str | None:
    """보조 키워드 deny-list. 걸리면 사유 문자열, 아니면 None."""
    text = _strip_comments(cypher)
    # 문자열 리터럴 제거(리터럴 안의 'CREATE' 같은 단어를 키워드로 오인하지 않게).
    text = re.sub(r"'(?:[^'\\]|\\.)*'", "''", text)
    text = re.sub(r'"(?:[^"\\]|\\.)*"', '""', text)
    lowered = text.lower()
    for kw in WRITE_KEYWORDS:
        if re.search(rf"(?<![\w]){re.escape(kw)}(?![\w])", lowered):
            return f"쓰기 키워드 '{kw.upper()}' 감지(보조 deny-list)"
    for pat in WRITE_PROCEDURE_PATTERNS:
        if re.search(pat, lowered):
            return f"쓰기 프로시저 패턴 '{pat}' 감지(보조 deny-list)"
    return None


class ReadOnlyGuard:
    """EXPLAIN 플랜 검사(주) + 키워드 deny-list(보조)로 읽기 전용을 보장하고, execute_read 로 실행한다."""

    def __init__(self, driver):
        self._driver = driver

    def _explain_is_write(self, cypher: str) -> tuple[bool, str]:
        """EXPLAIN 으로 플랜을 컴파일해 쓰기 연산자 존재 여부를 본다.

        EXPLAIN 은 실행하지 않으므로 read/write 판별에 안전하게 쓸 수 있다.
        반환: (쓰기여부, 발견한 연산자명 또는 "")
        """
        with self._driver.session() as session:
            result = session.run(f"EXPLAIN {cypher}")
            summary = result.consume()
        plan = summary.plan  # EXPLAIN 은 .plan(실행 안 함). PROFILE 만 .profile.
        if plan is None:
            # 플랜을 못 받으면 보수적으로 "판별 불가"로 본다(거부 쪽으로).
            return True, "플랜 미수신(판별 불가 — 보수적 거부)"
        found = self._find_write_operator(plan)
        return (found is not None), (found or "")

    @staticmethod
    def _find_write_operator(plan: dict) -> str | None:
        """플랜 트리를 훑어 쓰기 연산자명을 찾으면 그 이름을 돌려준다.

        쓰기 플랜 연산자는 키워드로 시작한다(CreateNode, MergeNode, Delete, DetachDelete,
        SetProperty, SetLabels, RemoveProperty, Foreach, LoadCSV ...). 연산자명을 소문자로
        바꿔 prefix 로 검사한다. "offset" 같은 데 'set' 이 오인되지 않게 startswith 만 쓴다.
        """
        op = (plan.get("operatorType") or "").lower()
        for w in WRITE_PLAN_OPERATORS:
            if op.startswith(w):
                return plan.get("operatorType")
        for child in plan.get("children", []):
            hit = ReadOnlyGuard._find_write_operator(child)
            if hit:
                return hit
        return None

    def assert_read_only(self, cypher: str) -> GuardResult:
        """질의가 읽기 전용인지 판정한다. 통과면 allowed=True, 아니면 사유 포함 거부.

        검사 순서:
          (0) 다중 구문(세미콜론) 차단 — 숨긴 쓰기 구문 방지.
          (1) EXPLAIN 플랜에 쓰기 연산자가 있으면 거부(주 신뢰 경계).
          (2) 보조 키워드 deny-list 에 걸리면 거부(이중 안전망).
        """
        if not cypher or not cypher.strip():
            return GuardResult(False, "빈 질의")

        if _has_multiple_statements(cypher):
            return GuardResult(False, "다중 구문(세미콜론) 감지 — 단일 읽기 질의만 허용")

        try:
            is_write, op = self._explain_is_write(cypher)
        except Exception as exc:
            # 문법 오류 등으로 EXPLAIN 자체가 실패하면 실행 전에 막는다.
            return GuardResult(False, f"EXPLAIN 실패(문법/권한 등): {type(exc).__name__}: {exc}")
        if is_write:
            return GuardResult(False, f"쓰기 연산자 '{op}' 가 플랜에 있음(정적 검증 1층)")

        kw_hit = _keyword_denylist_hit(cypher)
        if kw_hit:
            return GuardResult(False, kw_hit)

        return GuardResult(True, "읽기 전용 확인")

    def run_read(self, cypher: str, **params) -> list[dict]:
        """가드를 통과시킨 뒤 execute_read(2층)로 실행한다. 거부되면 PermissionError 를 던진다."""
        verdict = self.assert_read_only(cypher)
        if not verdict.allowed:
            raise PermissionError(f"ReadOnlyGuard 거부: {verdict.reason}")
        with self._driver.session() as session:
            return session.execute_read(
                lambda tx: [r.data() for r in tx.run(cypher, **params)]
            )


# === 자가 테스트(서버 연결 필요) =============================================
# 통과해야 하는 읽기 질의와 거부돼야 하는 쓰기/우회 시도를 한자리에 모았다.
READ_OK_CASES = [
    ("단순 조회", "MATCH (e:Entity {name: 'LightRAG'}) RETURN e.name, e.type"),
    ("집계", "MATCH (e:Entity) RETURN e.type AS t, count(*) AS c ORDER BY c DESC"),
    ("멀티홉", "MATCH (a:Entity {name:'RAG'})-[*1..2]-(b:Entity) RETURN DISTINCT b.name LIMIT 10"),
    # 문자열 리터럴 안에 'CREATE' 가 있어도 실제로는 읽기다(키워드 오탐 방지 확인용).
    ("리터럴 속 키워드", "MATCH (e:Entity) WHERE e.name CONTAINS 'CREATE' RETURN e.name"),
]

WRITE_DENY_CASES = [
    ("CREATE", "CREATE (x:Hacker {name:'oops'})"),
    ("MERGE", "MERGE (x:Entity {name:'RAG'}) RETURN x"),
    ("SET", "MATCH (e:Entity {name:'RAG'}) SET e.hacked = true RETURN e"),
    ("DETACH DELETE", "MATCH (n) DETACH DELETE n"),
    ("REMOVE", "MATCH (e:Entity {name:'RAG'}) REMOVE e.type RETURN e"),
    ("다중 구문 우회", "MATCH (e:Entity) RETURN e LIMIT 1; CREATE (x:Hacker)"),
    ("주석 뒤 쓰기", "MATCH (e:Entity) RETURN e // 그냥 읽기\nCREATE (x:Hacker)"),
]


def _self_test() -> int:
    failures = 0
    with GraphDatabase.driver(URI, auth=AUTH) as driver:
        driver.verify_connectivity()
        guard = ReadOnlyGuard(driver)

        print("=" * 60)
        print("통과해야 하는 읽기 질의")
        print("=" * 60)
        for label, q in READ_OK_CASES:
            v = guard.assert_read_only(q)
            mark = "PASS" if v.allowed else "FAIL"
            if not v.allowed:
                failures += 1
            print(f"  [{mark}] {label:<16} → allowed={v.allowed}  {v.reason}")

        print("\n" + "=" * 60)
        print("거부돼야 하는 쓰기/우회 시도")
        print("=" * 60)
        for label, q in WRITE_DENY_CASES:
            v = guard.assert_read_only(q)
            mark = "PASS" if not v.allowed else "FAIL"
            if v.allowed:
                failures += 1
            print(f"  [{mark}] {label:<16} → allowed={v.allowed}  {v.reason}")

    print("\n" + "-" * 60)
    if failures == 0:
        print("[OK] 모든 케이스 기대대로 동작(읽기 통과, 쓰기 거부).")
        return 0
    print(f"[FAIL] {failures} 개 케이스가 기대와 다르다.")
    return 1


if __name__ == "__main__":
    try:
        sys.exit(_self_test())
    except Exception as exc:
        print(f"[FAIL] {type(exc).__name__}: {exc}", file=sys.stderr)
        print("  - Neo4j 가 떠 있고 02 적재가 끝났는지 확인하라(EXPLAIN 은 서버 연결이 필요).",
              file=sys.stderr)
        print("  - 접속 환경변수 NEO4J_URI/USER/PASSWORD 를 확인하라.", file=sys.stderr)
        sys.exit(1)
