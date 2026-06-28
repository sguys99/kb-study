# 스택·버전·코퍼스 규약 (Stack Conventions)

모든 토픽이 같은 도구·버전·데이터·키를 쓴다. 토픽마다 다른 라이브러리를 임의로 들이지 않는다. 버전이 빠른 항목은 [authoring-checklist.md]의 "선별 검증" 대상이다.

## 레퍼런스 스택 (기본 선택 고정)

| 역할 | 기본 선택 | 대안 / 비고 |
|------|-----------|-------------|
| LLM | **Claude** (Anthropic) | OpenAI GPT / Ollama(로컬·비용 0) |
| 임베딩 | **VoyageAI** `voyage-3.5`(기본) / `voyage-3-large`(고품질) / `voyage-context-3`(문맥형) | 도메인: `voyage-finance-2`·`voyage-law-2` / 대안 `BAAI/bge-m3`·`e5` |
| GraphRAG 프레임워크 | **LightRAG** (HKUDS, 메인) — 5모드 `naive/local/global/hybrid/mix` + WebUI | 개념·비교용 Microsoft GraphRAG |
| 그래프 DB | **Neo4j** 5.26 LTS 또는 2025+ CalVer(YYYY.MM) + **GDS**(PageRank·Leiden) + 네이티브 벡터·풀텍스트 인덱스 | Memgraph(LightRAG 호환) |
| 문서 파싱 | **Docling** / **MinerU** / **RAG-Anything** 비교 | MinerU=한국어 OCR, RAG-Anything=멀티모달 |
| 구조적 출력·검증 | **Pydantic**(LLM Structured Output) + **SHACL/pyshacl**(그래프 제약) | instructor |
| 평가 | **Ragas** | DeepEval |
| 관측성 | **Langfuse** | LangSmith |
| 에이전트 | Anthropic tool-use 루프(기본·경량) / **LangGraph**(분기·루프·체크포인트) | — |
| 환경 | Python 3.11+, Docker / Docker Compose, Claude Code | — |

> ⚠️ **버전 주의 (선별 검증 항목)**: Neo4j는 2025년부터 CalVer로 전환 — **5.26 LTS** 또는 2025+ CalVer 사용. LightRAG 쿼리모드·API 서버, VoyageAI 모델명, Ragas/Langfuse API는 빠르게 바뀌므로 작성 시점에 재확인한다.

## 러닝 코퍼스 (Part 2 전체 공통)

- **무엇**: AI/LLM 기술 문서 — arXiv RAG/GraphRAG/에이전트 논문(Self-RAG, CRAG, Microsoft GraphRAG 등) + 프레임워크 공식 docs(LightRAG, LangChain, Neo4j).
- **왜**: 대상 개발자에게 친숙하고, 멀티홉·관계·인용·전체 요약 질문이 풍부해 GraphRAG 효과를 체감하기 좋으며, 라이선스 부담이 적고 자기참조적이다.
- **규모**: Phase 1에서 약 50–100건으로 시작 → Phase 진행하며 증분 적재로 확장.
- **원칙**: 하나의 코퍼스가 단계마다 진화한다(원문 → LLM Wiki → KG → Neo4j → GraphRAG → Agent → 캡스톤). 토픽 코드는 **앞 Phase 산출물을 입력으로** 받는다.
- **캡스톤 분기**: 금융(SEC EDGAR) · 의료(PrimeKG·DDInter·FHIR) · 연구(OpenAlex·arXiv·S2ORC). Phase 7 Reference Harness에 도메인 어댑터만 교체.

## API 키 · 비용 대안 분기

- **필수 키**: `ANTHROPIC_API_KEY`(Claude), `VOYAGE_API_KEY`(임베딩). 코드는 `os.environ`/`.env`에서 읽고, 키를 하드코딩하지 않는다.
- **비용 최소화 분기**: 상용 API가 필요한 실습에는 **Ollama + `bge-m3`** 로컬 대안을 lesson에 1–2줄로 명시한다. 비용 비교(Phase 4)처럼 상용 모델이 핵심인 토픽에서는 그 이유를 밝힌다.
- **권장 안내 문구(예)**: "비용이 부담되면 임베딩을 `bge-m3`(로컬), LLM을 Ollama로 바꿔도 된다. 결과 품질은 떨어질 수 있으나 파이프라인은 동일하게 동작한다."

## 코드 작성 규약

- 코드 주석은 **한국어**. 변수·함수명은 영어(관용).
- 외부 의존(Neo4j 접속, API 키, Docker)이 필요한 코드는 **상단 주석에 전제**를 명시하고, 가능하면 `docker-compose.yml`을 `practice/`에 동봉한다.
- 실행 절차는 `labs/`에 단계별 명령 + **예상 출력**으로 둔다.
- 코드는 [authoring-checklist.md]의 "정적 검증" 기준(문법·import·타입·논리 일관성)을 통과해야 한다. 실제 실행 검증은 학습자 몫(roadmap 방침).

## 핵심 출처 (URL — roadmap 참고 문헌과 일치)

- GraphRAG Survey: arXiv [2408.08921](https://arxiv.org/abs/2408.08921)
- Microsoft *From Local to Global*: arXiv [2404.16130](https://arxiv.org/abs/2404.16130)
- LLM Meets KG for QA: arXiv [2505.20099](https://arxiv.org/abs/2505.20099)
- Self-RAG [2310.11511](https://arxiv.org/abs/2310.11511) · CRAG [2401.15884](https://arxiv.org/abs/2401.15884) · Adaptive-RAG [2403.14403](https://arxiv.org/abs/2403.14403)
- LightRAG: https://github.com/HKUDS/LightRAG · Microsoft GraphRAG: https://microsoft.github.io/graphrag/
- Neo4j: https://neo4j.com/docs/ · GDS: https://neo4j.com/docs/graph-data-science/current/
- VoyageAI: https://docs.voyageai.com/docs/embeddings · Pydantic: https://docs.pydantic.dev/
- SHACL: https://www.w3.org/TR/shacl/ · pySHACL: https://github.com/RDFLib/pySHACL
- Ragas: https://docs.ragas.io/ · Langfuse: https://langfuse.com/docs · LangGraph: https://docs.langchain.com/
- Docling: https://github.com/docling-project/docling · MinerU: https://github.com/opendatalab/MinerU · RAG-Anything: https://github.com/HKUDS/RAG-Anything
- Awesome-GraphRAG: https://github.com/DEEP-PolyU/Awesome-GraphRAG

> 토픽별 "출처"에는 roadmap의 해당 Phase "자료" 섹션 URL을 우선 사용한다. 새 URL은 선별 검증 후에만 추가한다.
