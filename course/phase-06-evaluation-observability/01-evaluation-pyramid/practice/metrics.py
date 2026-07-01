# metrics.py — 평가 피라미드 4계층 지표 함수 (순수 파이썬, 표준 라이브러리만)
#
# 전제:
#   - 외부 의존 없음. Python 3.11+ 표준 라이브러리만 사용한다.
#   - 여기서는 Ragas·Langfuse 같은 LLM 기반 평가 도구를 쓰지 않는다.
#     지표의 "형태와 의미"를 먼저 손으로 계산해 감을 잡는 것이 목적이다.
#     LLM 기반 recall/faithfulness 대체는 토픽 02(Ragas)에서 다룬다.
#
# 4계층:
#   Construction  → 그래프 구축 품질 (스키마 준수율, 중복률, 고아 노드 비율)
#   Retrieval     → 검색 품질 (context recall / precision, hit@k)
#   Generation    → 생성 품질 (인용 정확도 = citation precision/recall)
#   Agent         → 에이전트 품질 (tool-call accuracy, task success rate)
#
# 모든 지표는 0.0~1.0 사이 실수를 돌려준다. 분모가 0이면 0.0으로 처리한다.

from __future__ import annotations

from typing import Iterable, Sequence


def _safe_div(numerator: float, denominator: float) -> float:
    """분모 0을 0.0으로 처리하는 나눗셈."""
    if denominator == 0:
        return 0.0
    return numerator / denominator


# ---------------------------------------------------------------------------
# 1) Construction — 그래프 구축 품질
# ---------------------------------------------------------------------------

def schema_conformance(nodes: Sequence[dict], allowed_labels: set[str],
                       required_props: dict[str, set[str]]) -> float:
    """스키마 준수율.

    노드 하나가 '준수'로 세어지려면:
      - label 이 allowed_labels 안에 있어야 하고
      - 그 label 이 요구하는 필수 속성(required_props)을 모두 가져야 한다.
    반환값 = 준수 노드 수 / 전체 노드 수.
    """
    if not nodes:
        return 0.0
    ok = 0
    for n in nodes:
        label = n.get("label")
        if label not in allowed_labels:
            continue
        needed = required_props.get(label, set())
        props = set(n.get("props", {}).keys())
        if needed.issubset(props):
            ok += 1
    return _safe_div(ok, len(nodes))


def duplicate_rate(node_keys: Sequence[str]) -> float:
    """중복률 = (전체 - 유니크) / 전체.

    node_keys 는 엔티티 해소 후 각 노드의 정규화 키(canonical key)라고 가정한다.
    같은 키가 두 번 이상 나오면 엔티티 해소가 덜 된 중복 노드다.
    """
    if not node_keys:
        return 0.0
    unique = len(set(node_keys))
    return _safe_div(len(node_keys) - unique, len(node_keys))


def orphan_rate(node_ids: Sequence[str],
                edges: Sequence[tuple[str, str]]) -> float:
    """고아 노드 비율 = 어떤 엣지에도 안 걸린 노드 수 / 전체 노드 수.

    edges 는 (source_id, target_id) 튜플의 목록.
    고아 노드가 많으면 관계 추출이 빈약하다는 신호다(멀티홉이 막힌다).
    """
    if not node_ids:
        return 0.0
    connected: set[str] = set()
    for src, dst in edges:
        connected.add(src)
        connected.add(dst)
    orphans = sum(1 for nid in node_ids if nid not in connected)
    return _safe_div(orphans, len(node_ids))


# ---------------------------------------------------------------------------
# 2) Retrieval — 검색 품질
# ---------------------------------------------------------------------------

def context_recall(retrieved: Iterable[str], relevant: Iterable[str]) -> float:
    """context recall = (검색된 것 중 정답인 것) / (전체 정답).

    '정답을 얼마나 놓치지 않고 가져왔나'. 재현율이 낮으면 근거 자체가 없어
    아래 Generation 층에서 아무리 잘 써도 답이 틀린다.
    """
    relevant_set = set(relevant)
    if not relevant_set:
        return 0.0
    hit = sum(1 for r in set(retrieved) if r in relevant_set)
    return _safe_div(hit, len(relevant_set))


def context_precision(retrieved: Iterable[str], relevant: Iterable[str]) -> float:
    """context precision = (검색된 것 중 정답인 것) / (검색된 전체).

    '가져온 근거가 얼마나 알짜였나'. 정밀도가 낮으면 노이즈가 많아
    LLM 이 엉뚱한 문맥에 휘둘린다.
    """
    retrieved_set = set(retrieved)
    if not retrieved_set:
        return 0.0
    relevant_set = set(relevant)
    hit = sum(1 for r in retrieved_set if r in relevant_set)
    return _safe_div(hit, len(retrieved_set))


def hit_at_k(ranked: Sequence[str], relevant: Iterable[str], k: int) -> float:
    """hit@k = 상위 k개 안에 정답이 하나라도 있으면 1.0, 없으면 0.0.

    ranked 는 점수 내림차순으로 정렬된 검색 결과 id 목록.
    질문 하나에 대한 값이며, 여러 질문의 평균이 최종 hit@k 가 된다.
    """
    top_k = set(ranked[:k])
    relevant_set = set(relevant)
    return 1.0 if top_k & relevant_set else 0.0


# ---------------------------------------------------------------------------
# 3) Generation — 생성 품질 (여기서는 인용 정확도만 손으로 계산)
# ---------------------------------------------------------------------------

def citation_accuracy(cited: Iterable[str], gold_support: Iterable[str]) -> dict[str, float]:
    """인용 정확도 = 답변이 실제로 쓴 인용(cited)이 근거 문서(gold_support)와 얼마나 맞나.

    precision: 답변이 붙인 인용 중 진짜 근거였던 비율 (헛인용/hallucinated citation 탐지)
    recall:    진짜 근거 중 답변이 실제로 인용한 비율 (근거 누락 탐지)
    f1:        둘의 조화평균

    faithfulness(근거 충실도)·answer relevancy 는 LLM 판단이 필요해 여기서 계산하지 않는다.
    → 상세는 토픽 02(Ragas).
    """
    cited_set = set(cited)
    gold_set = set(gold_support)
    tp = len(cited_set & gold_set)
    precision = _safe_div(tp, len(cited_set))
    recall = _safe_div(tp, len(gold_set))
    f1 = _safe_div(2 * precision * recall, precision + recall)
    return {"precision": precision, "recall": recall, "f1": f1}


# ---------------------------------------------------------------------------
# 4) Agent — 에이전트 품질
# ---------------------------------------------------------------------------

def tool_call_accuracy(predicted_tools: Sequence[str],
                       gold_tools: Sequence[str]) -> float:
    """tool-call accuracy = 스텝별로 올바른 도구를 부른 비율.

    두 목록을 스텝 순서대로 짝지어 비교한다. 길이가 다르면 긴 쪽 기준으로
    나눠, 도구를 덜 부르거나 더 부른 것도 감점되게 한다.
    (라우팅 정확도도 같은 방식으로 계산할 수 있다: 도구 대신 라우트 라벨을 넣으면 된다.)
    """
    steps = max(len(predicted_tools), len(gold_tools))
    if steps == 0:
        return 0.0
    correct = sum(
        1 for p, g in zip(predicted_tools, gold_tools) if p == g
    )
    return _safe_div(correct, steps)


def task_success_rate(results: Sequence[bool]) -> float:
    """태스크 성공률 = 성공한 태스크 수 / 전체 태스크 수.

    results 는 태스크별 성공(True)/실패(False) 목록.
    스텝 수·비용·지연은 Langfuse 트레이스에서 관측한다 → 상세는 토픽 03.
    """
    if not results:
        return 0.0
    return _safe_div(sum(1 for r in results if r), len(results))
