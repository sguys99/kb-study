# 1.4 문서 Data Contract — stable ID·version·source span·ACL·provenance

> **Phase 1 · 토픽 04** · 02가 "source_id만 씨앗으로 넣고 나머지는 04로 미룬다"고 적어 둔 약속을 여기서 이행한다. 문서 한 건이 다운스트림(검색·추출·인용·삭제권)에 제공하기로 약속하는 안정적 인터페이스, 곧 Data Contract를 만든다.

## 학습 목표

이 토픽을 끝내면 다음을 할 수 있다.

- 문서 1건을 다섯 계약 필드(stable ID·version·source span·ACL·provenance)를 갖춘 `DocumentContract`로 표현한다.
- content_hash로 version을 결정하고, 본문이 한 글자만 바뀌어도 version이 따라 바뀌는 것을 재현한다.
- `SourceSpan`으로 인용 텍스트를 원문 문자 offset과 1:1로 정합 검증하고, 깨진 span이 거부되는 것을 확인한다.

**완료 기준**: `python validate_contract.py`가 Wiki 문서 8건을 Data Contract로 검증·직렬화하고, 임의 인용 span의 `text[start:end]`가 원문과 정확히 일치함을 출력하면 완료.

---

## 1. 왜 필요한가 — 답변이 원문으로 돌아갈 길

Phase 0에서 RAG가 무너지는 4가지를 봤다. 그중 둘이 출처 불명과 재현 불가다. 답변은 그럴듯한데 어느 문서에서 나왔는지 짚지 못한다. 같은 질문을 다시 던졌더니 근거가 달라진다. 이 둘은 검색 알고리즘을 바꾼다고 풀리지 않는다. 애초에 답변이 원문으로 돌아갈 길이 없어서 생기는 문제다.

그 길을 깔아 두는 게 Source Layer다. 그래프를 만들기 전에 신뢰 가능한 원본 레이어가 먼저다. 01에서 `src-` stable ID를 정했고, 02에서 Wiki 프런트매터로 구조를 얹었다. 02 코드는 `source_id`만 계약의 씨앗으로 넣고, version·source span·ACL·provenance는 04로 미뤘다. 미룬 그 필드를 채울 때가 지금이다.

계약이 책임지는 건 세 가지다. **인용 가능성** — 답변에서 원문으로 정확히 역추적된다. **재현성** — ID와 version이 같으면 내용이 같다고 보장한다. **거버넌스** — 누가 이 문서를 근거로 쓸 수 있는지, 이 문장이 어디서 와서 어떤 손을 거쳤는지 추적한다. 이 셋이 없으면 Phase 2에서 클레임을 추출해도 근거를 댈 수 없고, Phase 5에서 정책 게이트를 걸 데가 없다.

## 2. 다섯 필드의 직관 설계

### stable ID — 정체성

`src-01-rag` 같은 불변 식별자다. 01/02 규약을 그대로 쓴다. 핵심은 **불변**이다. 문서 내용이 바뀌어도 ID는 그대로 둔다. 대신 version을 올린다. ID는 정체성이고 version은 상태다. 내용이 바뀔 때마다 새 ID를 발급하면 같은 문서가 여러 정체성으로 쪼개진다. 그러면 "이 문서의 이전 버전"을 가리킬 방법이 사라진다.

### version — content-hash로 결정한다

version은 본문에서 파생한다. 본문을 정규화한 뒤 sha256으로 해시하고 앞 8글자만 떼서 `sha256:ab12cd34` 형태로 쓴다. 본문이 1글자만 달라도 해시가 바뀐다. 그래서 "같은 version이면 같은 내용"이 성립한다.

정수 version과 content-hash version은 잘하는 게 서로 다르다. 단조 증가 정수(`v1`, `v2`)는 순서가 명확하지만 누군가 상태를 관리해 줘야 한다. content-hash는 내용에서 결정적으로 나오지만 어느 게 먼저인지 순서를 모른다. 둘을 함께 쓰는 게 절충이다. `revision`(정수)이 순서를, `content_hash`가 내용 동일성을 책임지게 하고, 보여 줄 때만 `v{revision}@{short_hash}`로 합친다.

### source span — 라인이 아니라 문자 offset

답변이나 클레임이 가리키는 원문 위치를 문자 offset `(start, end)`로 표현한다. 검증식은 단순하다. `text[start:end]`가 인용 텍스트와 정확히 일치해야 한다. 일치하지 않으면 그 span은 거짓말이다.

왜 라인 번호가 아니라 문자 offset인가. 본문을 재정규화하거나 한국어·유니코드가 섞이면 라인 경계가 흔들린다. 줄바꿈 하나로 라인 번호가 통째로 밀린다. 문자 offset은 그런 흔들림에 강하고, `text[start:end]`로 곧장 검증된다. `SourceSpan`에는 `quote`(검증용 사본)를 함께 둔다. `text[start:end] == quote`를 자체검사하기 위해서다.

### ACL — 검색됐다고 인용해도 되는 건 아니다

접근 제어다. `visibility`(`public`/`internal`/`restricted`)와 `allow` 그룹 목록 정도로 최소하게 잡는다. 동기는 분명하다. 검색은 됐는데 권한 없는 문서가 답변에 인용되면 그게 사고다. 그래서 계약 단계에서 공개 범위를 못 박는다. Phase 5에서 이 필드를 답변 시점 정책 게이트로 확장한다.

### provenance — 어디서 와서 어떤 손을 거쳤나

출처와 가공 이력의 체인이다. `origin`(원본 URL·파일), `retrieved_at`(획득 시각), `parser`, 그리고 `steps`(가공 단계 목록)를 담는다. `parser`를 따로 둔 이유는 03과 이어진다. PDF를 Docling으로 변환했는지 MinerU로 변환했는지가 인용 정확도를 좌우했다. 표가 table로 살아남은 파서라야 셀 단위 span을 걸 수 있다는 게 03의 결론이다. 그 선택을 계약에 한 필드로 박아 둔다. steps는 원문→파싱→정규화→wiki 4단계로 표준화한다.

## 3. 실습 — DocumentContract를 짠다

해시 계산과 version 포맷은 모델과 분리한다. `provenance.py`에 순수 함수로 두고, `data_contract.py`가 import한다. 순환 import를 막으려는 분리다.

```python
# practice/provenance.py 핵심
import hashlib

def normalize_text(text: str) -> str:
    # 개행 통일 + 줄 끝 공백 제거 + 끝쪽 빈 줄 정리.
    # '줄 끝·개행'만 손댄다. 본문 글자를 건드리면 source span offset 이 어긋난다.
    unified = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in unified.split("\n")]
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines) + "\n"

def content_hash(text: str, *, short: bool = True) -> str:
    digest = hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()
    return f"sha256:{digest[:8]}" if short else f"sha256:{digest}"

def make_version(revision: int, hash_value: str) -> str:
    return f"v{revision}@{hash_value.split(':', 1)[-1]}"   # 예: v1@ab12cd34
```

`SourceSpan`은 위치만 약속한다. 본문은 담지 않는다. `quote`로 자체검사한다.

```python
# practice/data_contract.py 핵심
from pydantic import BaseModel, Field, model_validator

class SourceSpan(BaseModel):
    source_id: str
    start: int = Field(..., ge=0)
    end: int = Field(..., gt=0)
    quote: str | None = None   # 검증용 사본. text[start:end] 와 일치해야 한다.

    @model_validator(mode="after")
    def _check_range(self):
        if self.start >= self.end:
            raise ValueError(f"span 은 start < end 여야 한다: {self.start}, {self.end}")
        return self

    def verify_against(self, text: str) -> bool:
        if self.end > len(text):           # end 가 길이를 넘으면 거짓 span
            return False
        sliced = text[self.start:self.end]
        return self.quote is None or sliced == self.quote
```

`DocumentContract`는 02의 5필드를 그대로 품고 계약 필드를 얹는다. version은 저장하지 않고 `revision`과 `content_hash`에서 파생한다.

```python
class DocumentContract(BaseModel):
    # 02 WikiFrontmatter 계승 5필드
    title: str
    source_id: str
    tags: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    links: list[str] = Field(default_factory=list)
    # 04 계약 필드
    revision: int = Field(default=1, ge=1)
    content_hash: str
    acl: ACL = Field(default_factory=ACL)
    provenance: Provenance

    @property
    def version(self) -> str:                 # 항상 파생. single source of truth.
        return prov.make_version(self.revision, self.content_hash)

    @classmethod
    def from_document(cls, text, *, source_id, title, origin, retrieved_at,
                      parser="none", **kw) -> "DocumentContract":
        ch = prov.content_hash(text, short=True)     # 본문에서 content_hash 산출
        steps = [ProvenanceStep(**s) for s in prov.default_chain(parser=parser)]
        return cls(title=title, source_id=source_id, content_hash=ch,
                   provenance=Provenance(origin=origin, retrieved_at=retrieved_at,
                                         parser=parser, steps=steps), **kw)
```

검증 스크립트는 02의 sources/*.md 8건을 **그대로** 입력으로 읽는다. 파일을 복제하지 않는다.

```python
# practice/validate_contract.py 핵심
SOURCES_DIR = (HERE / ".." / ".." / "02-markdown-yaml-wikilink" / "practice" / "sources").resolve()

for path in load_sources():
    text = path.read_text(encoding="utf-8")
    c = DocumentContract.from_document(text, source_id=make_source_id_from_stem(path.stem), ...)
    span = first_sentence_span(text, c.source_id)     # 첫 본문 문장을 span 으로
    assert span.verify_against(text)                  # text[start:end] == quote
```

> 전체 코드와 실행 절차는 [`practice/`](practice/)와 [`labs/`](labs/) 참조.
> 이 토픽은 LLM·임베딩을 호출하지 않는다. 순수 로컬 Pydantic + `hashlib`만 쓰므로 비용 대안 분기가 필요 없다(API 키·Neo4j 불필요). 임베딩이 붙는 건 Phase 4다. 비용이 부담되면 그때 임베딩을 `bge-m3`(로컬), LLM을 Ollama로 바꾸면 된다.

## 4. 결과 해석

`validate_contract.py`를 돌리면 8건이 한 줄씩 요약된다.

```
src-01-rag           1 sha256:100918bd        internal    4
...
src-06-neo4j         1 sha256:cad6be18        restricted  4
```

`06-neo4j`만 `restricted`다. 검색에 걸려도 `allow` 그룹 밖이면 답변 근거로 못 쓴다. Phase 5 정책 게이트가 이 필드를 읽는다.

span 정합성 출력이 이 토픽의 핵심이다.

```
[PASS] src-01-rag         ( 17, 84)  '검색 증강 생성(Retrieval-Augmented G…'
...
span 정합성: ALL PASS
```

한국어·영문·괄호가 섞인 첫 문장을 문자 offset으로 떴는데 8건 모두 `text[start:end] == quote`가 성립한다. 이게 인용 품질의 토대다. 답변이 "src-01-rag의 (17,84)에서 나왔다"고 말하면, 그 자리에 정확히 그 문장이 있다고 계약이 보증한다. 추측이 아니라 검증된 인용이다.

여기서 03의 파서 선택이 다시 걸린다. 파서가 표를 줄글로 뭉개거나 한글을 깨뜨렸다면 offset이 어긋나 span 검증이 무너진다. provenance의 `parser` 필드가 "이 인용을 믿어도 되는가"의 단서가 되는 까닭이다.

마지막 블록은 깨진 span을 일부러 만들어 거부되는 걸 보여 준다. `end`가 본문 길이를 넘으면 `verify_against`가 `False`, `start >= end`면 `ValidationError`. 계약은 거짓 span을 통과시키지 않는다.

문서 단위 계약과 문자 offset span까지가 04의 범위다. 청크 분할은 05 몫이다. 05는 이 `DocumentContract`를 입력으로 받아 chunk마다 source span을 물려준다.

---

## 🚨 자주 하는 실수

1. **내용이 바뀔 때마다 stable ID를 새로 발급한다** — 같은 문서가 여러 정체성으로 쪼개진다. "이전 버전"을 가리킬 길이 사라지고, ID로 잇던 KG 엣지가 끊긴다. ID는 그대로 두고 version(`revision`+`content_hash`)으로 다뤄라. ID는 정체성, version은 상태다.
2. **source span을 라인 번호로 잡는다** — 본문을 재정규화하거나 한국어가 섞이면 라인 경계가 밀려 인용이 엉뚱한 곳을 가리킨다. 문자 offset `(start, end)`로 잡고 `quote` 사본으로 `text[start:end] == quote`를 자체검사하라. 라인은 사람이 읽기 편할 뿐 검증되지 않는다.
3. **content_hash 계산 전에 정규화를 안 한다** — 에디터가 붙인 줄 끝 공백, CRLF/LF 차이, 끝의 빈 줄 같은 무의미한 차이로 version이 흔들린다. 같은 내용인데 version이 갈리면 재현성이 깨진다. 해시 직전에 `normalize_text`로 개행·트레일링 공백만 정리하라(본문 글자는 건드리지 말 것 — offset이 어긋난다).
4. **provenance에 parser·origin을 안 남긴다** — 답변이 어느 파일에서, 어떤 파서를 거쳐 나왔는지 추적할 수 없다. 03에서 표가 죽은 파서로 변환했는데 그 사실이 계약에 없으면, 잘못된 인용의 원인을 영영 못 찾는다.

## 출처

- Pydantic 공식 문서: https://docs.pydantic.dev/
- (Phase 5 예고) SHACL — 그래프 제약 검증으로 ACL·정책을 확장할 때 다룬다: https://www.w3.org/TR/shacl/

## 다음 토픽

→ [Wiki 파서 · section-aware chunking · metadata index](../05-wiki-parser-chunking/lesson.md)
