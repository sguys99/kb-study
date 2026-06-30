"""run_normalize.py — 관계 정규화 + Event reification 전체 파이프라인 실행.

이 토픽의 end-to-end 경로다. 키 없이 돈다.
입력은 04 relations.resolved.jsonl + 03 events.jsonl 이지만, 시연용으로는
동봉 sample(동의어·inverse·symmetric·self-loop·미등록·n-ary 케이스를 일부러 넣은
사본)을 기본으로 쓴다. 산출물은 다음 토픽(2/06 품질 게이트·증분 적재)의 입력이다.

흐름:
  1) relation_vocab.yaml 로드.
  2) relations 를 동의어 정규화 → 방향 정규화 → dedup. 미등록·self-loop 는 reject.
  3) events 를 role 부여된 ReifiedEvent 로 reify(+ 수치 claim → MEASUREMENT 시연).
  4) 요약 리포트(N 관계 → M canonical type, K dedup, R reject).
  5) normalized_relations.jsonl · events.normalized.jsonl · reject_relations.jsonl 저장.

사용:
  python run_normalize.py                 # 시연 sample (기본, 키 불필요)
  python run_normalize.py --input resolved # 04/03 실제 산출물 사용(상위 04 디렉토리에서 복사 가정)
  python run_normalize.py --with-claims    # claims 도 MEASUREMENT Event 로 추가 reify

전제: pyyaml + pydantic. 네트워크·API 키 불필요.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from model_events import load_event_vocab, reify_claim_as_measurement, reify_event
from normalize_relations import RelationVocab, normalize_relations
from schema_adapter import Claim, Event, Relation

HERE = Path(__file__).resolve().parent

SAMPLE_RELATIONS = HERE / "sample_relations.resolved.jsonl"
SAMPLE_EVENTS = HERE / "sample_events.jsonl"
SAMPLE_CLAIMS = HERE / "sample_claims.jsonl"  # 없으면 claim 단계는 건너뜀
# 04/03 실제 산출물을 직접 쓸 때(같은 practice 디렉토리에 복사해 둔다고 가정).
SRC_RELATIONS = HERE / "relations.resolved.jsonl"
SRC_EVENTS = HERE / "events.jsonl"
SRC_CLAIMS = HERE / "claims.jsonl"

OUT_RELATIONS = HERE / "normalized_relations.jsonl"
OUT_EVENTS = HERE / "events.normalized.jsonl"
OUT_REJECT = HERE / "reject_relations.jsonl"


def load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="관계 정규화 + Event reification")
    parser.add_argument(
        "--input",
        default="sample",
        choices=["sample", "resolved"],
        help="입력 선택(기본 sample / resolved: 04·03 실제 산출물)",
    )
    parser.add_argument(
        "--with-claims",
        action="store_true",
        help="수치 claim 을 MEASUREMENT Event 로 추가 reify(시연)",
    )
    args = parser.parse_args()

    rel_path = SAMPLE_RELATIONS if args.input == "sample" else SRC_RELATIONS
    ev_path = SAMPLE_EVENTS if args.input == "sample" else SRC_EVENTS
    claim_path = SAMPLE_CLAIMS if args.input == "sample" else SRC_CLAIMS

    # --input resolved 인데 04·03 산출물을 아직 복사하지 않았다면 친절히 안내한다.
    for p in (rel_path, ev_path):
        if not p.exists():
            print(
                f"입력이 없다: {p.name}. --input resolved 는 04·03 산출물을 "
                f"이 practice/ 로 복사해야 한다(relations.resolved.jsonl·events.jsonl). "
                f"시연만 하려면 인자 없이 `python run_normalize.py` 로 sample 을 쓰라."
            )
            return 2

    relations = [Relation.model_validate(r) for r in load_jsonl(rel_path)]
    events = [Event.model_validate(r) for r in load_jsonl(ev_path)]
    print(
        f"입력: {rel_path.name} 관계 {len(relations)}건 · "
        f"{ev_path.name} 이벤트 {len(events)}건"
    )

    # ── 1) 관계 정규화 ────────────────────────────────────────────────
    rel_vocab = RelationVocab.load()
    result = normalize_relations(relations, rel_vocab)

    print()
    print(
        f"관계 정규화: {len(relations)}건 → {len(result.normalized)} canonical 엣지 "
        f"(dedup 으로 {len(relations) - len(result.normalized) - len(result.rejected)}건 합쳐짐) · "
        f"reject {len(result.rejected)}건"
    )
    print()
    print("정규화된 엣지(근거 개수 = support):")
    for nr in sorted(result.normalized, key=lambda x: (x.type, x.head)):
        print(
            f"  ({nr.head})-[{nr.type}]->({nr.tail})  "
            f"[{nr.direction}, support={nr.support}]"
        )

    if result.rejected:
        print()
        print("reject(미등록 술어 / self-loop):")
        for rj in result.rejected:
            print(f"  ({rj['head']})-[{rj['type']}]->({rj['tail']})  — {rj['reason']}")

    # ── 2) Event reification ──────────────────────────────────────────
    ev_vocab = load_event_vocab()
    reified: list = []
    ev_rejected: list = []
    for ev in events:
        out = reify_event(ev, ev_vocab)
        if isinstance(out, dict):
            ev_rejected.append(out)
        else:
            reified.append(out)

    # 수치 claim → MEASUREMENT Event(선택).
    if args.with_claims and claim_path.exists():
        claims = [Claim.model_validate(r) for r in load_jsonl(claim_path)]
        for cl in claims:
            if cl.value:  # 수치가 있는 클레임만 measured Event 로
                reified.append(reify_claim_as_measurement(cl, ev_vocab))

    print()
    print(f"Event reification: {len(events)}건 → {len(reified)} reified Event "
          f"(reject {len(ev_rejected)}건)")
    for re in reified:
        roles_str = ", ".join(f"{k}={v}" for k, v in re.roles.items())
        print(f"  [{re.type}] {re.event_id}  {{{roles_str}}}")

    # ── 3) 저장 ───────────────────────────────────────────────────────
    with OUT_RELATIONS.open("w", encoding="utf-8") as f:
        for nr in result.normalized:
            f.write(nr.model_dump_json() + "\n")
    with OUT_EVENTS.open("w", encoding="utf-8") as f:
        for re in reified:
            f.write(re.model_dump_json() + "\n")
    with OUT_REJECT.open("w", encoding="utf-8") as f:
        for rj in result.rejected:
            f.write(json.dumps(rj, ensure_ascii=False) + "\n")

    print()
    print(
        f"저장: {OUT_RELATIONS.name}({len(result.normalized)}) "
        f"{OUT_EVENTS.name}({len(reified)}) "
        f"{OUT_REJECT.name}({len(result.rejected)}) — 다음 토픽(2/06)의 입력"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
