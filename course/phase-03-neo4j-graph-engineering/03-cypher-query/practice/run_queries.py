"""02가 적재한 그래프에서 핵심 멀티홉·경로·집계 Cypher 를 Python Driver 로 실행해 보기 좋게 출력한다.

queries.cypher 와 같은 질의지만, "코드에서 Cypher 를 어떻게 돌리고 결과를 꺼내는지"를 보여주는 게 목적이다.
04 하이브리드 검색에서 그래프 절반은 이렇게 Driver 로 Cypher 를 실행해 후보를 모으는 식으로 동작한다.

전제:
  - 02(bulk-ingest-merge)가 그래프를 적재해 둔 상태(python ingest_bulk.py → nodes=14, rels=11, events=2).
  - Neo4j 5.26 기동 중(bolt://localhost:7687) — docker compose up -d (02 의 compose 재사용 가능).
  - pip install -r requirements.txt
  - 접속 정보는 환경변수에서 읽는다. 미설정 시 02 와 동일한 로컬 docker 기본값.
      NEO4J_URI      (기본 bolt://localhost:7687)
      NEO4J_USER     (기본 neo4j)
      NEO4J_PASSWORD (기본 testpassword1)
  - 이 토픽은 LLM·임베딩 API 를 쓰지 않는다. 키 불필요, 과금 없음(로컬 Neo4j 만).

실행:
  python run_queries.py
"""

import os
import sys

from neo4j import GraphDatabase

# --- 접속 정보(02 규약과 동일) ---------------------------------------------
URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
AUTH = (
    os.environ.get("NEO4J_USER", "neo4j"),
    os.environ.get("NEO4J_PASSWORD", "testpassword1"),
)


def section(title: str) -> None:
    """질의 묶음 구분 헤더."""
    print(f"\n=== {title} ===")


def run_query(driver, title: str, cypher: str, params: dict | None = None) -> list[dict]:
    """Cypher 한 건을 실행하고 결과 레코드를 dict 리스트로 돌려준다.

    execute_read 는 읽기 전용 트랜잭션이라 라우팅·재시도가 자동으로 붙는다.
    여기선 단일 인스턴스라 효과는 작지만, 읽기/쓰기 의도를 코드로 드러내는 게 좋은 습관이다.
    """
    with driver.session() as session:
        records = session.execute_read(
            lambda tx: [r.data() for r in tx.run(cypher, params or {})]
        )
    print(f"\n[{title}]")
    if not records:
        print("  (결과 없음)")
    for rec in records:
        print(f"  {rec}")
    return records


def main() -> int:
    with GraphDatabase.driver(URI, auth=AUTH) as driver:
        driver.verify_connectivity()

        # --- (a) 패턴 매칭 ---------------------------------------------------
        section("(a) 패턴 매칭")
        run_query(
            driver,
            "LightRAG 가 USES 하는 도구",
            """
            MATCH (a:Entity {name: $name})-[:USES]->(b:Entity)
            RETURN a.name AS user, b.name AS used
            """,
            {"name": "LightRAG"},
        )

        # --- (b) 멀티홉 -----------------------------------------------------
        section("(b) 멀티홉 순회")
        run_query(
            driver,
            "RAG 를 개선하는 것들이 쓰는 도구 (IMPROVES → USES)",
            """
            MATCH (x:Entity)-[:IMPROVES]->(:Entity {name: $name})
            MATCH (x)-[:USES]->(tool:Entity)
            RETURN x.name AS improver, tool.name AS uses_tool
            """,
            {"name": "RAG"},
        )

        # --- (c) 경로 -------------------------------------------------------
        section("(c) 가변 길이 + 최단 경로")
        # 가변 길이 경로는 파라미터로 상한을 못 받는다. 상한은 쿼리 문자열에 박는다(*1..3).
        run_query(
            driver,
            "LightRAG ↔ RAG 1~3홉 경로 (짧은 순 5개)",
            """
            MATCH p = (a:Entity {name: $a})-[*1..3]-(b:Entity {name: $b})
            RETURN [n IN nodes(p) | n.name] AS hops, length(p) AS hop_count
            ORDER BY hop_count
            LIMIT 5
            """,
            {"a": "LightRAG", "b": "RAG"},
        )
        run_query(
            driver,
            "LightRAG ↔ RAG 최단 경로 (shortestPath)",
            """
            MATCH (a:Entity {name: $a}), (b:Entity {name: $b})
            MATCH p = shortestPath((a)-[*1..5]-(b))
            RETURN [n IN nodes(p) | n.name] AS path, length(p) AS hops
            """,
            {"a": "LightRAG", "b": "RAG"},
        )

        # --- (d) 집계 -------------------------------------------------------
        section("(d) 집계")
        run_query(
            driver,
            "가장 많이 참조되는 엔티티 (in-degree)",
            """
            MATCH (n:Entity)<-[r]-()
            WITH n, count(r) AS in_degree
            RETURN n.name AS entity, in_degree
            ORDER BY in_degree DESC
            LIMIT 5
            """,
        )
        run_query(
            driver,
            "무엇을 누가 개선하는가 (collect)",
            """
            MATCH (n:Entity)<-[:IMPROVES]-(m:Entity)
            WITH n, collect(m.name) AS improvers, count(m) AS cnt
            RETURN n.name AS improved, improvers, cnt
            ORDER BY cnt DESC
            """,
        )
        run_query(
            driver,
            "고립 노드 (Entity-Entity 관계 없음, OPTIONAL MATCH)",
            """
            MATCH (n:Entity)
            OPTIONAL MATCH (n)-[r]-(:Entity)
            WITH n, count(r) AS deg
            WHERE deg = 0
            RETURN n.name AS isolated
            ORDER BY isolated
            """,
        )

        # --- (e) Event ------------------------------------------------------
        section("(e) Event 질의")
        run_query(
            driver,
            "엔티티별 발표 이벤트 (ABOUT, time)",
            """
            MATCH (e:Event)-[:ABOUT]->(n:Entity)
            RETURN n.name AS entity, e.type AS event_type, e.time AS year, e.venue AS venue
            ORDER BY year
            """,
        )

    print("\n[OK] 모든 질의 실행 완료.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"[FAIL] {type(exc).__name__}: {exc}", file=sys.stderr)
        print("  - Neo4j 가 떠 있는지(docker compose ps), 02 적재가 끝났는지 확인하라.",
              file=sys.stderr)
        print("  - 그래프가 비어 있으면: cd ../../02-bulk-ingest-merge/practice && python ingest_bulk.py",
              file=sys.stderr)
        sys.exit(1)
