"""스택 헬스체크 — Claude · Voyage · Neo4j · LightRAG 4개 컴포넌트를 각각 한 번씩 가볍게 점검한다.

전제:
  - .env 에 ANTHROPIC_API_KEY, VOYAGE_API_KEY, NEO4J_URI/USER/PASSWORD 가 채워져 있어야 한다.
  - Neo4j 는 docker compose up -d 로 먼저 기동돼 있어야 한다(bolt 7687).
  - 비용 대안: USE_LOCAL_EMBEDDING=1 이면 Voyage 점검은 로컬 임베딩 점검으로 대체된다.

실행: python healthcheck.py
완료 기준: 4개 컴포넌트 모두 OK 출력.
키·접속 정보는 환경변수에서만 읽는다(하드코딩 금지).
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


def check_claude() -> tuple[bool, str]:
    """Claude 에 1토큰짜리 호출을 던져 응답이 오는지 본다."""
    try:
        import anthropic

        if not os.environ.get("ANTHROPIC_API_KEY"):
            return False, "ANTHROPIC_API_KEY 미설정"
        client = anthropic.Anthropic()
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=5,
            messages=[{"role": "user", "content": "ping. 'pong' 한 단어로만 답하라."}],
        )
        text = resp.content[0].text.strip()
        return True, f"응답='{text}'"
    except Exception as e:  # noqa: BLE001 — 헬스체크는 모든 예외를 FAIL 로 본다
        return False, f"{type(e).__name__}: {e}"


def check_voyage() -> tuple[bool, str]:
    """임베딩 1건을 만들어 차원을 확인한다. 로컬 대안 분기도 여기서 흡수된다."""
    try:
        from embeddings import embed_query

        local = os.environ.get("USE_LOCAL_EMBEDDING", "0") == "1"
        if not local and not os.environ.get("VOYAGE_API_KEY"):
            return False, "VOYAGE_API_KEY 미설정"
        vec = embed_query("healthcheck")
        backend = "bge-m3(local)" if local else "voyage-3.5"
        return True, f"backend={backend}, dim={vec.shape[0]}"
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"


def check_neo4j() -> tuple[bool, str]:
    """드라이버로 접속해 verify_connectivity 로 bolt 연결을 확인한다."""
    try:
        from neo4j import GraphDatabase

        uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
        user = os.environ.get("NEO4J_USER", "neo4j")
        password = os.environ.get("NEO4J_PASSWORD")
        if not password:
            return False, "NEO4J_PASSWORD 미설정"
        driver = GraphDatabase.driver(uri, auth=(user, password))
        try:
            driver.verify_connectivity()
        finally:
            driver.close()
        return True, f"connected to {uri}"
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"


def check_lightrag() -> tuple[bool, str]:
    """LightRAG core 가 import 되고 핵심 심볼이 노출되는지 확인한다.

    본격 인덱싱은 Phase 4 에서 다룬다. 여기서는 설치/임포트 수준만 점검한다.
    """
    try:
        from lightrag import LightRAG, QueryParam  # noqa: F401

        return True, "import OK (LightRAG, QueryParam)"
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"


def main() -> None:
    checks = [
        ("Claude", check_claude),
        ("Voyage", check_voyage),
        ("Neo4j", check_neo4j),
        ("LightRAG", check_lightrag),
    ]
    results = []
    for name, fn in checks:
        ok, detail = fn()
        status = "OK  " if ok else "FAIL"
        print(f"[{status}] {name:9s} | {detail}")
        results.append(ok)

    print("-" * 60)
    if all(results):
        print("ALL OK — 스택 4개 컴포넌트 정상. 다음 토픽으로 진행하라.")
    else:
        failed = [n for (n, _), ok in zip(checks, results) if not ok]
        print(f"FAIL — 점검 필요: {', '.join(failed)}")


if __name__ == "__main__":
    main()
