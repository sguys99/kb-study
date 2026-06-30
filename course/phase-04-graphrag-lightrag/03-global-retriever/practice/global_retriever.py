"""4.3 global_retriever.py — Map-Reduce 전역 검색기. *From Local to Global* 의 핵심 알고리즘.

4.2 의 Local·Path 는 '특정 엔티티에서 출발'한다. "Neo4j 와 RAG 는 어떻게 연결되나"처럼
시작점이 분명한 질문에 강하다. 반대로 "이 코퍼스 전체의 핵심 주제는?", "GraphRAG 연구
지형을 요약하면?" 같은 질문은 시작 엔티티가 없다. Local 은 어디서 출발할지 못 정한다.
Vector RAG 도 top-k 청크만 봐서 전체 그림을 못 본다.

Global 은 다르게 푼다. 코퍼스를 커뮤니티로 쪼개 미리 요약해 두고(community_summarize),
질문이 오면 그 요약들을 map-reduce 로 종합한다.

    MAP    : 질문을 '커뮤니티 요약마다' 따로 던진다.
             각 요약이 질문에 얼마나 답이 되는지 (부분답변 + 관련도 점수)를 만든다.
    REDUCE : 부분답변들을 관련도 순으로 모아 하나의 전역 답변으로 종합한다.

Local 은 한 군데를 깊게 본다. Global 은 전체를 한 번에 훑는다. 둘은 경쟁이 아니라 보완이다.
4.4(Vector+Graph Fusion)·4.5(A/B)가 이 GlobalRetriever 를 import 해서 두 축을 섞는다.

전제:
    - community_summarize.py 로 community_reports.json 이 만들어져 있어야 한다.
      (요약 캐시만 있으면 이 단계는 Neo4j 없이도 돈다 — JSON 만 읽는다.)
    - LLM 백엔드: ANTHROPIC_API_KEY 있으면 Claude, 없으면 Ollama(llm_backend 규약).
      키는 os.environ 에서만 읽는다. 하드코딩 금지.

실행:
    python global_retriever.py "이 코퍼스의 핵심 주제를 요약하면?"
    python global_retriever.py                # 인자 없으면 기본 전체요약 질문으로 데모
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from llm_backend import active_backend, complete

REPORTS_PATH = Path(__file__).with_name("community_reports.json")


def load_reports() -> list[dict]:
    """community_summarize.py 가 만든 요약 캐시를 읽는다."""
    if not REPORTS_PATH.exists():
        raise FileNotFoundError(
            f"{REPORTS_PATH.name} 가 없다. 먼저 python community_summarize.py 를 돌려라."
        )
    data = json.loads(REPORTS_PATH.read_text(encoding="utf-8"))
    return data["reports"]


def _parse_score(text: str) -> float:
    """LLM 답에서 'SCORE: 7' 같은 관련도 점수를 뽑는다. 못 찾으면 0."""
    m = re.search(r"SCORE\s*[:=]\s*(\d+(?:\.\d+)?)", text, flags=re.IGNORECASE)
    if not m:
        return 0.0
    return max(0.0, min(10.0, float(m.group(1))))  # 0~10 로 클램프


def _strip_score_line(text: str) -> str:
    """부분답변 본문에서 SCORE 줄을 떼어 낸다(종합 단계에 점수 줄이 섞이지 않게)."""
    lines = [ln for ln in text.splitlines() if not re.match(r"\s*SCORE\s*[:=]", ln, re.IGNORECASE)]
    return "\n".join(lines).strip()


def map_one(question: str, report: dict) -> dict:
    """MAP — 커뮤니티 요약 하나에 질문을 던져 (부분답변, 점수)를 만든다.

    점수는 'SCORE: 0~10' 형식으로 받아 파싱한다. 이 요약이 질문과 무관하면 0 에 가깝게,
    핵심이면 10 에 가깝게 매기라고 시킨다. 무관한 커뮤니티를 REDUCE 에서 거르기 위함이다.
    """
    prompt = (
        "아래는 지식그래프 한 커뮤니티의 요약이다. 사용자 질문에 이 커뮤니티가 도움이 되는 만큼만 답하라.\n"
        "먼저 'SCORE: <0~10 정수>' 한 줄로 이 요약이 질문에 얼마나 관련 있는지 매겨라"
        "(무관하면 0, 핵심이면 10). 그다음 줄부터 이 커뮤니티 정보만으로 한국어 1~3문장 부분답변을 적어라.\n\n"
        f"[질문]\n{question}\n\n[커뮤니티 {report['community']} 요약]\n{report['summary']}\n\n답:"
    )
    raw = complete(prompt, max_tokens=300)
    return {
        "community": report["community"],
        "members": report["members"],
        "score": _parse_score(raw),
        "answer": _strip_score_line(raw),
    }


def reduce_answers(question: str, partials: list[dict], top_k: int = 5) -> str:
    """REDUCE — 점수 높은 부분답변을 모아 하나의 전역 답변으로 종합한다.

    관련도 0 인 커뮤니티는 버린다. 남은 부분답변을 점수순으로 정렬해 종합 프롬프트에 넣고,
    LLM 에 '근거가 된 커뮤니티를 밝히며' 하나로 합치게 한다. map 만 하고 reduce 를 빼면
    부분답변 더미만 남고 '전역 답변'이 안 나온다 — reduce 가 Global 의 완성이다.
    """
    useful = sorted(
        [p for p in partials if p["score"] > 0],
        key=lambda p: p["score"], reverse=True,
    )[:top_k]
    if not useful:
        return "[Global] 어떤 커뮤니티도 질문과 관련이 없다. 질문을 바꾸거나 코퍼스를 넓혀라."

    block = "\n\n".join(
        f"[커뮤니티 {p['community']} · 관련도 {p['score']:.0f} · 멤버 {', '.join(p['members'][:4])}]\n"
        f"{p['answer']}"
        for p in useful
    )
    prompt = (
        "여러 커뮤니티에서 모은 부분답변이다. 이를 하나의 일관된 전역 답변으로 종합하라.\n"
        "중복은 합치고, 관련도 높은 내용을 앞세우고, 한국어로 답하라. "
        "어느 커뮤니티에서 나온 근거인지 괄호로 가볍게 밝혀라.\n\n"
        f"[질문]\n{question}\n\n[부분답변들]\n{block}\n\n전역 답변:"
    )
    return complete(prompt, max_tokens=600)


class GlobalRetriever:
    """전역(Map-Reduce) 검색기. 4.4·4.5 가 import 하는 진입점.

    reports 를 한 번 읽어 들고, search() 한 번에 map → reduce 를 돈다.
    Local·Path 처럼 시작 엔티티를 받지 않는다 — 코퍼스 전체를 대상으로 한다.
    """

    def __init__(self, reports: list[dict] | None = None) -> None:
        self.reports = reports if reports is not None else load_reports()

    def map_all(self, question: str) -> list[dict]:
        """MAP 단계 — 모든 커뮤니티 요약에 질문을 던진다."""
        return [map_one(question, r) for r in self.reports]

    def search(self, question: str, top_k: int = 5) -> dict:
        """전역 검색 한 번 — map(부분답변+점수) → reduce(종합). 중간 결과도 함께 돌려준다."""
        partials = self.map_all(question)
        final = reduce_answers(question, partials, top_k=top_k)
        return {"question": question, "partials": partials, "answer": final}


def main(argv: list[str]) -> int:
    question = argv[1] if len(argv) > 1 else "이 코퍼스의 핵심 주제를 큰 그림으로 요약하면?"
    print(f"[백엔드] LLM = {active_backend()}")
    print(f"[질문] {question}\n")

    retriever = GlobalRetriever()
    result = retriever.search(question)

    print("[MAP] 커뮤니티별 부분답변(관련도 점수):")
    for p in sorted(result["partials"], key=lambda x: x["score"], reverse=True):
        head = p["answer"].replace("\n", " ")[:80]
        print(f"  c{p['community']} (score {p['score']:.0f}, {', '.join(p['members'][:3])}...): {head}")

    print("\n[REDUCE] 전역 답변:")
    print(result["answer"])
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except FileNotFoundError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"[FAIL] {type(exc).__name__}: {exc}", file=sys.stderr)
        print("  - community_reports.json 생성(community_summarize.py) 여부를 확인하라.",
              file=sys.stderr)
        print("  - LLM 호출 실패면 ANTHROPIC_API_KEY 또는 Ollama 기동을 확인하라.", file=sys.stderr)
        sys.exit(1)
