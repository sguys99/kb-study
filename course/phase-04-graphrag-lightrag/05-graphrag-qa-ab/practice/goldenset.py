"""4.5 goldenset.py — golden_questions.json 을 Candidate 풀로 로드한다.

04 의 sample_candidates.json 은 질문 한 개에 vector/graph 풀을 동봉했다. 05 는 같은 모양을
질문 여러 개로 확장한다. 각 질문은 type(simple-fact / multi-hop / global-summary)과
gold(정답 근거 후보 id 집합)를 함께 갖는다.

이 모듈은 04 의 Candidate 스키마를 그대로 쓴다(id, source, text, score, metadata).
04 모듈을 import 경로에 올려 같은 클래스를 재사용한다 — 두 토픽이 같은 후보 타입을 공유해야
strategies/fusion_pipeline 이 그대로 맞물린다.

전제: 없음(키 불필요, 과금 0).
실행:
    python goldenset.py            # 골든셋 요약(질문 수·type 분포·gold 라벨) 출력
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# 04 practice 를 import 경로에 추가해 같은 Candidate 클래스를 쓴다.
_FUSION_DIR = (Path(__file__).resolve().parent.parent.parent
               / "04-vector-graph-fusion" / "practice")
if str(_FUSION_DIR) not in sys.path:
    sys.path.insert(0, str(_FUSION_DIR))

from candidates import Candidate  # noqa: E402

GOLDEN_PATH = Path(__file__).with_name("golden_questions.json")
VALID_TYPES = ("simple-fact", "multi-hop", "global-summary")


def _to_candidates(block: list[dict], source: str) -> list[Candidate]:
    """JSON 후보 블록을 Candidate 리스트로 감싼다."""
    out = []
    for c in block:
        out.append(Candidate(id=c["id"], source=source, text=c["text"],
                             score=float(c["score"]), metadata=c.get("metadata", {})))
    return out


def load_golden(path: str | Path | None = None) -> list[dict]:
    """골든셋을 읽어 질문별 dict 리스트로 돌려준다.

    각 dict: qid, type, question, gold(set[str]), pool(list[Candidate]).
    """
    p = Path(path) if path else GOLDEN_PATH
    raw = json.loads(p.read_text(encoding="utf-8"))

    items: list[dict] = []
    for q in raw["questions"]:
        if q["type"] not in VALID_TYPES:
            raise ValueError(f"알 수 없는 type: {q['type']!r} (qid={q['qid']})")
        pool = _to_candidates(q.get("vector", []), "vector") \
            + _to_candidates(q.get("graph", []), "graph")
        items.append({
            "qid": q["qid"],
            "type": q["type"],
            "question": q["question"],
            "gold": set(q["gold"]),
            "pool": pool,
        })
    return items


def load_pool_for(qid: str | None = None,
                  path: str | Path | None = None) -> tuple[str, list[Candidate], set[str]]:
    """특정 qid(없으면 첫 질문)의 (질문, 후보 풀, gold)를 돌려준다.

    strategies.py 가 단건 비교를 찍을 때 쓴다.
    """
    items = load_golden(path)
    if not items:
        raise ValueError("골든셋이 비었다.")
    if qid is None:
        chosen = items[0]
    else:
        match = [it for it in items if it["qid"] == qid]
        if not match:
            raise ValueError(f"qid 를 찾을 수 없다: {qid!r}")
        chosen = match[0]
    return chosen["question"], chosen["pool"], chosen["gold"]


def main(argv: list[str]) -> None:
    items = load_golden()
    by_type: dict[str, int] = {}
    for it in items:
        by_type[it["type"]] = by_type.get(it["type"], 0) + 1

    print(f"[골든셋] 질문 {len(items)}개")
    print("[type 분포] " + ", ".join(f"{t}={by_type.get(t, 0)}" for t in VALID_TYPES))
    print()
    for it in items:
        n_vec = sum(c.source == "vector" for c in it["pool"])
        n_gph = sum(c.source == "graph" for c in it["pool"])
        print(f"  {it['qid']} [{it['type']:>13}] gold={sorted(it['gold'])} "
              f"풀(vec {n_vec}/graph {n_gph})  {it['question'][:34]}…")
    print("\n[다음] python strategies.py 로 한 질문에 네 전략을 세워 본다.")


if __name__ == "__main__":
    main(sys.argv)
