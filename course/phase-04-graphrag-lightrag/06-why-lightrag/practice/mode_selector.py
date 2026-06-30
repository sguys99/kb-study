"""질문 type → LightRAG 권장 모드 선택기 (키·네트워크 없이 결정론적).

전제: 외부 의존 없음. 표준 라이브러리만. 과금 0.
      4.5의 골든 질문 type 분류(simple-fact / multi-hop / global-summary)와
      호환되는 작은 예시 질문셋을 들고, 두 가지 방식으로 모드를 고른다.
        (1) type이 이미 라벨돼 있으면 type → 모드 매핑으로 결정(권장 경로).
        (2) type 라벨이 없으면 간단 휴리스틱(키워드)으로 type을 추정한 뒤 매핑.

실행:
    python3 mode_selector.py
"""

# 4.5에서 갈린 결론을 그대로 규칙으로 굳힌다.
#   simple-fact   → naive   (Vector-only가 만점이던 자리)
#   multi-hop     → local    (Local·Path가 1.000이던 자리)
#   global-summary→ global   (Community 요약이 1.000이던 자리)
# type을 모르거나 섞였다고 보면 mix(기본·권장)로 떨군다.
TYPE_TO_MODE = {
    "simple-fact": "naive",
    "multi-hop": "local",
    "global-summary": "global",
}
FALLBACK_MODE = "mix"  # type을 못 가리거나 섞이면 가장 견고한 기본으로

# 휴리스틱용 약한 신호. 정밀한 분류기가 아니라 "라벨이 없을 때만" 쓰는 보조 수단이다.
_MULTIHOP_HINTS = ("어떻게 이어", "관계", "거쳐", "사이", "연결", "통해 ")
_GLOBAL_HINTS = ("전체", "전반", "요약", "공통", "트렌드", "한눈에", "정리해")


def select_mode_by_type(qtype: str) -> str:
    """질문 type 라벨로 모드를 고른다. 라벨이 표에 없으면 mix로."""
    return TYPE_TO_MODE.get(qtype, FALLBACK_MODE)


def guess_type(question: str) -> str:
    """type 라벨이 없을 때 쓰는 간단 휴리스틱. 약한 신호로만 추정한다."""
    q = question
    if any(h in q for h in _GLOBAL_HINTS):
        return "global-summary"
    if any(h in q for h in _MULTIHOP_HINTS):
        return "multi-hop"
    return "simple-fact"


def select_mode(question: str, qtype: str | None = None) -> tuple[str, str]:
    """(추정/주어진 type, 권장 모드)를 돌려준다.

    qtype이 주어지면 그대로 매핑(권장 경로). 없으면 휴리스틱으로 추정한 뒤 매핑.
    """
    resolved = qtype if qtype else guess_type(question)
    return resolved, select_mode_by_type(resolved)


# 4.5 골든셋과 같은 type 체계를 따르는 작은 예시 질문셋(type마다 2개).
# 첫 묶음은 type 라벨이 있고, 마지막 2개는 라벨 없이 휴리스틱 경로를 보여 준다.
SAMPLE_QUESTIONS = [
    ("VoyageAI의 기본 임베딩 모델 이름은?", "simple-fact"),
    ("LightRAG의 기본·권장 쿼리 모드는?", "simple-fact"),
    ("Neo4j와 RAG는 어떻게 이어지나?", "multi-hop"),
    ("Leiden 커뮤니티 탐지가 Global 검색과 어떤 관계인가?", "multi-hop"),
    ("이 코퍼스의 GraphRAG 연구 흐름을 전체 요약해줘.", "global-summary"),
    ("RAG 프레임워크들의 공통 설계를 한눈에 정리해줘.", "global-summary"),
    ("LightRAG와 Microsoft GraphRAG는 어떻게 이어지나?", None),  # 휴리스틱 경로
    ("Phase 4 전체를 요약해줘.", None),                         # 휴리스틱 경로
]


def main():
    print("=== 질문 type → LightRAG 권장 모드 선택기 ===\n")
    print(f"매핑 규칙: {TYPE_TO_MODE}  (그 외/섞임 → {FALLBACK_MODE})\n")

    header = f"{'질문':52}  {'type':14}  {'mode':7}  경로"
    print(header)
    print("-" * len(header))
    for question, qtype in SAMPLE_QUESTIONS:
        resolved, mode = select_mode(question, qtype)
        path = "label" if qtype else "heuristic"
        q_disp = (question[:50] + "…") if len(question) > 51 else question
        print(f"{q_disp:52}  {resolved:14}  {mode:7}  {path}")

    print()
    print("[핵심] type이 라벨돼 있으면 simple-fact→naive, multi-hop→local, "
          "global-summary→global으로 결정론적으로 떨어진다.")
    print("       라벨이 없으면 휴리스틱으로 type을 추정한 뒤 같은 매핑을 쓴다.")
    print("       어떤 type인지 가리기 어려우면 mix(기본·권장)가 가장 안전하다.")


if __name__ == "__main__":
    main()
