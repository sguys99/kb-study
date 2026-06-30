"""metadata_index.py — metadata index 구축. chunk_id 정방향 + tag/source 역인덱스.

06 Baseline RAG 가 검색·필터·인용에 쓰는 색인이다. 두 방향을 같이 둔다.

  정방향(forward):  chunk_id -> {source_id, version, section_path, tags,
                                acl_visibility, char_start, char_end, token_estimate}
      검색 결과로 받은 chunk_id 로 메타를 즉시 끌어와 인용·필터·정책 판정에 쓴다.

  역인덱스(inverted):
      tag -> [chunk_id...]          # 06 에서 'rag 태그 문서만' 같은 태그 필터 검색에 쓴다.
      source_id -> [chunk_id...]    # 한 문서의 모든 청크를 모아 문서 단위로 다룰 때.

text 본문은 인덱스에 넣지 않는다(인덱스는 가볍게, 본문은 chunks.jsonl 이 보관).
JSON 으로 직렬화/역직렬화한다. ensure_ascii=False 로 한글이 \\uXXXX 로 깨지지 않게 한다.

전제: 네트워크·API 키 불필요. 순수 로컬.
의존: pydantic>=2. (chunker.Chunk 를 입력으로 받는다.)
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from chunker import Chunk


class ChunkMeta(BaseModel):
    """정방향 인덱스의 값. 청크 본문(text)을 뺀 메타만 담는다."""

    source_id: str
    version: str
    section_path: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    acl_visibility: str = Field(default="internal")
    char_start: int
    char_end: int
    token_estimate: int


class MetadataIndex(BaseModel):
    """metadata index 전체. 정방향 + 두 역인덱스."""

    forward: dict[str, ChunkMeta] = Field(default_factory=dict)
    by_tag: dict[str, list[str]] = Field(default_factory=dict)
    by_source: dict[str, list[str]] = Field(default_factory=dict)

    def add(self, chunk: Chunk, *, tags: list[str], acl_visibility: str) -> None:
        """청크 1건을 인덱스에 등록한다. tags·acl 은 문서 단위 메타에서 주입받는다."""
        self.forward[chunk.chunk_id] = ChunkMeta(
            source_id=chunk.source_id,
            version=chunk.version,
            section_path=chunk.section_path,
            tags=tags,
            acl_visibility=acl_visibility,
            char_start=chunk.char_start,
            char_end=chunk.char_end,
            token_estimate=chunk.token_estimate,
        )
        for t in tags:
            self.by_tag.setdefault(t, []).append(chunk.chunk_id)
        self.by_source.setdefault(chunk.source_id, []).append(chunk.chunk_id)

    def chunks_for_tag(self, tag: str) -> list[str]:
        """태그로 chunk_id 역조회. 없으면 빈 목록."""
        return self.by_tag.get(tag, [])

    def chunks_for_source(self, source_id: str) -> list[str]:
        """문서 source_id 로 그 문서의 모든 chunk_id 역조회."""
        return self.by_source.get(source_id, [])

    def to_json(self, path: Path) -> None:
        """JSON 파일로 직렬화. ensure_ascii=False 로 한글 보존."""
        path.write_text(
            json.dumps(self.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @classmethod
    def from_json(cls, path: Path) -> "MetadataIndex":
        """JSON 파일에서 역직렬화."""
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls.model_validate(data)


if __name__ == "__main__":
    # 빠른 자기점검: 청크 2건을 넣고 태그 역조회가 되는지 본다.
    idx = MetadataIndex()
    c = Chunk(
        chunk_id="src-99-sample#s0-0",
        source_id="src-99-sample",
        version="v1@deadbeef",
        section_path=["개요"],
        heading="개요",
        char_start=0,
        char_end=10,
        token_estimate=5,
        text="짧은 본문.",
        quote="짧은 본문.",
    )
    idx.add(c, tags=["rag", "foundation"], acl_visibility="internal")
    print("tag 'rag' ->", idx.chunks_for_tag("rag"))
    print("source ->", idx.chunks_for_source("src-99-sample"))
