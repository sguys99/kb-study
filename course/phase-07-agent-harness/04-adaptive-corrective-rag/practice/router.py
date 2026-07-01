"""router.py — Adaptive-RAG 의 '질문 복잡도 라우터'를 하니스에 맞춰 축약한 것.

Adaptive-RAG(2403.14403)는 질문의 복잡도를 먼저 분류해 no-retrieval / single-step /
multi-step 으로 나눈다. 우리는 그 아이디어만 가져와, 03 까지 만든 '3개의 도구'에 질문을
어떻게 보낼지 결정하는 라우팅 계획으로 바꾼다. 논문 재현이 아니라 실무용 3분기다.

우리 라우팅 4유형(복잡도·성격 → 도구/모드):
  - simple    : 단순 사실·정의 한 방 → docs_search 1회.        (single-step)
  - relation  : 엔티티 사이 관계·멀티홉·경로 → graph_query(template). (multi-step)
  - broad     : 전체 요약·개괄·"무엇들이 있나" → graph_query(lightrag, mode=global).
  - schema    : "이 관계가 스키마상 맞나" → ontology_check.

출력 계약 RoutePlan:
  route     : 위 4유형 중 하나
  tool      : 실제 부를 도구 이름(docs_search / graph_query / ontology_check)
  tool_input: 그 도구에 넘길 입력(01~03 스키마 그대로). adaptive_loop 이 그대로 dispatch.
  reason    : 왜 그렇게 라우팅했는지(감사·디버깅용 한 줄)

두 경로:
  1) 기본 — ANTHROPIC_API_KEY 로 Claude 가 route 를 JSON(enum)으로 판정(Structured Output).
  2) 폴백(비용 0) — 키 없으면 규칙 기반 분류기. 키워드·엔티티 개수로 route 를 정한다.
     실제 추론이 아니라 '라우팅 흐름'을 API 없이 재현하려는 것.

전제: 표준 라이브러리 + (선택) anthropic. 도구 입력 생성에 03 register_all_tools 의
  template 카탈로그를 참고하지 않고, 02 에서 고정한 template 이름(neighbors/path_between)만 쓴다.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

# 라우팅이 아는 엔티티 사전(mock 편의). 02 graph_query 의 mock 그래프와 같은 이름 집합.
KNOWN_ENTITIES = [
    "Self-RAG", "CRAG", "Adaptive-RAG", "Agentic RAG", "GraphRAG",
    "LightRAG", "Tool Use", "Reflection Token", "Workflow", "Agent",
]

# route → 성격 키워드(규칙 폴백용). LLM 경로에서는 프롬프트로 대체된다.
_RELATION_HINTS = ("관계", "연결", "경로", "사이", "이웃", "어떻게 이어", "무엇과", "연관")
_BROAD_HINTS = ("요약", "개괄", "전체", "전반", "무엇들", "어떤 것들", "정리해", "개요", "landscape")
_SCHEMA_HINTS = ("스키마", "온톨로지", "타당", "허용된 관계", "방향이 맞", "관계가 맞")


@dataclass
class RoutePlan:
    """라우팅 결정 한 건. adaptive_loop 이 이걸 보고 어떤 도구를 부를지 안다."""

    route: str                 # simple / relation / broad / schema
    tool: str                  # docs_search / graph_query / ontology_check
    tool_input: dict           # 그 도구에 넘길 입력(01~03 스키마 그대로)
    reason: str
    backend: str = "rule"      # rule / claude (판정 주체)
    extras: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "route": self.route,
            "tool": self.tool,
            "tool_input": self.tool_input,
            "reason": self.reason,
            "backend": self.backend,
        }


def extract_entities(question: str) -> list[str]:
    """질문에 등장한 알려진 엔티티를 등장 순서대로 뽑는다(라우팅·도구입력 생성용)."""
    ql = question.lower()
    found = [(ql.index(e.lower()), e) for e in KNOWN_ENTITIES if e.lower() in ql]
    found.sort(key=lambda x: x[0])
    return [e for _, e in found]


# ── route → 도구 입력으로 변환(01~03 스키마 고정) ────────────────────────────
def _tool_input_for(route: str, question: str) -> tuple[str, dict]:
    """route 와 질문에서 실제 도구 이름 + 입력을 만든다. 여기서 01~03 계약을 그대로 쓴다."""
    ents = extract_entities(question)

    if route == "relation":
        # 엔티티 2개면 경로, 1개면 이웃. 02 template 이름(neighbors/path_between)을 쓴다.
        if len(ents) >= 2:
            return "graph_query", {
                "method": "template", "template": "path_between",
                "params": {"source": ents[0], "target": ents[1]},
            }
        return "graph_query", {
            "method": "template", "template": "neighbors",
            "params": {"name": ents[0] if ents else "Self-RAG"},
        }

    if route == "broad":
        # 전체 요약은 LightRAG global 모드로(Phase 4 5모드 중 global).
        return "graph_query", {"method": "lightrag", "question": question, "mode": "global"}

    if route == "schema":
        # 스키마 타당성은 ontology_check. 질문에서 삼중항을 근사 추출(못 뽑으면 예시 하나).
        return "ontology_check", {"triples": _guess_triples(question)}

    # simple(기본): docs_search 한 방.
    return "docs_search", {"query": question, "k": 3}


def _guess_triples(question: str) -> list[dict]:
    """스키마 질문에서 (subject, relation, object) 삼중항 근사 추출. 03 mock 규칙과 동일."""
    labels = ["Method", "Concept", "Component", "Framework", "Dataset"]
    rels = ["USES", "IS_A", "BUILT_ON", "IMPLEMENTS", "EXTENDS", "MENTIONS"]
    ql = question.lower()
    found_l = sorted((x for x in labels if x.lower() in ql), key=lambda x: ql.index(x.lower()))
    found_r = [x for x in rels if x.lower() in ql]
    if len(found_l) >= 2 and found_r:
        return [{"subject": found_l[0], "relation": found_r[0], "object": found_l[1]}]
    return [{"subject": "Method", "relation": "USES", "object": "Component"}]


# ── 규칙 기반 분류기(폴백) ───────────────────────────────────────────────────
def _classify_rule(question: str) -> tuple[str, str]:
    """키워드·엔티티 개수로 route 를 정한다. (route, reason) 반환."""
    q = question
    if any(h in q for h in _SCHEMA_HINTS):
        return "schema", "스키마·온톨로지 타당성 질문 → ontology_check"
    if any(h in q for h in _BROAD_HINTS):
        return "broad", "전체 요약·개괄 질문 → lightrag(global)"
    ents = extract_entities(q)
    if any(h in q for h in _RELATION_HINTS) or len(ents) >= 2:
        return "relation", f"관계·멀티홉 신호(엔티티 {len(ents)}개) → graph_query(template)"
    return "simple", "단순 사실·정의 질문 → docs_search 1회"


# ── LLM 기반 분류기(기본 경로) ──────────────────────────────────────────────
_ROUTER_SYSTEM = (
    "너는 질문 라우터다. 사용자 질문을 아래 네 유형 중 하나로 분류한다.\n"
    "- simple  : 단순 사실·정의 하나로 답하는 질문.\n"
    "- relation: 엔티티 사이 관계·연결·경로·멀티홉을 묻는 질문.\n"
    "- broad   : 전체 요약·개괄·landscape 를 묻는 광범위 질문.\n"
    "- schema  : 특정 관계가 스키마(온톨로지)상 타당한지 묻는 질문.\n"
    '반드시 {"route": "<simple|relation|broad|schema>", "reason": "<한 줄>"} JSON 만 출력한다.'
)


def _classify_llm(question: str) -> tuple[str, str] | None:
    """Claude 로 route 를 JSON(enum) 판정. 실패하면 None(호출부가 규칙으로 폴백)."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic

        client = anthropic.Anthropic()
        model = os.environ.get("HARNESS_MODEL", "claude-sonnet-4-6")
        resp = client.messages.create(
            model=model, max_tokens=200, system=_ROUTER_SYSTEM,
            messages=[{"role": "user", "content": question}],
        )
        text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
        data = json.loads(_first_json(text))
        route = data.get("route", "").strip()
        if route not in ("simple", "relation", "broad", "schema"):
            return None
        return route, data.get("reason", "(LLM 판정)")
    except Exception:
        return None


def _first_json(text: str) -> str:
    """텍스트에서 첫 JSON 오브젝트만 뽑는다(모델이 앞뒤에 군말을 붙여도 견디게)."""
    m = re.search(r"\{.*\}", text, re.DOTALL)
    return m.group(0) if m else text


def route(question: str) -> RoutePlan:
    """질문을 분류해 RoutePlan 을 만든다. 키 있으면 Claude, 없거나 실패하면 규칙 폴백."""
    llm = _classify_llm(question)
    if llm is not None:
        r, reason = llm
        backend = "claude"
    else:
        r, reason = _classify_rule(question)
        backend = "rule"
    tool, tinput = _tool_input_for(r, question)
    return RoutePlan(route=r, tool=tool, tool_input=tinput, reason=reason, backend=backend)


if __name__ == "__main__":
    samples = [
        "Self-RAG 는 언제 검색을 하나?",                       # simple
        "CRAG 와 Self-RAG 는 어떻게 연결돼 있나?",             # relation(엔티티 2개)
        "GraphRAG 진영에는 어떤 것들이 있는지 전체를 요약해줘",  # broad
        "Component 가 Method 를 USES 하는 관계는 스키마상 타당한가?",  # schema
    ]
    print(f"[router] backend={'claude' if os.environ.get('ANTHROPIC_API_KEY') else 'rule'}\n")
    for q in samples:
        plan = route(q)
        print(f"Q: {q}")
        print(f"   route={plan.route:9} tool={plan.tool:14} reason={plan.reason}")
        print(f"   tool_input={json.dumps(plan.tool_input, ensure_ascii=False)}\n")
