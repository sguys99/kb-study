"""LightRAG Core 호출 최소 예시 — '07에서 실제로 돌린다'는 전제의 참고용.

⚠️ 이 파일은 06에서 실행하지 않는다. 06은 개념·선택 기준 토픽이고,
   실제 LightRAG 설치·인덱싱·5모드 A/B는 07-lightrag-indexing-webui가 담당한다.
   여기서는 "Core API가 어떻게 생겼나"를 눈으로 확인하는 용도로만 둔다.

실행 전제(07에서 충족):
  - pip install "lightrag-hku"
  - LLM/임베딩 백엔드 키: 기본 스택은 Claude + VoyageAI.
      ANTHROPIC_API_KEY, VOYAGE_API_KEY 를 .env/os.environ 에서 읽는다.
    비용 대안(키 0): Ollama + bge-m3 로컬 백엔드로 llm_model_func/embedding_func를 교체.
  - initialize_storages() 를 반드시 호출(빠뜨리면 AttributeError: __aenter__).

아래 예시는 검증 결과의 현행 Core API를 그대로 따른다(데모는 OpenAI 백엔드,
본 과정 기본은 Claude/Voyage 또는 Ollama+bge-m3로 함수만 교체).
"""

import asyncio

from lightrag import LightRAG, QueryParam
from lightrag.llm.openai import gpt_4o_mini_complete, openai_embed
from lightrag.utils import setup_logger

setup_logger("lightrag", level="INFO")


async def main():
    rag = LightRAG(
        working_dir="./rag_storage",
        llm_model_func=gpt_4o_mini_complete,   # 본 과정 기본은 Claude/Voyage 또는 Ollama로 교체
        embedding_func=openai_embed,
    )
    # REQUIRED — 빠뜨리면 AttributeError: __aenter__
    await rag.initialize_storages()

    # 한 번 인덱싱하면 5모드가 같은 그래프/벡터 저장소를 공유한다.
    await rag.ainsert("LightRAG는 KG와 vector 검색을 한 프레임워크로 묶는다.",
                      file_paths="intro.txt")

    # 같은 질문을 모드만 바꿔 던지는 게 07의 A/B 골격이다.
    for mode in ["naive", "local", "global", "hybrid", "mix"]:
        answer = await rag.aquery(
            "LightRAG는 무엇을 통합하나?",
            param=QueryParam(
                mode=mode,
                top_k=60,        # KG 엔티티/관계 상한
                chunk_top_k=20,  # 텍스트 청크 상한
                enable_rerank=True,
            ),
        )
        print(f"[{mode}] {answer}")

    await rag.finalize_storages()


if __name__ == "__main__":
    # 07에서 키/패키지를 갖춘 뒤 실행한다.
    asyncio.run(main())
