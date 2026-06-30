"""schema_adapter.py — 2/03·2/04 산출물을 되살리는 Pydantic 모델 + 이 토픽의 산출 모델.

입력(앞 토픽 산출물):
  - Relation : 04 relations.resolved.jsonl (head/type/tail/provenance) — head/tail 은 이미 canonical 이름.
  - Event    : 03 events.jsonl (name/participants[]/time/provenance) — 아직 role 이 없는 밋밋한 참여자 리스트.
  - Claim    : 03 claims.jsonl (subject/predicate/object/value/provenance) — 수치 클레임.

산출(이 토픽이 만드는 것):
  - NormalizedRelation : (head, canonical_type, tail) + provenances[] (여러 근거 누적) + direction.
  - ReifiedEvent       : event_id/type/roles{role→entity}/time/value?/provenance — n-ary reification.

provenance 포맷은 03·04 와 동일(source_id/version/start/end/quote).
전제: pydantic>=2 만 필요. 네트워크·API 키 불필요.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Provenance(BaseModel):
    """근거 추적 메타. 03·04 와 같은 포맷."""

    source_id: str
    version: str
    start: int
    end: int
    quote: str


# ── 입력 모델 (앞 토픽 산출물을 되살린다) ──────────────────────────────────────


class Relation(BaseModel):
    """04 relations.resolved.jsonl 한 줄. head/tail 은 이미 canonical 이름."""

    head: str
    type: str
    tail: str
    provenance: Provenance


class Event(BaseModel):
    """03 events.jsonl 한 줄. participants 에 아직 role 라벨이 없다."""

    name: str
    participants: list[str]
    time: str | None = None
    provenance: Provenance


class Claim(BaseModel):
    """03 claims.jsonl 한 줄. 수치 클레임(value)을 들고 있다."""

    subject: str
    predicate: str
    object: str
    value: str | None = None
    provenance: Provenance


# ── 산출 모델 (이 토픽이 만든다) ──────────────────────────────────────────────


class NormalizedRelation(BaseModel):
    """정규화·방향통일·dedup 을 끝낸 관계 엣지.

    같은 (head, type, tail) 로 모인 여러 표면형의 provenance 를 리스트로 보존한다.
    카운트와 근거 quote 가 살아 있어야 2/06·Phase 4 가 쓴다.
    """

    head: str
    type: str  # vocab canonical relation type
    tail: str
    direction: str = Field(description="symmetric | asymmetric")
    provenances: list[Provenance] = Field(default_factory=list)

    @property
    def support(self) -> int:
        """이 엣지를 떠받치는 근거 개수(=병합된 표면형 수)."""
        return len(self.provenances)


class ReifiedEvent(BaseModel):
    """n-ary 사실을 담는 Event 노드(reification).

    이항 (head,type,tail) 으로 못 담는 3항 이상 사실을 노드 하나로 올린다.
    roles 는 role 이름 → 엔티티(또는 시간 리터럴) 매핑이다.
    """

    event_id: str
    type: str  # vocab canonical event type (PUBLICATION ...)
    roles: dict[str, str]  # role → entity name (또는 시간 같은 리터럴)
    time: str | None = None
    value: str | None = None
    provenance: Provenance
