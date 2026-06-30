"""03 이 질의하던 같은 그래프의 각 Entity 에 임베딩과 description 을 부여한다.

03 그래프의 Entity 에는 텍스트 임베딩이 아직 없다. 벡터 검색을 하려면 각 엔티티를
"검색 가능한 문장"으로 만들고(=description), 그걸 임베딩해 e.embedding 속성으로 저장해야 한다.

description 을 어떻게 만드나:
  - 이름(name)
  - 별칭(aliases)        — 02 의 canonical entities JSONL 에서 가져온다.
  - 그 엔티티가 걸린 관계들의 근거 문장(provenance quote)
    └ 주의: 02 적재는 관계에 source_ids 만 저장하고 quote 텍스트는 Neo4j 에 넣지 않았다.
            그래서 quote 는 02 가 쓴 원본 relations JSONL 에서 직접 읽어 description 을 만든다.
            (같은 데이터를 입력으로 재사용 — 새 데이터셋을 만들지 않는다.)

저장 결과(각 :Entity 노드에):
  - e.description : 위 텍스트를 합친 한 문단
  - e.embedding   : 1024 차원 float 리스트(voyage-3.5 기본 차원)

전제:
  - Neo4j 5.26 기동 + 02 적재 완료(03 과 같은 그래프). docker compose up -d
  - pip install -r requirements.txt
  - 접속 정보는 환경변수에서 읽는다(02/03 규약과 동일).
      NEO4J_URI      (기본 bolt://localhost:7687)
      NEO4J_USER     (기본 neo4j)
      NEO4J_PASSWORD (기본 testpassword1)
  - 임베딩 백엔드:
      기본 voyage  → 환경변수 VOYAGE_API_KEY 필요(코드에 하드코딩 금지).
      비용 0 분기  → --backend ollama (로컬 Ollama 의 bge-m3, API 키·과금 없음).
                    ollama pull bge-m3 로 모델을 받아두고 ollama serve 가 떠 있어야 한다.
                    bge-m3 도 1024 차원이라 인덱스 차원 설정을 그대로 쓸 수 있다.

실행:
  python add_embeddings.py                       # VoyageAI voyage-3.5
  python add_embeddings.py --backend ollama      # 로컬 bge-m3 (비용 0)
"""

import argparse
import json
import os
import sys
from pathlib import Path

from neo4j import GraphDatabase

# --- 접속 정보(02/03 규약과 동일) -------------------------------------------
URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
AUTH = (
    os.environ.get("NEO4J_USER", "neo4j"),
    os.environ.get("NEO4J_PASSWORD", "testpassword1"),
)

# --- 02 가 적재에 쓴 원본 데이터 위치(quote·aliases 출처) ---------------------
# 02 의 practice/data/ 를 상대 경로로 가리킨다. 같은 그래프의 입력을 그대로 재사용.
DATA_DIR = Path(__file__).resolve().parents[2] / "02-bulk-ingest-merge" / "practice" / "data"
ENTITIES_FILE = "sample_canonical_entities.jsonl"
RELATIONS_FILE = "normalized_relations.jsonl"

EMBED_DIM = 1024  # voyage-3.5 기본 차원. bge-m3 도 1024 라 인덱스 설정을 공유한다.


# === 임베딩 백엔드 ===========================================================
def embed_texts(texts: list[str], backend: str = "voyage") -> list[list[float]]:
    """텍스트 리스트를 1024 차원 임베딩 리스트로 변환한다.

    backend="voyage"  → VoyageAI voyage-3.5 (VOYAGE_API_KEY 필요)
    backend="ollama"  → 로컬 Ollama bge-m3 (비용 0, 네트워크/키 불필요)

    hybrid_search.py 도 이 함수를 import 해 질의 임베딩에 그대로 쓴다.
    저장 임베딩과 질의 임베딩은 반드시 같은 모델이어야 코사인 유사도가 의미를 갖는다.
    """
    if backend == "voyage":
        return _embed_voyage(texts)
    if backend == "ollama":
        return _embed_ollama(texts)
    raise ValueError(f"알 수 없는 backend: {backend} (voyage | ollama)")


def _embed_voyage(texts: list[str]) -> list[list[float]]:
    """VoyageAI voyage-3.5 임베딩. 키는 환경변수에서만 읽는다(하드코딩 금지)."""
    import voyageai  # 지연 import — ollama 백엔드만 쓰면 voyageai 미설치여도 동작.

    api_key = os.environ.get("VOYAGE_API_KEY")
    if not api_key:
        raise RuntimeError(
            "VOYAGE_API_KEY 가 없다. export VOYAGE_API_KEY=... 하거나 "
            "--backend ollama 로 비용 0 로컬 임베딩을 쓴다."
        )
    client = voyageai.Client(api_key=api_key)
    # output_dimension=1024 명시 — voyage-3.5 는 256/512/1024/2048 중 고를 수 있고 기본 1024.
    result = client.embed(texts, model="voyage-3.5", output_dimension=EMBED_DIM)
    return result.embeddings


def _embed_ollama(texts: list[str]) -> list[list[float]]:
    """로컬 Ollama bge-m3 임베딩. ollama serve 가 localhost:11434 에 떠 있어야 한다."""
    import requests  # 지연 import — voyage 백엔드만 쓰면 불필요.

    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    out: list[list[float]] = []
    for text in texts:
        resp = requests.post(
            f"{host}/api/embeddings",
            json={"model": "bge-m3", "prompt": text},
            timeout=60,
        )
        resp.raise_for_status()
        out.append(resp.json()["embedding"])
    return out


# === description 만들기 ======================================================
def read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def build_descriptions() -> dict[str, dict]:
    """canonical_id 별로 description 재료를 모은다.

    반환: {canonical_id: {"name", "aliases", "quotes": [근거 문장...]}}
    quote 는 head/tail 양쪽 엔티티 모두에 귀속시킨다(그 엔티티가 등장하는 근거이므로).
    endpoint 이름 → canonical_id 매핑은 02 와 같은 규칙(name + aliases).
    """
    entities = read_jsonl(DATA_DIR / ENTITIES_FILE)
    relations = read_jsonl(DATA_DIR / RELATIONS_FILE)

    # name/alias -> canonical_id 맵 (02 build_name_index 와 동일 규칙)
    name2id: dict[str, str] = {}
    info: dict[str, dict] = {}
    for ent in entities:
        cid = ent["canonical_id"]
        name2id[ent["name"]] = cid
        for alias in ent.get("aliases", []):
            name2id[alias] = cid
        info[cid] = {
            "name": ent["name"],
            "aliases": ent.get("aliases", []),
            "quotes": [],
        }

    # 관계 quote 를 양 끝 엔티티의 description 재료로 누적
    for rel in relations:
        quotes = [p["quote"] for p in rel.get("provenances", []) if p.get("quote")]
        for endpoint in (rel.get("head"), rel.get("tail")):
            cid = name2id.get(endpoint)
            if cid and cid in info:
                info[cid]["quotes"].extend(quotes)

    return info


def compose_description(item: dict) -> str:
    """이름 + 별칭 + 근거 문장(dedup)을 한 문단으로 합친다."""
    parts = [item["name"]]
    if item["aliases"]:
        parts.append("aka " + ", ".join(item["aliases"]))
    # quote 중복 제거(순서 보존)
    seen: set[str] = set()
    uniq_quotes = []
    for q in item["quotes"]:
        if q not in seen:
            seen.add(q)
            uniq_quotes.append(q)
    parts.extend(uniq_quotes)
    return ". ".join(parts)


# === Neo4j 쓰기 ==============================================================
def fetch_entity_ids(driver) -> list[str]:
    """그래프에 실제로 적재된 Entity 의 canonical_id 목록(임베딩 대상)."""
    with driver.session() as session:
        return session.execute_read(
            lambda tx: [r["cid"] for r in tx.run(
                "MATCH (e:Entity) RETURN e.canonical_id AS cid ORDER BY cid"
            )]
        )


def write_embeddings(driver, rows: list[dict]) -> int:
    """canonical_id 별 description·embedding 을 UNWIND 배치로 SET.

    임베딩은 db.create.setNodeVectorProperty 로 저장한다 — 벡터 인덱스가 인식하는
    표준 방식이라 단순 SET 보다 권장된다(Neo4j 5.x 네이티브 벡터).
    """
    with driver.session() as session:
        result = session.execute_write(
            lambda tx: tx.run(
                """
                UNWIND $rows AS row
                MATCH (e:Entity {canonical_id: row.canonical_id})
                SET e.description = row.description
                WITH e, row
                CALL db.create.setNodeVectorProperty(e, 'embedding', row.embedding)
                RETURN count(e) AS n
                """,
                rows=rows,
            ).single()["n"]
        )
    return result


# === 엔트리포인트 ============================================================
def run(backend: str) -> int:
    descriptions = build_descriptions()

    with GraphDatabase.driver(URI, auth=AUTH) as driver:
        driver.verify_connectivity()

        graph_ids = fetch_entity_ids(driver)
        if not graph_ids:
            print("[FAIL] 그래프에 Entity 가 없다. 먼저 02 적재를 끝내라.", file=sys.stderr)
            return 1

        # 그래프에 실제 존재하는 엔티티만 임베딩한다(미해소 fallback 노드 포함 대응).
        targets = []
        for cid in graph_ids:
            item = descriptions.get(cid)
            if item is None:
                # JSONL 에 없던 fallback 노드(예: LangChain) — 이름만으로 description 구성.
                # 그래프에서 name 을 직접 읽어 채운다.
                item = {"name": cid, "aliases": [], "quotes": []}
            targets.append({"canonical_id": cid, "item": item})

        # fallback 노드의 name 을 그래프에서 보강
        _fill_missing_names(driver, targets)

        texts = [compose_description(t["item"]) for t in targets]
        print(f"[INFO] 임베딩 대상 {len(texts)} 개 엔티티, backend={backend}, dim={EMBED_DIM}")

        vectors = embed_texts(texts, backend=backend)
        if len(vectors) != len(texts):
            print("[FAIL] 임베딩 개수가 입력과 다르다.", file=sys.stderr)
            return 1
        if vectors and len(vectors[0]) != EMBED_DIM:
            print(f"[WARN] 임베딩 차원 {len(vectors[0])} != 기대 {EMBED_DIM}. "
                  "인덱스 차원 설정(indexes.cypher)과 맞는지 확인하라.", file=sys.stderr)

        rows = [
            {
                "canonical_id": t["canonical_id"],
                "description": compose_description(t["item"]),
                "embedding": vec,
            }
            for t, vec in zip(targets, vectors)
        ]
        n = write_embeddings(driver, rows)
        print(f"[OK] {n} 개 엔티티에 description·embedding({EMBED_DIM}d) 저장 완료.")
    return 0


def _fill_missing_names(driver, targets: list[dict]) -> None:
    """JSONL 에 없던 노드(fallback)의 name 을 그래프에서 읽어 item.name 에 채운다."""
    missing = [t["canonical_id"] for t in targets if t["item"]["name"] == t["canonical_id"]]
    if not missing:
        return
    with driver.session() as session:
        name_map = session.execute_read(
            lambda tx: {
                r["cid"]: r["name"]
                for r in tx.run(
                    "MATCH (e:Entity) WHERE e.canonical_id IN $ids "
                    "RETURN e.canonical_id AS cid, e.name AS name",
                    ids=missing,
                )
            }
        )
    for t in targets:
        cid = t["canonical_id"]
        if cid in name_map and name_map[cid]:
            t["item"]["name"] = name_map[cid]


def main() -> int:
    parser = argparse.ArgumentParser(description="03 그래프의 Entity 에 임베딩 부여")
    parser.add_argument(
        "--backend",
        choices=["voyage", "ollama"],
        default="voyage",
        help="임베딩 백엔드(기본 voyage / 비용 0 는 ollama)",
    )
    args = parser.parse_args()
    return run(args.backend)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"[FAIL] {type(exc).__name__}: {exc}", file=sys.stderr)
        print("  - Neo4j 가 떠 있는지(docker compose ps), 02 적재가 끝났는지 확인하라.",
              file=sys.stderr)
        print("  - VOYAGE_API_KEY 미설정 시 --backend ollama 로 비용 0 로컬 임베딩을 쓴다.",
              file=sys.stderr)
        sys.exit(1)
