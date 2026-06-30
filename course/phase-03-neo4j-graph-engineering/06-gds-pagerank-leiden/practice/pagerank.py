"""GDS PageRank 로 그래프에서 가장 중심적인 엔티티(허브)를 뽑는다.

01 에서 GDS 개요만 봤다. 06 은 GDS 를 처음 실제로 돌린다.
흐름은 항상 같다. (1) in-memory 그래프로 투영 → (2) 알고리즘 실행 → (3) 투영 정리.

  투영(projection): GDS 는 디스크 그래프를 직접 안 돌리고, 메모리 카탈로그에 사본을
                    올린 뒤 그 위에서 계산한다. gds.graph.project 가 그 사본을 만든다.
  PageRank        : "중요한 노드가 가리키는 노드는 중요하다"를 반복 계산해 노드마다 점수를 준다.
                    웹페이지 랭킹에서 온 알고리즘. 그래프에선 "연결 구조상 중심에 있는 노드"를 찾는다.

stream vs write/mutate:
  - gds.pageRank.stream : 점수를 결과 행으로만 돌려준다. 그래프에 아무것도 안 쓴다(읽기 전용 탐색).
  - gds.pageRank.write  : 점수를 원본 노드의 속성(예: n.pagerank)으로 디스크에 기록한다.
  - gds.pageRank.mutate : 점수를 투영(메모리)에만 기록한다(다음 알고리즘이 이어 쓸 때).
  이 스크립트는 stream 으로 점수를 "보기"만 한다. 디스크에 쓰고 싶으면 아래 주석의 write 예시 참고.

⚠️ 작은 그래프 주의:
  우리 그래프는 Entity 12개뿐이다. PageRank 점수는 규모가 클수록 또렷이 갈린다.
  12개 무방향 그래프에선 점수가 비교적 평평하게(서로 비슷하게) 나오기 쉽다.
  그래도 "연결이 많은 노드가 조금 더 높다"는 순위는 읽힌다. 여기선 메커니즘과 점수 읽는 법을 익힌다.
  허브·커뮤니티 분리가 극적으로 보이려면 Phase 1~2 의 코퍼스를 50~100건으로 키워야 한다.

전제:
  - Neo4j 5.26 + GDS 플러그인 기동(docker compose up -d) — 04/05 와 같은 컨테이너면 그대로 OK.
  - 02 적재가 끝나 Entity 노드가 있어야 한다(비었으면 02→04 먼저).
  - pip install -r requirements.txt
  - 접속 정보 환경변수(02/03/04/05 규약과 동일):
      NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD (기본 bolt://localhost:7687 / neo4j / testpassword1)
  - 이 토픽은 LLM·임베딩 API 를 쓰지 않는다. 키 불필요, 과금 없음(로컬 Neo4j·GDS 만).

실행:
  python pagerank.py            # top-10 허브 출력
  python pagerank.py --top 5    # 상위 5개만
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

# 투영 이름. leiden.py 와 같은 이름을 쓰되, 각 스크립트가 자기 투영을 만들고 끝나면 지운다.
GRAPH_NAME = "entityGraph_pagerank"


def drop_if_exists(driver, name: str) -> None:
    """같은 이름의 투영이 남아 있으면 먼저 지운다(이름 충돌·메모리 누수 방지).

    gds.graph.drop 의 두 번째 인자 false = 없을 때 에러 대신 조용히 넘어간다.
    """
    with driver.session() as session:
        session.run("CALL gds.graph.drop($name, false)", name=name)


def project_entity_graph(driver, name: str) -> tuple[int, int]:
    """Entity 노드 + 엔티티 간 관계를 무방향으로 투영한다.

    orientation: 'UNDIRECTED' 인 이유는 gds_projection.cypher 주석 참고.
    PageRank 만 보면 방향 투영도 되지만, leiden.py 와 해석 기준을 맞추려 무방향으로 통일한다.
    (nodeCount, relationshipCount) 를 돌려준다.
    """
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


def run_pagerank_stream(driver, name: str, top: int) -> list[dict]:
    """PageRank 를 stream 모드로 돌려 score 내림차순 top-k 를 돌려준다.

    gds.pageRank.stream 은 (nodeId, score) 를 행으로 준다. 그래프엔 안 쓴다.
    gds.util.asNode(nodeId) 로 투영 id 를 원래 Entity 노드로 되돌려 name·type 을 읽는다.
    """
    cypher = """
    CALL gds.pageRank.stream($name)
    YIELD nodeId, score
    RETURN gds.util.asNode(nodeId).name AS name,
           gds.util.asNode(nodeId).type AS type,
           score
    ORDER BY score DESC, name ASC
    LIMIT $top
    """
    with driver.session() as session:
        return [dict(r) for r in session.run(cypher, name=name, top=top)]


# 참고) 점수를 디스크 노드 속성으로 남기고 싶다면 write 모드를 쓴다.
# Phase 4 검색에서 후보 우선순위로 재사용하려면 이렇게 한 번 써 두면 편하다.
#   CALL gds.pageRank.write('entityGraph_pagerank', { writeProperty: 'pagerank' })
#   YIELD nodePropertiesWritten, ranIterations
# 이후 일반 Cypher 로 MATCH (e:Entity) RETURN e.name, e.pagerank ORDER BY e.pagerank DESC.


def main() -> int:
    parser = argparse.ArgumentParser(description="GDS PageRank 로 중심 노드(허브) 뽑기")
    parser.add_argument("--top", type=int, default=10, help="상위 몇 개를 볼지(기본 10)")
    args = parser.parse_args()

    with GraphDatabase.driver(URI, auth=AUTH) as driver:
        driver.verify_connectivity()

        # 1) 이전 잔여 투영 정리 → 새로 투영
        drop_if_exists(driver, GRAPH_NAME)
        n_nodes, n_rels = project_entity_graph(driver, GRAPH_NAME)
        print(f"[투영] {GRAPH_NAME} — nodes={n_nodes} rels={n_rels} (UNDIRECTED)")
        if n_nodes == 0:
            print("[경고] 투영된 Entity 노드가 0개다. 02 적재가 끝났는지 확인하라.",
                  file=sys.stderr)

        # 2) PageRank stream → top-k 허브
        rows = run_pagerank_stream(driver, GRAPH_NAME, args.top)
        print(f"\n[PageRank] score 내림차순 top-{args.top} — '연결 구조상 중심' 엔티티")
        print(f"  {'rank':<5}{'score':<12}{'type':<14}name")
        for i, r in enumerate(rows, start=1):
            print(f"  {i:<5}{r['score']:<12.5f}{(r['type'] or ''):<14}{r['name']}")

        # 3) 투영 정리(메모리 반납)
        drop_if_exists(driver, GRAPH_NAME)
        print(f"\n[정리] {GRAPH_NAME} drop 완료.")

    print("\n[해석] 점수가 서로 비슷하면 그래프가 작아 허브가 덜 두드러진 것이다(정상).")
    print("       상위 노드는 Phase 4 검색에서 후보 우선순위·엔트리포인트로 쓰인다.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"[FAIL] {type(exc).__name__}: {exc}", file=sys.stderr)
        print("  - Neo4j+GDS 가 떠 있는지(docker compose ps), 02 적재가 끝났는지 확인하라.",
              file=sys.stderr)
        print("  - 'There is no procedure with the name gds.*' 면 GDS 플러그인 미설치다.",
              file=sys.stderr)
        sys.exit(1)
