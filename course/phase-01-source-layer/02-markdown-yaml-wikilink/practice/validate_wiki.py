"""validate_wiki.py — LLM Wiki 의 품질 게이트.

wiki/*.md 를 모두 읽어 세 가지를 점검한다.
  (a) 프런트매터 스키마 통과 — 모든 문서의 YAML 이 WikiFrontmatter 로 검증되는가.
  (b) dangling link 0 건 — 본문의 모든 [[대상]] 이 실제로 존재하는 문서(또는 그 alias)를 가리키는가.
  (c) tag 표기 일관성 — 같은 주제를 가리키는데 표기가 갈라진 태그가 없는가(대소문자·유사 변형).

문제 0 건이면 종료 코드 0, 1 건 이상이면 1 (CI 게이트로 쓸 수 있게 — 01 validate_sources.py 와 같은 패턴).

검증을 통과해야 다음 토픽(03~)이 이 Wiki 를 신뢰하고 쓸 수 있고,
Phase 2 가 [[...]] 를 '문서 간 관계'의 씨앗으로 안전하게 가져갈 수 있다.

전제: 네트워크·API 키 불필요. 로컬 파일만 읽는다.
의존: pydantic v2, pyyaml, wiki_schema.py, wikilink.py.

실행:
    python validate_wiki.py
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

import yaml
from pydantic import ValidationError

from wiki_schema import WikiFrontmatter
from wikilink import parse_wikilinks, resolve


def split_frontmatter(text: str) -> tuple[dict | None, str]:
    """`---` 로 감싼 YAML 프런트매터와 본문을 분리한다.

    프런트매터가 없으면 (None, 본문). 형식이 깨졌으면 ValueError.
    """
    if not text.startswith("---"):
        return None, text
    parts = text.split("---", 2)
    # text == "---\n<yaml>\n---\n<body>" -> ["", "\n<yaml>\n", "\n<body>"]
    if len(parts) < 3:
        raise ValueError("프런트매터 닫는 '---' 가 없다")
    fm = yaml.safe_load(parts[1])
    body = parts[2].lstrip("\n")
    if not isinstance(fm, dict):
        raise ValueError("프런트매터가 매핑(dict)이 아니다")
    return fm, body


def normalize_tag(tag: str) -> str:
    """tag 일관성 비교용 정규화 키. 대소문자·하이픈/언더스코어/공백 차이를 한데 모은다."""
    return tag.lower().replace("_", "-").replace(" ", "-")


def validate(wiki_root: Path) -> int:
    """문제 건수를 반환한다(0 = 통과)."""
    if not wiki_root.is_dir():
        sys.exit(f"[ERROR] wiki 폴더가 없다: {wiki_root}. 먼저 to_wiki.py 를 실행하라.")

    md_files = sorted(p for p in wiki_root.glob("*.md") if p.name.lower() != "readme.md")
    if not md_files:
        sys.exit(f"[ERROR] {wiki_root} 아래 wiki 문서가 없다.")

    problems: list[str] = []
    docs: dict[str, WikiFrontmatter] = {}  # source_id -> frontmatter
    bodies: dict[str, str] = {}  # source_id -> 본문
    alias_index: dict[str, str] = {}  # alias(소문자) -> source_id
    tag_variants: dict[str, set[str]] = defaultdict(set)  # 정규화키 -> 실제 표기 집합

    # 1) (a) 프런트매터 스키마 통과
    for path in md_files:
        text = path.read_text(encoding="utf-8")
        try:
            fm_dict, body = split_frontmatter(text)
        except ValueError as e:
            problems.append(f"[frontmatter] {path.name}: {e}")
            continue
        if fm_dict is None:
            problems.append(f"[frontmatter] {path.name}: 프런트매터가 없다")
            continue
        try:
            fm = WikiFrontmatter.model_validate(fm_dict)
        except ValidationError as e:
            problems.append(f"[schema] {path.name}: {e.errors()[0]['msg']}")
            continue

        docs[fm.source_id] = fm
        bodies[fm.source_id] = body
        for a in fm.aliases:
            alias_index[a.lower()] = fm.source_id
        for t in fm.tags:
            tag_variants[normalize_tag(t)].add(t)

    known_ids = set(docs.keys())

    # 2) (b) dangling link — 본문 [[대상]] 이 존재하는 문서/alias 를 가리키는가
    for sid, body in bodies.items():
        for link in parse_wikilinks(body):
            resolved = resolve(link.target, known_ids, alias_index)
            if resolved is None:
                problems.append(
                    f"[dangling] {sid}: [[{link.target}]] 가 가리키는 문서가 없다"
                )

    # 3) (c) tag 표기 일관성 — 같은 정규화키에 표기가 2가지 이상이면 난립
    for key, variants in sorted(tag_variants.items()):
        if len(variants) > 1:
            problems.append(
                f"[tag] 표기 불일치: {sorted(variants)} 가 같은 주제를 가리킨다(하나로 통일)"
            )

    # 요약 출력
    n_links = sum(len(parse_wikilinks(b)) for b in bodies.values())
    n_dangling = sum(1 for p in problems if p.startswith("[dangling]"))
    n_tag = sum(1 for p in problems if p.startswith("[tag]"))
    n_schema = len(problems) - n_dangling - n_tag
    print(
        f"checked {len(docs)} wiki docs | {n_links} wikilinks | "
        f"{n_schema} schema | {n_dangling} dangling | {n_tag} tag-inconsistency"
    )
    if problems:
        print("-" * 60)
        for p in problems:
            print("  " + p)
        print(f"FAIL — {len(problems)} problem(s).")
    else:
        print(f"OK: {len(docs)} wiki docs, 0 dangling link, tags consistent")
    return len(problems)


def main() -> None:
    here = Path(__file__).resolve().parent
    wiki_root = here / "wiki"
    n_problems = validate(wiki_root)
    sys.exit(1 if n_problems else 0)


if __name__ == "__main__":
    main()
