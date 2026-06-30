"""특정 문서 1건을 adelete_by_doc_id 로 지우고, 전후 그래프를 대조한다.

삭제는 단순 행 삭제가 아니다. 한 문서를 지우면 LightRAG 가
  청크 삭제 → 그 청크에만 연결된 엔티티/관계 정리 → 고아 엔티티 처리 →
  인덱스(벡터·DocStatus) 갱신
까지 그래프를 재구성한다. 다른 문서가 함께 참조하는 엔티티는 남고,
04 에서만 나온 엔티티는 사라진다. 그래서 노드/관계가 줄어드는 폭이
"04 만의 고유 엔티티" 크기다.

주의:
  - adelete_by_doc_id 는 async 전용이다. 동기로 부르는 API 는 없다(await 필수).
  - 파괴적 연산이라 LightRAG 가 삭제 중 동시 enqueue 를 차단해 일관성을 지킨다.
    동시성을 아무리 높여도 삭제는 직렬화된다.

전제: incremental_insert.py 로 04 가 이미 들어가 있어야 지울 게 있다.
      doc id 를 모를 때를 위해, 파일 경로로 doc id 를 역조회하는 헬퍼를 둔다.
"""

import asyncio
import os

from dotenv import load_dotenv

from index_neo4j import build_rag
from graph_stats import doc_status_summary, neo4j_counts, print_delta

load_dotenv()

# 지울 문서. doc id 를 알면 DOC_ID 로 바로 지정, 모르면 파일 경로로 역조회한다.
DOC_ID = os.environ.get("DOC_ID")           # 예: doc-abc123... (있으면 우선)
TARGET_FILE = os.environ.get("TARGET_FILE", "04-incremental-and-storage.md")


async def resolve_doc_id(rag, file_path: str) -> str:
    """file_paths 로 적재된 문서의 doc id 를 DocStatus 에서 역조회한다.

    LightRAG 의 doc id 는 내용 해시라 파일명만으론 알 수 없다. 처리 완료 문서
    목록에서 file_path 가 일치하는 항목을 찾는다.
    """
    docs = await rag.aget_docs_by_status("processed")
    # docs 는 {doc_id: status_obj} 형태. status_obj.file_path 로 매칭한다.
    for doc_id, status in docs.items():
        fp = getattr(status, "file_path", None)
        if fp is None and isinstance(status, dict):
            fp = status.get("file_path")
        if fp == file_path:
            return doc_id
    raise LookupError(
        f"file_path={file_path} 에 해당하는 processed 문서를 못 찾았다. "
        f"먼저 incremental_insert.py 로 적재했는지, TARGET_FILE 이 맞는지 확인한다."
    )


async def main() -> None:
    rag = await build_rag()
    try:
        before_graph = neo4j_counts()
        before_docs = await doc_status_summary(rag)
        print(f"[삭제 전] Neo4j {before_graph}   DocStatus {before_docs}")

        doc_id = DOC_ID or await resolve_doc_id(rag, TARGET_FILE)
        print(f"[삭제] doc_id={doc_id}  (await adelete_by_doc_id — async 전용)")
        # async 전용. 청크 삭제→연결 엔티티/관계 정리→고아 처리→인덱스 갱신을 한 번에.
        await rag.adelete_by_doc_id(doc_id)

        after_graph = neo4j_counts()
        after_docs = await doc_status_summary(rag)
        print(f"[삭제 후] Neo4j {after_graph}   DocStatus {after_docs}")

        print_delta("Neo4j 그래프", before_graph, after_graph)
        print_delta("DocStatus", before_docs, after_docs)
        print(
            "\n[읽는 법] 줄어든 노드/관계 = 04 에서만 나온 고유 엔티티/관계. "
            "01~03 과 공유된 엔티티는 남는다(고아만 정리). processed 가 -1 이면 04 가 빠진 것."
        )
    finally:
        await rag.finalize_storages()


if __name__ == "__main__":
    asyncio.run(main())
