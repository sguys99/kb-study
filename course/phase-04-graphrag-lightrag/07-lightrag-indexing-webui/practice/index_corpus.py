"""러닝 코퍼스(AI/LLM 기술 문서)를 LightRAG로 한 번 인덱싱한다.

핵심: ainsert 한 호출이 청킹 → 엔티티/관계 추출 → KG 저장 → 벡터 저장까지
      한 번에 끝낸다. 한 번 인덱싱하면 5모드(naive/local/global/hybrid/mix)가
      같은 working_dir 저장소를 공유한다. 모드를 바꾼다고 재인덱싱하지 않는다.

실행 전제:
  - pip install -r requirements.txt   ("lightrag-hku[api]")
  - .env 작성(.env.example 참고). 기본 스택 = Claude + VoyageAI.
      ANTHROPIC_API_KEY, VOYAGE_API_KEY 를 .env/os.environ 에서 읽는다(하드코딩 금지).
    비용 0 대안 = Ollama + bge-m3. BACKEND=ollama 로 두면 키 없이 로컬에서 돈다.
  - initialize_storages() 를 반드시 호출(빠뜨리면 AttributeError: __aenter__).

코퍼스 위치:
  - 기본 ./corpus 아래의 .txt/.md 파일을 읽는다.
  - Phase 1 산출물(원문/LLM Wiki)을 그대로 쓰려면 CORPUS_DIR 만 바꾸면 된다.
    예: CORPUS_DIR=../../../phase-01-*/.../source_docs
"""

import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv

from lightrag import LightRAG
from lightrag.kg.shared_storage import initialize_pipeline_status
from lightrag.utils import EmbeddingFunc, setup_logger

load_dotenv()
setup_logger("lightrag", level="INFO")

WORKING_DIR = os.environ.get("WORKING_DIR", "./rag_storage")
CORPUS_DIR = os.environ.get("CORPUS_DIR", "./corpus")
BACKEND = os.environ.get("BACKEND", "anthropic")  # anthropic(기본) | ollama(비용0)


# --- 백엔드 팩토리: 함수 두 개(llm_model_func, embedding_func)만 갈아끼운다 -----
def build_backend(backend: str):
    """LLM 함수와 임베딩 함수를 backend 선택에 따라 만들어 돌려준다.

    기본 스택(anthropic)과 비용 0 대안(ollama)이 같은 호출 시그니처를 갖도록
    LightRAG 제공 래퍼를 그대로 쓴다. index/query 코드는 백엔드를 모른다.
    """
    if backend == "ollama":
        # 비용 0 분기: Ollama + bge-m3 (키 불필요, 로컬 데몬 필요)
        from lightrag.llm.ollama import ollama_embed, ollama_model_complete

        host = os.environ.get("LLM_BINDING_HOST", "http://localhost:11434")
        llm_model_func = ollama_model_complete
        embedding_func = EmbeddingFunc(
            embedding_dim=int(os.environ.get("EMBEDDING_DIM", "1024")),
            func=lambda texts: ollama_embed(
                texts,
                embed_model=os.environ.get("EMBEDDING_MODEL", "bge-m3"),
                host=host,
            ),
        )
        llm_kwargs = {
            "hashing_kv": None,  # LightRAG가 내부에서 채운다
            "host": host,
            "options": {"num_ctx": 32768},
        }
        return llm_model_func, embedding_func, os.environ.get("LLM_MODEL", "qwen2.5"), llm_kwargs

    # 기본 스택: Claude(anthropic) + VoyageAI(voyage-3.5)
    from lightrag.llm.anthropic import anthropic_complete
    from lightrag.llm.voyageai import voyage_embed

    require_env("ANTHROPIC_API_KEY")
    require_env("VOYAGE_API_KEY")

    llm_model_func = anthropic_complete
    embedding_func = EmbeddingFunc(
        embedding_dim=int(os.environ.get("EMBEDDING_DIM", "1024")),
        func=lambda texts: voyage_embed(
            texts,
            model=os.environ.get("EMBEDDING_MODEL", "voyage-3.5"),
            api_key=os.environ["VOYAGE_API_KEY"],
        ),
    )
    llm_kwargs = {"api_key": os.environ["ANTHROPIC_API_KEY"]}
    return llm_model_func, embedding_func, os.environ.get("LLM_MODEL", "claude-3-5-haiku-latest"), llm_kwargs


def require_env(name: str) -> None:
    if not os.environ.get(name):
        raise RuntimeError(
            f"환경변수 {name} 가 없다. .env.example 을 .env 로 복사해 채우거나 "
            f"BACKEND=ollama 로 비용 0 대안을 쓴다."
        )


def load_corpus(corpus_dir: str):
    """corpus_dir 아래 .txt/.md 파일을 (상대경로, 본문) 으로 읽어 yield."""
    root = Path(corpus_dir)
    if not root.exists():
        raise FileNotFoundError(
            f"코퍼스 디렉토리가 없다: {root.resolve()}  "
            f"(CORPUS_DIR 로 Phase 1 산출물 경로를 지정하거나 ./corpus 에 문서를 둔다)"
        )
    files = sorted([*root.rglob("*.txt"), *root.rglob("*.md")])
    if not files:
        raise FileNotFoundError(f"{root.resolve()} 에 .txt/.md 문서가 없다.")
    for path in files:
        text = path.read_text(encoding="utf-8").strip()
        if text:
            yield str(path.relative_to(root)), text


async def build_rag() -> LightRAG:
    llm_model_func, embedding_func, llm_model_name, llm_kwargs = build_backend(BACKEND)

    rag = LightRAG(
        working_dir=WORKING_DIR,
        llm_model_func=llm_model_func,
        llm_model_name=llm_model_name,
        llm_model_kwargs=llm_kwargs,
        embedding_func=embedding_func,
        summary_max_tokens=int(os.environ.get("MAX_TOKENS", "4000")),
    )
    # REQUIRED — 빠뜨리면 AttributeError: __aenter__
    await rag.initialize_storages()
    await initialize_pipeline_status()
    return rag


async def main() -> None:
    print(f"[backend] {BACKEND}   [working_dir] {WORKING_DIR}   [corpus] {CORPUS_DIR}")
    rag = await build_rag()
    try:
        count = 0
        for rel_path, text in load_corpus(CORPUS_DIR):
            print(f"  인덱싱: {rel_path}  ({len(text)} chars)")
            # ainsert 한 호출이 청킹→엔티티/관계 추출→KG+벡터 저장까지 끝낸다
            await rag.ainsert(text, file_paths=rel_path)
            count += 1
        print(f"[완료] 문서 {count}건 인덱싱. 저장소: {Path(WORKING_DIR).resolve()}")
        print("       이제 ab_query_modes.py 로 5모드 A/B 를 돌리거나 WebUI 로 띄운다.")
    finally:
        await rag.finalize_storages()


if __name__ == "__main__":
    asyncio.run(main())
