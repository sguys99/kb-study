"""4.2 path_retriever.py — Path 검색기. 두 표현 → 양끝 링킹 → 멀티홉 경로 → 근거 문장열.

Phase 0 에서 무너졌던 멀티홉을 정면으로 메우는 검색기다.
"A와 B는 어떻게 연결되나" 류 질문에서 Vector+BM25 는 A·B 가 같은 청크에 안 나오면
둘의 관계를 못 찾는다. 그래프는 중간 노드를 디딤돌 삼아 길을 잇는다.

절차:
    1) 두 자연어 표현을 각각 entity_linking 으로 양 끝 노드에 꽂는다.
    2) shortestPath 로 최단 경로를, 필요하면 가변 길이 경로로 여러 경로를 추적한다.
    3) 경로를 사람이 읽는 근거 문장열("A -[REL]- B -[REL]- C")로 변환한다.

경로 폭발 주의: 가변 길이 [*..N] 에는 반드시 상한 N 을 둔다. [*] 처럼 상한 없이 쓰면
큰 그래프에서 경로가 폭발해 타임아웃 난다.

전제:
    - Neo4j 5.26 LTS 기동 + graph_setup.py 적재 완료.
    - 접속 정보는 NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD 환경변수. 키 불필요·과금 0.

실행:
    python path_retriever.py                          # 'Neo4j' ↔ 'RAG' 최단 경로
    python path_retriever.py "light rag" "벡터 검색"   # 임의 두 표현
"""

from __future__ import annotations

import sys

from entity_linking import link, get_driver

# 가변 길이 경로의 상한. 미니 그래프엔 6이면 충분하다. 큰 그래프에선 더 낮춰 잡는다.
MAX_HOPS = 6


def shortest_path(session, start_name: str, end_name: str) -> list[str] | None:
    """두 노드 사이 최단 경로의 노드 이름 시퀀스를 돌려준다(없으면 None).

    무방향(-[*..N]-)으로 잡아 관계 방향에 갇히지 않게 한다.
    상한 MAX_HOPS 가 경로 폭발을 막는다.
    """
    rec = session.run(
        "MATCH (a:Mini {name: $start}), (b:Mini {name: $end}), "
        f"p = shortestPath((a)-[*..{MAX_HOPS}]-(b)) "
        "RETURN [n IN nodes(p) | n.name] AS hops, "
        "       [r IN relationships(p) | type(r)] AS rels",
        start=start_name, end=end_name,
    ).single()
    if rec is None:
        return None
    # 노드와 관계를 번갈아 끼워 'A -[REL]- B -[REL]- C' 형태의 문장열로 만든다.
    nodes = rec["hops"]
    rels = rec["rels"]
    parts: list[str] = [nodes[0]]
    for rel, nxt in zip(rels, nodes[1:]):
        parts.append(f"-[{rel}]-")
        parts.append(nxt)
    return parts


def all_shortest_paths(session, start_name: str, end_name: str, limit: int = 3) -> list[list[str]]:
    """같은 최단 길이의 경로가 여럿일 때 모두 가져온다(상위 limit개).

    allShortestPaths 는 최단 길이에 해당하는 모든 경로를 돌려준다.
    경로가 여러 갈래로 갈릴 수 있는 질문에서 근거를 풍부하게 한다.
    """
    rows = session.run(
        "MATCH (a:Mini {name: $start}), (b:Mini {name: $end}), "
        f"p = allShortestPaths((a)-[*..{MAX_HOPS}]-(b)) "
        "RETURN [n IN nodes(p) | n.name] AS hops "
        "LIMIT $limit",
        start=start_name, end=end_name, limit=limit,
    )
    return [r["hops"] for r in rows]


def path_retrieve(session, mention_a: str, mention_b: str) -> str:
    """Path 검색 한 번 — 두 표현 링킹 → 최단 경로 → 근거 문장열 반환."""
    a = link(session, mention_a)
    b = link(session, mention_b)

    # 한쪽이라도 링킹 실패면 경로 추적을 시작할 수 없다. 빈 결과의 흔한 원인이다.
    if a.name is None or b.name is None:
        fails = [m for m, r in ((mention_a, a), (mention_b, b)) if r.name is None]
        return (f"[Path 컨텍스트] 링킹 실패 — {fails} 를 노드로 꽂지 못했다. "
                "경로 검색을 시작할 수 없다.")

    header = (f"(링킹: '{mention_a}' → {a.name} [{a.method}], "
              f"'{mention_b}' → {b.name} [{b.method}])")

    path = shortest_path(session, a.name, b.name)
    if path is None:
        return header + f"\n[Path 컨텍스트] {a.name} ↔ {b.name}: 연결 경로 없음."

    hop_len = (len(path) - 1) // 2  # 'N -[r]- N -[r]- N' 에서 관계 개수 = 홉 수
    body = (f"[Path 컨텍스트] {a.name} ↔ {b.name} 최단 경로 (길이 {hop_len} 홉)\n"
            f"  {' '.join(path)}")

    # 같은 길이의 다른 경로가 있으면 함께 보여 준다(근거 보강).
    alts = all_shortest_paths(session, a.name, b.name)
    if len(alts) > 1:
        body += f"\n  (같은 길이 경로 {len(alts)}개 중 일부:)"
        for nodes in alts:
            body += "\n    " + " → ".join(nodes)
    return header + "\n" + body


def main(argv: list[str]) -> None:
    mention_a = argv[1] if len(argv) > 1 else "Neo4j"
    mention_b = argv[2] if len(argv) > 2 else "RAG"
    driver = get_driver()
    try:
        with driver.session() as session:
            print(path_retrieve(session, mention_a, mention_b))
    finally:
        driver.close()


if __name__ == "__main__":
    main(sys.argv)
