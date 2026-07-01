"""query_rewrite.py — Self-RAG/CRAG 의 '질의 교정'을 하니스에 맞춰 축약한 재작성기.

Grader 가 relevant 가 아니라고 판정하면, 원 질문을 검색 친화적으로 다시 써서 재검색한다.
CRAG 는 질의를 분해·정제하고, Self-RAG 는 반성 토큰으로 재검색을 유도한다. 우리는 그중
'검색이 잘 걸리도록 질문을 다시 쓴다'는 한 줄만 가져온다. 재시도 상한은 adaptive_loop 이 건다.

입력: 원 질문 + (선택) 직전 등급/사유 + 이미 시도한 재작성들(중복 방지).
출력 계약 RewriteResult:
  query     : 새 검색 질의(재검색에 그대로 쓴다)
  strategy  : 어떤 재작성 전략을 썼는지(감사·디버깅용)
  changed   : 원 질문과 달라졌는지(안 바뀌면 재시도가 무의미하므로 루프가 멈출 근거)

두 경로:
  1) 기본 — ANTHROPIC_API_KEY 로 Claude 가 검색 친화 질의로 재작성.
  2) 폴백(비용 0) — 키 없으면 규칙 재작성. 조사·군더더기 제거 → 엔티티·핵심어만 남긴다.

전제: 표준 라이브러리 + (선택) anthropic. router 의 엔티티 사전을 재사용한다.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from router import KNOWN_ENTITIES

# 규칙 재작성에서 버리는 군더더기 토큰(질문투·조사·불용어). 검색어만 남기려는 것.
# 부분 문자열이 아니라 '토큰 전체'가 이 집합이거나, 이 접미사로 끝나면 버린다.
# (부분 치환은 '하는 건가요'를 '하 건 요'로 부수므로 토큰 단위로 판정한다.)
_NOISE_TOKENS = {
    "무엇", "무엇인가", "무엇인가요", "무엇이야", "어떻게", "어떤", "언제", "왜", "도대체",
    "인가", "인가요", "일까", "일까요", "건가요", "건가", "하나", "하는", "하나요",
    "해줘", "알려줘", "설명해", "정리해", "정리해줘", "요약해", "무엇인지",
    "차이", "관계", "그건", "그것", "동작하나요", "동작",
    "라는", "대체", "거야", "논문에서", "제안한", "아이디어",
    "은", "는", "이", "가", "을", "를", "와", "과", "의", "에", "에서", "도", "만",
}
# 이 접미사로 끝나는 토큰은 조사·어미가 붙은 것으로 보고 접미사만 떼어낸다.
_JOSA_SUFFIX = ("은", "는", "이", "가", "을", "를", "와", "과", "의", "에", "에서", "도", "만")
_WORD_RE = re.compile(r"[A-Za-z0-9가-힣\-]+")


@dataclass
class RewriteResult:
    query: str
    strategy: str
    changed: bool
    backend: str = "rule"

    def to_dict(self) -> dict:
        return {"query": self.query, "strategy": self.strategy,
                "changed": self.changed, "backend": self.backend}


def _strip_josa(token: str) -> str:
    """토큰 끝에 붙은 한 글자 조사를 떼어낸다(검색을 → 검색). 3글자 이상 한글 토큰만."""
    if len(token) >= 3 and token[-1] in _JOSA_SUFFIX and "가" <= token[-1] <= "힣":
        return token[:-1]
    return token


def _rewrite_rule(question: str, tried: list[str]) -> RewriteResult:
    """규칙 재작성: 엔티티는 살리고 질문투·조사를 걷어 핵심 검색어만 남긴다.

    엔티티가 잡히면 '엔티티 + 남은 핵심어'로 좁혀 검색이 걸리게 한다.
    엔티티가 없으면 군더더기만 제거한다. 이미 시도한 질의와 같으면 살짝 다르게 만든다.
    """
    ents = [e for e in KNOWN_ENTITIES if e.lower() in question.lower()]
    # 멀티 단어 엔티티(Tool Use, Reflection Token)의 '구성 단어'까지 제외 집합에 넣는다.
    # 안 그러면 'Reflection Token' 이 엔티티로도, 'Reflection'·'Token' 키워드로도 중복된다.
    ent_words = set()
    for e in ents:
        for w in _WORD_RE.findall(e.lower()):
            ent_words.add(w)

    # 토큰 단위로 걷어낸다: 엔티티(구성 단어 포함)는 제외, 군더더기·1글자는 버린다.
    keywords: list[str] = []
    for tok in _WORD_RE.findall(question):
        if tok.lower() in ent_words:
            continue  # 엔티티는 ents 로 따로 처리(중복 방지).
        clean = _strip_josa(tok)
        if len(clean) < 2 or clean in _NOISE_TOKENS:
            continue
        if clean not in keywords:
            keywords.append(clean)

    if ents:
        # 엔티티를 앞세우고 남은 핵심어를 덧붙인다(검색 신호 강화).
        new_q = (" ".join(ents) + (" " + " ".join(keywords) if keywords else "")).strip()
        strategy = "엔티티 중심 축약 + 조사·질문투 제거"
    else:
        new_q = " ".join(keywords) or question
        strategy = "조사·질문투 제거"

    # 이미 시도한 질의와 같으면 '정의'를 덧붙여 한 번 더 흔든다(무의미한 재시도 방지).
    if new_q in tried:
        new_q = (new_q + " 정의 개념").strip()
        strategy += " + 동의 키워드 추가"

    return RewriteResult(query=new_q, strategy=strategy, changed=(new_q != question), backend="rule")


_REWRITE_SYSTEM = (
    "너는 검색 질의 재작성기다. 사용자의 원 질문이 검색에서 좋은 근거를 못 찾았다. "
    "같은 의도를 유지하되, 벡터·키워드 검색에 잘 걸리도록 핵심 개념·고유명사 중심으로 "
    "질의를 다시 써라. 새 질의 한 줄만 출력한다(설명·따옴표 없이)."
)


def _rewrite_llm(question: str, grade_reason: str, tried: list[str]) -> RewriteResult | None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic

        client = anthropic.Anthropic()
        model = os.environ.get("HARNESS_MODEL", "claude-sonnet-4-6")
        ctx = f"원 질문: {question}\n직전 검색이 부족한 이유: {grade_reason}"
        if tried:
            ctx += f"\n이미 시도한 질의(피하라): {tried}"
        resp = client.messages.create(
            model=model, max_tokens=120, system=_REWRITE_SYSTEM,
            messages=[{"role": "user", "content": ctx}],
        )
        text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
        new_q = text.strip().strip('"').strip()
        if not new_q:
            return None
        return RewriteResult(query=new_q, strategy="LLM 재작성",
                             changed=(new_q != question), backend="claude")
    except Exception:
        return None


def rewrite(question: str, grade_reason: str = "", tried: list[str] | None = None) -> RewriteResult:
    """질문을 검색 친화적으로 재작성한다. 키 있으면 Claude, 없거나 실패하면 규칙 폴백."""
    tried = tried or []
    llm = _rewrite_llm(question, grade_reason, tried)
    if llm is not None:
        return llm
    return _rewrite_rule(question, tried)


if __name__ == "__main__":
    print(f"[query_rewrite] backend={'claude' if os.environ.get('ANTHROPIC_API_KEY') else 'rule'}\n")
    samples = [
        "Self-RAG 는 도대체 언제 검색을 하는 건가요?",
        "CRAG 와 Self-RAG 의 차이가 무엇인지 정리해줘",
        "그건 어떻게 동작하나요?",  # 엔티티 없음 — 군더더기만 제거
    ]
    tried: list[str] = []
    for q in samples:
        r = rewrite(q, grade_reason="질문 용어와 겹침 0.10", tried=tried)
        tried.append(r.query)
        print(f"원  : {q}")
        print(f"재작성: {r.query!r}  ({r.strategy}, changed={r.changed})\n")
