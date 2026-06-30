"""chunker.py — section-aware chunking. 섹션 경계를 가로지르지 않는 청킹.

핵심 약속(이게 section-aware 의 전부다):
  - 한 청크는 한 섹션 '안'에서만 존재한다. 절대 섹션 경계를 넘지 않는다.
    순진한 고정길이 청킹은 ## 헤딩 한복판을 잘라 맥락·인용을 깬다. 그걸 막는다.
  - 섹션이 토큰 예산보다 길면 문단/문장 경계에서 sub-chunk 로 쪼갠다.
    선택적 overlap(기본 1문장)을 줘서 경계 문장이 어느 한쪽에는 온전히 담기게 한다.
  - 짧은 섹션은 통째로 1청크.

청크가 무는 메타(06 Baseline RAG 가 색인·인용에 쓴다):
  chunk_id · source_id · version · section_path · heading ·
  char_start · char_end(본문 body 기준 offset) · token_estimate · text · quote.

04 SourceSpan 정합성 재사용:
  청크의 (char_start, char_end)는 body[char_start:char_end] == text 를 만족해야 한다.
  즉 청크 수준에서도 "청크→문서→원문" 인용 사슬이 끊기지 않는다. verify() 가 이걸 확인한다.

chunk_id 설계:
  f"{source_id}#s{section_idx}-{ordinal}". '위치 식별자'다.
  내용이 바뀌어도 같은 위치면 같은 id 를 준다 — 내용 변화는 version 이 책임진다.
  (06 에서 chunk_id 로 검색 결과를 안정적으로 참조·중복 제거하려면 위치 안정성이 필요하다.)

토큰 추정:
  의존성 가벼운 휴리스틱으로 센다(영문 단어수 + 한글/CJK 글자수 근사).
  정확히 세려면 tiktoken 을 선택적으로 쓸 수 있으나, 기본 경로는 네트워크·추가 의존이 없다.

전제: 네트워크·API 키·LLM 불필요. 순수 로컬.
의존: pydantic>=2. (wiki_parser.Section 을 입력으로 받는다.)
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from wiki_parser import Section

# CJK(한글·한자·가나) 글자 범위. 휴리스틱 토큰 추정에서 글자 1개를 토큰 1개로 근사한다.
_CJK_RE = re.compile(r"[　-〿぀-ヿ㐀-䶿一-鿿가-힣]")
# 영문/숫자 단어. 단어 1개를 토큰 ~1.3개로 근사(아래 estimate_tokens 참고).
_WORD_RE = re.compile(r"[A-Za-z0-9]+")
# 문장 끝 경계(한국어·영어 공용 근사). 마침표·물음표·느낌표 + 공백/개행.
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?。！？])\s+")


def estimate_tokens(text: str) -> int:
    """의존성 없는 토큰 추정. CJK 글자수 + 영문 단어수×1.3 를 더한다.

    정확한 값이 필요하면 tiktoken 으로 교체할 수 있다(선택). 기본 경로는 휴리스틱이라
    네트워크·추가 의존이 없고, 청킹 예산을 가르는 용도로는 충분하다.
    """
    cjk = len(_CJK_RE.findall(text))
    words = len(_WORD_RE.findall(text))
    return cjk + round(words * 1.3)


class Chunk(BaseModel):
    """청크 1건. 검색·인용의 최소 단위이자 06 색인 대상."""

    chunk_id: str = Field(..., description="위치 식별자. f'{source_id}#s{sec}-{ord}'. 안정적.")
    source_id: str = Field(..., description="소속 문서 stable ID.")
    version: str = Field(..., description="문서 version. 04 make_version 산출. 예: v1@ab12cd34.")
    section_path: list[str] = Field(default_factory=list, description="루트부터의 헤딩 경로.")
    heading: str = Field(default="", description="이 청크가 속한 섹션의 헤딩.")
    char_start: int = Field(..., ge=0, description="body 기준 시작 offset(포함).")
    char_end: int = Field(..., ge=0, description="body 기준 끝 offset(미포함).")
    token_estimate: int = Field(..., ge=0, description="추정 토큰 수(휴리스틱).")
    text: str = Field(..., description="청크 본문.")
    quote: str = Field(..., description="text 앞부분 사본(04 SourceSpan 정합 검증·미리보기용).")

    def verify(self, body: str) -> bool:
        """04 SourceSpan 계약을 청크 수준에서 검증. body[char_start:char_end] == text."""
        if self.char_end > len(body):
            return False
        return body[self.char_start : self.char_end] == self.text


# quote 미리보기 길이. text 앞부분만 사본으로 둔다.
QUOTE_LEN = 60


def _sentence_spans(text: str) -> list[tuple[int, int]]:
    """text 를 문장 경계로 끊어 (start, end) offset 목록으로 돌려준다(text 기준 상대 offset).

    경계가 없으면 text 전체를 한 문장으로 본다. 빈 꼬리는 만들지 않는다.
    """
    spans: list[tuple[int, int]] = []
    cursor = 0
    for m in _SENT_SPLIT_RE.finditer(text):
        end = m.start()
        if end > cursor:
            spans.append((cursor, end))
        cursor = m.end()
    if cursor < len(text):
        spans.append((cursor, len(text)))
    return spans or [(0, len(text))]


def _split_section_body(
    body: str, sec: Section, max_tokens: int, overlap_sentences: int
) -> list[tuple[int, int]]:
    """한 섹션 본문을 토큰 예산 안의 sub-chunk (abs_start, abs_end) 목록으로 쪼갠다.

    문장 경계를 모아 예산(max_tokens)을 넘기 직전까지 한 청크로 묶는다.
    overlap_sentences 만큼 앞 청크의 끝 문장을 다음 청크 앞에 겹쳐 준다
    (경계 문장이 어느 한쪽에는 온전히 담기게).
    offset 은 body(문서 본문) 기준 절대 offset 으로 환산해 돌려준다.
    """
    sec_text = sec.body_text(body)
    # 앞뒤 공백을 떼되 그만큼 offset 을 보정한다(빈 청크 방지 + offset 정합 유지).
    lstripped = sec_text.lstrip()
    lead = len(sec_text) - len(lstripped)
    inner = lstripped.rstrip()
    base = sec.char_start + lead  # body 기준, 실제 본문이 시작하는 offset
    if not inner:
        return []  # 헤딩만 있고 본문이 빈 섹션은 청크를 만들지 않는다.

    # 섹션 전체가 예산 안이면 통째로 1청크.
    if estimate_tokens(inner) <= max_tokens:
        return [(base, base + len(inner))]

    sents = _sentence_spans(inner)  # inner 기준 상대 offset
    chunks: list[tuple[int, int]] = []
    cur_start_idx = 0
    while cur_start_idx < len(sents):
        budget = 0
        end_idx = cur_start_idx
        # 예산을 넘기 직전까지 문장을 모은다(최소 1문장은 보장).
        while end_idx < len(sents):
            s0, s1 = sents[end_idx]
            t = estimate_tokens(inner[s0:s1])
            if budget + t > max_tokens and end_idx > cur_start_idx:
                break
            budget += t
            end_idx += 1
        abs_start = base + sents[cur_start_idx][0]
        abs_end = base + sents[end_idx - 1][1]
        chunks.append((abs_start, abs_end))
        if end_idx >= len(sents):
            break
        # overlap: 다음 청크를 끝에서 overlap_sentences 만큼 앞당겨 시작.
        cur_start_idx = max(end_idx - overlap_sentences, cur_start_idx + 1)
    return chunks


def chunk_document(
    *,
    body: str,
    sections: list[Section],
    source_id: str,
    version: str,
    max_tokens: int = 220,
    overlap_sentences: int = 1,
) -> list[Chunk]:
    """문서 본문 + 섹션 목록 -> Chunk 목록. 섹션 경계를 절대 넘지 않는다.

    각 섹션을 독립적으로 청킹한다(그래서 한 청크는 한 섹션 안에만 존재한다).
    chunk_id 는 (섹션 인덱스, 섹션 내 순번)으로 안정적으로 매긴다.
    """
    chunks: list[Chunk] = []
    for sec_idx, sec in enumerate(sections):
        spans = _split_section_body(body, sec, max_tokens, overlap_sentences)
        for ordinal, (start, end) in enumerate(spans):
            text = body[start:end]
            chunks.append(
                Chunk(
                    chunk_id=f"{source_id}#s{sec_idx}-{ordinal}",
                    source_id=source_id,
                    version=version,
                    section_path=sec.section_path,
                    heading=sec.heading,
                    char_start=start,
                    char_end=end,
                    token_estimate=estimate_tokens(text),
                    text=text,
                    quote=text[:QUOTE_LEN],
                )
            )
    return chunks


if __name__ == "__main__":
    # 빠른 자기점검: 멀티섹션 본문을 청킹하고 섹션 경계를 넘지 않는지 확인한다.
    from wiki_parser import parse_wiki

    sample = (
        "# 개요\n\n이 문서는 청킹을 다룬다. 두 문장으로 짧게.\n\n"
        "## 배경\n\n" + ("배경 문장이다. " * 40) + "\n\n"
        "## 결론\n\n결론 한 문장.\n"
    )
    parsed = parse_wiki(sample)
    chunks = chunk_document(
        body=parsed.body,
        sections=parsed.sections,
        source_id="src-99-sample",
        version="v1@deadbeef",
        max_tokens=80,
    )
    for c in chunks:
        ok = "OK" if c.verify(parsed.body) else "BAD"
        print(f"  [{ok}] {c.chunk_id}  path={c.section_path}  tok={c.token_estimate}  {c.quote[:30]!r}")
