# 1.2 원문 → Markdown·YAML·WikiLink 구조화 — 원본을 LLM Wiki로

> **Phase 1 · 토픽 02** · 01에서 세운 신뢰 가능한 원본 8건에 YAML 프런트매터를 얹고, 문서끼리 WikiLink로 잇고, tag로 분류해 LLM·Agent가 읽기 좋은 LLM Wiki로 구조화한다.

## 학습 목표

이 토픽을 끝내면 다음을 할 수 있다.

- Pydantic v2로 Wiki 프런트매터 스키마(`title`·`source_id`·`tags`·`aliases`·`links`)를 정의하고, tag·source_id 표기 규칙을 모델 선언에 박는다.
- `[[target]]` / `[[target|alias]]` WikiLink를 파싱·해소하는 유틸을 만들고, 원본 본문을 보존한 채 프런트매터와 WikiLink를 주입해 `wiki/*.md`를 생성한다.
- 프런트매터 스키마·dangling link 0건·tag 표기 일관성을 검사하는 품질 게이트를 만들어, 없는 문서로 가는 링크나 표기를 어긴 tag를 직접 깨뜨려 잡아낸다.

**완료 기준**: `python to_wiki.py`가 8건을 구조화하고, `python validate_wiki.py`가 `OK: 8 wiki docs, 0 dangling link, tags consistent`(exit 0)를 출력하며, 없는 문서로 가는 `[[...]]`나 표기 규칙을 어긴 tag를 넣으면 게이트가 exit 1로 잡으면 완료.

---

## 1. 왜 필요한가 — 원본은 깔았는데 읽기는 나쁘다

01에서 원본을 신뢰 가능하게 만들었다. 각 파일에 안 변하는 주소(stable ID)가 생겼고, 내용이 바뀌면 해시가 잡는다. 거기서 한 가지를 일부러 미뤘다. 메타와 본문을 섞지 않으려고, 메타는 인덱스에 따로 모으고 본문은 손대지 않았다.

그 본문을 이제 LLM과 Agent가 읽는다. 그런데 지금 형태로는 읽기가 나쁘다. 문서가 어떤 주제인지, 무엇과 관련 있는지, 다른 이름으로는 뭐라 불리는지 — 본문을 다 읽기 전엔 알 수가 없다. 검색기가 `02-self-rag.md`를 가져와도, 이 문서가 `03-crag.md`와 한 줄기라는 사실은 본문 어딘가에 묻혀 있다.

사람이 위키를 쓰는 방식을 떠올려 보자. 문서 맨 위에 제목·태그·별칭을 적고, 본문에서 다른 문서를 `[[...]]`로 가리킨다. 그러면 기계도 본문을 끝까지 읽지 않고 문서의 골격과 이웃을 파악한다. 02는 01의 원본을 바로 그 위키 문서로 바꾼다. 이게 LLM Wiki의 본체다.

이 구조화가 다음 단계의 씨앗이라는 점이 중요하다. 문서끼리 그은 `[[...]]` 선은 Phase 2에서 KG의 "문서 간 관계"가 된다. tag는 주제 묶음의 출발점이 된다. 지금 깔아 두는 골격이 그래프의 밑그림이다.

## 2. 세 가지 구조화 장치 — 직관부터

LLM Wiki 문서 하나에 얹는 건 세 가지다. 각각이 뭘 보장하는지부터 잡는다.

**YAML 프런트매터.** 문서 맨 위 `---`로 감싼 메타 블록이다. 본문을 읽기 전에 기계가 먼저 보는 카드다. `title`·`source_id`·`tags`·`aliases`·`links`를 담는다. 01에서 메타를 *분리*했다면, 여기서는 그 메타 일부를 *문서 자체에* 구조적으로 얹는다. 모순이 아니다. 01의 인덱스는 원본 관리용이고, 02의 프런트매터는 그 문서를 읽는 기계용이다. 둘을 잇는 고리가 `source_id`다. 01의 stable ID 규약(`src-01-rag` 형태)을 그대로 재사용한다.

**WikiLink.** 본문에서 `[[대상]]`만 적으면 그게 다른 문서로 가는 링크다. 별칭을 붙이려면 `[[대상|표시이름]]`. Obsidian과 위키의 관례다. 이 토픽에서는 `[[...]]`의 '대상'을 항상 다른 문서의 `source_id`로 통일한다. 사람이 읽는 이름은 `|` 뒤 alias로 둔다. 왜 이렇게 하나. 제목이 바뀌어도 링크가 안 깨지게 하려는 것이다. 제목을 대상으로 쓰면 제목 한 번 손보는 순간 그 제목을 가리키던 링크가 죄다 떠 버린다.

**tag.** 주제 분류다. 단순해 보이지만 여기에 함정이 있다. `rag`·`RAG`·`Rag`·`rag `가 섞이면 같은 주제가 네 갈래로 쪼개진다. 그래서 표기를 코드로 강하게 통제한다. 소문자·숫자·하이픈만 허용하고, 어기면 입구에서 막는다.

> 프런트매터에 `source_id`는 넣지만, `version`·source span·ACL·provenance 같은 풀 Data Contract 필드는 넣지 않는다. 그 전체 계약은 04 토픽 몫이다. 02는 Markdown·YAML·WikiLink·tag 구조화까지만 한다.

## 3. 실습 — 스키마·WikiLink·구조화기·게이트

### 프런트매터 스키마

먼저 프런트매터 한 건을 표현하는 모델을 정한다. 검증을 코드가 아니라 모델 선언에 박아 두면, 표기가 어긋난 문서가 Wiki에 끼어드는 걸 입구에서 막는다.

```python
# practice/wiki_schema.py 의 핵심 부분
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

class WikiFrontmatter(BaseModel):
    title: str
    source_id: str                       # 01 의 stable ID 재사용 (src-01-rag)
    tags: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    links: list[str] = Field(default_factory=list)   # 본문 [[...]] 대상 source_id 목록

    @field_validator("tags")
    @classmethod
    def _tags_format(cls, v: list[str]) -> list[str]:
        for t in v:
            if not SLUG_RE.match(t):     # 소문자·숫자·하이픈만. RAG / rag  / Rag 차단
                raise ValueError(f"tag 형식 오류: {t!r}")
        if len(v) != len(set(v)):
            raise ValueError(f"중복 tag: {v!r}")
        return v
```

`links`는 본문에서 가리키는 대상 `source_id` 목록이다. 이걸 손으로 적지 않는다. 본문의 WikiLink에서 자동으로 뽑는다. 그래야 본문과 메타가 어긋나지 않는다.

### WikiLink 파싱

`[[대상]]`과 `[[대상|별칭]]`을 정규식 하나로 잡는다.

```python
# practice/wikilink.py 의 핵심 부분
WIKILINK_RE = re.compile(r"\[\[([^\[\]\|]+?)(?:\|([^\[\]\|]+?))?\]\]")

def unique_targets(text: str) -> list[str]:
    """본문이 가리키는 대상 source_id 를 등장 순서대로, 중복 없이."""
    seen: list[str] = []
    for link in parse_wikilinks(text):
        if link.target not in seen:
            seen.append(link.target)
    return seen
```

링크 해소는 단순하다. 대상이 이미 아는 `source_id`면 그대로 통과. 어떤 문서의 alias면 그 문서의 `source_id`로 바꿔 준다. 둘 다 아니면 `None` — 가리키는 문서가 없는 dangling link다.

### 구조화기

`to_wiki.py`는 원본 본문을 읽어, 정해진 어구를 WikiLink로 치환하고, 위에 프런트매터를 얹는다. **원본 본문 텍스트는 바꾸지 않는다.** WikiLink 치환과 프런트매터 추가만 한다. 어느 어구를 어느 문서로 잇고 어떤 tag를 붙일지는 작은 계획표(`LINK_PLAN`)에 선언해 둔다. 치환할 어구는 원본에 실제로 있는 표현만 쓴다 — 없으면 치환이 0회라 본문이 그대로 남는다.

```python
# practice/to_wiki.py 의 핵심 부분
def convert_one(path: Path, src_root: Path) -> tuple[str, str]:
    raw = path.read_text(encoding="utf-8")
    plan = LINK_PLAN.get(path.stem, {})
    body = inject_wikilinks(raw, plan.get("links", []))   # 본문 보존, 어구만 [[...]] 로
    fm = WikiFrontmatter(
        title=extract_title(raw, path.stem),
        source_id=make_source_id(path, src_root),         # 01 규약 재사용
        tags=plan.get("tags", []),
        aliases=plan.get("aliases", []),
        links=unique_targets(body),                       # 본문에서 자동 도출
    )
    return path.name, to_frontmatter_md(fm, body)
```

YAML로 직렬화할 때 `allow_unicode=True`를 꼭 준다. 안 그러면 한글 `title`·`alias`가 `\uXXXX`로 깨진다. `sort_keys=False`로 선언 순서도 지킨다.

### 품질 게이트

`validate_wiki.py`는 `wiki/*.md`를 모두 읽어 세 가지를 본다. 모든 프런트매터가 스키마를 통과하는가(a). 본문의 모든 `[[대상]]`이 존재하는 문서나 alias를 가리키는가(b). 같은 주제를 가리키는데 표기가 갈라진 tag가 없는가(c). 01의 `validate_sources.py`와 같은 패턴이다. 문제 0건이면 exit 0, 1건 이상이면 exit 1이라 CI 게이트로도 쓴다.

```python
# practice/validate_wiki.py 의 핵심 부분
for sid, body in bodies.items():
    for link in parse_wikilinks(body):
        if resolve(link.target, known_ids, alias_index) is None:
            problems.append(f"[dangling] {sid}: [[{link.target}]] 가 가리키는 문서가 없다")
```

> 전체 코드와 실행 절차는 [`practice/`](practice/) 와 [`labs/`](labs/) 참조.
> 이 토픽은 임베딩·LLM 호출이 없어 API 키가 필요 없다. 로컬 파일·YAML·정규식만 다룬다. (Phase 4에서 LLM이 본문을 읽고 WikiLink·tag를 *자동 제안*하게 되는데, 그때도 검증 게이트는 그대로다. 비용이 부담되면 그 단계의 LLM을 Ollama로 바꿔도 파이프라인은 동일하다.)

## 4. 결과 해석 — 그래프의 밑그림이 생긴다

`to_wiki.py`를 돌리면 8건이 구조화된다.

```
[OK] structured 8 sources -> .../wiki/
     src-01-rag           links=2  tags=[rag,foundation]
     src-02-self-rag      links=1  tags=[rag,self-reflection]
     ...
     src-08-multihop      links=2  tags=[graphrag,foundation]
```

여기서 봐야 할 건 `links` 숫자다. `src-01-rag`는 멀티홉 문서와 Microsoft GraphRAG 문서를 가리키고, `src-08-multihop`은 Self-RAG·CRAG 문서를 가리킨다. 이 선들이 모이면 문서 그래프다. Phase 2는 이걸 처음부터 만들지 않는다. 여기 그어 둔 `[[...]]`를 KG의 첫 엣지로 받아 간다.

게이트가 통과하면 이렇게 나온다.

```
checked 8 wiki docs | 10 wikilinks | 0 schema | 0 dangling | 0 tag-inconsistency
OK: 8 wiki docs, 0 dangling link, tags consistent
```

게이트의 쓸모는 깨질 때 드러난다. 없는 문서로 가는 `[[src-99-nonexistent]]`를 넣으면 dangling으로 잡힌다. 한 문서의 tag를 대문자 `RAG`로 바꾸면 스키마에서 막힌다. 그런데 거기서 끝이 아니다. 그 문서가 검증에서 빠지면, 그 문서를 가리키던 다른 문서의 링크까지 줄줄이 dangling이 된다. WikiLink 그래프가 한 덩어리라서다. 표기 하나가 흔들리면 그래프 전체가 흔들린다 — 표기 통제가 사소해 보여도 사소하지 않은 이유다.

---

## 🚨 자주 하는 실수

1. **프런트매터를 본문 한가운데나 끝에 적음** — YAML 프런트매터는 파일 맨 위 첫 줄부터 `---`로 시작해야 파서가 인식한다. 본문 중간에 `---` 블록을 끼워 넣으면 메타가 아니라 그냥 수평선으로 읽힌다. 01에서 잡은 원본 해시는 본문 기준이고, 프런트매터는 그 위에 새로 얹는 층이라는 점을 기억하라. 본문을 고쳐 해시를 흔들지 말고, `wiki/`라는 새 산출물에만 프런트매터를 단다.
2. **dangling link를 방치함** — "나중에 그 문서 만들 거니까 일단 링크부터" 하고 없는 대상을 가리키면, 그 깨진 선이 Phase 2에서 그대로 KG의 끊긴 엣지가 된다. 게이트를 통과하지 못한 Wiki는 다음 토픽이 신뢰할 수 없다. 대상이 아직 없으면 링크를 걸지 않거나, 대상 문서부터 만든다.
3. **tag를 자유 입력으로 둠** — `rag`·`RAG`·`Rag`·`rag-`가 섞이면 같은 주제가 여러 갈래로 쪼개져 분류가 무의미해진다. tag는 통제 어휘처럼 다룬다. 표기 규칙(소문자·하이픈)을 스키마에 박고, 새 tag는 함부로 늘리지 않는다.
4. **WikiLink를 곧 KG 관계로 과신함** — `[[...]]`는 "이 둘이 관련 있다" 수준의 약한 선이다. *어떤* 관계인지(파생됨/사용함/반박함)는 담지 않는다. 02의 링크는 그래프의 *씨앗*일 뿐, 관계의 종류와 방향은 Phase 2에서 본문을 다시 읽어 라벨링한다. 지금 링크가 있다고 KG가 완성된 게 아니다.

## 출처

- Pydantic 공식 문서: https://docs.pydantic.dev/
- PyYAML 문서: https://pyyaml.org/wiki/PyYAMLDocumentation
- Peng et al., *Graph Retrieval-Augmented Generation: A Survey*(문서 그래프·구조화의 배경), arXiv [2408.08921](https://arxiv.org/abs/2408.08921)
- Obsidian 내부 링크(WikiLink) 관례: https://help.obsidian.md/Linking+notes+and+files/Internal+links

## 다음 토픽

→ [PDF·표·수식 파싱 — Docling·MinerU·RAG-Anything 비교](../03-pdf-table-formula-parsing/lesson.md)
