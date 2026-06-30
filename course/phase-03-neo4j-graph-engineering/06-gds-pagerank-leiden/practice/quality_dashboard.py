"""Graph Quality Dashboard — 적재된 그래프의 건강검진을 한 표로 모은다.

Phase 2 의 품질 게이트가 "그래프를 만들기 전" 입력을 거른 검문소라면,
이 대시보드는 "그래프를 만든 뒤" 적재 결과를 점검하는 사후 진단이다.
적재가 끝난 그래프가 멀쩡한지, 끊긴 데가 없는지, 중복이 새지 않았는지를 숫자로 본다.

모으는 지표(전부 순수 Cypher + GDS degree 로 계산. LLM·임베딩 안 씀):
  1) 규모            — 전체 노드/관계 수, 라벨별·관계타입별 분포
  2) 고립 노드        — degree 0 인 노드(아무 관계도 없는 떠 있는 노드). 적재 누락의 신호.
  3) degree 분포      — 최대/평균 degree + degree 상위 허브 top-k (GDS degreeCentrality)
  4) 자기 루프        — (a)-[r]->(a) 같은 자기 참조 관계. 보통 추출 오류.
  5) 중복 후보        — 같은 name 인데 canonical_id 가 다른 엔티티(엔티티 해소가 놓친 쌍)
  6) 미해소 노드      — 02 가 fallback 으로 만든 n.unresolved=true 노드(추후 보강 추적)
  7) 커뮤니티 분포    — Leiden 커뮤니티 개수·크기(노드에 e.community 가 기록돼 있을 때만)
  8) PageRank top-k   — degree 와 별개로 PageRank 중심 노드(투영해서 즉석 계산)

전제:
  - Neo4j 5.26 + GDS 플러그인 기동(04/05 와 같은 컨테이너면 그대로 OK).
  - 02 적재 완료(Entity·Event 노드 존재).
  - pip install -r requirements.txt
  - 접속 정보 환경변수(02/03/04/05 규약과 동일):
      NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD (기본 bolt://localhost:7687 / neo4j / testpassword1)
  - LLM·임베딩 API 안 씀. 키 불필요, 과금 없음.
  - 7) 커뮤니티 분포는 leiden.py --write 를 먼저 돌려 e.community 가 있어야 채워진다(없으면 스킵).

실행:
  python quality_dashboard.py            # top-k 기본 5
  python quality_dashboard.py --top 3
"""

import argparse
import os
import sys

from neo4j import GraphDatabase

# --- 접속 정보(02/03/04/05 규약과 동일) -------------------------------------
URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
AUTH = (
    os.environ.get("NEO4J_USER", "neo4j"),
    os.environ.get("NEO4J_PASSWORD", "testpassword1"),
)

GRAPH_NAME = "entityGraph_dashboard"


# === 작은 출력 헬퍼 ==========================================================
def section(title: str) -> None:
    print("\n" + "─" * 60)
    print(f"■ {title}")
    print("─" * 60)


def kv(label: str, value) -> None:
    print(f"  {label:<26}{value}")


# === 1) 규모: 노드/관계 총수 + 라벨별·관계타입별 분포 =========================
def scale_metrics(session) -> None:
    section("1) 규모 — 노드·관계 총수와 분포")
    nodes = session.run("MATCH (n) RETURN count(n) AS c").single()["c"]
    rels = session.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
    kv("전체 노드", nodes)
    kv("전체 관계", rels)

    # 라벨별 노드 수. 노드가 여러 라벨을 가지면 라벨마다 한 번씩 센다.
    print("  라벨별 노드:")
    for r in session.run(
        "MATCH (n) UNWIND labels(n) AS label "
        "RETURN label, count(*) AS c ORDER BY c DESC, label"
    ):
        print(f"    - {r['label']:<16}{r['c']}")

    # 관계 타입별 수.
    print("  관계 타입별:")
    for r in session.run(
        "MATCH ()-[r]->() RETURN type(r) AS t, count(*) AS c ORDER BY c DESC, t"
    ):
        print(f"    - {r['t']:<16}{r['c']}")


# === 2) 고립 노드: degree 0 ==================================================
def isolated_nodes(session) -> None:
    section("2) 고립 노드 — 아무 관계도 없는 노드(적재 누락 신호)")
    rows = list(session.run(
        "MATCH (n) WHERE NOT (n)--() "
        "RETURN labels(n) AS labels, coalesce(n.name, n.event_id, '?') AS id "
        "ORDER BY id"
    ))
    if not rows:
        kv("고립 노드", "없음 (모든 노드가 최소 1개 관계를 가짐)")
    else:
        kv("고립 노드 수", len(rows))
        for r in rows:
            print(f"    - {r['id']}  {r['labels']}")


# === 3) degree 분포: 최대/평균 + 허브 top-k (GDS degreeCentrality) ===========
def degree_distribution(session, top: int) -> None:
    section("3) degree 분포 — 연결 수 최대/평균과 허브 top-k")
    # 순수 Cypher 로 노드별 degree 를 먼저 구하고(WITH), 그 위에서 최대/평균을 집계한다.
    # count{ (n)--() } 는 패턴 카운트 서브쿼리(Neo4j 5.x). 노드마다 연결된 관계 수를 센다.
    agg = session.run(
        "MATCH (n) "
        "WITH n, count{ (n)--() } AS deg "
        "RETURN max(deg) AS max_deg, avg(deg) AS avg_deg"
    ).single()
    kv("최대 degree", agg["max_deg"])
    kv("평균 degree", f"{agg['avg_deg']:.2f}")

    # GDS degreeCentrality 로 허브 top-k (Entity 무방향 투영 기준).
    rows = list(session.run(
        """
        CALL gds.degree.stream($name)
        YIELD nodeId, score
        RETURN gds.util.asNode(nodeId).name AS name, score AS degree
        ORDER BY degree DESC, name ASC
        LIMIT $top
        """,
        name=GRAPH_NAME, top=top,
    ))
    print(f"  degree 허브 top-{top} (Entity 무방향 투영):")
    for i, r in enumerate(rows, start=1):
        print(f"    {i}. {r['name']:<22}degree={r['degree']:.1f}")


# === 4) 자기 루프 ============================================================
def self_loops(session) -> None:
    section("4) 자기 루프 — (a)-[r]->(a) 자기 참조(보통 추출 오류)")
    rows = list(session.run(
        "MATCH (a)-[r]->(a) "
        "RETURN coalesce(a.name, a.event_id, '?') AS id, type(r) AS t"
    ))
    if not rows:
        kv("자기 루프", "없음")
    else:
        kv("자기 루프 수", len(rows))
        for r in rows:
            print(f"    - ({r['id']})-[:{r['t']}]->(self)")


# === 5) 중복 후보: 같은 name, 다른 canonical_id ==============================
def duplicate_candidates(session) -> None:
    section("5) 중복 후보 — 같은 name, 다른 canonical_id(엔티티 해소 누락)")
    rows = list(session.run(
        "MATCH (e:Entity) "
        "WITH e.name AS name, collect(DISTINCT e.canonical_id) AS ids "
        "WHERE size(ids) > 1 "
        "RETURN name, ids ORDER BY name"
    ))
    if not rows:
        kv("중복 후보", "없음 (name 하나당 canonical_id 하나)")
    else:
        kv("중복 후보 수", len(rows))
        for r in rows:
            print(f"    - '{r['name']}' → {r['ids']}")


# === 6) 미해소 노드: 02 fallback ============================================
def unresolved_nodes(session) -> None:
    section("6) 미해소 노드 — 02 가 fallback 으로 만든 unresolved=true")
    rows = list(session.run(
        "MATCH (e:Entity {unresolved: true}) RETURN e.name AS name ORDER BY name"
    ))
    if not rows:
        kv("미해소 노드", "없음")
    else:
        kv("미해소 노드 수", len(rows))
        for r in rows:
            print(f"    - {r['name']}")


# === 7) 커뮤니티 분포: e.community 가 있을 때만 ==============================
def community_distribution(session) -> None:
    section("7) 커뮤니티 분포 — Leiden(e.community) 개수·크기")
    has = session.run(
        "MATCH (e:Entity) WHERE e.community IS NOT NULL RETURN count(e) AS c"
    ).single()["c"]
    if has == 0:
        kv("커뮤니티", "기록 없음 — 먼저 `python leiden.py --write` 실행")
        return
    rows = list(session.run(
        "MATCH (e:Entity) WHERE e.community IS NOT NULL "
        "RETURN e.community AS cid, count(*) AS size "
        "ORDER BY size DESC, cid"
    ))
    kv("커뮤니티 개수", len(rows))
    for r in rows:
        print(f"    - community {r['cid']}: {r['size']}개")


# === 8) PageRank top-k =======================================================
def pagerank_top(session, top: int) -> None:
    section(f"8) PageRank top-{top} — 연결 구조상 중심 엔티티")
    rows = list(session.run(
        """
        CALL gds.pageRank.stream($name)
        YIELD nodeId, score
        RETURN gds.util.asNode(nodeId).name AS name, score
        ORDER BY score DESC, name ASC
        LIMIT $top
        """,
        name=GRAPH_NAME, top=top,
    ))
    for i, r in enumerate(rows, start=1):
        print(f"    {i}. {r['name']:<22}score={r['score']:.5f}")


# === 투영 관리 ===============================================================
def project(session) -> tuple[int, int]:
    """degree·PageRank 계산용 Entity 무방향 투영을 만든다."""
    session.run("CALL gds.graph.drop($name, false)", name=GRAPH_NAME)
    rec = session.run(
        """
        CALL gds.graph.project(
          $name, 'Entity', { ALL_REL: { type: '*', orientation: 'UNDIRECTED' } }
        )
        YIELD nodeCount, relationshipCount
        RETURN nodeCount, relationshipCount
        """,
        name=GRAPH_NAME,
    ).single()
    return rec["nodeCount"], rec["relationshipCount"]


def drop_projection(session) -> None:
    session.run("CALL gds.graph.drop($name, false)", name=GRAPH_NAME)


def main() -> int:
    parser = argparse.ArgumentParser(description="Graph Quality Dashboard — 적재 그래프 건강검진")
    parser.add_argument("--top", type=int, default=5, help="허브·PageRank 상위 개수(기본 5)")
    args = parser.parse_args()

    print("=" * 60)
    print(" Graph Quality Dashboard — 적재된 그래프 건강검진")
    print("=" * 60)

    with GraphDatabase.driver(URI, auth=AUTH) as driver:
        driver.verify_connectivity()
        with driver.session() as session:
            # GDS 가 필요한 지표(3·8)를 위해 먼저 투영.
            n_nodes, n_rels = project(session)
            print(f"[투영] {GRAPH_NAME} — nodes={n_nodes} rels={n_rels} (UNDIRECTED)")

            # 순수 Cypher 지표
            scale_metrics(session)
            isolated_nodes(session)
            self_loops(session)
            duplicate_candidates(session)
            unresolved_nodes(session)
            community_distribution(session)

            # GDS 지표
            degree_distribution(session, args.top)
            pagerank_top(session, args.top)

            # 투영 정리
            drop_projection(session)

    print("\n" + "=" * 60)
    print(" 건강검진 끝. 고립 노드·중복 후보·자기 루프가 0 이면 적재가 깨끗하다는 신호다.")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"[FAIL] {type(exc).__name__}: {exc}", file=sys.stderr)
        print("  - Neo4j+GDS 기동(docker compose ps)·02 적재 완료 여부를 확인하라.",
              file=sys.stderr)
        print("  - 'no procedure with the name gds.*' 면 GDS 플러그인 미설치다.",
              file=sys.stderr)
        sys.exit(1)
