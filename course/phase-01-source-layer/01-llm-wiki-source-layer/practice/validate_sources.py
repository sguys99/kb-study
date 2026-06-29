"""validate_sources.py — Source Layer 의 최소 품질 게이트.

source_index.jsonl 과 실제 sources/ 폴더를 대조해 세 가지를 잡는다.
  1) 중복 ID   — 같은 source_id 가 둘 이상 있으면 KG·Agent 가 어느 원본을 가리키는지 모호해진다.
  2) 해시 불일치 — 인덱스의 sha256 과 현재 파일의 sha256 이 다르면 원본이 인덱싱 후 바뀐 것이다.
  3) 필수 메타 누락 / 형식 오류 — SourceRecord 로 재검증해 깨진 레코드를 잡는다.
     + 인덱스에는 있는데 파일이 사라진 경우(고아 레코드)도 함께 본다.

검증을 통과해야 다음 토픽(02~)이 이 인덱스를 신뢰하고 쓸 수 있다.

전제: 네트워크·API 키 불필요. 로컬 파일만 읽는다.
의존: pydantic v2 (source_record.py), build_source_index.py 의 sha256_of.

실행:
    python validate_sources.py
종료 코드: 문제 0건이면 0, 1건 이상이면 1 (CI 게이트로 쓸 수 있게).
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from pydantic import ValidationError

from build_source_index import sha256_of
from source_record import SourceRecord


def load_index(index_path: Path) -> list[dict]:
    if not index_path.is_file():
        sys.exit(f"[ERROR] 인덱스가 없다: {index_path}. 먼저 build_source_index.py 를 실행하라.")
    rows: list[dict] = []
    for lineno, line in enumerate(index_path.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as e:
            sys.exit(f"[ERROR] {index_path}:{lineno} JSON 파싱 실패: {e}")
    return rows


def validate(index_path: Path, topic_root: Path) -> int:
    """문제 건수를 반환한다(0 = 통과)."""
    rows = load_index(index_path)
    problems: list[str] = []

    # 1) 스키마 재검증 — 필수 메타 누락·형식 오류
    valid_rows: list[SourceRecord] = []
    for i, row in enumerate(rows):
        try:
            valid_rows.append(SourceRecord.model_validate(row))
        except ValidationError as e:
            problems.append(f"[schema] 레코드 #{i} 검증 실패: {e.errors()[0]['msg']}")

    # 2) 중복 ID
    id_counts = Counter(r.source_id for r in valid_rows)
    duplicate_ids = [sid for sid, n in id_counts.items() if n > 1]
    for sid in duplicate_ids:
        problems.append(f"[dup-id] 중복 source_id: {sid} ({id_counts[sid]}건)")

    # 3) 해시 불일치 / 고아 레코드
    hash_mismatch = 0
    missing_file = 0
    for rec in valid_rows:
        file_path = (topic_root / rec.path).resolve()
        if not file_path.is_file():
            problems.append(f"[missing] {rec.source_id}: 인덱스에는 있으나 파일 없음 ({rec.path})")
            missing_file += 1
            continue
        actual, _ = sha256_of(file_path)
        if actual != rec.sha256:
            problems.append(
                f"[hash] {rec.source_id}: 해시 불일치 "
                f"(index={rec.sha256[:12]}… actual={actual[:12]}…) — 원본이 바뀜"
            )
            hash_mismatch += 1

    # 요약 출력
    n = len(valid_rows)
    print(
        f"checked {len(rows)} records "
        f"({n} valid) | {len(duplicate_ids)} duplicate id | "
        f"{hash_mismatch} hash mismatch | {missing_file} missing file"
    )
    if problems:
        print("-" * 60)
        for p in problems:
            print("  " + p)
        print(f"FAIL — {len(problems)} problem(s).")
    else:
        print(f"OK: {n} sources, 0 duplicate id, 0 hash mismatch")
    return len(problems)


def main() -> None:
    here = Path(__file__).resolve().parent
    index_path = here / "source_index.jsonl"
    topic_root = here  # path 는 토픽 디렉토리 기준 상대 경로(예: sources/01-rag.md)
    n_problems = validate(index_path, topic_root)
    sys.exit(1 if n_problems else 0)


if __name__ == "__main__":
    main()
