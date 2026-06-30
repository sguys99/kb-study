"""4.4 candidates.py — 출처가 다른 후보를 하나의 공통 스키마로 통일한다.

이 토픽의 입력은 두 갈래다.
  - Vector 후보: Phase 1/06 의 Hybrid(Vector+BM25) 검색기가 내는 의미 근접 청크.
  - Graph 후보: 4.2 의 Local/Path 검색기, 4.3 의 Community 요약이 내는 그래프 근거.

두 후보는 점수 스케일이 전혀 다르다(코사인 유사도 0~1 vs 경로 홉 수 vs 관련도 0~10).
그대로 한 리스트에 섞으면 비교가 안 된다. 그래서 먼저 '같은 모양'으로 맞춘다 —
공통 데이터클래스 Candidate(id, source, text, score, metadata).

이 모듈은 외부 의존이 없다. 표준 라이브러리만 쓰고, 동봉된 sample_candidates.json 으로
앞 토픽 산출물을 모사한다. 실제로는 4.2/4.3 의 검색기 출력을 이 스키마로 감싸면 된다.

전제: 없음(키 불필요, 과금 0).
실행:
    python candidates.py                       # 동봉 샘플을 Candidate 로 로드해 출력
    python candidates.py path/to/other.json     # 다른 후보 파일 사용
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

# 동봉 샘플 경로 — 스크립트와 같은 폴더.
SAMPLE_PATH = Path(__file__).with_name("sample_candidates.json")

# 후보 출처 종류. vector = Phase 1 하이브리드 청크, graph = 4.2/4.3 그래프 근거.
VALID_SOURCES = {"vector", "graph"}


@dataclass
class Candidate:
    """출처가 달라도 융합·재순위·패킹이 똑같이 다룰 수 있는 공통 후보 단위.

    score 는 '출처 안에서의 원점수'다. vector 는 코사인 유사도(0~1),
    graph 는 출처별로 의미가 다르다(path=홉 수, community=관련도 0~10 등).
    스케일이 다르므로 fuse.py 가 정규화·순위 융합으로 공통 척도로 바꾼다.
    """

    id: str
    source: str          # "vector" | "graph"
    text: str
    score: float
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.source not in VALID_SOURCES:
            raise ValueError(f"source 는 {VALID_SOURCES} 중 하나여야 한다: {self.source!r}")

    def short(self, width: int = 60) -> str:
        """로그·표에 한 줄로 찍기 위한 짧은 미리보기."""
        t = self.text.replace("\n", " ").strip()
        return t if len(t) <= width else t[: width - 1] + "…"


def load_pool(path: str | Path | None = None) -> tuple[str, list[Candidate]]:
    """후보 파일을 읽어 (질문, 후보 리스트)로 돌려준다.

    vector / graph 두 블록을 각각 Candidate 로 감싸 하나의 풀로 합친다.
    여기서는 합치기만 한다. 점수를 섞는 일은 fuse.py 의 몫이다.
    """
    p = Path(path) if path else SAMPLE_PATH
    raw = json.loads(p.read_text(encoding="utf-8"))
    question = raw.get("question", "")

    pool: list[Candidate] = []
    for c in raw.get("vector", []):
        pool.append(Candidate(id=c["id"], source="vector", text=c["text"],
                              score=float(c["score"]), metadata=c.get("metadata", {})))
    for c in raw.get("graph", []):
        pool.append(Candidate(id=c["id"], source="graph", text=c["text"],
                              score=float(c["score"]), metadata=c.get("metadata", {})))
    return question, pool


def main(argv: list[str]) -> None:
    path = argv[1] if len(argv) > 1 else None
    question, pool = load_pool(path)

    print(f"[질문] {question}")
    print(f"[후보 풀] 총 {len(pool)}개 "
          f"(vector {sum(c.source == 'vector' for c in pool)}, "
          f"graph {sum(c.source == 'graph' for c in pool)})\n")
    for c in pool:
        print(f"  {c.id:>3} [{c.source:>6}] score={c.score:>5.2f}  {c.short()}")
    print("\n[다음] python fuse.py 로 스케일 다른 점수를 RRF 로 융합한다.")


if __name__ == "__main__":
    main(sys.argv)
