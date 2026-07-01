"""register_all_tools.py — 01 Registry + 02 graph_query(안전판) + 03 ontology_check.

도구가 3개로 확장된다: docs_search + graph_query + ontology_check.
새 레지스트리를 만들지 않는다. 01 의 Tool/ToolRegistry, 02 의 등록 규약을 그대로 잇는다.

바뀌는 것은 두 가지뿐:
  1) graph_query 의 실행 함수를 03 의 안전판(graph_query_safe.graph_query)으로 교체.
     → text2cypher 가 Safety Guard 를 반드시 통과한 뒤에만 실행된다.
  2) ontology_check 를 세 번째 도구로 추가 등록.

전제: 01·02 practice 를 import 경로에 올린다. 03 의 graph_query_safe·ontology_check 사용.
  표준 라이브러리 + Pydantic·PyYAML(ontology). API 키·Neo4j 불필요(mock 기본).
"""

from __future__ import annotations

import json
import os
import sys


def _attach(*rel_parts: str) -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    p = os.path.normpath(os.path.join(here, *rel_parts))
    if os.path.isdir(p) and p not in sys.path:
        sys.path.insert(0, p)


# 01(Tool/ToolRegistry, docs_search), 02(GRAPH_QUERY_SCHEMA·description)를 재사용.
_attach("..", "..", "01-agent-harness-minimal", "practice")
_attach("..", "..", "02-graph-query-tool", "practice")

from tools import Tool, build_registry  # type: ignore  # noqa: E402
from register_graph_tools import GRAPH_QUERY_SCHEMA, _graph_query_description  # type: ignore  # noqa: E402

# 03: graph_query 안전판 + ontology_check 도구.
from graph_query_safe import graph_query as graph_query_safe  # noqa: E402
from ontology_check import ontology_check  # noqa: E402


def _run_graph_query_safe(
    method: str = "template",
    template: str | None = None,
    params: dict | None = None,
    question: str | None = None,
    mode: str = "hybrid",
) -> dict:
    """graph_query 실행 어댑터 — 02 스키마 그대로, 실행만 03 안전판으로."""
    return graph_query_safe(
        method=method, template=template, params=params, question=question, mode=mode
    )


# ontology_check 의 입력 스키마(JSON Schema). cypher/triples 중 최소 하나.
ONTOLOGY_CHECK_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "cypher": {
            "type": "string",
            "description": "검사할 Cypher 문자열. 여기 등장하는 라벨(:Method)·관계타입([:USES])이 "
                           "허용 온톨로지에 있는지 본다.",
        },
        "triples": {
            "type": "array",
            "description": "검사할 (subject_label, relation, object_label) 삼중항 리스트. "
                           "관계 존재 + 방향(domain/range)까지 검증한다.",
            "items": {
                "type": "object",
                "properties": {
                    "subject": {"type": "string", "description": "주어 노드 라벨(예: Method)"},
                    "relation": {"type": "string", "description": "관계 타입(예: USES)"},
                    "object": {"type": "string", "description": "목적어 노드 라벨(예: Component)"},
                },
                "required": ["subject", "relation", "object"],
            },
        },
    },
}

ONTOLOGY_CHECK_DESCRIPTION = (
    "지식그래프 스키마(허용 온톨로지) 검증 도구. 생성한 Cypher 나 답변이 참조하는 "
    "라벨·관계타입·방향이 스키마상 타당한지 확인한다. "
    "graph_query(text2cypher) 로 만든 질의를 실행하기 전, 또는 답변이 'A 는 B 를 R 한다'고 "
    "주장할 때 그 관계가 온톨로지에 맞는지 이 도구로 검사하라. "
    "입력은 cypher(문자열) 또는 triples([{subject,relation,object}]) 중 최소 하나. "
    "결과 violations 가 비어 있지 않으면(ok=false) 스키마에 없는 라벨/관계이거나 방향이 어긋난 것이다."
)


def build_registry_full():
    """01(docs_search) + 02 graph_query(안전판) + 03 ontology_check. 에이전트가 도구 3개를 갖는다."""
    reg = build_registry()  # 01: docs_search 등록됨.

    # graph_query — 02 스키마·설명 그대로, 실행만 안전판으로.
    reg.register(
        Tool(
            name="graph_query",
            description=_graph_query_description(),
            input_schema=GRAPH_QUERY_SCHEMA,
            fn=_run_graph_query_safe,
        )
    )

    # ontology_check — 세 번째 도구.
    reg.register(
        Tool(
            name="ontology_check",
            description=ONTOLOGY_CHECK_DESCRIPTION,
            input_schema=ONTOLOGY_CHECK_SCHEMA,
            fn=ontology_check,
        )
    )
    return reg


if __name__ == "__main__":
    reg = build_registry_full()
    print("=== 등록된 도구 이름(3개여야 한다) ===")
    print([spec["name"] for spec in reg.specs()])

    print("\n=== graph_query(text2cypher) — Safety Guard 통과 후 실행 ===")
    print(reg.dispatch("graph_query", {"method": "text2cypher", "question": "'CRAG' 는 무엇과 연결돼 있나?"}))

    print("\n=== ontology_check — 위반 Cypher 검사 ===")
    print(reg.dispatch(
        "ontology_check",
        {"cypher": "MATCH (m:Method)-[:MENTIONS]->(d:Dataset) RETURN m,d LIMIT 10"},
    ))

    # 자체검증
    names = [s["name"] for s in reg.specs()]
    assert names == ["docs_search", "graph_query", "ontology_check"], names
    out = json.loads(reg.dispatch(
        "ontology_check", {"cypher": "MATCH (m:Method)-[:MENTIONS]->(d:Dataset) RETURN m LIMIT 5"}))
    assert out["ok"] is False
    print("\n[assert] 도구 3개 등록 + ontology_check 위반 탐지 통과")
