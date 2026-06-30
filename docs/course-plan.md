# 지식그래프 + GraphRAG + Agentic RAG 교육자료 작성 계획

> **기준 문서**: [study-roadmap.md](study-roadmap.md) — 커리큘럼의 Single Source of Truth(SSOT)
> **사용법**: 한 토픽을 진행한 뒤 해당 산출물 체크박스를 `[x]`로 갱신합니다.
> **스킬 연계**: 집필은 [`/kb-course-author`](../.claude/skills/kb-course-author/), 윤문은 [`/humanize-korean`](../.claude/skills/humanize-korean/)로 수행합니다.

---

## 📐 토픽 1개 작성 표준 절차

모든 토픽은 아래 6단계를 그대로 거칩니다. 이 절차는 한 번만 정의하고, 이후 토픽 목록은 체크박스로만 추적합니다.

1. **집필 호출** — `/kb-course-author <Phase/토픽>`을 실행합니다(예: `1/06`, `phase-1 baseline-hybrid-rag`). 스킬이 roadmap의 해당 Phase·토픽과 공유 레퍼런스 키트를 로드하고, 빠르게 바뀌는 버전·API(Neo4j 5.26 LTS · LightRAG · VoyageAI · Ragas 등)만 선별 검증한 뒤 **`kb-agent`** 에이전트로 디스패치합니다.
2. **초안 산출** — `kb-agent`가 `course/phase-<NN>-<slug>/<NN>-<topic-slug>/` 아래에 `lesson.md` 초안 + `practice/`(실행 가능한 코드) + `labs/`(단계별 핸즈온 + 예상 출력)를 표준 템플릿대로 작성하고 정적 검증합니다. **이 단계에서 윤문은 하지 않습니다.**
3. **자동 윤문** — 스킬이 곧바로 `/humanize-korean`으로 `lesson.md` **본문만** 윤문합니다. 코드 블록·명령어·URL·버전·수치·완료 기준·영문 약어·토픽 슬러그는 **보존 대상(한 글자도 불변)**입니다.
4. **보존 검증** — 윤문 전후를 diff로 대조해 보존 대상이 바뀌었으면 롤백합니다. 변경률이 과도하면 경고하거나 중단합니다.
5. **실행검증(학습자)** — 학습자가 `labs/`를 실제로 실행해 동작을 확인한 뒤 해당 체크박스를 갱신합니다.
6. **마무리** — 본 계획서의 체크박스를 `[x]`로 갱신하고 이모지 + 컨벤셔널 커밋으로 기록합니다(예: `:white_check_mark: Phase 1/06 baseline-hybrid-rag 완료`).

> ⚠️ **윤문 철칙**: `/humanize-korean`은 **문체·리듬·표현만** 바꾸고 **내용·코드·수치·출처·용어는 한 글자도 건드리지 않습니다.** 윤문 후 실습 코드가 그대로인지 반드시 확인합니다.

> 💡 **후속 명령**: "이 토픽 다시" → 1단계부터 재진행 / "practice만 보강" → `kb-agent` 재호출(해당 산출물만) / "윤문 다시" → 3–4단계만 재실행.

---

## 📦 토픽별 산출물 5종 (모든 토픽 공통)

각 토픽은 `course/phase-<NN>-<slug>/<NN>-<topic-slug>/` 아래에 다음 5단계를 갖습니다.

| # | 산출물 | 도구/주체 | 내용 |
|---|--------|----------|------|
| 1 | `lesson.md` 초안 | kb-agent | 학습 목표 3개+ · 완료 기준 1줄 · 이론+코드 실습 · 자주 하는 실수 1–3개 · 출처 · 다음 토픽 링크 |
| 2 | `practice/` | kb-agent | Python 스크립트·노트북 · Dockerfile · `docker-compose.yml` · Cypher · 매니페스트 |
| 3 | `labs/` | kb-agent | 단계별 핸즈온 명령 + 예상 출력 |
| 4 | 윤문 | /humanize-korean | `lesson.md` 본문 윤문 (코드·URL·수치·완료 기준 보존) |
| 5 | 실행검증 | 학습자 | 로컬에서 `labs/` 실행 동작 확인 |

---

## Phase 0. 오리엔테이션 & 환경 세팅 (3–5일)

> RAG가 무너지는 4가지 실패를 직접 재현하고 전체 스택 헬스체크. 상세: [study-roadmap.md](study-roadmap.md#phase-0-오리엔테이션--환경-세팅-35일)

- [ ] **01-why-graphrag-and-setup** — RAG 한계 4종 데모 + GraphRAG 도입 의사결정 매트릭스 + 환경 세팅 + 헬스체크
  - [x] lesson.md 초안 (kb-agent)
  - [x] practice/
  - [x] labs/
  - [x] 윤문 (/humanize-korean)
  - [ ] 실행검증 _(학습자)_

---

## Phase 1. LLM Wiki / 소스·프로비넌스 레이어 (1.5주)

> 신뢰 가능한 Source Layer + 이후 모든 비교의 기준선이 될 Baseline Hybrid RAG.

- [ ] **01-llm-wiki-source-layer** — LLM Wiki / Source Layer 개념, 신뢰 가능한 원본 폴더 설계
  - [x] lesson.md 초안 (kb-agent)
  - [x] practice/
  - [x] labs/
  - [x] 윤문 (/humanize-korean)
  - [ ] 실행검증 _(학습자)_
- [ ] **02-markdown-yaml-wikilink** — 원문 → Markdown · YAML metadata · WikiLink · tag 구조화
  - [x] lesson.md 초안 (kb-agent)
  - [x] practice/
  - [x] labs/
  - [x] 윤문 (/humanize-korean)
  - [ ] 실행검증 _(학습자)_
- [ ] **03-pdf-table-formula-parsing** — Docling · MinerU · RAG-Anything 파싱 결과 비교(표·수식·한국어)
  - [x] lesson.md 초안 (kb-agent)
  - [x] practice/
  - [x] labs/
  - [x] 윤문 (/humanize-korean)
  - [ ] 실행검증 _(학습자)_
- [ ] **04-document-data-contract** — stable ID · version · source span · ACL · provenance 설계
  - [x] lesson.md 초안 (kb-agent)
  - [x] practice/
  - [x] labs/
  - [x] 윤문 (/humanize-korean)
  - [ ] 실행검증 _(학습자)_
- [ ] **05-wiki-parser-chunking** — Wiki parser → JSONL · section-aware chunking · metadata index
  - [x] lesson.md 초안 (kb-agent)
  - [x] practice/
  - [x] labs/
  - [x] 윤문 (/humanize-korean)
  - [ ] 실행검증 _(학습자)_
- [ ] **06-baseline-hybrid-rag** — Vector + BM25 Hybrid RAG · 인용 · Golden Question(기준선)
  - [x] lesson.md 초안 (kb-agent)
  - [x] practice/
  - [x] labs/
  - [x] 윤문 (/humanize-korean)
  - [ ] 실행검증 _(학습자)_

---

## Phase 2. Knowledge Graph 설계·추출·정제 (1.5주)

> 추출이 아니라 정제가 그래프 품질을 좌우 — Entity Resolution · 품질 게이트.

- [ ] **01-text-to-graph-schema** — Entity·Relation·Claim·Event·Schema 개념 + Competency Question → Schema
  - [x] lesson.md 초안 (kb-agent)
  - [x] practice/
  - [x] labs/
  - [x] 윤문 (/humanize-korean)
  - [ ] 실행검증 _(학습자)_
- [ ] **02-entity-extraction-pydantic** — 문서에서 Entity 후보 추출 — Structured Output · Pydantic
  - [x] lesson.md 초안 (kb-agent)
  - [x] practice/
  - [x] labs/
  - [x] 윤문 (/humanize-korean)
  - [ ] 실행검증 _(학습자)_
- [ ] **03-relation-claim-event** — Relation·Claim·Event 추출 — 근거·시간·수치 보존
  - [x] lesson.md 초안 (kb-agent)
  - [x] practice/
  - [x] labs/
  - [x] 윤문 (/humanize-korean)
  - [ ] 실행검증 _(학습자)_
- [ ] **04-entity-resolution** — alias · coreference · fuzzy · embedding 병합
  - [x] lesson.md 초안 (kb-agent)
  - [x] practice/
  - [x] labs/
  - [x] 윤문 (/humanize-korean)
  - [ ] 실행검증 _(학습자)_
- [ ] **05-relation-normalization-events** — Relation 정규화 & Event 모델링 — 방향·동의어·n-ary
  - [x] lesson.md 초안 (kb-agent)
  - [x] practice/
  - [x] labs/
  - [x] 윤문 (/humanize-korean)
  - [ ] 실행검증 _(학습자)_
- [ ] **06-quality-gate-incremental** — 품질 게이트 & 증분 적재 — reject queue · MERGE · version · delete · Eval
  - [x] lesson.md 초안 (kb-agent)
  - [x] practice/
  - [x] labs/
  - [x] 윤문 (/humanize-korean)
  - [ ] 실행검증 _(학습자)_

---

## Phase 3. Neo4j 그래프 데이터 엔지니어링 (1.5주)

> 추출한 그래프를 Neo4j에 실무 수준으로 적재 — Cypher 멀티홉 · 하이브리드 검색 · GDS.

- [ ] **01-neo4j-fundamentals** — LPG · Transaction · Python Driver · Index · GDS 개요
  - [x] lesson.md 초안 (kb-agent)
  - [x] practice/
  - [x] labs/
  - [x] 윤문 (/humanize-korean)
  - [ ] 실행검증 _(학습자)_
- [ ] **02-bulk-ingest-merge** — 연결 · Bulk Ingest — UNWIND · MERGE · Constraint
  - [x] lesson.md 초안 (kb-agent)
  - [x] practice/
  - [x] labs/
  - [x] 윤문 (/humanize-korean)
  - [ ] 실행검증 _(학습자)_
- [ ] **03-cypher-query** — 패턴 매칭 · 멀티홉 · 경로 · 집계
  - [x] lesson.md 초안 (kb-agent)
  - [x] practice/
  - [x] labs/
  - [x] 윤문 (/humanize-korean)
  - [ ] 실행검증 _(학습자)_
- [ ] **04-hybrid-search-neo4j** — Vector · Full-text · Graph Hybrid Search
  - [x] lesson.md 초안 (kb-agent)
  - [x] practice/
  - [x] labs/
  - [x] 윤문 (/humanize-korean)
  - [ ] 실행검증 _(학습자)_
- [ ] **05-query-tuning-readonly-guard** — EXPLAIN · PROFILE 튜닝 + Read-only Guard
  - [x] lesson.md 초안 (kb-agent)
  - [x] practice/
  - [x] labs/
  - [x] 윤문 (/humanize-korean)
  - [ ] 실행검증 _(학습자)_
- [ ] **06-gds-pagerank-leiden** — GDS PageRank · Leiden + Graph Quality Dashboard
  - [x] lesson.md 초안 (kb-agent)
  - [x] practice/
  - [x] labs/
  - [x] 윤문 (/humanize-korean)
  - [ ] 실행검증 _(학습자)_

---

## Phase 4. GraphRAG 검색 설계 & LightRAG ⭐ (2주)

> 이 과정의 심장 — Local/Global/Path/Community 검색 패턴 + LightRAG 5모드 A/B. Phase 1 기준선을 넘어섭니다.

- [ ] **01-graphrag-method-map** — Local · Global · Path · Community · Memory 개념 지도
  - [x] lesson.md 초안 (kb-agent)
  - [x] practice/
  - [x] labs/
  - [x] 윤문 (/humanize-korean)
  - [ ] 실행검증 _(학습자)_
- [ ] **02-local-path-retriever** — Entity Linking → Neighborhood → Multi-hop Path
  - [ ] lesson.md 초안 (kb-agent)
  - [ ] practice/
  - [ ] labs/
  - [ ] 윤문 (/humanize-korean)
  - [ ] 실행검증 _(학습자)_
- [ ] **03-global-retriever** — Leiden Community · Summary · Map-Reduce
  - [ ] lesson.md 초안 (kb-agent)
  - [ ] practice/
  - [ ] labs/
  - [ ] 윤문 (/humanize-korean)
  - [ ] 실행검증 _(학습자)_
- [ ] **04-vector-graph-fusion** — Rerank · Context Packing · Token Budget
  - [ ] lesson.md 초안 (kb-agent)
  - [ ] practice/
  - [ ] labs/
  - [ ] 윤문 (/humanize-korean)
  - [ ] 실행검증 _(학습자)_
- [ ] **05-graphrag-qa-ab** — Vector vs Local vs Global vs Hybrid A/B
  - [ ] lesson.md 초안 (kb-agent)
  - [ ] practice/
  - [ ] labs/
  - [ ] 윤문 (/humanize-korean)
  - [ ] 실행검증 _(학습자)_
- [ ] **06-why-lightrag** — LightRAG Main Framework · 5 Query Mode
  - [ ] lesson.md 초안 (kb-agent)
  - [ ] practice/
  - [ ] labs/
  - [ ] 윤문 (/humanize-korean)
  - [ ] 실행검증 _(학습자)_
- [ ] **07-lightrag-indexing-webui** — LightRAG Indexing · WebUI · naive/local/global/hybrid/mix A/B
  - [ ] lesson.md 초안 (kb-agent)
  - [ ] practice/
  - [ ] labs/
  - [ ] 윤문 (/humanize-korean)
  - [ ] 실행검증 _(학습자)_
- [ ] **08-lightrag-neo4j-ops** — incremental insert · delete · storage · cache · concurrency
  - [ ] lesson.md 초안 (kb-agent)
  - [ ] practice/
  - [ ] labs/
  - [ ] 윤문 (/humanize-korean)
  - [ ] 실행검증 _(학습자)_

---

## Phase 5. Ontology / Semantic Layer & Governance (1주)

> 그래프가 커질 때 허용 타입·관계·용어를 통제하는 의미 계층 — Controlled Vocabulary · Canonical ID · SHACL.

- [ ] **01-taxonomy-vocabulary-ontology** — Taxonomy·Vocabulary·Ontology vs Graph Schema
  - [ ] lesson.md 초안 (kb-agent)
  - [ ] practice/
  - [ ] labs/
  - [ ] 윤문 (/humanize-korean)
  - [ ] 실행검증 _(학습자)_
- [ ] **02-controlled-vocabulary** — Entity·Relation Type + Controlled Vocabulary 설계
  - [ ] lesson.md 초안 (kb-agent)
  - [ ] practice/
  - [ ] labs/
  - [ ] 윤문 (/humanize-korean)
  - [ ] 실행검증 _(학습자)_
- [ ] **03-canonical-id-alignment** — Canonical ID · Ontology Alignment(alias → 표준 개념)
  - [ ] lesson.md 초안 (kb-agent)
  - [ ] practice/
  - [ ] labs/
  - [ ] 윤문 (/humanize-korean)
  - [ ] 실행검증 _(학습자)_
- [ ] **04-constraint-validation-shacl** — Pydantic + SHACL-inspired Rule + Reject Reason
  - [ ] lesson.md 초안 (kb-agent)
  - [ ] practice/
  - [ ] labs/
  - [ ] 윤문 (/humanize-korean)
  - [ ] 실행검증 _(학습자)_
- [ ] **05-answer-time-policy-check** — Answer-time Semantic · Access · Policy Check
  - [ ] lesson.md 초안 (kb-agent)
  - [ ] practice/
  - [ ] labs/
  - [ ] 윤문 (/humanize-korean)
  - [ ] 실행검증 _(학습자)_

---

## Phase 6. 평가 · 관측성 · 회귀 테스트 (1주)

> "좋아진 것 같다"는 금물 — Ragas Golden Testset · Langfuse Trace · Regression Gate로 개선을 숫자로 입증.

- [ ] **01-evaluation-pyramid** — Construction·Retrieval·Generation·Agent 평가 계층
  - [ ] lesson.md 초안 (kb-agent)
  - [ ] practice/
  - [ ] labs/
  - [ ] 윤문 (/humanize-korean)
  - [ ] 실행검증 _(학습자)_
- [ ] **02-golden-testset-ragas** — Golden Testset + Ragas + Graph-specific Metrics
  - [ ] lesson.md 초안 (kb-agent)
  - [ ] practice/
  - [ ] labs/
  - [ ] 윤문 (/humanize-korean)
  - [ ] 실행검증 _(학습자)_
- [ ] **03-langfuse-trace** — 검색 경로 · Tool Call · Cost · Latency 관측
  - [ ] lesson.md 초안 (kb-agent)
  - [ ] practice/
  - [ ] labs/
  - [ ] 윤문 (/humanize-korean)
  - [ ] 실행검증 _(학습자)_
- [ ] **04-ablation-ab-regression-gate** — Ablation · A/B · Regression Gate
  - [ ] lesson.md 초안 (kb-agent)
  - [ ] practice/
  - [ ] labs/
  - [ ] 윤문 (/humanize-korean)
  - [ ] 실행검증 _(학습자)_

---

## Phase 7. Agent Harness — Agentic GraphRAG ⭐ (2주)

> 검색을 호출하는 주체를 에이전트로 — Tool Contract · Router · Grader · Audit Trail. 결과물은 캡스톤 3개가 공유하는 도메인 중립 Reference Harness.

- [ ] **01-agent-harness-minimal** — Workflow vs Agent, 최소 구조 + Tool Contract + docs_search
  - [ ] lesson.md 초안 (kb-agent)
  - [ ] practice/
  - [ ] labs/
  - [ ] 윤문 (/humanize-korean)
  - [ ] 실행검증 _(학습자)_
- [ ] **02-graph-query-tool** — Template Cypher · Text-to-Cypher · LightRAG 도구화
  - [ ] lesson.md 초안 (kb-agent)
  - [ ] practice/
  - [ ] labs/
  - [ ] 윤문 (/humanize-korean)
  - [ ] 실행검증 _(학습자)_
- [ ] **03-cypher-safety-ontology-check** — Cypher Safety Guard + ontology_check Tool
  - [ ] lesson.md 초안 (kb-agent)
  - [ ] practice/
  - [ ] labs/
  - [ ] 윤문 (/humanize-korean)
  - [ ] 실행검증 _(학습자)_
- [ ] **04-adaptive-corrective-rag** — Self-RAG · CRAG · Adaptive-RAG + Router · Grader · Query Rewrite
  - [ ] lesson.md 초안 (kb-agent)
  - [ ] practice/
  - [ ] labs/
  - [ ] 윤문 (/humanize-korean)
  - [ ] 실행검증 _(학습자)_
- [ ] **05-fallback-budget-checkpoint** — Fallback · Retry · Cache · Budget · Stop · Human Checkpoint
  - [ ] lesson.md 초안 (kb-agent)
  - [ ] practice/
  - [ ] labs/
  - [ ] 윤문 (/humanize-korean)
  - [ ] 실행검증 _(학습자)_
- [ ] **06-citation-audit-state-graph** — Structured Output · Citation · Audit Trail + 통합 State Graph
  - [ ] lesson.md 초안 (kb-agent)
  - [ ] practice/
  - [ ] labs/
  - [ ] 윤문 (/humanize-korean)
  - [ ] 실행검증 _(학습자)_

---

## ⭐ 캡스톤 — 3개 도메인 프로젝트 (별도 계획서)

Phase 7의 **Reference Harness 하나**에 도메인 데이터·온톨로지·평가만 갈아 끼워 완전히 동작하는 서비스 3개를 만듭니다.

- **캡스톤 1 — 금융**: SEC EDGAR 10-K → Financial KG → 기업 리서치 Agent (임베딩 `voyage-finance-2`)
- **캡스톤 2 — 의료**: PrimeKG + DDInter + Synthetic FHIR → 처방 검토 Agent
- **캡스톤 3 — 연구**: OpenAlex + arXiv + S2ORC → 문헌 리뷰 Agent

공통 완료 기준(roadmap 인용):
```bash
curl http://localhost:8000/chat -d '{"query":"<도메인 멀티홉 질문>","mode":"agent"}'
# → 200 OK + 답변 + 인용 문서/그래프 경로 + Audit Trail 이 반환되면 캡스톤 완료
```

> 📌 캡스톤의 토픽별 상세 작성 계획은 **별도 계획서 `docs/capstone-plan.md`(추후 작성)**에서 진행합니다. 본 계획서에서는 위 개요와 완료 기준만 명시합니다.

---

## Phase 8. 통합 운영 & 향후 로드맵 (0.5–1주)

> 하나의 Reference Harness + 도메인 어댑터를 운영 — 배포 · 갱신 · 삭제 · 백업 · Incident Playbook.

- [ ] **01-reference-harness-adapters** — 하나의 Reference Harness, 세 개의 Domain Adapter 종합
  - [ ] lesson.md 초안 (kb-agent)
  - [ ] practice/
  - [ ] labs/
  - [ ] 윤문 (/humanize-korean)
  - [ ] 실행검증 _(학습자)_
- [ ] **02-deploy-update-backup** — 배포 · 갱신 · 삭제 · 백업 (FastAPI · Docker · Neo4j · LightRAG)
  - [ ] lesson.md 초안 (kb-agent)
  - [ ] practice/
  - [ ] labs/
  - [ ] 윤문 (/humanize-korean)
  - [ ] 실행검증 _(학습자)_
- [ ] **03-incident-playbook** — 품질 · 비용 · 보안 Incident Playbook
  - [ ] lesson.md 초안 (kb-agent)
  - [ ] practice/
  - [ ] labs/
  - [ ] 윤문 (/humanize-korean)
  - [ ] 실행검증 _(학습자)_
- [ ] **04-roadmap-further-reading** — 현업 적용 로드맵 & 더 알아보기
  - [ ] lesson.md 초안 (kb-agent)
  - [ ] practice/
  - [ ] labs/
  - [ ] 윤문 (/humanize-korean)
  - [ ] 실행검증 _(학습자)_

---

## 📅 권장 진행 순서 (10–12주, study-roadmap 기준)

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

---

## 📌 진행 메모

- 토픽 작성 시 [`/kb-course-author`](../.claude/skills/kb-course-author/) 호출을 권장합니다(상단 "표준 절차" 참고). 작성·윤문 후 본 파일의 체크박스를 `[x]`로 갱신하고 커밋합니다.
- 토픽 슬러그·번호·버전·데이터셋·논문 URL은 [study-roadmap.md](study-roadmap.md)와 일치시킵니다(SSOT). 임의 변경 금지.
- 비용 최소화 시 Phase 0~3은 Ollama + `bge-m3`로 진행하고, GraphRAG 효과 비교(Phase 4)에서만 상용 모델을 씁니다(각 lesson에 대안 분기 명시).
