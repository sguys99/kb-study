"""agent_loop.py — 도구 3개(docs_search + graph_query + ontology_check)를 쓰는 tool-use 루프.

02 의 agent_loop 뼈대를 그대로 잇는다. 바뀌는 것은 레지스트리뿐:
  build_registry_with_graph()(도구 2개) → build_registry_full()(도구 3개).
루프 골격(create → tool_use → dispatch → tool_result)은 01·02 와 동일하다.
'도구가 늘어도 하니스 골격은 안 바뀐다'는 원칙을 세 번째 도구로 다시 확인한다.

두 경로:
  1) 기본 — ANTHROPIC_API_KEY 로 Claude tool-use 루프(도구 3개). 모델이 스스로 도구를 고른다.
  2) 폴백(비용 0) — 키 없으면 MockClient 로 같은 루프. 관계·경로 질문이면 graph_query,
     '스키마/온톨로지/관계 타당' 질문이면 ontology_check, 그 밖이면 docs_search 를 부른다.

전제: 01·02·03 practice 를 import 경로에 올린다(register_all_tools 가 처리).
  기본 경로만 ANTHROPIC_API_KEY. 폴백·mock 그래프·Safety Guard·온톨로지는 표준 라이브러리 + Pydantic.
사용: python agent_loop.py "질문"
"""

from __future__ import annotations

import json
import os
import sys

from register_all_tools import build_registry_full

LLM_MODEL = os.environ.get("HARNESS_MODEL", "claude-sonnet-4-6")

SYSTEM = (
    "너는 문서 + 지식그래프 기반 리서치 어시스턴트다. 도구가 셋이다. "
    "정의·사실·비교는 docs_search 로 근거를 찾는다. "
    "엔티티 사이 '관계·연결·경로'는 graph_query 를 쓴다(안전한 template 우선, 안 되면 text2cypher, 요약은 lightrag). "
    "생성한 Cypher 나 답변이 주장하는 관계가 스키마상 타당한지 의심되면 ontology_check 로 검증한다. "
    "graph_query(text2cypher)는 실행 전에 Cypher Safety Guard 를 반드시 통과한다 — 거부되면 질의를 고쳐 다시 시도하라. "
    "최종 답변의 각 주장 끝에 근거의 [chunk_id] 또는 [source] 를 인용한다. "
    "근거가 없으면 모른다고 답한다. 한국어로 3~5문장으로 간결히."
)

MAX_TURNS = 8


def _make_client():
    if os.environ.get("ANTHROPIC_API_KEY"):
        import anthropic

        return anthropic.Anthropic(), "claude"
    return MockClient(), "mock"


class MockClient:
    """도구 3개를 쓰는 루프를 API 없이 검증하는 가짜 클라이언트(실제 추론 아님).

    규칙:
      - tool_result 가 없고 질문에 '스키마/온톨로지/타당/관계 맞' 이 있으면 ontology_check 를,
      - '관계/연결/경로/사이/이웃' 이 있으면 graph_query(template) 을,
      - 그 밖이면 docs_search 를 부른다.
      - tool_result 가 이미 있으면 근거를 모아 인용 답변을 만든다.
    """

    class _Block:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    class _Resp:
        def __init__(self, content, stop_reason):
            self.content = content
            self.stop_reason = stop_reason

    _ONTO_HINTS = ("스키마", "온톨로지", "타당", "관계 맞", "허용된 관계", "방향")
    _GRAPH_HINTS = ("관계", "연결", "경로", "사이", "이웃", "어떻게 이어")

    def messages_create_like(self, messages: list[dict]) -> "MockClient._Resp":
        has_tool_result = any(
            isinstance(m.get("content"), list)
            and any(b.get("type") == "tool_result" for b in m["content"])
            for m in messages
        )
        user_q = self._first_user_text(messages)
        if not has_tool_result:
            if any(h in user_q for h in self._ONTO_HINTS):
                # 스키마 타당성 질문 → ontology_check. 질문의 삼중항을 근사 추출.
                tinput = {"triples": self._guess_triples(user_q)}
                block = self._Block(type="tool_use", id="mock-o1", name="ontology_check", input=tinput)
                return self._Resp([block], "tool_use")
            if any(h in user_q for h in self._GRAPH_HINTS):
                names = self._extract_names(user_q)
                if len(names) >= 2:
                    tinput = {"method": "template", "template": "path_between",
                              "params": {"source": names[0], "target": names[1]}}
                else:
                    tinput = {"method": "template", "template": "neighbors",
                              "params": {"name": names[0] if names else "Self-RAG"}}
                block = self._Block(type="tool_use", id="mock-g1", name="graph_query", input=tinput)
                return self._Resp([block], "tool_use")
            block = self._Block(type="tool_use", id="mock-d1", name="docs_search",
                                input={"query": user_q, "k": 3})
            return self._Resp([block], "tool_use")

        summary = self._summarize(messages)
        text = self._Block(type="text", text=summary)
        return self._Resp([text], "end_turn")

    @staticmethod
    def _first_user_text(messages: list[dict]) -> str:
        for m in messages:
            if m["role"] == "user" and isinstance(m["content"], str):
                return m["content"]
        return ""

    @staticmethod
    def _extract_names(q: str) -> list[str]:
        known = ["Self-RAG", "CRAG", "Adaptive-RAG", "Agentic RAG", "GraphRAG",
                 "LightRAG", "Tool Use", "Reflection Token"]
        return [n for n in known if n.lower() in q.lower()]

    @staticmethod
    def _guess_triples(q: str) -> list[dict]:
        """질문에서 라벨·관계를 근사 추출(mock 편의). 못 뽑으면 예시 삼중항 하나.

        주의: subject/object 는 '질문에 나온 순서'로 잡는다. 그래야
        'Component 이 Method 를 USES' 같은 방향 위반이 그대로 삼중항에 실린다.
        """
        labels = ["Method", "Concept", "Component", "Framework", "Dataset"]
        rels = ["USES", "IS_A", "BUILT_ON", "IMPLEMENTS", "EXTENDS", "MENTIONS"]
        ql = q.lower()
        # 등장 위치 순으로 라벨을 정렬(질문 어순 = subject → object).
        found_l = sorted((x for x in labels if x.lower() in ql), key=lambda x: ql.index(x.lower()))
        found_r = [x for x in rels if x.lower() in ql]
        if len(found_l) >= 2 and found_r:
            return [{"subject": found_l[0], "relation": found_r[0], "object": found_l[1]}]
        return [{"subject": "Method", "relation": "USES", "object": "Component"}]

    def _summarize(self, messages: list[dict]) -> str:
        sources: list[str] = []
        onto_ok = None
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
                if isinstance(payload, dict) and "violations" in payload:
                    onto_ok = payload.get("ok")
                sources.extend(_ids_from_payload(payload))
        user_q = self._first_user_text(messages)
        cite = " ".join(f"[{s}]" for s in sources[:3]) or "[근거 없음]"
        note = ""
        if onto_ok is True:
            note = " (스키마 검증 통과)"
        elif onto_ok is False:
            note = " (스키마 위반이 발견돼 해당 관계는 답에서 제외)"
        return f"'{user_q}' 에 대한 답: 근거를 종합하면 아래와 같다.{note} {cite}"


def _ids_from_payload(payload) -> list[str]:
    """docs_search / graph_query / ontology_check 결과에서 인용 식별자 추출."""
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
    registry = build_registry_full()
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
    q = sys.argv[1] if len(sys.argv) > 1 else "Self-RAG 는 무엇과 연결돼 있나?"
    result = run_agent(q)
    print("\n--- 요약 ---")
    print(f"backend    : {result['backend']}")
    print(f"tool_calls : {result['tool_calls']}")
    print(f"turns      : {result['turns']}")
