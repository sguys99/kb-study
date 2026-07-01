"""citation.py — 답변이 단 인용이 '실제 검색 결과에 있는지' 검증하고, 없는 인용은 제거한다.

Structured Output 으로 답 모양을 강제해도, LLM 이 인용 id 를 지어낼 수 있다. "이 주장은
[doc-xyz-99] 에 근거한다"고 써 놓고 정작 doc-xyz-99 는 검색된 적이 없는 경우 — 환각 인용
(hallucinated citation)이다. 근거가 있는 척하는 이 거짓말이 RAG 신뢰를 가장 크게 무너뜨린다.

방어는 단순하다. 이번 질문에서 도구가 실제로 돌려준 근거의 id 집합을 만들고(allowed set),
답변이 단 인용 중 그 집합에 없는 것을 걸러낸다. 있는 척하는 인용은 응답에서 지운다.

두 가지를 한다:
  1) build_evidence_index(retrievals) — 이번 질문에서 나온 모든 검색 결과를 훑어
     {id -> Citation} 인덱스를 만든다(docs_search=chunk_id, graph_query=rows 경로).
  2) verify_citations(answer_citations, index) — 답의 인용을 인덱스와 대조해
     valid(실존) / dropped(환각) 로 가른다. valid 만 남긴다.

핵심 규약: 검증은 '지어낸 인용 제거'만 한다. 근거를 새로 만들거나 답 내용을 바꾸지 않는다.

전제: 표준 라이브러리 + schema.Citation. API 키·DB 불필요.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from schema import Citation


def _rows_of(retrieval: object) -> list[dict]:
    """도구 결과를 행 리스트로 정규화한다. 04 grader.normalize_rows 와 같은 계약."""
    if isinstance(retrieval, dict):
        rows = retrieval.get("rows")
        return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []
    if isinstance(retrieval, list):
        return [r for r in retrieval if isinstance(r, dict)]
    return []


def _graph_key(row: dict) -> str | None:
    """graph_query 의 한 행을 '경로 인용 키'로 만든다.

    rows 는 이웃/경로 결과라 chunk_id 가 없다. from/relation/to 나 name 을 조합해
    사람이 읽을 수 있는 경로 키를 만든다. 예: 'Self-RAG -[RELATES]-> CRAG'.
    """
    for a, rel, b in (("from", "relation", "to"), ("source", "relation", "target")):
        if row.get(a) and row.get(b):
            r = row.get(rel, "REL")
            return f"{row[a]} -[{r}]-> {row[b]}"
    if row.get("neighbor"):
        base = row.get("entity") or row.get("name") or "?"
        return f"{base} ~ {row['neighbor']}"
    if row.get("path"):
        return str(row["path"])
    return None


def _citations_from_row(row: dict) -> list[Citation]:
    """검색 결과 한 행에서 근거 Citation 을 만든다(있으면). 여러 키로 색인될 수 있다.

    한 행이 여러 식별자를 가질 수 있다. 예를 들어 graph_query 의 경로 행은 사람이 읽는
    경로 키('CRAG -[IS_A]-> Agentic RAG')와 원천 식별자(source='e-agentic-rag')를 둘 다
    가진다. 05 run_guarded 는 인용을 source 기준으로 뽑고, 이 파일의 표시용 인용은 경로
    기준으로 만든다 — 같은 근거를 둘이 다른 이름으로 부른다. 그래서 둘 다 allowed 로
    등록해, 05 가 뽑은 인용이 '실존'으로 검증되게 한다(같은 행을 가리키면 환각이 아니다).
    """
    out: list[Citation] = []
    if row.get("chunk_id"):
        out.append(Citation(
            id=str(row["chunk_id"]), kind="chunk",
            source=row.get("source_id") or row.get("source"),
            snippet=row.get("text"),
        ))
        return out  # 문서 청크는 chunk_id 하나로 충분.
    gk = _graph_key(row)
    if gk:
        out.append(Citation(id=gk, kind="graph", source=row.get("source"), snippet=None))
    if row.get("source") or row.get("source_id"):
        sid = str(row.get("source") or row.get("source_id"))
        # 경로 키가 이미 있으면 같은 근거를 source 이름으로도 등록(별칭). 없으면 단독 source 인용.
        out.append(Citation(id=sid, kind="graph" if gk else "source", source=sid, snippet=None))
    return out


def build_evidence_index(retrievals: list[object]) -> dict[str, Citation]:
    """이번 질문에서 나온 모든 검색 결과 → {인용 id -> Citation} 인덱스.

    retrievals 는 이 질문을 처리하며 도구가 돌려준 결과들의 리스트(재시도·폴백 포함).
    한 행이 여러 식별자(경로 키 + source)를 가지면 각각을 allowed 로 등록한다. 같은 id 가
    여러 번 나오면 먼저 본 것을 유지한다. 이 인덱스의 키 집합이 곧 'allowed set'.
    """
    index: dict[str, Citation] = {}
    for retrieval in retrievals:
        for row in _rows_of(retrieval):
            for c in _citations_from_row(row):
                if c.id not in index:
                    index[c.id] = c
    return index


@dataclass
class CitationCheck:
    """인용 검증 결과. valid=실존 인용, dropped=환각(지어낸) 인용."""

    valid: list[Citation] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)   # 제거된 인용 id
    allowed_ids: list[str] = field(default_factory=list)  # 검색으로 나온 실존 id 집합

    @property
    def hallucinated(self) -> int:
        return len(self.dropped)

    def summary(self) -> dict:
        return {
            "valid": [c.id for c in self.valid],
            "dropped": self.dropped,
            "allowed": self.allowed_ids,
            "hallucinated": self.hallucinated,
        }


def verify_citations(
    answer_citations: list[Citation],
    index: dict[str, Citation],
) -> CitationCheck:
    """답이 단 인용을 검색 인덱스와 대조한다. 인덱스에 없는 인용은 환각으로 보고 제거한다.

    실존 인용은 인덱스의 정본(snippet·source 가 채워진 것)으로 교체해 돌려준다 — LLM 이 준
    snippet 이 아니라 '실제 검색된 근거'를 표시하려는 것.
    """
    allowed = set(index.keys())
    check = CitationCheck(allowed_ids=sorted(allowed))
    seen: set[str] = set()
    for c in answer_citations:
        if c.id in allowed:
            if c.id not in seen:       # 중복 인용은 한 번만.
                check.valid.append(index[c.id])   # 정본으로 교체.
                seen.add(c.id)
        else:
            check.dropped.append(c.id)  # 환각 인용 — 제거.
    return check


def enrich_citations(index: dict[str, Citation], limit: int = 3) -> list[Citation]:
    """답에 인용이 하나도 안 붙었을 때, 검색 인덱스 상위 근거로 인용을 보강한다.

    mock 답변은 [chunk_id] 를 문자열로만 흘리고 구조화 인용을 안 줄 수 있다. 그럴 때 실제
    검색 근거에서 상위 limit 개를 인용으로 붙인다(환각이 아니라 실존 근거이므로 안전).
    """
    return list(index.values())[:limit]


if __name__ == "__main__":
    # 빠른 자기점검: 실존 인용은 남기고 환각 인용은 지운다.
    retrievals = [
        [  # docs_search 결과
            {"chunk_id": "doc-self-rag-01", "source_id": "src-self-rag",
             "text": "Self-RAG 는 reflection 토큰으로 검색 필요성을 평가한다."},
            {"chunk_id": "doc-crag-01", "source_id": "src-crag", "text": "CRAG 는 검색 품질을 평가한다."},
        ],
        {"rows": [{"from": "Self-RAG", "relation": "RELATES", "to": "CRAG"}]},  # graph_query 결과
    ]
    index = build_evidence_index(retrievals)
    print("검색으로 나온 실존 인용 id:", sorted(index.keys()))

    # 답이 단 인용: 2개는 실존, 1개(doc-fake-99)는 지어냄.
    answer_cites = [
        Citation(id="doc-self-rag-01"),
        Citation(id="Self-RAG -[RELATES]-> CRAG", kind="graph"),
        Citation(id="doc-fake-99"),   # 환각 — 검색된 적 없음.
    ]
    check = verify_citations(answer_cites, index)
    print("검증 결과:", check.summary())

    assert "doc-fake-99" in check.dropped, "환각 인용이 제거되지 않았다"
    assert {c.id for c in check.valid} == {"doc-self-rag-01", "Self-RAG -[RELATES]-> CRAG"}
    print("[assert] 환각 인용 1건 제거, 실존 인용 2건 유지 통과")
