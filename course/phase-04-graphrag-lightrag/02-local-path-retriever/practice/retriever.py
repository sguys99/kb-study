"""4.2 retriever.py — Local·Path 검색기를 한 클래스로 묶는다(03/04 에서 import 용).

entity_linking + local_retriever + path_retriever 를 LocalPathRetriever 하나로 감싼다.
다음 토픽(03 Global Retriever, 04 Vector+Graph Fusion)이 이 클래스를 import 해서
"엔티티 링킹된 Local/Path 컨텍스트"를 바로 받아 쓸 수 있게 한다.

세션 수명을 클래스가 관리한다(컨텍스트 매니저). 사용 측은 with 한 줄이면 된다.

전제:
    - Neo4j 5.26 LTS 기동 + graph_setup.py 적재 완료.
    - 접속 정보는 NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD 환경변수. 키 불필요·과금 0.

실행(단독 데모):
    python retriever.py
"""

from __future__ import annotations

from entity_linking import link, get_driver, LinkResult
from local_retriever import local_retrieve
from path_retriever import path_retrieve


class LocalPathRetriever:
    """엔티티 링킹 위에 Local·Path 검색을 얹은 검색기. 03/04 의 입력 단으로 쓴다."""

    def __init__(self, driver=None):
        # driver 를 주입하면 그걸 쓰고(외부에서 수명 관리), 없으면 직접 만든다.
        self._owns_driver = driver is None
        self.driver = driver or get_driver()

    def __enter__(self) -> "LocalPathRetriever":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_driver and self.driver is not None:
            self.driver.close()

    def link(self, mention: str) -> LinkResult:
        """자연어 표현 하나를 :Mini 노드로 링킹한다."""
        with self.driver.session() as session:
            return link(session, mention)

    def local(self, mention: str, depth: int = 1) -> str:
        """Local 검색 — 시작 표현의 이웃 서브그래프 컨텍스트 문자열."""
        with self.driver.session() as session:
            return local_retrieve(session, mention, depth=depth)

    def path(self, mention_a: str, mention_b: str) -> str:
        """Path 검색 — 두 표현 사이 멀티홉 경로 근거 문장열."""
        with self.driver.session() as session:
            return path_retrieve(session, mention_a, mention_b)


def main() -> None:
    with LocalPathRetriever() as r:
        print("== 엔티티 링킹 ==")
        print(" ", r.link("light rag"))
        print("\n== Local (depth=1) ==")
        print(r.local("LightRAG", depth=1))
        print("\n== Path ==")
        print(r.path("Neo4j", "RAG"))


if __name__ == "__main__":
    main()
