"""wiki_parser.py — Wiki Markdown 파서. 프런트매터 분리 + 섹션 트리 빌드.

하는 일:
  1) `---` 구분자로 YAML 프런트매터와 본문(body)을 가른다.
     프런트매터가 없으면(02 sources/ 같은 순수 Markdown) 본문 전체를 body 로 본다.
  2) body 안의 ATX 헤딩(#, ##, ###)을 스캔해 '섹션 트리'를 만든다.
     각 섹션은 heading 텍스트·level·section_path(루트부터의 헤딩 경로)·
     body 기준 char offset 범위(start, end)를 갖는다.

설계 메모:
  - offset 은 '본문(body) 문자열' 기준으로 잡는다. 프런트매터는 제외한다.
    body 가 그 문서의 '기록 대상'이고, 04 SourceSpan 도 본문 offset 으로 약속했다.
    청크가 무는 (char_start, char_end)도 같은 body 기준이라야 06 인용이 일관된다.
  - section_path 는 헤딩 레벨 스택으로 만든다. ## 아래 ### 가 오면
    경로가 ['상위 H2', '하위 H3'] 로 누적된다. 이게 section-aware chunking 의 좌표계다.
  - 섹션의 본문 범위는 '그 헤딩 줄 끝 다음'부터 '다음 헤딩 줄 시작 직전'까지다.
    헤딩 줄 자체는 본문에 포함하지 않는다(헤딩 텍스트는 메타로 따로 들고 있으므로).

전제: 네트워크·API 키·LLM·Neo4j 불필요. 순수 로컬.
의존: pydantic>=2, pyyaml.
"""

from __future__ import annotations

import re

import yaml
from pydantic import BaseModel, Field

# ATX 헤딩: 줄 시작의 1~3개 '#' + 공백 + 텍스트. ####+ 는 본문 문단으로 본다(과분할 방지).
HEADING_RE = re.compile(r"^(#{1,3})[ \t]+(.+?)[ \t]*#*\s*$")

# 프런트매터 경계. 문서 첫 줄이 정확히 '---' 일 때만 프런트매터로 인정한다.
FENCE = "---"


class Section(BaseModel):
    """본문 한 섹션. 헤딩 하나와 그 헤딩이 거느리는 본문 범위.

    char_start/char_end 는 body 문자열 기준 offset 이다(body[start:end] 가 섹션 본문).
    헤딩이 전혀 없는 문서는 '루트 섹션' 한 개로 본문 전체를 담는다(heading="", level=0).
    """

    heading: str = Field(..., description="헤딩 텍스트. 루트 섹션은 빈 문자열.")
    level: int = Field(..., ge=0, le=3, description="헤딩 레벨(1~3). 루트 섹션은 0.")
    section_path: list[str] = Field(
        default_factory=list,
        description="루트부터 이 섹션까지의 헤딩 경로. 예: ['배경', '한계'].",
    )
    char_start: int = Field(..., ge=0, description="body 기준 본문 시작 offset(포함).")
    char_end: int = Field(..., ge=0, description="body 기준 본문 끝 offset(미포함).")

    def body_text(self, body: str) -> str:
        """이 섹션의 본문 텍스트. body[char_start:char_end]."""
        return body[self.char_start : self.char_end]


class ParsedWiki(BaseModel):
    """파싱 결과. 프런트매터 dict + 본문 body + 섹션 목록."""

    frontmatter: dict = Field(default_factory=dict, description="YAML 프런트매터. 없으면 빈 dict.")
    body: str = Field(..., description="프런트매터를 뗀 본문 전체.")
    sections: list[Section] = Field(default_factory=list, description="헤딩 기준 섹션 목록.")


def split_frontmatter(text: str) -> tuple[dict, str]:
    """`---` 구분자로 프런트매터와 본문을 가른다.

    첫 줄이 '---' 이고 그 뒤에 닫는 '---' 가 또 나오면 그 사이를 YAML 로 읽는다.
    그렇지 않으면 프런트매터 없음 — text 전체를 본문으로 본다(순수 Markdown 입력 대비).

    반환하는 body 는 lstrip 하지 않는다. offset 안정성을 위해 '닫는 --- 다음 한 줄'까지만
    소비하고 그 뒤 본문은 손대지 않는다(공백 1~2개 차이로 offset 이 흔들리지 않게).
    """
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\n") != FENCE:
        return {}, text

    # 닫는 '---' 찾기
    close_idx = None
    for i in range(1, len(lines)):
        if lines[i].rstrip("\n") == FENCE:
            close_idx = i
            break
    if close_idx is None:
        # 여는 --- 만 있고 닫는 --- 가 없다 → 프런트매터로 취급하지 않는다.
        return {}, text

    fm_block = "".join(lines[1:close_idx])
    body = "".join(lines[close_idx + 1 :])
    # 닫는 --- 바로 다음의 빈 줄 1개만 흡수(02 to_wiki 가 '---\n\n본문' 으로 쓴다).
    if body.startswith("\n"):
        body = body[1:]

    try:
        fm = yaml.safe_load(fm_block) or {}
    except yaml.YAMLError:
        fm = {}
    if not isinstance(fm, dict):
        fm = {}
    return fm, body


def build_sections(body: str) -> list[Section]:
    """body 의 ATX 헤딩을 스캔해 섹션 목록을 만든다.

    헤딩 스택으로 section_path 를 누적한다. 새 헤딩 레벨 L 을 만나면
    스택에서 레벨 >= L 인 항목을 모두 비우고 자신을 쌓는다.
    헤딩이 하나도 없으면 루트 섹션 1개(level 0)로 본문 전체를 담는다.
    """
    # (offset, level, heading_text, line_end_offset) 목록을 먼저 모은다.
    heads: list[tuple[int, int, str, int]] = []
    pos = 0
    for line in body.splitlines(keepends=True):
        m = HEADING_RE.match(line.rstrip("\n"))
        if m:
            level = len(m.group(1))
            heading_text = m.group(2).strip()
            line_end = pos + len(line)  # 헤딩 줄 끝(= 섹션 본문 시작점)
            heads.append((pos, level, heading_text, line_end))
        pos += len(line)

    if not heads:
        # 헤딩 없음 → 루트 섹션 하나. 본문 전체.
        return [
            Section(heading="", level=0, section_path=[], char_start=0, char_end=len(body))
        ]

    sections: list[Section] = []
    stack: list[tuple[int, str]] = []  # (level, heading) — section_path 누적용

    # 첫 헤딩 앞에 본문(서문)이 있으면 루트 섹션으로 한 번 잡아 둔다.
    first_head_start = heads[0][0]
    if body[:first_head_start].strip():
        sections.append(
            Section(heading="", level=0, section_path=[], char_start=0, char_end=first_head_start)
        )

    for idx, (h_start, level, heading_text, line_end) in enumerate(heads):
        # 스택에서 자신과 같거나 깊은 레벨을 비운다(형제·하위 섹션 진입).
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, heading_text))
        section_path = [h for _, h in stack]

        # 본문 끝 = 다음 헤딩 시작 직전. 마지막 헤딩이면 body 끝까지.
        next_start = heads[idx + 1][0] if idx + 1 < len(heads) else len(body)
        sections.append(
            Section(
                heading=heading_text,
                level=level,
                section_path=section_path,
                char_start=line_end,   # 헤딩 줄 다음부터가 본문
                char_end=next_start,   # 다음 헤딩 직전까지
            )
        )
    return sections


def parse_wiki(text: str) -> ParsedWiki:
    """Wiki Markdown(또는 순수 Markdown) 한 건을 ParsedWiki 로 파싱한다."""
    frontmatter, body = split_frontmatter(text)
    sections = build_sections(body)
    return ParsedWiki(frontmatter=frontmatter, body=body, sections=sections)


if __name__ == "__main__":
    # 빠른 자기점검: 프런트매터 + 멀티섹션 본문을 파싱해 섹션 경로를 출력한다.
    sample = (
        "---\n"
        "title: 샘플\n"
        "source_id: src-99-sample\n"
        "---\n\n"
        "# 개요\n\n서문 문단.\n\n"
        "## 배경\n\n배경 본문.\n\n"
        "### 한계\n\n한계 본문.\n\n"
        "## 결론\n\n결론 본문.\n"
    )
    parsed = parse_wiki(sample)
    print("frontmatter:", parsed.frontmatter)
    print("sections:")
    for s in parsed.sections:
        path = " > ".join(s.section_path) if s.section_path else "(root)"
        print(f"  L{s.level} [{path}]  ({s.char_start},{s.char_end})  {s.body_text(parsed.body)!r}")
