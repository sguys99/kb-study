"""run_extract_rce.py — entities.jsonl + sample_chunks.jsonl → 추출 → 검증 → 3개 jsonl 저장.

이 토픽의 end-to-end 경로다. 키 없이 돈다(기본 backend=mock).
출력 relations/claims/events.jsonl 은 다음 토픽(2/04 Entity Resolution,
2/05 Relation 정규화·Event 모델링)의 입력이다.

흐름:
  1) sample_chunks.jsonl(1/05 Chunk 형태)과 entities.jsonl(2/02 출력)을 읽는다.
  2) 청크마다 extract_relations_claims_events(chunk, entities, backend) 로
     Relation·Claim·Event 후보를 뽑는다(로컬 offset → body offset 환산은 추출기 안에서).
  3) 뽑힌 후보를 raw dict 로 모아 validate_rce 로 검증:
     enum + span quote + 수치/시점 환각 + dangling 참조.
  4) accept 된 것만 relations/claims/events.jsonl 로 저장. reject 는 사유와 함께 출력.

사용:
  python run_extract_rce.py                    # mock (기본, 키 불필요)
  python run_extract_rce.py --backend anthropic    # ANTHROPIC_API_KEY 필요
  python run_extract_rce.py --backend instructor   # ANTHROPIC_API_KEY 필요
  python run_extract_rce.py --strict-dangling      # dangling 참조를 reject 로 올림

전제: mock 경로는 pydantic>=2 만 필요. anthropic/instructor 는 키 + 패키지(선택).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from extract_relations import extract_relations_claims_events
from schema_adapter import Entity
from validate_rce import print_report, validate_rce

HERE = Path(__file__).resolve().parent
SAMPLE_PATH = HERE / "sample_chunks.jsonl"
ENTITIES_PATH = HERE / "entities.jsonl"
OUT_RELATIONS = HERE / "relations.jsonl"
OUT_CLAIMS = HERE / "claims.jsonl"
OUT_EVENTS = HERE / "events.jsonl"


def load_jsonl(path: Path) -> list[dict]:
    """JSONL 파일을 읽는다. 빈 줄은 건너뛴다."""
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def load_entities(path: Path) -> list[Entity]:
    """2/02 가 만든 entities.jsonl 을 Entity 객체로 되살린다."""
    return [Entity.model_validate(row) for row in load_jsonl(path)]


def main() -> int:
    parser = argparse.ArgumentParser(description="청크에서 Relation·Claim·Event 후보 추출")
    parser.add_argument(
        "--backend",
        default="mock",
        choices=["mock", "anthropic", "instructor"],
        help="추출 백엔드(기본 mock, 키 불필요)",
    )
    parser.add_argument(
        "--strict-dangling",
        action="store_true",
        help="dangling 참조(엔티티 미존재)를 경고가 아니라 reject 로 올린다",
    )
    args = parser.parse_args()

    chunks = load_jsonl(SAMPLE_PATH)
    entities = load_entities(ENTITIES_PATH)
    known_names = {e.name for e in entities}
    print(f"청크 {len(chunks)}건 · 엔티티 {len(entities)}건 로드 — backend={args.backend}")

    # 1~2) 청크별 추출 → raw dict 누적.
    raw = {"relations": [], "claims": [], "events": []}
    for chunk in chunks:
        out = extract_relations_claims_events(chunk, entities, backend=args.backend)
        n = (len(out["relations"]), len(out["claims"]), len(out["events"]))
        print(f"  {chunk['chunk_id']:<28} → R {n[0]} / C {n[1]} / E {n[2]}")
        for r in out["relations"]:
            raw["relations"].append(r.model_dump(mode="json"))
        for c in out["claims"]:
            raw["claims"].append(c.model_dump(mode="json"))
        for e in out["events"]:
            raw["events"].append(e.model_dump(mode="json"))

    # 3) 검증(enum + span quote + 수치/시점 환각 + dangling).
    report = validate_rce(
        raw, chunks, known_entities=known_names, strict_dangling=args.strict_dangling
    )
    print()
    print_report(report)

    # 4) accept 된 것만 저장. reject 는 위 리포트에 카운트로 남는다.
    def _dump(path: Path, items: list) -> None:
        with path.open("w", encoding="utf-8") as f:
            for it in items:
                f.write(it.model_dump_json() + "\n")

    _dump(OUT_RELATIONS, report.relations)
    _dump(OUT_CLAIMS, report.claims)
    _dump(OUT_EVENTS, report.events)
    print()
    print(
        f"저장: {OUT_RELATIONS.name}({len(report.relations)}) "
        f"{OUT_CLAIMS.name}({len(report.claims)}) "
        f"{OUT_EVENTS.name}({len(report.events)}) — 다음 토픽(2/04·2/05)의 입력"
    )

    # reject 가 있으면 비정상 종료 코드로 알린다(2/06 게이트 복선).
    return 1 if report.rejected else 0


if __name__ == "__main__":
    raise SystemExit(main())
