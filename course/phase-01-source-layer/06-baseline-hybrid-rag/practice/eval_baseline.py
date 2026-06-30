"""eval_baseline.py — Golden Question 10개로 기준선 점수를 측정·영속화한다.

이 점수가 Phase 4 GraphRAG 와의 A/B 기준선이다. 그래서 안정 스키마로 저장한다.

측정 지표(검색 품질):
  - Hit@k   : 상위 k 안에 정답 문서가 하나라도 있으면 1. 질문 평균.
  - MRR     : 첫 정답 문서의 역순위 평균(1/rank). 정답이 얼마나 위에 오나.
  - Recall@k: 기대 문서들 중 상위 k 안에서 회수된 비율. 멀티홉에서 특히 중요하다.
  - 인용 정확도(citation precision): 답변이 단 인용 중 기대 문서 소속 비율.

채점 단위: 검색 결과 chunk_id → source_id 로 환원해 '문서 단위'로 맞춘다
  (golden 의 expected_source_ids 가 문서 단위라서).

출력: 표 + out/baseline_scores.json.
  baseline_scores.json 스키마(Phase 4 가 다시 읽는다):
    {
      "meta":    {embed_backend, llm_backend, k, n_questions, generated_at},
      "metrics": {hit_at_k, mrr, recall_at_k, citation_precision,
                  single_hop:{...}, multi_hop:{...}},
      "per_question": [{id, type, expected_source_ids, retrieved_source_ids,
                        hit, first_rank, recall, citation_precision}, ...]
    }

멀티홉 점수가 single-hop 보다 낮게 나오는 게 정상이다 — 그게 Phase 4 의 동기다.

전제: 검색 백엔드(voyage/hash)·답변 백엔드(claude/extractive)는 키 유무로 자동 결정.
의존: pyyaml. (검색·답변 모듈은 numpy·rank-bm25 사용.)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import yaml

from load_chunks import OUT_DIR, load_chunks, load_index
from hybrid_search import HybridSearcher
from answer_with_citations import answer_with_citations

HERE = Path(__file__).resolve().parent
GOLDEN_PATH = HERE / "golden_questions.yaml"
SCORES_PATH = OUT_DIR / "baseline_scores.json"

K = 5  # 검색 top-k. 기준선 평가의 k.


def load_golden() -> list[dict]:
    data = yaml.safe_load(GOLDEN_PATH.read_text(encoding="utf-8"))
    return data["questions"]


def _source_ranks(retrieved_ids: list[str], cmap: dict) -> list[str]:
    """검색된 chunk_id 순위를 source_id 순위로 환원한다(중복 source 는 첫 등장만)."""
    seen: list[str] = []
    for cid in retrieved_ids:
        sid = cmap[cid].source_id
        if sid not in seen:
            seen.append(sid)
    return seen


def evaluate() -> dict:
    chunks = load_chunks()
    index = load_index()
    hs = HybridSearcher(chunks, index)
    cmap = hs.cmap
    golden = load_golden()

    per_q: list[dict] = []
    for q in golden:
        expected = set(q["expected_source_ids"])
        results = hs.search(q["question"], k=K)
        retrieved_cids = [cid for cid, _ in results]
        retrieved_sids = _source_ranks(retrieved_cids, cmap)

        # Hit@k & 첫 정답 순위(MRR 재료).
        first_rank = 0
        for rank, sid in enumerate(retrieved_sids, start=1):
            if sid in expected:
                first_rank = rank
                break
        hit = 1 if first_rank > 0 else 0

        # Recall@k: 기대 문서 중 상위 k(=source 환원 후)에 든 비율.
        recovered = expected.intersection(retrieved_sids)
        recall = len(recovered) / len(expected) if expected else 0.0

        # 인용 정확도: 답변이 단 인용 중 기대 문서 소속 비율.
        ctx = [cmap[cid] for cid in retrieved_cids]
        ans = answer_with_citations(q["question"], ctx)
        cited_sids = [c.source_id for c in ans.citations]
        cite_hit = sum(1 for s in cited_sids if s in expected)
        citation_precision = cite_hit / len(cited_sids) if cited_sids else 0.0

        per_q.append({
            "id": q["id"],
            "type": q["type"],
            "expected_source_ids": sorted(expected),
            "retrieved_source_ids": retrieved_sids,
            "hit": hit,
            "first_rank": first_rank,
            "recall": round(recall, 4),
            "citation_precision": round(citation_precision, 4),
        })

    llm_backend = ans.backend if golden else "none"  # 마지막 답변의 백엔드(전부 동일).
    return _aggregate(per_q, embed_backend=hs.embed_backend, llm_backend=llm_backend)


def _avg(rows: list[dict], key: str) -> float:
    return round(sum(r[key] for r in rows) / len(rows), 4) if rows else 0.0


def _subset_metrics(rows: list[dict]) -> dict:
    return {
        "n": len(rows),
        "hit_at_k": _avg(rows, "hit"),
        "mrr": round(sum((1.0 / r["first_rank"]) if r["first_rank"] else 0.0 for r in rows) / len(rows), 4) if rows else 0.0,
        "recall_at_k": _avg(rows, "recall"),
        "citation_precision": _avg(rows, "citation_precision"),
    }


def _aggregate(per_q: list[dict], *, embed_backend: str, llm_backend: str) -> dict:
    single = [r for r in per_q if r["type"] == "single-hop"]
    multi = [r for r in per_q if r["type"] == "multi-hop"]
    metrics = _subset_metrics(per_q)
    metrics["single_hop"] = _subset_metrics(single)
    metrics["multi_hop"] = _subset_metrics(multi)
    return {
        "meta": {
            "embed_backend": embed_backend,
            "llm_backend": llm_backend,
            "k": K,
            "n_questions": len(per_q),
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        },
        "metrics": metrics,
        "per_question": per_q,
    }


def print_report(scores: dict) -> None:
    m = scores["metrics"]
    meta = scores["meta"]
    print(f"[기준선] embed={meta['embed_backend']}  llm={meta['llm_backend']}  k={meta['k']}  질문={meta['n_questions']}\n")
    print(f"  {'구간':10s} {'n':>3s} {'Hit@k':>7s} {'MRR':>7s} {'Recall@k':>9s} {'인용정확도':>9s}")
    print(f"  {'-'*10} {'-'*3} {'-'*7} {'-'*7} {'-'*9} {'-'*9}")
    for label, key in [("전체", None), ("single-hop", "single_hop"), ("multi-hop", "multi_hop")]:
        d = m if key is None else m[key]
        print(f"  {label:10s} {d['n']:>3d} {d['hit_at_k']:>7.3f} {d['mrr']:>7.3f} {d['recall_at_k']:>9.3f} {d['citation_precision']:>9.3f}")

    print("\n  질문별:")
    print(f"    {'id':5s} {'type':10s} {'hit':>3s} {'rank':>4s} {'recall':>6s}  retrieved")
    for r in scores["per_question"]:
        print(f"    {r['id']:5s} {r['type']:10s} {r['hit']:>3d} {r['first_rank']:>4d} {r['recall']:>6.2f}  {r['retrieved_source_ids'][:3]}")

    if meta["embed_backend"] == "hash-fallback":
        print("\n  ⚠️ embed_backend=hash-fallback — 해시 임베딩 데모 점수다. 실측이 아니다.")
        print("     VOYAGE_API_KEY 를 설정하면 voyage-3.5 실측 점수가 나온다.")
    print("\n  ※ multi-hop 의 점수가 single-hop 보다 낮다 — 이게 Phase 4 GraphRAG 의 동기다.")


def main() -> None:
    scores = evaluate()
    print_report(scores)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    SCORES_PATH.write_text(json.dumps(scores, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[완료] 기준선 점수 저장: {SCORES_PATH.relative_to(HERE)}")


if __name__ == "__main__":
    main()
