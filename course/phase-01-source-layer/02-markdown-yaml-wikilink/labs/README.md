# Lab 1.2 — 원본을 LLM Wiki 로 구조화하고 게이트 통과시키기

01 에서 신뢰 가능한 원본 8건을 세웠다. 이번에는 그 원본을 LLM·Agent 가 읽기 좋은 Wiki 문서로 바꾼다.
각 문서에 YAML 프런트매터를 얹고, 문서끼리 WikiLink([[...]])로 잇고, tag 로 분류한 뒤,
dangling link·tag 표기 오류를 잡는 품질 게이트를 통과시킨다.

이 실습은 네트워크·API 키·Neo4j·LLM 호출이 필요 없다. 로컬 파일만 다룬다.

## 사전 준비

```bash
cd course/phase-01-source-layer/02-markdown-yaml-wikilink/practice
pip install -r requirements.txt    # pydantic, pyyaml
```

예상 출력(이미 설치돼 있으면 다를 수 있다):

```
Successfully installed pydantic-2.x.x pyyaml-6.x.x ...
```

> `sources/` 8건은 01 과 같은 원본이다(같은 source_id 규약). 02 는 독립 실행을 위해 자체 동봉했다.

---

## 1단계 — 원본 확인

```bash
ls sources/
```

예상 출력:

```
01-rag.md  02-self-rag.md  03-crag.md  04-graphrag-ms.md  05-lightrag.md  06-neo4j.md  07-embedding.md  08-multihop.md
```

---

## 2단계 — Wiki 로 구조화

`sources/` 를 읽어 프런트매터 + WikiLink 를 주입한 `wiki/*.md` 를 만든다. 원본 본문은 보존한다.

```bash
python to_wiki.py
```

예상 출력:

```
[OK] structured 8 sources -> .../wiki/
     src-01-rag           links=2  tags=[rag,foundation]
     src-02-self-rag      links=1  tags=[rag,self-reflection]
     src-03-crag          links=1  tags=[rag,self-reflection]
     src-04-graphrag-ms   links=1  tags=[graphrag,community-summary]
     src-05-lightrag      links=1  tags=[graphrag,framework]
     src-06-neo4j         links=1  tags=[graph-db,storage]
     src-07-embedding     links=1  tags=[embedding,foundation]
     src-08-multihop      links=2  tags=[graphrag,foundation]
```

생성된 문서 하나를 들여다보자.

```bash
sed -n '1,24p' wiki/01-rag.md
```

예상 출력(프런트매터 + 본문 안 WikiLink):

```markdown
---
title: 검색 증강 생성(RAG)
source_id: src-01-rag
tags:
- rag
- foundation
aliases:
- RAG
- 검색 증강 생성
links:
- src-08-multihop
- src-04-graphrag-ms
---

# 검색 증강 생성(RAG)

...
RAG의 한계는 여러 문서에 흩어진 사실을 엮는 [[src-08-multihop|멀티홉 질문과 그래프]]에서 두드러진다.
이 문제의식이 [[src-04-graphrag-ms|Microsoft GraphRAG]]로 이어졌다.
```

`links` 는 본문의 WikiLink 에서 자동 도출된다. 본문과 메타가 어긋날 일이 없다.

---

## 3단계 — 품질 게이트 통과 확인

모든 문서의 프런트매터가 스키마를 통과하는지, dangling link 가 없는지, tag 표기가 일관적인지 본다.

```bash
python validate_wiki.py
echo "exit=$?"
```

예상 출력:

```
checked 8 wiki docs | 10 wikilinks | 0 schema | 0 dangling | 0 tag-inconsistency
OK: 8 wiki docs, 0 dangling link, tags consistent
exit=0
```

종료 코드 0 이면 다음 토픽(03~)과 Phase 2 가 이 Wiki 를 신뢰하고 쓸 수 있다.

---

## 4단계 — 일부러 깨뜨려 게이트가 잡는지 본다

### (a) dangling link — 없는 문서를 가리키기

```bash
cp wiki/06-neo4j.md /tmp/06-bak.md
# 06 본문에 존재하지 않는 문서로 가는 WikiLink 를 끼워 넣는다
python - <<'PY'
p="wiki/06-neo4j.md"; s=open(p,encoding="utf-8").read()
s=s.replace("그래프 데이터베이스다.","그래프 데이터베이스다. 자세한 건 [[src-99-nonexistent]] 참고.",1)
open(p,"w",encoding="utf-8").write(s)
PY
python validate_wiki.py; echo "exit=$?"
```

예상 출력(dangling 1건, 종료 코드 1):

```
checked 8 wiki docs | 11 wikilinks | 0 schema | 1 dangling | 0 tag-inconsistency
------------------------------------------------------------
  [dangling] src-06-neo4j: [[src-99-nonexistent]] 가 가리키는 문서가 없다
FAIL — 1 problem(s).
exit=1
```

복구한다.

```bash
cp /tmp/06-bak.md wiki/06-neo4j.md
```

### (b) tag 표기 오류 — 대문자 태그

```bash
cp wiki/02-self-rag.md /tmp/02-bak.md
# tag 를 소문자 rag -> 대문자 RAG 로 바꾼다(표기 규칙 위반)
python - <<'PY'
p="wiki/02-self-rag.md"; s=open(p,encoding="utf-8").read()
s=s.replace("- rag","- RAG",1)
open(p,"w",encoding="utf-8").write(s)
PY
python validate_wiki.py; echo "exit=$?"
```

예상 출력(스키마에서 tag 형식 위반을 잡는다. 그 문서가 빠지면서 그 문서를 가리키던 링크가 dangling 으로 번진다):

```
checked 7 wiki docs | 9 wikilinks | 1 schema | 2 dangling | 0 tag-inconsistency
------------------------------------------------------------
  [schema] 02-self-rag.md: Value error, tag 는 소문자·숫자·하이픈만 허용(공백·대문자·언더스코어 금지): 'RAG'
  [dangling] src-03-crag: [[src-02-self-rag]] 가 가리키는 문서가 없다
  [dangling] src-08-multihop: [[src-02-self-rag]] 가 가리키는 문서가 없다
FAIL — 3 problem(s).
exit=1
```

한 문서의 tag 표기 하나가 어긋났을 뿐인데, 그 문서를 가리키던 다른 문서의 링크까지 줄줄이 깨진다.
WikiLink 그래프가 한 덩어리라서다. 표기 통제가 왜 중요한지 여기서 드러난다.

복구한다.

```bash
cp /tmp/02-bak.md wiki/02-self-rag.md
```

### 롤백 확인

```bash
python validate_wiki.py; echo "exit=$?"
```

예상 출력:

```
checked 8 wiki docs | 10 wikilinks | 0 schema | 0 dangling | 0 tag-inconsistency
OK: 8 wiki docs, 0 dangling link, tags consistent
exit=0
```

> 깨진 결과를 못 믿겠으면 `python to_wiki.py` 로 wiki/ 를 통째로 다시 만들면 깨끗한 상태로 돌아온다.

---

## 완료 기준

`python to_wiki.py` 가 8건을 구조화하고, `python validate_wiki.py` 가
`OK: 8 wiki docs, 0 dangling link, tags consistent`(exit 0)를 출력하며,
없는 문서로 가는 `[[...]]` 나 표기 규칙을 어긴 tag 를 넣으면 게이트가 exit 1 로 잡으면 완료.
