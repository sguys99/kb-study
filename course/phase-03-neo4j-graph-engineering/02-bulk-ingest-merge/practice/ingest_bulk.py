"""Phase 2/06 그래프(JSONL 3개)를 Neo4j 에 UNWIND 배치로 idempotent 하게 대량 적재한다.

3/01 은 엔티티 한 건씩 execute_write 루프로 MERGE 했다(소수 노드 확인용).
이 토픽은 그걸 끌어올린다 — 파일 전체를 list[dict] 로 읽어 파라미터 $rows 하나로 넘기고,
Cypher 의 UNWIND $rows AS row ... MERGE 로 한 트랜잭션에 통째로 적재한다.
per-row 루프 대비 네트워크 왕복과 트랜잭션 횟수가 행 수만큼 줄어 훨씬 빠르다.

핵심 처리 4가지:
  1) 제약 먼저       — 적재 전에 유니크 제약/인덱스를 건다(constraints.cypher 와 동일 내용).
  2) 엔드포인트 해소  — relations 의 head/tail 은 '이름'인데 노드 키는 canonical_id 다.
                       entities 파일로 name -> canonical_id 맵을 만들어 해소한다(= Phase 2 ER 적용).
  3) 미해소 fallback  — entities 에 없는 이름(예: "LangChain")은 결정적 슬러그 id 를 부여하고
                       n.unresolved = true 플래그를 단다. 단일 유니크 키 유지 + idempotent + 추후 보강 추적.
  4) 동적 관계 타입   — Cypher 는 관계 타입을 파라미터로 못 받는다. 타입별로 그룹핑해 타입당 UNWIND
                       한 번씩 실행하고, 타입 문자열은 코드가 통제하는 화이트리스트만 f-string 으로 박는다.

전제:
  - Neo4j 5.26 기동 중(bolt://localhost:7687) — docker compose up -d
  - pip install -r requirements.txt
  - 접속 정보는 환경변수에서 읽는다. 미설정 시 로컬 docker 기본값(3/01 connect.py 와 동일 규약).
      NEO4J_URI      (기본 bolt://localhost:7687)
      NEO4J_USER     (기본 neo4j)
      NEO4J_PASSWORD (기본 testpassword1)
  - 이 토픽은 LLM·임베딩 API 를 쓰지 않는다. 키 불필요, 과금 없음(로컬 Neo4j 만).

실행:
  python ingest_bulk.py                 # 동봉 data/ 의 JSONL 을 적재
  python ingest_bulk.py --data-dir ../../../phase-02-knowledge-graph/06-quality-gate-incremental/practice
                                        # Phase 2/06 원본을 직접 가리키고 싶을 때
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

from neo4j import GraphDatabase

# --- 접속 정보(3/01 규약과 동일) ---------------------------------------------
URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
AUTH = (
    os.environ.get("NEO4J_USER", "neo4j"),
    os.environ.get("NEO4J_PASSWORD", "testpassword1"),
)

# --- 입력 파일 위치 ----------------------------------------------------------
# 기본은 재현성을 위해 동봉한 data/ 의 사본을 읽는다(Phase 2/06 원본과 내용 동일).
DEFAULT_DATA_DIR = Path(__file__).parent / "data"
ENTITIES_FILE = "sample_canonical_entities.jsonl"
RELATIONS_FILE = "normalized_relations.jsonl"
EVENTS_FILE = "events.normalized.jsonl"

# 관계 타입 화이트리스트 — Cypher 에 f-string 으로 박히는 값은 반드시 이 집합 안에서만 나와야 한다.
# 우리 데이터의 4종. 외부 입력이 그대로 타입으로 들어가면 주입 위험이 있으므로 코드가 통제한다.
ALLOWED_REL_TYPES = {"COMPARES_TO", "DEVELOPED_BY", "IMPROVES", "USES"}


# === 입출력 유틸 =============================================================
def read_jsonl(path: Path) -> list[dict]:
    """JSONL 한 줄 = dict 한 개로 읽는다. 빈 줄은 건너뛴다."""
    rows: list[dict] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def slugify_unresolved(name: str) -> str:
    """미해소 이름을 결정적 fallback canonical_id 로 만든다.

    같은 이름이면 항상 같은 id 가 나와야 재적재가 idempotent 하다.
    예: "LangChain" -> "ent-unresolved-langchain"
    """
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return f"ent-unresolved-{slug}"


# === 1) 이름 -> canonical_id 맵 + 미해소 노드 수집 ============================
def build_name_index(entities: list[dict]) -> dict[str, str]:
    """canonical entities 로 name -> canonical_id 맵을 만든다.

    Phase 2 가 정리한 aliases 도 같은 canonical_id 로 매핑해 둔다(별칭으로 들어온 endpoint 도 해소).
    """
    name2id: dict[str, str] = {}
    for ent in entities:
        cid = ent["canonical_id"]
        name2id[ent["name"]] = cid
        for alias in ent.get("aliases", []):
            name2id[alias] = cid
    return name2id


def resolve_endpoint(name: str, name2id: dict[str, str], unresolved: dict[str, dict]) -> str:
    """endpoint 이름을 canonical_id 로 해소한다.

    맵에 있으면 그 id, 없으면 fallback id 를 만들고 unresolved 노드로 등록한다.
    unresolved 는 {canonical_id: {canonical_id, name, unresolved}} 형태로 쌓인다(중복 자동 병합).
    """
    if name in name2id:
        return name2id[name]
    fallback = slugify_unresolved(name)
    unresolved.setdefault(
        fallback,
        {"canonical_id": fallback, "name": name, "unresolved": True},
    )
    return fallback


# === 2) 적재 단위 Cypher (UNWIND + MERGE) ====================================
def ingest_entities(tx, rows: list[dict]) -> None:
    """엔티티 노드를 UNWIND 배치로 한 번에 MERGE.

    MERGE 의미론 = idempotent upsert. 같은 canonical_id 면 새로 만들지 않고 재사용한다.
    Phase 2/06 graph_store.py 가 흉내 낸 "같은 키면 누적" 이 여기선 엔진 기능 그대로다.
    """
    tx.run(
        """
        UNWIND $rows AS row
        MERGE (n:Entity {canonical_id: row.canonical_id})
        ON CREATE SET n.created = timestamp()
        SET n.name = row.name,
            n.type = row.type,
            n.unresolved = coalesce(row.unresolved, false)
        """,
        rows=rows,
    )


def ingest_relations_of_type(tx, rel_type: str, rows: list[dict]) -> None:
    """한 가지 타입의 관계들을 UNWIND 배치로 MERGE.

    관계 타입은 파라미터로 못 넣어 f-string 으로 끼운다. rel_type 은 호출 전에
    ALLOWED_REL_TYPES 로 검증된 값만 들어온다(주입 방지).
    MERGE 키 = (head canonical_id, type, tail canonical_id).
    provenance 는 호출부에서 결정적으로 dedup 한 source_ids 리스트로 넘어온다.
    """
    if rel_type not in ALLOWED_REL_TYPES:
        raise ValueError(f"허용되지 않은 관계 타입: {rel_type}")
    tx.run(
        f"""
        UNWIND $rows AS row
        MERGE (h:Entity {{canonical_id: row.head_id}})
        MERGE (t:Entity {{canonical_id: row.tail_id}})
        MERGE (h)-[r:{rel_type}]->(t)
        ON CREATE SET r.created = timestamp()
        SET r.source_ids = row.source_ids,
            r.provenance_count = row.provenance_count
        """,
        rows=rows,
    )


def ingest_events(tx, rows: list[dict]) -> None:
    """이벤트 노드를 UNWIND 배치로 MERGE. roles 의 평탄한 속성만 노드에 SET."""
    tx.run(
        """
        UNWIND $rows AS row
        MERGE (e:Event {event_id: row.event_id})
        ON CREATE SET e.created = timestamp()
        SET e.type = row.type,
            e.time = row.time,
            e.value = row.value,
            e.year = row.year,
            e.venue = row.venue
        """,
        rows=rows,
    )


def ingest_event_about(tx, rows: list[dict]) -> None:
    """이벤트가 가리키는 published_work 를 canonical_id 로 해소해 (:Event)-[:ABOUT]->(:Entity) 연결.

    해소된 행만 넘어온다(미해소면 호출부에서 제외). 양 끝은 이미 존재하므로 MATCH 로 잡는다.
    """
    tx.run(
        """
        UNWIND $rows AS row
        MATCH (e:Event {event_id: row.event_id})
        MATCH (n:Entity {canonical_id: row.entity_id})
        MERGE (e)-[:ABOUT]->(n)
        """,
        rows=rows,
    )


# === 3) 입력 -> 적재용 행 변환 ===============================================
def prepare_rows(data_dir: Path) -> dict:
    """3개 JSONL 을 읽어 적재용 구조로 가공한다.

    반환:
      entity_rows         : 노드 행(미해소 fallback 노드 포함)
      relations_by_type   : {rel_type: [ {head_id, tail_id, source_ids, provenance_count}, ... ]}
      event_rows          : 이벤트 노드 행
      about_rows          : (event_id, entity_id) — published_work 해소 성공분만
    """
    entities = read_jsonl(data_dir / ENTITIES_FILE)
    relations = read_jsonl(data_dir / RELATIONS_FILE)
    events = read_jsonl(data_dir / EVENTS_FILE)

    name2id = build_name_index(entities)
    unresolved: dict[str, dict] = {}

    # --- 엔티티 행: canonical entities 는 unresolved=false ---
    entity_rows = [
        {
            "canonical_id": e["canonical_id"],
            "name": e["name"],
            "type": e["type"],
            "unresolved": False,
        }
        for e in entities
    ]

    # --- 관계 행: endpoint 해소 + provenance dedup + 타입별 그룹핑 ---
    relations_by_type: dict[str, list[dict]] = {}
    for rel in relations:
        rel_type = rel["type"]
        if rel_type not in ALLOWED_REL_TYPES:
            # 화이트리스트 밖 타입은 적재하지 않고 경고만(데이터 계약 위반).
            print(f"[WARN] 미등록 관계 타입 건너뜀: {rel_type}", file=sys.stderr)
            continue
        head_id = resolve_endpoint(rel["head"], name2id, unresolved)
        tail_id = resolve_endpoint(rel["tail"], name2id, unresolved)

        # provenance 를 결정적으로 dedup: source_id 기준 중복 제거 후 정렬.
        # 같은 스냅샷을 다시 적재해도 동일한 리스트가 나와 idempotent 하다.
        source_ids = sorted({p["source_id"] for p in rel.get("provenances", [])})

        relations_by_type.setdefault(rel_type, []).append(
            {
                "head_id": head_id,
                "tail_id": tail_id,
                "source_ids": source_ids,
                "provenance_count": len(source_ids),
            }
        )

    # --- 이벤트 행 + ABOUT 엣지(published_work 해소 성공분만) ---
    event_rows = []
    about_rows = []
    for ev in events:
        roles = ev.get("roles", {})
        event_rows.append(
            {
                "event_id": ev["event_id"],
                "type": ev["type"],
                "time": ev.get("time"),
                "value": ev.get("value"),
                "year": roles.get("year"),
                "venue": roles.get("venue"),
            }
        )
        work = roles.get("published_work")
        # 미해소 이름이면 ABOUT 을 만들지 않는다(엔티티 집합에 아직 없을 때는 생략).
        if work and work in name2id:
            about_rows.append({"event_id": ev["event_id"], "entity_id": name2id[work]})

    # 미해소 노드를 엔티티 행에 합친다(중복은 dict 키로 이미 병합됨).
    entity_rows.extend(unresolved.values())

    return {
        "entity_rows": entity_rows,
        "relations_by_type": relations_by_type,
        "event_rows": event_rows,
        "about_rows": about_rows,
        "unresolved_names": [u["name"] for u in unresolved.values()],
    }


# === 4) 제약 적용 + 카운트 ===================================================
CONSTRAINT_STATEMENTS = [
    "CREATE CONSTRAINT entity_canonical_id IF NOT EXISTS "
    "FOR (n:Entity) REQUIRE n.canonical_id IS UNIQUE",
    "CREATE CONSTRAINT event_id IF NOT EXISTS "
    "FOR (e:Event) REQUIRE e.event_id IS UNIQUE",
    "CREATE INDEX entity_name IF NOT EXISTS FOR (n:Entity) ON (n.name)",
]


def apply_constraints(driver) -> None:
    """적재 직전에 제약/인덱스를 건다. IF NOT EXISTS 라 여러 번 돌려도 안전."""
    with driver.session() as session:
        for stmt in CONSTRAINT_STATEMENTS:
            session.run(stmt)


def count_graph(driver) -> tuple[int, int, int]:
    """노드(라벨 무관)·관계·이벤트 수를 센다."""
    with driver.session() as session:
        nodes = session.run("MATCH (n) RETURN count(n) AS c").single()["c"]
        rels = session.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
        events = session.run("MATCH (e:Event) RETURN count(e) AS c").single()["c"]
    return nodes, rels, events


def ingest_all(driver, prepared: dict) -> None:
    """가공된 행들을 순서대로 적재: 엔티티 -> 관계(타입별) -> 이벤트 -> ABOUT."""
    with driver.session() as session:
        session.execute_write(ingest_entities, prepared["entity_rows"])
        for rel_type, rows in prepared["relations_by_type"].items():
            session.execute_write(ingest_relations_of_type, rel_type, rows)
        session.execute_write(ingest_events, prepared["event_rows"])
        if prepared["about_rows"]:
            session.execute_write(ingest_event_about, prepared["about_rows"])


# === 엔트리포인트 ============================================================
def run(data_dir: Path) -> tuple[int, int, int]:
    """제약 적용 -> 가공 -> 적재 -> 카운트. (nodes, rels, events) 반환.

    verify_idempotent.py 가 이 함수를 그대로 재사용한다.
    """
    prepared = prepare_rows(data_dir)
    if prepared["unresolved_names"]:
        print(f"[INFO] 미해소 endpoint -> fallback 노드 생성: {prepared['unresolved_names']}")

    with GraphDatabase.driver(URI, auth=AUTH) as driver:
        driver.verify_connectivity()
        apply_constraints(driver)          # 적재 전에 제약 먼저
        ingest_all(driver, prepared)
        nodes, rels, events = count_graph(driver)

    print(f"[OK] 적재 완료 — nodes={nodes} rels={rels} events={events}")
    return nodes, rels, events


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 2 그래프를 Neo4j 에 UNWIND 배치 적재")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help="JSONL 3개가 있는 디렉토리(기본: 동봉 data/)",
    )
    args = parser.parse_args()
    run(args.data_dir)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"[FAIL] {type(exc).__name__}: {exc}", file=sys.stderr)
        print("  - Neo4j 가 떠 있는지(docker compose ps), 포트가 7687 인지 확인하라.",
              file=sys.stderr)
        sys.exit(1)
