# Lab 1.1 — Source Layer 만들고 인덱스 검증하기

Phase 0 코퍼스 8건을 신뢰 가능한 원본 레이어로 편입하고, stable ID·해시를 붙인 인덱스를 만든 뒤 품질 게이트를 통과시킨다.

이 실습은 네트워크·API 키·Neo4j 가 필요 없다. 로컬 파일만 다룬다.

## 사전 준비

```bash
cd course/phase-01-source-layer/01-llm-wiki-source-layer/practice
pip install -r requirements.txt    # pydantic 만 설치된다
```

예상 출력(이미 설치돼 있으면 다를 수 있다):

```
Successfully installed pydantic-2.x.x ...
```

---

## 1단계 — Source Layer 폴더 확인

Phase 0 코퍼스 8건이 `sources/` 로 이미 편입돼 있다. (직접 다시 복사하고 싶으면 아래 명령으로 덮어쓴다.)

```bash
ls sources/
```

예상 출력:

```
01-rag.md  02-self-rag.md  03-crag.md  04-graphrag-ms.md  05-lightrag.md  06-neo4j.md  07-embedding.md  08-multihop.md  README.md
```

> 직접 편입하려면: `cp ../../../phase-00-orientation/01-why-graphrag-and-setup/practice/corpus/*.md sources/`

---

## 2단계 — 인덱스 빌드

`sources/` 를 스캔해 각 원본에 stable ID·SHA-256 해시를 부여하고 `source_index.jsonl` 을 만든다. (`README.md` 는 규약 설명 문서라 인덱스에서 빠진다.)

```bash
python build_source_index.py
```

예상 출력(해시 앞 12자는 환경 무관하게 동일하다):

```
[OK] indexed 8 sources -> .../source_index.jsonl
     src-01-rag               sha256=100918bd7135…  (639B)  검색 증강 생성(RAG)
     src-02-self-rag          sha256=bb20664e9b96…  (492B)  Self-RAG
     src-03-crag              sha256=ae7157df38c9…  (501B)  Corrective RAG(CRAG)
     src-04-graphrag-ms       sha256=7ab1f370383b…  (640B)  Microsoft GraphRAG
     src-05-lightrag          sha256=a50e8b8c2bb3…  (600B)  LightRAG
     src-06-neo4j             sha256=cad6be18d4d2…  (572B)  Neo4j
     src-07-embedding         sha256=a7a0c9d5e554…  (546B)  임베딩과 VoyageAI
     src-08-multihop          sha256=f824aa352eab…  (728B)  멀티홉 질문과 그래프
```

생성된 인덱스 한 줄을 들여다보자.

```bash
head -1 source_index.jsonl
```

예상 출력(한 줄 = 한 레코드, JSONL):

```json
{"source_id": "src-01-rag", "title": "검색 증강 생성(RAG)", "path": "sources/01-rag.md", "sha256": "100918bd7135...", "bytes": 639, "origin": "local", "origin_url": null, "license": "unknown", "ingested_at": "2026-..."}
```

---

## 3단계 — 품질 게이트 통과 확인

인덱스와 실제 파일을 대조해 중복 ID·해시 불일치·필수 메타 누락을 점검한다.

```bash
python validate_sources.py
echo "exit=$?"
```

예상 출력:

```
checked 8 records (8 valid) | 0 duplicate id | 0 hash mismatch | 0 missing file
OK: 8 sources, 0 duplicate id, 0 hash mismatch
exit=0
```

종료 코드 0 이면 다음 토픽이 이 인덱스를 신뢰하고 쓸 수 있다.

---

## 4단계 — 일부러 깨뜨려 게이트가 잡는지 본다

원본을 한 글자 바꾸면 해시가 달라진다. 검증이 이걸 잡아야 진짜 무결성 게이트다.

```bash
echo "" >> sources/01-rag.md      # 원본에 빈 줄 한 줄 추가(내용 변경)
python validate_sources.py
echo "exit=$?"
```

예상 출력(해시 불일치 1건 검출, 종료 코드 1):

```
checked 8 records (8 valid) | 0 duplicate id | 1 hash mismatch | 0 missing file
------------------------------------------------------------
  [hash] src-01-rag: 해시 불일치 (index=100918bd7135… actual=…) — 원본이 바뀜
FAIL — 1 problem(s).
exit=1
```

원상 복구하고 인덱스를 다시 빌드하면 OK 로 돌아온다.

```bash
cp ../../../phase-00-orientation/01-why-graphrag-and-setup/practice/corpus/01-rag.md sources/01-rag.md
python build_source_index.py
python validate_sources.py
```

예상 출력(마지막 줄):

```
OK: 8 sources, 0 duplicate id, 0 hash mismatch
```

---

## 완료 기준

`python build_source_index.py` 가 8건을 인덱싱하고, `python validate_sources.py` 가 `OK: 8 sources, 0 duplicate id, 0 hash mismatch` 를 출력하며, 원본을 한 글자 바꾸면 해시 불일치가 잡히면 완료.
