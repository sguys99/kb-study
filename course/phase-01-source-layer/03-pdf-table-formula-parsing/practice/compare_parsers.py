"""세 파서 산출 Markdown 을 같은 자로 재어 한 표로 비교하는 하니스.

전제:
- 표준 라이브러리 + pandas 만 사용(파서 라이브러리 불필요).
- 먼저 parse_docling.py / parse_mineru.py / parse_raganything.py 를 돌려
  out/docling, out/mineru, out/raganything 아래에 Markdown 이 생겨 있어야 한다.
  (없는 파서는 'missing' 으로 표시하고 건너뛴다.)

지표(상대 비교용 — 절대값이 목적이 아니다):
- table_blocks   : Markdown table 블록 수(연속된 | 행을 한 블록으로 묶음)
- formula_tokens : $...$ 또는 \\[...\\] 수식 토큰 수
- hangul_chars   : 한글 음절 수
- hangul_ratio   : 입력 PDF 대비 한글 보존율 근사(--ref-hangul 로 기준 음절 수 전달)

사용:
    python compare_parsers.py [--root out] [--ref-hangul N]
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import pandas as pd

PARSERS = ["docling", "mineru", "raganything"]

TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
# $...$ (인라인) 또는 \[ ... \] (디스플레이) 수식
FORMULA = re.compile(r"\$[^$\n]+\$|\\\[[^\]]+?\\\]")
HANGUL = re.compile(r"[가-힣]")


def count_table_blocks(md: str) -> int:
    """연속된 | 행 덩어리를 표 블록 하나로 센다. 2행 이상이어야 표로 인정."""
    blocks = 0
    run_len = 0
    for line in md.splitlines():
        if TABLE_ROW.match(line):
            run_len += 1
        else:
            if run_len >= 2:  # 헤더 + 구분선 최소 2행
                blocks += 1
            run_len = 0
    if run_len >= 2:
        blocks += 1
    return blocks


def read_markdown(parser_dir: Path) -> str | None:
    """파서 출력 디렉토리에서 .md 를 모두 모아 한 문자열로. 없으면 None."""
    if not parser_dir.exists():
        return None
    md_files = sorted(parser_dir.rglob("*.md"))
    if not md_files:
        return None
    return "\n\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in md_files)


def metrics(md: str, ref_hangul: int) -> dict:
    hangul = len(HANGUL.findall(md))
    ratio = round(hangul / ref_hangul, 2) if ref_hangul > 0 else None
    return {
        "table_blocks": count_table_blocks(md),
        "formula_tokens": len(FORMULA.findall(md)),
        "hangul_chars": hangul,
        "hangul_ratio": ratio,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="세 파서 산출 Markdown 비교")
    ap.add_argument("--root", default="out", help="out 루트(아래에 docling/mineru/raganything)")
    ap.add_argument(
        "--ref-hangul",
        type=int,
        default=0,
        help="입력 PDF 의 한글 음절 수(보존율 근사 기준). 0 이면 비율 생략",
    )
    args = ap.parse_args()
    root = Path(args.root)

    rows = []
    for parser in PARSERS:
        md = read_markdown(root / parser)
        if md is None:
            rows.append({"parser": parser, "status": "missing"})
            continue
        row = {"parser": parser, "status": "ok"}
        row.update(metrics(md, args.ref_hangul))
        rows.append(row)

    df = pd.DataFrame(rows).set_index("parser")
    print(df.to_string())

    ok = [r for r in rows if r.get("status") == "ok"]
    if not ok:
        print("\n[안내] 비교할 산출물이 없다. 먼저 parse_*.py 를 돌려 out/ 를 채워라.")


if __name__ == "__main__":
    main()
