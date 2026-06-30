"""07 코퍼스를 LightRAG 로 인덱싱하되, 그래프 스토리지만 Neo4j 로 띄운다.

07 과의 차이는 딱 하나다. LightRAG(...) 에 graph_storage="Neo4JStorage" 를 넘긴다.
그러면 KG(엔티티·관계)만 Neo4j 로 가고, KV/Vector/DocStatus 는 그대로
WORKING_DIR(파일)에 남는다. 벡터까지 옮기는 게 아니다(자주 하는 착각).

왜 그래프만 Neo4j 로 빼나:
  Cypher 로 그래프를 직접 질의하고, Neo4j Browser 로 시각화하고, 여러 프로세스가
  같은 그래프에 동시 접근하고, 백업·복구를 DB 기능으로 한다. 운영에 필요한 것들이다.

실행 전제:
  - pip install -r requirements.txt   (lightrag-hku[api] + neo4j 드라이버)
  - docker compose up -d              (neo4j:5.26 + lightrag, 둘 다 healthy)
  - .env 작성(.env.example 참고). 기본 스택 = Claude + VoyageAI.
      ANTHROPIC_API_KEY, VOYAGE_API_KEY 를 .env/os.environ 에서 읽는다(하드코딩 금지).
      Neo4j: NEO4J_URI / NEO4J_USERNAME / NEO4J_PASSWORD / NEO4J_DATABASE.
      NEO4J_DATABASE 는 community edition 에서 필수다(누락 시 연결 실패).
    비용 0 대안 = Ollama + bge-m3. BACKEND=ollama 로 두면 키 없이 로컬에서 돈다.
  - initialize_storages() + initialize_pipeline_status() 를 반드시 호출(07과 동일).

주의:
  백엔드 선택은 문서 추가 전에 정해야 한다. 파일 그래프로 이미 인덱싱한 working_dir 을
  중간에 Neo4j 로 바꿔 이어 쓸 수 없다. 새 working_dir/DB 로 처음부터 인덱싱한다.

코퍼스 위치:
  - 기본 ./corpus 아래 .txt/.md (07 의 01~03 + 이 토픽에서 더한 04).
    04 는 증분 데모용이라, 첫 적재에서 04 를 빼고 싶으면 CORPUS_GLOB 로 거른다.
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

# 그래프 스토리지 백엔드. 08 의 핵심 — 이 한 줄이 KG 를 Neo4j 로 보낸다.
GRAPH_STORAGE = os.environ.get("LIGHTRAG_GRAPH_STORAGE", "Neo4JStorage")


def require_env(name: str) -> None:
    if not os.environ.get(name):
        raise RuntimeError(
            f"환경변수 {name} 가 없다. .env.example 을 .env 로 복사해 채우거나 "
            f"BACKEND=ollama 로 비용 0 대안을 쓴다."
        )


def require_neo4j_env() -> None:
    """Neo4j 백엔드를 쓸 때만 호출. NEO4J_DATABASE 누락이 가장 흔한 함정이다."""
    for name in ("NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD", "NEO4J_DATABASE"):
        if not os.environ.get(name):
            raise RuntimeError(
                f"환경변수 {name} 가 없다. graph_storage=Neo4JStorage 는 4개를 모두 요구한다. "
                f"특히 NEO4J_DATABASE 는 community edition 필수(누락 시 연결 실패)."
            )


# --- 백엔드 팩토리: 07 그대로 (함수 두 개만 갈아끼운다) -----------------------
def build_backend(backend: str):
    """LLM 함수와 임베딩 함수를 backend 선택에 따라 만들어 돌려준다(07 계승)."""
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


def load_corpus(corpus_dir: str):
    """corpus_dir 아래 .txt/.md 파일을 (상대경로, 본문) 으로 읽어 yield (07 계승)."""
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
    """그래프 스토리지만 Neo4j 로 둔 LightRAG 를 만들고 초기화한다.

    incremental_insert.py · delete_ops.py 가 이 함수를 그대로 재사용한다(중복 정의 금지).
    같은 graph_storage·working_dir 로 만들어야 같은 저장소를 가리킨다.
    """
    llm_model_func, embedding_func, llm_model_name, llm_kwargs = build_backend(BACKEND)

    if GRAPH_STORAGE == "Neo4JStorage":
        require_neo4j_env()

    rag = LightRAG(
        working_dir=WORKING_DIR,
        graph_storage=GRAPH_STORAGE,  # 08 의 핵심 — KG 만 Neo4j 로 (KV/Vector/DocStatus 는 파일)
        llm_model_func=llm_model_func,
        llm_model_name=llm_model_name,
        llm_model_kwargs=llm_kwargs,
        embedding_func=embedding_func,
        summary_max_tokens=int(os.environ.get("MAX_TOKENS", "4000")),
        # 캐시: 재인덱싱·반복 질의 비용 절감(기본 True). 캐시는 KV 스토리지에 저장된다.
        enable_llm_cache=os.environ.get("ENABLE_LLM_CACHE", "true").lower() == "true",
        enable_llm_cache_for_entity_extract=(
            os.environ.get("ENABLE_LLM_CACHE_FOR_EXTRACT", "true").lower() == "true"
        ),
    )
    # REQUIRED — 빠뜨리면 AttributeError: __aenter__ (07과 동일)
    await rag.initialize_storages()
    await initialize_pipeline_status()
    return rag


async def main() -> None:
    print(f"[backend] {BACKEND}   [graph_storage] {GRAPH_STORAGE}")
    print(f"[working_dir] {WORKING_DIR}  (KV/Vector/DocStatus)   [corpus] {CORPUS_DIR}")
    rag = await build_rag()
    try:
        count = 0
        for rel_path, text in load_corpus(CORPUS_DIR):
            print(f"  인덱싱: {rel_path}  ({len(text)} chars)")
            # ainsert 가 청킹→추출→KG(Neo4j)+벡터(파일) 저장까지 끝낸다.
            # 같은 내용을 다시 ainsert 해도 doc id(내용 해시)로 스킵된다(증분 정책).
            await rag.ainsert(text, file_paths=rel_path)
            count += 1
        print(f"[완료] 문서 {count}건 인덱싱.")
        print(f"       그래프 → Neo4j  /  KV·Vector·DocStatus → {Path(WORKING_DIR).resolve()}")
        print("       Neo4j Browser(http://localhost:7474)에서 MATCH (n) RETURN count(n) 으로 확인.")
    finally:
        await rag.finalize_storages()


if __name__ == "__main__":
    asyncio.run(main())
