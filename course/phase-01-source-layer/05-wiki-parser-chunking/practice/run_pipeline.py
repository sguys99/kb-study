"""run_pipeline.py — 엔드투엔드: Wiki/원본 -> 파싱 -> 청킹 -> 메타 부착 -> chunks.jsonl + index.json.

흐름:
  1) 입력 선택. 02 의 wiki/ 가 있으면 그걸(프런트매터 포함), 없으면 02 의 sources/ 를
     직접 읽는다(04 validate_contract 가 sources 를 직접 읽은 패턴 그대로). 둘 다 상대경로 재사용.
  2) 각 문서: wiki_parser 로 파싱 → version 은 04 provenance(content_hash/make_version)로 산출
     → chunker 로 section-aware 청킹 → 청크에 문서 단위 tags·acl 을 메타로 부착.
  3) 출력: out/chunks.jsonl(청크 1건=1줄 JSON, ensure_ascii=False) + out/index.json(metadata index).
  4) 통계 + 첫 청크 예시 출력. 전 청크에 대해 body[start:end]==text 자체검증(04 톤과 일관).

04 provenance.py 재사용:
  토픽 독립을 위해 복제하지 않고 import 한다. 04 practice/ 를 sys.path 에 더해 import 한다
  (경로가 깔끔하므로 import 권장). 04 가 없으면 친절히 안내하고 멈춘다.

전제: 네트워크·API 키·LLM·Neo4j 불필요. 순수 로컬.
의존: pydantic>=2, pyyaml. 04 practice/provenance.py(상대경로).

실행:
    python run_pipeline.py                 # 자동: wiki/ 있으면 wiki, 없으면 sources
    python run_pipeline.py --src sources   # 강제로 02 sources 사용
    python run_pipeline.py --max-tokens 180
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from chunker import Chunk, chunk_document
from metadata_index import MetadataIndex
from wiki_parser import parse_wiki

HERE = Path(__file__).resolve().parent

# 02 산출물 경로(상대경로 재사용 — 복제하지 않는다).
WIKI_DIR = (HERE / ".." / ".." / "02-markdown-yaml-wikilink" / "practice" / "wiki").resolve()
SOURCES_DIR = (HERE / ".." / ".." / "02-markdown-yaml-wikilink" / "practice" / "sources").resolve()

# 04 provenance.py 를 import 하려고 04 practice/ 를 sys.path 에 더한다.
PROV_DIR = (HERE / ".." / ".." / "04-document-data-contract" / "practice").resolve()
if str(PROV_DIR) not in sys.path:
    sys.path.insert(0, str(PROV_DIR))

try:
    import provenance as prov  # 04 의 순수 함수 모듈(모델 비의존)
except ModuleNotFoundError:
    sys.exit(
        "[ERROR] 04 의 provenance.py 를 찾지 못했다.\n"
        f"        기대 경로: {PROV_DIR}/provenance.py\n"
        "        04-document-data-contract/practice 가 있는지 확인하라."
    )

OUT_DIR = HERE / "out"

# 문서 단위 tags·acl(시연용). 02 LINK_PLAN·04 DOC_META 와 같은 의도로 둔다.
# wiki/ 입력이면 프런트매터의 tags 를 우선 쓰고, 여기 값은 sources/ 입력일 때의 보강용이다.
DOC_META: dict[str, dict] = {
    "01-rag": {"tags": ["rag", "foundation"], "acl_visibility": "internal"},
    "02-self-rag": {"tags": ["rag", "self-reflection"], "acl_visibility": "internal"},
    "03-crag": {"tags": ["rag", "self-reflection"], "acl_visibility": "public"},
    "04-graphrag-ms": {"tags": ["graphrag", "community-summary"], "acl_visibility": "internal"},
    "05-lightrag": {"tags": ["graphrag", "framework"], "acl_visibility": "internal"},
    "06-neo4j": {"tags": ["graph-db", "storage"], "acl_visibility": "restricted"},
    "07-embedding": {"tags": ["embedding", "foundation"], "acl_visibility": "internal"},
    "08-multihop": {"tags": ["graphrag", "foundation"], "acl_visibility": "internal"},
}


def choose_input(force_src: str | None) -> tuple[Path, str]:
    """입력 폴더와 모드('wiki'/'sources')를 고른다."""
    if force_src == "sources":
        if not SOURCES_DIR.is_dir():
            sys.exit(f"[ERROR] sources 폴더가 없다: {SOURCES_DIR}")
        return SOURCES_DIR, "sources"
    if force_src == "wiki":
        if not WIKI_DIR.is_dir():
            sys.exit(f"[ERROR] wiki 폴더가 없다(02 to_wiki.py 먼저 실행): {WIKI_DIR}")
        return WIKI_DIR, "wiki"
    # 자동: wiki 있으면 wiki, 없으면 sources.
    if WIKI_DIR.is_dir() and any(WIKI_DIR.glob("*.md")):
        return WIKI_DIR, "wiki"
    if SOURCES_DIR.is_dir():
        return SOURCES_DIR, "sources"
    sys.exit(
        "[ERROR] 입력을 찾지 못했다. 02-markdown-yaml-wikilink/practice 의\n"
        f"        wiki/ 또는 sources/ 가 있어야 한다.\n"
        f"        wiki   : {WIKI_DIR}\n"
        f"        sources: {SOURCES_DIR}"
    )


def make_source_id_from_stem(stem: str) -> str:
    """04 provenance.make_source_id_from_stem 와 동일 규약. 01-rag -> src-01-rag."""
    return prov.make_source_id_from_stem(stem)


def doc_tags_acl(stem: str, frontmatter: dict) -> tuple[list[str], str]:
    """문서 단위 tags·acl_visibility 결정. wiki 프런트매터 tags 를 우선, 없으면 DOC_META."""
    meta = DOC_META.get(stem, {})
    fm_tags = frontmatter.get("tags") if isinstance(frontmatter.get("tags"), list) else None
    tags = fm_tags if fm_tags else meta.get("tags", [])
    acl_visibility = meta.get("acl_visibility", "internal")
    return list(tags), acl_visibility


def process_one(path: Path, max_tokens: int, overlap_sentences: int) -> tuple[str, list[Chunk], list[str], str]:
    """문서 1건 -> (body, chunks, tags, acl_visibility). version 을 04 함수로 산출한다."""
    text = path.read_text(encoding="utf-8")
    parsed = parse_wiki(text)

    source_id = make_source_id_from_stem(path.stem)
    # version: 04 의 content_hash(정규화 후 sha256 short) + make_version. body 기준으로 해시한다.
    ch = prov.content_hash(parsed.body, short=True)
    version = prov.make_version(1, ch)  # revision 은 이 토픽에선 1 고정(내용 변화는 hash 가 책임)

    tags, acl_visibility = doc_tags_acl(path.stem, parsed.frontmatter)
    chunks = chunk_document(
        body=parsed.body,
        sections=parsed.sections,
        source_id=source_id,
        version=version,
        max_tokens=max_tokens,
        overlap_sentences=overlap_sentences,
    )
    return parsed.body, chunks, tags, acl_visibility


def main() -> None:
    ap = argparse.ArgumentParser(description="Wiki/원본 -> chunks.jsonl + metadata index")
    ap.add_argument("--src", choices=["wiki", "sources"], default=None, help="입력 강제(기본: 자동)")
    ap.add_argument("--max-tokens", type=int, default=220, help="섹션 분할 토큰 예산(기본 220)")
    ap.add_argument("--overlap", type=int, default=1, help="sub-chunk overlap 문장 수(기본 1)")
    args = ap.parse_args()

    in_dir, mode = choose_input(args.src)
    md_files = sorted(p for p in in_dir.glob("*.md") if p.name.lower() != "readme.md")
    if not md_files:
        sys.exit(f"[ERROR] {in_dir} 아래 .md 가 없다.")

    print(f"[1] 입력: {mode} 모드 — {in_dir}  ({len(md_files)}건)\n")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    chunks_path = OUT_DIR / "chunks.jsonl"
    index_path = OUT_DIR / "index.json"

    index = MetadataIndex()
    all_records: list[dict] = []
    bodies: dict[str, str] = {}  # source_id -> body (span 자체검증용)
    n_sections_total = 0

    print(f"    {'source_id':18s} {'version':14s} {'sec':>3s} {'chunks':>6s} {'avg_tok':>7s}")
    print(f"    {'-' * 18} {'-' * 14} {'-' * 3} {'-' * 6} {'-' * 7}")

    for path in md_files:
        body, chunks, tags, acl_visibility = process_one(path, args.max_tokens, args.overlap)
        parsed_sections = len(parse_wiki(path.read_text(encoding="utf-8")).sections)
        n_sections_total += parsed_sections
        source_id = chunks[0].source_id if chunks else make_source_id_from_stem(path.stem)
        bodies[source_id] = body

        for c in chunks:
            index.add(c, tags=tags, acl_visibility=acl_visibility)
            all_records.append(c.model_dump())

        avg_tok = round(sum(c.token_estimate for c in chunks) / len(chunks), 1) if chunks else 0.0
        version = chunks[0].version if chunks else "-"
        print(f"    {source_id:18s} {version:14s} {parsed_sections:>3d} {len(chunks):>6d} {avg_tok:>7.1f}")

    # chunks.jsonl 쓰기 — 1청크=1줄. ensure_ascii=False 로 한글 보존.
    with chunks_path.open("w", encoding="utf-8") as f:
        for rec in all_records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # metadata index 쓰기.
    index.to_json(index_path)

    total_chunks = len(all_records)
    avg_tokens = round(sum(r["token_estimate"] for r in all_records) / total_chunks, 1) if total_chunks else 0.0
    print(f"\n[2] 통계 — 문서 {len(md_files)}건 · 섹션 {n_sections_total}개 · 청크 {total_chunks}건 · 평균 토큰 {avg_tokens}")
    print(f"    출력: {chunks_path.relative_to(HERE)}  +  {index_path.relative_to(HERE)}")

    # 첫 청크 예시.
    if all_records:
        print("\n[3] 첫 청크 예시:")
        print("    " + json.dumps(all_records[0], ensure_ascii=False)[:300] + " ...")

    # span 자체검증 — 전 청크에 대해 body[start:end]==text 확인.
    print("\n[4] span 정합성 — 전 청크 body[char_start:char_end] == text 확인")
    all_ok = True
    bad = 0
    for c in (Chunk.model_validate(r) for r in all_records):
        ok = c.verify(bodies[c.source_id])
        if not ok:
            bad += 1
        all_ok = all_ok and ok
    print(f"    검사 {total_chunks}건 · 실패 {bad}건 → span 정합성: {'ALL PASS' if all_ok else 'FAIL 있음'}")

    print("\n[완료] chunks.jsonl + index.json 생성 + span 정합성 확인 끝.")


if __name__ == "__main__":
    main()
