"""run_extract.py — sample_chunks.jsonl 을 읽어 mock 으로 추출 → entities.jsonl → 검증 리포트.

이 토픽의 end-to-end 경로다. 키 없이 돈다(기본 backend=mock).
출력 entities.jsonl 은 다음 토픽(2/03 Relation·Claim·Event, 2/04 Entity Resolution)의 입력이다.

흐름:
  1) sample_chunks.jsonl(1/05 Chunk 형태) 한 줄씩 읽는다.
  2) 청크마다 extract_entities(chunk, backend) 로 Entity 후보를 뽑는다.
     - 로컬 offset → body offset 환산은 extract_entities 안에서 끝난다.
  3) 뽑힌 Entity 를 raw dict 로 모아 validate_entities 로 검증(enum + quote 무결성).
  4) accept 된 것만 entities.jsonl 로 저장. reject 는 카운트·사유로 출력(reject queue 복선).

사용:
  python run_extract.py                  # mock (기본, 키 불필요)
  python run_extract.py --backend anthropic   # ANTHROPIC_API_KEY 필요
  python run_extract.py --backend instructor  # ANTHROPIC_API_KEY 필요

전제: mock 경로는 pydantic>=2 만 필요. anthropic/instructor 는 키 + 패키지(선택).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from extract_entities import extract_entities
from validate_entities import print_report, validate_raw_entities

HERE = Path(__file__).resolve().parent
SAMPLE_PATH = HERE / "sample_chunks.jsonl"
OUTPUT_PATH = HERE / "entities.jsonl"


def load_chunks(path: Path) -> list[dict]:
    """JSONL 청크 파일을 읽는다. 빈 줄은 건너뛴다."""
    chunks: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            chunks.append(json.loads(line))
    return chunks


def main() -> int:
    parser = argparse.ArgumentParser(description="청크에서 Entity 후보 추출")
    parser.add_argument(
        "--backend",
        default="mock",
        choices=["mock", "anthropic", "instructor"],
        help="추출 백엔드(기본 mock, 키 불필요)",
    )
    args = parser.parse_args()

    chunks = load_chunks(SAMPLE_PATH)
    print(f"청크 {len(chunks)}건 로드 — backend={args.backend}")

    # 1~2) 청크별 추출 → raw dict 누적.
    raw_entities: list[dict] = []
    for chunk in chunks:
        ents = extract_entities(chunk, backend=args.backend)
        print(f"  {chunk['chunk_id']:<28} → 후보 {len(ents)}건")
        for e in ents:
            raw_entities.append(e.model_dump(mode="json"))

    # 3) 검증(enum + span quote 무결성).
    report = validate_raw_entities(raw_entities, chunks)
    print()
    print_report(report)

    # 4) accept 된 것만 저장. reject 는 위 리포트에 카운트로 남는다.
    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        for ent in report.accepted:
            f.write(ent.model_dump_json() + "\n")
    print()
    print(f"저장: {OUTPUT_PATH.name} ({len(report.accepted)}건) — 다음 토픽(2/03·2/04)의 입력")

    # reject 가 있으면 비정상 종료 코드로 알린다(2/06 게이트 복선).
    return 1 if report.rejected else 0


if __name__ == "__main__":
    raise SystemExit(main())
