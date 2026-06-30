# 1.5 Wiki 파서 · section-aware chunking · metadata index

> **Phase 1 · 토픽 05** · 04의 문서 단위 Data Contract를 청크 단위로 전파해, 06 Baseline RAG가 색인할 `chunks.jsonl`과 metadata index를 만든다.

## 학습 목표

이 토픽을 끝내면 다음을 할 수 있다.

- Wiki Markdown을 파싱해 프런트매터·본문·섹션 트리로 가르고, 헤딩 경로(section_path)를 본문 char offset과 함께 추출한다.
- section-aware chunker를 구성해 청크가 헤딩 경계를 가로지르지 않게 청킹하고, 긴 섹션은 문장 경계에서 overlap을 두고 분할한다.
- 청크마다 source_id·version·문자 offset을 물려 04 SourceSpan 계약을 청크 수준에서 검증하고(`body[start:end] == text`), `chunks.jsonl` + metadata index를 만들어 tag·source_id로 chunk_id를 역조회한다.

**완료 기준**: `python run_pipeline.py`가 8개 문서를 청킹해 `chunks.jsonl`과 `index.json`을 쓰고, 전 청크에서 `body[char_start:char_end] == text`가 성립하며(ALL PASS), `index.json`에서 tag로 chunk_id를 역조회하면 완료.

---

## 1. 왜 필요한가 — 04는 문서까지였다

04에서 문서 한 건은 stable ID·version·source span·ACL·provenance를 갖춘 Data Contract가 됐다. "답변이 이 문서, 이 offset에서 나왔다"를 코드로 검증한다.

문제는 RAG가 문서를 통째로 검색하지 않는다는 데 있다. 검색하고 인용하는 단위는 청크다. 04가 보증한 "문서 → 원문 역추적"은 청크가 그 계약을 물려받지 못하면 검색 결과에서 끊긴다. 06이 어떤 청크를 찾아왔는데 그게 어느 문서의 어느 자리인지, version이 뭔지 모르면 인용도 ACL 판정도 못 한다.

여기에 청킹 방식 자체의 함정이 겹친다. 순진한 고정길이 청킹은 "500자마다 자른다"처럼 의미 구조를 무시하고 끊는다. ## 헤딩 한복판, 문장 중간에서 잘린다. 한 청크에 서로 다른 두 절의 내용이 섞이면 검색 정밀도가 떨어지고, 그 청크를 인용해도 출처가 어느 절인지 흐려진다. Phase 0에서 본 RAG 실패 — 맥락이 끊긴 검색, 근거가 어긋난 답변 — 의 한 뿌리가 여기다.

05는 둘을 같이 푼다. 섹션 경계를 지키는 청킹으로 맥락을 보존하고, 청크마다 04 계약을 물려 "청크 → 문서 → 원문" 사슬을 잇는다.

## 2. 핵심 개념

### section-aware chunking

규칙은 하나다. **한 청크는 한 섹션 안에서만 존재한다.** 섹션 경계를 절대 넘지 않는다.

먼저 본문을 헤딩(`#`, `##`, `###`) 기준으로 섹션 트리로 나눈다. 각 섹션은 `section_path`를 갖는다 — 루트부터의 헤딩 경로다. `## 배경` 아래 `### 한계`는 `['배경', '한계']`가 된다. 청킹은 이 섹션 '안에서만' 일어난다. 짧은 섹션은 통째로 1청크, 토큰 예산을 넘는 섹션만 문장 경계에서 sub-chunk로 쪼갠다. 경계 문장이 어느 한쪽에는 온전히 담기도록 1문장 정도 overlap을 준다.

이렇게 하면 청크는 늘 한 절의 내용만 담는다. `section_path`가 따라붙으니 "이 청크는 GraphRAG 문서의 '한계' 절에서 왔다"를 그대로 안다.

### 청크가 무는 4개 메타

청크 하나가 04 계약을 청크 수준에서 이으려면 무는 핵심이 넷이다.

- **chunk_id** — `{source_id}#s{섹션인덱스}-{순번}`. 위치 식별자다. 내용이 바뀌어도 같은 위치면 같은 id다. 06이 검색 결과를 안정적으로 참조하고 중복을 제거하려면 이 위치 안정성이 필요하다.
- **version** — 04의 `make_version`이 만든 `v1@해시`. 내용 동일성은 이게 책임진다(그래서 chunk_id는 위치만 식별한다).
- **char_start·char_end** — 본문(body) 기준 문자 offset. 04 SourceSpan과 같은 좌표계다.
- **section_path** — 청크의 출처 절. 인용·필터에 쓴다.

`char_start`·`char_end`는 04 SourceSpan을 청크 수준에서 다시 쓰는 지점이다. `body[char_start:char_end] == text`가 성립해야 청크가 건강하다. 이 한 줄이 "청크 → 문서 → 원문" 인용 사슬의 자물쇠다.

### JSONL과 metadata index

출력은 둘이다.

`chunks.jsonl`은 한 줄에 청크 하나인 JSON이다. 06의 임베딩·BM25 색인이 한 줄씩 스트리밍으로 읽기 좋고, 한 청크를 고쳐도 그 줄만 다시 쓰면 된다. 한글이 `\uXXXX`로 깨지지 않게 `ensure_ascii=False`로 쓴다.

metadata index는 본문을 뺀 가벼운 색인이다. 정방향은 `chunk_id → {source_id, version, section_path, tags, acl_visibility, offset...}`이다. 검색이 던져 준 chunk_id로 메타를 즉시 끌어와 인용·정책 판정에 쓴다. 역인덱스는 `tag → [chunk_id...]`, `source_id → [chunk_id...]`다. 06에서 "rag 태그 청크만" 같은 필터 검색에 쓴다.

## 3. 실습 — section-aware chunker

핵심은 "섹션을 먼저 나누고, 각 섹션 안에서만 청킹한다"는 구조다. 아래는 `chunker.py`의 분할 루프 골격이다.

```python
# practice/chunker.py 의 핵심 — 섹션 안에서만, 문장 경계로 분할
def chunk_document(*, body, sections, source_id, version, max_tokens=220, overlap_sentences=1):
    chunks = []
    for sec_idx, sec in enumerate(sections):
        # 섹션 본문을 토큰 예산 안의 (start, end) 로 쪼갠다(섹션 경계를 절대 안 넘는다)
        spans = _split_section_body(body, sec, max_tokens, overlap_sentences)
        for ordinal, (start, end) in enumerate(spans):
            text = body[start:end]
            chunks.append(Chunk(
                chunk_id=f"{source_id}#s{sec_idx}-{ordinal}",   # 위치 식별자(안정적)
                source_id=source_id, version=version,
                section_path=sec.section_path, heading=sec.heading,
                char_start=start, char_end=end,                 # 본문 기준 offset
                token_estimate=estimate_tokens(text),
                text=text, quote=text[:QUOTE_LEN],
            ))
    return chunks
```

04 계약을 청크 수준에서 검증하는 메서드는 이렇게 단순하다.

```python
# Chunk.verify — 04 SourceSpan 을 청크 수준에서 재사용
def verify(self, body: str) -> bool:
    if self.char_end > len(body):
        return False
    return body[self.char_start:self.char_end] == self.text
```

`run_pipeline.py`는 02의 `wiki/`(없으면 `sources/`)를 읽어 파싱 → version 산출(04 `provenance.py`를 import) → 청킹 → 메타 부착 → `out/chunks.jsonl` + `out/index.json`을 쓰고, 전 청크에 대해 `verify`를 돌린다.

> 전체 코드와 실행 절차는 [`practice/`](practice/)와 [`labs/`](labs/) 참조.
> 이 토픽은 04와 마찬가지로 임베딩·LLM이 없다(순수 로컬, 토큰 추정은 휴리스틱). 임베딩은 06/Phase 4에서 붙고, 비용이 부담되면 그때 `bge-m3`(로컬)·Ollama 대안 분기를 따른다.

## 4. 결과 해석

`python run_pipeline.py`는 문서수·섹션수·청크수·평균 토큰 통계와 span 자체검증을 출력한다.

```
[2] 통계 — 문서 8건 · 섹션 8개 · 청크 8건 · 평균 토큰 159.2
[4] span 정합성 — 전 청크 body[char_start:char_end] == text 확인
    검사 8건 · 실패 0건 → span 정합성: ALL PASS
```

02 sources는 H1 하나뿐이라 문서마다 섹션 1개·청크 1건이다. version의 해시(`v1@100918bd`)는 04의 `content_hash`(`sha256:100918bd`)와 같다 — 같은 본문을 같은 방식으로 해시했으니 일치하는 게 맞다. 청크가 04 문서 계약과 같은 좌표를 쓴다는 증거다.

`span 정합성: ALL PASS`가 이 토픽의 핵심 검증이다. 전 청크에서 `body[char_start:char_end]`가 `text`와 정확히 일치하면, 06이 이 offset으로 원문을 떠도 인용이 어긋나지 않는다. 멀티섹션 샘플(`sample_multisection.md`)로 돌리면 긴 `배경` 절이 `#s1-0/1/2`로 쪼개지면서도 셋 다 `section_path`가 `['배경']`에 머무는 걸 볼 수 있다(labs 5단계). 섹션을 넘은 청크는 하나도 없다.

`index.json`에서 `by_tag['rag']`를 조회하면 rag 태그가 붙은 chunk_id 목록이 나온다. 06의 태그 필터 검색이 여기서 출발한다.

---

## 🚨 자주 하는 실수

1. **고정 길이로 무작정 잘라 섹션·문장을 끊는다** — "N자마다 자른다"는 ## 헤딩 한복판, 문장 중간을 끊어 한 청크에 두 절을 섞는다. 검색 정밀도가 떨어지고 인용 출처가 흐려진다. 섹션을 먼저 나누고 각 섹션 안에서만 청킹한다(section-aware). overlap을 0으로 두면 섹션 끝 문장이 어느 청크에도 온전히 안 담길 수 있으니 1문장 정도는 겹친다.
2. **청크에 version·offset을 안 단다** — chunk_id만 있고 version·char offset이 없으면 04의 인용·삭제권 계약이 청크에서 끊긴다. 06이 청크를 찾아도 어느 version의 어느 자리인지 몰라 원문 역추적이 안 된다. 청크를 만들 때 04 `provenance`로 version을 산출해 붙이고, `body[start:end] == text`를 반드시 검증한다.
3. **JSONL을 `ensure_ascii=True`로 쓴다** — 한글이 `\uXXXX`로 깨져 사람이 파일을 못 읽고 디버깅이 어려워진다. `json.dumps(..., ensure_ascii=False)`로 쓴다(`python -m json.tool`은 기본이 `ensure_ascii=True`라 화면에선 이스케이프되어 보이지만, 파일 자체는 멀쩡한 것과 구분해야 한다).

## 출처

- Pydantic — https://docs.pydantic.dev/
- (06 예고) VoyageAI 임베딩 — https://docs.voyageai.com/docs/embeddings

## 다음 토픽

→ [Baseline Hybrid RAG (기준선)](../06-baseline-hybrid-rag/lesson.md)
