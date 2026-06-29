# sources/ — Source Layer 루트

이 폴더가 **신뢰 가능한 원본 레이어(Source Layer)**다. 이후 모든 Phase(KG 추출·Neo4j·GraphRAG·Agent)는 여기 있는 원본을 인용 단위로 삼는다.

## 폴더 규약

- 원본은 한 파일에 한 문서. 파일명은 소문자·숫자·하이픈만 쓴다(`01-rag.md`).
- 원본 내용은 **함부로 바꾸지 않는다.** 내용이 바뀌면 해시가 달라지고, 인덱스 검증이 불일치를 잡는다.
- 메타·인덱스는 원본과 분리한다. 원본 옆에 메타를 섞어 넣지 않고, `source_index.jsonl` 한 곳에 모은다.
- 출처 URL·라이선스가 있으면 인덱스 레코드(`origin_url`, `license`)에 적는다. 지금 코퍼스는 Phase 0 에서 만든 로컬 학습용이라 `origin=local`, `license=unknown` 으로 둔다.

## 지금 들어 있는 것

Phase 0(`course/phase-00-orientation/01-why-graphrag-and-setup/practice/corpus/`)에서 만든 AI/LLM 기술 문서 8건을 그대로 편입했다. 이 8건이 이 토픽의 입력이고, 인덱싱·검증을 거친 결과가 02~06 토픽의 입력이 된다.

## 다음 토픽 예고

이 원본을 Markdown·YAML 프런트매터·WikiLink·tag 로 더 구조화하는 작업은 02 토픽에서, PDF·표·수식 파싱은 03, stable ID·version·source span·ACL 풀 Data Contract 는 04 에서 다룬다. 여기서는 폴더 규약 + 최소 인덱스까지만 만든다.
