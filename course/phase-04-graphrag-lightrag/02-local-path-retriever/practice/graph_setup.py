"""4.2 graph_setup.py — 4.1 의 :Mini 미니 그래프를 더 풍부하게 키우고 full-text 인덱스를 만든다.

4.1 은 7개 노드 + 7개 관계로 Local/Path/Global 대표 Cypher 를 "한 줄씩" 보여 줬다.
4.2 는 그 위에 두 가지를 더한다.
    1) 각 엔티티에 aliases(별칭 목록) 속성 — 엔티티 링킹이 "LightRAG", "light rag",
       "lightrag framework" 같은 자연어 표현을 같은 노드로 매핑하게 한다.
    2) 노드·관계 2개씩 추가 — VoyageAI, vector search 를 끼워 멀티홉 경로가 더 길고 또렷해진다.
       (예: Neo4j → LightRAG → ... → RAG 보다 다양한 경로가 생긴다.)

그리고 full-text 인덱스(miniNameFulltext)를 만든다. 엔티티 링킹의 후보 생성이
db.index.fulltext.queryNodes 로 name·aliases 를 한 번에 검색하게 하기 위함이다.

:Mini 라벨로 격리하므로 같은 DB 에 Phase 3 의 진짜 그래프가 있어도 건드리지 않는다.

전제:
    - Neo4j 5.26 LTS 가 떠 있어야 한다(practice/docker-compose.yml 로 기동).
    - 접속 정보는 환경변수에서 읽는다. 하드코딩하지 않는다.
        NEO4J_URI       (기본 bolt://localhost:7687)
        NEO4J_USER      (기본 neo4j)
        NEO4J_PASSWORD  (기본 testpassword1)
    - GDS·임베딩·LLM 은 쓰지 않는다. 순수 Cypher + full-text 라 키 불필요, 과금 0.

실행:
    pip install -r requirements.txt
    export NEO4J_PASSWORD=testpassword1
    python graph_setup.py            # 미니 그래프 적재 + full-text 인덱스 생성
    python graph_setup.py --reset    # 미니 그래프만 지우고 종료(인덱스는 유지)
"""

from __future__ import annotations

import os
import sys

from neo4j import GraphDatabase

# full-text 인덱스 이름 — 다른 모듈(entity_linking 등)이 import 해서 같은 이름을 쓴다.
FULLTEXT_INDEX = "miniNameFulltext"

# 엔티티 — 4.1 의 7개에 VoyageAI · vector search 2개를 더해 9개.
# aliases 는 엔티티 링킹용 별칭. 자연어 질문이 노드 name 과 정확히 안 맞아도 잡히게 한다.
#   community 0 = "검색 기법" 군집,  community 1 = "조직·도구" 군집  (4.1 과 동일 규약)
ENTITIES: list[dict] = [
    {"name": "RAG",           "type": "Method",       "community": 0,
     "aliases": ["retrieval augmented generation", "retrieval-augmented generation"]},
    {"name": "GraphRAG",      "type": "Method",       "community": 0,
     "aliases": ["graph rag", "graph-based rag"]},
    {"name": "LightRAG",      "type": "Framework",    "community": 0,
     "aliases": ["light rag", "lightrag framework"]},
    {"name": "multi-hop",     "type": "Concept",      "community": 0,
     "aliases": ["multi hop", "multihop", "멀티홉"]},
    {"name": "vector search", "type": "Concept",      "community": 0,
     "aliases": ["vector retrieval", "dense retrieval", "벡터 검색"]},
    {"name": "Neo4j",         "type": "Database",     "community": 1,
     "aliases": ["neo4j graph database", "neo4j db"]},
    {"name": "HKUDS",         "type": "Organization", "community": 1,
     "aliases": ["hong kong university data science", "hku data science lab"]},
    {"name": "Microsoft",     "type": "Organization", "community": 1,
     "aliases": ["msft", "microsoft research"]},
    {"name": "VoyageAI",      "type": "Organization", "community": 1,
     "aliases": ["voyage ai", "voyage"]},
]

# (시작, 관계타입, 끝) — 무방향처럼 읽되 저장은 방향 그대로 둔다.
# 4.1 의 7개 + (RAG)-[:USES]->(vector search), (LightRAG)-[:EMBEDS_WITH]->(VoyageAI) 2개 = 9개.
# 이 2개가 더해지면 'Neo4j' 와 'vector search' 같은 더 먼 쌍도 경로로 이어진다.
RELATIONS: list[tuple[str, str, str]] = [
    ("GraphRAG",  "EXTENDS",      "RAG"),
    ("GraphRAG",  "ADDRESSES",    "multi-hop"),
    ("LightRAG",  "IMPLEMENTS",   "GraphRAG"),
    ("LightRAG",  "DEVELOPED_BY", "HKUDS"),
    ("LightRAG",  "USES",         "Neo4j"),
    ("GraphRAG",  "DEVELOPED_BY", "Microsoft"),
    ("Microsoft", "COMPARES_TO",  "HKUDS"),
    ("RAG",       "USES",         "vector search"),   # 추가 — RAG 의 토대 기법
    ("LightRAG",  "EMBEDS_WITH",  "VoyageAI"),         # 추가 — 임베딩 공급자
]


def get_driver():
    """환경변수에서 접속 정보를 읽어 드라이버를 만든다. 비밀번호 하드코딩 금지."""
    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD", "testpassword1")
    return GraphDatabase.driver(uri, auth=(user, password))


def reset(session) -> None:
    """이 데모가 만든 미니 그래프만 지운다(:Mini 라벨로 격리). 인덱스는 남겨 둔다."""
    session.run("MATCH (n:Mini) DETACH DELETE n")


def create_fulltext_index(session) -> None:
    """name 과 aliases 를 한 번에 검색하는 full-text 인덱스를 만든다(이미 있으면 무시).

    엔티티 링킹의 후보 생성이 db.index.fulltext.queryNodes(FULLTEXT_INDEX, q) 로
    name·aliases 양쪽을 동시에 매칭하게 한다. Neo4j 5.x 네이티브 기능, 플러그인 불필요.
    """
    session.run(
        f"CREATE FULLTEXT INDEX {FULLTEXT_INDEX} IF NOT EXISTS "
        "FOR (n:Mini) ON EACH [n.name, n.aliases]"
    )


def load(session) -> None:
    """미니 그래프를 MERGE 로 적재한다. 멱등(여러 번 돌려도 중복 안 쌓임)하다."""
    # 노드: :Mini 라벨로 격리. name 을 키로 MERGE. aliases 는 문자열 리스트 속성.
    for e in ENTITIES:
        session.run(
            "MERGE (n:Mini {name: $name}) "
            "SET n.type = $type, n.community = $community, n.aliases = $aliases",
            name=e["name"], type=e["type"],
            community=e["community"], aliases=e["aliases"],
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


def main(argv: list[str]) -> None:
    do_reset_only = "--reset" in argv
    driver = get_driver()
    try:
        with driver.session() as session:
            if do_reset_only:
                reset(session)
                print("[reset] 미니 그래프(:Mini)를 삭제했다(full-text 인덱스는 유지).")
                return

            reset(session)                  # 멱등성 위해 먼저 비우고
            load(session)                   # 다시 적재
            create_fulltext_index(session)  # full-text 인덱스 보장
            print(f"[load] 미니 그래프 적재 완료 — :Mini 노드 {len(ENTITIES)}개 "
                  f"+ 관계 {len(RELATIONS)}개")
            print(f"[index] full-text 인덱스 '{FULLTEXT_INDEX}' 준비 완료 "
                  "(name + aliases 검색)")
    finally:
        driver.close()


if __name__ == "__main__":
    main(sys.argv)
