"""build_source_index.py — Source Layer 폴더를 스캔해 source_index.jsonl 을 만든다.

하는 일:
  1) sources/ 아래 *.md 를 모두 찾는다.
  2) 각 파일의 SHA-256 해시·바이트 크기를 계산하고, 제목(H1)·stable ID 를 뽑는다.
  3) SourceRecord 로 검증한 뒤 한 줄에 한 건씩 source_index.jsonl 로 쓴다.

이 인덱스가 02~06 토픽의 입력이다. 원본은 손대지 않고, 메타만 따로 모은다(원본/메타 분리).

전제: 네트워크·API 키·Neo4j 불필요. 로컬 파일만 읽는다.
의존: pydantic v2 (source_record.py).

실행:
    python build_source_index.py                  # sources/ → source_index.jsonl
    python build_source_index.py --root sources --out source_index.jsonl
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from source_record import SourceRecord, make_source_id


def sha256_of(path: Path) -> tuple[str, int]:
    """파일을 청크 단위로 읽어 SHA-256 과 바이트 크기를 함께 반환한다.

    전체를 메모리에 올리지 않으려고 64KB 씩 끊어 읽는다(큰 코퍼스 대비).
    """
    h = hashlib.sha256()
    size = 0
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(64 * 1024), b""):
            h.update(chunk)
            size += len(chunk)
    return h.hexdigest(), size


def extract_title(path: Path) -> str:
    """Markdown 첫 H1(`# ...`)을 제목으로 쓴다. 없으면 파일명(확장자 제외)."""
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return path.stem


def build_record(path: Path, root: Path) -> SourceRecord:
    """파일 하나 → SourceRecord 한 건."""
    digest, size = sha256_of(path)
    return SourceRecord(
        source_id=make_source_id(path, root),
        title=extract_title(path),
        path=str(path.relative_to(root.parent).as_posix()),  # 토픽 디렉토리 기준 상대 경로
        sha256=digest,
        bytes=size,
        origin="local",
        origin_url=None,
        license="unknown",
    )


def build_index(root: Path, out: Path) -> list[SourceRecord]:
    """root 아래 *.md 를 정렬된 순서로 스캔해 records 를 만들고 JSONL 로 쓴다."""
    if not root.is_dir():
        sys.exit(f"[ERROR] Source Layer 루트가 없다: {root}")

    # README.md 는 폴더 규약 설명 문서이므로 원본 인덱스에서 제외한다.
    md_files = sorted(p for p in root.rglob("*.md") if p.name.lower() != "readme.md")
    if not md_files:
        sys.exit(f"[ERROR] {root} 아래 .md 원본이 없다. Phase 0 corpus 를 먼저 편입하라.")

    records = [build_record(p, root) for p in md_files]

    with out.open("w", encoding="utf-8") as f:
        for rec in records:
            # model_dump_json 으로 직렬화. JSONL 은 한 줄 = 한 레코드.
            f.write(rec.model_dump_json() + "\n")

    print(f"[OK] indexed {len(records)} sources -> {out}")
    for rec in records:
        print(f"     {rec.source_id:24s} sha256={rec.sha256[:12]}…  ({rec.bytes}B)  {rec.title}")
    return records


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Source Layer 인덱스 빌더")
    ap.add_argument("--root", default="sources", help="Source Layer 루트 폴더 (기본: sources)")
    ap.add_argument("--out", default="source_index.jsonl", help="출력 JSONL 경로")
    return ap.parse_args()


def main() -> None:
    args = parse_args()
    here = Path(__file__).resolve().parent
    root = (here / args.root).resolve()
    out = (here / args.out).resolve()
    build_index(root, out)


if __name__ == "__main__":
    main()
