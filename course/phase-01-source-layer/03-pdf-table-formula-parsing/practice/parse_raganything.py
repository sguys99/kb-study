"""RAG-Anything 으로 '파싱만' 수행. 파서를 골라 쓰는 통합 계층 시연.

전제:
- pip install raganything  (또는 pip install "raganything[all]")
- RAG-Anything 은 파서가 아니라 LightRAG 기반 멀티모달 RAG 프레임워크다.
  내부에서 parser="mineru" | "docling" 로 실제 파서를 고른다.
- 03 에서는 파싱 단계만 다룬다. 질의(rag.aquery)는 LLM·임베딩이 필요하므로 Phase 4 예고.
  -> 따라서 이 스크립트는 LLM/임베딩 키 없이 도는 '파싱' 범위만 호출한다.
- parser="mineru" 를 쓰려면 MinerU 가 설치돼 있어야 한다(parse_mineru.py 주석 참고).

사용:
    python parse_raganything.py <input.pdf> [--parser mineru|docling] [--out out/raganything]

산출:
    out/raganything/ 아래에 선택한 파서가 떨군 Markdown/JSON.
"""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from raganything import RAGAnything, RAGAnythingConfig


async def parse_only(pdf_path: Path, parser: str, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    config = RAGAnythingConfig(
        working_dir="./rag_storage",
        parser=parser,            # "mineru"(기본·한국어 OCR) 또는 "docling"
        parse_method="auto",
        enable_image_processing=True,
    )
    rag = RAGAnything(config=config)

    # 파싱만 수행한다. 문서를 파싱해 산출 디렉토리에 콘텐츠를 떨군다.
    # (질의 rag.aquery 는 LLM·임베딩이 필요하므로 Phase 4 에서 붙인다.)
    await rag.parse_document(
        file_path=str(pdf_path),
        output_dir=str(out_dir),
        parse_method="auto",
    )
    print(f"[raganything] parser={parser}  -> {out_dir}/")
    print("  질의 단계(rag.aquery)는 Phase 4(LightRAG)에서 LLM·임베딩과 함께 다룬다.")


def main() -> None:
    ap = argparse.ArgumentParser(description="RAG-Anything 파싱(파서 선택 계층)")
    ap.add_argument("source", help="로컬 PDF 경로")
    ap.add_argument(
        "--parser",
        default="mineru",
        choices=["mineru", "docling"],
        help="내부에서 부를 실제 파서",
    )
    ap.add_argument("--out", default="out/raganything", help="출력 디렉토리")
    args = ap.parse_args()

    pdf_path = Path(args.source)
    if not pdf_path.exists():
        print(f"[오류] 입력 PDF 가 없다: {pdf_path}")
        raise SystemExit(1)

    asyncio.run(parse_only(pdf_path, args.parser, Path(args.out)))


if __name__ == "__main__":
    main()
