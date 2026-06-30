"""4.1 routing_demo.py — 질문을 5가지 GraphRAG 검색 패턴으로 라우팅하는 규칙 기반 데모.

이 토픽은 "어떤 질문에 어떤 검색 패턴을 쓰는가"의 개념 지도다.
여기서는 그 매핑을 손으로 만져 보려고, 질문 문자열을 받아 키워드·질문형으로
Local / Path / Global / Community / Memory 중 하나로 분류한다. 각 패턴에 대응하는
대표 LightRAG 모드(naive/local/global/hybrid/mix)도 함께 출력한다.

전제:
    - 외부 의존 없음. Python 3.11+ 표준 라이브러리만 사용한다(LLM·API 키 불필요, 과금 0).

실행:
    python routing_demo.py                  # 내장 예시 질문 6개를 분류
    python routing_demo.py "RAG와 GraphRAG는 어떻게 연결되는가?"   # 임의 질문 1개 분류

주의 — 이건 "개념 이해용" 휴리스틱이다:
    실제 라우팅은 규칙 몇 줄로 끝나지 않는다. Phase 7 Agent Harness 에서 이 자리를
    LLM Router(질문 의도를 LLM 이 판단해 검색 도구를 고르는)로 교체한다. 여기서는
    패턴과 모드의 대응을 눈으로 익히는 데 목적이 있다.
    LLM 으로 라우팅을 실험하고 싶다면 Claude(ANTHROPIC_API_KEY) 또는
    비용 0 으로 Ollama(로컬) 를 써서 이 분류 함수를 LLM 호출로 바꾸면 된다.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class Pattern:
    """검색 패턴 한 개의 정의 — 이름, 직관, 대표 LightRAG 모드, 메우는 RAG 실패."""

    key: str           # 패턴 키 (local/path/global/community/memory)
    intuition: str     # 한 줄 직관
    lightrag_mode: str # 대표 LightRAG 모드 — 영문 소문자 고정
    fixes: str         # Phase 0 의 어떤 RAG 실패를 메우는가


# 5가지 패턴 정의. lightrag_mode 는 glossary 표기(naive/local/global/hybrid/mix)를 따른다.
PATTERNS: dict[str, Pattern] = {
    "local": Pattern(
        key="local",
        intuition="특정 엔티티의 이웃을 집중 탐색 — '이건 무엇이고 무엇과 직접 연결되나'",
        lightrag_mode="local",
        fixes="단일 엔티티 사실은 Baseline 도 어느 정도 답하지만, 관계 맥락은 그래프가 더 정확",
    ),
    "path": Pattern(
        key="path",
        intuition="두 엔티티 사이 멀티홉 경로 추적 — 'A와 B는 어떻게 이어지나'",
        lightrag_mode="hybrid",  # 엔티티+관계를 함께 끌어오는 hybrid 가 경로형에 가깝다
        fixes="멀티홉 실패 — Vector+BM25 는 중간 연결고리를 못 잇는다",
    ),
    "global": Pattern(
        key="global",
        intuition="커뮤니티 요약 + Map-Reduce 로 전체 조망 — '코퍼스 전체의 핵심 주제는'",
        lightrag_mode="global",
        fixes="전체요약 실패 — top-k 청크로는 코퍼스 전체를 못 본다",
    ),
    "community": Pattern(
        key="community",
        intuition="커뮤니티(클러스터) 자체를 검색 단위로 — '이 분야는 어떤 묶음으로 나뉘나'",
        lightrag_mode="global",  # 커뮤니티 기반이라 global 과 같은 모드 계열
        fixes="주제 구획·군집 질문 — 평면 검색은 묶음 구조를 못 드러낸다",
    ),
    "memory": Pattern(
        key="memory",
        intuition="대화·이전 결과를 상태로 누적 — '아까 그거 말고 다른 건' 같은 후속 질의",
        lightrag_mode="mix",  # 대화 히스토리를 함께 쓰는 멀티턴 맥락은 mix 에서 다룬다
        fixes="멀티턴 맥락 유실 — 단발 검색은 직전 턴을 기억하지 못한다",
    ),
}


# 패턴별 신호어. 한국어/영어를 섞어 둔다(코퍼스가 AI/LLM 기술 문서라 영어 용어가 흔하다).
# 위에서 아래로 우선순위가 높다(먼저 맞은 패턴을 택한다).
#
# 순서가 중요하다. 한국어 조사 '와/과'는 'A와 B'(연결)에도, '주제와 트렌드'(나열)에도
# 똑같이 쓰여 path 신호로는 너무 헐겁다. 그래서 더 또렷한 의도 신호(memory·global·community)를
# 먼저 거르고, 애매한 연결 조사는 path 의 마지막 보루로만 남긴다. 이 한계 자체가
# "규칙 기반 라우터는 곧 한계에 부딪힌다 → Phase 7 LLM Router 로 간다"의 산 증거다.
RULES: list[tuple[str, list[str]]] = [
    # memory — 후속·맥락 의존 신호. 가장 먼저 거른다(멀티턴이면 다른 패턴과 겹쳐도 memory 우선).
    ("memory", ["아까", "방금", "이전 답", "앞에서", "그거 말고", "후속", "다시 말해",
                "follow up", "previous", "earlier"]),
    # global — 전체·요약·트렌드·핵심 조망. '와/과'보다 또렷한 신호라 path 보다 위에 둔다.
    ("global", ["전체", "전반", "핵심 주제", "핵심 흐름", "트렌드", "요약", "정리하면",
                "한눈에", "큰 그림", "overall", "summary", "trend", "themes", "landscape"]),
    # community — 묶음·분야 구획·그룹
    ("community", ["어떤 그룹", "어떤 묶음", "분야로 나", "군집", "클러스터", "카테고리로",
                   "cluster", "community", "grouping", "categories"]),
    # path — 두 대상의 연결·경로·관계 추론. 명시적 연결 표현을 먼저 보고,
    # 헐거운 조사 '와/과'는 맨 끝에 둬 다른 패턴이 다 빗나갔을 때만 잡게 한다.
    ("path", ["어떻게 연결", "어떻게 이어", "관계가", "사이의", "사이를", "경로",
              "연결되", "이어지", " vs ", "between", "path", "connect", "related to",
              "와 ", "과 "]),
    # local — 단일 엔티티 정의·속성·직접 이웃
    ("local", ["무엇", "뭐야", "뭔가", "정의", "어떤 것", "속성", "특징", "누가 만들",
               "what is", "define", "who made", "properties of"]),
]

# 어디에도 안 걸리면 떨어지는 기본값. 가장 일반적인 단일 엔티티 조회로 본다.
DEFAULT_KEY = "local"


def route(question: str) -> tuple[str, str]:
    """질문을 패턴 키로 라우팅하고, 매칭 근거가 된 신호어도 돌려준다.

    규칙은 RULES 순서대로 검사하고, 먼저 맞은 패턴을 택한다(위쪽 우선).
    매칭은 단순 부분 문자열 포함(대소문자 무시)이다.
    """
    low = question.lower()
    for key, signals in RULES:
        for sig in signals:
            if sig.strip().lower() in low:
                return key, sig.strip()
    return DEFAULT_KEY, "(기본값 — 매칭 신호어 없음)"


def explain(question: str) -> str:
    """질문 한 개를 분류해 '질문 → 패턴 → LightRAG 모드 → 근거'를 한 줄로 만든다."""
    key, signal = route(question)
    p = PATTERNS[key]
    return (
        f"  Q: {question}\n"
        f"     → 패턴: {key:<9} | LightRAG 모드: {p.lightrag_mode:<6} | 근거 신호: '{signal}'\n"
        f"       직관: {p.intuition}\n"
        f"       메우는 RAG 실패: {p.fixes}"
    )


# 내장 예시 질문 — 5패턴을 골고루 자극하도록 골랐다(Golden Question 의 축소판).
SAMPLE_QUESTIONS: list[str] = [
    "RAG는 무엇이고 어떤 속성을 가지나?",                       # local
    "RAG와 GraphRAG는 어떻게 연결되는가?",                      # path
    "이 코퍼스 전체에서 핵심 주제와 트렌드는 무엇인가?",        # global
    "검색 기법들은 어떤 그룹(클러스터)으로 나뉘나?",            # community
    "아까 그거 말고 다른 GraphRAG 프레임워크는 없나?",         # memory
    "LightRAG는 누가 만들었나?",                                 # local
]


def main(argv: list[str]) -> None:
    print("=" * 72)
    print("GraphRAG Method Map — 질문 → 검색 패턴 → LightRAG 모드 라우팅 데모")
    print("  (규칙 기반 휴리스틱. 실제로는 Phase 7 에서 LLM Router 로 대체)")
    print("=" * 72)

    questions = argv[1:] if len(argv) > 1 else SAMPLE_QUESTIONS
    for q in questions:
        print(explain(q))
        print("-" * 72)

    print("\n[패턴 ↔ LightRAG 모드 요약]")
    for key, p in PATTERNS.items():
        print(f"  {key:<9} → {p.lightrag_mode}")


if __name__ == "__main__":
    main(sys.argv)
