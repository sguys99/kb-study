"""4.5 metrics.py — 검색 품질 지표를 표준 라이브러리만으로 계산한다.

A/B 의 핵심 질문은 하나다. "정답 근거(gold)가 상위 k 안에 들어왔나?"
좋아 보인다가 아니라 숫자로 답해야 모드 간 우열이 갈린다.

세 지표:
  - recall_at_k : gold 중 상위 k 안에 잡힌 비율. '정답 근거 포함률'의 핵심 지표.
  - mrr         : 첫 gold 가 나온 순위의 역수(1/rank). 정답을 얼마나 위로 올렸나.
  - hit_rate    : gold 가 상위 k 안에 하나라도 있으면 1, 없으면 0. "맞췄나/놓쳤나".

모두 ranked(전략이 돌려준 Candidate 리스트)와 gold(정답 id 집합)만 받는다.
질문 type 별로 분리 집계할 수 있게 per-type 평균 헬퍼도 둔다.

전제: 없음(키 불필요, 과금 0).
실행:
    python metrics.py            # 작은 자체 예시로 세 지표를 시연
"""

from __future__ import annotations

from typing import Sequence


def _ids(ranked: Sequence) -> list[str]:
    """ranked 가 Candidate 리스트든 id 리스트든 id 순서 리스트로 정규화한다."""
    out = []
    for r in ranked:
        out.append(r if isinstance(r, str) else r.id)
    return out


def recall_at_k(ranked: Sequence, gold: set[str], k: int = 3) -> float:
    """상위 k 안에 잡힌 gold 비율. gold 가 비면 0.0.

    예: gold={a,b}, 상위 3 안에 a 만 있으면 0.5.
    """
    if not gold:
        return 0.0
    topk = set(_ids(ranked)[:k])
    return len(topk & gold) / len(gold)


def mrr(ranked: Sequence, gold: set[str]) -> float:
    """첫 gold 의 순위 역수(Mean Reciprocal Rank 의 단건). 못 찾으면 0.0.

    gold 가 2등에 처음 나오면 1/2=0.5. 위로 올릴수록 1 에 가까워진다.
    """
    for i, cid in enumerate(_ids(ranked), 1):
        if cid in gold:
            return 1.0 / i
    return 0.0


def hit_rate(ranked: Sequence, gold: set[str], k: int = 3) -> float:
    """상위 k 안에 gold 가 하나라도 있으면 1.0, 없으면 0.0."""
    if not gold:
        return 0.0
    topk = set(_ids(ranked)[:k])
    return 1.0 if topk & gold else 0.0


def evaluate_one(ranked: Sequence, gold: set[str], k: int = 3) -> dict:
    """한 질문에 대한 세 지표를 한 번에."""
    return {
        "recall@k": recall_at_k(ranked, gold, k),
        "mrr": mrr(ranked, gold),
        "hit_rate": hit_rate(ranked, gold, k),
    }


def mean(values: list[float]) -> float:
    """빈 리스트면 0.0(표준 라이브러리만 쓰려고 statistics 대신 직접)."""
    return sum(values) / len(values) if values else 0.0


def aggregate(rows: list[dict], key: str) -> float:
    """rows 에서 지표 하나(key)의 평균."""
    return mean([r[key] for r in rows])


def _demo() -> None:
    # Candidate 없이 id 리스트만으로도 동작하는지 보여주는 자체 예시.
    ranked = ["g1", "v2", "g3", "v1"]   # 전략이 돌려준 순서(상위부터)
    gold = {"g1", "v1"}                 # 정답 근거 2개
    print(f"[예시] ranked={ranked}, gold={sorted(gold)}, k=3")
    print(f"  recall@3 = {recall_at_k(ranked, gold, 3):.3f}   "
          f"(상위3 {ranked[:3]} 안 gold 1/2)")
    print(f"  mrr      = {mrr(ranked, gold):.3f}   (첫 gold g1 이 1등 → 1/1)")
    print(f"  hit@3    = {hit_rate(ranked, gold, 3):.3f}   (상위3 안에 gold 있음)")
    print("\n[다음] python ab_runner.py 로 전체 골든셋 × 네 전략에 이 지표를 적용한다.")


if __name__ == "__main__":
    _demo()
