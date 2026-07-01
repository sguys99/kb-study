"""agent_loop.py — 최소 tool-use 루프. Phase 7 Reference Harness 의 뼈대.

핵심 구조(외우면 되는 4줄):
  while True:
      resp = client.messages.create(..., tools=registry.specs())
      messages.append(assistant 응답)
      if resp.stop_reason != "tool_use": break        # 최종 텍스트 답변
      for tool_use in resp 안의 tool_use 블록:          # 도구 실행
          result = registry.dispatch(name, input)
      messages.append(tool_result 블록들)               # 결과 붙여 재호출

Workflow 와의 차이: 여기서 '다음에 무엇을 할지(도구를 부를지·끝낼지)'를 코드가 아니라
모델이 stop_reason 으로 결정한다. 그래서 멀티홉 질문이면 도구를 여러 번 부르고,
단순 질문이면 한 번도 안 부를 수 있다. 순서를 고정하지 않는 것이 Agent 다.

두 경로:
  1) 기본 — ANTHROPIC_API_KEY 로 Claude tool-use 루프.
  2) 폴백(비용 0) — 키가 없으면 MockClient 로 '같은 루프'를 돈다.
     실제 LLM 대신 규칙으로 tool_use 를 흉내 내, API 없이도 루프·인용·최종답변을 확인한다.
     Ollama(로컬 LLM)로 바꾸려면 _make_client 만 교체하면 된다(주석 참조).

전제: 기본 경로만 ANTHROPIC_API_KEY + anthropic 필요. 폴백은 표준 라이브러리만.
사용: python agent_loop.py "질문"
"""

from __future__ import annotations

import json
import os
import sys

from tools import ToolRegistry, build_registry

# 최신 Claude 모델. 상수로 두어 교체 지점을 한 곳에 모은다.
# 예: "claude-sonnet-4-6", "claude-opus-4-8", 비용 낮추려면 "claude-haiku-4-5".
LLM_MODEL = os.environ.get("HARNESS_MODEL", "claude-sonnet-4-6")

SYSTEM = (
    "너는 문서 기반 리서치 어시스턴트다. 사실·정의·비교 질문에는 반드시 docs_search 로 "
    "근거를 먼저 찾고 답한다. 여러 개념을 비교하는 멀티홉 질문이면 필요한 만큼 검색을 반복하라. "
    "최종 답변의 각 주장 끝에 근거 청크의 [chunk_id] 를 대괄호로 인용한다. "
    "근거가 없으면 모른다고 답한다. 한국어로 3~5문장으로 간결히."
)

MAX_TURNS = 6  # 무한 루프 방지. 예산/중단 가드의 원형(05 에서 정교화).


def _make_client():
    """LLM 클라이언트를 만든다. 키 있으면 Anthropic, 없으면 MockClient.

    Ollama 로 바꾸려면: OpenAI 호환 엔드포인트(http://localhost:11434/v1)를 쓰는
    클라이언트를 여기서 돌려주고, tool-use 를 그 API 스펙에 맞게 매핑하면 된다.
    """
    if os.environ.get("ANTHROPIC_API_KEY"):
        import anthropic

        return anthropic.Anthropic(), "claude"
    return MockClient(), "mock"


class MockClient:
    """API 키 없이 '루프 자체'를 검증하는 가짜 클라이언트.

    규칙: 아직 도구를 안 썼으면 docs_search 를 부르는 tool_use 를 반환하고,
    이미 tool_result 가 있으면 그 근거로 최종 텍스트 답변을 만든다.
    실제 LLM 의 추론은 없다 — 루프·tool_use/tool_result 왕복·인용 형식만 그대로 재현한다.
    """

    class _Block:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    class _Resp:
        def __init__(self, content, stop_reason):
            self.content = content
            self.stop_reason = stop_reason

    def messages_create_like(self, messages: list[dict]) -> "MockClient._Resp":
        # 이미 tool_result 가 대화에 있는지 확인.
        has_tool_result = any(
            isinstance(m.get("content"), list)
            and any(b.get("type") == "tool_result" for b in m["content"])
            for m in messages
        )
        user_q = self._first_user_text(messages)
        if not has_tool_result:
            # 첫 턴: docs_search 를 부른다.
            block = self._Block(
                type="tool_use",
                id="mock-1",
                name="docs_search",
                input={"query": user_q, "k": 3},
            )
            return self._Resp([block], "tool_use")
        # 둘째 턴: 마지막 tool_result 로 인용 답변을 만든다.
        cids = self._collect_chunk_ids(messages)
        cite = " ".join(f"[{c}]" for c in cids[:3]) or "[근거 없음]"
        text = self._Block(
            type="text",
            text=f"'{user_q}' 에 대한 답: 검색된 근거를 종합하면 아래와 같다. {cite}",
        )
        return self._Resp([text], "end_turn")

    @staticmethod
    def _first_user_text(messages: list[dict]) -> str:
        for m in messages:
            if m["role"] == "user" and isinstance(m["content"], str):
                return m["content"]
        return ""

    @staticmethod
    def _collect_chunk_ids(messages: list[dict]) -> list[str]:
        cids: list[str] = []
        for m in messages:
            if not isinstance(m.get("content"), list):
                continue
            for b in m["content"]:
                if b.get("type") == "tool_result":
                    try:
                        rows = json.loads(b["content"])
                        cids.extend(r["chunk_id"] for r in rows)
                    except Exception:
                        pass
        return cids


def _create(client, backend: str, registry: ToolRegistry, messages: list[dict]):
    """백엔드에 맞춰 messages.create 를 호출하고 (content_blocks, stop_reason) 로 정규화."""
    if backend == "claude":
        resp = client.messages.create(
            model=LLM_MODEL,
            max_tokens=1024,
            system=SYSTEM,
            tools=registry.specs(),
            messages=messages,
        )
        return resp.content, resp.stop_reason
    resp = client.messages_create_like(messages)
    return resp.content, resp.stop_reason


def run_agent(question: str, *, verbose: bool = True) -> dict:
    """최소 tool-use 루프. 최종 답변 텍스트와 사용한 도구·인용을 돌려준다."""
    client, backend = _make_client()
    registry = build_registry()
    messages: list[dict] = [{"role": "user", "content": question}]
    tool_calls: list[str] = []

    if verbose:
        print(f"[agent] backend={backend} model={LLM_MODEL if backend == 'claude' else 'mock'}")
        print(f"[agent] question={question!r}\n")

    for turn in range(1, MAX_TURNS + 1):
        content, stop_reason = _create(client, backend, registry, messages)
        # 어시스턴트 응답을 그대로 대화에 붙인다(tool_use 블록 포함).
        messages.append({"role": "assistant", "content": _as_api_content(content, backend)})

        if stop_reason != "tool_use":
            final = _extract_text(content)
            if verbose:
                print(f"[turn {turn}] 최종 답변(stop_reason={stop_reason})\n")
                print(final)
            return {"answer": final, "tool_calls": tool_calls, "turns": turn, "backend": backend}

        # tool_use 블록마다 도구를 실행하고 tool_result 를 모은다.
        tool_results = []
        for block in content:
            if _btype(block) != "tool_use":
                continue
            name, tinput, tid = _tool_use_fields(block)
            tool_calls.append(name)
            if verbose:
                print(f"[turn {turn}] tool_use → {name}({json.dumps(tinput, ensure_ascii=False)})")
            result_str = registry.dispatch(name, tinput)
            tool_results.append(
                {"type": "tool_result", "tool_use_id": tid, "content": result_str}
            )
        messages.append({"role": "user", "content": tool_results})

    return {
        "answer": "(중단) 최대 턴 수 초과",
        "tool_calls": tool_calls,
        "turns": MAX_TURNS,
        "backend": backend,
    }


# ── 백엔드별 블록 접근 헬퍼(Claude SDK 객체 vs Mock 객체를 같은 코드로 다룬다) ──
def _btype(block) -> str:
    return getattr(block, "type", None) or (block.get("type") if isinstance(block, dict) else None)


def _tool_use_fields(block):
    return block.name, block.input, block.id


def _extract_text(content) -> str:
    parts = []
    for b in content:
        if _btype(b) == "text":
            parts.append(getattr(b, "text", "") or (b.get("text", "") if isinstance(b, dict) else ""))
    return "".join(parts).strip()


def _as_api_content(content, backend: str):
    """어시스턴트 content 를 다음 create 호출에 다시 넣을 형태로.

    Claude SDK 는 응답 content 를 그대로 다시 넣을 수 있다(객체 리스트 허용).
    Mock 은 객체를 dict 로 바꿔 준다(직렬화 흐름을 명시적으로 보이려는 것).
    """
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
    q = sys.argv[1] if len(sys.argv) > 1 else "CRAG 와 Self-RAG 는 무엇이 다른가?"
    result = run_agent(q)
    print("\n--- 요약 ---")
    print(f"backend    : {result['backend']}")
    print(f"tool_calls : {result['tool_calls']}")
    print(f"turns      : {result['turns']}")
