"""graph_query_safe.py — 02 의 graph_query 에 Safety Guard 를 삽입한 확장.

02 는 text2cypher 경로가 생성된 Cypher 를 '그대로' 실행할 위험이 남아 있었다.
여기서 그 경로만 감싼다. 나머지(template·lightrag)는 02 를 그대로 재사용한다 — 다시 만들지 않는다.

핵심 흐름(text2cypher):
  자연어 → (02 의) _generate_cypher → [Safety Guard: is_safe] → 통과 시에만 실행 → rows
  거부되면 실행하지 않고 거부 사유를 rows 에 담아 반환한다(에이전트가 복구하도록).

왜 02 를 import 하고 새로 안 짜나:
  - Tool Contract(입력·출력)를 그대로 유지해야 01 Registry·02 register 규약이 안 깨진다.
  - 백엔드(mock/Neo4j)·템플릿·LightRAG 경로는 이미 검증됐다. 바꾸는 건 text2cypher 실행 앞단뿐이다.

전제: 02 practice 를 import 경로에 올린다(_attach_phase7_02). Safety Guard 는 표준 라이브러리.
  text2cypher 의 LLM 생성은 02 그대로(키 있으면 Claude, 없으면 mock). Neo4j 있으면 붙고 없으면 mock.
"""

from __future__ import annotations

import os
import sys


def _attach_phase7_02() -> None:
    """02 practice 폴더를 sys.path 에 올려 graph_query 내부 함수를 import 가능하게 한다."""
    here = os.path.dirname(os.path.abspath(__file__))
    p02 = os.path.normpath(os.path.join(here, "..", "..", "02-graph-query-tool", "practice"))
    if os.path.isdir(p02) and p02 not in sys.path:
        sys.path.insert(0, p02)


_attach_phase7_02()

# 02 의 내부를 재사용한다(재정의하지 않는다).
#   _generate_cypher : 자연어 → Cypher (Claude 또는 mock)
#   _GRAPH_KIND/_GRAPH: 백엔드(mock/Neo4j)
#   graph_query      : template·lightrag 경로는 이걸 그대로 위임
import graph_query as gq02  # type: ignore  # noqa: E402

from cypher_safety import is_safe  # noqa: E402


def _run_text2cypher_safe(question: str) -> list[dict]:
    """02 의 text2cypher 흐름 + Safety Guard. 통과한 Cypher 만 실행한다."""
    cypher = gq02._generate_cypher(question)  # 02 의 생성기 재사용
    verdict = is_safe(cypher)

    if not verdict.safe:
        # 실행하지 않는다. 거부 사유를 그대로 돌려줘 에이전트가 질의를 고치게 한다.
        return [{
            "generated_cypher": cypher,
            "blocked": True,
            "reason": verdict.reason,
        }]

    safe_cypher = verdict.cypher or cypher  # LIMIT 이 보강됐을 수 있는 최종본
    generated = {"generated_cypher": cypher, "safe_cypher": safe_cypher, "blocked": False}

    if gq02._GRAPH_KIND == "neo4j":
        rows = gq02._GRAPH.run_read(safe_cypher, {})  # (2) execute_read 로 읽기 전용 실행
        return [generated, *rows]

    # mock 그래프는 임의 Cypher 를 해석하지 못한다. 02 와 동일하게 이름을 뽑아 근사 실행.
    import re

    m = re.search(r"name:\s*'([^']+)'", safe_cypher)
    name = m.group(1) if m else "Self-RAG"
    rows = gq02._GRAPH.neighbors(name)
    return [generated, *rows]


def graph_query(
    method: str = "template",
    template: str | None = None,
    params: dict | None = None,
    question: str | None = None,
    mode: str = "hybrid",
) -> dict:
    """02 와 같은 시그니처·출력 계약. text2cypher 만 Safety Guard 를 거치도록 가로챈다."""
    if method == "text2cypher":
        if not question:
            rows = [{"error": "method=text2cypher 는 question 이 필요하다."}]
        else:
            rows = _run_text2cypher_safe(question)
        return {"method": "text2cypher", "rows": rows, "backend": gq02._GRAPH_KIND}

    # template·lightrag 은 02 를 그대로 위임(검증된 경로를 재사용).
    return gq02.graph_query(
        method=method, template=template, params=params, question=question, mode=mode
    )


# 02 와 동일 이름으로 재노출(register 가 그대로 import 하도록).
template_catalog = gq02.template_catalog
graph_backend_kind = gq02.graph_backend_kind


if __name__ == "__main__":
    import json

    print(f"[graph_query_safe] backend={graph_backend_kind()}\n")

    # 02 mock 생성기는 질문 속 '따옴표 이름'으로 안전한 MATCH...RETURN 을 만든다 → 통과 기대.
    print("=== text2cypher(정상 생성) ===")
    print(json.dumps(graph_query("text2cypher", question="'CRAG' 는 무엇과 연결돼 있나?"),
                     ensure_ascii=False, indent=2))

    # 위험한 Cypher 를 강제로 흘려 Guard 가 막는지 직접 확인(생성기를 우회한 저수준 테스트).
    print("\n=== Safety Guard 직접 확인(위험 Cypher 주입) ===")
    from cypher_safety import is_safe as _is_safe
    for cy in ["MATCH (n) DETACH DELETE n", "CREATE (n:Method) RETURN n"]:
        r = _is_safe(cy)
        print(f"  {cy!r:40} -> safe={r.safe} reason={r.reason}")

    print("\n=== template 경로는 02 그대로 ===")
    print(json.dumps(graph_query("template", template="neighbors", params={"name": "Self-RAG"}),
                     ensure_ascii=False, indent=2))
