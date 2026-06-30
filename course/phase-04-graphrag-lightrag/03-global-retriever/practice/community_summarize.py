"""4.3 community_summarize.py — 커뮤니티별 요약(Community Report)을 만들고 JSON 에 캐시한다.

Global 검색기의 두 번째 단추다. community_detect.py 가 나눈 커뮤니티 각각을
'한 단락 요약'으로 압축한다. 이 요약이 map-reduce 질의의 검색 단위가 된다.
원문 전체나 모든 노드를 LLM 에 매번 넣는 대신, 미리 만든 짧은 요약만 쓴다.
이게 *From Local to Global*(arXiv 2404.16130)의 핵심 절약 장치다.

파이프라인:
    1) e.community 로 노드를 묶는다(detect --write 가 채운 값).
    2) 커뮤니티마다 멤버 노드 + 내부 관계를 사람이 읽는 텍스트로 직렬화한다.
    3) 그 텍스트를 LLM 에 줘 짧은 요약 1건을 받는다(llm_backend.complete).
    4) 결과를 community_reports.json 에 캐시한다.

⚠️ 캐시가 핵심이다:
   요약은 한 번만 만들면 된다. 그래프가 안 바뀌면 다시 만들 이유가 없다.
   매 질문마다 요약을 새로 뽑으면 LLM 비용이 폭증한다. 그래서 결과를 JSON 에 저장하고,
   --refresh 를 주지 않는 한 캐시가 있으면 LLM 을 건너뛴다. global_retriever 는 이
   JSON 만 읽어 map-reduce 를 돌리므로, 한 번 만든 요약을 몇 번이고 공짜로 재사용한다.

전제:
    - Neo4j 5.26 + GDS 기동. community_detect.py --write 로 e.community 가 채워져 있어야 함.
    - LLM 백엔드: ANTHROPIC_API_KEY 있으면 Claude, 없으면 Ollama 로컬(llm_backend 규약).
      키는 os.environ 에서만 읽는다. 하드코딩 금지.

실행:
    python community_summarize.py            # 캐시 없으면 생성, 있으면 그대로 사용
    python community_summarize.py --refresh  # 캐시 무시하고 전부 다시 생성
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from neo4j import GraphDatabase

from llm_backend import active_backend, complete

URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
AUTH = (
    os.environ.get("NEO4J_USER", "neo4j"),
    os.environ.get("NEO4J_PASSWORD", "testpassword1"),
)

# 커뮤니티 요약 캐시 파일. global_retriever 가 이 파일을 읽는다.
REPORTS_PATH = Path(__file__).with_name("community_reports.json")


def fetch_members(driver) -> dict[int, list[dict]]:
    """e.community 로 노드를 묶어 {community_id: [멤버, ...]} 로 돌려준다."""
    cypher = """
    MATCH (n:Mini)
    WHERE n.community IS NOT NULL
    RETURN n.community AS cid, n.name AS name, n.type AS type
    ORDER BY cid, name
    """
    groups: dict[int, list[dict]] = {}
    with driver.session() as session:
        for r in session.run(cypher):
            groups.setdefault(r["cid"], []).append({"name": r["name"], "type": r["type"]})
    return groups


def fetch_internal_relations(driver, member_names: list[str]) -> list[tuple[str, str, str]]:
    """커뮤니티 멤버끼리 잇는 내부 관계만 가져온다(군집의 '내부 구조'를 요약에 넣기 위함)."""
    cypher = """
    MATCH (a:Mini)-[r]->(b:Mini)
    WHERE a.name IN $names AND b.name IN $names
    RETURN a.name AS src, type(r) AS rel, b.name AS dst
    ORDER BY src, dst
    """
    with driver.session() as session:
        rows = session.run(cypher, names=member_names)
        return [(r["src"], r["rel"], r["dst"]) for r in rows]


def serialize_community(members: list[dict], relations: list[tuple[str, str, str]]) -> str:
    """멤버 + 내부 관계를 LLM 에 줄 한 덩어리 텍스트로 직렬화한다."""
    lines = ["[엔티티]"]
    lines += [f"  - {m['name']} ({m['type']})" for m in members]
    lines.append("[관계]")
    if relations:
        lines += [f"  - {s} -[{rel}]- {d}" for s, rel, d in relations]
    else:
        lines.append("  - (커뮤니티 내부 관계 없음)")
    return "\n".join(lines)


def build_summary_prompt(serialized: str) -> str:
    """직렬화된 커뮤니티를 짧게 요약하라는 프롬프트. 한국어로, 군더더기 없이."""
    return (
        "다음은 지식그래프의 한 커뮤니티(주제 군집)를 이루는 엔티티와 관계다.\n"
        "이 군집이 '무엇에 관한 묶음인지'를 한국어 3~4문장으로 요약하라. "
        "핵심 주제, 주요 엔티티, 그들 사이 관계를 담되 과장하지 말고 사실만 적어라.\n\n"
        f"{serialized}\n\n요약:"
    )


def summarize_communities(driver, refresh: bool = False) -> dict:
    """커뮤니티별 요약을 만들어 캐시한다. 캐시가 있고 refresh 가 아니면 그대로 쓴다."""
    if REPORTS_PATH.exists() and not refresh:
        cached = json.loads(REPORTS_PATH.read_text(encoding="utf-8"))
        print(f"[캐시] {REPORTS_PATH.name} 재사용 — 커뮤니티 {len(cached['reports'])}개 "
              "(LLM 호출 0, 과금 0). 다시 만들려면 --refresh.")
        return cached

    print(f"[백엔드] LLM = {active_backend()}  (요약 생성에 실제 호출 발생)")
    groups = fetch_members(driver)
    reports = []
    for cid, members in sorted(groups.items()):
        names = [m["name"] for m in members]
        relations = fetch_internal_relations(driver, names)
        serialized = serialize_community(members, relations)
        summary = complete(build_summary_prompt(serialized), max_tokens=300)
        reports.append({
            "community": cid,
            "members": names,
            "summary": summary,
        })
        print(f"  community {cid}: {len(names)}개 멤버 요약 완료")

    result = {"reports": reports}
    REPORTS_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[캐시] {REPORTS_PATH.name} 저장 완료 — 커뮤니티 {len(reports)}개. "
          "global_retriever 가 이 파일을 읽어 map-reduce 를 돌린다.")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="커뮤니티별 요약(Community Report) 생성·캐시")
    parser.add_argument("--refresh", action="store_true",
                        help="캐시를 무시하고 요약을 전부 다시 생성")
    args = parser.parse_args()

    with GraphDatabase.driver(URI, auth=AUTH) as driver:
        driver.verify_connectivity()
        result = summarize_communities(driver, refresh=args.refresh)

    print("\n[미리보기]")
    for rep in result["reports"]:
        head = rep["summary"].replace("\n", " ")[:70]
        print(f"  c{rep['community']} ({', '.join(rep['members'][:3])}...): {head}...")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"[FAIL] {type(exc).__name__}: {exc}", file=sys.stderr)
        print("  - e.community 가 비었으면 community_detect.py --write 를 먼저 돌려라.",
              file=sys.stderr)
        print("  - LLM 호출 실패면 ANTHROPIC_API_KEY 또는 Ollama 기동을 확인하라.", file=sys.stderr)
        sys.exit(1)
