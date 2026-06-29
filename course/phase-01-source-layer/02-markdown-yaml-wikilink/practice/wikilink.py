"""wikilink.py — [[target]] / [[target|alias]] 파싱·해소 유틸.

WikiLink 는 위키에서 문서끼리 잇는 가장 가벼운 방법이다. 본문에 [[대상]] 만 적으면 링크가 된다.
표기는 Obsidian·위키 관례를 따른다.
  [[src-02-self-rag]]              -> 대상 src-02-self-rag, 화면 표시도 src-02-self-rag
  [[src-02-self-rag|Self-RAG]]     -> 대상 src-02-self-rag, 화면 표시는 "Self-RAG"(alias)

이 토픽에서 [[...]] 의 '대상'은 다른 문서의 source_id 로 통일한다.
사람이 읽는 이름(Self-RAG)은 alias 로 따로 둔다. 이렇게 해야 제목이 바뀌어도 링크가 안 깨진다.

이 [[...]] 연결이 Phase 2 KG 의 '문서 간 관계(Document-DocumentLink)' 의 씨앗이 된다.
다만 WikiLink 자체는 의미 없는 '관련 있음' 수준의 약한 엣지라는 점을 기억할 것 —
관계의 종류(파생됨/사용함 등)는 Phase 2 에서 본문을 다시 읽어 라벨링한다.

전제: 네트워크·API 키 불필요. 순수 문자열 처리.
의존: 표준 라이브러리만.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# [[target]] 또는 [[target|alias]]. target/alias 안의 ']' 와 '|' 는 허용하지 않는다.
WIKILINK_RE = re.compile(r"\[\[([^\[\]\|]+?)(?:\|([^\[\]\|]+?))?\]\]")


@dataclass(frozen=True)
class WikiLink:
    """본문에서 발견한 WikiLink 한 건."""

    target: str  # 가리키는 대상(이 토픽에서는 대상 문서의 source_id)
    alias: str | None  # 화면 표시 이름(없으면 target 을 그대로 표시)
    raw: str  # 원본 [[...]] 문자열 그대로

    @property
    def display(self) -> str:
        """화면에 보일 텍스트. alias 가 있으면 alias, 없으면 target."""
        return self.alias if self.alias else self.target


def parse_wikilinks(text: str) -> list[WikiLink]:
    """본문 문자열에서 모든 [[...]] 를 찾아 WikiLink 목록으로 돌려준다.

    같은 링크가 여러 번 나오면 여러 건으로 잡힌다(중복 제거는 호출자 몫).
    """
    links: list[WikiLink] = []
    for m in WIKILINK_RE.finditer(text):
        target = m.group(1).strip()
        alias = m.group(2).strip() if m.group(2) else None
        links.append(WikiLink(target=target, alias=alias, raw=m.group(0)))
    return links


def unique_targets(text: str) -> list[str]:
    """본문에서 가리키는 대상 source_id 들을 등장 순서대로, 중복 없이 반환한다.

    프런트매터 links 필드를 본문에서 자동 도출할 때 쓴다(본문과 메타가 어긋나지 않게).
    """
    seen: list[str] = []
    for link in parse_wikilinks(text):
        if link.target not in seen:
            seen.append(link.target)
    return seen


def resolve(target: str, known_ids: set[str], aliases: dict[str, str]) -> str | None:
    """링크 대상을 실제 source_id 로 해소한다.

    1) target 이 이미 알려진 source_id 면 그대로 반환.
    2) target 이 어떤 문서의 alias 면, 그 문서의 source_id 로 바꿔 반환.
    3) 둘 다 아니면 None(= dangling link, 가리키는 문서가 없음).

    aliases: { 별칭(소문자) -> source_id } 매핑.
    """
    if target in known_ids:
        return target
    sid = aliases.get(target.lower())
    if sid is not None:
        return sid
    return None
