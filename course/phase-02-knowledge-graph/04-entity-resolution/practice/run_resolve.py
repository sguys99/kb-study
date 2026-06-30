"""run_resolve.py — entities.jsonl + relations.jsonl → 4단계 ER → canonical 산출물 저장.

이 토픽의 end-to-end 경로다. 키 없이 돈다(기본 embedding backend=mock).
입력은 2/03 이 만든 entities.jsonl·relations.jsonl 이지만, 시연용으로는
sample_entities.jsonl·sample_relations.jsonl(표기 흔들림 케이스를 더 넣은 사본)을
기본으로 쓴다. 산출물은 다음 토픽(2/05 관계 정규화·Event, 2/06 품질 게이트·증분
적재)의 입력이다.

흐름:
  1) 입력 jsonl 두 개를 Entity·Relation 객체로 되살린다.
  2) resolve() 로 4단계 ER → Union-Find 클러스터 → canonical 선정 → relation 재배선.
  3) 병합 전후 리포트를 찍는다(N 엔티티 → M canonical, 클러스터 멤버, 어느 단계가 묶었나).
  4) Self-RAG·CRAG·RAG 가 서로 다른 클러스터인지(오병합 가드)를 눈으로 확인한다.
  5) canonical_entities.jsonl · merge_map.json · relations.resolved.jsonl 저장.

사용:
  python run_resolve.py                         # mock 임베딩 (기본, 키 불필요)
  python run_resolve.py --input entities        # 시연 sample 대신 2/03 entities.jsonl 사용
  python run_resolve.py --embedding-backend voyage   # VOYAGE_API_KEY 필요
  python run_resolve.py --fuzzy-threshold 70    # 임계값 낮춰 substring 함정 깨보기(labs 5단계)

전제: mock 경로는 rapidfuzz + pydantic 만 필요. voyage/local 백엔드는 키·패키지(선택).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from resolve_entities import resolve
from schema_adapter import Entity, Relation

HERE = Path(__file__).resolve().parent
# 기본은 표기 흔들림을 더 넣은 시연용 sample. --input entities 로 2/03 원본을 쓴다.
SAMPLE_ENTITIES = HERE / "sample_entities.jsonl"
SAMPLE_RELATIONS = HERE / "sample_relations.jsonl"
SRC_ENTITIES = HERE / "entities.jsonl"
SRC_RELATIONS = HERE / "relations.jsonl"

OUT_ENTITIES = HERE / "canonical_entities.jsonl"
OUT_MERGE_MAP = HERE / "merge_map.json"
OUT_RELATIONS = HERE / "relations.resolved.jsonl"

# 오병합 가드 회귀를 눈으로 확인할 이름들. 이들은 서로 다른 클러스터여야 한다.
GUARD_NAMES = ["RAG", "Self-RAG", "CRAG"]


def load_jsonl(path: Path) -> list[dict]:
    """JSONL 파일을 읽는다. 빈 줄은 건너뛴다."""
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="4단계 엔티티 해소 파이프라인")
    parser.add_argument(
        "--input",
        default="sample",
        choices=["sample", "entities"],
        help="입력 선택(기본 sample: 표기 흔들림 케이스 포함 / entities: 2/03 원본)",
    )
    parser.add_argument(
        "--embedding-backend",
        default="mock",
        choices=["mock", "voyage", "local"],
        help="임베딩 백엔드(기본 mock, 키 불필요)",
    )
    parser.add_argument(
        "--fuzzy-threshold",
        type=int,
        default=90,
        help="fuzzy 매칭 임계값(0~100, 기본 90). 낮추면 오병합 위험↑(labs 5단계 시연)",
    )
    parser.add_argument(
        "--embedding-threshold",
        type=float,
        default=0.92,
        help="embedding 코사인 임계값(0~1, 기본 0.92)",
    )
    parser.add_argument(
        "--no-substring-guard",
        action="store_true",
        help="substring 함정 가드를 끈다(labs 5단계: 오병합 재현용. 실전 금지)",
    )
    args = parser.parse_args()

    ent_path = SAMPLE_ENTITIES if args.input == "sample" else SRC_ENTITIES
    rel_path = SAMPLE_RELATIONS if args.input == "sample" else SRC_RELATIONS

    entities = [Entity.model_validate(r) for r in load_jsonl(ent_path)]
    relations = [Relation.model_validate(r) for r in load_jsonl(rel_path)]
    print(
        f"입력: {ent_path.name} 엔티티 {len(entities)}건 · "
        f"{rel_path.name} 관계 {len(relations)}건 — "
        f"embedding={args.embedding_backend}, fuzzy_threshold={args.fuzzy_threshold}"
    )

    clusters, merge_map, rewired, pairs = resolve(
        entities,
        relations,
        embedding_backend=args.embedding_backend,
        fuzzy_threshold=args.fuzzy_threshold,
        embedding_threshold=args.embedding_threshold,
        substring_guard=not args.no_substring_guard,
    )
    if args.no_substring_guard:
        print("⚠️  substring 가드 OFF — 오병합 재현 모드(labs 5단계). 실전에서 쓰지 마라.")

    # 단계별 병합 쌍 개수.
    by_stage: dict[str, int] = {}
    for p in pairs:
        by_stage[p.stage] = by_stage.get(p.stage, 0) + 1
    print()
    print("단계별 병합 후보 쌍:")
    for stage in ["alias", "coref", "fuzzy", "embedding"]:
        print(f"  {stage:<10} {by_stage.get(stage, 0)} 쌍")

    # 병합 전후 요약.
    multi = [c for c in clusters if len(c.members) > 1]
    print()
    print(f"병합 결과: {len(entities)} 엔티티 → {len(clusters)} canonical "
          f"(병합된 클러스터 {len(multi)}개)")
    print()
    print("병합 그룹(멤버 2개 이상):")
    for c in sorted(multi, key=lambda x: -len(x.members)):
        members = ", ".join(sorted(set(c.members)))
        print(f"  [{c.type}] {c.canonical_name}  ←  {{{members}}}  "
              f"(빈도 {len(c.members)})  id={c.canonical_id}")

    # 오병합 가드 확인: GUARD_NAMES 가 각각 어느 canonical 로 갔나.
    print()
    print("오병합 가드 확인 (서로 다른 canonical 이어야 정상):")
    guard_targets = {}
    for nm in GUARD_NAMES:
        target = merge_map.get(nm, "(미존재)")
        guard_targets[nm] = target
        print(f"  {nm:<10} → {target}")
    distinct = len(set(guard_targets.values())) == len(GUARD_NAMES)
    print(f"  판정: {'PASS — Self-RAG·CRAG 가 RAG 로 안 합쳐졌다' if distinct else 'FAIL — 오병합 발생!'}")

    # 저장.
    with OUT_ENTITIES.open("w", encoding="utf-8") as f:
        for c in clusters:
            row = {
                "canonical_id": c.canonical_id,
                "name": c.canonical_name,
                "type": c.type,
                "aliases": c.aliases,
                "member_count": len(c.members),
            }
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    OUT_MERGE_MAP.write_text(
        json.dumps(merge_map, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with OUT_RELATIONS.open("w", encoding="utf-8") as f:
        for r in rewired:
            f.write(r.model_dump_json() + "\n")

    print()
    print(
        f"저장: {OUT_ENTITIES.name}({len(clusters)}) "
        f"{OUT_MERGE_MAP.name}({len(merge_map)} 매핑) "
        f"{OUT_RELATIONS.name}({len(rewired)}) — 다음 토픽(2/05·2/06)의 입력"
    )

    # 오병합이 났으면 비정상 종료 코드로 알린다(품질 게이트 복선).
    return 0 if distinct else 1


if __name__ == "__main__":
    raise SystemExit(main())
