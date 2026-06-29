"""Source Layer 의 최소 데이터 단위 — SourceRecord (Pydantic v2).

이 토픽(01)은 "신뢰 가능한 원본 레이어"의 출발점이다.
원본 파일 하나하나를 Agent 가 나중에 인용할 수 있도록, 최소한의 메타와 무결성 정보를 붙인다.

여기서 정의하는 필드는 풀 Data Contract 스펙이 아니라 최소 골격이다.
stable ID·version·source span·ACL·provenance 의 완전한 계약은 04번 토픽에서 다룬다.

전제: 네트워크·API 키·Neo4j 불필요. 순수 로컬 파일 + 메타 + 해시만 다룬다.
의존: pydantic v2.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field, field_validator


def utc_now_iso() -> str:
    """수집 시각을 UTC ISO-8601 문자열로 만든다(타임존 명시)."""
    return datetime.now(timezone.utc).isoformat()


class SourceRecord(BaseModel):
    """Source Layer 에 편입된 원본 한 건의 메타.

    핵심은 두 가지다.
      1) source_id — 단계가 바뀌어도 안 변하는 안정 식별자(stable ID). 이후 KG·Agent 가 이 ID 로 원본을 가리킨다.
      2) sha256    — 내용 무결성 지문. 같은 ID 인데 해시가 다르면 원본이 바뀐 것이다(프로비넌스의 최소 단위).
    """

    source_id: str = Field(
        ...,
        description="안정 식별자(stable ID). 파일명·경로가 바뀌어도 유지되도록 부여한다.",
        examples=["src-01-rag"],
    )
    title: str = Field(..., description="원본 제목. Markdown 첫 H1 또는 파일명에서 추출.")
    path: str = Field(
        ...,
        description="Source Layer 루트 기준 상대 경로. 절대 경로를 박으면 환경마다 깨진다.",
        examples=["sources/01-rag.md"],
    )
    sha256: str = Field(..., description="원본 내용의 SHA-256 해시(소문자 hex 64자).")
    bytes: int = Field(..., ge=0, description="원본 바이트 크기.")
    origin: str = Field(
        default="local",
        description="원본 출처 종류. local / arxiv / web / docs 등. 풀 provenance 는 04 에서.",
    )
    origin_url: str | None = Field(
        default=None, description="원본을 가져온 URL(있으면). 없으면 None."
    )
    license: str = Field(
        default="unknown",
        description="라이선스·접근 권한 요약. 미상이면 unknown. 풀 ACL 은 04 에서.",
    )
    ingested_at: str = Field(
        default_factory=utc_now_iso, description="Source Layer 편입 시각(UTC ISO-8601)."
    )

    @field_validator("source_id")
    @classmethod
    def _id_format(cls, v: str) -> str:
        # stable ID 는 소문자·숫자·하이픈만 허용한다. 공백·대문자는 나중에 깨지기 쉽다.
        if not v:
            raise ValueError("source_id 가 비어 있다")
        if not all(ch.islower() or ch.isdigit() or ch == "-" for ch in v):
            raise ValueError(f"source_id 는 소문자·숫자·하이픈만 허용: {v!r}")
        return v

    @field_validator("sha256")
    @classmethod
    def _sha_format(cls, v: str) -> str:
        v = v.lower()
        if len(v) != 64 or any(c not in "0123456789abcdef" for c in v):
            raise ValueError(f"sha256 형식 오류(64자 hex 아님): {v!r}")
        return v


def make_source_id(path: Path, root: Path) -> str:
    """경로에서 stable ID 를 만든다.

    규칙: 루트 기준 상대 경로에서 확장자를 떼고, 디렉토리 구분자를 하이픈으로 바꾼 뒤 'src-' 접두.
      sources/01-rag.md            -> src-01-rag
      sources/papers/self-rag.md   -> src-papers-self-rag

    파일명 자체를 ID 로 쓰므로, 폴더 안에서 파일을 함부로 rename 하면 ID 가 바뀐다는 점을 기억할 것.
    (안정 식별자를 파일명과 분리하는 방법은 04 토픽에서 다룬다.)
    """
    rel = path.relative_to(root).with_suffix("")
    slug = "-".join(rel.parts)
    return f"src-{slug}"
