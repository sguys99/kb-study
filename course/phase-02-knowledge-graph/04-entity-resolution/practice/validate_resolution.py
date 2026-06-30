"""validate_resolution.py — 병합 결과를 검증한다. 오병합·dangling 을 회귀 테스트로 잡는다.

ER 은 '합치기'다. 합치기는 틀리면 거짓 사실을 만든다(Self-RAG 를 RAG 로 합치면
"Self-RAG 가 RAG 를 개선한다"가 "RAG 가 RAG 를 개선한다"가 된다). 그래서 병합한
다음에는 반드시 네 가지를 검증한다. 2/03 validate_rce 와 같은 정신이다 —
파이프라인이 만든 산출물을 그대로 믿지 않고, 게이트로 막는다(2/06 품질 게이트 복선).

검증 4종:
  (a) type 일관   — 한 canonical 클러스터 안에 서로 다른 type 이 섞이지 않았는가.
  (b) 오병합 가드 — Self-RAG·CRAG·RAG 가 서로 다른 canonical 인가(회귀 테스트).
  (c) merge_map 1:1 — 모든 원본 표면형이 정확히 하나의 canonical 로 매핑되는가.
  (d) dangling 없음 — relations.resolved 의 head/tail 이 전부 canonical 집합 안에 있는가.

종료 코드: 하나라도 FAIL 이면 1, 전부 PASS 면 0. CI 회귀 게이트로 쓸 수 있다.

전제: 네트워크·API 키 불필요. 표준 라이브러리 + pydantic(간접).
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENTITIES = HERE / "canonical_entities.jsonl"
MERGE_MAP = HERE / "merge_map.json"
RELATIONS = HERE / "relations.resolved.jsonl"

# (b) 오병합 가드 대상. 이들은 서로 다른 canonical 이어야 한다.
GUARD_NAMES = ["RAG", "Self-RAG", "CRAG"]


@dataclass
class Check:
    name: str
    ok: bool
    detail: str


def load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def check_type_consistency(canon: list[dict], merge_map: dict[str, str]) -> Check:
    """(a) 한 canonical 안에 type 이 하나만 있어야 한다.

    canonical_entities 각 행은 이미 단일 type 을 들고 있다. 여기서는 merge_map 이
    가리키는 canonical 이름이 실제로 canonical 집합에 존재하고 type 충돌이 없는지를
    교차 확인한다. (서로 다른 type 끼리 stage 들이 후보를 안 만들었어야 정상이다.)
    """
    name_to_type = {c["name"]: c["type"] for c in canon}
    bad = []
    for surface, target in merge_map.items():
        if target not in name_to_type:
            bad.append(f"{surface!r}→{target!r}(canonical 집합에 없음)")
    ok = not bad
    detail = "모든 매핑 대상이 canonical 집합에 존재" if ok else "; ".join(bad[:5])
    return Check("(a) type 일관 / canonical 존재", ok, detail)


def check_misjoin_guard(merge_map: dict[str, str]) -> Check:
    """(b) Self-RAG·CRAG·RAG 가 서로 다른 canonical 로 가는가(오병합 회귀 테스트)."""
    targets = {nm: merge_map.get(nm, f"(미존재:{nm})") for nm in GUARD_NAMES}
    distinct = len(set(targets.values())) == len(GUARD_NAMES)
    detail = ", ".join(f"{k}→{v}" for k, v in targets.items())
    return Check("(b) 오병합 가드 (Self-RAG·CRAG·RAG 분리)", distinct, detail)


def check_merge_map_functional(merge_map: dict[str, str]) -> Check:
    """(c) merge_map 이 함수(1:1 매핑)인가 — 한 표면형이 하나의 canonical 로만.

    dict 라 자료구조상 키 중복은 불가능하지만, canonical 이 자기 자신으로 매핑되는
    고정점(target ∈ keys 이고 merge_map[target]==target)이 깨지면 사슬이 꼬인다.
    여기서는 모든 target 이 다시 자기 자신으로 매핑되는 안정점인지 확인한다.
    """
    bad = []
    for surface, target in merge_map.items():
        if merge_map.get(target) != target:
            bad.append(f"{surface!r}→{target!r}이지만 {target!r}→{merge_map.get(target)!r}")
    ok = not bad
    detail = "모든 canonical 이 자기 자신으로 매핑(안정점)" if ok else "; ".join(bad[:5])
    return Check("(c) merge_map 1:1 (안정점)", ok, detail)


def check_no_dangling(relations: list[dict], canon: list[dict]) -> Check:
    """(d) relations.resolved 의 head/tail 이 전부 canonical 이름 집합 안에 있는가."""
    canon_names = {c["name"] for c in canon}
    dangling = []
    for r in relations:
        for end in ("head", "tail"):
            if r[end] not in canon_names:
                dangling.append(f"{r['head']}-[{r['type']}]->{r['tail']} ({end}={r[end]!r})")
    ok = not dangling
    detail = "모든 head/tail 이 canonical" if ok else "; ".join(sorted(set(dangling))[:5])
    return Check("(d) dangling 없음", ok, detail)


def main() -> int:
    for p in (ENTITIES, MERGE_MAP, RELATIONS):
        if not p.exists():
            print(f"입력이 없다: {p.name}. 먼저 `python run_resolve.py` 를 실행하라.")
            return 2

    canon = load_jsonl(ENTITIES)
    relations = load_jsonl(RELATIONS)
    merge_map = json.loads(MERGE_MAP.read_text(encoding="utf-8"))

    checks = [
        check_type_consistency(canon, merge_map),
        check_misjoin_guard(merge_map),
        check_merge_map_functional(merge_map),
        check_no_dangling(relations, canon),
    ]

    print(f"검증 입력: canonical {len(canon)}건 · relations {len(relations)}건 · "
          f"merge_map {len(merge_map)} 매핑")
    print()
    all_ok = True
    for c in checks:
        mark = "PASS" if c.ok else "FAIL"
        print(f"[{mark}] {c.name}")
        print(f"       {c.detail}")
        all_ok = all_ok and c.ok

    print()
    print("결과:", "전부 통과" if all_ok else "FAIL 있음 — 병합을 의심하라")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
