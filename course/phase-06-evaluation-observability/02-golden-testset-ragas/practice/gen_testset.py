# gen_testset.py — Ragas TestsetGenerator 로 코퍼스에서 golden testset 자동 생성.
#
# 왜:
#   손으로 만드는 golden set(golden_seed.jsonl)은 정확하지만 느리다. 코퍼스가
#   커지면 자동 생성이 필요하다. Ragas TestsetGenerator 는 문서에서 single-hop /
#   multi-hop 질문과 정답을 뽑아 준다. 빠르지만 반드시 사람이 검수해야 한다
#   (틀린 질문·정답·근거가 섞인다) — 자동 생성의 최대 함정.
#
# ── 전제(비용/키) ──────────────────────────────────────────────────────────
#   자동 생성은 LLM/임베딩을 많이 호출한다 → 과금된다. 소량(testset_size=5)부터.
#     필요 키: ANTHROPIC_API_KEY, VOYAGE_API_KEY.
#   키가 없으면 기본 모드(mock)로 "생성 대신 golden_seed.jsonl 을 그대로 보여준다".
#   비용 최소화: Ollama + bge-m3 로 바꿔도 API 는 동일하다(build_generator 주석).
#
# 실행:
#   python gen_testset.py                       # mock (키/과금 불필요)
#   python gen_testset.py --real --size 5       # 실제 생성(키·과금 필요)
#   python gen_testset.py --real --size 5 --corpus ./corpus
#
# 출력: generated_testset.jsonl (question / reference / reference_contexts 흉내)

from __future__ import annotations

import argparse
import json
from pathlib import Path

HERE = Path(__file__).parent
OUT_PATH = HERE / "generated_testset.jsonl"
SEED_PATH = HERE / "golden_seed.jsonl"


def build_generator():
    """TestsetGenerator 와 문서 로더에 쓸 LLM/임베딩 래퍼를 만든다(실제 모드 전용)."""
    from langchain_anthropic import ChatAnthropic
    from langchain_voyageai import VoyageAIEmbeddings
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from ragas.llms import LangchainLLMWrapper
    from ragas.testset import TestsetGenerator

    generator_llm = LangchainLLMWrapper(
        ChatAnthropic(model="claude-sonnet-4-5", temperature=0)
    )
    generator_embeddings = LangchainEmbeddingsWrapper(
        VoyageAIEmbeddings(model="voyage-3.5")
    )

    # ── 비용 최소화 분기(Ollama + bge-m3) ──────────────────────────────
    # from langchain_ollama import ChatOllama, OllamaEmbeddings
    # generator_llm = LangchainLLMWrapper(ChatOllama(model="llama3.1"))
    # generator_embeddings = LangchainEmbeddingsWrapper(
    #     OllamaEmbeddings(model="bge-m3"))
    # ───────────────────────────────────────────────────────────────────

    generator = TestsetGenerator(
        llm=generator_llm,
        embedding_model=generator_embeddings,
    )
    return generator


def load_corpus(corpus_dir: Path):
    """코퍼스 디렉토리의 .md/.txt 를 LangChain Document 로 읽는다(실제 모드)."""
    from langchain_core.documents import Document

    docs = []
    for path in sorted(corpus_dir.glob("**/*")):
        if path.suffix.lower() in {".md", ".txt"} and path.is_file():
            docs.append(Document(
                page_content=path.read_text(encoding="utf-8"),
                metadata={"source": str(path)},
            ))
    if not docs:
        raise SystemExit(f"코퍼스 문서를 못 찾았다: {corpus_dir} (.md/.txt 필요)")
    return docs


def generate_real(corpus_dir: Path, size: int) -> list[dict]:
    """실제 Ragas 자동 생성(과금). single-hop/multi-hop 이 섞여 나온다."""
    generator = build_generator()
    docs = load_corpus(corpus_dir)

    # 문서에서 바로 생성하는 편의 API. 내부에서 knowledge graph 를 만들고
    # single-hop / multi-hop 질문을 뽑는다.
    testset = generator.generate_with_langchain_docs(docs, testset_size=size)

    df = testset.to_pandas()
    rows = []
    for _, r in df.iterrows():
        rows.append({
            "question": r["user_input"],
            "reference": r["reference"],
            "reference_contexts": list(r.get("reference_contexts", [])),
            # 자동 생성 결과에는 hops/엔티티 라벨이 없다 → 검수 때 사람이 채운다.
            "hops": None,
            "gold_entities": [],
            "_needs_review": True,   # 자동 생성물은 반드시 검수 대상
        })
    return rows


def generate_mock(size: int) -> list[dict]:
    """API 없이 golden_seed.jsonl 을 '생성 결과인 척' 보여준다(과금 0)."""
    rows = []
    for line in SEED_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            item = json.loads(line)
            item["_needs_review"] = True   # 자동 생성물은 검수 필요를 명시
            rows.append(item)
    print(f"[mock] 실제 생성 대신 seed {len(rows)}건을 그대로 반환(과금 0). "
          f"실제 생성은 --real 로 실행하라.")
    return rows[:size]


def save(rows: list[dict], out: Path = OUT_PATH) -> None:
    with out.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"저장: {out} ({len(rows)}건)")
    review = sum(1 for r in rows if r.get("_needs_review"))
    if review:
        print(f"⚠️ 검수 필요 {review}건 — 질문·정답·근거가 맞는지 사람이 확인할 것.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Ragas Golden Testset 자동 생성")
    parser.add_argument("--real", action="store_true",
                        help="실제 TestsetGenerator 호출(키·과금 필요). 기본은 mock")
    parser.add_argument("--size", type=int, default=5, help="생성할 testset 크기")
    parser.add_argument("--corpus", type=str, default="./corpus",
                        help="코퍼스 디렉토리(.md/.txt). 실제 모드에서만 사용")
    args = parser.parse_args()

    if args.real:
        rows = generate_real(Path(args.corpus), args.size)
    else:
        rows = generate_mock(args.size)

    save(rows)


if __name__ == "__main__":
    main()
