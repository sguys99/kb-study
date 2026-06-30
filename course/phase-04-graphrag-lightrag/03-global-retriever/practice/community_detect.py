"""4.3 community_detect.py — GDS Leiden 으로 :Mini 그래프를 커뮤니티로 나눈다.

Global 검색기의 첫 단추다. "커뮤니티별로 요약하고 map-reduce 로 종합"하려면
먼저 커뮤니티가 있어야 한다. 그 커뮤니티를 Leiden(커뮤니티 탐지)이 만든다.
서로 촘촘히 연결된 노드를 같은 community 로 묶는다 — modularity 를 최대화하는 방향으로.

Phase 3.6 의 leiden.py 패턴을 :Mini 라벨로 그대로 이식했다. 바뀐 건 라벨(Entity → Mini)뿐이다.

⚠️ UNDIRECTED 필수:
   Leiden 은 무방향 그래프에서 동작한다. 방향 그래프로 투영하면 에러가 난다.
   그래서 gds.graph.project 에 orientation: 'UNDIRECTED' 를 반드시 넣는다. 빼면 실패한다.

⚠️ community 속성을 Leiden 이 덮어쓴다:
   graph_setup.py 가 박은 community(0/1/2)는 임시 시드다.
   --write 를 주면 Leiden 이 '실제로 탐지한 값'으로 e.community 를 덮어쓴다.
   4.2 의 하드코딩 community 를 Leiden 탐지값으로 교체하는 단계가 바로 이것이다.

⚠️ 작은 그래프 주의:
   :Mini 는 노드 14개다. 커뮤니티 탐지는 규모가 커야 군집이 또렷이 갈린다.
   graph_setup.py 가 군집 사이 다리를 일부러 성기게 둬서 보통 2~3개로 갈리지만,
   GDS 버전·랜덤 시드에 따라 다르게 묶일 수 있다. 1개로 뭉쳐도 정상이다 — 다음 단계
   (summarize/global)는 커뮤니티 수가 1개든 3개든 그대로 동작한다.

전제:
  - Neo4j 5.26 + GDS 플러그인 기동(docker-compose.yml). 4.3 은 GDS 필수.
  - graph_setup.py 적재 완료(:Mini 노드 존재).
  - pip install -r requirements.txt
  - 접속 정보 환경변수(4.2 규약과 동일):
      NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD
      (기본 bolt://localhost:7687 / neo4j / testpassword1)
  - LLM·임베딩 API 안 씀. 키 불필요, 과금 없음.

실행:
  python community_detect.py            # 커뮤니티별 멤버 출력(stream, 그래프엔 안 씀)
  python community_detect.py --write    # e.community 를 탐지값으로 덮어쓰기(요약·global 입력)
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict

from neo4j import GraphDatabase

# 접속 정보(4.2 규약과 동일).
URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
AUTH = (
    os.environ.get("NEO4J_USER", "neo4j"),
    os.environ.get("NEO4J_PASSWORD", "testpassword1"),
)

GRAPH_NAME = "miniGraph_leiden"  # GDS 투영 이름(임시 인메모리 그래프)


def drop_if_exists(driver, name: str) -> None:
    """남은 투영을 먼저 지운다(이름 충돌·메모리 누수 방지)."""
    with driver.session() as session:
        session.run("CALL gds.graph.drop($name, false)", name=name)


def project_mini_graph(driver, name: str) -> tuple[int, int]:
    """:Mini + 그 사이 관계를 무방향으로 투영한다(Leiden 은 UNDIRECTED 필수)."""
    cypher = """
    CALL gds.graph.project(
      $name,
      'Mini',
      { ALL_REL: { type: '*', orientation: 'UNDIRECTED' } }
    )
    YIELD nodeCount, relationshipCount
    RETURN nodeCount, relationshipCount
    """
    with driver.session() as session:
        rec = session.run(cypher, name=name).single()
    return rec["nodeCount"], rec["relationshipCount"]


def run_leiden_stream(driver, name: str) -> list[dict]:
    """Leiden 을 stream 모드로 돌려 (name, communityId) 행을 돌려준다(그래프엔 안 씀).

    gds.util.asNode 로 투영 id 를 원래 :Mini 노드로 되돌려 name 을 읽는다.
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
    """Leiden 결과를 e.community 속성으로 디스크에 기록한다(요약·global 입력).

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
    parser = argparse.ArgumentParser(description="GDS Leiden 으로 :Mini 커뮤니티 탐지")
    parser.add_argument(
        "--write",
        action="store_true",
        help="탐지값을 e.community 속성으로 디스크에 기록(요약·global 입력용)",
    )
    args = parser.parse_args()

    with GraphDatabase.driver(URI, auth=AUTH) as driver:
        driver.verify_connectivity()

        drop_if_exists(driver, GRAPH_NAME)
        n_nodes, n_rels = project_mini_graph(driver, GRAPH_NAME)
        print(f"[투영] {GRAPH_NAME} — nodes={n_nodes} rels={n_rels} (UNDIRECTED, Leiden 필수)")

        rows = run_leiden_stream(driver, GRAPH_NAME)
        groups = group_by_community(rows)
        print(f"\n[Leiden] 커뮤니티 {len(groups)}개 — 서로 촘촘히 연결된 :Mini 무리")
        for cid, names in groups.items():
            print(f"  community {cid} ({len(names)}개): {', '.join(names)}")

        if args.write:
            stats = run_leiden_write(driver, GRAPH_NAME)
            print(f"\n[write] e.community 덮어쓰기 완료 — "
                  f"communityCount={stats['communityCount']} "
                  f"modularity={stats['modularity']:.4f} "
                  f"nodePropertiesWritten={stats['nodePropertiesWritten']}")
            print("  확인: MATCH (e:Mini) RETURN e.community, collect(e.name)")
            print("  다음: python community_summarize.py 로 커뮤니티별 요약(Community Report)을 만든다.")

        drop_if_exists(driver, GRAPH_NAME)
        print(f"\n[정리] {GRAPH_NAME} drop 완료(인메모리 투영만 제거, 디스크 그래프는 유지).")

    print("\n[해석] 작은 그래프라 커뮤니티가 1~2개로 뭉쳐도 정상이다.")
    print("       이 커뮤니티 분할이 community_summarize / global_retriever 의 입력이 된다.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"[FAIL] {type(exc).__name__}: {exc}", file=sys.stderr)
        print("  - Leiden 은 UNDIRECTED 투영이 필수다. 'must be UNDIRECTED' 에러면 투영 방향을 확인하라.",
              file=sys.stderr)
        print("  - GDS 미설치면 'no procedure gds.*' 에러가 난다. docker-compose 의 NEO4J_PLUGINS 확인.",
              file=sys.stderr)
        print("  - graph_setup.py 적재 여부(:Mini 노드 존재)도 확인하라.", file=sys.stderr)
        sys.exit(1)
