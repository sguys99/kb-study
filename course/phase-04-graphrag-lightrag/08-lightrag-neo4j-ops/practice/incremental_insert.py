"""이미 적재된 그래프 위에 04 문서 1건만 증분 적재한다(재인덱싱 없음).

흐름:
  1) index_neo4j.py 로 01~03 이 이미 Neo4j 에 적재됐다고 가정한다.
  2) 적재 전 노드/관계/문서상태를 센다.
  3) corpus/04-*.md 1건만 ainsert 한다.
  4) 적재 후를 다시 세서 증분이 그래프에 반영됐는지 본다.

핵심:
  ainsert 는 문서 내용 해시(doc id)로 이미 처리된 문서를 스킵한다. 그래서
  04 만 새로 들어가고 01~03 은 다시 추출되지 않는다(전체 재인덱싱 불필요).
  DocStatus 스토리지가 pending→processing→processed 로 상태를 추적한다.

전제: index_neo4j.py 와 같은 .env / working_dir / Neo4j 를 가리켜야 한다.
      (build_rag 를 그대로 재사용하므로 graph_storage·working_dir 이 자동으로 일치한다.)
"""

import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv

# index_neo4j 의 build_rag(그래프=Neo4j 로 초기화)와 load_corpus 를 그대로 재사용.
from index_neo4j import build_rag, load_corpus
from graph_stats import doc_status_summary, neo4j_counts, print_delta

load_dotenv()

# 증분으로 새로 넣을 문서. 기본은 corpus/04-incremental-and-storage.md 1건.
NEW_DOC = os.environ.get("NEW_DOC", "04-incremental-and-storage.md")
CORPUS_DIR = os.environ.get("CORPUS_DIR", "./corpus")


def read_one(corpus_dir: str, filename: str) -> tuple[str, str]:
    """corpus_dir 아래 filename 한 건만 (상대경로, 본문) 으로 읽는다."""
    path = Path(corpus_dir) / filename
    if not path.exists():
        raise FileNotFoundError(
            f"증분 대상 문서가 없다: {path.resolve()}  "
            f"(NEW_DOC 로 다른 파일을 지정하거나 corpus/ 에 04 문서를 둔다)"
        )
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"{path} 가 비어 있다.")
    return filename, text


async def main() -> None:
    rag = await build_rag()
    try:
        before_graph = neo4j_counts()
        before_docs = await doc_status_summary(rag)
        print(f"[적재 전] Neo4j {before_graph}   DocStatus {before_docs}")

        rel_path, text = read_one(CORPUS_DIR, NEW_DOC)
        print(f"[증분] {rel_path} ({len(text)} chars) 만 ainsert (01~03 은 doc id 로 스킵)")
        await rag.ainsert(text, file_paths=rel_path)

        after_graph = neo4j_counts()
        after_docs = await doc_status_summary(rag)
        print(f"[적재 후] Neo4j {after_graph}   DocStatus {after_docs}")

        print_delta("Neo4j 그래프", before_graph, after_graph)
        print_delta("DocStatus", before_docs, after_docs)
        print(
            "\n[읽는 법] 노드/관계가 늘면 04 의 새 엔티티·관계가 들어간 것이다. "
            "processed 가 +1 이면 재인덱싱 없이 04 만 처리된 것."
        )
    finally:
        await rag.finalize_storages()


if __name__ == "__main__":
    asyncio.run(main())
