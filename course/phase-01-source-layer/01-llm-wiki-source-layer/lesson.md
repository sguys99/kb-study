# 1.1 LLM Wiki / Source Layer — 파일을 Agent의 신뢰 가능한 원본으로

> **Phase 1 · 토픽 01** · Phase 0 코퍼스 8건을 신뢰 가능한 원본 레이어(Source Layer)로 편입하고, 각 원본에 안정 식별자와 무결성 해시를 붙인 인덱스를 만든다.

## 학습 목표

이 토픽을 끝내면 다음을 할 수 있다.

- 신뢰 가능한 원본 레이어(Source Layer)의 폴더 규약을 설계하고, Phase 0 코퍼스 8건을 그 구조로 편입한다.
- Pydantic v2로 `SourceRecord` 모델을 정의해, 원본마다 안정 식별자(stable ID)·SHA-256 해시·출처 메타를 부여한 `source_index.jsonl`을 생성한다.
- 중복 ID·해시 불일치·필수 메타 누락을 잡는 최소 품질 게이트를 만들어, 원본을 한 글자 바꿨을 때 검증이 깨지는 것을 직접 확인한다.

**완료 기준**: `python build_source_index.py`가 8건을 인덱싱하고, `python validate_sources.py`가 `OK: 8 sources, 0 duplicate id, 0 hash mismatch`를 출력하며, 원본을 한 글자 바꾸면 해시 불일치가 잡히면 완료.

---

## 1. 왜 필요한가 — 그래프보다 원본이 먼저다

Phase 0에서 Vector-only RAG가 무너지는 네 가지를 봤다. 그중 마지막이 출처·근거였다. RAG는 조각을 합쳐 그럴듯한 답을 내지만, 그 문장이 *어느 파일의 어느 부분*에서 나왔는지는 보장하지 못한다.

이 문제는 그래프를 만든다고 저절로 풀리지 않는다. 오히려 반대다. 원본이 흐리면 거기서 뽑은 엔티티·관계도 흐리고, 그래프 위에서 추론한 답도 출처로 되돌아갈 길이 없다. 추출보다 정제가, 정제보다 *신뢰 가능한 원본*이 먼저다.

그래서 Phase 1은 그래프를 만들기 전에 토대부터 깐다. 흩어진 파일 더미를 Agent가 안심하고 인용할 수 있는 한 겹의 레이어로 정돈한다. 이게 Source Layer다. 이 토픽에서 만드는 정돈된 폴더와 인덱스가 02~06 토픽의 입력이 된다.

## 2. Source Layer와 LLM Wiki — 직관부터

Source Layer는 "원본을 한곳에, 일정한 규약으로, 추적 가능하게" 모아 둔 계층이다. 평범한 폴더와 뭐가 다른가. 세 가지를 보장한다.

첫째, **안정 식별자**. 파일명이 바뀌거나 폴더가 재배치돼도 같은 원본을 같은 ID로 가리킬 수 있어야 한다. KG의 노드도, Agent의 인용도 결국 이 ID를 잡는다.

둘째, **무결성**. 원본이 언제 바뀌었는지 알 수 있어야 한다. 내용의 해시를 지문처럼 떠 두면, 같은 ID인데 해시가 다른 순간을 잡아낼 수 있다. 이게 프로비넌스(Provenance, 출처·근거 추적)의 가장 작은 단위다.

셋째, **메타와 원본의 분리**. 원본 본문은 건드리지 않고, 메타는 따로 모은다. 본문에 YAML을 섞어 넣는 식의 구조화는 다음 토픽 몫이고, 여기서는 원본은 그대로 두고 인덱스만 옆에 둔다.

LLM Wiki는 이 Source Layer를 LLM·Agent가 읽기 좋은 형태로 가꾼 결과물을 가리키는 말이다. 위키처럼 문서끼리 연결되고, 각 문서에 메타가 붙고, 출처가 또렷한 지식 베이스. 이 토픽은 그 위키의 1층, 신뢰 가능한 바닥을 까는 단계다.

> stable ID·source span·ACL·버전을 포함한 풀 데이터 계약(Data Contract) 스펙은 04 토픽에서 다룬다. 여기서는 ID와 해시의 *필요성*만 직관으로 잡고, 최소 인덱스까지만 만든다.

## 3. 실습 — SourceRecord와 인덱스 빌더

먼저 원본 한 건을 표현하는 데이터 모델을 정한다. Pydantic v2를 쓴다. 필드 검증을 코드가 아니라 모델 선언에 박아 두면, 깨진 레코드가 인덱스에 들어가는 걸 입구에서 막을 수 있다.

핵심 필드는 `source_id`(안정 식별자)와 `sha256`(무결성 지문) 둘이다. 나머지는 제목·경로·크기·출처 같은 최소 메타다.

```python
# practice/source_record.py 의 핵심 부분
class SourceRecord(BaseModel):
    source_id: str = Field(..., examples=["src-01-rag"])  # 안정 식별자
    title: str
    path: str                                             # Source Layer 기준 상대 경로
    sha256: str                                           # 내용 무결성 지문
    bytes: int = Field(..., ge=0)
    origin: str = "local"
    origin_url: str | None = None
    license: str = "unknown"
    ingested_at: str = Field(default_factory=utc_now_iso)

    @field_validator("source_id")
    @classmethod
    def _id_format(cls, v: str) -> str:
        # 안정 식별자는 소문자·숫자·하이픈만. 공백·대문자는 나중에 깨진다.
        if not all(ch.islower() or ch.isdigit() or ch == "-" for ch in v):
            raise ValueError(f"source_id 는 소문자·숫자·하이픈만 허용: {v!r}")
        return v
```

stable ID는 경로에서 규칙적으로 만든다. 루트 기준 상대 경로에서 확장자를 떼고 디렉토리 구분자를 하이픈으로 바꾼 뒤 `src-`를 붙인다. `sources/01-rag.md`는 `src-01-rag`가 된다.

인덱스 빌더는 `sources/`를 스캔하면서 파일마다 해시를 뜨고, 제목(Markdown 첫 H1)을 뽑아 `SourceRecord`로 검증한 다음, 한 줄에 한 건씩 JSONL로 쓴다. 해시는 큰 코퍼스를 대비해 64KB씩 끊어 읽는다.

```python
# practice/build_source_index.py 의 핵심 부분
def build_record(path: Path, root: Path) -> SourceRecord:
    digest, size = sha256_of(path)              # 청크 단위 SHA-256
    return SourceRecord(
        source_id=make_source_id(path, root),   # sources/01-rag.md -> src-01-rag
        title=extract_title(path),              # 첫 H1, 없으면 파일명
        path=str(path.relative_to(root.parent).as_posix()),
        sha256=digest,
        bytes=size,
    )
```

품질 게이트는 인덱스와 실제 폴더를 대조한다. 보는 건 세 가지다. 같은 `source_id`가 둘 이상이면 Agent가 어느 원본을 가리키는지 모호해진다(중복 ID). 인덱스의 해시와 현재 파일의 해시가 다르면 인덱싱 후 원본이 바뀐 것이다(해시 불일치). `SourceRecord`로 다시 검증해 깨진 레코드도 잡는다(메타 누락·형식 오류). 문제가 0건이면 종료 코드 0을, 1건 이상이면 1을 돌려주므로 CI 게이트로도 쓸 수 있다.

```python
# practice/validate_sources.py 의 핵심 부분
actual, _ = sha256_of(file_path)
if actual != rec.sha256:
    problems.append(f"[hash] {rec.source_id}: 해시 불일치 — 원본이 바뀜")
```

> 전체 코드와 실행 절차는 [`practice/`](practice/) 와 [`labs/`](labs/) 참조.
> 이 토픽은 임베딩·LLM 호출이 없어 API 키가 필요 없다. 로컬 파일·메타·해시만 다룬다.

## 4. 결과 해석 — 인덱스가 보장하는 것

`build_source_index.py`를 돌리면 8건이 인덱싱된다.

```
[OK] indexed 8 sources -> source_index.jsonl
     src-01-rag               sha256=100918bd7135…  (639B)  검색 증강 생성(RAG)
     src-02-self-rag          sha256=bb20664e9b96…  (492B)  Self-RAG
     ...
```

여기서 봐야 할 건 ID와 해시다. `src-01-rag`라는 ID는 이제 이 원본의 영구 주소다. Phase 2에서 이 문서에서 엔티티를 뽑을 때도, Phase 7에서 Agent가 답에 출처를 달 때도 이 ID로 되돌아온다. 해시 `100918bd7135…`는 지금 이 순간 원본의 지문이다.

지문의 쓸모는 깨질 때 드러난다. 원본에 빈 줄 하나만 더해도 해시가 달라지고, `validate_sources.py`가 곧바로 불일치를 잡는다.

```
checked 8 records (8 valid) | 0 duplicate id | 1 hash mismatch | 0 missing file
  [hash] src-01-rag: 해시 불일치 (index=100918bd7135… actual=…) — 원본이 바뀜
FAIL — 1 problem(s).
```

Phase 0의 RAG는 답이 어느 파일에서 왔는지 보장하지 못했다. 이제 적어도 *원본 쪽*은 또렷해졌다. 원본마다 변하지 않는 주소가 있고, 내용이 바뀌면 그 사실이 곧바로 드러난다. 출처를 문장 단위로 답에 매다는 일은 청킹·검색을 거쳐 06 토픽 이후의 몫이지만, 그 출발점인 신뢰 가능한 원본 레이어가 여기서 선다.

---

## 🚨 자주 하는 실수

1. **파일명을 그대로 stable ID로 쓰고 나서 파일을 rename함** — 이 토픽의 ID 규칙은 경로 기반이라 편하지만, 파일을 옮기거나 이름을 바꾸면 ID가 통째로 바뀐다. 그러면 그 ID를 참조하던 KG 노드·인용이 전부 끊긴다. 일단 인덱싱한 원본은 함부로 rename하지 않는다. ID를 파일명과 완전히 분리하는 방법은 04 토픽에서 다룬다.
2. **원본 본문에 메타를 섞어 넣음** — "출처 URL을 본문 맨 위에 적어 두자" 같은 편의가 화를 부른다. 본문이 바뀌면 해시가 흔들리고, 메타와 내용이 엉켜 다음 토픽의 파싱이 꼬인다. 메타는 인덱스에, 원본은 그대로. 본문 안의 구조화(YAML 프런트매터 등)는 02 토픽의 규약을 따른다.
3. **검증을 한 번 통과시키고 다시 안 돌림** — 해시 게이트는 원본이 바뀔 때 의미가 있다. 원본을 손봤으면 인덱스를 다시 빌드하고 검증을 다시 돌려야 한다. 빌드 없이 검증만 돌리면 옛 해시와 새 파일이 어긋나 계속 FAIL이 난다.

## 출처

- Pydantic 공식 문서: https://docs.pydantic.dev/
- VoyageAI 임베딩(다음 단계 임베딩 배경): https://docs.voyageai.com/docs/embeddings
- Peng et al., *Graph Retrieval-Augmented Generation: A Survey*(원본·프로비넌스 레이어의 배경), arXiv [2408.08921](https://arxiv.org/abs/2408.08921)

## 다음 토픽

→ [원문 → Markdown·YAML·WikiLink 구조화](../02-markdown-yaml-wikilink/lesson.md)
