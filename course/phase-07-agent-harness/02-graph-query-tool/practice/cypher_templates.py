"""cypher_templates.py — 파라미터화된, 미리 검증된 Cypher 템플릿 레지스트리.

왜 템플릿인가: text2cypher 는 유연하지만 위험하다(쓰기·주입·잘못된 스키마).
템플릿은 '사람이 미리 검증한 읽기 질의'에 파라미터만 꽂는다. LLM 은 템플릿 이름과
파라미터만 고르므로, 생성 자유도가 없다 = 가장 안전하다. graph_query 의 기본 권장 방식.

각 템플릿은:
  - name : LLM 이 고를 식별자
  - description : 언제 쓰는지(모델이 읽는 설명)
  - params : 필요한 파라미터 이름과 설명
  - cypher : 실제 Cypher(파라미터는 $name 바인딩. 문자열 포매팅 금지 = 주입 차단)
  - mock_fn : Neo4j 없이 돌릴 때 MockGraph 로 같은 의미를 실행하는 함수

모든 Cypher 는 읽기 전용(MATCH/RETURN 만). 쓰기 키워드가 없음을 로드 시 assert 로 강제한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from graph_backend import MockGraph

# 읽기 전용 가드(1차): 템플릿 Cypher 에 아래 키워드가 있으면 로드 자체를 거부한다.
# 이건 '사람이 미리 검증한' 템플릿을 위한 최소 안전장치다.
# text2cypher(모델 생성 문자열)를 막는 본격 Safety Guard 는 03 에서 만든다.
_WRITE_KEYWORDS = (
    "CREATE", "DELETE", "SET ", "MERGE", "REMOVE", "DROP", "DETACH",
    "CALL {", "LOAD CSV", "FOREACH",
)


@dataclass
class CypherTemplate:
    name: str
    description: str
    params: dict[str, str]  # param_name -> 설명
    cypher: str
    mock_fn: Callable[[MockGraph, dict], list[dict]]

    def __post_init__(self) -> None:
        upper = self.cypher.upper()
        for kw in _WRITE_KEYWORDS:
            assert kw not in upper, f"템플릿 {self.name} 에 쓰기 키워드 발견: {kw!r}"


# ── 템플릿 1: 엔티티 X 의 이웃 ──────────────────────────────────────────────
# $name 으로 바인딩(문자열 포매팅 아님). 방향 무관 1-홉 이웃 + 관계 타입.
_NEIGHBORS_CYPHER = """
MATCH (x {name: $name})-[r]-(nb)
RETURN x.name AS entity,
       type(r) AS relation,
       nb.name AS neighbor,
       labels(nb)[0] AS neighbor_label,
       elementId(nb) AS source
LIMIT $limit
""".strip()


def _mock_neighbors(g: MockGraph, params: dict) -> list[dict]:
    return g.neighbors(params["name"], limit=int(params.get("limit", 10)))


# ── 템플릿 2: X 와 Y 사이 경로 ─────────────────────────────────────────────
# shortestPath 로 두 노드 사이 최단 경로. 멀티홉 질문의 핵심 패턴.
# 주의: Cypher 는 가변 길이 경로의 상한 [*..N] 을 $파라미터로 바인딩할 수 없다(리터럴만 허용).
# 그래서 상한은 템플릿에 리터럴로 고정한다(여기선 4홉). 이름만 $source/$target 으로 바인딩.
# max_hops 를 바꾸고 싶으면 템플릿을 하나 더 만들어 화이트리스트에 추가한다.
_PATH_CYPHER = """
MATCH (a {name: $source}), (b {name: $target}),
      p = shortestPath((a)-[*..4]-(b))
RETURN [n IN nodes(p) | n.name] AS path_nodes,
       [r IN relationships(p) | type(r)] AS path_relations,
       elementId(b) AS source
""".strip()


def _mock_path(g: MockGraph, params: dict) -> list[dict]:
    return g.path_between(
        params["source"], params["target"], max_hops=int(params.get("max_hops", 4))
    )


class TemplateRegistry:
    """이름 → CypherTemplate. graph_query 의 template 백엔드가 여기서 고른다."""

    def __init__(self) -> None:
        self._templates: dict[str, CypherTemplate] = {}

    def register(self, t: CypherTemplate) -> None:
        self._templates[t.name] = t

    def get(self, name: str) -> CypherTemplate | None:
        return self._templates.get(name)

    def catalog(self) -> list[dict]:
        """LLM 에 노출할 템플릿 목록(이름·설명·파라미터). graph_query description 에 넣는다."""
        return [
            {"name": t.name, "description": t.description, "params": t.params}
            for t in self._templates.values()
        ]


def build_template_registry() -> TemplateRegistry:
    reg = TemplateRegistry()
    reg.register(
        CypherTemplate(
            name="neighbors",
            description="엔티티 하나의 1-홉 이웃과 관계를 조회한다. 'X 는 무엇과 연결돼 있나' 류 질문.",
            params={"name": "중심 엔티티 이름(예: 'Self-RAG')", "limit": "최대 이웃 수(기본 10)"},
            cypher=_NEIGHBORS_CYPHER,
            mock_fn=_mock_neighbors,
        )
    )
    reg.register(
        CypherTemplate(
            name="path_between",
            description="두 엔티티 사이 최단 경로를 조회한다. 'X 와 Y 는 어떻게 이어지나' 류 멀티홉 질문.",
            params={
                "source": "시작 엔티티 이름",
                "target": "도착 엔티티 이름",
                "max_hops": "최대 홉 수(기본 4)",
            },
            cypher=_PATH_CYPHER,
            mock_fn=_mock_path,
        )
    )
    return reg


if __name__ == "__main__":
    import json

    reg = build_template_registry()
    print("=== 템플릿 카탈로그(LLM 에 노출) ===")
    print(json.dumps(reg.catalog(), ensure_ascii=False, indent=2))
    print("\n=== neighbors 템플릿 Cypher ===")
    print(reg.get("neighbors").cypher)
