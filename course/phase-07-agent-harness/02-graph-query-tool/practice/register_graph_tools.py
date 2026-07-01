"""register_graph_tools.py — 01 의 ToolRegistry 에 graph_query 를 '추가 등록'한다.

핵심: 01 에서 만든 Tool/ToolRegistry 구조를 그대로 재사용한다. 새로 만들지 않는다.
01 의 build_registry() 로 docs_search 가 등록된 레지스트리를 받아, graph_query 를 한 건 더 얹는다.
그 결과 에이전트는 도구 2개(docs_search + graph_query)를 갖는다.

graph_query 의 input_schema 는 method 로 세 백엔드를 분기하도록 설계한다.
description 은 '모델이 읽는 사용 설명서'다 — 언제 template/text2cypher/lightrag 를 쓸지 적는다.

전제: 01-agent-harness-minimal/practice 를 import 경로에 올린다(아래 _attach_phase7_01).
  표준 라이브러리 + 같은 practice 폴더 모듈만 필요. API 키 불필요(mock 기본).
"""

from __future__ import annotations

import json
import os
import sys


def _attach_phase7_01() -> None:
    """01 practice 폴더를 sys.path 에 올려 tools.py(Tool/ToolRegistry)를 import 가능하게 한다."""
    here = os.path.dirname(os.path.abspath(__file__))
    p01 = os.path.normpath(os.path.join(here, "..", "..", "01-agent-harness-minimal", "practice"))
    if os.path.isdir(p01) and p01 not in sys.path:
        sys.path.insert(0, p01)


_attach_phase7_01()

# 01 의 계약을 그대로 가져온다(재정의하지 않는다).
from tools import Tool, build_registry  # type: ignore  # noqa: E402

from graph_query import graph_query, template_catalog  # noqa: E402


def _graph_query_description() -> str:
    """graph_query 도구 설명. 템플릿 카탈로그를 설명에 녹여 모델이 이름을 고르게 한다."""
    cat = template_catalog()
    tmpl_lines = "; ".join(f"{t['name']}({', '.join(t['params'])})" for t in cat)
    return (
        "지식그래프(KG)에 질의해 엔티티 이웃·경로·그래프 기반 답을 얻는다. "
        "엔티티 사이 관계나 멀티홉 연결을 묻는 질문은 docs_search 대신 이 도구를 써라. "
        "method 로 세 방식 중 하나를 고른다: "
        "(1) template — 미리 검증된 안전한 질의. 가장 먼저 고려한다. "
        f"사용 가능한 template: {tmpl_lines}. template 이름과 params 를 넘겨라. "
        "(2) text2cypher — 위 템플릿으로 안 되는 자유 질의. question 을 넘기면 Cypher 를 생성해 실행한다. "
        "(3) lightrag — 요약·전역 관점이 필요하면 question 과 mode(naive/local/global/hybrid/mix)를 넘겨라. "
        "결과 rows 의 각 항목에는 근거 식별자 source 가 있으니, 답변에 [source] 로 인용하라."
    )


# graph_query 의 입력 스키마(JSON Schema). method 로 분기하되, 세 경로의 파라미터를 모두 노출한다.
GRAPH_QUERY_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "method": {
            "type": "string",
            "enum": ["template", "text2cypher", "lightrag"],
            "description": "질의 방식. 안전한 template 을 우선 고려.",
        },
        "template": {
            "type": "string",
            "description": "method=template 일 때 템플릿 이름(예: neighbors, path_between).",
        },
        "params": {
            "type": "object",
            "description": "method=template 의 파라미터. 예: {\"name\": \"Self-RAG\"} 또는 "
                           "{\"source\": \"LightRAG\", \"target\": \"Tool Use\"}.",
        },
        "question": {
            "type": "string",
            "description": "method=text2cypher/lightrag 일 때 자연어 질문.",
        },
        "mode": {
            "type": "string",
            "enum": ["naive", "local", "global", "hybrid", "mix"],
            "description": "method=lightrag 일 때 LightRAG 검색 모드. 기본 hybrid.",
        },
    },
    "required": ["method"],
}


def _run_graph_query(
    method: str = "template",
    template: str | None = None,
    params: dict | None = None,
    question: str | None = None,
    mode: str = "hybrid",
) -> dict:
    """graph_query 도구의 실행 어댑터. 계약을 graph_query() 본체로 넘긴다."""
    return graph_query(
        method=method, template=template, params=params, question=question, mode=mode
    )


def build_registry_with_graph():
    """01 레지스트리(docs_search) + graph_query. 에이전트가 도구 2개를 갖게 한다."""
    reg = build_registry()  # 01 의 docs_search 가 이미 등록된 상태.
    reg.register(
        Tool(
            name="graph_query",
            description=_graph_query_description(),
            input_schema=GRAPH_QUERY_SCHEMA,
            fn=_run_graph_query,
        )
    )
    return reg


if __name__ == "__main__":
    reg = build_registry_with_graph()
    print("=== 등록된 도구 이름 ===")
    print([spec["name"] for spec in reg.specs()])

    print("\n=== graph_query dispatch: template neighbors ===")
    out = reg.dispatch(
        "graph_query",
        {"method": "template", "template": "neighbors", "params": {"name": "Self-RAG"}},
    )
    print(out)

    print("\n=== graph_query dispatch: lightrag mix ===")
    out = reg.dispatch(
        "graph_query",
        {"method": "lightrag", "question": "GraphRAG 개요", "mode": "mix"},
    )
    print(out)
