"""validate_contract.py — 02 의 Wiki 원본 8건을 Data Contract 로 검증·직렬화한다.

흐름:
  1) 02 의 sources/*.md 8건을 그대로 입력으로 읽는다(복제하지 않는다. 상대경로 재사용).
  2) 각 문서로 DocumentContract 를 빌드하고 한 줄 요약을 출력한다.
  3) source span 정합성 자체검사 — 각 문서에서 한 구간을 SourceSpan 으로 떠서
     text[start:end] == quote 가 정확히 일치하는지 확인한다(인용 품질의 토대).
  4) 일부러 깨진 span(end 가 본문 길이를 초과)을 만들어 거부되는 것을 시연한다.

완료 기준 충족: 8건 검증·직렬화 + 임의 인용 span 의 offset 일치 출력.

전제: 네트워크·API 키 불필요. 02 practice/sources/ 가 있어야 한다(없으면 친절히 안내).
의존: pydantic>=2, data_contract.py, provenance.py(같은 폴더).
"""

from __future__ import annotations

import sys
from pathlib import Path

from pydantic import ValidationError

from data_contract import ACL, DocumentContract, SourceSpan
from provenance import make_source_id_from_stem

HERE = Path(__file__).resolve().parent

# 02 의 sources 를 재사용한다. 파일을 복제하지 말고 상대경로로 읽는다.
SOURCES_DIR = (HERE / ".." / ".." / "02-markdown-yaml-wikilink" / "practice" / "sources").resolve()

# 문서별 ACL·파서 메타(시연용). 실제로는 적재 파이프라인이 채운다.
# 대부분 internal, 한 건만 restricted 로 두어 visibility 차이를 눈으로 보게 한다.
DOC_META: dict[str, dict] = {
    "06-neo4j": {"acl": ACL(visibility="restricted", allow=["infra"]), "parser": "docling"},
    "03-crag": {"acl": ACL(visibility="public"), "parser": "none"},
}


def load_sources() -> list[Path]:
    if not SOURCES_DIR.is_dir():
        sys.exit(
            "[ERROR] 02 의 sources 폴더를 찾지 못했다.\n"
            f"        기대 경로: {SOURCES_DIR}\n"
            "        02-markdown-yaml-wikilink/practice/sources 가 있는지 확인하라."
        )
    md = sorted(p for p in SOURCES_DIR.glob("*.md") if p.name.lower() != "readme.md")
    if not md:
        sys.exit(f"[ERROR] {SOURCES_DIR} 아래 .md 원본이 없다.")
    return md


def extract_title(text: str, fallback: str) -> str:
    """본문 첫 H1 을 제목으로. 02 의 규칙과 동일."""
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("# "):
            return s[2:].strip()
    return fallback


def build_contract(path: Path) -> tuple[str, DocumentContract]:
    """원본 1건 -> (본문 text, DocumentContract)."""
    text = path.read_text(encoding="utf-8")
    source_id = make_source_id_from_stem(path.stem)  # 01/02 규약: 01-rag -> src-01-rag
    meta = DOC_META.get(path.stem, {})
    contract = DocumentContract.from_document(
        text,
        source_id=source_id,
        title=extract_title(text, path.stem),
        origin=f"local://{path.relative_to(SOURCES_DIR.parent.parent.parent.parent)}",
        retrieved_at="2026-06-30",
        parser=meta.get("parser", "none"),
        acl=meta.get("acl"),
    )
    return text, contract


def first_sentence_span(text: str, source_id: str) -> SourceSpan:
    """본문에서 '첫 문장'을 한 구간으로 떠서 SourceSpan 을 만든다.

    여기서는 첫 H1 다음의 첫 비어 있지 않은 본문 줄을 인용 대상으로 삼는다.
    중요한 것은 offset 산출 방식이다 — text.index(line) 로 실제 시작 위치를 찾고,
    quote 를 그 자리의 사본으로 둔다. 그래야 text[start:end] == quote 가 성립한다.
    """
    target = ""
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("# "):
            continue
        target = s
        break
    start = text.index(target)
    end = start + len(target)
    return SourceSpan(source_id=source_id, start=start, end=end, quote=text[start:end])


def main() -> None:
    paths = load_sources()
    print(f"[1] Data Contract 빌드·검증 — {SOURCES_DIR}\n")
    print(f"    {'source_id':18s} {'rev':>3s} {'content_hash':22s} {'visibility':11s} steps")
    print(f"    {'-' * 18} {'-' * 3} {'-' * 22} {'-' * 11} -----")

    contracts: list[tuple[str, DocumentContract]] = []
    for path in paths:
        text, c = build_contract(path)
        contracts.append((text, c))
        print(
            f"    {c.source_id:18s} {c.revision:>3d} {c.content_hash:22s} "
            f"{c.acl.visibility:11s} {len(c.provenance.steps)}"
        )

    # 직렬화가 되는지(다운스트림에 넘길 수 있는지) 한 건 확인한다.
    sample_json = contracts[0][1].model_dump_json(indent=2)
    print(f"\n    직렬화 OK — {contracts[0][1].source_id} 계약을 JSON {len(sample_json)} bytes 로 덤프")

    # ── span 정합성 자체검사 ─────────────────────────────────────────────
    print("\n[2] source span 정합성 — text[start:end] == quote 인지 8건 모두 확인\n")
    all_ok = True
    for text, c in contracts:
        span = first_sentence_span(text, c.source_id)
        ok = span.verify_against(text)
        all_ok = all_ok and ok
        mark = "PASS" if ok else "FAIL"
        preview = span.quote[:30] + ("…" if span.quote and len(span.quote) > 30 else "")
        print(f"    [{mark}] {c.source_id:18s} ({span.start:>3d},{span.end:>3d})  {preview!r}")

    print(f"\n    span 정합성: {'ALL PASS' if all_ok else 'FAIL 있음'}")

    # ── 깨진 span 거부 시연 ──────────────────────────────────────────────
    print("\n[3] 일부러 깨진 span(end 초과) — 거부되어야 정상\n")
    text0, c0 = contracts[0]
    bad_end = len(text0) + 100
    try:
        bad = SourceSpan(source_id=c0.source_id, start=0, end=bad_end, quote=text0[:10])
        if bad.verify_against(text0):
            print("    [BUG] 깨진 span 이 통과했다 — 검증 로직 점검 필요")
        else:
            print(f"    [OK] end={bad_end} > len(text)={len(text0)} → verify_against 가 거부함")
    except ValidationError as e:
        print(f"    [OK] start<end 위반은 ValidationError 로 거부됨: {e.error_count()} error")

    # start >= end 위반도 한 건 시연(스키마 레벨 거부).
    try:
        SourceSpan(source_id=c0.source_id, start=50, end=10)
        print("    [BUG] start>=end span 이 통과했다")
    except ValidationError:
        print("    [OK] start>=end 위반은 model_validator 가 ValidationError 로 거부함")

    print("\n[완료] 8건 계약 검증·직렬화 + span offset 일치 확인 끝.")


if __name__ == "__main__":
    main()
