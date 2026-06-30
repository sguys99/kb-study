"""Docling 으로 PDF -> Markdown + 표(DataFrame/CSV) + 수식 LaTeX 추출.

전제:
- pip install docling  (requirements.txt 참고)
- API 키 불필요. 로컬에서 동작한다.
- source 는 로컬 PDF 경로 또는 arXiv pdf URL(예: https://arxiv.org/pdf/2404.16130) 둘 다 받는다.

사용:
    python parse_docling.py <input.pdf | pdf-url> [--out out/docling] [--no-formula]

산출:
    out/docling/<stem>.md          # 통짜 Markdown
    out/docling/<stem>.table_<i>.csv  # 표마다 행·열이 살아 있는 CSV
"""
from __future__ import annotations

import argparse
from pathlib import Path

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption


def build_converter(do_formula: bool) -> DocumentConverter:
    """수식 enrichment 옵션을 켠/끈 컨버터를 만든다.

    기본값에서는 수식이 LaTeX 로 남지 않으므로, 비교를 위해 켜는 것을 기본으로 한다.
    """
    if not do_formula:
        return DocumentConverter()
    opts = PdfPipelineOptions()
    opts.do_formula_enrichment = True  # 수식 -> LaTeX
    return DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)}
    )


def source_stem(source: str) -> str:
    """로컬 경로든 URL 이든 파일 stem 을 안전하게 뽑는다."""
    name = source.rstrip("/").split("/")[-1]
    return Path(name).stem or "document"


def run(source: str, out_dir: Path, do_formula: bool) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    conv = build_converter(do_formula)

    res = conv.convert(source)  # 로컬 경로 또는 URL
    doc = res.document

    # 1) 통짜 Markdown
    stem = source_stem(source)
    md = doc.export_to_markdown()
    md_path = out_dir / f"{stem}.md"
    md_path.write_text(md, encoding="utf-8")

    # 2) 표를 따로 꺼내 행·열이 살아 있는지 CSV 로 확인
    #    통짜 Markdown 만 보면 표 구조 손실을 못 알아챈다.
    n_tables = 0
    for i, table in enumerate(doc.tables):
        df = table.export_to_dataframe(doc=doc)
        df.to_csv(out_dir / f"{stem}.table_{i}.csv", index=False)
        n_tables += 1

    print(f"[docling] {source}")
    print(f"  -> {md_path}  (formula_enrichment={do_formula})")
    print(f"  -> 표 {n_tables}건 CSV 저장")


def main() -> None:
    ap = argparse.ArgumentParser(description="Docling PDF 파서")
    ap.add_argument("source", help="로컬 PDF 경로 또는 arXiv pdf URL")
    ap.add_argument("--out", default="out/docling", help="출력 디렉토리")
    ap.add_argument(
        "--no-formula",
        action="store_true",
        help="수식 enrichment 끄기(기본은 켬)",
    )
    args = ap.parse_args()
    run(args.source, Path(args.out), do_formula=not args.no_formula)


if __name__ == "__main__":
    main()
