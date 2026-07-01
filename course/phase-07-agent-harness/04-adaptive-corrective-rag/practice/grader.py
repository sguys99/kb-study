"""grader.py — CRAG 의 'retrieval evaluator'를 하니스에 맞춰 축약한 채점기.

CRAG(2401.15884)는 경량 retrieval evaluator 로 검색 결과의 신뢰도를 correct / incorrect /
ambiguous 로 나누고, 부족하면 교정(재검색·웹 폴백)을 튼다. 우리는 등급 이름만 바꿔
relevant / ambiguous / irrelevant 로 채점하고, 부족하면 Query Rewrite 재검색을 튼다.
웹 폴백 대신 재작성 재시도를 교정 행동으로 삼는다(웹 폴백은 이 코스 범위 밖).

입력: 원 질문 + 검색 결과(01~03 도구가 돌려준 형태). 도구마다 결과 모양이 달라
  '행 리스트'로 정규화해 채점한다(docs_search=리스트, graph_query={"rows":[...]}).

출력 계약 GradeResult:
  grade  : relevant / ambiguous / irrelevant
  score  : 0.0~1.0 근거 충분도(디버깅·임계값 조정용)
  reason : 왜 그 등급인지 한 줄
  n_rows : 채점 대상 행 수

두 경로:
  1) 기본 — ANTHROPIC_API_KEY 로 Claude 가 등급을 JSON(enum)으로 판정.
  2) 폴백(비용 0) — 키 없으면 규칙 채점기. 결과 유무·질문 용어와의 겹침으로 등급을 매긴다.

전제: 표준 라이브러리 + (선택) anthropic. 도구 결과의 '모양'만 알면 되고 도구 내부는 모른다.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

# CRAG 임계값(규칙 폴백). score 상한/하한으로 3등급을 가른다.
RELEVANT_TH = 0.5
IRRELEVANT_TH = 0.15

_TOKEN_RE = re.compile(r"[A-Za-z0-9가-힣]+")
# 불용어: 조사·의문사·자주 나오는 서술어. 이걸 빼야 '핵심 명사 겹침'으로 채점된다.
# 안 빼면 '어떻게·연결돼·있나' 같은 질문투가 분모를 키워 정상 근거도 ambiguous 로 깎인다.
_STOP = {
    "은", "는", "이", "가", "을", "를", "와", "과", "의", "에", "에서", "도", "만",
    "무엇", "어떻게", "왜", "언제", "어떤", "어디", "누가", "얼마나",
    "있나", "있는가", "하나", "하는가", "인가", "된다", "한다", "되나",
    "연결돼", "연결된", "이어져", "관련", "차이", "무엇인가",
}


@dataclass
class GradeResult:
    grade: str          # relevant / ambiguous / irrelevant
    score: float
    reason: str
    n_rows: int
    backend: str = "rule"

    @property
    def sufficient(self) -> bool:
        """교정이 필요 없을 만큼 충분한가. relevant 만 통과."""
        return self.grade == "relevant"

    def to_dict(self) -> dict:
        return {
            "grade": self.grade, "score": round(self.score, 3),
            "reason": self.reason, "n_rows": self.n_rows, "backend": self.backend,
        }


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text) if t not in _STOP]


def normalize_rows(retrieval: object) -> list[dict]:
    """도구가 뱉은 결과를 채점용 행 리스트로 정규화한다.

    - docs_search        : [{"chunk_id","text",...}, ...] (리스트)
    - graph_query        : {"rows":[...], ...}            (dict)
    - ontology_check     : {"violations":[...], "ok":...} (dict, rows 없음)
    graph_query 의 rows 첫 항목이 generated_cypher 같은 메타면 그대로 둔다(있는 그대로 채점).
    """
    if isinstance(retrieval, dict):
        if "rows" in retrieval and isinstance(retrieval["rows"], list):
            return [r for r in retrieval["rows"] if isinstance(r, dict)]
        # ontology_check 처럼 rows 가 없는 결과는 통째로 한 행 취급.
        return [retrieval]
    if isinstance(retrieval, list):
        return [r for r in retrieval if isinstance(r, dict)]
    return []


def _row_text(row: dict) -> str:
    """행에서 채점에 쓸 텍스트를 모은다. 여러 도구의 필드명을 넓게 받는다."""
    parts = []
    # docs_search=text / graph_query=from·to·relation·neighbor·entity / lightrag=answer.
    for key in ("text", "from", "to", "neighbor", "relation", "entity",
                "path", "answer", "name", "reason"):
        v = row.get(key)
        if isinstance(v, str):
            parts.append(v)
    return " ".join(parts)


# ── 규칙 채점기(폴백) ───────────────────────────────────────────────────────
def _grade_rule(question: str, rows: list[dict]) -> tuple[str, float, str]:
    """결과 유무 + 질문 용어와의 어휘 겹침으로 3등급을 매긴다."""
    # 오류/차단/빈 결과는 곧장 irrelevant.
    if not rows:
        return "irrelevant", 0.0, "검색 결과가 비었다"
    if any(r.get("error") or r.get("blocked") for r in rows):
        return "irrelevant", 0.05, "도구가 오류·차단을 반환했다"

    q_terms = set(_tokenize(question))
    if not q_terms:
        return "ambiguous", 0.4, "질문에서 유효 토큰을 못 뽑았다"

    # 각 행에서 질문 용어가 얼마나 겹치는지 → 최고 겹침 비율을 score 로.
    best = 0.0
    for r in rows:
        r_terms = set(_tokenize(_row_text(r)))
        if not r_terms:
            continue
        overlap = len(q_terms & r_terms) / len(q_terms)
        best = max(best, overlap)

    if best >= RELEVANT_TH:
        return "relevant", best, f"질문 용어와 겹침 {best:.2f} ≥ {RELEVANT_TH}"
    if best <= IRRELEVANT_TH:
        return "irrelevant", best, f"질문 용어와 겹침 {best:.2f} ≤ {IRRELEVANT_TH}"
    return "ambiguous", best, f"겹침 {best:.2f} — 부분적으로만 관련"


# ── LLM 채점기(기본 경로) ───────────────────────────────────────────────────
_GRADER_SYSTEM = (
    "너는 검색 결과 채점기다. 사용자 질문과 검색된 근거를 보고, 근거가 질문에 답하기 충분한지 "
    "세 등급으로 매긴다.\n"
    "- relevant  : 근거만으로 질문에 답할 수 있다.\n"
    "- ambiguous : 일부만 관련. 답하기엔 부족하거나 애매하다.\n"
    "- irrelevant: 질문과 무관하거나 근거가 비었다.\n"
    '반드시 {"grade":"<relevant|ambiguous|irrelevant>","score":<0~1>,"reason":"<한 줄>"} JSON 만 출력한다.'
)


def _grade_llm(question: str, rows: list[dict]) -> tuple[str, float, str] | None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic

        client = anthropic.Anthropic()
        model = os.environ.get("HARNESS_MODEL", "claude-sonnet-4-6")
        evidence = json.dumps(rows, ensure_ascii=False)[:4000]
        resp = client.messages.create(
            model=model, max_tokens=200, system=_GRADER_SYSTEM,
            messages=[{"role": "user", "content": f"질문: {question}\n근거: {evidence}"}],
        )
        text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
        data = json.loads(_first_json(text))
        grade = data.get("grade", "").strip()
        if grade not in ("relevant", "ambiguous", "irrelevant"):
            return None
        return grade, float(data.get("score", 0.5)), data.get("reason", "(LLM 판정)")
    except Exception:
        return None


def _first_json(text: str) -> str:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    return m.group(0) if m else text


def grade(question: str, retrieval: object) -> GradeResult:
    """검색 결과를 채점한다. 키 있으면 Claude, 없거나 실패하면 규칙 폴백."""
    rows = normalize_rows(retrieval)
    llm = _grade_llm(question, rows)
    if llm is not None:
        g, s, reason = llm
        backend = "claude"
    else:
        g, s, reason = _grade_rule(question, rows)
        backend = "rule"
    return GradeResult(grade=g, score=s, reason=reason, n_rows=len(rows), backend=backend)


if __name__ == "__main__":
    print(f"[grader] backend={'claude' if os.environ.get('ANTHROPIC_API_KEY') else 'rule'}\n")

    q = "Self-RAG 는 언제 검색을 하나?"
    good = [{"chunk_id": "doc-self-rag-01",
             "text": "Self-RAG 는 검색이 필요한지 스스로 평가해, 언제 검색을 할지 매 스텝 결정한다."}]
    print("정상 결과:", grade(q, good).to_dict())

    empty = []  # 검색이 빈약(0건) — irrelevant 기대
    print("빈 결과  :", grade(q, empty).to_dict())

    off = [{"chunk_id": "doc-x", "text": "Neo4j 는 속성 그래프 데이터베이스다."}]
    print("빗나간 결과:", grade(q, off).to_dict())
