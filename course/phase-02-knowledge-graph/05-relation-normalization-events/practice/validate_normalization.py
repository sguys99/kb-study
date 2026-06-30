"""validate_normalization.py — 정규화 결과를 검증한다. 4종 게이트.

관계를 정규화·dedup·reify 한 뒤에는 반드시 확인한다. 04 validate_resolution 과 같은
정신 — 파이프라인 산출물을 그대로 믿지 않고 게이트로 막는다(2/06 품질 게이트 복선).

검증 4종:
  (a) vocab 소속    — 모든 normalized relation type 이 vocab canonical 에 속하는가
                      (= 미등록 술어가 새어 들어오지 않았는가).
  (b) 대칭 dedup    — symmetric 관계가 (head,tail) 정렬 순서를 지키는가
                      (= A~B 와 B~A 가 두 엣지로 남지 않았는가).
  (c) self-loop 없음 — head==tail 엣지가 하나도 없는가.
  (d) dangling 없음  — normalized relation 의 head/tail, reified event 의 role 엔티티가
                       전부 canonical_entities 에 존재하는가(시간 리터럴은 예외).

종료 코드: 하나라도 FAIL 이면 1, 전부 PASS 면 0. CI 회귀 게이트로 쓸 수 있다.

전제: pyyaml. 네트워크·API 키 불필요.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
VOCAB = HERE / "relation_vocab.yaml"
RELATIONS = HERE / "normalized_relations.jsonl"
EVENTS = HERE / "events.normalized.jsonl"
CANON = HERE / "sample_canonical_entities.jsonl"  # 04 산출물(시연은 sample)

# 시간 리터럴 패턴(연도 등). dangling 검사에서 엔티티가 아니라 리터럴로 본다.
YEAR_RE = re.compile(r"^\d{3,4}$")


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


def load_vocab(path: Path = VOCAB) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def check_vocab_membership(relations: list[dict], vocab: dict) -> Check:
    """(a) 모든 relation type 이 vocab canonical(relations 키)에 속하는가."""
    canonical_types = set(vocab["relations"].keys())
    bad = [r["type"] for r in relations if r["type"] not in canonical_types]
    ok = not bad
    detail = "모든 type 이 vocab canonical" if ok else f"미등록 type: {sorted(set(bad))}"
    return Check("(a) vocab 소속", ok, detail)


def check_symmetric_dedup(relations: list[dict], vocab: dict) -> Check:
    """(b) symmetric 관계가 (head,tail) 정렬 순서를 지키고 중복이 없는가."""
    sym_types = {t for t, s in vocab["relations"].items() if s["symmetry"] == "symmetric"}
    bad_order = []
    seen: set[tuple[str, str, str]] = set()
    dup = []
    for r in relations:
        if r["type"] not in sym_types:
            continue
        if [r["head"], r["tail"]] != sorted([r["head"], r["tail"]]):
            bad_order.append(f"{r['head']}-[{r['type']}]->{r['tail']}(정렬 안 됨)")
        key = (r["head"], r["type"], r["tail"])
        if key in seen:
            dup.append(str(key))
        seen.add(key)
    ok = not bad_order and not dup
    if ok:
        detail = "symmetric 엣지가 모두 정렬·dedup 됨"
    else:
        detail = "; ".join(bad_order + [f"중복:{d}" for d in dup])[:200]
    return Check("(b) 대칭 dedup", ok, detail)


def check_no_self_loop(relations: list[dict]) -> Check:
    """(c) head==tail 인 self-loop 가 없는가."""
    loops = [f"{r['head']}-[{r['type']}]->{r['tail']}" for r in relations if r["head"] == r["tail"]]
    ok = not loops
    detail = "self-loop 없음" if ok else f"self-loop: {loops}"
    return Check("(c) self-loop 없음", ok, detail)


def check_no_dangling(relations: list[dict], events: list[dict], canon: list[dict]) -> Check:
    """(d) relation head/tail + event role 엔티티가 전부 canonical 집합 안에 있는가.

    시간 리터럴(연도)은 엔티티가 아니므로 예외 처리한다.
    """
    canon_names = {c["name"] for c in canon}
    dangling: list[str] = []

    for r in relations:
        for end in ("head", "tail"):
            if r[end] not in canon_names:
                dangling.append(f"relation {r['head']}-[{r['type']}]->{r['tail']} ({end}={r[end]!r})")

    for e in events:
        for role, val in e.get("roles", {}).items():
            if YEAR_RE.match(str(val)):
                continue  # 시간 리터럴은 엔티티가 아님
            if val not in canon_names:
                dangling.append(f"event {e['event_id']} role {role}={val!r}")

    ok = not dangling
    detail = "모든 엔티티 참조가 canonical" if ok else "; ".join(sorted(set(dangling))[:5])
    return Check("(d) dangling 없음", ok, detail)


def main() -> int:
    for p in (VOCAB, RELATIONS, EVENTS, CANON):
        if not p.exists():
            print(f"입력이 없다: {p.name}. 먼저 `python run_normalize.py` 를 실행하라.")
            return 2

    vocab = load_vocab()
    relations = load_jsonl(RELATIONS)
    events = load_jsonl(EVENTS)
    canon = load_jsonl(CANON)

    checks = [
        check_vocab_membership(relations, vocab),
        check_symmetric_dedup(relations, vocab),
        check_no_self_loop(relations),
        check_no_dangling(relations, events, canon),
    ]

    print(f"검증 입력: relations {len(relations)}건 · events {len(events)}건 · "
          f"canonical {len(canon)}건")
    print()
    all_ok = True
    for c in checks:
        mark = "PASS" if c.ok else "FAIL"
        print(f"[{mark}] {c.name}")
        print(f"       {c.detail}")
        all_ok = all_ok and c.ok

    print()
    print("결과:", "전부 통과" if all_ok else "FAIL 있음 — 정규화를 의심하라")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
