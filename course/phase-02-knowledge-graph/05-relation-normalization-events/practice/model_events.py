"""model_events.py — 03 events.jsonl 의 밋밋한 participants[] 를 role 부여된 Event 로 reify.

이항 (head,type,tail) 으로는 "RAG was published at NeurIPS in 2020" 같은 3항 사실을
못 담는다(참여자 3: RAG, NeurIPS, 2020). W3C n-ary relations note 가 권하는 패턴이
바로 이것 — 관계 자체를 노드로 올려(reify) 각 참여자에 role 을 붙인다.

여기서는 결정적인 휴리스틱으로 role 을 배정한다.
  1) event name 토큰으로 vocab event type 을 찾는다(PUBLICATION ...). 못 찾으면 reject.
  2) time(예 "2020")은 vocab 의 time_role(예 year)에 박는다.
  3) 나머지 participants 는 event type 의 roles 슬롯에 순서대로 채운다.
     (실전이라면 타입 신호로 role 을 추론하지만, 강의용으로는 순서 휴리스틱이 충분하고 결정적이다.)

claims.jsonl 의 수치 클레임도 필요하면 MEASUREMENT Event 로 모델링할 수 있다(아래 함수).

전제: pyyaml + pydantic. 네트워크·API 키 불필요. 결정적.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from schema_adapter import Claim, Event, Provenance, ReifiedEvent

HERE = Path(__file__).resolve().parent
VOCAB_PATH = HERE / "relation_vocab.yaml"


def load_event_vocab(path: Path = VOCAB_PATH) -> dict:
    """relation_vocab.yaml 의 events 섹션만 펼친다.

    돌려주는 형태:
      {canonical_event_type: {"roles": [...], "time_role": <str|None>},
       "_synonym": {표면형: canonical_event_type}}
    """
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    events = data.get("events", {})
    synonym: dict[str, str] = {}
    spec: dict[str, dict] = {}
    for canon, body in events.items():
        spec[canon] = {"roles": body["roles"], "time_role": body.get("time_role")}
        for syn in body["synonyms"]:
            synonym[syn.upper()] = canon
    spec["_synonym"] = synonym
    return spec


def _match_event_type(name: str, synonym: dict[str, str]) -> str | None:
    """event name 토큰 중 하나라도 synonym 에 걸리면 그 canonical event type."""
    tokens = name.replace("-", "_").upper().split("_")
    for tok in tokens:
        if tok in synonym:
            return synonym[tok]
    return None


def _slug(text: str) -> str:
    """event_id 용 안정 슬러그."""
    out = []
    for ch in text.lower():
        out.append(ch if ch.isalnum() else "-")
    s = "".join(out)
    while "--" in s:
        s = s.replace("--", "-")
    return s.strip("-")


def reify_event(ev: Event, vocab: dict) -> ReifiedEvent | dict:
    """Event 한 건을 role 부여된 ReifiedEvent 로. 매핑 실패 시 reject dict 반환."""
    synonym = vocab["_synonym"]
    canon_type = _match_event_type(ev.name, synonym)
    if canon_type is None:
        return {
            "name": ev.name,
            "reason": "vocab 미등록 event type",
            "provenance": ev.provenance.model_dump(),
        }

    spec = vocab[canon_type]
    role_names: list[str] = list(spec["roles"])
    time_role: str | None = spec["time_role"]

    roles: dict[str, str] = {}

    # 1) time 값을 time_role 슬롯에 먼저 박는다(있으면).
    remaining_roles = list(role_names)
    if ev.time and time_role and time_role in remaining_roles:
        roles[time_role] = ev.time
        remaining_roles.remove(time_role)

    # 2) 남은 participants 를 남은 role 슬롯에 순서대로 채운다.
    for participant, role in zip(ev.participants, remaining_roles):
        roles[role] = participant

    event_id = f"evt-{canon_type.lower()}-{_slug(ev.name)}"
    return ReifiedEvent(
        event_id=event_id,
        type=canon_type,
        roles=roles,
        time=ev.time,
        value=None,
        provenance=ev.provenance,
    )


def reify_claim_as_measurement(claim: Claim, vocab: dict) -> ReifiedEvent:
    """수치 클레임(value 가 있는 Claim)을 MEASUREMENT Event 로 reify.

    예: {subject:LightRAG, predicate:reduces_token_cost, object:GraphRAG, value:"99%"}
        → MEASUREMENT{subject=LightRAG, metric=reduces_token_cost, value=99%, baseline=GraphRAG}
    이항 클레임에 '얼마나(value)' 와 '무엇 대비(baseline)' 를 함께 담으려면 reify 가 맞다.
    """
    spec = vocab["MEASUREMENT"]
    roles = {
        "subject": claim.subject,
        "metric": claim.predicate,
        "value": claim.value or "",
        "baseline": claim.object,
    }
    # spec.roles 에 없는 키는 떨군다(vocab 가 단일 기준).
    roles = {k: v for k, v in roles.items() if k in spec["roles"]}
    event_id = f"evt-measurement-{_slug(claim.subject)}-{_slug(claim.predicate)}"
    return ReifiedEvent(
        event_id=event_id,
        type="MEASUREMENT",
        roles=roles,
        time=None,
        value=claim.value,
        provenance=claim.provenance,
    )
