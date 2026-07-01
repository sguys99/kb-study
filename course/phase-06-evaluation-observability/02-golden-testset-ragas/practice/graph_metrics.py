# graph_metrics.py — 그래프 특화 커스텀 지표 (순수 파이썬, 표준 라이브러리만)
#
# 왜 필요한가:
#   Ragas 의 기본 지표(faithfulness / answer_relevancy / context_precision /
#   context_recall)는 "텍스트 컨텍스트" 관점의 RAG 를 잰다. GraphRAG 가 진짜
#   그래프를 밟았는지 — 정답이 요구하는 홉 수를 실제로 이동했는지, 근거가
#   그래프 엣지로 연결됐는지, 정답 엔티티를 실제로 건드렸는지 — 는 못 잡는다.
#   그래서 그래프 특화 지표는 순수 파이썬 커스텀으로 잰다.
#   (토픽 01 metrics.py 의 Retrieval 지표를 그래프 축으로 확장하는 셈이다.)
#
# 전제:
#   - 외부 의존 없음. Python 3.11+ 표준 라이브러리만.
#   - 입력은 앞 Phase 산출물의 축소판이다:
#       * 정답이 요구하는 홉 수(hops) : golden set 에 사람이 라벨링
#       * 실제 밟은 경로(traversed edges) : Phase 4 GraphRAG(LightRAG) 검색 로그
#       * 정답 엔티티(gold_entities)  : golden set 라벨
#       * 검색이 건드린 엔티티/엣지    : GraphRAG 검색 로그
#   - 모든 지표는 0.0~1.0 실수. 분모 0 이면 0.0.

from __future__ import annotations

from typing import Iterable, Sequence


def _safe_div(numerator: float, denominator: float) -> float:
    """분모 0을 0.0으로 처리하는 나눗셈."""
    if denominator == 0:
        return 0.0
    return numerator / denominator


# ---------------------------------------------------------------------------
# 1) 멀티홉 경로 적중률 — 정답이 요구하는 홉 수를 실제로 밟았는가
# ---------------------------------------------------------------------------

def multihop_path_hit(required_hops: int, traversed_edges: Sequence[tuple]) -> float:
    """멀티홉 경로 적중.

    required_hops : 이 질문이 정답에 닿으려면 몇 홉을 이동해야 하는가(golden 라벨).
    traversed_edges : GraphRAG 검색이 실제로 밟은 (source, target) 엣지 목록.

    실제 밟은 홉 수 = len(traversed_edges). 요구 홉을 채웠으면 1.0.
    2홉이 필요한데 1홉만 밟았다면 부분 점수(1/2)를 준다.
    벡터-only RAG 는 엣지를 안 밟으니 멀티홉에서 0.0 이 나온다 — 이게 핵심 대비점.
    """
    if required_hops <= 0:
        return 1.0  # 홉이 필요 없는(single-fact) 질문은 통과 처리
    walked = len(traversed_edges)
    return min(1.0, _safe_div(walked, required_hops))


# ---------------------------------------------------------------------------
# 2) 그래프 근거 커버리지 — 정답 근거가 그래프 엣지/노드로 연결됐는가
# ---------------------------------------------------------------------------

def graph_grounding_coverage(reference_contexts: Iterable[str],
                             graph_connected_contexts: Iterable[str]) -> float:
    """그래프 근거 커버리지.

    reference_contexts : 정답이 필요로 하는 근거 chunk/노드 id(golden 라벨).
    graph_connected_contexts : 그중 실제로 그래프 상에서 서로 엣지로 연결돼
        하나의 서브그래프로 묶인 근거 id 목록.

    = 그래프로 연결된 근거 수 / 전체 정답 근거 수.
    근거들이 텍스트로만 검색되고 그래프상 이어지지 않으면 이 값이 떨어진다.
    멀티홉 답변의 '설명 가능성'을 보는 지표다.
    """
    ref = set(reference_contexts)
    if not ref:
        return 0.0
    connected = set(graph_connected_contexts) & ref
    return _safe_div(len(connected), len(ref))


# ---------------------------------------------------------------------------
# 3) 엔티티 커버리지 — 정답 엔티티를 실제로 건드렸는가
# ---------------------------------------------------------------------------

def entity_coverage(gold_entities: Iterable[str],
                    retrieved_entities: Iterable[str]) -> float:
    """엔티티 커버리지 = (검색이 건드린 정답 엔티티) / (전체 정답 엔티티).

    표기 흔들림(대소문자·공백)을 흡수하려고 소문자·strip 로 정규화해 비교한다.
    엔티티 해소(Phase 2)가 잘 됐다면 이 값이 높다. 낮으면 정답 엔티티를
    아예 못 찾았거나 표기가 어긋나 매칭이 실패한 것이다.
    """
    def norm(xs: Iterable[str]) -> set[str]:
        return {x.strip().lower() for x in xs}

    gold = norm(gold_entities)
    if not gold:
        return 0.0
    hit = gold & norm(retrieved_entities)
    return _safe_div(len(hit), len(gold))


# ---------------------------------------------------------------------------
# 케이스 묶음 계산 헬퍼 — golden set + 검색 로그를 받아 케이스별/평균 점수
# ---------------------------------------------------------------------------

def score_graph_case(case: dict) -> dict[str, float]:
    """그래프 케이스 하나(golden 라벨 + 검색 로그)를 받아 3지표를 계산한다.

    case 스키마(dict):
      required_hops           : int
      traversed_edges         : list[tuple]  (검색이 밟은 엣지)
      reference_contexts      : list[str]    (정답 근거)
      graph_connected_contexts: list[str]    (그래프로 이어진 근거)
      gold_entities           : list[str]
      retrieved_entities      : list[str]
    """
    return {
        "multihop_path_hit": multihop_path_hit(
            case["required_hops"], case["traversed_edges"]
        ),
        "graph_grounding_coverage": graph_grounding_coverage(
            case["reference_contexts"], case["graph_connected_contexts"]
        ),
        "entity_coverage": entity_coverage(
            case["gold_entities"], case["retrieved_entities"]
        ),
    }


def score_graph_cases(cases: Sequence[dict]) -> dict[str, float]:
    """여러 케이스의 평균 그래프 특화 점수."""
    if not cases:
        return {"multihop_path_hit": 0.0,
                "graph_grounding_coverage": 0.0,
                "entity_coverage": 0.0}
    keys = ("multihop_path_hit", "graph_grounding_coverage", "entity_coverage")
    totals = {k: 0.0 for k in keys}
    for c in cases:
        s = score_graph_case(c)
        for k in keys:
            totals[k] += s[k]
    n = len(cases)
    return {k: totals[k] / n for k in keys}


if __name__ == "__main__":
    # 작은 데모: vector-only(엣지 0) vs GraphRAG(엣지 밟음) 대비
    demo_cases = [
        {   # 2홉 멀티홉 — GraphRAG 가 2엣지를 밟고 근거를 잇는다
            "required_hops": 2,
            "traversed_edges": [("From Local to Global", "Leiden"),
                                ("From Local to Global", "community summary")],
            "reference_contexts": ["c2", "c4"],
            "graph_connected_contexts": ["c2", "c4"],
            "gold_entities": ["community summary", "From Local to Global", "Leiden"],
            "retrieved_entities": ["community summary", "from local to global", "leiden"],
        },
        {   # 같은 질문을 vector-only 로 풀면: 엣지 0, 근거는 텍스트로만
            "required_hops": 2,
            "traversed_edges": [],
            "reference_contexts": ["c2", "c4"],
            "graph_connected_contexts": [],       # 그래프로 안 이어짐
            "gold_entities": ["community summary", "From Local to Global", "Leiden"],
            "retrieved_entities": ["community summary"],
        },
    ]
    print("GraphRAG 케이스 :", score_graph_case(demo_cases[0]))
    print("vector-only 케이스:", score_graph_case(demo_cases[1]))
    print("평균           :", score_graph_cases(demo_cases))
