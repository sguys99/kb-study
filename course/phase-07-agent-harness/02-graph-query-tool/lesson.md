# 7.2 graph_query Tool — Template Cypher · Text-to-Cypher · LightRAG 도구화

> **Phase 7 · 토픽 02** · 01에서 세운 tool-use 루프에 두 번째 도구 `graph_query`를 같은 Tool Contract 규약으로 얹는다. 그래프에 질의하는 세 방식(template / text2cypher / lightrag)을 도구 하나로 통합한다.

## 학습 목표

이 토픽을 끝내면 다음을 할 수 있다.

- 파라미터화된 미리 검증된 Cypher 템플릿 레지스트리를 만들고, LLM이 템플릿 이름 + 파라미터만 고르게 한다.
- 그래프 스키마를 프롬프트에 넣어 자연어를 Cypher로 생성하고, 읽기 전용으로 실행한다(text2cypher).
- Phase 4 LightRAG의 5모드(`naive`/`local`/`global`/`hybrid`/`mix`)를 `graph_query`의 한 백엔드로 감싼다.
- 세 방식을 하나의 도구 계약으로 통합하고, 01의 `ToolRegistry`에 `graph_query`를 추가 등록해 에이전트가 도구 2개를 쓰게 만든다.

**완료 기준**: `python agent_loop.py "질문"` 실행 시 에이전트가 docs_search 또는 graph_query를 상황에 맞게 골라 호출하고, template Cypher가 파라미터로 안전하게 실행되며 인용이 붙은 답변을 반환하면 완료.

---

## 1. 왜 필요한가 — 문서 검색만으로는 못 푸는 질문

01의 에이전트는 도구가 `docs_search` 하나였다. "Self-RAG는 무엇인가"처럼 정의를 묻는 질문은 잘 답한다. 근거 청크가 코퍼스 안에 통째로 들어 있으니까.

"LightRAG와 Tool Use는 어떻게 이어지나"는 다르다. 답이 한 문서에 없다. LightRAG는 GraphRAG를 구현하고, GraphRAG는 Agentic RAG를 확장하며, Agentic RAG는 Tool Use 위에 선다. 세 홉을 건너야 나오는 관계다. 벡터 검색은 이런 멀티홉 연결을 청크 하나로 못 잡는다. Phase 3에서 만든 그래프가 필요한 이유가 여기 있다.

그래서 두 번째 도구 `graph_query`를 붙인다. 에이전트는 이제 질문을 보고 고른다. 정의·비교면 docs_search, 관계·경로면 graph_query. 도구를 고르는 판단은 코드가 아니라 모델이 한다(01의 tool-use 루프 골격 그대로).

## 2. 세 가지 질의 방식 — 안전과 유연함의 트레이드오프

그래프에 질의하는 방법은 하나가 아니다. 안전한 쪽부터 유연한 쪽까지 세 가지를 한 도구에 담는다.

**Template Cypher (기본 권장).** 사람이 미리 검증한 Cypher에 파라미터만 꽂는다. "엔티티 X의 이웃", "X와 Y 사이 경로" 같은 자주 쓰는 패턴을 이름 붙여 등록해 둔다. LLM은 템플릿 이름과 파라미터만 고른다. 생성 자유도가 0이라 가장 안전하다. 잘못된 Cypher도, 쓰기 질의도 나올 수 없다.

**Text-to-Cypher.** 템플릿으로 안 되는 자유 질의는 LLM이 스키마를 보고 Cypher를 직접 만든다. 유연하지만 위험하다. 모델이 `DELETE`를 뱉을 수도, 주입 공격에 노출될 수도 있다. 이 토픽은 "스키마 프롬프트 → 생성 → 읽기 전용 실행"까지만 다룬다. **쓰기 차단·주입 방어 같은 본격 Safety Guard는 03에서 완성한다.** 여기서는 위험이 어디 있는지 드러내는 게 목적이다.

**LightRAG 도구화.** Phase 4에서 만든 LightRAG를 그대로 백엔드로 감싼다. 5모드를 `mode` 파라미터로 노출한다. 전역 요약이 필요하면 `global`, 그래프+벡터 융합이면 `mix`. Phase 4의 검색 자산을 에이전트 도구로 승격하는 것이다.

세 방식을 따로 도구 세 개로 만들지 않는다. `graph_query` 하나에 `method` 파라미터로 분기한다(`template` | `text2cypher` | `lightrag`). 출력은 01의 docs_search와 같은 계약을 지킨다 — 인용 가능한 결과 리스트, 각 항목에 근거 식별자 `source`.

## 3. 실습 — graph_query 도구 만들고 registry에 얹기

### 3.1 파라미터화 템플릿

템플릿은 `$파라미터` 바인딩만 쓴다. 문자열 포매팅으로 값을 끼워 넣지 않는다 — 그게 주입을 막는 첫 장치다. 로드할 때 쓰기 키워드가 없는지 `assert`로 강제한다.

```python
# practice/cypher_templates.py 의 핵심 부분
_NEIGHBORS_CYPHER = """
MATCH (x {name: $name})-[r]-(nb)
RETURN x.name AS entity, type(r) AS relation,
       nb.name AS neighbor, labels(nb)[0] AS neighbor_label,
       elementId(nb) AS source
LIMIT $limit
""".strip()

@dataclass
class CypherTemplate:
    name: str
    description: str          # 모델이 읽는 '언제 쓰는지' 설명
    params: dict[str, str]
    cypher: str
    mock_fn: Callable         # Neo4j 없이 in-memory 그래프로 같은 의미 실행

    def __post_init__(self):
        upper = self.cypher.upper()
        for kw in _WRITE_KEYWORDS:      # CREATE/DELETE/SET/MERGE...
            assert kw not in upper, f"템플릿 {self.name} 에 쓰기 키워드: {kw}"
```

> 가변 길이 경로의 상한 `[*..N]`은 `$파라미터`로 바인딩할 수 없다(Cypher는 리터럴만 허용). `path_between`은 상한을 리터럴 `4`로 고정했다. 홉 수를 바꾸려면 템플릿을 하나 더 등록한다.

### 3.2 세 백엔드를 한 계약으로

`graph_query`는 `method`로 분기하되, 세 경로 모두 `{"method", "rows", "backend"}` 모양으로 돌려준다. `rows`의 각 항목에는 `source`가 있어 답변에 인용할 수 있다.

```python
# practice/graph_query.py 의 핵심 부분
def graph_query(method="template", template=None, params=None,
                question=None, mode="hybrid") -> dict:
    params = params or {}
    if method == "template":            # 가장 안전: 이름 + 파라미터만
        rows = _run_template(template, params)
        return {"method": "template", "template": template, "rows": rows, "backend": _GRAPH_KIND}
    if method == "text2cypher":         # 유연·위험: 생성 → 읽기전용 실행 (가드는 03)
        rows = _run_text2cypher(question)
        return {"method": "text2cypher", "rows": rows, "backend": _GRAPH_KIND}
    if method == "lightrag":            # Phase 4 LightRAG 5모드
        rows = lightrag_query(question, mode=mode)
        return {"method": "lightrag", "mode": mode, "rows": rows, "backend": _GRAPH_KIND}
```

text2cypher는 생성한 Cypher를 읽기 전용으로 실행한다. Neo4j 경로는 `session.execute_read`로만 돈다 — 쓰기 트랜잭션 함수를 아예 노출하지 않는 게 1차 방어선이다. 그런데 생성된 문자열 자체에 `// 주석 뒤 CREATE` 같은 게 섞이면 이 방어선만으로는 부족하다. 그 완성은 03의 몫이다.

### 3.3 01 registry에 얹기

여기가 누적 스토리라인의 핵심이다. 01에서 만든 `Tool`·`ToolRegistry`를 다시 만들지 않는다. `build_registry()`로 docs_search가 이미 등록된 레지스트리를 받아, graph_query를 한 건 더 얹는다.

```python
# practice/register_graph_tools.py 의 핵심 부분
from tools import Tool, build_registry     # 01 의 계약을 그대로 import

def build_registry_with_graph():
    reg = build_registry()                 # docs_search 가 이미 등록된 상태
    reg.register(Tool(
        name="graph_query",
        description=_graph_query_description(),   # method별 사용법 + 템플릿 카탈로그
        input_schema=GRAPH_QUERY_SCHEMA,          # method enum + 백엔드별 파라미터
        fn=_run_graph_query,
    ))
    return reg                             # 이제 도구가 2개
```

`agent_loop.py`는 레지스트리만 `build_registry_with_graph()`로 바꾼다. 루프 골격은 01과 한 줄도 다르지 않다. 도구가 늘어도 하니스는 그대로다.

> 전체 코드와 실행 절차는 [`practice/`](practice/) 와 [`labs/`](labs/) 참조.
> 기본 경로는 Neo4j·LightRAG·API 키 없이 mock으로 돈다. 비용을 줄이려면 임베딩을 `bge-m3`(로컬), LLM을 Ollama로 바꿔도 파이프라인은 동일하게 동작한다(stack-conventions 규약).

## 4. 결과 해석

`python agent_loop.py "LightRAG 와 Tool Use 는 어떻게 이어지나?"`를 돌리면:

```
[turn 1] tool_use → graph_query({"method": "template", "template": "path_between",
                                  "params": {"source": "LightRAG", "target": "Tool Use"}})
[turn 2] 최종 답변(stop_reason=end_turn)
... [e-graphrag] [e-agentic-rag] [e-tool-use]
tool_calls : ['graph_query']
```

에이전트가 관계 질문을 보고 graph_query의 path_between 템플릿을 골랐다. 경로가 LightRAG → GraphRAG → Agentic RAG → Tool Use로 세 홉 나온다. 답변 끝의 `[e-...]`는 경로에 등장한 노드의 근거 식별자다. docs_search가 청크 id로 인용했듯, graph_query는 노드 id로 인용한다 — 계약이 같다.

같은 에이전트에 "CRAG 와 Self-RAG 는 무엇이 다른가?"를 던지면 이번엔 docs_search를 고른다. 정의·비교니까. 도구 선택을 코드가 정하지 않고 모델(mock에선 규칙)이 질문에 맞춰 정한다는 게 핵심이다. 이 판단력이 04의 Router로 정교해진다.

---

## 🚨 자주 하는 실수

1. **text2cypher를 안전한 것으로 착각한다** — 이 토픽의 text2cypher는 생성한 Cypher를 사실상 그대로 실행한다. `execute_read`가 트랜잭션 레벨에서 쓰기를 막긴 하지만, 잘못된 스키마·비싼 카테시안 곱·주입 문자열은 못 거른다. 프로덕션에 이 상태로 쓰면 안 된다. **쓰기 차단·화이트리스트·주입 방어는 03에서 붙인다.** 그 전까지 text2cypher는 데모용이다.
2. **템플릿 Cypher에 값을 문자열로 끼워 넣는다** — `f"MATCH (x {{name: '{name}'}})"` 처럼 포매팅하면 주입에 뚫린다. 반드시 `$name` 바인딩 + `params` 딕셔너리로 넘긴다. Neo4j 드라이버가 값을 안전하게 처리한다.
3. **graph_query를 도구 세 개로 쪼갠다** — template/text2cypher/lightrag를 각각 도구로 만들면 모델이 셋 중 뭘 부를지 헷갈리고, 04의 Router 설계도 복잡해진다. 하나의 계약에 `method`로 분기하는 편이 모델에게도 명확하다. 백엔드는 달라도 출력 계약(rows + source)은 하나여야 인용 처리가 단순하다.

## 출처

- Anthropic Tool Use: https://docs.anthropic.com/en/docs/build-with-claude/tool-use
- Neo4j Python Driver (execute_read / 파라미터 바인딩): https://neo4j.com/docs/api/python-driver/current/
- Neo4j Cypher Manual (shortestPath · parameters): https://neo4j.com/docs/cypher-manual/current/
- LightRAG (5모드 QueryParam): https://github.com/HKUDS/LightRAG
- LangGraph Agentic RAG 가이드: https://docs.langchain.com/oss/python/langgraph/agentic-rag

## 다음 토픽

→ [7.3 Cypher Safety Guard + ontology_check Tool](../03-cypher-safety-ontology-check/lesson.md)
