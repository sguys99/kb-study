"""schema_adapter.py — 2/01 의 graph_schema.py 를 이 토픽으로 끌어온다.

스키마를 여기서 다시 정의하지 않는다. 추출 타깃은 2/01 에서 이미 못 박았다:
  Entity / Relation / Claim / Event / RelationType / NodeType / Provenance.
2/02 가 Entity 를, 2/03 이 Relation·Claim·Event 를 채웠다면, 이 토픽(2/04)은
그 점들을 '정제'한다. 같은 개체가 여러 표기로 흩어진 중복을 하나로 병합한다.
스키마는 단일 진실 원천(2/01)을 import 로 재사용한다(2/02·2/03 와 동일 패턴).

import 전략(둘 중 위가 우선):
  1) 2/01 practice 디렉토리를 sys.path 에 넣고 graph_schema 를 그대로 import.
     출처: ../01-text-to-graph-schema/practice/graph_schema.py
  2) 어떤 이유로든 import 가 실패하면(예: 파일 위치 이동) 명확한 에러로 죽인다.
     스키마를 몰래 복제해 두지 않는다 — 어긋남을 숨기는 게 더 위험하다.

전제: 네트워크·API 키 불필요. pydantic>=2 만 있으면 된다.
"""

from __future__ import annotations

import sys
from pathlib import Path

# 이 파일(.../04-.../practice/schema_adapter.py) 기준으로 2/01 practice 경로를 계산한다.
_HERE = Path(__file__).resolve().parent
_SCHEMA_DIR = (_HERE / ".." / ".." / "01-text-to-graph-schema" / "practice").resolve()

if str(_SCHEMA_DIR) not in sys.path:
    sys.path.insert(0, str(_SCHEMA_DIR))

try:
    # 출처: 2/01 graph_schema.py. 여기서 정의를 새로 만들지 않는다.
    from graph_schema import (  # type: ignore  # noqa: E402
        Claim,
        Entity,
        Event,
        GraphSchemaSample,
        NodeType,
        Provenance,
        Relation,
        RelationType,
    )
except ModuleNotFoundError as exc:  # pragma: no cover - 환경 점검용
    raise ModuleNotFoundError(
        "2/01 graph_schema.py 를 찾지 못했다. 경로를 확인하라: "
        f"{_SCHEMA_DIR}\n"
        "이 토픽은 2/01 스키마를 재사용한다(스키마 재정의 금지)."
    ) from exc

__all__ = [
    "Claim",
    "Entity",
    "Event",
    "GraphSchemaSample",
    "NodeType",
    "Provenance",
    "Relation",
    "RelationType",
]
