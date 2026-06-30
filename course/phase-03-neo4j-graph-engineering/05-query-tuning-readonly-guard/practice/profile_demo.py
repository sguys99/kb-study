"""EXPLAIN · PROFILE 로 03/04 질의를 들여다보고 인덱스 효과를 before/after 로 대조한다.

03/04 는 질의를 "돌아가게" 만들었다. 05 는 같은 질의를 "빠르게" 만든다. 방법은 외우는 게 아니라
들여다보는 것이다. EXPLAIN/PROFILE 가 그 도구다.

  EXPLAIN <query>  : 실행하지 않고 쿼리 플랜만 컴파일해 보여준다. estimated rows(추정 행수)만.
                     데이터 조회·변경 부작용이 전혀 없다. read/write 판별에도 안전하게 쓸 수 있다.
  PROFILE <query>  : 실제로 실행하고 연산자별 db hits(데이터베이스 접근 횟수)와 실제 rows 를 보여준다.
                     db hits 가 비용의 핵심 지표다. 같은 답이라도 db hits 가 작은 플랜이 빠르다.

이 스크립트가 하는 일:
  1) (e:Entity {name: "..."}) 질의를 PROFILE → 인덱스가 없으면 NodeByLabelScan + Filter 가 뜬다.
  2) indexes_constraints.cypher 적용 여부에 따라 db hits 가 어떻게 달라지는지 출력.
  3) 가변 길이 경로 *1..2 vs *1..3 의 db hits 차이로 "상한이 왜 중요한지" 를 보여준다.

전제:
  - Neo4j 5.26 기동 + 02 적재(03/04 와 같은 그래프).
  - pip install -r requirements.txt
  - 접속 정보 환경변수(02/03/04 규약과 동일):
      NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD (기본 bolt://localhost:7687 / neo4j / testpassword1)
  - 임베딩·API 키는 필요 없다. 05 는 읽기 전용 PROFILE/EXPLAIN 만 한다.

실행:
  python profile_demo.py                 # name 질의 PROFILE + 가변 경로 비교
  python profile_demo.py --explain        # PROFILE 대신 EXPLAIN(실행 없이 플랜만)

해석 팁:
  - 플랜에 AllNodesScan / NodeByLabelScan 이 보이고 db hits 가 노드 수에 비례하면, 시작점 인덱스가 없다는 신호다.
  - NodeIndexSeek 이 보이면 인덱스를 타고 있다는 뜻이다(= 좋다).
  - CartesianProduct 가 보이면 두 패턴이 묶이지 않은 것이다(보통 WHERE 누락). 경고 신호다.
"""

import argparse
import os
import sys

from neo4j import GraphDatabase

# --- 접속 정보(02/03/04 규약과 동일) ----------------------------------------
URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
AUTH = (
    os.environ.get("NEO4J_USER", "neo4j"),
    os.environ.get("NEO4J_PASSWORD", "testpassword1"),
)

# 03/04 에서 실제로 쓰던 시작점 질의. name 으로 한 엔티티를 집는다.
NAME_QUERY = """
MATCH (e:Entity {name: $name})
RETURN e.name AS name, e.type AS type, e.canonical_id AS cid
"""

# 가변 길이 경로. 03 의 멀티홉 패턴. 상한만 바꿔 비용 차이를 본다.
PATH_QUERY_TMPL = """
MATCH (a:Entity {{name: $name}})-[*1..{hops}]-(b:Entity)
RETURN count(DISTINCT b) AS reachable
"""


def _profile_keyword(explain_only: bool) -> str:
    """PROFILE 또는 EXPLAIN 접두어를 고른다."""
    return "EXPLAIN" if explain_only else "PROFILE"


def _walk_plan(plan, depth: int = 0) -> list[tuple[int, str, int, int]]:
    """쿼리 플랜 트리를 깊이 우선으로 훑어 (depth, operator, est_rows, db_hits) 목록을 만든다.

    neo4j 드라이버의 result.summary.profile(또는 .plan)은 중첩 dict 다.
    PROFILE 이면 각 노드에 dbHits/rows 가 있고, EXPLAIN 이면 estimatedRows 만 있다.
    """
    if plan is None:
        return []
    args = plan.get("args", {})
    operator = plan.get("operatorType", "?")
    est_rows = int(args.get("EstimatedRows", 0))
    db_hits = int(plan.get("dbHits", args.get("DbHits", 0)) or 0)
    rows = [(depth, operator, est_rows, db_hits)]
    for child in plan.get("children", []):
        rows.extend(_walk_plan(child, depth + 1))
    return rows


def _print_plan(label: str, plan: dict) -> int:
    """플랜을 들여쓰기로 출력하고 db hits 총합을 돌려준다."""
    print(f"\n[{label}]")
    total = 0
    for depth, op, est, hits in _walk_plan(plan):
        indent = "  " * depth
        total += hits
        print(f"  {indent}{op:<24} est_rows={est:<6} dbHits={hits}")
    print(f"  └─ db hits 총합: {total}")
    return total


def run_profile(driver, cypher: str, params: dict, label: str, explain_only: bool) -> int:
    """질의를 PROFILE/EXPLAIN 하고 플랜 출력 + db hits 총합 반환."""
    kw = _profile_keyword(explain_only)
    with driver.session() as session:
        result = session.run(f"{kw} {cypher}", **params)
        # 결과 행을 끝까지 읽어야 PROFILE 의 dbHits 가 집계된다.
        for _ in result:
            pass
        summary = result.consume()
    # PROFILE 이면 summary.profile, EXPLAIN 이면 summary.plan 에 트리가 들어온다.
    plan = summary.profile if summary.profile is not None else summary.plan
    if plan is None:
        print(f"\n[{label}] 플랜을 받지 못했다(드라이버/서버 버전 확인).")
        return 0
    return _print_plan(label, plan)


def demo_name_lookup(driver, explain_only: bool) -> None:
    """이름으로 한 엔티티를 집는 질의의 플랜을 본다.

    인덱스가 없으면 NodeByLabelScan + Filter, entity_name 인덱스가 있으면 NodeIndexSeek 이 뜬다.
    indexes_constraints.cypher 적용 전/후로 이 스크립트를 두 번 돌려 db hits 를 대조하라.
    """
    print("\n" + "=" * 64)
    print("A. 이름으로 시작점 잡기 — (e:Entity {name: 'LightRAG'})")
    print("=" * 64)
    print("  인덱스가 없으면 NodeByLabelScan+Filter, entity_name 인덱스가 있으면 NodeIndexSeek.")
    run_profile(driver, NAME_QUERY, {"name": "LightRAG"}, "name 조회", explain_only)


def demo_varlen_path(driver, explain_only: bool) -> None:
    """가변 길이 경로의 상한이 비용에 미치는 영향을 본다.

    *1..2 와 *1..3 의 db hits 를 비교한다. 상한을 한 칸 늘리면 탐색 공간이 곱으로 커진다.
    그래서 03 에서 *1..2 처럼 상한을 박는 게 중요했다.
    """
    print("\n" + "=" * 64)
    print("B. 가변 길이 경로 상한의 비용 — *1..2 vs *1..3")
    print("=" * 64)
    h2 = run_profile(
        driver, PATH_QUERY_TMPL.format(hops=2), {"name": "RAG"}, "경로 *1..2", explain_only
    )
    h3 = run_profile(
        driver, PATH_QUERY_TMPL.format(hops=3), {"name": "RAG"}, "경로 *1..3", explain_only
    )
    if not explain_only and h2:
        print(f"\n  → 상한을 2에서 3으로 늘리자 db hits {h2} → {h3} "
              f"(약 {h3 / h2:.1f}배). 상한을 박아야 하는 이유다.")


def main() -> int:
    parser = argparse.ArgumentParser(description="EXPLAIN/PROFILE 로 03/04 질의 튜닝 데모")
    parser.add_argument(
        "--explain",
        action="store_true",
        help="PROFILE 대신 EXPLAIN(실행 없이 플랜·추정 행수만)",
    )
    args = parser.parse_args()

    with GraphDatabase.driver(URI, auth=AUTH) as driver:
        driver.verify_connectivity()
        demo_name_lookup(driver, args.explain)
        demo_varlen_path(driver, args.explain)
    kw = "EXPLAIN" if args.explain else "PROFILE"
    print(f"\n[OK] {kw} 데모 완료. "
          "indexes_constraints.cypher 적용 전/후로 두 번 돌려 db hits 를 대조하라.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"[FAIL] {type(exc).__name__}: {exc}", file=sys.stderr)
        print("  - Neo4j 가 떠 있고 02 적재가 끝났는지 확인하라(MATCH (n) RETURN count(n)).",
              file=sys.stderr)
        print("  - 접속 환경변수 NEO4J_URI/USER/PASSWORD 를 확인하라.", file=sys.stderr)
        sys.exit(1)
