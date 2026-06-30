"""validate_rce.py — Relation·Claim·Event 후보를 검증하고 reject 사유를 집계한다.

2/02 validate_entities 의 확장이다. 2/06 품질 게이트의 한 단계로, 다섯 가지를 본다:

  1) RelationType enum 위반 → reject.
     Pydantic 이 Relation 생성 시점에 막는다(2/01 통제 어휘). LLM 이 enum 밖
     관계 타입을 내면 ValidationError 가 난다. 여기서 그 에러를 reject 로 집계한다.

  2) span quote 불일치(body[start:end] != quote) → reject.
     근거 사슬 무결성 게이트(2/02 와 동일). quote 가 출처 청크의 실제 위치와
     어긋나면 인용이 깨진 것이므로 버린다.

  3) Claim.value 가 quote 안에 없음 → reject(수치 환각 차단).
     '99%' 라고 주장하면서 근거 quote 에 '99%' 가 없으면 LLM 이 수치를 지어낸 것이다.
     surface 그대로 quote 안에 있어야 한다.

  4) Event.time 이 quote 안에 없음 → reject(시점 환각 차단).
     '2020' 이라고 적으면서 근거 quote 에 '2020' 이 없으면 시점을 지어낸 것이다.

  5) dangling 참조(head/tail/participant 가 알려진 엔티티 집합에 없음) → 경고.
     2/02 가 만든 엔티티 집합에 없는 이름을 가리키는 관계는 '매달린' 관계다.
     기본은 reject 가 아니라 경고로 둔다 — 엔티티 추출이 놓친 개체일 수 있고,
     2/04 Entity Resolution 이 정리할 수도 있다. 정책은 strict 플래그로 바꿀 수 있다.

reject 된 후보는 그냥 버리지 않는다. 사유와 함께 모아 둔다(다음 Phase reject queue).

전제: 네트워크·API 키 불필요. pydantic>=2.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import ValidationError

from schema_adapter import Claim, Event, Provenance, Relation, RelationType


@dataclass
class RejectRecord:
    """버려진 후보 1건. 종류(kind)·원자료(raw)·사유를 같이 들고 다닌다(reject queue 복선)."""

    kind: str   # "relation" | "claim" | "event"
    raw: dict
    reason: str


@dataclass
class WarnRecord:
    """경고 1건. reject 는 아니지만 다음 단계가 봐야 할 것(예: dangling 참조)."""

    kind: str
    detail: str


@dataclass
class ValidationReport:
    relations: list[Relation] = field(default_factory=list)
    claims: list[Claim] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)
    rejected: list[RejectRecord] = field(default_factory=list)
    warnings: list[WarnRecord] = field(default_factory=list)

    @property
    def accepted_count(self) -> int:
        return len(self.relations) + len(self.claims) + len(self.events)

    @property
    def total(self) -> int:
        return self.accepted_count + len(self.rejected)


def _quote_matches(prov: Provenance, chunks_by_source: dict[str, list[dict]]) -> bool:
    """body[start:end] == quote 인지 출처 청크 text 로 확인한다(2/02 와 동일 로직).

    청크가 body[char_start:char_end] == text 를 보장하므로,
    body[start:end] 는 곧 text[start - char_start : end - char_start] 와 같다.
    그 span 을 품는 청크를 찾아 quote 와 1:1 비교한다.
    """
    candidates = chunks_by_source.get(prov.source_id, [])
    for chunk in candidates:
        cs, ce = chunk["char_start"], chunk["char_end"]
        if cs <= prov.start and prov.end <= ce:  # 이 청크 범위 안의 span
            local_start = prov.start - cs
            local_end = prov.end - cs
            return chunk["text"][local_start:local_end] == prov.quote
    return False  # 어느 청크에도 안 들어가면 근거를 못 댄다 → 불일치 취급


def _index_by_source(chunks: list[dict]) -> dict[str, list[dict]]:
    by_source: dict[str, list[dict]] = {}
    for c in chunks:
        by_source.setdefault(c["source_id"], []).append(c)
    return by_source


def validate_rce(
    raw: dict,
    chunks: list[dict],
    known_entities: set[str] | None = None,
    strict_dangling: bool = False,
) -> ValidationReport:
    """raw {relations, claims, events} 후보들을 검증한다.

    각 리스트 항목은 dict 다(LLM 백엔드가 enum 밖 값을 낸 상황을 재현·집계하려고
    Pydantic 검증 전 dict 부터 받는다). known_entities 는 2/02 가 만든 엔티티 이름
    집합이다(dangling 판정용). strict_dangling=True 면 dangling 을 경고가 아니라
    reject 로 올린다.
    """
    report = ValidationReport()
    chunks_by_source = _index_by_source(chunks)
    known = known_entities or set()

    def _check_dangling(kind: str, names: list[str], raw_item: dict) -> bool:
        """names 중 알려진 엔티티에 없는 게 있으면 경고 또는(strict) reject. reject 면 True."""
        if not known:  # 엔티티 집합이 없으면 dangling 판정을 건너뛴다.
            return False
        missing = [n for n in names if n not in known]
        if not missing:
            return False
        if strict_dangling:
            report.rejected.append(
                RejectRecord(kind=kind, raw=raw_item, reason=f"dangling 참조(엔티티 미존재): {missing}")
            )
            return True
        report.warnings.append(WarnRecord(kind=kind, detail=f"dangling 참조: {missing} (raw={raw_item.get('head') or raw_item.get('name')})"))
        return False

    # ── Relation ────────────────────────────────────────────────────────────
    for r in raw.get("relations", []):
        # 1) enum + 구조 검증. Pydantic 이 RelationType enum 밖 라벨을 막는다.
        try:
            rel = Relation.model_validate(r)
        except ValidationError as exc:
            label = r.get("type")
            allowed = [t.value for t in RelationType]
            reason = (
                f"enum 위반: type={label!r} (허용 {allowed})"
                if label not in allowed
                else f"구조 오류: {exc.error_count()}건"
            )
            report.rejected.append(RejectRecord(kind="relation", raw=r, reason=reason))
            continue
        # 2) span quote 무결성.
        if not _quote_matches(rel.provenance, chunks_by_source):
            report.rejected.append(
                RejectRecord(kind="relation", raw=r, reason="span quote 불일치(body[start:end] != quote)")
            )
            continue
        # 5) dangling head/tail(기본 경고).
        if _check_dangling("relation", [rel.head, rel.tail], r):
            continue
        report.relations.append(rel)

    # ── Claim ─────────────────────────────────────────────────────────────────
    for c in raw.get("claims", []):
        try:
            claim = Claim.model_validate(c)
        except ValidationError as exc:
            report.rejected.append(RejectRecord(kind="claim", raw=c, reason=f"구조 오류: {exc.error_count()}건"))
            continue
        if not _quote_matches(claim.provenance, chunks_by_source):
            report.rejected.append(
                RejectRecord(kind="claim", raw=c, reason="span quote 불일치(body[start:end] != quote)")
            )
            continue
        # 3) 수치 환각 차단: value 가 있으면 quote 안에 surface 그대로 있어야 한다.
        if claim.value is not None and claim.value not in claim.provenance.quote:
            report.rejected.append(
                RejectRecord(kind="claim", raw=c, reason=f"수치 환각: value={claim.value!r} 가 근거 quote 에 없음")
            )
            continue
        report.claims.append(claim)

    # ── Event ─────────────────────────────────────────────────────────────────
    for e in raw.get("events", []):
        try:
            event = Event.model_validate(e)
        except ValidationError as exc:
            report.rejected.append(RejectRecord(kind="event", raw=e, reason=f"구조 오류: {exc.error_count()}건"))
            continue
        if not _quote_matches(event.provenance, chunks_by_source):
            report.rejected.append(
                RejectRecord(kind="event", raw=e, reason="span quote 불일치(body[start:end] != quote)")
            )
            continue
        # 4) 시점 환각 차단: time 이 있으면 quote 안에 surface 그대로 있어야 한다.
        if event.time is not None and event.time not in event.provenance.quote:
            report.rejected.append(
                RejectRecord(kind="event", raw=e, reason=f"시점 환각: time={event.time!r} 가 근거 quote 에 없음")
            )
            continue
        # 5) dangling participant(기본 경고, strict 면 reject).
        if _check_dangling("event", event.participants, e):
            continue
        report.events.append(event)

    return report


def print_report(report: ValidationReport) -> None:
    """검증 리포트를 사람이 읽게 출력한다."""
    print("=== RCE 검증 리포트 ===")
    print(
        f"총 후보 {report.total}건 — "
        f"accept {report.accepted_count} "
        f"(R {len(report.relations)} / C {len(report.claims)} / E {len(report.events)}) "
        f"/ reject {len(report.rejected)}"
    )
    if report.relations:
        print("--- relations (accepted) ---")
        for r in report.relations:
            print(f"  [OK] ({r.head}) -[{r.type.value}]-> ({r.tail})  src={r.provenance.source_id}")
    if report.claims:
        print("--- claims (accepted) ---")
        for c in report.claims:
            print(f"  [OK] {c.subject} {c.predicate} value={c.value!r}  src={c.provenance.source_id}")
    if report.events:
        print("--- events (accepted) ---")
        for e in report.events:
            print(f"  [OK] {e.name} participants={e.participants} time={e.time!r}  src={e.provenance.source_id}")
    if report.warnings:
        print("--- warnings (다음 단계가 볼 것) ---")
        for w in report.warnings:
            print(f"  [WARN] ({w.kind}) {w.detail}")
    if report.rejected:
        print("--- rejected (reject queue 로 보존) ---")
        for r in report.rejected:
            print(f"  [REJECT] ({r.kind}) {r.reason}")


if __name__ == "__main__":
    # 키 없이 도는 점검: 정상 + 네 가지 reject(enum/quote/수치환각/시점환각)를 넣어 본다.
    chunk = {
        "chunk_id": "src-05-lightrag::c021",
        "source_id": "src-05-lightrag",
        "version": "v1@ab12cd34",
        "char_start": 3000,
        "char_end": 3094,
        "text": "LightRAG reduces token cost by 99% compared to GraphRAG. RAG was published at NeurIPS in 2020.",
    }
    prov_ok = {  # body[3000:3034] == 'LightRAG reduces token cost by 99%'
        "source_id": "src-05-lightrag", "version": "v1@ab12cd34",
        "start": 3000, "end": 3034, "quote": "LightRAG reduces token cost by 99%",
    }
    raw = {
        "relations": [
            {  # enum 위반: 'BEATS' 는 RelationType 에 없다 → reject
                "head": "LightRAG", "type": "BEATS", "tail": "GraphRAG",
                "provenance": {**prov_ok, "start": 3000, "end": 3055,
                               "quote": "LightRAG reduces token cost by 99% compared to GraphRAG"},
            },
        ],
        "claims": [
            {  # 정상: value '99%' 가 quote 안에 있다 → accept
                "subject": "LightRAG", "predicate": "reduces_token_cost",
                "object": "GraphRAG", "value": "99%", "provenance": prov_ok,
            },
            {  # 수치 환각: value '50%' 가 quote 에 없다 → reject
                "subject": "LightRAG", "predicate": "reduces_token_cost",
                "object": "GraphRAG", "value": "50%", "provenance": prov_ok,
            },
        ],
        "events": [
            {  # 시점 환각: time '1999' 가 quote 에 없다 → reject
                "name": "RAG_publication", "participants": ["RAG", "NeurIPS"], "time": "1999",
                "provenance": {"source_id": "src-05-lightrag", "version": "v1@ab12cd34",
                               "start": 3056, "end": 3093,
                               "quote": "RAG was published at NeurIPS in 2020"},
            },
        ],
    }
    rep = validate_rce(raw, [chunk], known_entities={"LightRAG", "GraphRAG", "RAG"})
    print_report(rep)
