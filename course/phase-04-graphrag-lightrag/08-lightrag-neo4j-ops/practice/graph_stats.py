"""Neo4j 그래프와 DocStatus 상태를 세는 작은 헬퍼.

incremental_insert.py · delete_ops.py 가 "적재/삭제 전후"를 수치로 대조할 때 쓴다.
Neo4j 노드/관계 수는 Bolt 드라이버로 직접 Cypher 를 던져 읽는다(LightRAG 우회).
문서 처리 상태는 LightRAG 의 DocStatus 스토리지에서 읽는다.

전제: NEO4J_URI / NEO4J_USERNAME / NEO4J_PASSWORD / NEO4J_DATABASE 가 .env 에 있다.
"""

import os

from neo4j import GraphDatabase


def neo4j_counts() -> dict:
    """Neo4j 의 전체 노드 수와 관계 수를 센다. (엔티티=노드, 관계=엣지)"""
    uri = os.environ["NEO4J_URI"]
    user = os.environ["NEO4J_USERNAME"]
    password = os.environ["NEO4J_PASSWORD"]
    database = os.environ.get("NEO4J_DATABASE", "neo4j")

    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        with driver.session(database=database) as session:
            nodes = session.run("MATCH (n) RETURN count(n) AS c").single()["c"]
            rels = session.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
        return {"nodes": nodes, "relationships": rels}
    finally:
        driver.close()


async def doc_status_summary(rag) -> dict:
    """LightRAG DocStatus 스토리지에서 상태별 문서 수를 읽는다.

    상태: pending / processing / processed / failed. 증분·삭제로 어떻게 바뀌는지 본다.
    """
    counts = await rag.aget_docs_by_status_counts() if hasattr(rag, "aget_docs_by_status_counts") else {}
    if counts:
        return counts
    # 폴백: 상태별로 직접 센다(LightRAG 버전에 따라 헬퍼명이 다를 수 있어 안전하게).
    summary: dict = {}
    for status in ("pending", "processing", "processed", "failed"):
        try:
            docs = await rag.aget_docs_by_status(status)
            summary[status] = len(docs)
        except Exception:
            summary[status] = "n/a"
    return summary


def print_delta(label: str, before: dict, after: dict) -> None:
    """before/after dict 를 키별 증감과 함께 출력한다."""
    print(f"\n[{label}] 전후 비교")
    keys = sorted(set(before) | set(after))
    for k in keys:
        b = before.get(k, 0)
        a = after.get(k, 0)
        delta = ""
        if isinstance(b, int) and isinstance(a, int):
            sign = "+" if a - b >= 0 else ""
            delta = f"  ({sign}{a - b})"
        print(f"  {k:16} {str(b):>8} -> {str(a):>8}{delta}")
