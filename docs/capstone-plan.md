# 캡스톤 강의 자료 작성 계획 — 3개 도메인 프로젝트

> **기준 문서**: [study-roadmap.md](study-roadmap.md#-캡스톤--3개-도메인-프로젝트-각-1주-내외-총-253주) (커리큘럼 SSOT), [course-plan.md](course-plan.md) (토픽 진행 체크리스트)
> **작성 스킬**: [`/kb-course-author`](../.claude/skills/kb-course-author/) (집필) · [`/humanize-korean`](../.claude/skills/humanize-korean/) (윤문)
> **작성일**: 2026-07-02
> **사용법**: 캡스톤 작성을 진행하며 본 문서의 체크박스를 `[x]`로 갱신해 현황을 추적합니다. 토픽 단위 진행은 [course-plan.md](course-plan.md) §캡스톤과 함께 운용합니다.

---

## 1. Context — 왜 별도 계획서가 필요한가

[course-plan.md](course-plan.md) §"⭐ 캡스톤 — 3개 도메인 프로젝트"는 개요와 공통 완료 기준만 담고, 토픽별 산출물 5종(`lesson.md` 초안 · `practice/` · `labs/` · 윤문 · 실행검증) 작성 계획이 없습니다(course-plan.md가 본 계획서를 "추후 작성"으로 명시).

캡스톤은 다른 Phase와 달리 **단일 토픽이 아니라 3개 도메인 × 6~7 토픽(총 19 토픽)** 규모입니다. 세 도메인은 **Phase 7의 Reference Harness 하나를 공유**하고, 도메인 **데이터 · 온톨로지 · 평가만 갈아 끼웁니다**. 따라서 course-plan.md의 체크박스만으로는 추적이 어렵고, 누가 보더라도 같은 결과물을 만들 수 있도록 **디렉토리 구조 / 토픽별 산출물 / 재사용 자산 매핑 / 검증 시나리오**를 별도 문서로 명시합니다.

본 계획서는 이 모든 항목에 체크박스를 달아 **현황을 한 화면에서 파악**할 수 있게 합니다.

---

## 2. 결정 사항 (사용자 승인 완료, 2026-07-02)

| 항목 | 결정 |
|------|------|
| 집필 깊이 | **3개 캡스톤 모두 동일 깊이로 풀 집필** (19 토픽 전체, 축약 없음) |
| 디렉토리 구조 | **도메인별 디렉토리 + 토픽별 하위폴더** — `course/capstone-<domain>/<NN>-<topic>/{lesson.md, practice/, labs/}` (기존 Phase 컨벤션 100% 일치). 공용 `harness/`·`data/`는 도메인 디렉토리 안 별도 폴더 |
| 데이터셋 취급 | **소형 샘플 동봉 + 전체 fetch 스크립트** — 저장소엔 소량 샘플만 커밋(10-K 3~5건, PrimeKG subgraph 등), 전체는 `fetch_*.py`/문서로 안내 |
| 집필 스킬 | **`/kb-course-author`** (토픽 1개 단위 호출 → kb-agent 집필 → humanize-korean 윤문) |
| 슬러그·데이터 URL | [study-roadmap.md](study-roadmap.md) §캡스톤을 SSOT로 그대로 사용(임의 변경 금지) |

---

## 3. 공통 아키텍처 — Reference Harness 1개 + Domain Adapter 3개

Phase 7에서 만든 **도메인 중립 Reference Harness**(Tool Contract · Router · Grader · Fallback · Citation · Audit Trail)는 세 캡스톤에서 **골격 그대로** 재사용합니다. 도메인마다 바뀌는 것은 아래 3 요소뿐입니다.

```
                       ┌──────────────────────────────────────────┐
                       │   Reference Harness (Phase 7, 불변)        │
                       │   Tool Contract · Router · Grader ·        │
                       │   Query Rewrite · Fallback · Budget ·      │
                       │   Citation · Audit Trail · State Graph      │
                       └───────────────┬──────────────────────────┘
                                       │  도메인 어댑터만 교체
             ┌─────────────────────────┼─────────────────────────┐
             ▼                         ▼                         ▼
     ┌───────────────┐        ┌───────────────┐        ┌───────────────┐
     │ 금융 Adapter   │        │ 의료 Adapter   │        │ 연구 Adapter   │
     │ ① 데이터       │        │ ① 데이터       │        │ ① 데이터       │
     │  EDGAR 10-K    │        │  PrimeKG·DDInter│        │  OpenAlex·arXiv│
     │ ② 온톨로지     │        │ ② 온톨로지     │        │ ② 온톨로지     │
     │  FIBO          │        │  RxNorm·MONDO  │        │  Method·Task   │
     │ ③ 평가         │        │ ③ 평가         │        │ ③ 평가         │
     │  FinanceBench  │        │  민감도·FN     │        │  인용 정확도   │
     └───────────────┘        └───────────────┘        └───────────────┘
```

**교체되는 3 요소**: ① 데이터(Source Layer) · ② 온톨로지/Semantic Layer · ③ 평가(Golden Testset·Metric).
**불변인 골격**: 도구 계약, 라우터/그레이더, 인용·감사 추적, State Graph — Phase 7 산출물을 `harness/`로 이식.

---

## 4. 디렉토리 구조 (산출물 체크리스트)

세 도메인이 **동일 레이아웃**을 씁니다. 아래는 `capstone-finance` 예시이며 의료·연구도 같은 골격입니다.

```
course/capstone-finance/
├─ README.md                     # 도메인 개요 + 아키텍처 + 토픽 인덱스
├─ harness/                      # Phase 7 Reference Harness 이식 (도메인 공통)
│  ├─ tools.py  router.py  grader.py  audit.py  state_graph.py
│  └─ adapter_finance.py         # 도메인 어댑터(데이터·온톨로지·평가 연결)
├─ data/
│  ├─ samples/                   # 소형 샘플만 커밋 (10-K 3~5건 등)
│  └─ fetch_edgar.py             # 전체 데이터 fetch 스크립트
├─ 01-problem-baseline/
│  ├─ lesson.md   practice/   labs/
├─ 02-edgar-source-layer/  …  06-eval-financebench/
```

- [ ] `course/capstone-finance/README.md` — 개요·아키텍처·토픽 인덱스
- [ ] `course/capstone-finance/harness/` — Phase 7 이식 + `adapter_finance.py`
- [ ] `course/capstone-finance/data/` — `samples/` + `fetch_edgar.py`
- [ ] `course/capstone-medical/README.md` · `harness/` · `data/` (+ `fetch_primekg.py`)
- [ ] `course/capstone-research/README.md` · `harness/` · `data/` (+ `fetch_openalex.py`)

> 토픽별 `{lesson.md, practice/, labs/}` 체크박스는 §7~§9에 도메인별로 배치합니다.

---

## 5. 산출물 5종 규약 (모든 토픽 공통)

캡스톤 토픽도 다른 Phase 토픽과 동일하게 산출물 5종을 만족합니다([course-plan.md](course-plan.md) §"토픽별 산출물 5종" 준용).

| # | 산출물 | 도구/주체 | 내용 |
|---|--------|----------|------|
| 1 | `lesson.md` 초안 | kb-agent | 학습 목표 3개+ · 완료 기준 1줄 · 이론+코드 실습 · 자주 하는 실수 1–3개 · 출처 · 다음 토픽 링크 |
| 2 | `practice/` | kb-agent | Python 스크립트·노트북 · Dockerfile · `docker-compose.yml` · Cypher · 매니페스트 |
| 3 | `labs/` | kb-agent | 단계별 핸즈온 명령 + 예상 출력 |
| 4 | 윤문 | /humanize-korean | `lesson.md` 본문 윤문 (코드·URL·수치·완료 기준·슬러그 보존) |
| 5 | 실행검증 | 학습자 | 로컬에서 `labs/` 실행 동작 확인 |

---

## 6. 캡스톤 1 — 금융: 기업 리서치·리스크

> SEC EDGAR 10-K → Financial KG(LightRAG + Neo4j) → 기업 리서치 Agent. 임베딩 `voyage-finance-2`.
> **데이터**: [SEC EDGAR](https://www.sec.gov/edgar/sec-api-documentation)

- [ ] **01-problem-baseline** — 기업·리스크·경쟁사·재무 멀티홉 질문 + Baseline
  - [ ] lesson.md 초안 (kb-agent)
  - [ ] practice/
  - [ ] labs/
  - [ ] 윤문 (/humanize-korean)
  - [ ] 실행검증 _(학습자)_
- [ ] **02-edgar-source-layer** — HTML · XBRL · 표 · 섹션 · 출처 계약
  - [ ] lesson.md 초안 (kb-agent)
  - [ ] practice/
  - [ ] labs/
  - [ ] 윤문 (/humanize-korean)
  - [ ] 실행검증 _(학습자)_
- [ ] **03-financial-kg** — LightRAG + Neo4j + FinReflectKG 비교
  - [ ] lesson.md 초안 (kb-agent)
  - [ ] practice/
  - [ ] labs/
  - [ ] 윤문 (/humanize-korean)
  - [ ] 실행검증 _(학습자)_
- [ ] **04-finance-ontology-validation** — FIBO · 시간 · 통화 · 단위 · 버전
  - [ ] lesson.md 초안 (kb-agent)
  - [ ] practice/
  - [ ] labs/
  - [ ] 윤문 (/humanize-korean)
  - [ ] 실행검증 _(학습자)_
- [ ] **05-research-agent** — docs · graph · ontology · calculator · router
  - [ ] lesson.md 초안 (kb-agent)
  - [ ] practice/
  - [ ] labs/
  - [ ] 윤문 (/humanize-korean)
  - [ ] 실행검증 _(학습자)_
- [ ] **06-eval-financebench** — FinanceBench · FinReflectKG MultiHop · Hallucination Slice
  - [ ] lesson.md 초안 (kb-agent)
  - [ ] practice/
  - [ ] labs/
  - [ ] 윤문 (/humanize-korean)
  - [ ] 실행검증 _(학습자)_

---

## 7. 캡스톤 2 — 의료: 처방·복약 검토

> PrimeKG + DDInter + Synthetic FHIR → 처방 검토 Agent.
> **데이터**: [PrimeKG](https://github.com/mims-harvard/PrimeKG) · [DDInter](http://ddinter.scbdd.com/) · [RxNorm](https://www.nlm.nih.gov/research/umls/rxnorm/) · [MONDO](https://mondo.monarchinitiative.org/)

- [ ] **01-problem-baseline** — 약물·질환·알레르기·중복 처방
  - [ ] lesson.md 초안 (kb-agent)
  - [ ] practice/
  - [ ] labs/
  - [ ] 윤문 (/humanize-korean)
  - [ ] 실행검증 _(학습자)_
- [ ] **02-kg-ingest-primekg** — PrimeKG Subgraph + DDInter + Synthetic FHIR Patient
  - [ ] lesson.md 초안 (kb-agent)
  - [ ] practice/
  - [ ] labs/
  - [ ] 윤문 (/humanize-korean)
  - [ ] 실행검증 _(학습자)_
- [ ] **03-terminology-alignment** — RxNorm · MONDO 중심 약물·질환 정규화
  - [ ] lesson.md 초안 (kb-agent)
  - [ ] practice/
  - [ ] labs/
  - [ ] 윤문 (/humanize-korean)
  - [ ] 실행검증 _(학습자)_
- [ ] **04-medical-ontology-rule-access** — 안전 제약과 최소 권한
  - [ ] lesson.md 초안 (kb-agent)
  - [ ] practice/
  - [ ] labs/
  - [ ] 윤문 (/humanize-korean)
  - [ ] 실행검증 _(학습자)_
- [ ] **05-prescription-review-agent** — `risk_found` / `no_known_risk` / `insufficient_evidence`
  - [ ] lesson.md 초안 (kb-agent)
  - [ ] practice/
  - [ ] labs/
  - [ ] 윤문 (/humanize-korean)
  - [ ] 실행검증 _(학습자)_
- [ ] **06-eval-sensitivity** — 민감도 · False Negative Review · 출처 · Robustness
  - [ ] lesson.md 초안 (kb-agent)
  - [ ] practice/
  - [ ] labs/
  - [ ] 윤문 (/humanize-korean)
  - [ ] 실행검증 _(학습자)_

---

## 8. 캡스톤 3 — 연구: 문헌 리뷰·Research Harness

> OpenAlex + arXiv + S2ORC → Research KG → 문헌 리뷰 Agent.
> **데이터**: [OpenAlex](https://openalex.org/) · [arXiv bulk](https://info.arxiv.org/help/bulk_data/) · [S2ORC](https://github.com/allenai/s2orc)

- [ ] **01-problem-baseline** — 방법·데이터셋·결과·인용 계보 멀티홉
  - [ ] lesson.md 초안 (kb-agent)
  - [ ] practice/
  - [ ] labs/
  - [ ] 윤문 (/humanize-korean)
  - [ ] 실행검증 _(학습자)_
- [ ] **02-scholarly-source-layer** — OpenAlex · arXiv · S2ORC · 라이선스 · 버전
  - [ ] lesson.md 초안 (kb-agent)
  - [ ] practice/
  - [ ] labs/
  - [ ] 윤문 (/humanize-korean)
  - [ ] 실행검증 _(학습자)_
- [ ] **03-llm-wiki-research-note** — 논문 → Markdown Research Note · Metadata · WikiLink
  - [ ] lesson.md 초안 (kb-agent)
  - [ ] practice/
  - [ ] labs/
  - [ ] 윤문 (/humanize-korean)
  - [ ] 실행검증 _(학습자)_
- [ ] **04-research-kg** — Paper · Method · Dataset · Metric · Result · Claim · Citation
  - [ ] lesson.md 초안 (kb-agent)
  - [ ] practice/
  - [ ] labs/
  - [ ] 윤문 (/humanize-korean)
  - [ ] 실행검증 _(학습자)_
- [ ] **05-research-ontology** — 방법 · 태스크 · 데이터셋 · 지표 표준화
  - [ ] lesson.md 초안 (kb-agent)
  - [ ] practice/
  - [ ] labs/
  - [ ] 윤문 (/humanize-korean)
  - [ ] 실행검증 _(학습자)_
- [ ] **06-research-harness** — Search → Screen → Extract → Graph → Compare → Brief
  - [ ] lesson.md 초안 (kb-agent)
  - [ ] practice/
  - [ ] labs/
  - [ ] 윤문 (/humanize-korean)
  - [ ] 실행검증 _(학습자)_
- [ ] **07-eval-continuous-update** — 인용 정확도 · 계보 · 상충 · 신규 논문
  - [ ] lesson.md 초안 (kb-agent)
  - [ ] practice/
  - [ ] labs/
  - [ ] 윤문 (/humanize-korean)
  - [ ] 실행검증 _(학습자)_

---

## 9. 재사용 정책 (어디서 무엇을 가져오는가)

캡스톤은 새로 만드는 코드를 최소화하고, Phase 1~7 산출물을 도메인 데이터로만 갈아 끼웁니다.

| 재사용 원본 (Phase) | 캡스톤에서의 역할 | 도메인별 교체 지점 |
|---------------------|-------------------|--------------------|
| **Phase 1** Source Layer / 파싱·청킹·Data Contract | 도메인 Source Layer | 금융=EDGAR HTML·XBRL / 의료=FHIR·PrimeKG / 연구=OpenAlex·arXiv |
| **Phase 2** KG 추출·Entity Resolution·품질 게이트 | 도메인 KG 구축 | 엔티티·관계 타입만 도메인화 |
| **Phase 3** Neo4j 적재·Cypher·하이브리드 검색 | 그래프 저장·질의 | 스키마·인덱스만 교체 |
| **Phase 4** LightRAG 5모드·Vector-Graph 융합 | GraphRAG 검색 | 인덱싱 코퍼스만 교체 |
| **Phase 5** Ontology·Controlled Vocabulary·SHACL | 도메인 온톨로지 | 금융=FIBO / 의료=RxNorm·MONDO / 연구=Method·Task |
| **Phase 6** Ragas Golden Testset·Langfuse·Regression Gate | 도메인 평가 | 금융=FinanceBench / 의료=민감도·FN / 연구=인용 정확도 |
| **Phase 7** Reference Harness (Tool·Router·Grader·Audit) | 에이전트 골격 (불변) | `adapter_<domain>.py`만 신규 |

**원칙**: 이식한 자산은 상단에 출처 주석(`# from course/phase-07-agent-harness/...`)을 답니다. lesson.md에서도 "Phase N에서 익힌 ~를 그대로 사용한다"고 명시해 학습 누적성을 강조합니다.

---

## 10. 데이터셋 취급 (소형 샘플 + 전체 fetch)

저장소에는 **소형 샘플만 커밋**하고, 전체 데이터는 `data/fetch_*.py`로 내려받습니다. 대용량 원본은 커밋 금지(`.gitignore`).

| 도메인 | 샘플 규모(커밋) | 전체 fetch | 키/제약 |
|--------|-----------------|-----------|---------|
| 금융 | 10-K 3~5건 (섹션 발췌) | `fetch_edgar.py` | SEC EDGAR `User-Agent` 헤더 필수, `VOYAGE_API_KEY`(`voyage-finance-2`) |
| 의료 | PrimeKG subgraph + DDInter 일부 + Synthetic FHIR 환자 소수 | `fetch_primekg.py` | PrimeKG/DDInter 라이선스 확인, RxNorm·MONDO 매핑 파일 |
| 연구 | OpenAlex·arXiv 메타 수십 건 + S2ORC 발췌 | `fetch_openalex.py` | OpenAlex `mailto` polite pool, arXiv bulk 이용약관 |

> ⚠️ 비용 최소화 분기: 임베딩은 상용(`voyage-*`) 대신 `bge-m3`, LLM은 Ollama 로컬로 대체 가능 — 각 lesson에 대안 명시.

---

## 11. 검증 시나리오

**공통 완료 기준** (roadmap 인용, 3 도메인 동일 패턴):

```bash
curl http://localhost:8000/chat -d '{"query":"<도메인 멀티홉 질문>","mode":"agent"}'
# → 200 OK + 답변 + 인용 문서/그래프 경로 + Audit Trail 이 반환되면 캡스톤 완료
```

도메인별 대표 멀티홉 질문(검증용):

- [ ] **금융**: "A사의 최대 리스크 요인이 경쟁사 B사의 어떤 사업 부문과 연결되는가?" → 인용 10-K 섹션 + 그래프 경로
- [ ] **의료**: "환자의 현재 복용 약물과 신규 처방약 사이에 상호작용/중복 위험이 있는가?" → `risk_found`/`no_known_risk`/`insufficient_evidence` + 근거
- [ ] **연구**: "이 방법론을 처음 제안한 논문과 이후 개선 계보, 상충하는 결과는?" → 인용 계보 + 상충 표

---

## 12. 작성 품질 체크리스트 (kb-course-author 표준 + 캡스톤 특화)

각 토픽 완료 시 점검:

- [ ] 학습 목표 3개+ 가 lesson.md 상단에 명시
- [ ] 완료 기준 1줄 명시
- [ ] 이론 뒤에 곧바로 실행 가능한 코드 실습
- [ ] 🚨 자주 하는 실수 1~3개 하단 배치
- [ ] 출처(공식 docs·GitHub·논문 URL) + 다음 토픽 링크
- [ ] **(캡스톤 특화)** Phase 1~7 자산 이식 시 출처 주석 명시
- [ ] **(캡스톤 특화)** 대용량 데이터는 샘플만 커밋 + `fetch_*.py` 분리, `.gitignore` 확인
- [ ] **(캡스톤 특화)** Harness 골격 불변 — `adapter_<domain>.py`만 도메인화했는지
- [ ] **(캡스톤 특화)** 공통 완료 기준 `curl` 시나리오가 실제로 200 + 인용 + Audit Trail 반환

---

## 13. 위험 / 주의사항

- [ ] **외부 데이터 라이선스**: PrimeKG·DDInter·S2ORC·EDGAR 각 이용약관 준수, 재배포 조건 확인 후 샘플만 커밋
- [ ] **API 비용·레이트리밋**: SEC EDGAR·OpenAlex polite pool, VoyageAI 비용 — 비용 최소화 분기(Ollama·`bge-m3`)를 lesson에 병기
- [ ] **의료 도메인 안전**: False Negative(위험 누락)가 치명적 — `06-eval-sensitivity`에서 민감도·FN 리뷰를 최우선 지표로. 교육용이며 실제 임상 판단 도구가 아님을 명시
- [ ] **대용량 데이터 커밋 금지**: 전체 코퍼스는 `.gitignore`, 저장소엔 소형 샘플만
- [ ] **Harness 드리프트 방지**: 세 도메인이 Phase 7 골격을 복붙 후 각자 수정하면 일관성 붕괴 — 골격은 이식하되 변경은 `adapter_*.py`로 격리

---

## 14. 단계별(Stage) 진행 계획

토픽은 `/kb-course-author <경로>` 단위로 순차 집필합니다. Stage 완료 시 아래 체크박스를 갱신합니다.

- [ ] **Stage 0 — 공통 준비**
  - [ ] 3 도메인 디렉토리 스캐폴딩 (`capstone-finance/medical/research`)
  - [ ] 공용 `harness/` — Phase 7 Reference Harness 이식
  - [ ] 도메인별 `data/samples/` 소형 샘플 + `fetch_*.py`
  - [ ] `README.md` 3종 (도메인 개요·아키텍처·토픽 인덱스)
- [ ] **Stage 1 — 캡스톤 1(금융) 6 토픽** — `capstone-finance/01`~`06` (§6 체크박스와 동기화)
- [ ] **Stage 2 — 캡스톤 2(의료) 6 토픽** — `capstone-medical/01`~`06` (§7 체크박스와 동기화)
- [ ] **Stage 3 — 캡스톤 3(연구) 7 토픽** — `capstone-research/01`~`07` (§8 체크박스와 동기화)
- [ ] **Stage 4 — 통합 검증·동기화**
  - [ ] 3 도메인 공통 완료 기준 `curl` 시나리오 통과(§11)
  - [ ] [course-plan.md](course-plan.md) §캡스톤 문구·체크박스 갱신
  - [ ] 이모지 + 컨벤셔널 커밋으로 기록

> 💡 학습 속도에 따라 캡스톤 1개만 깊게 하고 나머지는 차이 위주로 훑어도 됩니다 — Phase 7 Harness가 같으므로 도메인 어댑터만 바뀝니다(roadmap).

---

## 15. 핵심 참조 파일 경로

- 로드맵: [study-roadmap.md](study-roadmap.md) §캡스톤 · §Phase 7 · §Phase 1·2·4·5·6
- 진행 체크리스트: [course-plan.md](course-plan.md) §캡스톤
- 양식 참고: [capstone-plan-template](capstone-plan-template) (단일 캡스톤 완성 예시)
- 집필 스킬: `.claude/skills/kb-course-author/`
- 이식 원본: `course/phase-07-agent-harness/` (Harness) · `course/phase-01-source-layer/` · `course/phase-05-ontology-semantic-layer/` · `course/phase-06-evaluation-observability/`

---

## 16. 진행 메모 (작성 중 기록)

> 캡스톤 작성을 진행하며 결정·이슈·이식 시 발견한 차이점을 이 섹션에 누적합니다.

- (2026-07-02) 본 계획서 작성. 3개 풀 집필 / 토픽별 하위폴더 / 소형 샘플+fetch 확정.
