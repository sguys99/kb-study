"""checkpoint.py — Human Checkpoint: 저신뢰·위험 상황에서 사람 승인을 받는 후크.

지금까지의 가드는 '기계가 알아서 멈추거나 우회'했다. 하지만 어떤 상황은 기계가 단독으로
진행하면 안 된다. 두 가지다:
  - 저신뢰(low confidence) : Grader 등급이 낮은데도 답을 내보내려 할 때.
  - 위험(risky)           : 쓰기·삭제 유사, 민감어(비밀번호·결제·개인정보) 포함 등.

이때 루프를 잠깐 멈추고 사람에게 물어본다 — "이대로 진행할까요?" 승인이면 진행, 거절이면
stop_reason='rejected_by_human' 으로 안전하게 멈춘다.

비대화 실행을 반드시 지원한다. CI·테스트·labs 는 input() 을 못 받으므로, 환경변수
AUTO_APPROVE 로 사람 없이 자동 승인/거절하게 한다. 기본은 비대화(자동 승인)로 둬서
키·터미널 없이도 전 흐름이 돈다.
  - AUTO_APPROVE 미설정 or '1'/'yes' → 자동 승인(테스트 기본).
  - AUTO_APPROVE='0'/'no'            → 자동 거절.
  - AUTO_APPROVE='ask'               → 콘솔 input() 로 실제 사람에게 물어본다.

전제: 표준 라이브러리(os·re·dataclasses)만.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

# 위험 신호(쓰기 유사·민감어). Cypher 안전판(03)과 결이 같지만 여기선 '사람 승인' 트리거다.
_WRITE_LIKE = re.compile(
    r"\b(delete|remove|drop|create|merge|set|detach|update|insert|삭제|제거|변경|생성|수정)\b",
    re.IGNORECASE,
)
_SENSITIVE = re.compile(
    r"(비밀번호|password|주민등록|계좌|결제|카드번호|개인정보|api[_\s-]?key|secret|token)",
    re.IGNORECASE,
)

# 이 점수 미만이면 '저신뢰'로 보고 사람 승인을 요구한다. Grader.score(0~1) 기준.
LOW_CONFIDENCE_TH = 0.5


@dataclass
class CheckpointDecision:
    """체크포인트 판정 결과. 왜 체크포인트가 걸렸는지(reasons)와 승인 여부를 담는다."""

    needed: bool                       # 애초에 사람 승인이 필요했는가
    approved: bool                     # 승인되었는가(needed=False 면 항상 True)
    reasons: list[str] = field(default_factory=list)
    mode: str = "auto"                 # auto-approve / auto-reject / ask / not-needed


def assess(question: str, answer: str, score: float) -> list[str]:
    """이 답을 사람 확인 없이 내보내도 되는지 판단해, 걸리는 사유를 모아 돌려준다.

    사유가 하나라도 있으면 체크포인트가 필요하다. 빈 리스트면 그냥 통과.
    - 저신뢰   : Grader score 가 임계값 미만.
    - 쓰기 유사 : 질문·답에 쓰기/삭제 동사가 보임(부작용 위험).
    - 민감어   : 개인정보·자격증명 관련어가 보임.
    """
    reasons: list[str] = []
    if score < LOW_CONFIDENCE_TH:
        reasons.append(f"저신뢰(score={score:.2f} < {LOW_CONFIDENCE_TH})")
    blob = f"{question}\n{answer}"
    if _WRITE_LIKE.search(blob):
        reasons.append("쓰기·삭제 유사 표현 감지")
    if _SENSITIVE.search(blob):
        reasons.append("민감어(개인정보·자격증명) 감지")
    return reasons


def _auto_verdict() -> tuple[bool, str] | None:
    """AUTO_APPROVE 환경변수로 자동 판정. 'ask' 면 None(콘솔로 물어보라는 신호)."""
    raw = os.environ.get("AUTO_APPROVE")
    if raw is None:
        return True, "auto-approve"  # 기본: 비대화 자동 승인(labs·CI 가 막히지 않게).
    v = raw.strip().lower()
    if v in ("1", "yes", "y", "true"):
        return True, "auto-approve"
    if v in ("0", "no", "n", "false"):
        return False, "auto-reject"
    if v == "ask":
        return None  # 실제 사람에게 묻는다.
    return True, "auto-approve"


def request_approval(question: str, answer: str, score: float) -> CheckpointDecision:
    """저신뢰·위험이면 승인 절차를 태운다. 아니면 그냥 통과(needed=False).

    승인 경로:
      - AUTO_APPROVE 로 자동 승인/거절(테스트·비대화 기본).
      - AUTO_APPROVE='ask' 일 때만 콘솔 input() 로 실제 사람에게 y/N 을 묻는다.
    """
    reasons = assess(question, answer, score)
    if not reasons:
        return CheckpointDecision(needed=False, approved=True, reasons=[], mode="not-needed")

    verdict = _auto_verdict()
    if verdict is not None:
        approved, mode = verdict
        return CheckpointDecision(needed=True, approved=approved, reasons=reasons, mode=mode)

    # AUTO_APPROVE='ask' — 실제 콘솔 승인.
    print("\n[HUMAN CHECKPOINT] 사람 승인이 필요합니다.")
    for r in reasons:
        print(f"  - 사유: {r}")
    print(f"  질문: {question}")
    print(f"  답(초안): {answer[:200]}")
    try:
        ans = input("  진행할까요? [y/N] ").strip().lower()
    except EOFError:
        ans = "n"  # 입력 스트림이 없으면 안전하게 거절.
    approved = ans in ("y", "yes")
    return CheckpointDecision(needed=True, approved=approved, reasons=reasons, mode="ask")


if __name__ == "__main__":
    # 빠른 자기점검: 저신뢰 / 위험 / 정상 세 경우를 자동 승인 모드로.
    os.environ.setdefault("AUTO_APPROVE", "1")
    print("저신뢰:", request_approval("Self-RAG 는?", "잘 모르겠다.", score=0.2))
    print("위험  :", request_approval("이 노드를 delete 해도 되나?", "삭제 가능", score=0.9))
    print("정상  :", request_approval("Self-RAG 는?", "매 스텝 검색 여부를 스스로 정한다.[c1]", score=0.8))
