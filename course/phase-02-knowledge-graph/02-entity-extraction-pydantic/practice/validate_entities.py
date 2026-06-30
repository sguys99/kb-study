"""validate_entities.py — 추출된 Entity 후보를 검증하고 reject 사유를 집계한다.

2/06 품질 게이트의 가장 단순한 형태다. 두 가지를 본다:

  1) NodeType enum 위반 → reject.
     Pydantic 이 Entity 생성 시점에 자동으로 막는다(2/01 통제 어휘). LLM 이 enum 밖
     라벨을 내면 ValidationError 가 난다. 여기서는 그 에러를 reject 로 집계한다.

  2) span quote 불일치(body[start:end] != quote) → reject.
     이게 '근거 사슬 무결성' 게이트다. quote 가 실제 원문 위치와 어긋나면 인용이
     깨진 것이므로 버린다. 이 토픽에선 원문 body 대신 '출처 청크 text' 로 검증한다
     (청크가 body[char_start:char_end] == text 를 보장하므로 동치다).

reject 된 후보는 그냥 버리지 않는다. 사유와 함께 모아 둔다(다음 Phase reject queue 복선).
최소한 카운트·사유는 출력한다.

전제: 네트워크·API 키 불필요. pydantic>=2.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import ValidationError

from schema_adapter import Entity, NodeType, Provenance


@dataclass
class RejectRecord:
    """버려진 후보 1건. 원자료(raw)와 사유를 같이 들고 다닌다(reject queue 복선)."""

    raw: dict
    reason: str


@dataclass
class ValidationReport:
    accepted: list[Entity] = field(default_factory=list)
    rejected: list[RejectRecord] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.accepted) + len(self.rejected)


def _build_chunk_index(chunks: list[dict]) -> dict[str, dict]:
    """source_id → chunk. quote 검증용. 같은 source 의 청크가 여럿이면 char_start 로 찾는다."""
    return {c["chunk_id"]: c for c in chunks}


def _quote_matches(prov: Provenance, chunks_by_source: dict[str, list[dict]]) -> bool:
    """body[start:end] == quote 인지 출처 청크 text 로 확인한다.

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


def validate_raw_entities(raw_entities: list[dict], chunks: list[dict]) -> ValidationReport:
    """raw dict 후보들을 검증한다(enum 위반 + span quote 불일치).

    raw_entities 각 항목 형태:
      {"name": str, "type": str, "provenance": {source_id, version, start, end, quote}}
    LLM 백엔드가 enum 밖 type 을 낸 상황을 재현·집계하려고 일부러 dict 부터 검증한다.
    """
    report = ValidationReport()

    # source_id 별 청크 묶음(quote 검증용).
    chunks_by_source: dict[str, list[dict]] = {}
    for c in chunks:
        chunks_by_source.setdefault(c["source_id"], []).append(c)

    for raw in raw_entities:
        # 1) enum + 구조 검증. Pydantic 이 NodeType enum 밖 라벨을 막는다.
        try:
            ent = Entity.model_validate(raw)
        except ValidationError as exc:
            label = raw.get("type")
            allowed = [t.value for t in NodeType]
            reason = (
                f"enum 위반 또는 구조 오류: type={label!r} (허용 {allowed})"
                if label not in allowed
                else f"구조 오류: {exc.error_count()}건"
            )
            report.rejected.append(RejectRecord(raw=raw, reason=reason))
            continue

        # 2) span quote 무결성. body[start:end] == quote 여야 한다.
        if not _quote_matches(ent.provenance, chunks_by_source):
            report.rejected.append(
                RejectRecord(raw=raw, reason="span quote 불일치(body[start:end] != quote)")
            )
            continue

        report.accepted.append(ent)

    return report


def print_report(report: ValidationReport) -> None:
    """검증 리포트를 사람이 읽게 출력한다."""
    print("=== 엔티티 검증 리포트 ===")
    print(f"총 후보 {report.total}건 — accept {len(report.accepted)} / reject {len(report.rejected)}")
    if report.accepted:
        print("--- accepted ---")
        for e in report.accepted:
            print(f"  [OK]     {e.name:<10} {e.type.value:<12} src={e.provenance.source_id}")
    if report.rejected:
        print("--- rejected (reject queue 로 보존) ---")
        for r in report.rejected:
            name = r.raw.get("name", "?")
            print(f"  [REJECT] {name:<10} {r.reason}")


if __name__ == "__main__":
    # 키 없이 도는 점검: 정상 1건 + enum 위반 1건 + 깨진 quote 1건.
    good_chunk = {
        "chunk_id": "src-05-lightrag::c012",
        "source_id": "src-05-lightrag",
        "version": "v1@ab12cd34",
        "char_start": 1200,
        "char_end": 1230,
        "text": "LightRAG is a graph-based RAG",
    }
    raws = [
        {  # 정상: text[0:8]=="LightRAG", body[1200:1208] 동치
            "name": "LightRAG",
            "type": "Model",
            "provenance": {
                "source_id": "src-05-lightrag",
                "version": "v1@ab12cd34",
                "start": 1200,
                "end": 1208,
                "quote": "LightRAG",
            },
        },
        {  # enum 위반: 'Framework' 는 NodeType 에 없다 → reject
            "name": "LightRAG",
            "type": "Framework",
            "provenance": {
                "source_id": "src-05-lightrag",
                "version": "v1@ab12cd34",
                "start": 1200,
                "end": 1208,
                "quote": "LightRAG",
            },
        },
        {  # quote 깨짐: body[1200:1208] 는 'LightRAG' 인데 quote 가 다름 → reject
            "name": "LightRAG",
            "type": "Model",
            "provenance": {
                "source_id": "src-05-lightrag",
                "version": "v1@ab12cd34",
                "start": 1200,
                "end": 1208,
                "quote": "WRONGTXT",
            },
        },
    ]
    rep = validate_raw_entities(raws, [good_chunk])
    print_report(rep)
