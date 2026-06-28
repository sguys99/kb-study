# 개발자를 위한 지식그래프(Knowledge Graph) + GraphRAG + Agentic RAG 학습 로드맵

> **대상**: 개발·RAG·Agent 기본기는 있지만, 최신 지식베이스/그래프 개념과 구축 방법을 제대로 배우고 싶은 개발자
> **총 기간**: 약 10–12주 (주 8–10시간 기준)
> **핵심 원칙**: 모든 Phase에 **이론 + 코드 실습 + 핸즈온**을 포함하고, **하나의 코퍼스가 Wiki → KG → Neo4j → GraphRAG → Agent로 진화**합니다. 마지막에 3개 도메인 캡스톤으로 분기합니다.
> **출처**: 본 로드맵의 도구·버전·데이터셋·논문은 2026년 6월 기준 공식 문서/GitHub/논문으로 검증했습니다. 각 Phase "자료" 섹션과 문서 끝 [참고 문헌](#-참고-문헌source)에 URL을 명기합니다.

> 💡 **이 과정이 답하는 질문**: "기존 RAG는 왜 멀티홉·관계·전체 요약·출처 질문에서 무너지는가, 그리고 지식그래프로 어떻게 그것을 해결하는가." 우리는 그 답을 **읽지 않고 직접 만들면서** 배웁니다.

---

## 📐 챕터 작성 표준

본 로드맵은 토픽 단위로 강의 자료(`course/phase-<NN>-<slug>/<NN>-<topic-slug>/`)가 생성됩니다. 모든 토픽의 `lesson.md`는 다음을 포함합니다.

- **학습 목표 3개 이상** (상단)
- **완료 기준 1줄** (예: "`mix` 모드 답변에 인용 문서 3건이 붙고, Vector-only 대비 멀티홉 정답률이 올라가면 완료")
- **이론 + 코드 실습** (실습 비중을 풍부하게 — 개념 설명 후 곧바로 실행 가능한 코드)
- **🚨 자주 하는 실수 1–3개** (하단)
- **출처** (공식 docs/GitHub/논문 URL)
- **다음 토픽 링크** (마지막 줄)

각 토픽 디렉토리 산출물 4종:

| # | 산출물 | 내용 |
|---|--------|------|
| 1 | `lesson.md` | 이론 + 코드 실습 본문 (= 정적 사이트의 한 페이지) |
| 2 | `practice/` | Python 스크립트·노트북, Dockerfile, `docker-compose.yml`, Cypher, 매니페스트 |
| 3 | `labs/` | 단계별 핸즈온 명령 + 예상 출력 |
| 4 | 실행 검증 | 로컬에서 동작 확인 (학습자가 labs 실행 후 갱신) |

---

## 🧵 누적 실습 스토리라인

Phase별로 따로 노는 실습이 아니라, **하나의 지식 시스템이 단계마다 한 겹씩 쌓이며 완성**됩니다. Part 2(핵심 기술) 전체에서 **AI/LLM 기술 문서 코퍼스**(arXiv RAG/GraphRAG 논문 + 프레임워크 docs)를 일관되게 사용하고, 마지막에 3개 도메인 캡스톤으로 분기합니다.

| Phase | 산출물 | 다음 Phase 입력 |
|-------|--------|----------------|
| 0 | 환경 세팅(Claude·VoyageAI·LightRAG·Neo4j·Docker) + "RAG가 무너지는 4가지 실패" 재현 | Phase 1의 기준선 |
| 1 | 원문 → **LLM Wiki**(Markdown·YAML·WikiLink) + Data Contract + **Baseline Hybrid RAG**(Vector+BM25) | Phase 2의 추출 입력 |
| 2 | Wiki → **Knowledge Graph**(Entity·Relation·Claim·Event) + Entity Resolution + 품질 게이트 | Phase 3의 적재 대상 |
| 3 | KG를 **Neo4j**에 적재 + Cypher·하이브리드 검색 + GDS(PageRank·Leiden) | Phase 4의 그래프 백엔드 |
| 4 | **GraphRAG 검색**(Local·Global·Path) + **LightRAG** 5모드 + Neo4j 운영 | Phase 7 Agent의 검색 도구 |
| 5 | **Ontology / Semantic Layer**(Controlled Vocabulary·Canonical ID·SHACL 검증) | 검색·답변 시 의미·정책 게이트 |
| 6 | **평가·관측성**(Ragas·Langfuse·Regression Gate) | 개선을 정량 입증하는 안전망 |
| 7 | **Agent Harness**(Tool·Router·Grader·Audit Trail) = 도메인 중립 **Reference Harness** | 캡스톤 3개의 공통 골격 |
| Capstone | 금융·의료·연구 = Reference Harness + 도메인 어댑터 | Phase 8 운영 대상 |
| 8 | 통합 운영(배포·갱신·삭제·백업·Incident Playbook) + 현업 적용 로드맵 | — |

> 💡 **핵심 도약 지점**: Phase 4(LightRAG)에서 "그래프 + 벡터 융합 검색"이 완성되고, Phase 7(Agent Harness)에서 "검색을 호출하는 에이전트"로 한 단계 올라섭니다. 캡스톤은 Phase 7의 Harness 하나에 도메인 데이터/온톨로지만 갈아 끼웁니다.

---

## 🧪 레퍼런스 스택 · 러닝 코퍼스

모든 챕터에서 일관되게 사용할 스택을 미리 못 박습니다. **버전이 빨리 바뀌는 항목은 발행 시점에 재확인**하세요.

| 역할 | 기본 선택 | 대안 / 비고 | 출처 |
|------|-----------|-------------|------|
| **LLM** | **Claude** (Anthropic, Claude Code 환경) | OpenAI GPT / Ollama(로컬·비용 0) | [docs.anthropic.com](https://docs.anthropic.com/) |
| **임베딩** | **VoyageAI** — `voyage-3.5`(기본), `voyage-3-large`(고품질, 32K), `voyage-context-3`(문맥형 청크) | 도메인: `voyage-finance-2`·`voyage-law-2` / OpenAI `text-embedding-3` / `BAAI/bge-m3`·`e5` | [docs.voyageai.com](https://docs.voyageai.com/docs/embeddings) |
| **GraphRAG 프레임워크** | **LightRAG** (HKUDS, 본 과정 메인) — 5 쿼리모드 `naive/local/global/hybrid/mix` + WebUI | Microsoft GraphRAG(개념·비교용) | [github.com/HKUDS/LightRAG](https://github.com/HKUDS/LightRAG) |
| **그래프 DB** | **Neo4j** 5.26 LTS 또는 2025+ CalVer + **GDS**(PageRank·Leiden) + 네이티브 벡터·풀텍스트 인덱스 | Memgraph(LightRAG 호환) | [neo4j.com/docs](https://neo4j.com/docs/) |
| **문서 파싱** | **Docling** / **MinerU** / **RAG-Anything** 비교 | MinerU = 한국어 OCR 강점, RAG-Anything = 멀티모달 | 각 GitHub repo |
| **구조적 출력·검증** | **Pydantic**(LLM Structured Output) + **SHACL/pyshacl**(그래프 제약) | instructor / `with_structured_output` | [pydantic.dev](https://docs.pydantic.dev/), [w3.org/TR/shacl](https://www.w3.org/TR/shacl/) |
| **평가** | **Ragas**(KG 기반 testset 생성 + faithfulness·context recall·tool-call accuracy) + 그래프 특화 지표 | DeepEval | [docs.ragas.io](https://docs.ragas.io/) |
| **관측성** | **Langfuse**(trace·cost·latency·LLM-as-judge) | LangSmith | [langfuse.com](https://langfuse.com/docs) |
| **에이전트** | Anthropic tool-use 루프(기본·경량) / **LangGraph**(분기·루프·체크포인트) | — | [docs.langchain.com](https://docs.langchain.com/) |
| **환경** | Python 3.11+, Docker / Docker Compose, Claude Code | — | — |

### 러닝 코퍼스 (Part 2 전체 공통)

- **무엇**: AI/LLM 기술 문서 — arXiv의 RAG/GraphRAG/에이전트 논문(예: Self-RAG, CRAG, Microsoft GraphRAG) + 프레임워크 공식 docs(LightRAG, LangChain, Neo4j).
- **왜**: ① 대상 개발자에게 친숙, ② **멀티홉·관계·인용·전체 요약** 질문이 자연스럽게 풍부해 GraphRAG의 효과를 체감하기 좋음, ③ 라이선스 부담이 적고 자기참조적(우리가 배우는 도구의 문서를 우리가 그래프로 만든다).
- **규모**: Phase 1에서 약 50–100건으로 시작, Phase가 진행되며 증분 적재로 확장.

> 🔑 **API 키 준비물**: `ANTHROPIC_API_KEY`(Claude), `VOYAGE_API_KEY`(임베딩). 비용 최소화를 원하면 Ollama + `bge-m3`로 대체 가능(각 lesson에 대안 분기 명시).

---

## Phase 0. 오리엔테이션 & 환경 세팅 (3–5일)

지식그래프를 배우기 전에, **기존 RAG가 정확히 어디서 무너지는지**를 눈으로 봐야 동기가 생깁니다. 같은 문서를 주고 멀티홉·관계·전체요약·출처 질문에서 Vector RAG가 틀리는 것을 직접 재현합니다.

### 학습 내용
1. **강의 소개 & 목표** — RAG의 한계에서 3개의 Knowledge Graph Agent까지의 전체 흐름
2. **[데모] 같은 문서, 다른 실패** — 기존 RAG가 무너지는 4가지: 멀티홉 추론, 관계 질문, 전체(global) 요약, 출처·근거
3. **[개념] 언제 GraphRAG를 쓰고, 언제 쓰지 말아야 하는가** — 도입 의사결정 매트릭스(데이터 구조성·질문 유형·비용·유지보수)
4. **[실습] 환경 세팅** — Claude·VoyageAI·LightRAG·Neo4j·Python·Docker 일괄 구성 + 헬스체크

### 핸즈온 ⚒️
"같은 문서, 다른 실패" 노트북 — 작은 코퍼스로 Vector-only RAG를 띄우고 4가지 실패를 재현, 스택 전체(Claude API·Voyage 임베딩·Neo4j 컨테이너·LightRAG) 헬스체크 통과.

### 📚 토픽 목록

| # | 토픽 슬러그 | 핵심 내용 |
|---|------------|----------|
| 01 | `01-why-graphrag-and-setup` | RAG 한계 4종 데모 + GraphRAG 도입 의사결정 매트릭스 + 환경 세팅(Claude·VoyageAI·LightRAG·Neo4j·Docker) + 헬스체크 |

### 자료
- Peng et al., *Graph Retrieval-Augmented Generation: A Survey*, arXiv [2408.08921](https://arxiv.org/abs/2408.08921)
- Microsoft GraphRAG, *From Local to Global*, arXiv [2404.16130](https://arxiv.org/abs/2404.16130)
- [LightRAG GitHub](https://github.com/HKUDS/LightRAG) · [Neo4j Docker 가이드](https://neo4j.com/docs/operations-manual/current/docker/)

---

## Phase 1. LLM Wiki / 소스·프로비넌스 레이어 (1.5주)

그래프를 만들기 전에 **신뢰 가능한 원본 레이어(Source Layer)**가 먼저입니다. 원문을 Agent가 인용할 수 있는 구조(stable ID·source span·provenance)로 정제하고, 이후 모든 Phase의 비교 기준이 될 **Baseline Hybrid RAG**를 세웁니다.

### 학습 내용
1. **[개념] LLM Wiki와 Source Layer** — 파일/폴더를 Agent의 신뢰 가능한 원본으로 만들기
2. 원문 문서 → **Markdown · YAML metadata · WikiLink · tag** 구조
3. **PDF·표·수식 파싱** — Docling · MinerU · RAG-Anything 결과 비교(한국어/수식/표 정확도)
4. **문서 Data Contract** — stable ID · version · source span · ACL · provenance
5. Wiki parser → **JSONL · section-aware chunking · metadata index**
6. **Baseline Hybrid RAG** — Vector + BM25 · 인용 · Golden Question

### 핸즈온 ⚒️
AI/LLM 문서 50건을 LLM Wiki로 변환(Data Contract 준수) → section-aware 청킹 → Vector+BM25 Baseline RAG 구축 → Golden Question 10개로 기준 점수 측정. **이 점수가 Phase 4 GraphRAG와의 A/B 기준선**이 됩니다.

### 📚 토픽 목록

| # | 토픽 슬러그 | 핵심 내용 |
|---|------------|----------|
| 01 | `01-llm-wiki-source-layer` | LLM Wiki / Source Layer 개념, 신뢰 가능한 원본 폴더 설계 |
| 02 | `02-markdown-yaml-wikilink` | 원문 → Markdown · YAML metadata · WikiLink · tag 구조화 |
| 03 | `03-pdf-table-formula-parsing` | Docling · MinerU · RAG-Anything 파싱 결과 비교(표·수식·한국어) |
| 04 | `04-document-data-contract` | stable ID · version · source span · ACL · provenance 설계 |
| 05 | `05-wiki-parser-chunking` | Wiki parser → JSONL · section-aware chunking · metadata index |
| 06 | `06-baseline-hybrid-rag` | Vector + BM25 Hybrid RAG · 인용 · Golden Question(기준선) |

### 자료
- [Docling](https://github.com/docling-project/docling) · [MinerU](https://github.com/opendatalab/MinerU) · [RAG-Anything](https://github.com/HKUDS/RAG-Anything) (arXiv [2510.12323](https://arxiv.org/abs/2510.12323))
- [Pydantic 문서](https://docs.pydantic.dev/) · [VoyageAI 임베딩](https://docs.voyageai.com/docs/embeddings)

---

## Phase 2. Knowledge Graph 설계·추출·정제 (1.5주)

LLM Wiki의 텍스트를 **Entity·Relation·Claim·Event**로 바꿉니다. 핵심은 "추출"이 아니라 **정제** — 같은 개체를 하나로 합치고(Entity Resolution), 근거·시간·수치를 보존하며, 품질 게이트로 쓰레기 유입을 막습니다.

### 학습 내용
1. **[개념] 텍스트가 그래프가 되기까지** — Entity·Relation·Claim·Event·Schema
2. **Competency Question → Graph Schema** 초안 (그래프가 답해야 할 질문에서 스키마 역설계)
3. **Entity 후보 추출** — Structured Output · Pydantic
4. **Relation · Claim · Event 추출** — 근거(source span)·시간·수치까지 보존
5. **Entity Resolution** — alias · coreference · fuzzy · embedding 병합
6. **Relation 정규화 & Event 모델링** — 방향·동의어·n-ary 관계
7. **그래프 품질 게이트 & 증분 적재** — reject queue · MERGE · version · delete · Eval

### 핸즈온 ⚒️
Phase 1 Wiki를 입력으로 받아 Pydantic 스키마 기반 추출 → Entity Resolution → 품질 게이트(reject queue 포함) → 증분 적재까지 도는 **재현 가능한 KG 추출 파이프라인** 완성.

### 📚 토픽 목록

| # | 토픽 슬러그 | 핵심 내용 |
|---|------------|----------|
| 01 | `01-text-to-graph-schema` | Entity·Relation·Claim·Event·Schema 개념 + Competency Question → Schema |
| 02 | `02-entity-extraction-pydantic` | 문서에서 Entity 후보 추출 — Structured Output · Pydantic |
| 03 | `03-relation-claim-event` | Relation·Claim·Event 추출 — 근거·시간·수치 보존 |
| 04 | `04-entity-resolution` | alias · coreference · fuzzy · embedding 병합 |
| 05 | `05-relation-normalization-events` | Relation 정규화 & Event 모델링 — 방향·동의어·n-ary |
| 06 | `06-quality-gate-incremental` | 품질 게이트 & 증분 적재 — reject queue · MERGE · version · delete · Eval |

### 자료
- [Pydantic Structured Output](https://docs.pydantic.dev/) · [Anthropic Tool Use(구조적 추출)](https://docs.anthropic.com/en/docs/build-with-claude/tool-use)
- Graph RAG Survey, arXiv [2408.08921](https://arxiv.org/abs/2408.08921) (Construction 파트)

---

## Phase 3. Neo4j 그래프 데이터 엔지니어링 (1.5주)

추출한 그래프를 **Neo4j**에 실무 수준으로 적재하고 질의합니다. Cypher 멀티홉·경로 질의가 바로 "Vector RAG가 못하던 것"이고, 하이브리드 검색(벡터+풀텍스트+그래프)과 GDS(PageRank·Leiden)로 그래프의 진짜 힘을 봅니다.

### 학습 내용
1. **[개념] Neo4j 실무 구조** — LPG · Transaction · Driver · Index · GDS
2. **연결 · Bulk Ingest** — UNWIND · MERGE · Constraint(중복 방지·idempotent 적재)
3. **Cypher Query** — 패턴 매칭 · 멀티홉 · 경로 · 집계
4. **Vector · Full-text · Graph Hybrid Search in Neo4j** (네이티브 벡터·풀텍스트 인덱스)
5. **EXPLAIN · PROFILE로 Query Tuning** + Read-only Guard(에이전트 안전)
6. **GDS PageRank · Leiden** + Graph Quality Dashboard

### 핸즈온 ⚒️
Phase 2 그래프를 Neo4j에 Bulk Ingest(Constraint 포함) → 멀티홉 Cypher로 "RAG가 틀렸던 질문" 정답 확인 → 벡터+그래프 하이브리드 검색 → GDS로 중심 노드/커뮤니티 추출 + 품질 대시보드.

### 📚 토픽 목록

| # | 토픽 슬러그 | 핵심 내용 |
|---|------------|----------|
| 01 | `01-neo4j-fundamentals` | LPG · Transaction · Python Driver · Index · GDS 개요 |
| 02 | `02-bulk-ingest-merge` | 연결 · Bulk Ingest — UNWIND · MERGE · Constraint |
| 03 | `03-cypher-query` | 패턴 매칭 · 멀티홉 · 경로 · 집계 |
| 04 | `04-hybrid-search-neo4j` | Vector · Full-text · Graph Hybrid Search |
| 05 | `05-query-tuning-readonly-guard` | EXPLAIN · PROFILE 튜닝 + Read-only Guard |
| 06 | `06-gds-pagerank-leiden` | GDS PageRank · Leiden + Graph Quality Dashboard |

### 자료
- [Neo4j 공식 문서](https://neo4j.com/docs/) · [Neo4j Python Driver](https://neo4j.com/docs/python-manual/current/) · [GDS Manual](https://neo4j.com/docs/graph-data-science/current/)
- [Neo4j 벡터 인덱스](https://neo4j.com/docs/cypher-manual/current/indexes/semantic-indexes/vector-indexes/)
- ℹ️ **버전 주의**: Neo4j는 2025년부터 CalVer(YYYY.MM)로 전환. **5.26 LTS** 또는 2025+ CalVer 사용.

---

## Phase 4. GraphRAG 검색 설계 & LightRAG ⭐ (2주)

이 과정의 심장입니다. **그래프를 어떻게 검색에 쓰는가**를 Local/Global/Path/Community 4가지 패턴으로 익히고, 본 과정의 메인 프레임워크 **LightRAG**의 5가지 쿼리 모드를 A/B로 비교합니다. Phase 1 Baseline RAG 점수를 드디어 넘어섭니다.

### 학습 내용
1. **[개념] GraphRAG Method Map** — Local · Global · Path · Community · Memory
2. **Local · Path Retriever** — Entity Linking → Neighborhood → Multi-hop Path
3. **Global Retriever** — Leiden Community · Summary · Map-Reduce(전체 요약 질문)
4. **Vector + Graph Fusion** — Rerank · Context Packing · Token Budget
5. **GraphRAG Q&A A/B** — Vector vs Local vs Global vs Hybrid
6. **[개념] 왜 LightRAG인가** — 본 과정의 Main Framework와 5가지 Query Mode
7. **LightRAG Indexing · WebUI** — `naive`/`local`/`global`/`hybrid`/`mix` A/B
8. **LightRAG + Neo4j 운영** — incremental insert · delete · storage · cache · concurrency

### 핸즈온 ⚒️
동일 코퍼스에 LightRAG 인덱싱 → 5개 쿼리 모드로 Golden Question 응답 비교(WebUI 시각화) → Vector-only(Phase 1) 대비 멀티홉·전체요약 정답률 개선을 정량 확인 → LightRAG 백엔드를 Neo4j로 운영(증분·삭제·동시성).

### 📚 토픽 목록

| # | 토픽 슬러그 | 핵심 내용 |
|---|------------|----------|
| 01 | `01-graphrag-method-map` | Local · Global · Path · Community · Memory 개념 지도 |
| 02 | `02-local-path-retriever` | Entity Linking → Neighborhood → Multi-hop Path |
| 03 | `03-global-retriever` | Leiden Community · Summary · Map-Reduce |
| 04 | `04-vector-graph-fusion` | Rerank · Context Packing · Token Budget |
| 05 | `05-graphrag-qa-ab` | Vector vs Local vs Global vs Hybrid A/B |
| 06 | `06-why-lightrag` | LightRAG Main Framework · 5 Query Mode |
| 07 | `07-lightrag-indexing-webui` | LightRAG Indexing · WebUI · naive/local/global/hybrid/mix A/B |
| 08 | `08-lightrag-neo4j-ops` | incremental insert · delete · storage · cache · concurrency |

### 자료
- [LightRAG GitHub](https://github.com/HKUDS/LightRAG) · [LightRAG API Server·WebUI](https://github.com/HKUDS/LightRAG/blob/main/docs/LightRAG-API-Server.md)
- [Microsoft GraphRAG Docs](https://microsoft.github.io/graphrag/) · *From Local to Global*, arXiv [2404.16130](https://arxiv.org/abs/2404.16130)
- [Awesome-GraphRAG(DEEP-PolyU)](https://github.com/DEEP-PolyU/Awesome-GraphRAG)

---

## Phase 5. Ontology / Semantic Layer & Governance (1주)

그래프가 커지면 "어떤 타입·관계·용어가 허용되는가"를 통제하는 **의미 계층(Semantic Layer)**이 필요합니다. Controlled Vocabulary와 Canonical ID로 alias를 표준 개념에 매핑하고, SHACL 스타일 제약으로 답변 시점에 정책·접근 게이트를 겁니다.

### 학습 내용
1. **[개념] Taxonomy · Vocabulary · Ontology** — Graph Schema와 무엇이 다른가
2. **Entity · Relation Type + Controlled Vocabulary** 설계
3. **Canonical ID · Ontology Alignment** — alias를 표준 개념에 매핑
4. **Constraint Validation** — Pydantic + SHACL-inspired Rule + Reject Reason
5. **Answer-time Semantic · Access · Policy Check** (답변 직전 의미·권한 검증)

### 핸즈온 ⚒️
코퍼스용 경량 온톨로지(Entity/Relation Type + Controlled Vocabulary) 설계 → Canonical ID 매핑 → pyshacl 스타일 제약으로 그래프 검증(reject reason 출력) → 답변 시점 정책 체크 게이트.

### 📚 토픽 목록

| # | 토픽 슬러그 | 핵심 내용 |
|---|------------|----------|
| 01 | `01-taxonomy-vocabulary-ontology` | Taxonomy·Vocabulary·Ontology vs Graph Schema |
| 02 | `02-controlled-vocabulary` | Entity·Relation Type + Controlled Vocabulary 설계 |
| 03 | `03-canonical-id-alignment` | Canonical ID · Ontology Alignment(alias → 표준 개념) |
| 04 | `04-constraint-validation-shacl` | Pydantic + SHACL-inspired Rule + Reject Reason |
| 05 | `05-answer-time-policy-check` | Answer-time Semantic · Access · Policy Check |

### 자료
- [W3C SHACL 명세](https://www.w3.org/TR/shacl/) · [pySHACL](https://github.com/RDFLib/pySHACL)
- [Pydantic 검증](https://docs.pydantic.dev/) · LLM+KG for QA Survey, arXiv [2505.20099](https://arxiv.org/abs/2505.20099)

---

## Phase 6. 평가 · 관측성 · 회귀 테스트 (1주)

"좋아진 것 같다"는 금물입니다. **GraphRAG 개선을 숫자로 입증**하는 안전망을 만듭니다. Ragas Golden Testset, Langfuse 트레이스, 그리고 회귀 게이트로 다음 변경이 점수를 떨어뜨리면 막습니다.

### 학습 내용
1. **[개념] GraphRAG Evaluation Pyramid** — Construction · Retrieval · Generation · Agent
2. **Golden Testset + Ragas + Graph-specific Metrics** (faithfulness·context recall + 그래프 특화)
3. **Langfuse Trace** — 검색 경로 · Tool Call · Cost · Latency 관측
4. **Ablation · A/B · Regression Gate** — GraphRAG 개선을 정량 입증

### 핸즈온 ⚒️
Golden Testset 생성(Ragas) → 검색·생성 지표 측정 → Langfuse로 검색 경로·비용·지연 시각화 → Ablation(그래프 제거 시 점수 하락 확인) → CI에 Regression Gate 연결.

### 📚 토픽 목록

| # | 토픽 슬러그 | 핵심 내용 |
|---|------------|----------|
| 01 | `01-evaluation-pyramid` | Construction·Retrieval·Generation·Agent 평가 계층 |
| 02 | `02-golden-testset-ragas` | Golden Testset + Ragas + Graph-specific Metrics |
| 03 | `03-langfuse-trace` | 검색 경로 · Tool Call · Cost · Latency 관측 |
| 04 | `04-ablation-ab-regression-gate` | Ablation · A/B · Regression Gate |

### 자료
- [Ragas 문서](https://docs.ragas.io/) · [Ragas GitHub](https://github.com/explodinggradients/ragas)
- [Langfuse 문서](https://langfuse.com/docs)

---

## Phase 7. Agent Harness — Agentic GraphRAG ⭐ (2주)

검색을 "호출하는 주체"를 에이전트로 올립니다. 도구(docs_search·graph_query·ontology_check)를 계약(Tool Contract)으로 정의하고, Router·Grader·Query Rewrite로 적응형(Adaptive) / 교정형(Corrective) RAG를 구현합니다. 결과물은 **도메인 중립 Reference Harness** — 캡스톤 3개가 이걸 공유합니다.

### 학습 내용
1. **[개념] Agent Harness** — Workflow와 Agent를 구분, 최소 구조부터
2. **Tool Contract + docs_search Tool**
3. **graph_query Tool** — Template Cypher · Text-to-Cypher · LightRAG
4. **Cypher Safety Guard + ontology_check Tool** (읽기 전용·스키마 검증)
5. **[개념] Adaptive · Corrective Agentic RAG** — Self-RAG · CRAG · Adaptive-RAG에서 가져올 것
6. **Tool Router + Retrieval Grader + Query Rewrite**
7. **Fallback · Retry · Cache · Budget · Stop · Human Checkpoint**
8. **Structured Output · Citation · Audit Trail + 통합 State Graph**

### 핸즈온 ⚒️
도구 4개(docs_search·graph_query·ontology_check·calculator) + Router + Retrieval Grader + Query Rewrite + 예산/중단 가드 + Citation·Audit Trail을 갖춘 **Reference Harness** 완성. Langfuse로 전 과정 추적, Golden set으로 점수 검증.

### 📚 토픽 목록

| # | 토픽 슬러그 | 핵심 내용 |
|---|------------|----------|
| 01 | `01-agent-harness-minimal` | Workflow vs Agent, 최소 구조 + Tool Contract + docs_search |
| 02 | `02-graph-query-tool` | Template Cypher · Text-to-Cypher · LightRAG 도구화 |
| 03 | `03-cypher-safety-ontology-check` | Cypher Safety Guard + ontology_check Tool |
| 04 | `04-adaptive-corrective-rag` | Self-RAG · CRAG · Adaptive-RAG + Router · Grader · Query Rewrite |
| 05 | `05-fallback-budget-checkpoint` | Fallback · Retry · Cache · Budget · Stop · Human Checkpoint |
| 06 | `06-citation-audit-state-graph` | Structured Output · Citation · Audit Trail + 통합 State Graph |

### 자료
- Self-RAG, arXiv [2310.11511](https://arxiv.org/abs/2310.11511) · CRAG, arXiv [2401.15884](https://arxiv.org/abs/2401.15884) · Adaptive-RAG, arXiv [2403.14403](https://arxiv.org/abs/2403.14403)
- [LangGraph Agentic RAG 가이드](https://docs.langchain.com/oss/python/langgraph/agentic-rag) · [Anthropic Tool Use](https://docs.anthropic.com/en/docs/build-with-claude/tool-use)

---

## ⭐ 캡스톤 — 3개 도메인 프로젝트 (각 1주 내외, 총 2.5–3주)

Phase 7의 **Reference Harness 하나**에 도메인 데이터·온톨로지·평가만 갈아 끼워 **완전히 동작하는 서비스 3개**를 따라 만듭니다. 산출물 위치: `course/capstone-<domain>/` (단일 디렉토리, 다수 컴포넌트).

### 캡스톤 1 — 금융: 기업 리서치·리스크
SEC EDGAR 10-K → Financial KG(LightRAG + Neo4j) → 기업 리서치 Agent.

| # | 토픽 | 핵심 |
|---|------|------|
| 01 | 문제 정의 & Baseline | 기업·리스크·경쟁사·재무 멀티홉 질문 |
| 02 | EDGAR Source Layer | HTML · XBRL · 표 · 섹션 · 출처 계약 |
| 03 | Financial KG | LightRAG + Neo4j + FinReflectKG 비교 |
| 04 | 금융 Ontology & Validation | FIBO · 시간 · 통화 · 단위 · 버전 |
| 05 | 기업 리서치 Agent | docs · graph · ontology · calculator · router |
| 06 | Eval | FinanceBench · FinReflectKG MultiHop · Hallucination Slice |

**데이터**: [SEC EDGAR](https://www.sec.gov/edgar/sec-api-documentation) · 임베딩 `voyage-finance-2`

### 캡스톤 2 — 의료: 처방·복약 검토
PrimeKG + DDInter + Synthetic FHIR → 처방 검토 Agent.

| # | 토픽 | 핵심 |
|---|------|------|
| 01 | 문제 정의 & Baseline | 약물·질환·알레르기·중복 처방 |
| 02 | KG 적재 | PrimeKG Subgraph + DDInter + Synthetic FHIR Patient |
| 03 | Terminology Alignment | RxNorm · MONDO 중심 약물·질환 정규화 |
| 04 | 의료 Ontology · Rule · Access Scope | 안전 제약과 최소 권한 |
| 05 | 처방 검토 Agent | `risk_found` / `no_known_risk` / `insufficient_evidence` |
| 06 | Eval | 민감도 · False Negative Review · 출처 · Robustness |

**데이터**: [PrimeKG](https://github.com/mims-harvard/PrimeKG) · [DDInter](http://ddinter.scbdd.com/) · [RxNorm](https://www.nlm.nih.gov/research/umls/rxnorm/) · [MONDO](https://mondo.monarchinitiative.org/)

### 캡스톤 3 — 연구: 문헌 리뷰·Research Harness
OpenAlex + arXiv + S2ORC → Research KG → 문헌 리뷰 Agent.

| # | 토픽 | 핵심 |
|---|------|------|
| 01 | 문제 정의 & Baseline | 방법·데이터셋·결과·인용 계보 멀티홉 |
| 02 | Scholarly Source Layer | OpenAlex · arXiv · S2ORC · 라이선스 · 버전 |
| 03 | LLM Wiki | 논문 → Markdown Research Note · Metadata · WikiLink |
| 04 | Research KG | Paper · Method · Dataset · Metric · Result · Claim · Citation |
| 05 | Research Ontology | 방법 · 태스크 · 데이터셋 · 지표 표준화 |
| 06 | Research Harness | Search → Screen → Extract → Graph → Compare → Brief |
| 07 | Eval & Continuous Update | 인용 정확도 · 계보 · 상충 · 신규 논문 |

**데이터**: [OpenAlex](https://openalex.org/) · [arXiv bulk](https://info.arxiv.org/help/bulk_data/) · [S2ORC](https://github.com/allenai/s2orc)

### 캡스톤 완료 기준 (1줄, 공통 패턴)
```bash
curl http://localhost:8000/chat -d '{"query":"<도메인 멀티홉 질문>","mode":"agent"}'
# → 200 OK + 답변 + 인용 문서/그래프 경로 + Audit Trail이 반환되면 캡스톤 완료
```

---

## Phase 8. 통합 운영 & 향후 로드맵 (0.5–1주)

3개 캡스톤이 증명하듯, **하나의 Reference Harness + 도메인 어댑터**가 핵심 패턴입니다. 이제 이것을 운영합니다.

### 학습 내용
1. **[종합] 하나의 Reference Harness, 세 개의 Domain Adapter** — 공통/가변 부분 분리
2. **[운영] 배포 · 갱신 · 삭제 · 백업** — FastAPI · Docker · Neo4j · LightRAG
3. **[운영] 품질 · 비용 · 보안 Incident Playbook**
4. **[마무리] 현업 적용 로드맵 & 더 알아보기** — GraphRAG에서 Graph Agent까지

### 📚 토픽 목록

| # | 토픽 슬러그 | 핵심 내용 |
|---|------------|----------|
| 01 | `01-reference-harness-adapters` | 하나의 Reference Harness, 세 개의 Domain Adapter 종합 |
| 02 | `02-deploy-update-backup` | 배포 · 갱신 · 삭제 · 백업 (FastAPI · Docker · Neo4j · LightRAG) |
| 03 | `03-incident-playbook` | 품질 · 비용 · 보안 Incident Playbook |
| 04 | `04-roadmap-further-reading` | 현업 적용 로드맵 & 더 알아보기 |

### 자료
- GraphRAG Survey, arXiv [2408.08921](https://arxiv.org/abs/2408.08921) · LLM+KG for QA, arXiv [2505.20099](https://arxiv.org/abs/2505.20099)
- [Awesome-GraphRAG](https://github.com/DEEP-PolyU/Awesome-GraphRAG) (서베이·벤치마크·OSS 살아있는 인덱스)

---

## 📅 주차별 요약 일정 (10–12주)

| 주차 | Phase | 다루는 토픽 |
|-----|-------|-----------|
| 1 | Phase 0 + Phase 1 | `0/01`, `1/01`, `1/02` |
| 2 | Phase 1 | `1/03`, `1/04`, `1/05`, `1/06` (Baseline RAG 완성) |
| 3 | Phase 2 | `2/01`~`2/04` (추출·Entity Resolution) |
| 4 | Phase 2 + Phase 3 | `2/05`, `2/06`, `3/01`, `3/02` |
| 5 | Phase 3 | `3/03`~`3/06` (Cypher·하이브리드·GDS) |
| 6 | Phase 4 | `4/01`~`4/05` (GraphRAG 검색 패턴) |
| 7 | Phase 4 | `4/06`~`4/08` (LightRAG 5모드·Neo4j 운영) |
| 8 | Phase 5 + Phase 6 | `5/01`~`5/05`, `6/01`, `6/02` |
| 9 | Phase 6 + Phase 7 | `6/03`, `6/04`, `7/01`~`7/03` |
| 10 | Phase 7 | `7/04`~`7/06` (Reference Harness 완성) |
| 11 | 캡스톤 | 캡스톤 1(금융) + 캡스톤 2(의료) 착수 |
| 12 | 캡스톤 + Phase 8 | 캡스톤 3(연구) + 통합 운영·로드맵 |

> 학습 속도에 따라 캡스톤은 1개만 깊게 하고 나머지 2개는 차이점 위주로 훑어도 됩니다. **Phase 7 Harness가 같으므로 도메인 어댑터만 바뀝니다.**

---

## 💡 학습 팁

1. **Phase 0의 "RAG 실패 4종"을 꼭 직접 재현하세요.** 동기 없이 그래프를 만들면 지루합니다. 실패를 본 뒤 만들면 모든 단계가 "이걸 고치는 중"이 됩니다.
2. **Baseline 점수(Phase 1)를 버리지 마세요.** Phase 4·6·7의 모든 개선은 이 숫자와 비교해 입증합니다.
3. **추출보다 정제(Entity Resolution·품질 게이트)가 그래프 품질의 90%입니다.** LLM 추출은 쉽고, 같은 개체를 하나로 합치는 것이 어렵습니다.
4. **Cypher를 외우지 마세요.** `EXPLAIN`/`PROFILE`로 질의를 들여다보고, Text-to-Cypher는 항상 Safety Guard(읽기 전용)로 감싸세요.
5. **모르는 것 1개를 끝까지.** "LightRAG `mix` 모드를 Neo4j 백엔드로 띄워 내 코퍼스 질문에 답하기" 같은 작은 목표 하나를 완주하는 게 논문 5편 읽는 것보다 낫습니다.
6. **비용 관리**: Voyage/Claude API 비용이 부담되면 Phase 0~3은 Ollama + `bge-m3`로 진행하고, GraphRAG 효과 비교(Phase 4)에서만 상용 모델을 쓰세요.

---

## 🌐 github.io 배포 고려 (구조만, 셋업은 후속)

본 교육자료는 추후 `github.io` 정적 사이트로 배포할 예정입니다. 이를 위해 **작성 단계부터 다음 컨벤션**을 지킵니다.

```
course/phase-<NN>-<slug>/<NN>-<topic-slug>/
  ├─ lesson.md        # 정적 사이트의 한 페이지 (숫자 prefix가 메뉴 순서)
  ├─ practice/        # Python·노트북·Dockerfile·compose·Cypher
  └─ labs/            # 단계별 핸즈온 명령 + 예상 출력
course/capstone-<domain>/   # 캡스톤 3개 (단일 디렉토리, 다수 컴포넌트)
```

- 각 `lesson.md` = 사이트의 한 페이지. **숫자 prefix(`01-`, `02-`)가 네비게이션 정렬 순서**를 결정합니다.
- 상대 경로 링크(`[다음](../02-.../lesson.md)`)와 이미지(`./img/`)를 사용해 사이트 빌더 전환 시 깨지지 않게 합니다.
- 사이트 빌더(MkDocs Material / Docusaurus 등) 선택·설정·배포는 **교육 자료 본문이 어느 정도 쌓인 뒤** 별도로 진행합니다. **지금은 콘텐츠 작성에 집중합니다.**

---

## 📖 참고 문헌(Source)

**서베이 · 핵심 방법**
- Peng et al., *Graph Retrieval-Augmented Generation: A Survey*, arXiv [2408.08921](https://arxiv.org/abs/2408.08921)
- Edge et al. (Microsoft), *From Local to Global: A Graph RAG Approach*, arXiv [2404.16130](https://arxiv.org/abs/2404.16130)
- *Large Language Models Meet Knowledge Graphs for QA: Synthesis and Opportunities*, arXiv [2505.20099](https://arxiv.org/abs/2505.20099)
- [Awesome-GraphRAG (DEEP-PolyU)](https://github.com/DEEP-PolyU/Awesome-GraphRAG)

**에이전트 패턴**
- Self-RAG, arXiv [2310.11511](https://arxiv.org/abs/2310.11511) · CRAG, arXiv [2401.15884](https://arxiv.org/abs/2401.15884) · Adaptive-RAG, arXiv [2403.14403](https://arxiv.org/abs/2403.14403)

**프레임워크 · 도구**
- [LightRAG](https://github.com/HKUDS/LightRAG) · [Microsoft GraphRAG](https://microsoft.github.io/graphrag/) · [RAG-Anything](https://github.com/HKUDS/RAG-Anything) (arXiv [2510.12323](https://arxiv.org/abs/2510.12323))
- [Neo4j](https://neo4j.com/docs/) · [Neo4j GDS](https://neo4j.com/docs/graph-data-science/current/) · [VoyageAI](https://docs.voyageai.com/docs/embeddings)
- [Docling](https://github.com/docling-project/docling) · [MinerU](https://github.com/opendatalab/MinerU)
- [Ragas](https://docs.ragas.io/) · [Langfuse](https://langfuse.com/docs) · [LangGraph](https://docs.langchain.com/oss/python/langgraph/agentic-rag)
- [Pydantic](https://docs.pydantic.dev/) · [SHACL (W3C)](https://www.w3.org/TR/shacl/) · [pySHACL](https://github.com/RDFLib/pySHACL)

**캡스톤 데이터셋**
- [SEC EDGAR](https://www.sec.gov/edgar/sec-api-documentation) · [PrimeKG](https://github.com/mims-harvard/PrimeKG) · [DDInter](http://ddinter.scbdd.com/) · [RxNorm](https://www.nlm.nih.gov/research/umls/rxnorm/) · [MONDO](https://mondo.monarchinitiative.org/) · [OpenAlex](https://openalex.org/) · [arXiv](https://info.arxiv.org/help/bulk_data/) · [S2ORC](https://github.com/allenai/s2orc)

> 원본 커리큘럼: Fast Campus, *김용담의 에이전트를 위한 지식그래프 바이블: LLM Wiki·GraphRAG·온톨로지·Agent Harness* ([상세](https://fastcampus.co.kr/data_online_knowledgegraph)) — 본 로드맵은 이 커리큘럼의 36개 실습을 Phase 기반 누적 스토리라인으로 재구성하고, 2026년 기준 도구·데이터로 보완했습니다.

---

## 마지막 한마디

지식그래프는 "또 하나의 DB"가 아니라, **RAG가 못 보던 관계·경로·전체 구조를 LLM에게 보여주는 렌즈**입니다. 이 과정은 그 렌즈를 처음부터 끝까지 직접 깎아봅니다 — 원문에서 Wiki로, Wiki에서 그래프로, 그래프에서 검색으로, 검색에서 에이전트로. **Phase 0의 작은 노트북 하나, "RAG가 틀리는 순간"을 재현하는 것부터 오늘 시작**하세요.
