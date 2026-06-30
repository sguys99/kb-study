"""4.3 graph_setup.py — 4.2 의 :Mini 미니 그래프를 이어받아 커뮤니티가 또렷이 갈리게 보강한다.

4.2 는 9개 노드 + 9개 관계로 Local·Path 검색기를 만들었다. 그 그래프는 거의 한 덩어리라
Leiden 을 돌리면 커뮤니티가 1개로 뭉치기 쉽다(연결이 빽빽해서). Global 검색기는
'서로 다른 주제 군집'이 있어야 의미가 산다. 그래서 여기서 평가·관측 군집을 한 묶음 더한다.

  보강 1) 노드 5개 추가 — Ragas / Langfuse / Phase 1 Baseline / evaluation / multi-hop QA.
          이 다섯은 'GraphRAG 를 어떻게 평가·관측하나'라는 별개 주제로 자기들끼리 촘촘히
          엮인다. 그래서 Leiden 이 기존 검색-기법 군집과 갈라 놓는다.
  보강 2) 관계 7개 추가 — 평가 군집 내부를 엮고, 검색 군집과는 '딱 한두 다리'로만 잇는다.
          군집 내부는 빽빽하게, 군집 사이는 성기게. 이게 커뮤니티가 갈리는 조건이다.

4.2 와 같은 규약을 그대로 따른다.
  - :Mini 라벨로 격리 — 같은 DB 에 Phase 3 진짜 그래프가 있어도 안 건드린다.
  - MERGE 로 멱등 — 여러 번 돌려도 중복이 안 쌓인다.
  - full-text 인덱스(miniNameFulltext) 유지 — name + aliases 검색.
  - community 속성: 4.2 는 0/1 을 손으로 박았다. 4.3 은 그 값을 community_detect.py 의
    Leiden 이 '실제로 탐지한 값'으로 덮어쓴다. 그래서 여기서 박는 community 는 임시값이고,
    Leiden --write 가 진짜 값을 채운다(아래 SET 의 community 는 시드일 뿐).

전제:
    - Neo4j 5.26 LTS + GDS 플러그인 기동(practice/docker-compose.yml). 4.3 은 GDS 필수.
    - 접속 정보는 환경변수에서 읽는다. 하드코딩하지 않는다.
        NEO4J_URI       (기본 bolt://localhost:7687)
        NEO4J_USER      (기본 neo4j)
        NEO4J_PASSWORD  (기본 testpassword1)
    - 이 스크립트 자체는 GDS·임베딩·LLM 을 쓰지 않는다. 순수 Cypher, 키 불필요, 과금 0.

실행:
    pip install -r requirements.txt
    export NEO4J_PASSWORD=testpassword1
    python graph_setup.py            # 보강된 미니 그래프 적재 + full-text 인덱스 생성
    python graph_setup.py --reset    # 미니 그래프만 지우고 종료(인덱스는 유지)
"""

from __future__ import annotations

import os
import sys

from neo4j import GraphDatabase

# full-text 인덱스 이름 — 4.2 와 동일. 다른 모듈이 import 해서 같은 이름을 쓴다.
FULLTEXT_INDEX = "miniNameFulltext"

# 엔티티 — 4.2 의 9개에 평가·관측 주제 5개를 더해 14개.
#   community 시드값: 0 = 검색 기법, 1 = 조직·도구, 2 = 평가·관측.
#   이 값은 임시 시드다. community_detect.py 의 Leiden --write 가 실제 탐지값으로 덮어쓴다.
ENTITIES: list[dict] = [
    # --- 4.2 에서 그대로 이어받는 9개 (검색 기법 / 조직·도구) ---
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
    # --- 4.3 보강: 평가·관측 주제 군집 5개 ---
    {"name": "Ragas",         "type": "Framework",    "community": 2,
     "aliases": ["ragas eval", "ragas framework"]},
    {"name": "Langfuse",      "type": "Framework",    "community": 2,
     "aliases": ["lang fuse", "langfuse observability"]},
    {"name": "Baseline",      "type": "Concept",      "community": 2,
     "aliases": ["baseline hybrid rag", "phase 1 baseline", "기준선"]},
    {"name": "evaluation",    "type": "Concept",      "community": 2,
     "aliases": ["eval", "retrieval evaluation", "평가"]},
    {"name": "QA accuracy",   "type": "Metric",       "community": 2,
     "aliases": ["answer accuracy", "정답률", "qa 정답률"]},
]

# (시작, 관계타입, 끝). 저장은 방향 그대로 두되 읽기는 무방향처럼.
# 군집 내부는 빽빽하게, 군집 사이 다리는 성기게 — 이래야 Leiden 이 또렷이 가른다.
RELATIONS: list[tuple[str, str, str]] = [
    # --- 4.2 에서 이어받는 9개 ---
    ("GraphRAG",  "EXTENDS",      "RAG"),
    ("GraphRAG",  "ADDRESSES",    "multi-hop"),
    ("LightRAG",  "IMPLEMENTS",   "GraphRAG"),
    ("LightRAG",  "DEVELOPED_BY", "HKUDS"),
    ("LightRAG",  "USES",         "Neo4j"),
    ("GraphRAG",  "DEVELOPED_BY", "Microsoft"),
    ("Microsoft", "COMPARES_TO",  "HKUDS"),
    ("RAG",       "USES",         "vector search"),
    ("LightRAG",  "EMBEDS_WITH",  "VoyageAI"),
    # --- 4.3 보강: 평가·관측 군집 내부(빽빽하게 5개) ---
    ("evaluation", "MEASURES",     "QA accuracy"),
    ("Ragas",      "COMPUTES",     "QA accuracy"),
    ("Ragas",      "SUPPORTS",     "evaluation"),
    ("Langfuse",   "TRACES",       "evaluation"),
    ("Baseline",   "EVALUATED_BY", "Ragas"),
    # --- 4.3 보강: 군집 사이 다리(성기게 2개) ---
    #     평가 군집을 검색 군집에 '딱 두 다리'로만 잇는다. 더 많이 이으면 군집이 다시 뭉친다.
    ("Baseline",   "BASELINE_FOR", "GraphRAG"),   # 평가↔검색 다리 1
    ("RAG",        "MEASURED_BY",  "evaluation"),  # 평가↔검색 다리 2
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
    """name 과 aliases 를 한 번에 검색하는 full-text 인덱스(이미 있으면 무시). 4.2 와 동일."""
    session.run(
        f"CREATE FULLTEXT INDEX {FULLTEXT_INDEX} IF NOT EXISTS "
        "FOR (n:Mini) ON EACH [n.name, n.aliases]"
    )


def load(session) -> None:
    """보강된 미니 그래프를 MERGE 로 적재한다. 멱등(여러 번 돌려도 중복 안 쌓임)하다."""
    for e in ENTITIES:
        session.run(
            "MERGE (n:Mini {name: $name}) "
            "SET n.type = $type, n.community = $community, n.aliases = $aliases",
            name=e["name"], type=e["type"],
            community=e["community"], aliases=e["aliases"],
        )
    # 관계타입은 파라미터화가 안 돼 문자열로 끼운다. 입력이 코드 상수라 인젝션 위험은 없다.
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
            print(f"[load] 보강된 미니 그래프 적재 완료 — :Mini 노드 {len(ENTITIES)}개 "
                  f"+ 관계 {len(RELATIONS)}개")
            print(f"[index] full-text 인덱스 '{FULLTEXT_INDEX}' 준비 완료 (name + aliases)")
            print("[다음] python community_detect.py --write 로 Leiden 커뮤니티를 탐지·기록한다.")
    finally:
        driver.close()


if __name__ == "__main__":
    main(sys.argv)
