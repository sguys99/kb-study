# Lab 1.4 — 문서 Data Contract 핸즈온

`practice/`의 코드로 02 Wiki 원본 8건을 Data Contract로 검증한다. 네트워크·API 키·Neo4j는 필요 없다. 순수 로컬 Pydantic + 표준 라이브러리만 쓴다.

예상 출력의 해시값(`sha256:100918bd` 등)은 02 sources 본문이 그대로일 때 나오는 실제 값이다. 본문을 건드리면 해시는 당연히 달라진다.

---

## 0. 전제

- Python 3.11+ (3.12에서 검증)
- 선행 02 산출물이 같은 저장소에 있어야 한다: `course/phase-01-source-layer/02-markdown-yaml-wikilink/practice/sources/*.md` (8건). `validate_contract.py`가 이 폴더를 상대경로로 읽는다(복제하지 않는다).

## 1. 설치

작업 디렉토리는 `course/phase-01-source-layer/04-document-data-contract/practice/`.

```bash
cd course/phase-01-source-layer/04-document-data-contract/practice
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
Successfully installed pydantic-2.x.x pydantic-core-2.x.x ...
```

## 2. 계약 검증 + span 정합성

```bash
python validate_contract.py
```

**예상 출력**:

```
[1] Data Contract 빌드·검증 — .../02-markdown-yaml-wikilink/practice/sources

    source_id          rev content_hash           visibility  steps
    ------------------ --- ---------------------- ----------- -----
    src-01-rag           1 sha256:100918bd        internal    4
    src-02-self-rag      1 sha256:bb20664e        internal    4
    src-03-crag          1 sha256:ae7157df        public      4
    src-04-graphrag-ms   1 sha256:7ab1f370        internal    4
    src-05-lightrag      1 sha256:a50e8b8c        internal    4
    src-06-neo4j         1 sha256:cad6be18        restricted  4
    src-07-embedding     1 sha256:a7a0c9d5        internal    4
    src-08-multihop      1 sha256:f824aa35        internal    4

    직렬화 OK — src-01-rag 계약을 JSON 897 bytes 로 덤프

[2] source span 정합성 — text[start:end] == quote 인지 8건 모두 확인

    [PASS] src-01-rag         ( 17, 84)  '검색 증강 생성(Retrieval-Augmented G…'
    [PASS] src-02-self-rag    ( 12, 74)  'Self-RAG는 2023년 Asai 등이 발표한 기법…'
    ...
    [PASS] src-08-multihop    ( 15, 64)  '멀티홉(multi-hop) 질문은 답 하나를 얻으려고 …'

    span 정합성: ALL PASS

[3] 일부러 깨진 span(end 초과) — 거부되어야 정상

    [OK] end=411 > len(text)=311 → verify_against 가 거부함
    [OK] start>=end 위반은 model_validator 가 ValidationError 로 거부함

[완료] 8건 계약 검증·직렬화 + span offset 일치 확인 끝.
```

확인 포인트:

- 8건 모두 `[PASS]` — `text[start:end]`가 `quote`(검증용 사본)와 정확히 일치한다. 한국어·괄호·영문이 섞여도 문자 offset이라 안 깨진다.
- `visibility`가 문서마다 다르다. `06-neo4j`만 `restricted`, `03-crag`는 `public`. 나머지는 기본값 `internal`.
- `steps`가 모두 4 — 원문→파싱→정규화→wiki 체인이 붙었다.

## 3. 본문 1글자 수정 → version 변화

content_hash는 정규화한 본문을 sha256으로 해시한 값이다. 본문이 한 글자만 바뀌어도 해시가 바뀐다(=version이 바뀐다). 직접 확인한다.

```bash
python -c "
from provenance import content_hash, make_version
t1 = '# RAG\n\nRAG는 외부 문서를 검색해 근거를 붙인다.\n'
t2 = '# RAG\n\nRAG는 외부 문서를 검색해 근거를 붙인다!\n'   # 마지막 . -> !  (한 글자)
h1, h2 = content_hash(t1), content_hash(t2)
print('원본    :', h1, '->', make_version(1, h1))
print('1글자수정:', h2, '->', make_version(2, h2))
print('해시 다름:', h1 != h2)
"
```

**예상 출력**:

```
원본    : sha256:0b233fd6 -> v1@0b233fd6
1글자수정: sha256:3f7b10af -> v2@3f7b10af
해시 다름: True
```

`source_id`(stable ID)는 그대로다. 바뀐 건 version뿐이다. ID는 정체성, version은 상태다.

이번엔 본문은 그대로 두고 줄 끝 공백·빈 줄만 추가해 본다. 해시가 안 바뀌어야 한다(정규화가 흡수).

```bash
python -c "
from provenance import content_hash
t1 = '# RAG\n\nRAG는 외부 문서를 검색해 근거를 붙인다.\n'
t3 = '# RAG\n\nRAG는 외부 문서를 검색해 근거를 붙인다.   \n\n\n'  # 트레일링 공백+빈줄만
print('정규화가 흡수 (공백/빈줄 차이 무시):', content_hash(t1) == content_hash(t3))
"
```

**예상 출력**:

```
정규화가 흡수 (공백/빈줄 차이 무시): True
```

정규화 없이 해시하면 이 둘이 다른 version으로 갈렸을 것이다. 무의미한 공백 차이로 version이 흔들리면 재현성이 깨진다.

## 4. 잘못된 span은 계약이 거부한다

`end`가 본문 길이를 넘거나 `start >= end`이면 SourceSpan이 거부한다. 2단계 출력의 `[3]` 블록이 이미 이걸 시연한다. 직접 깨 보고 싶으면:

```bash
python -c "
from data_contract import SourceSpan
from pydantic import ValidationError
try:
    SourceSpan(source_id='src-01-rag', start=50, end=10)   # start >= end
except ValidationError as e:
    print('거부됨:', e.error_count(), 'error')
"
```

**예상 출력**:

```
거부됨: 1 error
```

`end > len(text)`는 본문을 알아야 잡히므로 스키마가 아니라 `span.verify_against(text)`가 `False`로 잡는다(2단계 `[3]` 참고).

## 다음

이 계약(`DocumentContract`)을 05에서 입력 스키마로 받아 청크마다 source span을 물려준다. → [`../05-wiki-parser-chunking/`](../05-wiki-parser-chunking/)
