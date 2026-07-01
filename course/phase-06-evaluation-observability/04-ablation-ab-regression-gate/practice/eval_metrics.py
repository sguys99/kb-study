# eval_metrics.py — 01/02 의 순수 파이썬 지표를 이 토픽에서 재사용하기 위한 얇은 재정의
#
# 왜 이렇게 하나:
#   Ablation·A/B·Regression Gate 는 "지표 함수" 자체를 새로 만드는 토픽이 아니다.
#   01(metrics.py) 의 4계층 지표와 02(graph_metrics.py) 의 그래프 특화 지표를
#   그대로 굴려 "구성(configuration)이 바뀌면 점수가 어떻게 움직이나"만 본다.
#
#   원칙대로면 01/02 의 파일을 import 해야 한다. 하지만 이 실습 폴더 하나만 받아도
#   상용 API 없이 바로 돌아가게 하려고, 필요한 함수만 여기 축약 재정의해 둔다.
#   (실전에서는 아래 주석의 import 경로로 바꿔 쓰면 된다.)
#
#   # from ...01_evaluation_pyramid.practice import metrics as M          # 01 재사용
#   # from ...02_golden_testset_ragas.practice import graph_metrics as G  # 02 재사용
#
# 전제:
#   - 외부 의존 없음. Python 3.11+ 표준 라이브러리만.
#   - 모든 지표는 0.0~1.0 실수. 분모 0 이면 0.0.

from __future__ import annotations

from typing import Iterable, Sequence


def _safe_div(numerator: float, denominator: float) -> float:
    """분모 0을 0.0으로 처리하는 나눗셈."""
    if denominator == 0:
        return 0.0
    return numerator / denominator


# --- 01 metrics.py 에서: Retrieval / Generation 지표 -----------------------

def context_recall(retrieved: Iterable[str], relevant: Iterable[str]) -> float:
    """context recall = (검색된 것 중 정답) / (전체 정답). 놓친 근거를 잡는다."""
    relevant_set = set(relevant)
    if not relevant_set:
        return 0.0
    hit = sum(1 for r in set(retrieved) if r in relevant_set)
    return _safe_div(hit, len(relevant_set))


def context_precision(retrieved: Iterable[str], relevant: Iterable[str]) -> float:
    """context precision = (검색된 것 중 정답) / (검색된 전체). 노이즈를 잡는다."""
    retrieved_set = set(retrieved)
    if not retrieved_set:
        return 0.0
    relevant_set = set(relevant)
    hit = sum(1 for r in retrieved_set if r in relevant_set)
    return _safe_div(hit, len(retrieved_set))


def citation_f1(cited: Iterable[str], gold_support: Iterable[str]) -> float:
    """인용 정확도 F1 = 답변 인용(cited)과 골든 근거(gold_support)의 조화평균."""
    cited_set = set(cited)
    gold_set = set(gold_support)
    tp = len(cited_set & gold_set)
    precision = _safe_div(tp, len(cited_set))
    recall = _safe_div(tp, len(gold_set))
    return _safe_div(2 * precision * recall, precision + recall)


# --- 02 graph_metrics.py 에서: 그래프 특화 지표 ----------------------------

def multihop_path_hit(required_hops: int, traversed_edges: Sequence[tuple]) -> float:
    """멀티홉 경로 적중. 벡터-only 는 엣지를 안 밟으니 0.0 이 나온다 — 핵심 대비점."""
    if required_hops <= 0:
        return 1.0
    walked = len(traversed_edges)
    return min(1.0, _safe_div(walked, required_hops))


def entity_coverage(gold_entities: Iterable[str],
                    retrieved_entities: Iterable[str]) -> float:
    """엔티티 커버리지 = (건드린 정답 엔티티) / (전체 정답 엔티티). 표기는 정규화 후 비교."""
    def norm(xs: Iterable[str]) -> set[str]:
        return {x.strip().lower() for x in xs}

    gold = norm(gold_entities)
    if not gold:
        return 0.0
    hit = gold & norm(retrieved_entities)
    return _safe_div(len(hit), len(gold))
