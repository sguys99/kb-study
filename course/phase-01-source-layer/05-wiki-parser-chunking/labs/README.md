# Lab 1.5 — Wiki 파서 · section-aware chunking · metadata index 핸즈온

`practice/`의 코드로 02 Wiki(또는 원본) 문서를 파싱·청킹해 `out/chunks.jsonl`과 `out/index.json`을 만든다. 네트워크·API 키·LLM·Neo4j는 필요 없다. 순수 로컬 Pydantic + 표준 라이브러리만 쓴다.

예상 출력의 version(`v1@100918bd` 등)은 02 sources 본문이 그대로일 때 나오는 실제 값이다. 04의 `content_hash`(`sha256:100918bd`)와 같은 해시다 — 같은 본문을 같은 방식으로 해시했으니 당연히 일치한다. 본문을 건드리면 해시는 달라진다.

---

## 0. 전제 · 설치

- Python 3.11+ (3.12에서 검증)
- 선행 산출물이 같은 저장소에 있어야 한다:
  - 02: `course/phase-01-source-layer/02-markdown-yaml-wikilink/practice/sources/*.md` (8건) — `run_pipeline.py`가 상대경로로 읽는다.
  - 04: `course/phase-01-source-layer/04-document-data-contract/practice/provenance.py` — version 산출 함수를 import 한다.

작업 디렉토리는 `course/phase-01-source-layer/05-wiki-parser-chunking/practice/`.

```bash
cd course/phase-01-source-layer/05-wiki-parser-chunking/practice
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

`uv`를 쓴다면:

```bash
uv venv && source .venv/bin/activate
uv pip install -r requirements.txt
```

**예상 출력** (대략):

```
Successfully installed pydantic-2.x.x pydantic-core-2.x.x PyYAML-6.x.x ...
```

## 1. (선택) 02 wiki/ 생성

`run_pipeline.py`는 02의 `wiki/`가 있으면 그걸, 없으면 02의 `sources/`를 직접 읽는다. 둘 다 동작한다. 프런트매터까지 통과시켜 보고 싶으면 먼저 02를 실행해 `wiki/`를 만든다.

```bash
python ../../02-markdown-yaml-wikilink/practice/to_wiki.py
```

생략해도 된다. 그 경우 다음 단계가 자동으로 `sources/`를 입력으로 쓴다.

## 2. 파이프라인 실행

```bash
python run_pipeline.py
```

**예상 출력** (sources 입력, 02 wiki/ 미생성 시):

```
[1] 입력: sources 모드 — .../02-markdown-yaml-wikilink/practice/sources  (8건)

    source_id          version        sec chunks avg_tok
    ------------------ -------------- --- ------ -------
    src-01-rag         v1@100918bd      1      1   171.0
    src-02-self-rag    v1@bb20664e      1      1   134.0
    src-03-crag        v1@ae7157df      1      1   131.0
    src-04-graphrag-ms v1@7ab1f370      1      1   170.0
    src-05-lightrag    v1@a50e8b8c      1      1   156.0
    src-06-neo4j       v1@cad6be18      1      1   157.0
    src-07-embedding   v1@a7a0c9d5      1      1   154.0
    src-08-multihop    v1@f824aa35      1      1   201.0

[2] 통계 — 문서 8건 · 섹션 8개 · 청크 8건 · 평균 토큰 159.2
    출력: out/chunks.jsonl  +  out/index.json

[3] 첫 청크 예시:
    {"chunk_id": "src-01-rag#s0-0", "source_id": "src-01-rag", "version": "v1@100918bd", ...

[4] span 정합성 — 전 청크 body[char_start:char_end] == text 확인
    검사 8건 · 실패 0건 → span 정합성: ALL PASS

[완료] chunks.jsonl + index.json 생성 + span 정합성 확인 끝.
```

확인 포인트:

- 02 sources는 문서마다 H1 하나뿐이라 섹션 1개·청크 1건씩 나온다(짧은 섹션은 통째로 1청크). 멀티섹션 분할은 5단계에서 확인한다.
- `version`이 04의 `content_hash`와 같은 해시다. "청크 → 문서 → 원문" 사슬이 04의 문서 단위 계약과 같은 좌표를 쓴다는 뜻이다.
- `span 정합성: ALL PASS` — 전 청크에서 `body[char_start:char_end] == text`가 성립한다. 06이 이 offset으로 원문 인용을 떠도 안전하다.

02 `wiki/`를 먼저 생성했다면 `입력: wiki 모드`로 나오고, 프런트매터를 떼고 본문만 해시하므로 version 해시는 sources 모드와 달라진다(본문이 02 to_wiki의 WikiLink 치환으로 바뀌었기 때문). 둘 다 정상이다.

입력을 강제하려면:

```bash
python run_pipeline.py --src sources      # 항상 원본 사용
python run_pipeline.py --src wiki          # 항상 wiki 사용(없으면 안내 후 종료)
python run_pipeline.py --max-tokens 180    # 섹션 분할 예산 조정
```

## 3. chunks.jsonl 한 줄 들여다보기

JSONL은 한 줄에 청크 하나다. 06의 임베딩·BM25 색인이 한 줄씩 스트리밍으로 읽는다.

```bash
head -1 out/chunks.jsonl | python -m json.tool
```

> `python -m json.tool`은 기본값이 `ensure_ascii=True`라 한글을 `\uXXXX`로 보여준다. 파일 자체는 `ensure_ascii=False`로 저장돼 사람이 읽을 수 있다. 날것으로 보려면 `head -1 out/chunks.jsonl`.

**예상 출력** (구조):

```json
{
    "chunk_id": "src-01-rag#s0-0",
    "source_id": "src-01-rag",
    "version": "v1@100918bd",
    "section_path": ["검색 증강 생성(RAG)"],
    "heading": "검색 증강 생성(RAG)",
    "char_start": 17,
    "char_end": 310,
    "token_estimate": 171,
    "text": "검색 증강 생성(Retrieval-Augmented Generation, RAG)은 ...",
    "quote": "검색 증강 생성(Retrieval-Augmented Generation, RAG)은 2020년 Lewis 등"
}
```

`chunk_id`가 `{source_id}#s{섹션인덱스}-{순번}` 형태다. 내용이 바뀌어도 같은 위치면 같은 id를 준다(내용 변화는 version이 책임진다).

## 4. metadata index에서 tag로 chunk_id 역조회

06은 "rag 태그가 붙은 청크만" 같은 필터 검색을 한다. 그때 쓰는 역인덱스를 확인한다.

```bash
python -c "
import json
idx = json.load(open('out/index.json', encoding='utf-8'))
print('tag rag      ->', idx['by_tag']['rag'])
print('tag graphrag ->', idx['by_tag']['graphrag'])
print('source 06    ->', idx['by_source']['src-06-neo4j'])
print('06 acl       ->', idx['forward']['src-06-neo4j#s0-0']['acl_visibility'])
"
```

**예상 출력**:

```
tag rag      -> ['src-01-rag#s0-0', 'src-02-self-rag#s0-0', 'src-03-crag#s0-0']
tag graphrag -> ['src-04-graphrag-ms#s0-0', 'src-05-lightrag#s0-0', 'src-08-multihop#s0-0']
source 06    -> ['src-06-neo4j#s0-0']
06 acl       -> restricted
```

`acl_visibility`가 청크 메타에 따라온다. `06-neo4j`만 `restricted`다(04의 ACL 계약이 청크 수준까지 전파됐다). 06에서 권한 없는 청크가 답변에 인용되지 않게 막는 근거다.

## 5. section-aware 검증 — 멀티섹션 샘플

02 sources는 H1만 있어 섹션 분할을 보기 어렵다. `practice/sample_multisection.md`는 H1·H2·H3가 섞인 샘플이다. 청크가 섹션 경계를 넘지 않는지 직접 확인한다.

```bash
python -c "
from wiki_parser import parse_wiki
from chunker import chunk_document
from pathlib import Path
t = Path('sample_multisection.md').read_text(encoding='utf-8')
p = parse_wiki(t)
print('섹션:')
for s in p.sections:
    print('  L%d %-26s (%d,%d)' % (s.level, ' > '.join(s.section_path) or '(root)', s.char_start, s.char_end))
chunks = chunk_document(body=p.body, sections=p.sections,
                        source_id='src-99-multisection', version='v1@demo0000', max_tokens=80)
print('청크:', len(chunks))
for c in chunks:
    print('  %-24s path=%-30s tok=%-3d verify=%s' % (c.chunk_id, c.section_path, c.token_estimate, c.verify(p.body)))
def in_one(c):
    return any(s.char_start <= c.char_start and c.char_end <= s.char_end for s in p.sections)
print('모든 청크가 단일 섹션 내부:', all(in_one(c) for c in chunks))
"
```

**예상 출력**:

```
섹션:
  L1 멀티섹션 청킹 데모              (13,108)
  L2 멀티섹션 청킹 데모 > 배경        (114,380)
  L3 멀티섹션 청킹 데모 > 배경 > 세부 한계 (390,468)
  L2 멀티섹션 청킹 데모 > 결론        (474,506)
청크: 6
  src-99-multisection#s0-0 path=['멀티섹션 청킹 데모']           tok=51  verify=True
  src-99-multisection#s1-0 path=['멀티섹션 청킹 데모', '배경']     tok=66  verify=True
  src-99-multisection#s1-1 path=['멀티섹션 청킹 데모', '배경']     tok=78  verify=True
  src-99-multisection#s1-2 path=['멀티섹션 청킹 데모', '배경']     tok=65  verify=True
  src-99-multisection#s2-0 path=['멀티섹션 청킹 데모', '배경', '세부 한계'] tok=41  verify=True
  src-99-multisection#s3-0 path=['멀티섹션 청킹 데모', '결론']     tok=21  verify=True
```

읽는 법:

- `배경`(H2)이 예산(`max_tokens=80`)을 넘어 `#s1-0/1/2` 세 청크로 쪼개졌다. 문장 경계에서 잘렸고, overlap으로 경계 문장이 양쪽에 걸친다.
- 그래도 세 청크 모두 `section_path`가 `['멀티섹션 청킹 데모', '배경']`이다. **섹션을 넘은 청크는 하나도 없다.** 이게 section-aware의 핵심이다.
- `세부 한계`(H3)는 `section_path`가 `['배경', '세부 한계']`까지 누적된다(헤딩 스택).
- `모든 청크가 단일 섹션 내부: True` — 각 청크 `[char_start, char_end)`가 정확히 한 섹션 범위 안에 들어간다.

순진한 고정길이 청킹이었다면 `배경` 끝과 `결론` 시작이 한 청크에 섞여 인용 출처가 어긋났을 것이다.

## 다음

이 `chunks.jsonl` + `index.json`을 06이 입력으로 받아 임베딩·BM25 색인을 만들고 Baseline Hybrid RAG를 세운다. → [`../06-baseline-hybrid-rag/`](../06-baseline-hybrid-rag/)
