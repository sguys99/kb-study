"""load_chunks.py — 05 산출물(chunks.jsonl + index.json) 로드. 06의 모든 색인이 여기서 시작한다.

05 run_pipeline.py 가 만든 두 파일을 상대경로로 읽는다(복제하지 않는다).
  - out/chunks.jsonl : 1줄 = 1청크 JSON. 05 Chunk 스키마 그대로.
  - out/index.json   : metadata index(forward · by_tag · by_source).

05 Chunk 스키마(필드 그대로 재현):
  chunk_id · source_id · version · section_path · heading ·
  char_start · char_end · token_estimate · text · quote.

입력 파일이 없으면(05 미실행) 친절히 안내하고 멈춘다 — 05 에러 톤과 일관.

전제: 네트워크·API 키 불필요. 순수 로컬.
의존: pydantic>=2.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from pydantic import BaseModel, Field

HERE = Path(__file__).resolve().parent

# 05 산출물 경로(상대경로 재사용 — 복제하지 않는다).
CHUNKS_PATH = (HERE / ".." / ".." / "05-wiki-parser-chunking" / "practice" / "out" / "chunks.jsonl").resolve()
INDEX_PATH = (HERE / ".." / ".." / "05-wiki-parser-chunking" / "practice" / "out" / "index.json").resolve()

# 06 자체 출력(임베딩 캐시·점수 등)을 둘 폴더.
OUT_DIR = HERE / "out"


class Chunk(BaseModel):
    """05 Chunk 스키마 재현. 검색·인용의 최소 단위."""

    chunk_id: str = Field(..., description="위치 식별자. f'{source_id}#s{sec}-{ord}'. 안정적.")
    source_id: str = Field(..., description="소속 문서 stable ID.")
    version: str = Field(..., description="문서 version. 예: v1@100918bd.")
    section_path: list[str] = Field(default_factory=list)
    heading: str = Field(default="")
    char_start: int = Field(..., ge=0)
    char_end: int = Field(..., ge=0)
    token_estimate: int = Field(..., ge=0)
    text: str = Field(...)
    quote: str = Field(..., description="text 앞부분 사본. 추출형 답변·미리보기에 쓴다.")


class MetaIndex(BaseModel):
    """05 metadata index 의 우리가 쓰는 부분. forward · by_tag · by_source."""

    forward: dict[str, dict] = Field(default_factory=dict)
    by_tag: dict[str, list[str]] = Field(default_factory=dict)
    by_source: dict[str, list[str]] = Field(default_factory=dict)

    def chunk_ids_for_tag(self, tag: str) -> list[str]:
        return self.by_tag.get(tag, [])


def _die_missing(path: Path) -> None:
    sys.exit(
        "[ERROR] 05 산출물을 찾지 못했다.\n"
        f"        기대 경로: {path}\n"
        "        05-wiki-parser-chunking/practice 에서 먼저 다음을 실행하라:\n"
        "            python run_pipeline.py\n"
        "        그러면 out/chunks.jsonl 과 out/index.json 이 생긴다."
    )


def load_chunks() -> list[Chunk]:
    """05 out/chunks.jsonl 을 Chunk 목록으로 로드·검증한다. 없으면 안내 후 종료."""
    if not CHUNKS_PATH.is_file():
        _die_missing(CHUNKS_PATH)
    chunks: list[Chunk] = []
    with CHUNKS_PATH.open(encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as e:
                sys.exit(f"[ERROR] chunks.jsonl {line_no}행 JSON 파싱 실패: {e}")
            chunks.append(Chunk.model_validate(rec))
    if not chunks:
        sys.exit(f"[ERROR] {CHUNKS_PATH} 가 비어 있다. 05 run_pipeline.py 를 다시 실행하라.")
    return chunks


def load_index() -> MetaIndex:
    """05 out/index.json 을 MetaIndex 로 로드한다. 없으면 안내 후 종료."""
    if not INDEX_PATH.is_file():
        _die_missing(INDEX_PATH)
    data = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    return MetaIndex.model_validate(data)


def chunk_map(chunks: list[Chunk]) -> dict[str, Chunk]:
    """chunk_id -> Chunk 딕셔너리. 검색 결과(id 목록)에서 본문·인용 메타를 즉시 끌어오려고 둔다."""
    return {c.chunk_id: c for c in chunks}


if __name__ == "__main__":
    # 빠른 자기점검: 로드되는지, 몇 건인지, 첫 청크가 뭔지 본다.
    cs = load_chunks()
    idx = load_index()
    print(f"[load_chunks] 청크 {len(cs)}건 · 문서 {len(idx.by_source)}개 · 태그 {len(idx.by_tag)}종")
    print(f"  태그 목록: {sorted(idx.by_tag)}")
    first = cs[0]
    print(f"  첫 청크: {first.chunk_id}  ({first.version})  tok={first.token_estimate}")
    print(f"    quote: {first.quote[:50]!r}")
