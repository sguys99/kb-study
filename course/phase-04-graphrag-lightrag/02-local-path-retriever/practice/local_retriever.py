"""4.2 local_retriever.py — Local 검색기. 엔티티 링킹 → 이웃 서브그래프 → 컨텍스트 문자열.

4.1 의 demo_local 은 "LightRAG 이웃을 보여 주는" 한 줄짜리였다. 여기서는 그걸
재사용 가능한 함수로 끌어올린다.
    - 시작 엔티티를 자연어 표현으로 받아 entity_linking 으로 먼저 노드에 꽂고,
    - depth(1~2홉)만큼 이웃을 모아,
    - LLM 이 그대로 읽을 수 있는 컨텍스트 문자열로 직렬화한다.

홉 수·노이즈 제어가 핵심이다. depth 를 키울수록 이웃이 폭증하므로 상한을 둔다.
컨텍스트 패킹·토큰 예산의 본격적인 다룸은 4.4(Vector+Graph Fusion)로 넘긴다.
여기서는 "이웃을 모아 문자열로 만든다"까지만 한다.

전제:
    - Neo4j 5.26 LTS 기동 + graph_setup.py 적재 완료.
    - 접속 정보는 NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD 환경변수. 키 불필요·과금 0.

실행:
    python local_retriever.py                 # 'LightRAG' 의 1~2홉 이웃 컨텍스트
    python local_retriever.py "light rag" 2   # 임의 표현 + depth 지정
"""

from __future__ import annotations

import sys

from entity_linking import link, get_driver


def collect_neighbors(session, name: str, depth: int = 1, limit: int = 30) -> list[dict]:
    """링크된 엔티티의 depth 홉 이웃을 (시작-관계-이웃) 삼중쌍으로 모은다.

    depth 1 이면 직접 이웃, 2 면 이웃의 이웃까지. 무방향(-[r]-)으로 훑어
    관계 방향에 갇히지 않게 한다(미니 그래프는 무방향처럼 읽어야 한다).
    상한 limit 으로 이웃 폭증을 막는다.
    """
    # 가변 길이 패턴 *1..depth 에는 상한이 반드시 있어야 한다(없으면 경로 폭발).
    # nodes(p)[-1] 가 도착 이웃, relationships(p)[-1] 가 마지막 홉 관계다.
    rows = session.run(
        f"MATCH p = (e:Mini {{name: $name}})-[*1..{depth}]-(nb:Mini) "
        "WITH nb, relationships(p) AS rels, length(p) AS d "
        "WITH DISTINCT nb, d, rels[-1] AS last_rel "
        "RETURN d AS hop, "
        "       startNode(last_rel).name AS src, type(last_rel) AS rel, "
        "       endNode(last_rel).name AS dst, "
        "       nb.name AS neighbor, nb.type AS ntype "
        "ORDER BY hop, neighbor "
        "LIMIT $limit",
        name=name, limit=limit,
    )
    return [dict(r) for r in rows]


def serialize_context(name: str, neighbors: list[dict]) -> str:
    """이웃 서브그래프를 LLM 컨텍스트로 쓸 사람이 읽는 문자열로 직렬화한다.

    각 줄을 'src -[REL]- dst' 한 사실로 적는다. 홉별로 묶어 가독성을 준다.
    이 문자열을 그대로 프롬프트의 근거 블록에 끼우면 된다.
    """
    if not neighbors:
        return f"[Local 컨텍스트] '{name}' 의 이웃이 없다(링킹 실패이거나 고립 노드)."

    lines = [f"[Local 컨텍스트] 시작 엔티티: {name}"]
    last_hop = None
    for nb in neighbors:
        if nb["hop"] != last_hop:
            lines.append(f"  -- {nb['hop']}홉 --")
            last_hop = nb["hop"]
        # 방향은 저장된 그대로(src -[REL]-> dst)를 보여 주되, 표기는 무방향처럼.
        lines.append(f"  {nb['src']} -[{nb['rel']}]- {nb['dst']}  "
                     f"(이웃: {nb['neighbor']}/{nb['ntype']})")
    return "\n".join(lines)


def local_retrieve(session, mention: str, depth: int = 1) -> str:
    """Local 검색 한 번 — 표현 링킹 → 이웃 수집 → 컨텍스트 문자열 반환."""
    linked = link(session, mention)
    if linked.name is None:
        return (f"[Local 컨텍스트] '{mention}' 를 그래프 노드로 링크하지 못했다. "
                "검색을 시작할 수 없다(그래프가 빈 게 아니라 링킹이 빗나간 것).")
    neighbors = collect_neighbors(session, linked.name, depth=depth)
    header = (f"(링킹: '{mention}' → :Mini({linked.name}) "
              f"[{linked.method}], depth={depth})")
    return header + "\n" + serialize_context(linked.name, neighbors)


def main(argv: list[str]) -> None:
    mention = argv[1] if len(argv) > 1 else "LightRAG"
    depth = int(argv[2]) if len(argv) > 2 else 1
    driver = get_driver()
    try:
        with driver.session() as session:
            print(local_retrieve(session, mention, depth=depth))
    finally:
        driver.close()


if __name__ == "__main__":
    main(sys.argv)
