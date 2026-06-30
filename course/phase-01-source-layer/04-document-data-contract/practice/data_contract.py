"""data_contract.py — 문서 1건의 Data Contract (Pydantic v2).

Data Contract = 문서 한 건이 다운스트림(검색·추출·인용·삭제권)에 제공하기로
약속한 '안정적 인터페이스'다. ID 가 같으면 같은 문서, version 이 같으면 같은 내용,
span 이 가리키면 그 자리에 정확히 그 텍스트가 있다 — 이 약속들을 코드로 강제한다.

02 의 WikiFrontmatter(title·source_id·tags·aliases·links 5필드)를 그대로 품고,
04 에서 계약 필드 다섯을 더 얹는다:
    stable ID(=source_id, 불변) · version(revision+content_hash) ·
    source span(문자 offset) · ACL(접근 제어) · provenance(가공 이력).

설계 메모:
  - 02 의 WikiFrontmatter 를 import 확장하지 않는다. 토픽 독립 실행을 위해
    SLUG_RE·5필드 검증을 이 파일 안에서 자기완결적으로 복제한다(아래 주석 참고).
    원본은 ../02-markdown-yaml-wikilink/practice/wiki_schema.py.
  - content_hash 계산·version 포맷은 provenance.py(모델 비의존 순수 함수)에 위임한다.

전제: 네트워크·API 키·Neo4j 불필요. 순수 로컬 Pydantic v2 + 표준 라이브러리.
의존: pydantic>=2. (provenance.py 는 같은 폴더의 로컬 모듈.)
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

import provenance as prov

# ─────────────────────────────────────────────────────────────────────────────
# 02 wiki_schema.py 의 SLUG_RE 를 그대로 복제한다(import 의존을 만들지 않으려고).
# 규칙: 소문자 영문/숫자로 시작, 소문자·숫자·하이픈만.
# ─────────────────────────────────────────────────────────────────────────────
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class SourceSpan(BaseModel):
    """원문 안의 한 구간을 '문자 offset (start, end)' 로 가리킨다.

    답변·클레임이 "이 문장에서 나왔다"고 말할 때 그 위치가 바로 SourceSpan 이다.
    라인 번호가 아니라 문자 offset 으로 잡는 이유: 본문을 재정규화하거나 한글·유니코드가
    섞이면 라인 경계가 흔들린다. 문자 offset 은 text[start:end] 로 곧장 검증된다.

    quote 는 '검증용 사본'이다. text[start:end] == quote 가 성립해야 span 이 건강하다.
    (text 자체는 모델에 담지 않는다 — 계약은 위치만 약속하고, 본문은 원본이 보관한다.)
    """

    source_id: str = Field(..., description="이 span 이 속한 문서의 stable ID.")
    start: int = Field(..., ge=0, description="구간 시작 문자 offset(포함).")
    end: int = Field(..., gt=0, description="구간 끝 문자 offset(미포함). text[start:end].")
    quote: str | None = Field(
        default=None,
        description="검증용 인용 사본. text[start:end] 와 정확히 일치해야 한다.",
    )

    @model_validator(mode="after")
    def _check_range(self) -> SourceSpan:
        # 빈 구간·역전 구간을 막는다. end<=len(text) 는 text 를 아는 쪽(검증 스크립트)이 확인한다.
        if self.start >= self.end:
            raise ValueError(f"span 은 start < end 여야 한다: start={self.start}, end={self.end}")
        return self

    def verify_against(self, text: str) -> bool:
        """원문 text 와 대조한다. end 가 길이를 넘거나 quote 가 어긋나면 False."""
        if self.end > len(text):
            return False
        sliced = text[self.start : self.end]
        if self.quote is not None and sliced != self.quote:
            return False
        return True


class ACL(BaseModel):
    """접근 제어(Access Control List). 누가 이 문서를 답변 근거로 쓸 수 있나.

    검색은 됐는데 권한 없는 문서가 답변에 인용되면 그게 사고다. 그래서 계약 단계에서
    visibility 를 못 박는다. Phase 5 에서 이 필드를 답변 시점 '정책 게이트'로 확장한다.
    여기서는 최소한으로만: visibility + allow 그룹 목록.
    """

    visibility: Literal["public", "internal", "restricted"] = Field(
        default="internal",
        description="공개 범위. restricted 는 allow 목록에 든 그룹만.",
    )
    allow: list[str] = Field(
        default_factory=list,
        description="restricted 일 때 접근 가능한 그룹·역할 목록. 예: ['research', 'admin'].",
    )


class ProvenanceStep(BaseModel):
    """가공 이력 체인의 한 단계. '어디서 와서 어떤 손을 거쳤나'의 한 칸."""

    stage: str = Field(..., description="단계 이름. 예: source / parse / normalize / wiki.")
    tool: str | None = Field(default=None, description="그 단계에서 쓴 도구. 예: docling, mineru.")
    note: str | None = Field(default=None, description="사람이 읽을 짧은 메모.")


class Provenance(BaseModel):
    """출처·가공 이력 전체. 답변→원문 역추적의 뼈대.

    parser 는 03 에서 고른 파서명(docling/mineru/none)을 따로 끌어올려 둔다.
    "표가 살아남은 파서였나"를 한 필드로 바로 보게 하려는 것이다.
    """

    origin: str = Field(..., description="원본 위치. URL 또는 로컬 파일 경로.")
    retrieved_at: str = Field(..., description="획득 시각. 문자열(ISO8601 권장). 예: 2026-06-30.")
    parser: str = Field(default="none", description="03 에서 쓴 파서. docling/mineru/none.")
    steps: list[ProvenanceStep] = Field(
        default_factory=list,
        description="원문→파싱→정규화→wiki 가공 단계 목록.",
    )


class DocumentContract(BaseModel):
    """문서 1건의 완결된 Data Contract.

    02 의 5필드(title·source_id·tags·aliases·links) +
    04 의 계약 필드(revision·content_hash·acl·provenance).

    'version' 은 따로 저장하지 않는다. revision + content_hash 로부터 항상 파생한다
    (single source of truth). version 프로퍼티로 'v{n}@{hash}' 를 만들어 보여 준다.
    """

    # ── 02 WikiFrontmatter 계승 5필드 ──────────────────────────────────────
    title: str = Field(..., description="문서 제목(원본 첫 H1).")
    source_id: str = Field(..., description="01/02 의 stable ID. 불변 식별자.", examples=["src-01-rag"])
    tags: list[str] = Field(default_factory=list, description="주제 태그. 소문자·하이픈만.")
    aliases: list[str] = Field(default_factory=list, description="이 문서를 가리키는 다른 이름.")
    links: list[str] = Field(default_factory=list, description="본문 [[...]] 가 가리키는 대상 source_id 목록.")

    # ── 04 계약 필드 ───────────────────────────────────────────────────────
    revision: int = Field(default=1, ge=1, description="단조 증가 정수. 내용이 바뀌면 올린다(순서 책임).")
    content_hash: str = Field(..., description="정규화 본문의 sha256 short. 내용 동일성 책임.")
    acl: ACL = Field(default_factory=ACL, description="접근 제어.")
    provenance: Provenance = Field(..., description="출처·가공 이력 체인.")

    # ── 02 와 동일한 표기 검증을 복제 ─────────────────────────────────────
    @field_validator("source_id")
    @classmethod
    def _source_id_format(cls, v: str) -> str:
        # 01/02 규약 재사용: src- 접두 + 소문자·숫자·하이픈.
        if not v.startswith("src-"):
            raise ValueError(f"source_id 는 'src-' 로 시작해야 한다: {v!r}")
        rest = v[len("src-") :]
        if not SLUG_RE.match(rest):
            raise ValueError(f"source_id 는 src- 뒤가 소문자·숫자·하이픈이어야 한다: {v!r}")
        return v

    @field_validator("tags")
    @classmethod
    def _tags_format(cls, v: list[str]) -> list[str]:
        for t in v:
            if not SLUG_RE.match(t):
                raise ValueError(f"tag 는 소문자·숫자·하이픈만 허용: {t!r}")
        if len(v) != len(set(v)):
            raise ValueError(f"중복 tag 가 있다: {v!r}")
        return v

    @field_validator("links")
    @classmethod
    def _links_format(cls, v: list[str]) -> list[str]:
        for sid in v:
            if not sid.startswith("src-"):
                raise ValueError(f"links 항목은 대상 source_id 여야 한다(src-...): {sid!r}")
        return v

    @property
    def version(self) -> str:
        """revision + content_hash 에서 파생하는 version 문자열. 예: 'v1@ab12cd34'."""
        return prov.make_version(self.revision, self.content_hash)

    @classmethod
    def from_document(
        cls,
        text: str,
        *,
        source_id: str,
        title: str,
        origin: str,
        retrieved_at: str,
        parser: str = "none",
        tags: list[str] | None = None,
        aliases: list[str] | None = None,
        links: list[str] | None = None,
        revision: int = 1,
        acl: ACL | None = None,
    ) -> DocumentContract:
        """본문 text 로부터 계약을 빌드한다. content_hash 를 여기서 계산한다.

        본문이 1글자만 바뀌어도 content_hash 가 바뀐다(version 도 따라 바뀐다).
        provenance 체인은 표준 4단계(source→parse→normalize→wiki)로 채운다.
        """
        ch = prov.content_hash(text, short=True)
        steps = [ProvenanceStep(**step) for step in prov.default_chain(parser=parser)]
        return cls(
            title=title,
            source_id=source_id,
            tags=tags or [],
            aliases=aliases or [],
            links=links or [],
            revision=revision,
            content_hash=ch,
            acl=acl or ACL(),
            provenance=Provenance(
                origin=origin,
                retrieved_at=retrieved_at,
                parser=parser,
                steps=steps,
            ),
        )


if __name__ == "__main__":
    # 빠른 자기점검: 본문에서 계약을 빌드하고 직렬화해 본다.
    sample = "# 검색 증강 생성(RAG)\n\nRAG 는 외부 문서를 검색해 LLM 생성에 근거를 붙인다.\n"
    c = DocumentContract.from_document(
        sample,
        source_id="src-01-rag",
        title="검색 증강 생성(RAG)",
        origin="local://sources/01-rag.md",
        retrieved_at="2026-06-30",
        parser="none",
        tags=["rag", "foundation"],
    )
    print("source_id:", c.source_id)
    print("version  :", c.version)
    print("hash     :", c.content_hash)
    print("steps    :", [s.stage for s in c.provenance.steps])
