"""4.2 entity_linking.py — 자연어 표현을 그래프 노드에 꽂는다(엔티티 링킹).

그래프 검색의 첫 관문은 "질문의 자연어 표현이 그래프의 어느 노드인가"다.
이게 빠지면 그래프 검색은 시작도 못 한다(빈 결과). 이 모듈이 그 관문을 맡는다.

링킹 절차(키 없이 도는 기본 경로):
    1) 후보 생성  — exact(name 정확히) → alias(별칭 정확히) → full-text(부분/유사)
                     순으로 후보를 모은다. full-text 는 graph_setup 의 miniNameFulltext 인덱스.
    2) 정규화     — 대소문자·공백·하이픈을 죽여(normalize) 비교한다.
    3) 최종 선택  — 가장 신뢰도 높은 후보 하나(또는 상위 N개)를 고른다.
                     exact > alias > full-text 점수 순.

임베딩 기반 링킹(선택 분기):
    full-text/alias 로도 안 잡히는 의역("그 그래프 데이터베이스" 같은)을 더 견고하게 잡으려면
    질문과 노드 name 을 임베딩해 코사인 유사도로 후보를 낸다. VOYAGE_API_KEY 가 있고
    voyageai 가 깔려 있을 때만 동작하고, 없으면 자동으로 None 을 돌려준다(기본 경로로 떨어짐).
    비용 0 로컬 대안은 BAAI/bge-m3(sentence-transformers) — 주석으로 자리만 표시.

전제:
    - Neo4j 5.26 LTS 기동 + graph_setup.py 로 :Mini 그래프와 full-text 인덱스 적재 완료.
    - 접속 정보는 NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD 환경변수.
    - 기본 경로는 키 불필요·과금 0. 임베딩 분기만 VOYAGE_API_KEY 사용.

실행:
    python entity_linking.py                 # 내장 예시 표현 몇 개를 링킹해 본다
    python entity_linking.py "light rag"     # 임의 표현 1개를 링킹
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass

from neo4j import GraphDatabase

from graph_setup import FULLTEXT_INDEX


@dataclass
class LinkResult:
    """링킹 결과 — 어떤 표현이 어느 노드로, 어떤 방식으로 얼마의 점수로 매핑됐나."""
    mention: str       # 입력 표현(질문에서 떼어 낸 자연어 조각)
    name: str | None   # 매핑된 :Mini 노드의 name (실패 시 None)
    method: str        # exact | alias | fulltext | embedding | none
    score: float       # 신뢰도(상대값). exact=1.0, alias=0.95, full-text/임베딩=원점수


def get_driver():
    """환경변수에서 접속 정보를 읽어 드라이버를 만든다. 비밀번호 하드코딩 금지."""
    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD", "testpassword1")
    return GraphDatabase.driver(uri, auth=(user, password))


def normalize(text: str) -> str:
    """대소문자·여분 공백·하이픈을 죽여 표기 흔들림을 흡수한다.

    'Light-RAG', 'light rag', 'LightRAG' 를 같은 키로 만든다.
    하이픈은 공백으로 바꾼 뒤 모든 공백을 제거해 'lightrag' 로 모은다.
    """
    low = text.strip().lower().replace("-", " ")
    return re.sub(r"\s+", "", low)


def link_exact(session, mention: str) -> LinkResult | None:
    """후보 ①: name 이 정규화 기준으로 정확히 일치하는 노드."""
    key = normalize(mention)
    rec = session.run(
        "MATCH (n:Mini) "
        # Cypher 쪽에서도 같은 정규화(소문자·하이픈→공백→공백제거)를 흉내 낸다.
        "WHERE replace(replace(toLower(n.name), '-', ''), ' ', '') = $key "
        "RETURN n.name AS name LIMIT 1",
        key=key,
    ).single()
    if rec is None:
        return None
    return LinkResult(mention, rec["name"], "exact", 1.0)


def link_alias(session, mention: str) -> LinkResult | None:
    """후보 ②: aliases 목록 중 하나와 정규화 기준으로 정확히 일치하는 노드."""
    key = normalize(mention)
    rec = session.run(
        "MATCH (n:Mini) "
        "WHERE any(a IN n.aliases "
        "          WHERE replace(replace(toLower(a), '-', ''), ' ', '') = $key) "
        "RETURN n.name AS name LIMIT 1",
        key=key,
    ).single()
    if rec is None:
        return None
    return LinkResult(mention, rec["name"], "alias", 0.95)


def link_fulltext(session, mention: str, top_k: int = 3) -> list[LinkResult]:
    """후보 ③: full-text 인덱스로 name·aliases 를 부분/유사 매칭한다.

    exact·alias 가 다 빗나간 의역·부분어("그래프 데이터베이스")를 잡는 그물이다.
    Lucene 점수를 그대로 score 로 쓴다(상대값이라 절댓값 자체엔 큰 의미 없음).
    """
    rows = session.run(
        "CALL db.index.fulltext.queryNodes($index, $q) "
        "YIELD node, score "
        "WHERE node:Mini "
        "RETURN node.name AS name, score "
        "ORDER BY score DESC LIMIT $k",
        index=FULLTEXT_INDEX, q=mention, k=top_k,
    )
    return [LinkResult(mention, r["name"], "fulltext", r["score"]) for r in rows]


def link_embedding(mention: str, candidates: list[str]) -> LinkResult | None:
    """선택 분기: 임베딩 코사인 유사도로 최적 후보를 고른다.

    VOYAGE_API_KEY 가 있고 voyageai 가 깔려 있을 때만 동작. 아니면 None(기본 경로로 떨어짐).
    비용 0 로 가려면 voyageai 대신 sentence-transformers + BAAI/bge-m3 로 바꾼다
    (아래 주석 자리). 파이프라인은 동일, 임베딩 함수만 교체하면 된다.
    """
    api_key = os.environ.get("VOYAGE_API_KEY")
    if not api_key or not candidates:
        return None
    try:
        import voyageai  # 선택 의존. 없으면 ImportError → 기본 경로로 떨어진다.
    except ImportError:
        return None

    client = voyageai.Client(api_key=api_key)
    texts = [mention] + candidates
    # voyage-3.5 로 한 번에 임베딩. query/document 구분이 필요하면 input_type 을 나눠도 된다.
    emb = client.embed(texts, model="voyage-3.5").embeddings
    q_vec = emb[0]
    cand_vecs = emb[1:]

    def cosine(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        na = sum(x * x for x in a) ** 0.5
        nb = sum(y * y for y in b) ** 0.5
        return dot / (na * nb) if na and nb else 0.0

    scored = sorted(
        ((cosine(q_vec, v), name) for v, name in zip(cand_vecs, candidates)),
        reverse=True,
    )
    best_score, best_name = scored[0]
    return LinkResult(mention, best_name, "embedding", best_score)

    # 비용 0 로컬 대안(bge-m3) — voyageai 블록을 아래로 갈아끼우면 키 없이 돈다:
    #   from sentence_transformers import SentenceTransformer
    #   model = SentenceTransformer("BAAI/bge-m3")
    #   vecs = model.encode([mention] + candidates, normalize_embeddings=True)
    #   q_vec, cand_vecs = vecs[0], vecs[1:]
    #   ... (코사인 동일)


def link(session, mention: str, use_embedding: bool = False) -> LinkResult:
    """표현 하나를 노드로 링킹한다. exact → alias → full-text(→ 선택적 임베딩) 순.

    하나라도 잡히면 가장 신뢰도 높은 후보를 돌려준다. 다 빗나가면 method='none'.
    """
    # ① exact
    hit = link_exact(session, mention)
    if hit is not None:
        return hit
    # ② alias
    hit = link_alias(session, mention)
    if hit is not None:
        return hit
    # ③ full-text — 상위 후보들
    ft = link_fulltext(session, mention)
    if ft:
        # 선택: 임베딩으로 full-text 후보들을 다시 정렬해 본다(키 있을 때만).
        if use_embedding:
            cand_names = [r.name for r in ft if r.name]
            emb_hit = link_embedding(mention, cand_names)
            if emb_hit is not None:
                return emb_hit
        return ft[0]
    # ④ 실패 — 빈 결과의 원인이 여기다. 그래프가 빈 게 아니라 링킹이 빗나간 것.
    return LinkResult(mention, None, "none", 0.0)


def _demo(driver, mentions: list[str]) -> None:
    use_emb = bool(os.environ.get("VOYAGE_API_KEY"))
    mode = "exact/alias/full-text (+임베딩)" if use_emb else "exact/alias/full-text"
    print(f"[엔티티 링킹] 방식: {mode}")
    with driver.session() as session:
        for m in mentions:
            r = link(session, m, use_embedding=use_emb)
            if r.name is None:
                print(f"  '{m}'  →  (링크 실패: 후보 없음)  [method=none]")
            else:
                print(f"  '{m}'  →  :Mini({r.name})  "
                      f"[method={r.method}, score={r.score:.3f}]")


def main(argv: list[str]) -> None:
    # 인자가 있으면 그 표현 하나를, 없으면 내장 예시들을 링킹한다.
    mentions = argv[1:] if len(argv) > 1 else [
        "LightRAG",                    # exact — name 정확 일치
        "light rag",                   # alias — 별칭 일치(공백 변형)
        "retrieval augmented generation",  # alias — RAG 의 풀어쓴 별칭
        "neo4j graph database",        # alias — Neo4j 별칭
        "벡터 검색",                    # alias(한글) — vector search 로
        "그래프 데이터베이스 같은 거",   # full-text — 부분 매칭에 기대는 의역
        "전혀 없는 표현 zzz",           # none — 일부러 빗나가게
    ]
    driver = get_driver()
    try:
        _demo(driver, mentions)
    finally:
        driver.close()


if __name__ == "__main__":
    main(sys.argv)
