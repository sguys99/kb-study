"""4.4 fuse.py — 스케일이 다른 Vector·Graph 점수를 하나의 척도로 합친다.

문제: vector 점수는 코사인 유사도 0~1, graph 점수는 출처마다 다르다
      (path=홉 수 3.0, community=관련도 8.0 ...). 그대로 더하면 큰 숫자가 이긴다.
      community 후보(8.0)가 vector 후보(0.83)를 항상 짓밟는다. 이건 융합이 아니다.

두 갈래 해법을 둔다.
  1) 점수 정규화(min-max / z-score) — 출처 안에서 0~1 로 줄 세운 뒤 가중합.
     스케일은 맞춰지지만 가중치(alpha)를 손으로 정해야 하고 분포에 민감하다.
  2) RRF(Reciprocal Rank Fusion) — 점수의 '값'이 아니라 '순위'만 본다.
     score 가 아니라 rank 로 합치니 스케일이 무엇이든 상관없다. 실무에서 선호된다.
     공식: RRF(d) = Σ_사용처 1 / (k + rank_사용처(d)),  k 는 보통 60.

이 모듈은 외부 의존이 없다(표준 라이브러리만).

전제: 없음(키 불필요, 과금 0).
실행:
    python fuse.py                 # RRF 융합. 융합 전(출처별 순위)/후 순위를 비교 출력
    python fuse.py --minmax        # min-max 정규화 가중합으로 융합(비교용)
"""

from __future__ import annotations

import sys

from candidates import Candidate, load_pool

# RRF 의 평활 상수. 작을수록 상위 순위에 가중이 쏠린다. 60 은 원논문/실무 관례값.
RRF_K = 60


def _rank_within_source(pool: list[Candidate], source: str) -> dict[str, int]:
    """한 출처(source) 안에서 점수 내림차순 순위를 매긴다(1등=1).

    RRF 는 출처별 '순위'를 입력으로 받으므로, 출처마다 따로 줄을 세운다.
    """
    items = sorted([c for c in pool if c.source == source],
                   key=lambda c: c.score, reverse=True)
    return {c.id: i + 1 for i, c in enumerate(items)}


def fuse_rrf(pool: list[Candidate], k: int = RRF_K) -> list[tuple[Candidate, float]]:
    """RRF 로 Vector·Graph 후보를 하나의 순위로 합친다.

    같은 id 가 두 출처에 다 있으면 두 기여가 더해진다(=양쪽에서 다 잡힌 후보가 강해진다).
    샘플은 id 가 안 겹치지만, 실전에서는 겹칠 수 있어 id 기준으로 합산한다.
    """
    ranks = {src: _rank_within_source(pool, src) for src in ("vector", "graph")}
    by_id: dict[str, Candidate] = {c.id: c for c in pool}

    fused: dict[str, float] = {}
    for src, rank_map in ranks.items():
        for cid, r in rank_map.items():
            fused[cid] = fused.get(cid, 0.0) + 1.0 / (k + r)

    out = [(by_id[cid], s) for cid, s in fused.items()]
    out.sort(key=lambda t: t[1], reverse=True)
    return out


def _minmax(values: list[float]) -> list[float]:
    """0~1 로 줄인다. 모든 값이 같으면 0.5 로 둔다(0 나눗셈 방지)."""
    lo, hi = min(values), max(values)
    if hi == lo:
        return [0.5 for _ in values]
    return [(v - lo) / (hi - lo) for v in values]


def fuse_minmax(pool: list[Candidate], alpha: float = 0.5) -> list[tuple[Candidate, float]]:
    """min-max 정규화 후 가중합. alpha 는 vector 가중치(1-alpha 가 graph).

    RRF 와 비교용으로 둔다. 가중치를 손으로 정해야 하는 부담이 RRF 와의 차이.
    """
    fused: dict[str, float] = {}
    by_id: dict[str, Candidate] = {c.id: c for c in pool}
    for src, w in (("vector", alpha), ("graph", 1 - alpha)):
        items = [c for c in pool if c.source == src]
        if not items:
            continue
        norm = _minmax([c.score for c in items])
        for c, n in zip(items, norm):
            fused[c.id] = fused.get(c.id, 0.0) + w * n
    out = [(by_id[cid], s) for cid, s in fused.items()]
    out.sort(key=lambda t: t[1], reverse=True)
    return out


def _print_pre_fusion(pool: list[Candidate]) -> None:
    """융합 전 — 출처별로 따로 세운 순위(Vector-only / Graph-only)를 보여준다."""
    for src in ("vector", "graph"):
        items = sorted([c for c in pool if c.source == src],
                       key=lambda c: c.score, reverse=True)
        print(f"[융합 전 · {src}-only 순위]")
        for i, c in enumerate(items, 1):
            print(f"  {i}. {c.id} (score={c.score:.2f}) {c.short(50)}")
        print()


def main(argv: list[str]) -> None:
    use_minmax = "--minmax" in argv
    _question, pool = load_pool()

    _print_pre_fusion(pool)

    if use_minmax:
        fused = fuse_minmax(pool)
        title = "융합 후 · min-max 가중합(alpha=0.5)"
    else:
        fused = fuse_rrf(pool)
        title = f"융합 후 · RRF(k={RRF_K})"

    print(f"[{title}] 한 줄로 합쳐진 순위:")
    for i, (c, s) in enumerate(fused, 1):
        print(f"  {i:>2}. {c.id} [{c.source:>6}] fused={s:.4f}  {c.short(48)}")
    print("\n[다음] python rerank.py 로 융합 상위 후보를 질문-문서 쌍으로 다시 점수 매긴다.")


if __name__ == "__main__":
    main(sys.argv)
