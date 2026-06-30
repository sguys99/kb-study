"""GDS Leiden 으로 그래프를 커뮤니티(밀집 군집)로 나눈다.

PageRank 가 "누가 중심인가"라면, Leiden(커뮤니티 탐지)은 "누가 누구와 한 무리인가"다.
서로 촘촘히 연결된 노드들을 같은 communityId 로 묶는다. modularity(군집성)를 최대화하는 방향으로.

⭐ Phase 4 연결: 여기서 나온 Leiden 커뮤니티가 Phase 4/03 Global Retriever 의 입력이 된다.
   Global 검색은 "커뮤니티별 요약을 만들고 → 질문에 대해 map-reduce 로 종합"한다.
   그 첫 단추인 '커뮤니티 분할'을 06 에서 만든다. 즉 이 스크립트의 출력이 다음 Phase 의 재료다.

⚠️ UNDIRECTED 필수:
   Leiden 은 무방향 그래프에서 동작한다. 방향 그래프로 투영하면 에러가 난다.
   그래서 gds.graph.project 에 orientation: 'UNDIRECTED' 를 반드시 넣는다.

⚠️ 작은 그래프 주의:
   우리 그래프는 Entity 12개다. 커뮤니티 탐지는 규모가 커야 군집이 또렷이 갈린다.
   12개 그래프에선 전체가 1~2개 커뮤니티로 뭉칠 수 있다(연결이 한 덩어리라서). 정상이다.
   여기선 "커뮤니티 ID 가 어떻게 붙고, 어떻게 그룹으로 읽는지"를 익힌다.
   코퍼스를 키우면(Phase 1~2) 주제별로 커뮤니티가 자연스럽게 갈라진다.

전제:
  - Neo4j 5.26 + GDS 플러그인 기동(04/05 와 같은 컨테이너면 그대로 OK).
  - 02 적재 완료(Entity 노드 존재).
  - pip install -r requirements.txt
  - 접속 정보 환경변수(02/03/04/05 규약과 동일):
      NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD (기본 bolt://localhost:7687 / neo4j / testpassword1)
  - LLM·임베딩 API 안 씀. 키 불필요, 과금 없음.

실행:
  python leiden.py            # 커뮤니티별 멤버 출력(stream)
  python leiden.py --write    # communityId 를 e.community 속성으로 디스크에 기록(Phase 4 용)
"""

import argparse
import os
import sys
from collections import defaultdict

from neo4j import GraphDatabase

# --- 접속 정보(02/03/04/05 규약과 동일) -------------------------------------
URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
AUTH = (
    os.environ.get("NEO4J_USER", "neo4j"),
    os.environ.get("NEO4J_PASSWORD", "testpassword1"),
)

GRAPH_NAME = "entityGraph_leiden"


def drop_if_exists(driver, name: str) -> None:
    """남은 투영을 먼저 지운다(이름 충돌·메모리 누수 방지)."""
    with driver.session() as session:
        session.run("CALL gds.graph.drop($name, false)", name=name)


def project_entity_graph(driver, name: str) -> tuple[int, int]:
    """Entity + 엔티티 간 관계를 무방향으로 투영(Leiden 은 UNDIRECTED 필수)."""
    cypher = """
    CALL gds.graph.project(
      $name,
      'Entity',
      { ALL_REL: { type: '*', orientation: 'UNDIRECTED' } }
    )
    YIELD nodeCount, relationshipCount
    RETURN nodeCount, relationshipCount
    """
    with driver.session() as session:
        rec = session.run(cypher, name=name).single()
    return rec["nodeCount"], rec["relationshipCount"]


def run_leiden_stream(driver, name: str) -> list[dict]:
    """Leiden 을 stream 모드로 돌려 (name, communityId) 행을 돌려준다.

    gds.leiden.stream 은 (nodeId, communityId) 를 준다. 그래프엔 안 쓴다.
    gds.util.asNode 로 투영 id 를 원래 Entity 로 되돌려 name 을 읽는다.
    """
    cypher = """
    CALL gds.leiden.stream($name)
    YIELD nodeId, communityId
    RETURN gds.util.asNode(nodeId).name AS name, communityId
    ORDER BY communityId ASC, name ASC
    """
    with driver.session() as session:
        return [dict(r) for r in session.run(cypher, name=name)]


def run_leiden_write(driver, name: str) -> dict:
    """Leiden 결과를 e.community 속성으로 디스크에 기록한다(Phase 4 Global Retriever 입력).

    write 모드는 communityCount·modularity 같은 요약 통계도 함께 돌려준다.
    """
    cypher = """
    CALL gds.leiden.write($name, { writeProperty: 'community' })
    YIELD communityCount, modularity, nodePropertiesWritten
    RETURN communityCount, modularity, nodePropertiesWritten
    """
    with driver.session() as session:
        return dict(session.run(cypher, name=name).single())


def group_by_community(rows: list[dict]) -> dict[int, list[str]]:
    """stream 결과를 communityId → [name, ...] 으로 묶는다."""
    groups: dict[int, list[str]] = defaultdict(list)
    for r in rows:
        groups[r["communityId"]].append(r["name"])
    return dict(sorted(groups.items()))


def main() -> int:
    parser = argparse.ArgumentParser(description="GDS Leiden 으로 커뮤니티 탐지")
    parser.add_argument(
        "--write",
        action="store_true",
        help="communityId 를 e.community 속성으로 디스크에 기록(Phase 4 입력용)",
    )
    args = parser.parse_args()

    with GraphDatabase.driver(URI, auth=AUTH) as driver:
        driver.verify_connectivity()

        drop_if_exists(driver, GRAPH_NAME)
        n_nodes, n_rels = project_entity_graph(driver, GRAPH_NAME)
        print(f"[투영] {GRAPH_NAME} — nodes={n_nodes} rels={n_rels} (UNDIRECTED, Leiden 필수)")

        # stream 으로 멤버를 본다(항상 실행).
        rows = run_leiden_stream(driver, GRAPH_NAME)
        groups = group_by_community(rows)
        print(f"\n[Leiden] 커뮤니티 {len(groups)}개 — 서로 촘촘히 연결된 엔티티 무리")
        for cid, names in groups.items():
            print(f"  community {cid} ({len(names)}개): {', '.join(names)}")

        # --write 면 디스크에도 기록한다(Phase 4 재사용).
        if args.write:
            stats = run_leiden_write(driver, GRAPH_NAME)
            print(f"\n[write] e.community 기록 완료 — "
                  f"communityCount={stats['communityCount']} "
                  f"modularity={stats['modularity']:.4f} "
                  f"nodePropertiesWritten={stats['nodePropertiesWritten']}")
            print("  이후 일반 Cypher 로 확인: "
                  "MATCH (e:Entity) RETURN e.community, collect(e.name)")

        drop_if_exists(driver, GRAPH_NAME)
        print(f"\n[정리] {GRAPH_NAME} drop 완료.")

    print("\n[해석] 작은 그래프라 커뮤니티가 1~2개로 뭉쳐도 정상이다.")
    print("       이 커뮤니티 분할이 Phase 4/03 Global Retriever 의 요약·map-reduce 입력이 된다.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"[FAIL] {type(exc).__name__}: {exc}", file=sys.stderr)
        print("  - Leiden 은 UNDIRECTED 투영이 필수다. 'must be UNDIRECTED' 에러면 투영 방향을 확인하라.",
              file=sys.stderr)
        print("  - Neo4j+GDS 기동·02 적재 완료 여부도 확인하라.", file=sys.stderr)
        sys.exit(1)
