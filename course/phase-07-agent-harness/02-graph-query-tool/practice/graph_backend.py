"""graph_backend.py — 그래프 질의 백엔드. mock in-memory 그래프(기본) + Neo4j 연결 분기.

이 파일이 하는 일: 'Cypher 비슷한 읽기 질의를 받아 결과 행을 돌려주는' 백엔드 하나를 고정한다.
graph_query 도구(3-백엔드)의 template·text2cypher 경로가 결국 여기로 내려온다.

두 경로:
  1) 기본(비용 0) — 작은 in-memory 속성 그래프 + Cypher 부분집합 실행기(MockGraph).
     Neo4j·API 키·Docker 없이도 Phase 7 을 단독으로 돌리려는 것.
     지원하는 패턴은 딱 두 가지: '엔티티 X 의 이웃', 'X 와 Y 사이 경로'. 템플릿과 1:1로 맞췄다.
  2) 실전 경로 — Neo4j 드라이버(session.execute_read)로 '읽기 전용' 질의.
     환경변수(NEO4J_URI 등)가 있으면 자동으로 붙는다. 없으면 조용히 mock 을 쓴다.

읽기 전용 강제:
  - Neo4j 경로는 session.execute_read 로만 실행한다(쓰기 트랜잭션 함수를 아예 안 쓴다).
  - text2cypher 가 생성한 문자열에 CREATE/DELETE 같은 쓰기 키워드가 있으면 어떻게 막을지는
    '03-cypher-safety-ontology-check' 에서 Safety Guard 로 완성한다. 여기서는 미완성이다.

전제(실전 경로만): Neo4j 5.26 LTS(또는 2025+ CalVer), `pip install neo4j`,
  환경변수 NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD. mock 경로는 표준 라이브러리만.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


# ── in-memory 속성 그래프(mock) ─────────────────────────────────────────────
# Part 2 러닝 코퍼스(RAG/GraphRAG 기술 문서)의 축소 KG 다.
# Phase 2~3 에서 만든 KG 를 이 토픽만 단독으로 돌릴 수 있게 손으로 축약해 넣었다.
# 노드: id·label·name / 엣지: (src)-[type]->(dst)
@dataclass
class Node:
    id: str
    label: str
    name: str


@dataclass
class Edge:
    src: str
    type: str
    dst: str


@dataclass
class MockGraph:
    """작은 속성 그래프 + 딱 필요한 만큼의 읽기 질의만 지원하는 실행기."""

    nodes: dict[str, Node] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)

    def add_node(self, node: Node) -> None:
        self.nodes[node.id] = node

    def add_edge(self, edge: Edge) -> None:
        self.edges.append(edge)

    # 템플릿 'neighbors' 의 실제 실행: 이름으로 노드를 찾아 1-홉 이웃을 돌려준다.
    def neighbors(self, name: str, limit: int = 10) -> list[dict]:
        start = self._find_by_name(name)
        if start is None:
            return []
        rows: list[dict] = []
        for e in self.edges:
            if e.src == start.id:
                nb = self.nodes.get(e.dst)
                if nb:
                    rows.append(self._neighbor_row(start, e.type, nb, "->"))
            elif e.dst == start.id:
                nb = self.nodes.get(e.src)
                if nb:
                    rows.append(self._neighbor_row(start, e.type, nb, "<-"))
        return rows[:limit]

    # 템플릿 'path_between' 의 실제 실행: 두 이름 사이 최단 경로(무향, BFS)를 돌려준다.
    def path_between(self, source: str, target: str, max_hops: int = 4) -> list[dict]:
        s = self._find_by_name(source)
        t = self._find_by_name(target)
        if s is None or t is None:
            return []
        # 인접 리스트(무향).
        adj: dict[str, list[tuple[str, str]]] = {}
        for e in self.edges:
            adj.setdefault(e.src, []).append((e.dst, e.type))
            adj.setdefault(e.dst, []).append((e.src, e.type))
        # BFS 로 최단 경로 한 개.
        queue: list[tuple[str, list[tuple[str, str]]]] = [(s.id, [])]
        visited = {s.id}
        while queue:
            cur, trail = queue.pop(0)
            if len(trail) > max_hops:
                continue
            if cur == t.id:
                return self._path_rows(s, trail)
            for nxt, etype in adj.get(cur, []):
                if nxt not in visited:
                    visited.add(nxt)
                    queue.append((nxt, trail + [(nxt, etype)]))
        return []

    def _neighbor_row(self, start: Node, etype: str, nb: Node, direction: str) -> dict:
        return {
            "entity": start.name,
            "relation": etype,
            "direction": direction,
            "neighbor": nb.name,
            "neighbor_label": nb.label,
            "source": nb.id,  # 인용 가능한 근거 식별자(노드 id).
        }

    def _path_rows(self, start: Node, trail: list[tuple[str, str]]) -> list[dict]:
        rows: list[dict] = []
        prev = start
        for node_id, etype in trail:
            cur = self.nodes[node_id]
            rows.append(
                {
                    "from": prev.name,
                    "relation": etype,
                    "to": cur.name,
                    "source": cur.id,
                }
            )
            prev = cur
        return rows

    def _find_by_name(self, name: str) -> Node | None:
        # 대소문자·공백을 관대하게 매칭(mock 편의). 실전 Neo4j 는 정확 매칭/인덱스를 쓴다.
        key = name.strip().lower()
        for n in self.nodes.values():
            if n.name.strip().lower() == key:
                return n
        # 부분 일치 폴백.
        for n in self.nodes.values():
            if key in n.name.strip().lower():
                return n
        return None


def build_mock_graph() -> MockGraph:
    """축소 KG 를 만든다. RAG 계열 기법과 그 구성요소를 노드·관계로 이었다."""
    g = MockGraph()
    nodes = [
        Node("e-self-rag", "Method", "Self-RAG"),
        Node("e-crag", "Method", "CRAG"),
        Node("e-adaptive-rag", "Method", "Adaptive-RAG"),
        Node("e-agentic-rag", "Concept", "Agentic RAG"),
        Node("e-reflection-token", "Component", "Reflection Token"),
        Node("e-retrieval-evaluator", "Component", "Retrieval Evaluator"),
        Node("e-query-router", "Component", "Query Router"),
        Node("e-tool-use", "Concept", "Tool Use"),
        Node("e-graphrag", "Concept", "GraphRAG"),
        Node("e-lightrag", "Framework", "LightRAG"),
    ]
    for n in nodes:
        g.add_node(n)
    edges = [
        Edge("e-self-rag", "USES", "e-reflection-token"),
        Edge("e-crag", "USES", "e-retrieval-evaluator"),
        Edge("e-adaptive-rag", "USES", "e-query-router"),
        Edge("e-self-rag", "IS_A", "e-agentic-rag"),
        Edge("e-crag", "IS_A", "e-agentic-rag"),
        Edge("e-adaptive-rag", "IS_A", "e-agentic-rag"),
        Edge("e-agentic-rag", "BUILT_ON", "e-tool-use"),
        Edge("e-lightrag", "IMPLEMENTS", "e-graphrag"),
        Edge("e-graphrag", "EXTENDS", "e-agentic-rag"),
    ]
    for e in edges:
        g.add_edge(e)
    return g


# ── Neo4j 실전 백엔드(있을 때만) ────────────────────────────────────────────
class Neo4jBackend:
    """Neo4j 읽기 전용 실행기. session.execute_read 로만 돈다.

    쓰기 트랜잭션 함수를 아예 노출하지 않는 것이 1차 방어선이다.
    text2cypher 문자열 자체의 위험(주석 뒤 CREATE 등)을 막는 것은 03 Safety Guard 몫이다.
    """

    def __init__(self) -> None:
        from neo4j import GraphDatabase  # 실전 경로에서만 import.

        uri = os.environ["NEO4J_URI"]
        user = os.environ.get("NEO4J_USER", "neo4j")
        pw = os.environ["NEO4J_PASSWORD"]
        self._driver = GraphDatabase.driver(uri, auth=(user, pw))
        self.mode = "neo4j"

    def run_read(self, cypher: str, params: dict) -> list[dict]:
        """읽기 전용 실행. execute_read 안에서만 session.run 을 부른다."""

        def _work(tx):
            result = tx.run(cypher, **params)
            return [dict(record) for record in result]

        with self._driver.session(database=os.environ.get("NEO4J_DB", "neo4j")) as session:
            return session.execute_read(_work)

    def close(self) -> None:
        self._driver.close()


def make_graph_backend():
    """환경변수에 Neo4j 접속 정보가 있으면 Neo4j, 없으면 mock 그래프.

    돌려주는 값: (kind, backend)
      kind == "mock"  → backend 는 MockGraph (neighbors/path_between 메서드 사용)
      kind == "neo4j" → backend 는 Neo4jBackend (run_read(cypher, params) 사용)
    """
    if os.environ.get("NEO4J_URI") and os.environ.get("NEO4J_PASSWORD"):
        try:
            return "neo4j", Neo4jBackend()
        except Exception:
            # 접속 실패 시 조용히 mock 으로 폴백(단독 실행 보장).
            pass
    return "mock", build_mock_graph()


if __name__ == "__main__":
    kind, backend = make_graph_backend()
    print(f"[graph_backend] kind={kind}\n")
    if kind == "mock":
        print("neighbors('Self-RAG'):")
        for row in backend.neighbors("Self-RAG"):
            print("  ", row)
        print("\npath_between('LightRAG', 'Tool Use'):")
        for row in backend.path_between("LightRAG", "Tool Use"):
            print("  ", row)
