"""4.1 mini_graph_neo4j.py — 초소형 예시 그래프 위에서 Local/Path/Global 대표 Cypher 를 보여 준다.

이 토픽은 개념 지도라 무거운 검색기는 안 만든다(그건 4.2~4.5 의 몫이다).
대신 5~10개 노드짜리 미니 그래프를 MERGE 로 직접 만들고, 세 가지 검색 패턴이
Cypher 로는 어떻게 생겼는지 대표 한 줄씩 직접 돌려 본다.

    Local  — 한 엔티티의 직접 이웃 조회
    Path   — 두 엔티티 사이 최단 멀티홉 경로
    Global — 커뮤니티(community 속성) 단위 집계로 전체 조망

Phase 3 에서 만든 그래프를 가정하되, 여기 미니 그래프는 그것과 독립적으로
이 스크립트가 직접 적재하므로 Phase 3 산출물이 없어도 단독 실행된다.
(실제 검색 토픽 4.2~ 에서는 Phase 3 의 진짜 그래프를 입력으로 쓴다.)

전제:
    - Neo4j 5.26 LTS 가 떠 있어야 한다(practice/docker-compose.yml 로 기동).
    - 접속 정보는 환경변수에서 읽는다. 하드코딩하지 않는다.
        NEO4J_URI       (기본 bolt://localhost:7687)
        NEO4J_USER      (기본 neo4j)
        NEO4J_PASSWORD  (기본 testpassword1)
    - GDS·임베딩·LLM 은 쓰지 않는다. 순수 Cypher 라 키 불필요, 과금 0.

실행:
    pip install -r requirements.txt
    export NEO4J_PASSWORD=testpassword1
    python mini_graph_neo4j.py            # 미니 그래프 적재 후 Local/Path/Global 데모
    python mini_graph_neo4j.py --reset    # 미니 그래프만 지우고 종료
"""

from __future__ import annotations

import os
import sys

from neo4j import GraphDatabase


# 미니 그래프 정의 — 7개 Entity + 7개 관계. AI/LLM 기술 문서 코퍼스의 축소판이다.
# community 속성은 Phase 3/06 Leiden 이 매겨 주는 값을 흉내 낸 것이다(여기선 손으로 박았다).
#   community 0 = "검색 기법" 군집,  community 1 = "조직·도구" 군집
ENTITIES: list[dict] = [
    {"name": "RAG",        "type": "Method",       "community": 0},
    {"name": "GraphRAG",   "type": "Method",       "community": 0},
    {"name": "LightRAG",   "type": "Framework",    "community": 0},
    {"name": "multi-hop",  "type": "Concept",      "community": 0},
    {"name": "Neo4j",      "type": "Database",     "community": 1},
    {"name": "HKUDS",      "type": "Organization", "community": 1},
    {"name": "Microsoft",  "type": "Organization", "community": 1},
]

# (시작, 관계타입, 끝) — 무방향처럼 읽되 저장은 방향 그대로 둔다.
RELATIONS: list[tuple[str, str, str]] = [
    ("GraphRAG", "EXTENDS",      "RAG"),
    ("GraphRAG", "ADDRESSES",    "multi-hop"),
    ("LightRAG", "IMPLEMENTS",   "GraphRAG"),
    ("LightRAG", "DEVELOPED_BY", "HKUDS"),
    ("LightRAG", "USES",         "Neo4j"),
    ("GraphRAG", "DEVELOPED_BY", "Microsoft"),
    ("Microsoft", "COMPARES_TO", "HKUDS"),
]


def get_driver():
    """환경변수에서 접속 정보를 읽어 드라이버를 만든다. 비밀번호 하드코딩 금지."""
    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD", "testpassword1")
    return GraphDatabase.driver(uri, auth=(user, password))


def reset(session) -> None:
    """이 데모가 만든 미니 그래프만 지운다(:Mini 라벨로 격리해 Phase 3 그래프를 안 건드린다)."""
    session.run("MATCH (n:Mini) DETACH DELETE n")


def load(session) -> None:
    """미니 그래프를 MERGE 로 적재한다. 멱등(여러 번 돌려도 중복 안 쌓임)하다."""
    # 노드: :Mini 라벨로 격리. name 을 키로 MERGE.
    for e in ENTITIES:
        session.run(
            "MERGE (n:Mini {name: $name}) "
            "SET n.type = $type, n.community = $community",
            name=e["name"], type=e["type"], community=e["community"],
        )
    # 관계: 양 끝 노드를 MERGE 로 보장한 뒤 관계 MERGE. 관계타입은 파라미터화 불가라
    # apoc 없이 가려고 타입을 문자열로 끼워 넣는다(입력이 코드 상수라 안전).
    for src, rel, dst in RELATIONS:
        session.run(
            f"MERGE (a:Mini {{name: $src}}) "
            f"MERGE (b:Mini {{name: $dst}}) "
            f"MERGE (a)-[:{rel}]->(b)",
            src=src, dst=dst,
        )


def demo_local(session, entity: str = "LightRAG") -> None:
    """Local 패턴 — 한 엔티티의 직접 이웃(1-hop)을 조회한다."""
    print(f"\n[Local] '{entity}' 의 직접 이웃 — 이 엔티티는 무엇과 바로 연결되나")
    rows = session.run(
        "MATCH (e:Mini {name: $name})-[r]-(nb:Mini) "
        "RETURN type(r) AS rel, nb.name AS neighbor, nb.type AS ntype "
        "ORDER BY rel, neighbor",
        name=entity,
    )
    for row in rows:
        print(f"  {entity} -[{row['rel']}]- {row['neighbor']} ({row['ntype']})")


def demo_path(session, start: str = "Neo4j", end: str = "RAG") -> None:
    """Path 패턴 — 두 엔티티 사이 최단 멀티홉 경로. Baseline RAG 가 무너지던 자리다."""
    print(f"\n[Path] '{start}' → '{end}' 최단 경로 — A와 B는 몇 홉으로 어떻게 이어지나")
    record = session.run(
        "MATCH (a:Mini {name: $start}), (b:Mini {name: $end}), "
        "p = shortestPath((a)-[*..6]-(b)) "
        "RETURN [n IN nodes(p) | n.name] AS hops, length(p) AS hop_len",
        start=start, end=end,
    ).single()
    if record is None:
        print("  경로 없음")
        return
    print(f"  {' → '.join(record['hops'])}  (길이 {record['hop_len']} 홉)")


def demo_global(session) -> None:
    """Global/Community 패턴 — community 단위 집계로 전체 구조를 조망한다."""
    print("\n[Global] community 단위 집계 — 코퍼스가 어떤 묶음으로 나뉘나")
    rows = session.run(
        "MATCH (e:Mini) WHERE e.community IS NOT NULL "
        "RETURN e.community AS community, count(*) AS size, "
        "       collect(e.name) AS members "
        "ORDER BY community"
    )
    for row in rows:
        members = ", ".join(sorted(row["members"]))
        print(f"  community {row['community']} ({row['size']}개): {members}")


def main(argv: list[str]) -> None:
    do_reset_only = "--reset" in argv
    driver = get_driver()
    try:
        with driver.session() as session:
            if do_reset_only:
                reset(session)
                print("[reset] 미니 그래프(:Mini)를 삭제했다.")
                return

            reset(session)   # 멱등성 위해 먼저 비우고
            load(session)    # 다시 적재
            print("[load] 미니 그래프 적재 완료 — :Mini 노드 7개 + 관계 7개")

            demo_local(session)
            demo_path(session)
            demo_global(session)
    finally:
        driver.close()


if __name__ == "__main__":
    main(sys.argv)
