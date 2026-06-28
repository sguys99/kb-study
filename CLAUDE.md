# CLAUDE.md

이 저장소는 **개발자를 위한 지식그래프(Knowledge Graph) + GraphRAG + Agentic RAG 강의자료**를 집필·관리하는 곳입니다. 코드를 운영하는 프로젝트가 아니라, 학습자가 따라 만들 **교육 콘텐츠(레슨 + 실습 + 핸즈온)를 생산**하는 것이 목표입니다.

전체 설계와 커리큘럼은 [docs/study-roadmap.md](docs/study-roadmap.md)가 단일 기준(SSOT)입니다. 작업 전 항상 이 문서의 해당 Phase·토픽을 먼저 확인하세요.

## 핵심 원칙

- **하나의 코퍼스가 단계마다 진화**합니다: 원문 → LLM Wiki → KG → Neo4j → GraphRAG → Agent → 캡스톤. Phase끼리 따로 놀지 않고, 앞 Phase 산출물이 다음 Phase의 입력입니다.
- **모든 토픽은 이론 + 코드 실습 + 핸즈온**을 함께 담습니다. 개념만 설명하고 끝내지 말고, 곧바로 실행 가능한 코드를 붙입니다(실습 비중을 풍부하게).
- **Baseline 기준선을 항상 유지**합니다. Phase 1의 Hybrid RAG 점수가 이후 모든 개선(Phase 4·6·7)의 A/B 비교 기준입니다.
- **추출보다 정제**가 그래프 품질을 좌우합니다(Entity Resolution·품질 게이트).

## 디렉토리 구조 / 산출물 컨벤션

콘텐츠는 다음 구조로 생성합니다. **숫자 prefix가 사이트 네비게이션 정렬 순서**를 결정합니다.

```
course/phase-<NN>-<slug>/<NN>-<topic-slug>/
  ├─ lesson.md        # 이론 + 코드 실습 본문 (= 정적 사이트의 한 페이지)
  ├─ practice/        # Python 스크립트·노트북·Dockerfile·docker-compose.yml·Cypher·매니페스트
  └─ labs/            # 단계별 핸즈온 명령 + 예상 출력
course/capstone-<domain>/   # 캡스톤 3개 (단일 디렉토리, 다수 컴포넌트)
```

- 링크는 **상대 경로**(`[다음](../02-.../lesson.md)`), 이미지는 `./img/`를 사용해 사이트 빌더 전환 시 깨지지 않게 합니다.
- 사이트 빌더(MkDocs Material / Docusaurus 등) 셋업은 콘텐츠가 쌓인 뒤 별도 진행합니다. **지금은 콘텐츠 작성에 집중**합니다.

## lesson.md 작성 표준

각 `lesson.md`는 다음을 반드시 포함합니다.

1. **학습 목표 3개 이상** (상단)
2. **완료 기준 1줄** (예: "`mix` 모드 답변에 인용 문서 3건이 붙고, Vector-only 대비 멀티홉 정답률이 올라가면 완료")
3. **이론 + 코드 실습** (개념 설명 후 곧바로 실행 가능한 코드)
4. **🚨 자주 하는 실수 1–3개** (하단)
5. **출처** (공식 docs/GitHub/논문 URL)
6. **다음 토픽 링크** (마지막 줄)

### 작성 워크플로 (초안 → 윤문)

교육자료는 사람이 쓴 것처럼 읽혀야 합니다. **2단계**로 완성합니다.

1. **초안 작성** — 위 작성 표준에 맞춰 본문과 실습 코드를 작성.
2. **윤문** — `/humanize-korean` 스킬로 윤문해 AI가 쓴 듯한 느낌(번역투·기계적 병렬·접속사 남발·이모지/불릿 과다 등)을 완화.

> ⚠️ **윤문 철칙**: `/humanize-korean`은 **문체·리듬·표현만** 바꾸고 **내용·코드·수치·출처·용어는 한 글자도 건드리지 않습니다.** 코드 블록·명령어·완료 기준·URL은 윤문 대상에서 제외하고, 윤문 후 실습 코드가 그대로인지 반드시 확인합니다.

## 레퍼런스 스택

버전이 빠른 항목은 작성 시점에 재확인하세요.

| 역할 | 기본 선택 | 비고 |
|------|-----------|------|
| LLM | **Claude** (Anthropic) | 대안: OpenAI GPT / Ollama(로컬·비용 0) |
| 임베딩 | **VoyageAI** `voyage-3.5`(기본) | 도메인: `voyage-finance-2`·`voyage-law-2` / 대안 `bge-m3` |
| GraphRAG 프레임워크 | **LightRAG** (메인, 5모드 `naive/local/global/hybrid/mix`) | 개념·비교용 Microsoft GraphRAG |
| 그래프 DB | **Neo4j** 5.26 LTS 또는 2025+ CalVer + GDS | Neo4j는 2025년부터 CalVer(YYYY.MM) |
| 문서 파싱 | **Docling / MinerU / RAG-Anything** 비교 | MinerU=한국어 OCR, RAG-Anything=멀티모달 |
| 구조적 출력·검증 | **Pydantic** + **SHACL/pyshacl** | — |
| 평가 | **Ragas** | 대안 DeepEval |
| 관측성 | **Langfuse** | 대안 LangSmith |
| 에이전트 | Anthropic tool-use 루프(기본) / **LangGraph** | — |
| 환경 | Python 3.11+, Docker / Docker Compose, Claude Code | — |

- **러닝 코퍼스**(Part 2 공통): AI/LLM 기술 문서 — arXiv RAG/GraphRAG 논문 + 프레임워크 docs. Phase 1에서 50–100건으로 시작해 증분 확장.
- **API 키**: `ANTHROPIC_API_KEY`, `VOYAGE_API_KEY`. 비용 최소화 시 Ollama + `bge-m3` 대안 분기를 lesson에 명시.

## Phase 개요 (상세는 study-roadmap.md)

- **Phase 0** 오리엔테이션 & 환경 세팅 — "RAG가 무너지는 4가지 실패" 재현
- **Phase 1** LLM Wiki / Source Layer + Baseline Hybrid RAG (기준선)
- **Phase 2** Knowledge Graph 설계·추출·정제 (Entity Resolution·품질 게이트)
- **Phase 3** Neo4j 그래프 데이터 엔지니어링 (Cypher·하이브리드·GDS)
- **Phase 4** ⭐ GraphRAG 검색 설계 & LightRAG (이 과정의 심장)
- **Phase 5** Ontology / Semantic Layer & Governance
- **Phase 6** 평가 · 관측성 · 회귀 테스트
- **Phase 7** ⭐ Agent Harness — 도메인 중립 Reference Harness
- **캡스톤** 금융(EDGAR) · 의료(PrimeKG) · 연구(OpenAlex) — Harness에 도메인 어댑터만 교체
- **Phase 8** 통합 운영 & 향후 로드맵

## 작업 규칙

- 콘텐츠·주석·리뷰는 **한국어**로 작성합니다.
- 새 토픽을 만들 때는 study-roadmap.md의 토픽 슬러그·번호를 그대로 따릅니다(임의 변경 금지).
- 도구·버전·데이터셋·논문 URL은 study-roadmap.md의 "자료"·"참고 문헌" 섹션과 일치시킵니다.
- 커밋은 이모지 + 컨벤셔널 커밋 컨벤션을 따릅니다(git 히스토리 참고).
