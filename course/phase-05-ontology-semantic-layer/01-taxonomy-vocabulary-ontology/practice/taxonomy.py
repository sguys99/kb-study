"""
taxonomy.py — 분류체계(Taxonomy): broader/narrower 계층

전제:
  - 외부 의존 없음(순수 파이썬 경로). API 키·Neo4j 불필요.
  - rdflib 는 선택. 깔려 있으면 같은 계층을 SKOS 트리플로도 보여준다.

배우는 것:
  Taxonomy 는 개념 사이의 is-a / broader-narrower(상위-하위) 관계만 담는 계층이다.
  Phase 2 에서 뽑은 엔티티 타입(Concept/Method/Dataset/Metric/Paper)과 실제 기법들을
  "무엇이 무엇의 하위 개념인가"로 줄 세운다.
  예) self-rag(하위) → retrieval-method → method(상위).

주의:
  Taxonomy 는 계층만 안다. "Self-RAG 의 표준 표기가 무엇인가"(→ Vocabulary),
  "USES 관계의 주어·목적어 타입이 무엇인가"(→ Ontology)는 여기서 다루지 않는다.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# 1) 순수 파이썬 taxonomy — concept_id -> 바로 위(broader) concept_id
#    코퍼스 도메인(AI/LLM 기술 문서)에 맞춘 mini taxonomy.
# ---------------------------------------------------------------------------

# broader: 자식 -> 부모 (한 단계 위). 루트는 부모가 없다.
BROADER: dict[str, str] = {
    # 최상위 타입
    "method": "concept",              # Method 는 넓게 보면 Concept 의 한 종류
    "dataset": "concept",
    "metric": "concept",
    # Method 하위 분류
    "retrieval-method": "method",
    "generation-method": "method",
    # 실제 기법(잎 노드)
    "self-rag": "retrieval-method",
    "crag": "retrieval-method",
    "hybrid-rag": "retrieval-method",
    "graphrag": "retrieval-method",
    # Dataset 하위
    "qa-dataset": "dataset",
    "popqa": "qa-dataset",
    # Metric 하위
    "answer-metric": "metric",
    "accuracy": "answer-metric",
}

# 사람이 읽는 라벨(선택). 질의 출력에만 쓴다.
LABEL: dict[str, str] = {
    "concept": "Concept",
    "method": "Method",
    "dataset": "Dataset",
    "metric": "Metric",
    "retrieval-method": "Retrieval Method",
    "generation-method": "Generation Method",
    "self-rag": "Self-RAG",
    "crag": "CRAG",
    "hybrid-rag": "Hybrid RAG",
    "graphrag": "GraphRAG",
    "qa-dataset": "QA Dataset",
    "popqa": "PopQA",
    "answer-metric": "Answer Metric",
    "accuracy": "Accuracy",
}


def broader_path(concept_id: str) -> list[str]:
    """concept_id 에서 루트까지 올라가는 상위 개념 경로를 반환한다.

    예) broader_path("self-rag")
        -> ["self-rag", "retrieval-method", "method", "concept"]
    존재하지 않는 concept_id 는 KeyError.
    """
    if concept_id not in BROADER and concept_id not in LABEL:
        raise KeyError(f"taxonomy 에 없는 개념: {concept_id!r}")
    path = [concept_id]
    current = concept_id
    # 부모가 있는 동안 계속 올라간다(사이클이 없다는 전제 — 잎에서 루트까지 유한).
    while current in BROADER:
        current = BROADER[current]
        path.append(current)
    return path


def narrower(concept_id: str) -> list[str]:
    """concept_id 의 바로 아래(직속 하위) 개념들을 반환한다."""
    return sorted(child for child, parent in BROADER.items() if parent == concept_id)


def is_a(child: str, ancestor: str) -> bool:
    """child 가 ancestor 의 (직·간접) 하위 개념이면 True.

    예) is_a("self-rag", "method") -> True
        is_a("self-rag", "dataset") -> False
    """
    return ancestor in broader_path(child)


def _pretty(concept_id: str) -> str:
    return LABEL.get(concept_id, concept_id)


# ---------------------------------------------------------------------------
# 2) (선택) 같은 계층을 SKOS 트리플로 — rdflib 가 있을 때만.
#    SKOS: skos:broader 로 상위-하위를 표준 표현한다.
# ---------------------------------------------------------------------------

def build_skos_graph():
    """rdflib 로 동일 계층을 SKOS(skos:broader) 그래프로 만든다.

    rdflib 미설치면 ImportError 를 그대로 올린다(호출부에서 건너뛴다).
    """
    from rdflib import Graph, Namespace, Literal, RDF
    from rdflib.namespace import SKOS

    EX = Namespace("http://example.org/kb/")
    g = Graph()
    g.bind("skos", SKOS)
    g.bind("ex", EX)

    for cid in set(BROADER) | set(BROADER.values()) | set(LABEL):
        node = EX[cid]
        g.add((node, RDF.type, SKOS.Concept))
        g.add((node, SKOS.prefLabel, Literal(_pretty(cid), lang="en")))
    for child, parent in BROADER.items():
        g.add((EX[child], SKOS.broader, EX[parent]))
    return g


if __name__ == "__main__":
    print("== broader path (self-rag 의 상위 경로) ==")
    path = broader_path("self-rag")
    print(" -> ".join(_pretty(c) for c in path))

    print("\n== narrower (retrieval-method 의 직속 하위) ==")
    for child in narrower("retrieval-method"):
        print(f"  - {_pretty(child)}  ({child})")

    print("\n== is-a 판정 ==")
    for child, anc in [("self-rag", "method"), ("self-rag", "dataset"), ("popqa", "dataset")]:
        print(f"  is_a({child!r}, {anc!r}) = {is_a(child, anc)}")

    # (선택) SKOS 트리플 — rdflib 있을 때만
    print("\n== SKOS 트리플(rdflib, 선택) ==")
    try:
        g = build_skos_graph()
        # self-rag 의 skos:broader 만 골라 몇 줄 찍는다.
        from rdflib import Namespace
        EX = Namespace("http://example.org/kb/")
        from rdflib.namespace import SKOS
        for _, _, parent in g.triples((EX["self-rag"], SKOS.broader, None)):
            print(f"  ex:self-rag skos:broader {parent.n3(g.namespace_manager)}")
        print(f"  (총 트리플 수: {len(g)})")
    except ImportError:
        print("  rdflib 미설치 — 순수 파이썬 경로만 사용(정상). "
              "보려면 requirements.txt 의 rdflib 주석을 푼다.")
