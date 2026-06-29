"""wiki_schema.py — LLM Wiki 문서의 YAML 프런트매터 스키마 (Pydantic v2).

이 토픽(02)은 01에서 만든 신뢰 가능한 원본을 LLM·Agent 가 읽기 좋은 Wiki 문서로 구조화한다.
구조화의 핵심은 본문 위에 얹는 YAML 프런트매터다. 여기서 그 프런트매터를 표현하는 모델을 정의한다.

프런트매터에 담는 것:
  - title   : 문서 제목(원본 첫 H1).
  - source_id : 01 의 stable ID 규약을 그대로 재사용한다(src-01-rag 형태). 원본과의 연결 고리.
  - tags    : 주제 분류용 태그. 표기를 강하게 통제한다(소문자·하이픈만) — 안 그러면 곧 난립한다.
  - aliases : 이 문서를 가리키는 다른 이름. WikiLink 해소·검색에 쓰인다.
  - links   : 이 문서가 본문에서 [[...]] 로 가리키는 대상 source_id 목록(WikiLink 의 메타 사본).

주의: 이 스키마는 Markdown/YAML/WikiLink/tag 구조화에만 집중한다.
version·source span·ACL·provenance 를 포함한 풀 Data Contract 는 04 토픽에서 다룬다.
여기서는 source_id 만 계약의 씨앗으로 넣고, 나머지 계약 필드는 04 로 미룬다.

전제: 네트워크·API 키·Neo4j 불필요. 순수 로컬 파일 + YAML 파싱만 다룬다.
의존: pydantic v2, pyyaml.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator

# tag·source_id 표기 규칙: 소문자 영문/숫자로 시작, 소문자·숫자·하이픈만.
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class WikiFrontmatter(BaseModel):
    """Wiki 문서 한 건의 프런트매터.

    extra 필드는 막지 않는다(forbid 아님) — 04 에서 계약 필드가 늘어날 때를 위해 열어 둔다.
    다만 여기서 검증하는 5개 필드의 표기 규칙은 엄격하게 잡는다.
    """

    title: str = Field(..., description="문서 제목. 원본 Markdown 첫 H1 에서 가져온다.")
    source_id: str = Field(
        ...,
        description="01 의 stable ID 를 재사용. 원본과 Wiki 문서를 잇는 고리.",
        examples=["src-01-rag"],
    )
    tags: list[str] = Field(
        default_factory=list,
        description="주제 분류 태그. 소문자·하이픈만. 표기가 흔들리면 같은 주제가 갈라진다.",
    )
    aliases: list[str] = Field(
        default_factory=list,
        description="이 문서를 가리키는 다른 이름. WikiLink 해소·검색에 쓴다.",
    )
    links: list[str] = Field(
        default_factory=list,
        description="본문 [[...]] 가 가리키는 대상 source_id 목록. Phase 2 KG '문서 간 관계'의 씨앗.",
    )

    @field_validator("source_id")
    @classmethod
    def _source_id_format(cls, v: str) -> str:
        # 01 규약 재사용: src- 접두 + 소문자·숫자·하이픈.
        if not v.startswith("src-"):
            raise ValueError(f"source_id 는 'src-' 로 시작해야 한다: {v!r}")
        if not all(ch.islower() or ch.isdigit() or ch == "-" for ch in v):
            raise ValueError(f"source_id 는 소문자·숫자·하이픈만 허용: {v!r}")
        return v

    @field_validator("tags")
    @classmethod
    def _tags_format(cls, v: list[str]) -> list[str]:
        # 태그는 표기를 강하게 통제한다. "RAG", "rag ", "Rag" 가 섞이면 분류가 깨진다.
        for t in v:
            if not SLUG_RE.match(t):
                raise ValueError(
                    f"tag 는 소문자·숫자·하이픈만 허용(공백·대문자·언더스코어 금지): {t!r}"
                )
        # 중복 태그도 막는다.
        if len(v) != len(set(v)):
            raise ValueError(f"중복 tag 가 있다: {v!r}")
        return v

    @field_validator("links")
    @classmethod
    def _links_format(cls, v: list[str]) -> list[str]:
        # links 는 대상 source_id 목록이므로 source_id 형식을 따른다.
        for sid in v:
            if not sid.startswith("src-"):
                raise ValueError(f"links 항목은 대상 source_id 여야 한다(src-...): {sid!r}")
        return v
