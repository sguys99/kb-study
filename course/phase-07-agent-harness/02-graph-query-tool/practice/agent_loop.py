"""agent_loop.py — 도구 2개(docs_search + graph_query)를 쓰는 tool-use 루프.

01 의 agent_loop 를 그대로 잇되, 두 가지만 바꾼다:
  1) 레지스트리를 build_registry_with_graph() 로 교체 → 도구가 2개.
  2) MockClient 가 질문 종류에 따라 docs_search / graph_query 를 골라 부르게 확장.

루프 뼈대(01 과 동일):
  while True:
      resp = create(..., tools=registry.specs())
      messages += assistant
      if stop_reason != "tool_use": break
      for tool_use: result = registry.dispatch(name, input)
      messages += tool_result

핵심은 '도구가 늘어도 하니스 골격은 안 바뀐다'는 것이다. 모델(또는 mock)이
description·schema 만 보고 어떤 도구를 부를지 스스로 정한다. 순서를 코드가 고정하지 않는다.

두 경로:
  1) 기본 — ANTHROPIC_API_KEY 로 Claude tool-use 루프(도구 2개).
  2) 폴백(비용 0) — 키 없으면 MockClient 로 같은 루프. 관계·경로 질문이면 graph_query,
     그 밖이면 docs_search 를 부른다(규칙 기반, 실제 추론 아님).

전제: 기본 경로만 ANTHROPIC_API_KEY + anthropic. 폴백·template·mock 그래프는 표준 라이브러리만.
사용: python agent_loop.py "질문"
"""

from __future__ import annotations

import json
import os
import sys

from register_graph_tools import build_registry_with_graph

LLM_MODEL = os.environ.get("HARNESS_MODEL", "claude-sonnet-4-6")

SYSTEM = (
    "너는 문서 + 지식그래프 기반 리서치 어시스턴트다. 도구가 둘이다. "
    "정의·사실·비교는 docs_search 로 근거를 찾는다. "
    "엔티티 사이 '관계·연결·경로'를 묻는 질문은 graph_query 를 쓴다("
    "가능하면 안전한 template 을 먼저, 안 되면 text2cypher, 요약은 lightrag). "
    "필요하면 두 도구를 함께 쓰고, 멀티홉이면 반복 호출하라. "
    "최종 답변의 각 주장 끝에 근거의 [chunk_id] 또는 [source] 를 인용한다. "
    "근거가 없으면 모른다고 답한다. 한국어로 3~5문장으로 간결히."
)

MAX_TURNS = 6


def _make_client():
    if os.environ.get("ANTHROPIC_API_KEY"):
        import anthropic

        return anthropic.Anthropic(), "claude"
    return MockClient(), "mock"


class MockClient:
    """도구 2개를 쓰는 루프를 API 없이 검증하는 가짜 클라이언트.

    규칙(실제 추론 아님):
      - 아직 도구를 안 썼으면, 질문에 '관계/연결/경로/사이' 가 있으면 graph_query(template),
        아니면 docs_search 를 부른다.
      - tool_result 가 이미 있으면 그 근거로 인용 답변을 만든다.
    """

    class _Block:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    class _Resp:
        def __init__(self, content, stop_reason):
            self.content = content
            self.stop_reason = stop_reason

    _GRAPH_HINTS = ("관계", "연결", "경로", "사이", "이웃", "어떻게 이어")

    def messages_create_like(self, messages: list[dict]) -> "MockClient._Resp":
        has_tool_result = any(
            isinstance(m.get("content"), list)
            and any(b.get("type") == "tool_result" for b in m["content"])
            for m in messages
        )
        user_q = self._first_user_text(messages)
        if not has_tool_result:
            if any(h in user_q for h in self._GRAPH_HINTS):
                # 관계·경로 질문 → graph_query(template). 이름을 못 뽑으면 Self-RAG 로.
                names = self._extract_names(user_q)
                if len(names) >= 2:
                    tinput = {
                        "method": "template",
                        "template": "path_between",
                        "params": {"source": names[0], "target": names[1]},
                    }
                else:
                    tinput = {
                        "method": "template",
                        "template": "neighbors",
                        "params": {"name": names[0] if names else "Self-RAG"},
                    }
                block = self._Block(type="tool_use", id="mock-g1", name="graph_query", input=tinput)
                return self._Resp([block], "tool_use")
            block = self._Block(
                type="tool_use", id="mock-d1", name="docs_search",
                input={"query": user_q, "k": 3},
            )
            return self._Resp([block], "tool_use")

        sources = self._collect_sources(messages)
        cite = " ".join(f"[{s}]" for s in sources[:3]) or "[근거 없음]"
        text = self._Block(
            type="text",
            text=f"'{user_q}' 에 대한 답: 검색·그래프 근거를 종합하면 아래와 같다. {cite}",
        )
        return self._Resp([text], "end_turn")

    @staticmethod
    def _first_user_text(messages: list[dict]) -> str:
        for m in messages:
            if m["role"] == "user" and isinstance(m["content"], str):
                return m["content"]
        return ""

    @staticmethod
    def _extract_names(q: str) -> list[str]:
        # 알려진 엔티티 이름을 질문에서 찾아낸다(mock 편의).
        known = ["Self-RAG", "CRAG", "Adaptive-RAG", "Agentic RAG", "GraphRAG",
                 "LightRAG", "Tool Use"]
        return [n for n in known if n.lower() in q.lower()]

    @staticmethod
    def _collect_sources(messages: list[dict]) -> list[str]:
        """tool_result 에서 인용 식별자(chunk_id 또는 source)를 모은다."""
        out: list[str] = []
        for m in messages:
            if not isinstance(m.get("content"), list):
                continue
            for b in m["content"]:
                if b.get("type") != "tool_result":
                    continue
                try:
                    payload = json.loads(b["content"])
                except Exception:
                    continue
                out.extend(_ids_from_payload(payload))
        return out


def _ids_from_payload(payload) -> list[str]:
    """docs_search(list of chunk) 와 graph_query(dict with rows) 둘 다에서 인용 식별자 추출."""
    ids: list[str] = []
    rows = payload.get("rows") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return ids
    for r in rows:
        if not isinstance(r, dict):
            continue
        if "chunk_id" in r:
            ids.append(r["chunk_id"])
        elif "source" in r:
            ids.append(r["source"])
    return ids


def _create(client, backend, registry, messages):
    if backend == "claude":
        resp = client.messages.create(
            model=LLM_MODEL, max_tokens=1024, system=SYSTEM,
            tools=registry.specs(), messages=messages,
        )
        return resp.content, resp.stop_reason
    resp = client.messages_create_like(messages)
    return resp.content, resp.stop_reason


def run_agent(question: str, *, verbose: bool = True) -> dict:
    client, backend = _make_client()
    registry = build_registry_with_graph()
    messages: list[dict] = [{"role": "user", "content": question}]
    tool_calls: list[str] = []

    if verbose:
        print(f"[agent] backend={backend} model={LLM_MODEL if backend == 'claude' else 'mock'}")
        print(f"[agent] tools={[s['name'] for s in registry.specs()]}")
        print(f"[agent] question={question!r}\n")

    for turn in range(1, MAX_TURNS + 1):
        content, stop_reason = _create(client, backend, registry, messages)
        messages.append({"role": "assistant", "content": _as_api_content(content, backend)})

        if stop_reason != "tool_use":
            final = _extract_text(content)
            if verbose:
                print(f"[turn {turn}] 최종 답변(stop_reason={stop_reason})\n")
                print(final)
            return {"answer": final, "tool_calls": tool_calls, "turns": turn, "backend": backend}

        tool_results = []
        for block in content:
            if _btype(block) != "tool_use":
                continue
            name, tinput, tid = block.name, block.input, block.id
            tool_calls.append(name)
            if verbose:
                print(f"[turn {turn}] tool_use → {name}({json.dumps(tinput, ensure_ascii=False)})")
            result_str = registry.dispatch(name, tinput)
            tool_results.append({"type": "tool_result", "tool_use_id": tid, "content": result_str})
        messages.append({"role": "user", "content": tool_results})

    return {"answer": "(중단) 최대 턴 수 초과", "tool_calls": tool_calls,
            "turns": MAX_TURNS, "backend": backend}


def _btype(block) -> str:
    return getattr(block, "type", None) or (block.get("type") if isinstance(block, dict) else None)


def _extract_text(content) -> str:
    parts = []
    for b in content:
        if _btype(b) == "text":
            parts.append(getattr(b, "text", "") or (b.get("text", "") if isinstance(b, dict) else ""))
    return "".join(parts).strip()


def _as_api_content(content, backend: str):
    if backend == "claude":
        return content
    out = []
    for b in content:
        if _btype(b) == "tool_use":
            out.append({"type": "tool_use", "id": b.id, "name": b.name, "input": b.input})
        elif _btype(b) == "text":
            out.append({"type": "text", "text": b.text})
    return out


if __name__ == "__main__":
    q = sys.argv[1] if len(sys.argv) > 1 else "LightRAG 와 Tool Use 는 어떻게 이어지나?"
    result = run_agent(q)
    print("\n--- 요약 ---")
    print(f"backend    : {result['backend']}")
    print(f"tool_calls : {result['tool_calls']}")
    print(f"turns      : {result['turns']}")
