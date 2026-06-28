# 용어집 (Glossary) — 표기 통일표

모든 토픽은 아래 표기를 **그대로** 따른다. 한 강의자료 안에서 같은 개념을 두 가지로 표기하지 않는다.

## 표기 원칙

1. **첫 등장 시 `한글(English)` 병기**, 이후에는 한글 단독 또는 약어 사용. 예: "지식그래프(Knowledge Graph)" → 이후 "지식그래프" 또는 "KG".
2. **영어 약어(RAG·LLM·KG·GDS·API·OCR 등)는 원형 보존**. 한글로 풀어쓰지 않는다.
3. **제품·프레임워크명은 공식 표기 그대로**: LightRAG, Neo4j, VoyageAI, Ragas, Langfuse, Docling, MinerU, Pydantic, SHACL.
4. roadmap "토픽 슬러그"는 **영문 그대로** 인용한다(번역·변경 금지).

## 핵심 용어 (한글 ↔ English ↔ 약어)

| 한글 표기 | English | 약어 | 비고 |
|-----------|---------|------|------|
| 지식그래프 | Knowledge Graph | KG | "지식 그래프" 띄어쓰기 금지, 붙여 씀 |
| 검색 증강 생성 | Retrieval-Augmented Generation | RAG | 약어 우선, 첫 등장만 풀어씀 |
| 그래프 기반 RAG | GraphRAG | — | 한 단어, 붙여 씀 |
| 에이전트형 RAG | Agentic RAG | — | "에이전틱 RAG" 아님 |
| 대규모 언어모델 | Large Language Model | LLM | 약어 우선 |
| 엔티티 | Entity | — | "개체"로 풀어도 되나 첫 등장 후 "엔티티"로 통일 |
| 관계 | Relation | — | 그래프 엣지 의미일 때 "관계" |
| 클레임 | Claim | — | 근거 보존 단위 |
| 이벤트 | Event | — | n-ary 관계 모델링 |
| 엔티티 해소 | Entity Resolution | ER | "개체 해소"와 혼용 금지, "엔티티 해소"로 통일 |
| 정규화 | Normalization | — | 관계·표기 정규화 |
| 스키마 | Schema | — | 그래프 스키마 |
| 온톨로지 | Ontology | — | — |
| 통제 어휘 | Controlled Vocabulary | — | — |
| 표준 식별자 | Canonical ID | — | — |
| 분류체계 | Taxonomy | — | — |
| 능력 질문 | Competency Question | CQ | 스키마 역설계의 출발점 |
| 속성 그래프 | Labeled Property Graph | LPG | Neo4j 데이터 모델 |
| 멀티홉 | multi-hop | — | "다중 홉" 아님, "멀티홉" |
| 하이브리드 검색 | Hybrid Search | — | Vector + BM25 / Vector + Graph |
| 벡터 인덱스 | Vector Index | — | Neo4j 네이티브 |
| 풀텍스트 인덱스 | Full-text Index | — | — |
| 임베딩 | Embedding | — | — |
| 재순위화 | Rerank | — | — |
| 커뮤니티 탐지 | Community Detection | — | Leiden 등 |
| 그래프 데이터 사이언스 | Graph Data Science | GDS | Neo4j 라이브러리 |
| 도구 사용 | Tool Use | — | Anthropic tool-use 루프 |
| 도구 계약 | Tool Contract | — | — |
| 라우터 | Router | — | Tool Router |
| 검색 평가자 | Retrieval Grader | — | — |
| 질의 재작성 | Query Rewrite | — | — |
| 감사 추적 | Audit Trail | — | — |
| 인용 | Citation | — | 출처 표기와 구분 |
| 프로비넌스 | Provenance | — | 출처·근거 추적 메타 |
| 데이터 계약 | Data Contract | — | stable ID·version·source span 등 |
| 기준선 | Baseline | — | Phase 1 Hybrid RAG 점수 |
| 회귀 게이트 | Regression Gate | — | — |
| 골든 질문 | Golden Question | — | 평가용 고정 질문셋 |
| 레퍼런스 하니스 | Reference Harness | — | 도메인 중립 에이전트 골격 |
| 도메인 어댑터 | Domain Adapter | — | 캡스톤 분기 단위 |

## LightRAG 5가지 쿼리 모드 (표기 고정)

코드·표·본문 모두 영문 소문자 그대로 쓴다: `naive`, `local`, `global`, `hybrid`, `mix`.
"로컬 모드/글로벌 모드"처럼 한글로 풀어 쓰지 않는다.

## 자주 틀리는 표기

- ✅ 지식그래프 / ❌ 지식 그래프
- ✅ GraphRAG / ❌ Graph RAG, 그래프RAG
- ✅ 멀티홉 / ❌ 다중 홉, multi hop
- ✅ 엔티티 해소 / ❌ 엔티티 레졸루션, 개체명 통합(첫 등장 외)
- ✅ Neo4j / ❌ Neo4J, neo4j(문장 중)
- ✅ VoyageAI · `voyage-3.5` / ❌ Voyage AI, voyage 3.5
