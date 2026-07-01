"""tools.py — Tool Contract 레지스트리. 도구 = 이름·설명·입력 스키마·실행 함수.

Anthropic tool-use 형식을 그대로 쓴다:
  - 요청에 넘길 스펙: {name, description, input_schema(JSON Schema)}
  - 모델이 tool_use 블록으로 도구를 호출하면, 이름으로 실행 함수를 찾아 돌린다.
  - 실행 결과(문자열)를 tool_result 블록으로 되돌린다.

이 토픽은 도구가 docs_search 하나뿐이다. 02 에서 graph_query 가 '같은 레지스트리'에
같은 규약으로 등록된다. 그래서 등록 방식을 처음부터 확장 가능하게 만든다.

전제: 표준 라이브러리 + docs_search 모듈. API 키 불필요.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable

from docs_search import docs_search

# ── docs_search 의 입력 스키마(JSON Schema) ────────────────────────────────
# LLM 은 이 description·schema 만 보고 '언제·어떻게' 도구를 부를지 판단한다.
# 그래서 description 은 사람이 아니라 '모델이 읽는 사용 설명서'라고 생각하고 쓴다.
DOCS_SEARCH_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "검색할 자연어 질의. 문서에서 근거 청크를 찾기 위한 핵심 키워드를 담는다.",
        },
        "k": {
            "type": "integer",
            "description": "돌려받을 상위 청크 수. 기본 3.",
            "default": 3,
        },
    },
    "required": ["query"],
}


@dataclass
class Tool:
    """Tool Contract 한 건. 스펙(모델에 노출) + 실행 함수(로컬)."""

    name: str
    description: str
    input_schema: dict
    fn: Callable[..., object]

    def to_spec(self) -> dict:
        """Anthropic messages.create 의 tools= 에 넣을 스펙."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }

    def run(self, tool_input: dict) -> str:
        """도구를 실행하고 tool_result 에 넣을 '문자열'로 직렬화한다.

        출력 계약: JSON 문자열. 모델이 파싱하기 쉽고, 인용 필드(chunk_id 등)를 보존한다.
        """
        result = self.fn(**tool_input)
        return json.dumps(result, ensure_ascii=False, indent=2)


def _run_docs_search(query: str, k: int = 3) -> list[dict]:
    """docs_search 도구의 실행 어댑터. 계약(입력 query·k → 인용 리스트)을 고정한다."""
    return docs_search(query=query, k=k)


class ToolRegistry:
    """이름 → Tool 매핑. specs() 로 모델에 넘기고, dispatch() 로 실행한다."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def specs(self) -> list[dict]:
        """messages.create(tools=...) 에 넣을 전체 스펙 리스트."""
        return [t.to_spec() for t in self._tools.values()]

    def dispatch(self, name: str, tool_input: dict) -> str:
        """모델이 호출한 도구를 이름으로 찾아 실행. 없으면 에러 문자열(모델이 복구하도록)."""
        tool = self._tools.get(name)
        if tool is None:
            return json.dumps({"error": f"unknown tool: {name}"}, ensure_ascii=False)
        return tool.run(tool_input)


def build_registry() -> ToolRegistry:
    """이 토픽의 도구 레지스트리를 만든다. 지금은 docs_search 하나."""
    reg = ToolRegistry()
    reg.register(
        Tool(
            name="docs_search",
            description=(
                "문서 코퍼스에서 질의와 관련된 근거 청크를 검색한다. "
                "사실·정의·비교를 물어보는 질문에 답하기 전 반드시 이 도구로 근거를 찾아라. "
                "결과의 각 항목은 chunk_id·source_id·text 를 포함하므로, 답변에 [chunk_id] 로 인용하라."
            ),
            input_schema=DOCS_SEARCH_SCHEMA,
            fn=_run_docs_search,
        )
    )
    return reg


if __name__ == "__main__":
    # 빠른 자기점검: 스펙 출력 + docs_search 를 레지스트리로 직접 실행.
    reg = build_registry()
    print("=== 등록된 도구 스펙(Anthropic tools 형식) ===")
    print(json.dumps(reg.specs(), ensure_ascii=False, indent=2))
    print("\n=== dispatch 테스트 ===")
    out = reg.dispatch("docs_search", {"query": "Self-RAG 는 언제 검색하나", "k": 2})
    print(out)
