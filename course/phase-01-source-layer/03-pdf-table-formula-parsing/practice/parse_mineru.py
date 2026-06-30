"""MinerU CLI 를 subprocess 로 감싸는 얇은 러너.

전제:
- MinerU 는 별도 설치한다(무거움):  uv pip install -U "mineru[all]"
  (또는 pip install -U "mineru[all]")
- 패키지명이 옛 magic-pdf 에서 mineru 로 바뀌었다. 옛 명령을 쓰지 말 것.
- 파이썬 API 는 버전마다 흔들리므로 여기서는 CLI 를 권장 경로로 잡는다.
- 첫 실행 때 VLM 모델을 내려받는다. GPU 가 있으면 빠르다(CPU 도 동작은 한다).

사용:
    python parse_mineru.py <input.pdf> [--out out/mineru]

산출:
    out/mineru/ 아래에 MinerU 가 Markdown/JSON 을 떨군다(버전별 하위 폴더 구조).
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path


def ensure_cli() -> bool:
    """mineru CLI 설치 여부 확인. 없으면 친절한 안내 후 False."""
    if shutil.which("mineru") is not None:
        return True
    print("[건너뜀] mineru CLI 가 PATH 에 없다.")
    print('  설치: uv pip install -U "mineru[all]"  (또는 pip install -U "mineru[all]")')
    print("  설치 후 다시 실행하라. 옛 magic-pdf 명령은 더 이상 권장 경로가 아니다.")
    return False


def run(pdf_path: Path, out_dir: Path) -> None:
    if not pdf_path.exists():
        print(f"[오류] 입력 PDF 가 없다: {pdf_path}")
        raise SystemExit(1)

    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = ["mineru", "-p", str(pdf_path), "-o", str(out_dir)]
    print(f"[mineru] 실행: {' '.join(cmd)}")
    # 스캔 PDF 라면 MinerU 가 OCR 경로로 처리한다(한국어 OCR 강점).
    subprocess.run(cmd, check=True)
    print(f"  -> 산출물: {out_dir}/ (Markdown/JSON)")


def main() -> None:
    ap = argparse.ArgumentParser(description="MinerU CLI 러너")
    ap.add_argument("source", help="로컬 PDF 경로")
    ap.add_argument("--out", default="out/mineru", help="출력 디렉토리")
    args = ap.parse_args()

    if not ensure_cli():
        raise SystemExit(0)  # 설치 안내만 하고 정상 종료(파이프라인을 막지 않는다)
    run(Path(args.source), Path(args.out))


if __name__ == "__main__":
    main()
