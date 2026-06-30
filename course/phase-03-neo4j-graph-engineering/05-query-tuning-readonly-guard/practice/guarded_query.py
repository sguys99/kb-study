"""guarded_query — ReadOnlyGuard 를 거쳐 Cypher 를 실행하는 데모.

이것이 Phase 7 Agent Harness 의 graph_query 도구가 할 일의 축소판이다. 에이전트가 만든
Cypher 한 줄을 받아, 가드로 읽기 전용인지 확인하고, 통과하면 결과를 돌려주고, 아니면 거부 사유를 돌려준다.
에이전트는 "도구가 거부했다" 는 사실과 사유를 받아 질의를 고쳐 다시 시도하면 된다.

전제:
  - readonly_guard.py 와 같은 디렉토리. Neo4j 5.26 기동 + 02 적재(03/04 와 같은 그래프).
  - pip install -r requirements.txt
  - 접속 정보 환경변수(02/03/04 규약과 동일): NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD
  - API 키·임베딩 불필요.

실행:
  python guarded_query.py                                   # 읽기 한 건 실행 + 쓰기 거부 시연
  python guarded_query.py --cypher "MATCH (e:Entity) RETURN count(e) AS n"   # 임의 질의 투입
"""

import argparse
import json
import os
import sys

from neo4j import GraphDatabase

from readonly_guard import ReadOnlyGuard

URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
AUTH = (
    os.environ.get("NEO4J_USER", "neo4j"),
    os.environ.get("NEO4J_PASSWORD", "testpassword1"),
)


def run_guarded(guard: ReadOnlyGuard, cypher: str, **params) -> dict:
    """에이전트 도구가 돌려줄 법한 모양의 결과 dict 를 만든다.

    통과: {"ok": True, "rows": [...], "count": n}
    거부: {"ok": False, "error": "거부 사유"}
    """
    verdict = guard.assert_read_only(cypher)
    if not verdict.allowed:
        return {"ok": False, "error": verdict.reason}
    rows = guard.run_read(cypher, **params)
    return {"ok": True, "rows": rows, "count": len(rows)}


def _print_result(title: str, cypher: str, result: dict) -> None:
    print(f"\n{'=' * 60}\n{title}\nCypher: {cypher}\n{'=' * 60}")
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description="ReadOnlyGuard 를 거친 Cypher 실행 데모")
    parser.add_argument("--cypher", default=None, help="실행할 단일 Cypher(미지정 시 데모)")
    args = parser.parse_args()

    with GraphDatabase.driver(URI, auth=AUTH) as driver:
        driver.verify_connectivity()
        guard = ReadOnlyGuard(driver)

        if args.cypher:
            _print_result("투입 질의", args.cypher, run_guarded(guard, args.cypher))
            return 0

        # 데모 1 — 정상 읽기 질의는 통과해 결과가 나온다.
        ok_q = "MATCH (e:Entity) RETURN e.type AS type, count(*) AS c ORDER BY c DESC"
        _print_result("1) 읽기 질의 — 통과", ok_q, run_guarded(guard, ok_q))

        # 데모 2 — 쓰기 질의는 실행되지 않고 거부 사유만 돌아온다(그래프는 그대로).
        bad_q = "MATCH (e:Entity {name:'RAG'}) SET e.hacked = true RETURN e"
        _print_result("2) 쓰기 질의 — 거부(실행 안 됨)", bad_q, run_guarded(guard, bad_q))

    print("\n[OK] 가드 데모 완료. 거부된 질의는 그래프에 아무 영향도 주지 않았다.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"[FAIL] {type(exc).__name__}: {exc}", file=sys.stderr)
        print("  - Neo4j 가 떠 있고 02 적재가 끝났는지 확인하라.", file=sys.stderr)
        print("  - readonly_guard.py 가 같은 디렉토리에 있는지 확인하라.", file=sys.stderr)
        sys.exit(1)
