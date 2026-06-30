"""Neo4j 연결 헬스체크.

전제:
  - docker-compose.yml 로 Neo4j 5.26 이 기동 중(bolt://localhost:7687)
  - pip install -r requirements.txt
  - 접속 정보는 환경변수에서 읽는다. 미설정 시 로컬 docker 기본값 사용.
    NEO4J_URI      (기본 bolt://localhost:7687)
    NEO4J_USER     (기본 neo4j)
    NEO4J_PASSWORD (기본 testpassword1)

실행:
  python connect.py
"""

import os
import sys

from neo4j import GraphDatabase

# 키는 절대 하드코딩하지 않는다. 환경변수 우선, 없으면 로컬 docker 기본값.
URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
USER = os.environ.get("NEO4J_USER", "neo4j")
PASSWORD = os.environ.get("NEO4J_PASSWORD", "testpassword1")
AUTH = (USER, PASSWORD)


def main() -> int:
    # 드라이버는 애플리케이션당 하나. with 블록이 끝나면 연결 풀을 닫는다.
    with GraphDatabase.driver(URI, auth=AUTH) as driver:
        # 연결이 안 되면 여기서 예외가 난다(서버 미기동·포트 오류·인증 실패).
        driver.verify_connectivity()
        print(f"[OK] connected to {URI} as {USER}")

        # execute_query: 세션·트랜잭션·재시도를 드라이버가 자동 관리하는 권장 API.
        records, summary, keys = driver.execute_query("RETURN 'pong' AS msg")
        print(f"[OK] query result: {records[0]['msg']}")

        # 서버 버전도 한 번 찍어 본다(5.26 또는 2025.x 가 나와야 한다).
        records, _, _ = driver.execute_query(
            "CALL dbms.components() YIELD name, versions, edition "
            "RETURN name, versions[0] AS version, edition"
        )
        for rec in records:
            print(f"[INFO] {rec['name']} {rec['version']} ({rec['edition']})")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # 연결 실패 시 원인을 보여주고 1 로 종료
        print(f"[FAIL] {type(exc).__name__}: {exc}", file=sys.stderr)
        print("  - Neo4j 컨테이너가 떠 있는지(docker compose ps), "
              "포트가 7687 인지 확인하라.", file=sys.stderr)
        sys.exit(1)
