"""graph_query.py — 그래프에 질의하는 '한 개의 도구', 세 가지 백엔드.

01 의 docs_search 와 같은 Tool Contract 규약을 따른다:
  (입력) → 인용 가능한 결과 리스트(각 항목에 source 필드).
docs_search 가 텍스트 청크를 돌려줬다면, graph_query 는 경로·이웃·그래프 답변을 돌려준다.

한 도구 계약 안에서 method 파라미터로 세 백엔드를 분기한다:
  - method="template"    : 파라미터화된 미리 검증된 Cypher 템플릿. 가장 안전. 기본 권장.
  - method="text2cypher" : 스키마를 프롬프트에 넣어 LLM 이 Cypher 생성 → 읽기 전용 실행.
                           유연하지만 위험. 안전 가드(쓰기 차단·주입 방어)는 03 에서 완성한다.
  - method="lightrag"    : Phase 4 LightRAG 5모드(naive/local/global/hybrid/mix)를 mode 로 호출.

출력 계약(세 백엔드 공통): {"method", "rows": [...], "backend"} 를 담은 dict.
  rows 의 각 항목에는 근거 식별자 source 가 있어 답변에 인용할 수 있다.

전제: 기본 경로는 표준 라이브러리만. text2cypher 의 LLM 생성은 ANTHROPIC_API_KEY 가
  있으면 Claude, 없으면 규칙 기반 mock 생성기. Neo4j·LightRAG 는 있으면 붙고 없으면 mock.
"""

from __future__ import annotations

import os

from cypher_templates import build_template_registry
from graph_backend import make_graph_backend
from lightrag_backend import lightrag_query

# 백엔드는 모듈 로드 시 한 번만 구성(도구 호출마다 재적재하지 않는다).
_TEMPLATES = build_template_registry()
_GRAPH_KIND, _GRAPH = make_graph_backend()


# ── 1) template 백엔드 ──────────────────────────────────────────────────────
def _run_template(template: str, params: dict) -> list[dict]:
    """이름으로 템플릿을 찾아 파라미터를 꽂아 실행한다. 문자열 포매팅 없음 = 주입 없음."""
    t = _TEMPLATES.get(template)
    if t is None:
        catalog = [c["name"] for c in _TEMPLATES.catalog()]
        return [{"error": f"unknown template: {template}. 사용 가능: {catalog}"}]
    # 필수 파라미터 점검(스키마 계약을 코드로 강제).
    missing = [p for p in t.params if p not in params and not p.endswith(("limit", "hops"))]
    if missing:
        return [{"error": f"template {template} 필수 파라미터 누락: {missing}"}]

    if _GRAPH_KIND == "neo4j":
        # 실전: 미리 검증된 Cypher 를 $파라미터 바인딩으로 읽기 전용 실행.
        return _GRAPH.run_read(t.cypher, params)
    # mock: 같은 의미를 in-memory 그래프로 실행.
    return t.mock_fn(_GRAPH, params)


# ── 2) text2cypher 백엔드 (생성 → 읽기전용 실행까지만. 안전 가드는 03) ───────
# 실전 KG 스키마 요약. text2cypher 프롬프트에 넣어 모델이 올바른 라벨·관계를 쓰게 한다.
GRAPH_SCHEMA_HINT = (
    "노드 라벨: Method, Concept, Component, Framework. 모든 노드는 name 속성을 가진다. "
    "관계 타입: USES, IS_A, BUILT_ON, IMPLEMENTS, EXTENDS. "
    "예: (:Method {name})-[:USES]->(:Component {name})."
)

_TEXT2CYPHER_SYSTEM = (
    "너는 그래프 질의 생성기다. 아래 스키마만 사용해 사용자의 자연어 질문을 '읽기 전용' "
    "Cypher 한 줄로 변환한다. MATCH 와 RETURN 만 쓴다. CREATE/DELETE/SET/MERGE 는 절대 쓰지 않는다. "
    "설명 없이 Cypher 만 출력한다.\n스키마: " + GRAPH_SCHEMA_HINT
)


def _generate_cypher(question: str) -> str:
    """자연어 → Cypher 문자열. 키 있으면 Claude, 없으면 규칙 기반 mock 생성."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        import anthropic

        client = anthropic.Anthropic()
        model = os.environ.get("HARNESS_MODEL", "claude-sonnet-4-6")
        resp = client.messages.create(
            model=model,
            max_tokens=256,
            system=_TEXT2CYPHER_SYSTEM,
            messages=[{"role": "user", "content": question}],
        )
        text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
        return _strip_code_fence(text).strip()
    return _mock_generate_cypher(question)


def _mock_generate_cypher(question: str) -> str:
    """키 없이 text2cypher '흐름'을 보여주는 규칙 기반 생성기(실제 추론 아님).

    질문에서 따옴표로 감싼 이름을 뽑아 neighbors 형태 Cypher 를 만든다.
    실전 LLM 이면 훨씬 다양한 질의를 생성한다 — 여기선 파이프라인만 재현한다.
    """
    import re

    names = re.findall(r"'([^']+)'|\"([^\"]+)\"", question)
    flat = [a or b for a, b in names]
    target = flat[0] if flat else "Self-RAG"
    return (
        f"MATCH (x {{name: '{target}'}})-[r]-(nb) "
        "RETURN x.name AS entity, type(r) AS relation, nb.name AS neighbor, "
        "elementId(nb) AS source LIMIT 10"
    )


def _strip_code_fence(text: str) -> str:
    """```cypher ... ``` 펜스를 벗겨 순수 Cypher 만 남긴다."""
    t = text.strip()
    if t.startswith("```"):
        lines = [ln for ln in t.splitlines() if not ln.strip().startswith("```")]
        return "\n".join(lines)
    return t


def _run_text2cypher(question: str) -> list[dict]:
    """자연어 → Cypher 생성 → 읽기 전용 실행.

    ⚠️ 여기서는 생성된 Cypher 를 '그대로' 실행할 위험이 남아 있다.
       쓰기 차단·주입 방어·화이트리스트 검증은 03-cypher-safety-ontology-check 에서 완성한다.
       이 토픽에서는 '생성 → 실행' 흐름과 그 위험만 드러낸다.
    """
    cypher = _generate_cypher(question)
    generated = {"generated_cypher": cypher}

    if _GRAPH_KIND == "neo4j":
        rows = _GRAPH.run_read(cypher, {})  # 실전: execute_read 로 읽기 전용 실행.
        return [generated, *rows]

    # mock 그래프는 임의 Cypher 를 해석하지 못한다. 생성된 Cypher 에서 이름을 뽑아
    # neighbors 로 근사 실행한다(생성 결과가 '실행 가능한 모양'임을 보여주려는 것).
    import re

    m = re.search(r"name:\s*'([^']+)'", cypher)
    name = m.group(1) if m else "Self-RAG"
    rows = _GRAPH.neighbors(name)
    return [generated, *rows]


# ── 도구 실행 함수(tools.py 가 부른다) ──────────────────────────────────────
def graph_query(
    method: str = "template",
    template: str | None = None,
    params: dict | None = None,
    question: str | None = None,
    mode: str = "hybrid",
) -> dict:
    """graph_query 도구 본체. method 로 세 백엔드를 분기하고, 공통 출력 계약으로 감싼다.

    - template    : template(이름) + params(dict) 필요.
    - text2cypher : question(자연어) 필요.
    - lightrag    : question(자연어) + mode(5모드 중 하나) 필요.
    """
    params = params or {}
    if method == "template":
        if not template:
            rows = [{"error": "method=template 은 template 이름이 필요하다."}]
        else:
            rows = _run_template(template, params)
        return {"method": "template", "template": template, "rows": rows, "backend": _GRAPH_KIND}

    if method == "text2cypher":
        if not question:
            rows = [{"error": "method=text2cypher 는 question 이 필요하다."}]
        else:
            rows = _run_text2cypher(question)
        return {"method": "text2cypher", "rows": rows, "backend": _GRAPH_KIND}

    if method == "lightrag":
        if not question:
            rows = [{"error": "method=lightrag 는 question 이 필요하다."}]
        else:
            rows = lightrag_query(question, mode=mode)
        return {"method": "lightrag", "mode": mode, "rows": rows, "backend": _GRAPH_KIND}

    return {"method": method, "rows": [{"error": f"unknown method: {method}"}], "backend": _GRAPH_KIND}


def template_catalog() -> list[dict]:
    """graph_query 도구 description 에 넣을 템플릿 카탈로그."""
    return _TEMPLATES.catalog()


def graph_backend_kind() -> str:
    return _GRAPH_KIND


if __name__ == "__main__":
    import json

    print(f"[graph_query] graph_backend={_GRAPH_KIND}\n")

    print("=== 1) template: neighbors(Self-RAG) ===")
    print(json.dumps(graph_query("template", template="neighbors", params={"name": "Self-RAG"}),
                     ensure_ascii=False, indent=2))

    print("\n=== 2) template: path_between(LightRAG → Tool Use) ===")
    print(json.dumps(
        graph_query("template", template="path_between",
                    params={"source": "LightRAG", "target": "Tool Use"}),
        ensure_ascii=False, indent=2))

    print("\n=== 3) text2cypher: \"'CRAG' 는 무엇과 연결돼 있나\" ===")
    print(json.dumps(graph_query("text2cypher", question="'CRAG' 는 무엇과 연결돼 있나?"),
                     ensure_ascii=False, indent=2))

    print("\n=== 4) lightrag: mix 모드 ===")
    print(json.dumps(
        graph_query("lightrag", question="GraphRAG 와 Agentic RAG 의 관계는?", mode="mix"),
        ensure_ascii=False, indent=2))
