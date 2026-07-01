# sample_data.py — 스코어카드 하니스가 먹는 작은 샘플 데이터 (golden ↔ 예측)
#
# 전제:
#   - 실제로는 이 데이터가 앞 Phase 산출물에서 나온다:
#       Construction : Phase 2 그래프 구축 결과(노드/엣지)
#       Retrieval    : Phase 4 GraphRAG(LightRAG 5모드) 검색 결과 vs Golden Question 정답 근거
#       Generation   : 답변이 붙인 인용 vs 골든 근거 문서
#       Agent        : Phase 7 에이전트의 tool-call 로그 vs 정답 도구 순서
#   - 여기서는 개념을 손에 익히려고 아주 작은 모형 데이터를 손으로 적어 둔다.
#     Golden Testset 을 LLM 으로 생성하는 방법은 토픽 02(Ragas)에서 다룬다.


# --- Construction: Phase 2 그래프 구축 산출물의 축소판 ---------------------

# 허용 라벨(스키마)과 라벨별 필수 속성. Phase 5 Semantic Layer 에서 확정된다고 가정.
ALLOWED_LABELS = {"Paper", "Method", "Dataset"}
REQUIRED_PROPS = {
    "Paper": {"title", "arxiv_id"},
    "Method": {"name"},
    "Dataset": {"name"},
}

NODES = [
    {"id": "p1", "label": "Paper", "props": {"title": "LightRAG", "arxiv_id": "2410.05779"}},
    {"id": "p2", "label": "Paper", "props": {"title": "GraphRAG Survey"}},   # arxiv_id 누락 → 스키마 위반
    {"id": "m1", "label": "Method", "props": {"name": "hybrid retrieval"}},
    {"id": "m2", "label": "Method", "props": {"name": "community detection"}},
    {"id": "d1", "label": "Dataset", "props": {"name": "arXiv corpus"}},
    {"id": "x1", "label": "Concept", "props": {"name": "multi-hop"}},        # 허용 안 된 라벨 → 위반
]

# 엔티티 해소 후 정규화 키. "lightrag" 가 두 번 → 중복 1건.
NODE_CANONICAL_KEYS = [
    "paper:lightrag",
    "paper:graphrag-survey",
    "method:hybrid-retrieval",
    "method:community-detection",
    "dataset:arxiv-corpus",
    "paper:lightrag",   # 중복(엔티티 해소 미완)
]

NODE_IDS = ["p1", "p2", "m1", "m2", "d1", "x1"]
# (source, target) 엣지. x1 은 어떤 엣지에도 없음 → 고아 노드.
EDGES = [
    ("p1", "m1"),
    ("p1", "d1"),
    ("p2", "m2"),
    ("m1", "d1"),
]


# --- Retrieval: Phase 4 GraphRAG 검색 결과 vs Golden 근거 -------------------
# 질문 3개. 각 질문마다 검색된 근거 chunk id 목록(랭킹순)과 정답(relevant) 근거.
RETRIEVAL_CASES = [
    {
        "question": "LightRAG 의 hybrid 모드는 무엇을 결합하나?",
        "retrieved": ["c1", "c3", "c7", "c9"],   # 랭킹순
        "relevant": ["c1", "c3"],
    },
    {
        "question": "커뮤니티 요약은 어느 논문에서 왔나? (멀티홉)",
        "retrieved": ["c5", "c2", "c8"],
        "relevant": ["c2", "c4"],                 # c4 는 못 가져옴 → recall 손실
    },
    {
        "question": "arXiv 코퍼스 규모는?",
        "retrieved": ["c6", "c1"],
        "relevant": ["c6"],
    },
]
HIT_AT_K = 3   # hit@k 의 k


# --- Generation: 답변 인용 vs 골든 근거 ------------------------------------
GENERATION_CASES = [
    {
        # 답변이 c1,c3 을 인용했고 둘 다 진짜 근거 → 완벽
        "cited": ["c1", "c3"],
        "gold_support": ["c1", "c3"],
    },
    {
        # 답변이 c2 는 맞게 인용했지만 c99 는 헛인용(hallucinated), c4 는 빠뜨림
        "cited": ["c2", "c99"],
        "gold_support": ["c2", "c4"],
    },
]


# --- Agent: tool-call 로그 vs 정답 도구 순서 -------------------------------
AGENT_CASES = [
    {
        # 라우팅·도구 선택 정확
        "predicted_tools": ["docs_search", "graph_query", "answer"],
        "gold_tools": ["docs_search", "graph_query", "answer"],
    },
    {
        # 2번째 스텝에서 graph_query 대신 docs_search 오출 + 마지막 스텝 누락
        "predicted_tools": ["docs_search", "docs_search"],
        "gold_tools": ["docs_search", "graph_query", "answer"],
    },
]
# 태스크별 최종 성공 여부(정답과 일치했는지)
AGENT_TASK_RESULTS = [True, False]
