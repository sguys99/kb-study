"""관리형 트랜잭션 + MERGE 로 소수 노드/관계를 idempotent 하게 적재.

Phase 2/06 산출물 형식을 그대로 흉내 낸 소규모 샘플을 적재한다.
  - 엔티티: {canonical_id, name, type}        (sample_canonical_entities.jsonl 형식)
  - 관계  : {head_id, type, tail_id}           (normalized_relations 의 head/type/tail 을 id 로)

핵심: 같은 적재를 두 번 돌려도 노드·관계 수가 늘지 않아야 한다(idempotent).
대량 적재(UNWIND 배치)는 토픽 02 에서 다룬다. 여기서는 MERGE 의미론을 눈으로 확인하는 게 목적.

전제:
  - Neo4j 5.26 기동 중(bolt://localhost:7687)
  - pip install -r requirements.txt
  - (선택) indexes.cypher 로 canonical_id 유니크 제약을 먼저 걸면 더 안전·빠르다.

실행:
  python transactions.py
"""

import os
import sys

from neo4j import GraphDatabase

URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
AUTH = (
    os.environ.get("NEO4J_USER", "neo4j"),
    os.environ.get("NEO4J_PASSWORD", "testpassword1"),
)

# Phase 2/06 코퍼스 엔티티 일부(연속성을 위해 같은 canonical_id 사용).
ENTITIES = [
    {"canonical_id": "ent-model-lightrag", "name": "LightRAG", "type": "Model"},
    {"canonical_id": "ent-tool-neo4j", "name": "Neo4j", "type": "Tool"},
    {"canonical_id": "ent-model-rag", "name": "RAG", "type": "Model"},
    {"canonical_id": "ent-model-self-rag", "name": "Self-RAG", "type": "Model"},
    {"canonical_id": "ent-model-crag", "name": "CRAG", "type": "Model"},
]

# normalized_relations.jsonl 의 head/type/tail 을 canonical_id 로 옮긴 형태.
RELATIONS = [
    {"head_id": "ent-model-lightrag", "type": "USES", "tail_id": "ent-tool-neo4j"},
    {"head_id": "ent-model-self-rag", "type": "IMPROVES", "tail_id": "ent-model-rag"},
    {"head_id": "ent-model-crag", "type": "IMPROVES", "tail_id": "ent-model-rag"},
]

# 관계 타입은 Cypher 에서 파라미터로 못 넣어 f-string 으로 끼운다.
# 외부 입력을 그대로 넣으면 주입 위험이 있으니, 코드가 통제하는 화이트리스트만 허용.
ALLOWED_REL_TYPES = {"USES", "IMPROVES"}


def upsert_entity(tx, ent: dict) -> None:
    # canonical_id 를 키로 MERGE — 같은 id 면 노드를 재사용한다(idempotent).
    # ON CREATE 는 최초 생성 시 1 회, SET 은 매번 최신 속성으로 갱신.
    tx.run(
        """
        MERGE (n:Entity {canonical_id: $canonical_id})
        ON CREATE SET n.created = timestamp()
        SET n.name = $name, n.type = $type
        """,
        canonical_id=ent["canonical_id"],
        name=ent["name"],
        type=ent["type"],
    )


def upsert_relation(tx, head_id: str, rel_type: str, tail_id: str) -> None:
    if rel_type not in ALLOWED_REL_TYPES:
        raise ValueError(f"허용되지 않은 관계 타입: {rel_type}")
    # 양 끝 노드를 MERGE 로 보장한 뒤 관계도 MERGE — (head,type,tail) 가 키.
    tx.run(
        f"""
        MERGE (h:Entity {{canonical_id: $head_id}})
        MERGE (t:Entity {{canonical_id: $tail_id}})
        MERGE (h)-[r:{rel_type}]->(t)
        ON CREATE SET r.created = timestamp()
        """,
        head_id=head_id,
        tail_id=tail_id,
    )


def count_graph(tx):
    # 노드 수와 관계 수를 한 번에 센다.
    rec = tx.run(
        """
        MATCH (n:Entity)
        OPTIONAL MATCH ()-[r]->()
        RETURN count(DISTINCT n) AS nodes, count(r) AS rels
        """
    ).single()
    return rec["nodes"], rec["rels"]


def load_once(driver) -> tuple[int, int]:
    with driver.session() as session:
        for ent in ENTITIES:
            session.execute_write(upsert_entity, ent)
        for rel in RELATIONS:
            session.execute_write(
                upsert_relation, rel["head_id"], rel["type"], rel["tail_id"]
            )
        nodes, rels = session.execute_read(count_graph)
    return nodes, rels


def main() -> int:
    with GraphDatabase.driver(URI, auth=AUTH) as driver:
        driver.verify_connectivity()

        # 1 회차 적재
        n1, r1 = load_once(driver)
        print(f"[1회차] nodes={n1} rels={r1}")

        # 2 회차 적재 — MERGE 가 제대로 걸렸으면 수가 그대로여야 한다.
        n2, r2 = load_once(driver)
        print(f"[2회차] nodes={n2} rels={r2}")

        if (n1, r1) == (n2, r2):
            print("[OK] idempotent 확인 — 두 번 적재해도 노드·관계 수가 동일하다.")
            return 0
        print("[FAIL] 수가 늘었다 — MERGE 키나 CREATE 사용을 점검하라.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"[FAIL] {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
