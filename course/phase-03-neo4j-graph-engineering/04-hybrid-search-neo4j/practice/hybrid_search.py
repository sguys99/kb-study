"""Vector + Full-text + Graph 3중 하이브리드 검색.

03 은 그래프 절반(멀티홉 Cypher)을 보여줬다. 04 는 벡터·풀텍스트 절반을 더해 3중 융합을 완성한다.

흐름:
  1) 질문을 임베딩(add_embeddings.embed_texts 재사용 — 저장과 같은 모델이어야 한다).
  2) 벡터 검색   : db.index.vector.queryNodes('entity_embedding', k, $qvec)   → 의미 유사 시드.
  3) 풀텍스트 검색: db.index.fulltext.queryNodes('entity_fulltext', $qtext)    → 정확 용어 시드.
  4) RRF 융합    : 두 랭킹을 Reciprocal Rank Fusion(score = Σ 1/(k_rrf + rank), k_rrf=60)로
                   Python 에서 합산 → 상위 N 시드 엔티티 선정. (Neo4j 내장 RRF 가 없어 수동 융합.)
  5) 그래프 확장 : 각 시드에서 1~2홉 이웃·관계·source_ids 를 03 식 Cypher 로 끌어와 컨텍스트로 합침.

전제:
  - Neo4j 5.26 기동 + 02 적재 + add_embeddings.py + indexes.cypher 까지 끝난 상태.
  - pip install -r requirements.txt
  - 접속 정보 환경변수(02/03 규약과 동일):
      NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD (기본 bolt://localhost:7687 / neo4j / testpassword1)
  - 임베딩 백엔드:
      기본 voyage  → VOYAGE_API_KEY 필요(저장 때와 같은 모델).
      비용 0 분기  → --backend ollama (bge-m3). 저장도 ollama 로 했어야 일관된다.

실행:
  python hybrid_search.py                                  # 데모 질문 일괄 실행
  python hybrid_search.py --query "RAG를 개선하는 모델은?"   # 단일 질문
  python hybrid_search.py --backend ollama                 # 비용 0 로컬 임베딩
"""

import argparse
import os
import sys

from neo4j import GraphDatabase

# 같은 디렉토리의 add_embeddings 에서 임베딩 함수를 그대로 가져온다.
# 저장 임베딩과 질의 임베딩이 동일 모델이어야 코사인 유사도가 의미를 갖는다.
from add_embeddings import embed_texts

# --- 접속 정보(02/03 규약과 동일) -------------------------------------------
URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
AUTH = (
    os.environ.get("NEO4J_USER", "neo4j"),
    os.environ.get("NEO4J_PASSWORD", "testpassword1"),
)

K_VECTOR = 5      # 벡터 검색 top-k
K_RRF = 60        # RRF 상수(관례값). 클수록 상위 랭크 가중이 완만해진다.
TOP_SEEDS = 3     # 융합 후 그래프 확장에 쓸 시드 엔티티 수

# 데모 질문 — 03 과 이어지는 멀티홉 질문. 벡터/풀텍스트 단독 한계를 드러낸다.
DEMO_QUERIES = [
    "RAG를 개선하는 모델은?",
    "LightRAG가 쓰는 저장소",
]


# === 개별 검색 ===============================================================
def vector_search(driver, qvec: list[float], k: int = K_VECTOR) -> list[dict]:
    """네이티브 벡터 인덱스로 의미 유사 엔티티 top-k.

    반환: [{"name", "cid", "score"}] (score = 코사인 유사도, 클수록 가깝다)
    """
    with driver.session() as session:
        return session.execute_read(
            lambda tx: [
                {"name": r["name"], "cid": r["cid"], "score": r["score"]}
                for r in tx.run(
                    """
                    CALL db.index.vector.queryNodes('entity_embedding', $k, $qvec)
                    YIELD node, score
                    RETURN node.name AS name, node.canonical_id AS cid, score
                    """,
                    k=k,
                    qvec=qvec,
                )
            ]
        )


def fulltext_search(driver, qtext: str) -> list[dict]:
    """풀텍스트 인덱스로 키워드 매칭 엔티티.

    질의 문자열은 Lucene 문법을 탄다. 한글 질문은 그대로 넣어도 되지만, 약어·고유명사
    (RAG, LightRAG, Neo4j)가 description 에 영어로 있으므로 영어 키워드가 더 잘 맞는다.
    """
    with driver.session() as session:
        return session.execute_read(
            lambda tx: [
                {"name": r["name"], "cid": r["cid"], "score": r["score"]}
                for r in tx.run(
                    """
                    CALL db.index.fulltext.queryNodes('entity_fulltext', $qtext)
                    YIELD node, score
                    RETURN node.name AS name, node.canonical_id AS cid, score
                    """,
                    qtext=qtext,
                )
            ]
        )


# === RRF 융합 ================================================================
def reciprocal_rank_fusion(
    rankings: list[list[dict]], k_rrf: int = K_RRF
) -> list[dict]:
    """여러 랭킹을 RRF 로 합친다.

    각 랭킹에서 엔티티의 등수 rank(0부터)를 보고 1/(k_rrf + rank)를 더한다.
    원점수 스케일이 달라도(코사인 vs Lucene) 등수만 쓰므로 안전하게 융합된다.
    반환: [{"cid", "name", "rrf"}] rrf 내림차순.
    """
    scores: dict[str, float] = {}
    names: dict[str, str] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking):
            cid = item["cid"]
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k_rrf + rank)
            names[cid] = item["name"]
    fused = [
        {"cid": cid, "name": names[cid], "rrf": score}
        for cid, score in scores.items()
    ]
    fused.sort(key=lambda x: x["rrf"], reverse=True)
    return fused


# === 그래프 확장 =============================================================
def expand_graph(driver, seed_cids: list[str], hops: int = 2) -> list[dict]:
    """시드에서 1~hops 홉 이웃·관계·source_ids 를 끌어와 컨텍스트로 만든다.

    03 의 가변 길이 경로와 같은 발상이다. 여기선 시드에 붙은 관계 사실을 모은다.
    반환: [{"seed", "rel", "neighbor", "neighbor_type", "source_ids", "hop"}]
    """
    # hops 는 가변 길이 상한이라 파라미터로 못 받는다. 화이트리스트로 검증 후 문자열에 박는다.
    if hops not in (1, 2, 3):
        raise ValueError("hops 는 1~3 만 허용")
    cypher = f"""
        MATCH (seed:Entity) WHERE seed.canonical_id IN $cids
        MATCH path = (seed)-[rels*1..{hops}]-(nbr:Entity)
        WHERE nbr.canonical_id <> seed.canonical_id
        WITH seed, nbr, relationships(path) AS rels, length(path) AS hop
        RETURN DISTINCT
          seed.name AS seed,
          nbr.name AS neighbor,
          nbr.type AS neighbor_type,
          [r IN rels | type(r)] AS rel_chain,
          [r IN rels | coalesce(r.source_ids, [])] AS source_ids,
          hop
        ORDER BY hop, seed, neighbor
    """
    with driver.session() as session:
        return session.execute_read(
            lambda tx: [r.data() for r in tx.run(cypher, cids=seed_cids)]
        )


# === 한 질문 처리 ============================================================
def hybrid_answer(driver, query: str, backend: str) -> None:
    print(f"\n{'=' * 60}\n질문: {query}\n{'=' * 60}")

    qvec = embed_texts([query], backend=backend)[0]

    vec_hits = vector_search(driver, qvec)
    ft_hits = fulltext_search(driver, query)

    print("\n[벡터 단독 top-k]")
    _print_hits(vec_hits)
    print("\n[풀텍스트 단독]")
    _print_hits(ft_hits)

    fused = reciprocal_rank_fusion([vec_hits, ft_hits])
    print("\n[RRF 융합 후 상위]")
    for i, item in enumerate(fused[:TOP_SEEDS]):
        print(f"  {i + 1}. {item['name']:<14} rrf={item['rrf']:.4f}")

    seed_cids = [item["cid"] for item in fused[:TOP_SEEDS]]
    if not seed_cids:
        print("\n  (시드 없음 — 인덱스/임베딩이 채워졌는지 확인)")
        return

    expansion = expand_graph(driver, seed_cids, hops=2)
    print(f"\n[그래프 1~2홉 확장 — 시드 {len(seed_cids)}개 기준]")
    if not expansion:
        print("  (이웃 없음)")
    for row in expansion:
        chain = " -> ".join(row["rel_chain"])
        print(f"  ({row['hop']}홉) {row['seed']} --[{chain}]-- {row['neighbor']} "
              f"({row['neighbor_type']})")


def _print_hits(hits: list[dict]) -> None:
    if not hits:
        print("  (결과 없음)")
    for i, h in enumerate(hits):
        print(f"  {i + 1}. {h['name']:<14} score={h['score']:.4f}")


# === 엔트리포인트 ============================================================
def run(query: str | None, backend: str) -> int:
    queries = [query] if query else DEMO_QUERIES
    with GraphDatabase.driver(URI, auth=AUTH) as driver:
        driver.verify_connectivity()
        for q in queries:
            hybrid_answer(driver, q, backend)
    print("\n[OK] 하이브리드 검색 완료.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Vector + Full-text + Graph 하이브리드 검색")
    parser.add_argument("--query", default=None, help="단일 질문(미지정 시 데모 질문 일괄)")
    parser.add_argument(
        "--backend",
        choices=["voyage", "ollama"],
        default="voyage",
        help="질의 임베딩 백엔드(저장 때와 동일해야 함)",
    )
    args = parser.parse_args()
    return run(args.query, args.backend)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"[FAIL] {type(exc).__name__}: {exc}", file=sys.stderr)
        print("  - 02 적재 → add_embeddings.py → indexes.cypher 순서가 끝났는지 확인하라.",
              file=sys.stderr)
        print("  - 인덱스 ONLINE 여부: SHOW INDEXES (indexes.cypher 마지막 참고).",
              file=sys.stderr)
        print("  - 저장 임베딩과 질의 임베딩 backend 가 같은지 확인하라(voyage/ollama).",
              file=sys.stderr)
        sys.exit(1)
