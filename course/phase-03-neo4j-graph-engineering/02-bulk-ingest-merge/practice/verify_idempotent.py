"""적재를 두 번 연속 돌려 노드·관계·이벤트 카운트가 동일한지 검증한다.

idempotent 의 정의: 같은 입력으로 적재를 N 번 해도 그래프 상태가 1번 했을 때와 같다.
MERGE 가 키로 노드/관계를 재사용하고, provenance dedup 이 결정적이면 카운트가 늘지 않는다.

ingest_bulk.run() 을 그대로 재사용한다(서브프로세스가 아니라 함수 직접 호출).

전제:
  - Neo4j 5.26 기동 중(bolt://localhost:7687)
  - pip install -r requirements.txt
  - 이 토픽은 API 키가 필요 없다(로컬 Neo4j 만, 과금 없음).

실행:
  python verify_idempotent.py                 # 동봉 data/ 로 검증
  python verify_idempotent.py --data-dir <경로>

종료 코드: idempotent 면 0, 카운트가 늘면 1.
"""

import argparse
import sys
from pathlib import Path

import ingest_bulk


def main() -> int:
    parser = argparse.ArgumentParser(description="2회 적재 카운트 동일성(idempotent) 검증")
    parser.add_argument("--data-dir", type=Path, default=ingest_bulk.DEFAULT_DATA_DIR)
    args = parser.parse_args()

    print("=== 1차 적재 ===")
    first = ingest_bulk.run(args.data_dir)

    print("=== 2차 적재 ===")
    second = ingest_bulk.run(args.data_dir)

    print(f"\n1차: nodes={first[0]} rels={first[1]} events={first[2]}")
    print(f"2차: nodes={second[0]} rels={second[1]} events={second[2]}")

    if first == second:
        print("[OK] idempotent — 두 번 적재해도 카운트가 동일하다.")
        return 0

    # 어디가 늘었는지 짚어 준다.
    labels = ("nodes", "rels", "events")
    grew = [f"{labels[i]} {first[i]} -> {second[i]}" for i in range(3) if first[i] != second[i]]
    print(f"[FAIL] idempotent 깨짐: {', '.join(grew)}", file=sys.stderr)
    print("  - 관계 MERGE 키나 provenance dedup, CREATE 오용을 점검하라.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"[FAIL] {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
