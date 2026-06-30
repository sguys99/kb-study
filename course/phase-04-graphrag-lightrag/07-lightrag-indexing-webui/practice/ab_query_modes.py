"""같은 골든 질문 셋을 5모드(naive/local/global/hybrid/mix)로 aquery 해 A/B 한다.

전제: index_corpus.py 로 이미 같은 working_dir 에 인덱싱이 끝나 있어야 한다.
      (인덱싱은 한 번, 질의만 다섯 번 — 5모드가 같은 저장소를 공유한다.)

핵심: QueryParam(mode=...) 만 바꾸고 나머지(top_k/chunk_top_k/enable_rerank)는
      고정해 모드 차이만 깨끗하게 비교한다.

      Core 코드로 직접 부를 때 권장 기본 모드는 mix 다.
      (API 서버/WebUI 에서 prefix 없이 던지면 기본은 hybrid — 다른 값이다.)

출력: 콘솔 표 + ab_result.json (question × mode 답·인용 수).
"""

import asyncio
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from lightrag import QueryParam

# index_corpus 의 백엔드 팩토리·저장소 초기화를 그대로 재사용한다(중복 정의 금지).
from index_corpus import build_rag

load_dotenv()

MODES = ["naive", "local", "global", "hybrid", "mix"]  # 영문 소문자 고정
DEFAULT_CORE_MODE = "mix"  # Core 직접 호출 권장 기본(WebUI 무prefix 기본은 hybrid)

OUT_PATH = os.environ.get("AB_OUT", "./ab_result.json")

# 골든 질문 — type 라벨을 달아 둔다(4.5의 type 구분 그대로).
GOLDEN_QUESTIONS = [
    {"id": "q1", "type": "simple-fact", "question": "VoyageAI의 기본 임베딩 모델 이름은?"},
    {"id": "q2", "type": "multi-hop", "question": "Neo4j와 RAG는 어떻게 이어지나?"},
    {"id": "q3", "type": "global-summary", "question": "이 코퍼스의 GraphRAG 연구 흐름을 전체 요약해줘."},
]


def query_param(mode: str) -> QueryParam:
    """모드만 바꾸고 나머지는 고정 — 모드 차이만 비교되게."""
    return QueryParam(
        mode=mode,
        top_k=60,            # KG 엔티티/관계 상한
        chunk_top_k=20,      # 텍스트 청크 상한
        enable_rerank=True,  # mix는 reranker와 함께 권장(RERANK_BINDING 없으면 무시됨)
    )


def short(text: str, n: int = 80) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1] + "…"


async def main() -> None:
    rag = await build_rag()
    results = []
    try:
        for q in GOLDEN_QUESTIONS:
            print(f"\n=== [{q['type']}] {q['question']} ===")
            row = {"id": q["id"], "type": q["type"], "question": q["question"], "answers": {}}
            for mode in MODES:
                answer = await rag.aquery(q["question"], param=query_param(mode))
                row["answers"][mode] = answer
                tag = "  <- Core 권장 기본" if mode == DEFAULT_CORE_MODE else ""
                print(f"  [{mode:6}] {short(answer)}{tag}")
            results.append(row)
    finally:
        await rag.finalize_storages()

    Path(OUT_PATH).write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[저장] {Path(OUT_PATH).resolve()}")
    print("[읽는 법] simple-fact는 naive로도 충분한가, multi-hop은 local이, "
          "global-summary는 global이 naive(=Phase 1 Baseline)보다 나은가를 본다.")
    print("[기본 모드] Core 직접 호출 = mix, WebUI 무prefix = hybrid (반드시 구분)")


if __name__ == "__main__":
    asyncio.run(main())
