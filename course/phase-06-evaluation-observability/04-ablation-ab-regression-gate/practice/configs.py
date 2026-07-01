# configs.py — 구성(configuration)별 검색 로그 + 고정 골든셋 (mock, 표준 라이브러리만)
#
# 왜 필요한가:
#   Ablation 은 "같은 질문셋을 서로 다른 구성으로 돌려 점수를 비교"하는 실험이다.
#   그러려면 (1) 고정된 골든 질문셋과 (2) 구성마다 달라지는 검색 결과가 필요하다.
#   실제로는 (2) 가 Phase 4 GraphRAG(LightRAG 5모드)·Phase 1 Baseline 을 각각 돌려
#   나온 로그다. 여기서는 상용 API 없이 로직을 익히려고 그 로그의 축소판을 손으로 적는다.
#
# 골든셋(GOLDEN): 질문마다 정답 근거(relevant)·필요 홉 수(required_hops)·정답 엔티티,
#   그리고 답변이 인용해야 할 골든 근거(gold_support)를 라벨로 박아 둔다. (02 골든셋의 축소판)
#
# 구성(CONFIGS): 각 구성이 질문마다 무엇을 검색했는지(retrieved), 어떤 엣지를 밟았는지
#   (traversed_edges), 어떤 엔티티를 건드렸는지(retrieved_entities), 답변이 무엇을 인용했는지
#   (cited) 를 담는다. 구성별로 이 값이 달라지는 게 Ablation 의 전부다:
#     - full        : 그래프 확장 + rerank 다 켠 GraphRAG(hybrid 지향). 멀티홉을 밟는다.
#     - vector_only : 그래프를 뗀 Phase 1 Baseline. 엣지를 안 밟아 멀티홉이 무너진다.
#     - no_rerank   : 그래프는 켜되 rerank 를 뗀 구성. 근거는 잡지만 정밀도가 흔들린다.
#     - lightrag_hybrid / lightrag_mix : A/B 비교용 두 LightRAG 모드.
#
# 전제: 외부 의존 없음. 표기(엔티티)는 02 와 동일한 표기 흔들림을 일부러 남겨 둔다.

from __future__ import annotations

# --------------------------------------------------------------------------
# 고정 골든셋 — 이 값은 구성이 바뀌어도 절대 변하지 않는다(정답이니까).
# --------------------------------------------------------------------------
GOLDEN = {
    "q1": {
        "question": "LightRAG 의 hybrid 모드는 무엇을 결합하나? (single-fact)",
        "relevant": ["c1", "c3"],
        "required_hops": 0,                       # 단일 사실 — 홉 불필요
        "gold_entities": ["hybrid retrieval"],
        "gold_support": ["c1", "c3"],
    },
    "q2": {
        "question": "커뮤니티 요약은 어느 논문 방법에서 왔나? (2-hop 멀티홉)",
        "relevant": ["c2", "c4"],
        "required_hops": 2,                       # From Local to Global → Leiden → community summary
        "gold_entities": ["From Local to Global", "Leiden", "community summary"],
        "gold_support": ["c2", "c4"],
    },
    "q3": {
        "question": "PageRank 로 중요 노드를 뽑은 논문과 그 데이터셋은? (2-hop 멀티홉)",
        "relevant": ["c5", "c6"],
        "required_hops": 2,
        "gold_entities": ["PageRank", "arXiv corpus"],
        "gold_support": ["c5", "c6"],
    },
}

QUESTION_IDS = ["q1", "q2", "q3"]


# --------------------------------------------------------------------------
# 구성별 검색 로그 — CONFIGS[config_name][question_id] = {검색이 실제로 한 일}
# --------------------------------------------------------------------------
CONFIGS: dict[str, dict[str, dict]] = {
    # (A) full GraphRAG: 그래프 확장 + rerank. 멀티홉을 밟고 정답 근거를 잇는다.
    "full": {
        "q1": {"retrieved": ["c1", "c3"], "traversed_edges": [],
               "retrieved_entities": ["hybrid retrieval"], "cited": ["c1", "c3"]},
        "q2": {"retrieved": ["c2", "c4"],
               "traversed_edges": [("From Local to Global", "Leiden"),
                                   ("Leiden", "community summary")],
               "retrieved_entities": ["from local to global", "leiden", "community summary"],
               "cited": ["c2", "c4"]},
        "q3": {"retrieved": ["c5", "c6"],
               "traversed_edges": [("Node2Vec paper", "PageRank"),
                                   ("PageRank", "arXiv corpus")],
               "retrieved_entities": ["pagerank", "arxiv corpus"],
               "cited": ["c5", "c6"]},
    },

    # (B) vector_only: Phase 1 Baseline. 그래프를 뗐다 → 엣지 0, 멀티홉 근거를 놓친다.
    "vector_only": {
        "q1": {"retrieved": ["c1", "c3"], "traversed_edges": [],
               "retrieved_entities": ["hybrid retrieval"], "cited": ["c1", "c3"]},
        "q2": {"retrieved": ["c2", "c9"], "traversed_edges": [],   # c4 를 못 잡음
               "retrieved_entities": ["community summary"], "cited": ["c2"]},
        "q3": {"retrieved": ["c5", "c8"], "traversed_edges": [],   # c6 를 못 잡음
               "retrieved_entities": ["pagerank"], "cited": ["c5"]},
    },

    # (C) no_rerank: 그래프는 켜되 rerank 를 뗐다 → 근거는 잡지만 노이즈가 섞여 정밀도 하락.
    "no_rerank": {
        "q1": {"retrieved": ["c1", "c3", "c7"], "traversed_edges": [],   # c7 노이즈
               "retrieved_entities": ["hybrid retrieval"], "cited": ["c1", "c3"]},
        "q2": {"retrieved": ["c2", "c4", "c9"],
               "traversed_edges": [("From Local to Global", "Leiden"),
                                   ("Leiden", "community summary")],
               "retrieved_entities": ["from local to global", "leiden", "community summary"],
               "cited": ["c2", "c4"]},
        "q3": {"retrieved": ["c5", "c6", "c8"],
               "traversed_edges": [("Node2Vec paper", "PageRank"),
                                   ("PageRank", "arXiv corpus")],
               "retrieved_entities": ["pagerank", "arxiv corpus"],
               "cited": ["c5", "c6"]},
    },

    # (D) lightrag_hybrid: A/B 비교용. full 과 거의 같되 q3 에서 1홉만 밟음(부분 점수).
    "lightrag_hybrid": {
        "q1": {"retrieved": ["c1", "c3"], "traversed_edges": [],
               "retrieved_entities": ["hybrid retrieval"], "cited": ["c1", "c3"]},
        "q2": {"retrieved": ["c2", "c4"],
               "traversed_edges": [("From Local to Global", "Leiden"),
                                   ("Leiden", "community summary")],
               "retrieved_entities": ["from local to global", "leiden", "community summary"],
               "cited": ["c2", "c4"]},
        "q3": {"retrieved": ["c5", "c6"],
               "traversed_edges": [("Node2Vec paper", "PageRank")],   # 1홉만 → 부분 점수
               "retrieved_entities": ["pagerank"], "cited": ["c5"]},
    },

    # (E) lightrag_mix: A/B 비교용. 전역 요약을 섞어 멀티홉/엔티티는 강하나 q1 정밀도 소폭 손해.
    "lightrag_mix": {
        "q1": {"retrieved": ["c1", "c3", "c7"], "traversed_edges": [],  # 요약 청크 c7 섞임
               "retrieved_entities": ["hybrid retrieval"], "cited": ["c1", "c3"]},
        "q2": {"retrieved": ["c2", "c4"],
               "traversed_edges": [("From Local to Global", "Leiden"),
                                   ("Leiden", "community summary")],
               "retrieved_entities": ["from local to global", "leiden", "community summary"],
               "cited": ["c2", "c4"]},
        "q3": {"retrieved": ["c5", "c6"],
               "traversed_edges": [("Node2Vec paper", "PageRank"),
                                   ("PageRank", "arXiv corpus")],
               "retrieved_entities": ["pagerank", "arxiv corpus"],
               "cited": ["c5", "c6"]},
    },
}
