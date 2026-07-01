"""cypher_safety.py — LLM 이 생성한 Cypher 를 '실행 전에' 정적 검사하는 Safety Guard.

02 의 text2cypher 경로는 생성된 Cypher 를 그대로 실행할 위험이 남아 있었다(02 코드 주석 참고).
여기서 그 구멍을 막는다. 실행 전에 문자열을 검사해 위험하면 (False, 사유) 로 거부한다.

방어선은 세 겹이다(defense in depth):
  (1) 정적 Safety Guard  ← 이 파일. deny-list + 구조 검사 + LIMIT 강제.
  (2) execute_read       ← 02 graph_backend.Neo4jBackend.run_read. 읽기 전용 트랜잭션.
  (3) Neo4j read-only 사용자 권한 ← DB 레벨 최종 방어선. 코드가 아니라 운영 설정(아래 주석).

왜 파서가 아니라 정규식/토큰 기반인가:
  - 완전한 Cypher 파서는 과하다. deny-list + 몇 가지 구조 검사가 투명하고 유지보수하기 쉽다.
  - '완벽'을 코드가 책임지지 않는다. 최종 방어선은 (3) DB 권한이다. Guard 는 실수를 대부분 걸러
    비용·사고를 줄이는 1차 필터다. 이 한계를 분명히 알고 3중으로 겹친다.

전제: 표준 라이브러리(re)만. API 키·Neo4j 불필요.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# ── (1) 쓰기·부작용 키워드 deny-list ────────────────────────────────────────
# 단어 경계(\b)로 매칭해 'CREATED_BY' 같은 관계 타입 이름의 오탐을 줄인다.
# 대소문자 무시. 하나라도 걸리면 거부.
_WRITE_KEYWORDS = [
    "CREATE", "MERGE", "DELETE", "DETACH", "SET", "REMOVE", "DROP",
    "FOREACH", "LOAD CSV",
]

# 부작용을 내는 프로시저 접두. apoc.* 중 쓰기 계열, dbms.*(관리), db.* 일부.
# 읽기 전용 프로시저(db.index.*.queryNodes 등)까지 막지 않으려고 '쓰기 냄새'만 좁게 잡는다.
_DANGEROUS_PROC_PATTERNS = [
    r"\bapoc\.(create|merge|refactor|periodic|trigger|load|export|do)\b",
    r"\bdbms\.",
    r"\bdb\.(create|drop|clear)",
]

# 서브쿼리 CALL { ... } 는 그 안에 쓰기를 숨길 수 있어 통째로 거부(읽기 전용 하니스 기준).
_CALL_SUBQUERY = re.compile(r"\bCALL\s*\{", re.IGNORECASE)

# 홉 상한 없는 가변 길이 경로: [*], [*..], [*2..] 처럼 상한이 비면 폭발 위험.
# [*..4], [*1..3] 처럼 상한 숫자가 있으면 허용. 상한이 MAX_HOPS 초과면 거부.
_VAR_LENGTH = re.compile(r"\[\s*[a-zA-Z_]*\s*\*\s*(\d*)\s*\.?\.?\s*(\d*)\s*\]")

MAX_HOPS = 5           # 가변 길이 경로 상한. 이보다 크거나 상한이 없으면 거부.
DEFAULT_LIMIT = 50     # LIMIT 이 없으면 강제로 붙일 값.


@dataclass
class SafetyResult:
    """검사 결과. safe=False 면 reason 에 거부 사유, safe=True 면 (필요 시) 보강된 cypher."""

    safe: bool
    reason: str | None = None
    cypher: str | None = None  # 통과 시: LIMIT 이 보강됐을 수 있는 최종 Cypher.


def _strip_string_literals(cypher: str) -> str:
    """따옴표 안 문자열을 지운다. 문자열 리터럴 속 'CREATE' 같은 값의 오탐을 막는다.

    예: MATCH (n {name: 'CREATE THE FUTURE'}) 의 'CREATE' 는 키워드가 아니다.
    검사는 리터럴을 제거한 사본에서만 한다(원본은 그대로 실행).
    """
    # '...' 와 "..." 리터럴을 공백으로 치환(백슬래시 이스케이프까지 완벽히 다루진 않는다 — 근사).
    no_single = re.sub(r"'(?:[^'\\]|\\.)*'", " ", cypher)
    no_double = re.sub(r'"(?:[^"\\]|\\.)*"', " ", no_single)
    return no_double


def _count_statements(scrubbed: str) -> int:
    """세미콜론으로 구분되는 구문 수. 다중 구문(;)은 주입 통로라 1개만 허용한다."""
    parts = [p for p in scrubbed.split(";") if p.strip()]
    return len(parts)


def _has_write_keyword(scrubbed: str) -> str | None:
    upper = scrubbed.upper()
    for kw in _WRITE_KEYWORDS:
        # 'LOAD CSV' 는 공백 포함이라 그대로, 단어형은 \b 경계로.
        pattern = re.escape(kw) if " " in kw else rf"\b{re.escape(kw)}\b"
        if re.search(pattern, upper):
            return kw
    return None


def _has_dangerous_proc(scrubbed: str) -> str | None:
    for pat in _DANGEROUS_PROC_PATTERNS:
        m = re.search(pat, scrubbed, re.IGNORECASE)
        if m:
            return m.group(0)
    return None


def _var_length_violation(scrubbed: str) -> str | None:
    """가변 길이 경로의 상한을 검사. 상한 없음 또는 MAX_HOPS 초과면 사유 문자열, 없으면 None."""
    for m in _VAR_LENGTH.finditer(scrubbed):
        upper = m.group(2) or m.group(1)  # [*..N]->group2, [*N]->group1
        if not upper:
            return f"가변 길이 경로에 홉 상한이 없다: {m.group(0)!r} (상한 {MAX_HOPS} 이하 필요)"
        if int(upper) > MAX_HOPS:
            return f"가변 길이 경로 상한이 너무 크다: {m.group(0)!r} (>{MAX_HOPS})"
    return None


def _ensure_limit(cypher: str, scrubbed: str) -> str:
    """LIMIT 이 없으면 끝에 강제로 붙인다. 결과 폭주로 인한 비용·지연을 막는 안전망.

    이미 LIMIT 이 있으면 건드리지 않는다(값 검증은 하지 않는다 — 있으면 작성자 의도로 본다).
    """
    if re.search(r"\bLIMIT\b", scrubbed, re.IGNORECASE):
        return cypher
    return f"{cypher.rstrip().rstrip(';')} LIMIT {DEFAULT_LIMIT}"


def is_safe(cypher: str) -> SafetyResult:
    """생성된 Cypher 한 건을 정적 검사한다.

    반환:
      SafetyResult(safe=False, reason=...)             거부. reason 에 사유.
      SafetyResult(safe=True, cypher=<보강본>)          통과. LIMIT 이 보강됐을 수 있음.

    검사 순서(가장 위험한 것부터):
      1) 빈 질의 거부
      2) 다중 구문(;) 거부
      3) 쓰기 키워드(CREATE/MERGE/DELETE/SET/REMOVE/DROP/FOREACH/LOAD CSV) 거부
      4) 위험 프로시저(apoc 쓰기·dbms.*·db.create 등) 거부
      5) CALL { ... } 서브쿼리 거부(쓰기 은닉 방지)
      6) 반드시 MATCH 로 시작(읽기 진입점 강제)
      7) 가변 길이 경로 홉 상한 검사
      8) 통과 시 LIMIT 강제 보강
    """
    if not cypher or not cypher.strip():
        return SafetyResult(safe=False, reason="빈 Cypher")

    scrubbed = _strip_string_literals(cypher)

    if _count_statements(scrubbed) > 1:
        return SafetyResult(safe=False, reason="다중 구문 금지: 세미콜론(;)으로 구문이 둘 이상이다")

    kw = _has_write_keyword(scrubbed)
    if kw:
        return SafetyResult(safe=False, reason=f"쓰기/부작용 키워드 금지: {kw!r} 발견")

    proc = _has_dangerous_proc(scrubbed)
    if proc:
        return SafetyResult(safe=False, reason=f"위험 프로시저 금지: {proc!r} 발견")

    if _CALL_SUBQUERY.search(scrubbed):
        return SafetyResult(safe=False, reason="CALL {...} 서브쿼리 금지(쓰기 은닉 방지)")

    # 읽기 진입점 강제: 정규화해 MATCH 또는 (드물게) 읽기용 UNWIND/WITH/RETURN 로 시작해야 한다.
    head = scrubbed.strip().upper()
    if not (head.startswith("MATCH") or head.startswith("WITH") or head.startswith("UNWIND")
            or head.startswith("RETURN") or head.startswith("OPTIONAL MATCH")):
        return SafetyResult(
            safe=False,
            reason="읽기 진입점 아님: MATCH/OPTIONAL MATCH/WITH/UNWIND/RETURN 로 시작해야 한다",
        )

    vl = _var_length_violation(scrubbed)
    if vl:
        return SafetyResult(safe=False, reason=vl)

    return SafetyResult(safe=True, cypher=_ensure_limit(cypher, scrubbed))


# ── (3) Neo4j read-only 사용자 권한 — 코드가 아니라 운영 설정으로 두는 최종 방어선 ──
# Guard 와 execute_read 를 뚫더라도 DB 계정 자체에 쓰기 권한이 없으면 아무 것도 못 바꾼다.
# 실전에서는 하니스 전용 계정에 읽기 롤만 부여한다(관리자 계정으로 붙지 않는다):
#
#   CREATE ROLE reader IF NOT EXISTS;
#   GRANT MATCH {*} ON GRAPH neo4j TO reader;      // 노드·관계·속성 읽기
#   GRANT TRAVERSE ON GRAPH neo4j TO reader;
#   CREATE USER harness SET PASSWORD 'change-me' CHANGE NOT REQUIRED;
#   GRANT ROLE reader TO harness;
#
# 그러면 NEO4J_USER=harness 로 접속했을 때 CREATE/DELETE 는 권한 오류로 막힌다.
# 이 3중 구조(정적 Guard → execute_read → DB 권한)가 실전 안전의 핵심이다.


if __name__ == "__main__":
    # 위험/정상 케이스를 한 번에 돌려 Guard 동작을 눈으로 확인한다.
    cases = [
        ("정상: 이웃 조회", "MATCH (x {name:'Self-RAG'})-[r]-(nb) RETURN nb.name LIMIT 10"),
        ("정상: LIMIT 없음(보강됨)", "MATCH (n:Method) RETURN n.name"),
        ("정상: 문자열 속 CREATE(오탐 아님)", "MATCH (n {name:'CREATE THE FUTURE'}) RETURN n"),
        ("위험: 노드 생성", "CREATE (n:Method {name:'evil'}) RETURN n"),
        ("위험: MATCH 뒤 DELETE", "MATCH (n:Method) DETACH DELETE n"),
        ("위험: SET 로 속성 변경", "MATCH (n) SET n.hacked = true RETURN n"),
        ("위험: 다중 구문 주입", "MATCH (n) RETURN n; DROP INDEX foo"),
        ("위험: LOAD CSV", "LOAD CSV FROM 'file:///x.csv' AS row RETURN row"),
        ("위험: apoc 쓰기", "CALL apoc.create.node(['X'],{}) YIELD node RETURN node"),
        ("위험: CALL 서브쿼리", "MATCH (n) CALL { CREATE (:X) } RETURN n"),
        ("위험: 무상한 가변 경로", "MATCH p=(a)-[*]-(b) RETURN p"),
        ("위험: 과대 홉 경로", "MATCH p=(a)-[*..99]-(b) RETURN p"),
    ]
    print("=== Cypher Safety Guard 검사 ===\n")
    for label, cy in cases:
        r = is_safe(cy)
        if r.safe:
            print(f"[PASS ] {label}")
            print(f"        입력 : {cy}")
            print(f"        실행 : {r.cypher}\n")
        else:
            print(f"[BLOCK] {label}")
            print(f"        입력 : {cy}")
            print(f"        사유 : {r.reason}\n")

    # 자체검증(assert) — 완료 기준을 코드로 못박는다.
    assert is_safe("CREATE (n) RETURN n").safe is False
    assert is_safe("MATCH (n) DETACH DELETE n").safe is False
    assert is_safe("MATCH (n) SET n.x=1 RETURN n").safe is False
    assert is_safe("MATCH (n) RETURN n; DROP INDEX foo").safe is False
    assert is_safe("LOAD CSV FROM 'x' AS r RETURN r").safe is False
    assert is_safe("MATCH p=(a)-[*]-(b) RETURN p").safe is False
    assert is_safe("MATCH p=(a)-[*..99]-(b) RETURN p").safe is False
    ok = is_safe("MATCH (n:Method) RETURN n.name")
    assert ok.safe is True and "LIMIT" in ok.cypher.upper()  # LIMIT 자동 보강
    assert is_safe("MATCH (n {name:'CREATE THE FUTURE'}) RETURN n").safe is True  # 오탐 아님
    print("[assert] Safety Guard 자체검증 통과")
