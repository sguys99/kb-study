"""LightRAG 5가지 쿼리 모드 메타 사전 + 비교표 출력.

전제: 외부 의존 없음. 표준 라이브러리만으로 키·네트워크 없이 결정론적으로 돈다.
      여기서는 LightRAG 를 실제로 설치·인덱싱하지 않는다(그건 07 토픽).
      06 은 "5모드가 각각 무엇이고, 4.2~4.5의 직접 구현과 어떻게 1:1로 대응하며,
      언제 쓰는가"를 코드로 표로 만드는 개념 토픽이다.

실행:
    python3 query_modes.py
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ModeSpec:
    """LightRAG 한 쿼리 모드의 의미·대응·사용처."""

    mode: str          # naive / local / global / hybrid / mix (영문 소문자 고정)
    meaning: str       # 모드가 검색에 무엇을 쓰는지
    maps_to: str       # 4.2~4.5에서 학습자가 직접 짠 어떤 전략에 대응하는가
    use_when: str      # 어떤 질문 type에 강한가


# 검증 결과(2026-06, context7) 그대로 반영한 5모드 메타.
# 순서는 "KG를 안 쓰는 쪽 → 점점 통합하는 쪽"으로 둔다: naive → local → global → hybrid → mix.
MODES = [
    ModeSpec(
        mode="naive",
        meaning="KG 없이 텍스트 청크 벡터검색만. 전통 RAG 그대로.",
        maps_to="4.1~4.5 Vector-only / Phase 1 Baseline(Hybrid RAG의 벡터 측)",
        use_when="simple-fact (답이 한 청크에 통째로 들어 있는 단순 사실)",
    ),
    ModeSpec(
        mode="local",
        meaning="엔티티 중심. 질문에 걸리는 엔티티의 로컬 문맥·이웃을 정밀 매칭.",
        maps_to="4.2 Local·Path Retriever",
        use_when="multi-hop (두세 엔티티를 거쳐야 답이 나오는 관계 질문)",
    ),
    ModeSpec(
        mode="global",
        meaning="커뮤니티 기반. 거시 주제·교차문서 추론을 위해 커뮤니티 요약을 모은다.",
        maps_to="4.3 Global Retriever (Leiden Community·Map-Reduce 요약)",
        use_when="global-summary (코퍼스 전체를 조망해야 하는 요약 질문)",
    ),
    ModeSpec(
        mode="hybrid",
        meaning="local + global 병합. 엔티티 정밀도와 커뮤니티 거시 시야를 함께 본다.",
        maps_to="4.4~4.5 Hybrid의 그래프 측 (local+global 결합)",
        use_when="multi-hop과 global-summary가 섞인 질문",
    ),
    ModeSpec(
        mode="mix",
        meaning="KG 검색 + vector 검색 통합(세 검색 타입 결합). reranker와 함께 권장.",
        maps_to="4.4 Vector+Graph Fusion의 완성형 (RRF·Rerank까지)",
        use_when="기본·권장 모드. type을 가리지 않고 가장 견고. naive보다 지연 약간 ↑",
    ),
]

# Core README 권장 기본 vs API 서버 무prefix 기본 — 이 뉘앙스 차이를 정확히 적어 둔다.
DEFAULT_CORE = "mix"     # LightRAG Core README 권장 기본
DEFAULT_API_SERVER = "hybrid"  # API 서버에서 쿼리 앞에 prefix가 없을 때의 기본


def _row(cells, widths):
    return "  ".join(c.ljust(w) for c, w in zip(cells, widths))


def print_table():
    cols = ["mode", "의미", "대응(직접 구현)", "언제 쓰나"]
    rows = [[m.mode, m.meaning, m.maps_to, m.use_when] for m in MODES]
    widths = [max(len(c), max(len(r[i]) for r in rows)) for i, c in enumerate(cols)]

    print("=== LightRAG 5 Query Mode 대응표 ===\n")
    print(_row(cols, widths))
    print("-" * (sum(widths) + 2 * (len(cols) - 1)))
    for r in rows:
        print(_row(r, widths))

    print()
    print(f"[기본 모드] Core README 권장 기본 = {DEFAULT_CORE}, "
          f"API 서버 무prefix 기본 = {DEFAULT_API_SERVER}")
    print("[메시지] 4.2~4.5에서 손으로 짠 vector_only/local/global/hybrid가 "
          "곧 LightRAG의 naive/local/global/hybrid 모드다.")
    print("         LightRAG는 거기에 KG+vector를 통합한 mix를 더해 다섯 모드를 "
          "한 프레임워크로 제공한다.")


if __name__ == "__main__":
    print_table()
