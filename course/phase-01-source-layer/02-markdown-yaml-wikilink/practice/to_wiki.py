"""to_wiki.py — 원본 sources/*.md 를 LLM Wiki 문서 wiki/*.md 로 구조화한다.

하는 일:
  1) sources/ 의 원본 본문을 읽는다(01 산출물과 같은 8건. 02 는 독립 실행을 위해 자체 동봉).
  2) 본문은 보존한 채, 정해진 어구를 WikiLink([[대상 source_id|표시이름]]) 로 치환한다.
  3) 위에 YAML 프런트매터(title, source_id, tags, aliases, links)를 얹는다.
     - links 는 본문의 WikiLink 에서 자동 도출한다(본문과 메타가 어긋나지 않게).
  4) wiki/<같은 파일명>.md 로 쓴다.

원칙: 원본 본문 텍스트는 바꾸지 않는다. WikiLink 치환과 프런트매터 추가만 한다.
      (원본 무결성은 01 의 해시 게이트가 지킨다. 02 는 원본을 건드리지 않고 wiki/ 만 새로 만든다.)

이 토픽은 Markdown/YAML/WikiLink/tag 구조화까지만 한다.
version·source span·ACL·provenance 전체 Data Contract 는 04 토픽에서 다룬다.

전제: 네트워크·API 키·Neo4j·LLM 호출 불필요. 로컬 파일만 읽고 쓴다.
의존: pyyaml, wiki_schema.py(WikiFrontmatter), wikilink.py(unique_targets).

실행:
    python to_wiki.py                 # sources/ -> wiki/
    python to_wiki.py --src sources --out wiki
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from wiki_schema import WikiFrontmatter
from wikilink import unique_targets


def make_source_id(path: Path, root: Path) -> str:
    """01 과 동일한 stable ID 규약. sources/01-rag.md -> src-01-rag."""
    rel = path.relative_to(root).with_suffix("")
    slug = "-".join(rel.parts)
    return f"src-{slug}"


def extract_title(text: str, fallback: str) -> str:
    """본문 첫 H1(`# ...`)을 제목으로. 없으면 fallback(파일명 stem)."""
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("# "):
            return s[2:].strip()
    return fallback


# 구조화 계획표 — 파일 stem 별로 tags / aliases / 본문 치환 규칙을 선언한다.
#   tags    : 이 문서에 붙일 주제 태그(소문자·하이픈).
#   aliases : 이 문서를 가리키는 다른 이름.
#   links   : (찾을 어구, 대상 source_id, 표시 이름) — 본문에서 어구를 [[대상|표시]] 로 바꾼다.
#             '찾을 어구'는 원본 본문에 실제로 있는 표현만 쓴다(없으면 치환 0회 → 그대로).
LINK_PLAN: dict[str, dict] = {
    "01-rag": {
        "tags": ["rag", "foundation"],
        "aliases": ["RAG", "검색 증강 생성"],
        "links": [
            ("멀티홉 질문", "src-08-multihop", "멀티홉 질문과 그래프"),
            ("GraphRAG 계열 연구", "src-04-graphrag-ms", "Microsoft GraphRAG"),
        ],
    },
    "02-self-rag": {
        "tags": ["rag", "self-reflection"],
        "aliases": ["Self-RAG"],
        "links": [
            ("CRAG", "src-03-crag", "Corrective RAG(CRAG)"),
        ],
    },
    "03-crag": {
        "tags": ["rag", "self-reflection"],
        "aliases": ["CRAG", "Corrective RAG"],
        "links": [
            ("Self-RAG", "src-02-self-rag", "Self-RAG"),
        ],
    },
    "04-graphrag-ms": {
        "tags": ["graphrag", "community-summary"],
        "aliases": ["Microsoft GraphRAG", "From Local to Global"],
        "links": [
            ("LightRAG", "src-05-lightrag", "LightRAG"),
        ],
    },
    "05-lightrag": {
        "tags": ["graphrag", "framework"],
        "aliases": ["LightRAG"],
        # 본문이 실제로 언급하는 것은 Microsoft GraphRAG 뿐이다. Neo4j 와의 연결은 06 본문이 가진다.
        "links": [
            ("Microsoft GraphRAG", "src-04-graphrag-ms", "Microsoft GraphRAG"),
        ],
    },
    "06-neo4j": {
        "tags": ["graph-db", "storage"],
        "aliases": ["Neo4j"],
        "links": [
            ("LightRAG", "src-05-lightrag", "LightRAG"),
        ],
    },
    "07-embedding": {
        "tags": ["embedding", "foundation"],
        "aliases": ["임베딩", "VoyageAI"],
        "links": [
            ("그래프가 필요한 이유", "src-08-multihop", "멀티홉 질문과 그래프"),
        ],
    },
    "08-multihop": {
        "tags": ["graphrag", "foundation"],
        "aliases": ["멀티홉", "multi-hop"],
        "links": [
            ("Self-RAG 문서", "src-02-self-rag", "Self-RAG"),
            ("CRAG 문서", "src-03-crag", "Corrective RAG(CRAG)"),
        ],
    },
}


def inject_wikilinks(body: str, link_rules: list[tuple[str, str, str]]) -> str:
    """본문에서 정해진 어구를 [[대상|표시]] 로 치환한다(어구당 첫 1회만).

    이미 WikiLink 안에 들어간 텍스트는 다시 건드리지 않도록, 각 어구를 한 번만 바꾼다.
    원본에 어구가 없으면 아무 일도 일어나지 않는다(본문 보존).
    """
    out = body
    for phrase, target, display in link_rules:
        replacement = f"[[{target}|{display}]]"
        if phrase in out and replacement not in out:
            out = out.replace(phrase, replacement, 1)
    return out


def to_frontmatter_md(fm: WikiFrontmatter, body: str) -> str:
    """프런트매터(YAML) + 본문을 합쳐 Wiki Markdown 문자열을 만든다."""
    # allow_unicode=True 라야 한글 title·alias 가 \uXXXX 로 깨지지 않는다.
    # sort_keys=False 로 선언 순서를 유지한다.
    yaml_block = yaml.safe_dump(
        fm.model_dump(),
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    ).strip()
    return f"---\n{yaml_block}\n---\n\n{body.lstrip()}"


def convert_one(path: Path, src_root: Path) -> tuple[str, str]:
    """원본 1건 -> (파일명, Wiki Markdown 문자열)."""
    raw = path.read_text(encoding="utf-8")
    source_id = make_source_id(path, src_root)
    plan = LINK_PLAN.get(path.stem, {})

    body = inject_wikilinks(raw, plan.get("links", []))
    fm = WikiFrontmatter(
        title=extract_title(raw, path.stem),
        source_id=source_id,
        tags=plan.get("tags", []),
        aliases=plan.get("aliases", []),
        links=unique_targets(body),  # 본문 WikiLink 에서 자동 도출 → 본문/메타 일치 보장
    )
    return path.name, to_frontmatter_md(fm, body)


def convert_all(src_root: Path, out_root: Path) -> int:
    if not src_root.is_dir():
        sys.exit(f"[ERROR] 원본 폴더가 없다: {src_root}")
    out_root.mkdir(parents=True, exist_ok=True)

    md_files = sorted(p for p in src_root.glob("*.md") if p.name.lower() != "readme.md")
    if not md_files:
        sys.exit(f"[ERROR] {src_root} 아래 .md 원본이 없다.")

    for path in md_files:
        name, content = convert_one(path, src_root)
        (out_root / name).write_text(content, encoding="utf-8")

    print(f"[OK] structured {len(md_files)} sources -> {out_root}/")
    for path in md_files:
        sid = make_source_id(path, src_root)
        plan = LINK_PLAN.get(path.stem, {})
        n_links = len(unique_targets(inject_wikilinks(path.read_text(encoding="utf-8"), plan.get("links", []))))
        tags = ",".join(plan.get("tags", []))
        print(f"     {sid:20s} links={n_links}  tags=[{tags}]")
    return len(md_files)


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="원본 -> LLM Wiki 구조화기")
    ap.add_argument("--src", default="sources", help="원본 폴더 (기본: sources)")
    ap.add_argument("--out", default="wiki", help="Wiki 출력 폴더 (기본: wiki)")
    return ap.parse_args()


def main() -> None:
    args = parse_args()
    here = Path(__file__).resolve().parent
    src_root = (here / args.src).resolve()
    out_root = (here / args.out).resolve()
    convert_all(src_root, out_root)


if __name__ == "__main__":
    main()
