"""answer_with_citations.py — 검색 컨텍스트로 인용 붙은 답변을 만든다.

기본: Claude 로 답변을 생성하고, 문장·주장마다 [chunk_id] 인용을 단다.
폴백(비용 0): ANTHROPIC_API_KEY 가 없으면 추출형(extractive) 답변으로 전환한다.
  - 상위 청크의 quote 를 인용과 함께 묶어 답을 구성한다. 네트워크 0. 키 0.
  - LLM 생성이 아니라 '근거 발췌 + 인용'이다. 기준선 평가엔 충분하다(인용 정확도를 본다).

인용 객체: 각 인용은 04 프로비넌스 사슬을 그대로 잇는다 —
  chunk_id · source_id · version · char_start · char_end · quote.
  "이 답은 src-04-graphrag-ms 문서 v1@xxxx 의 [120:340] 구간에서 나왔다"가 코드로 증명된다.

전제: 기본 경로는 ANTHROPIC_API_KEY + anthropic. 폴백 경로는 표준 라이브러리만.
"""

from __future__ import annotations

import os

from pydantic import BaseModel, Field

from load_chunks import Chunk

# 비용 낮은 기본 모델. 더 좋은 품질이 필요하면 claude-sonnet-4-6 등으로 바꾼다.
LLM_MODEL = "claude-haiku-4-5"


class Citation(BaseModel):
    """답변 1건이 근거로 단 인용. 04 프로비넌스 필드를 그대로 운반한다."""

    chunk_id: str
    source_id: str
    version: str
    char_start: int
    char_end: int
    quote: str


class Answer(BaseModel):
    """인용이 붙은 답변. backend 로 어떤 경로(llm/extractive)였는지 기록한다."""

    question: str
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    backend: str = Field(..., description="'claude' 또는 'extractive-fallback'.")


def _to_citation(c: Chunk) -> Citation:
    return Citation(
        chunk_id=c.chunk_id,
        source_id=c.source_id,
        version=c.version,
        char_start=c.char_start,
        char_end=c.char_end,
        quote=c.quote,
    )


def _build_context(chunks: list[Chunk]) -> str:
    """LLM 에 줄 컨텍스트 블록. 각 청크에 [chunk_id] 라벨을 달아 인용을 유도한다."""
    blocks = []
    for c in chunks:
        blocks.append(f"[{c.chunk_id}] (출처 {c.source_id} {c.version})\n{c.text}")
    return "\n\n".join(blocks)


def _answer_with_claude(question: str, chunks: list[Chunk]) -> Answer:
    """Claude 로 인용 답변 생성. 키 있을 때만 호출된다."""
    import anthropic  # 키 있을 때만 import.

    client = anthropic.Anthropic()  # ANTHROPIC_API_KEY 자동 사용.
    context = _build_context(chunks)
    system = (
        "너는 RAG 어시스턴트다. 아래 컨텍스트 안의 내용만으로 답한다. "
        "각 주장 끝에 근거 청크의 [chunk_id] 를 대괄호로 인용한다. "
        "컨텍스트에 없으면 모른다고 답한다. 답은 한국어로, 3~5문장으로 간결히."
    )
    msg = client.messages.create(
        model=LLM_MODEL,
        max_tokens=512,
        system=system,
        messages=[{"role": "user", "content": f"컨텍스트:\n{context}\n\n질문: {question}"}],
    )
    text = "".join(block.text for block in msg.content if block.type == "text")
    return Answer(
        question=question,
        answer=text.strip(),
        citations=[_to_citation(c) for c in chunks],
        backend="claude",
    )


def _answer_extractive(question: str, chunks: list[Chunk], top: int = 3) -> Answer:
    """추출형 폴백. 상위 청크 quote 를 인용과 함께 묶는다. 네트워크 0.

    LLM 생성이 아니라 근거 발췌다. 각 줄 끝에 [chunk_id] 를 단다.
    """
    used = chunks[:top]
    lines = [f"질문 '{question}' 에 대한 근거 발췌(추출형 폴백):"]
    for c in used:
        snippet = c.text.strip().replace("\n", " ")
        if len(snippet) > 160:
            snippet = snippet[:160] + "…"
        lines.append(f"- {snippet} [{c.chunk_id}]")
    return Answer(
        question=question,
        answer="\n".join(lines),
        citations=[_to_citation(c) for c in used],
        backend="extractive-fallback",
    )


def answer_with_citations(question: str, chunks: list[Chunk]) -> Answer:
    """검색된 청크로 인용 답변을 만든다. 키 있으면 Claude, 없으면 추출형 폴백."""
    if not chunks:
        return Answer(question=question, answer="검색 결과가 없다.", citations=[], backend="none")
    if os.environ.get("ANTHROPIC_API_KEY"):
        return _answer_with_claude(question, chunks)
    return _answer_extractive(question, chunks)


if __name__ == "__main__":
    # 빠른 자기점검: hybrid 검색 → 인용 답변 1건.
    from load_chunks import load_chunks, load_index
    from hybrid_search import HybridSearcher

    chunks = load_chunks()
    index = load_index()
    hs = HybridSearcher(chunks, index)
    q = "GraphRAG 는 전역 요약 질문을 어떻게 다루나?"
    ctx = hs.context_chunks(q, k=5)
    ans = answer_with_citations(q, ctx)
    print(f"[answer] backend={ans.backend}\n")
    print(ans.answer)
    print("\n인용:")
    for c in ans.citations:
        print(f"  [{c.chunk_id}]  {c.source_id} {c.version}  [{c.char_start}:{c.char_end}]")
