---
name: kb-course-author
version: "1.0.0"
description: "개발자를 위한 지식그래프(Knowledge Graph)·GraphRAG·Agentic RAG 강의자료를 study-roadmap.md 기준으로 한 토픽씩 집필하는 오케스트레이터 스킬. 토픽 1개를 받아 ① roadmap 해당 Phase/토픽 + 공유 레퍼런스 키트 로드 → ② 빠르게 바뀌는 버전·API 선별 검증 → ③ kb-agent 에이전트로 lesson.md + practice/ + labs/ 초안 집필 → ④ 초안 직후 humanize-korean 자동 윤문 + 코드·URL·수치 보존 검증 → ⑤ 완료기준 점검·경로 보고. 트리거 — \"강의자료 작성\", \"lesson.md 작성\", \"토픽 N 집필\", \"phase N 작성\", \"KG/GraphRAG 강의 만들어\", \"kb-course-author\", \"course author\", \"커리큘럼 자료 생성\", \"0/01 작성\", \"캡스톤 자료 작성\". 후속 — \"이 토픽 다시\", \"practice만 보강\", \"윤문 다시\"도 이 스킬. 단순 오탈자 교정·기존 글 윤문만 필요하면 humanize-korean 직접 사용."
---

# kb-course-author — 지식그래프/GraphRAG/Agentic RAG 강의자료 집필 오케스트레이터 (v1.0)

`docs/study-roadmap.md`(SSOT)를 기준으로 **한 번에 토픽 1개**의 강의자료(`lesson.md` + `practice/` + `labs/`)를 집필한다. 집필은 `kb-agent` 에이전트가, 윤문은 `humanize-korean` 스킬이 맡고, 이 스킬은 둘을 엮어 **일관성·검증·보고**를 책임진다.

> 설계 원칙: 스킬 = 오케스트레이터, `kb-agent` = 집필 워커, `humanize-korean` = 윤문. (humanize-korean 패턴 차용)

## Phase 0: 시작 고지 · 타깃 해석

작업 시작 시 한 줄을 출력한다.

```
kb-course-author v1.0 — 타깃: phase-{N}/{NN} ({topic-slug})
```

### 타깃 해석 규칙
사용자 인자에서 Phase·토픽을 식별한다. 아래 표기를 모두 허용한다.

| 입력 예 | 해석 |
|---------|------|
| `1/06`, `1-06`, `phase 1 토픽 6` | Phase 1, 토픽 06 |
| `0/01`, `phase-0 01` | Phase 0, 토픽 01 |
| 토픽 슬러그(`06-baseline-hybrid-rag`) | roadmap에서 해당 Phase·번호 역추적 |
| `phase 4` (토픽 미지정) | 어느 토픽인지 사용자에게 1회 확인(여러 개면 1개만) |
| 캡스톤(`capstone 금융 03`) | `course/capstone-<domain>/` 산출물 규약 적용 |

- **roadmap의 토픽 슬러그·번호를 그대로 사용한다. 임의 변경·신설 금지.**
- 타깃이 모호하면 추측하지 말고 사용자에게 1회 확인한다.

## Phase 1: 컨텍스트 로드

집필 디스패치 전에 다음을 읽어 기준을 확정한다.

1. **roadmap 해당 섹션** — `docs/study-roadmap.md`에서 타깃 Phase의 "학습 내용 · 핸즈온 · 토픽 목록 · 자료" 발췌. 누적 스토리라인 표(앞 Phase 산출물 → 이 Phase 입력)도 확인.
2. **작성 표준** — 루트 `CLAUDE.md`의 "lesson.md 작성 표준 / 디렉토리 컨벤션".
3. **공유 레퍼런스 키트** (이 스킬 `references/`):
   - [`glossary.md`](references/glossary.md) — 용어 한·영 표기 통일
   - [`style-and-difficulty.md`](references/style-and-difficulty.md) — 대상 독자·난이도·문체
   - [`lesson-template.md`](references/lesson-template.md) — lesson.md 골격
   - [`stack-conventions.md`](references/stack-conventions.md) — 스택·버전·코퍼스·API키·대안
   - [`authoring-checklist.md`](references/authoring-checklist.md) — 품질 게이트
4. **이전 토픽 산출물**(있으면) — 직전 토픽 `lesson.md`를 훑어 용어·난이도·다음 링크 정합성을 맞춘다.

## Phase 2: 선별 검증 (Selective Verification)

**빠르게 바뀌는 항목만** 작성 시점 기준으로 재확인한다. roadmap에 명시된 안정 URL·논문 번호는 그대로 신뢰한다.

검증 대상(해당 토픽에 등장할 때만):
- **Neo4j** 버전(5.26 LTS / CalVer YYYY.MM), GDS 호환
- **LightRAG** 쿼리모드·API 서버·스토리지 백엔드 옵션
- **VoyageAI** 모델명(`voyage-3.5` 등) 유효성
- **Ragas / Langfuse / LangGraph / Pydantic** 의 변경 잦은 API

도구: `context7`(라이브러리 docs) 우선, 필요 시 `WebSearch`/`WebFetch`. arXiv 논문 번호는 roadmap 값을 신뢰하되 의심되면 검색으로 확인. 검증으로 값이 바뀌면 키트(stack-conventions)와 lesson 출처에 반영한다.

## Phase 3: 집필 디스패치 (kb-agent)

`Agent` 도구로 `subagent_type: kb-agent`를 1회 호출한다. 전달 항목:

```
타깃: phase-{N}/{NN} {topic-slug}
출력 경로: course/phase-<NN>-<slug>/<NN>-<topic-slug>/
roadmap 발췌: <Phase 학습내용·핸즈온·토픽 핵심·자료 URL>
누적 스토리라인: <앞 Phase 산출물 = 이 토픽의 입력 / 이 토픽 산출물 = 다음 입력>
레퍼런스 키트 경로: .claude/skills/kb-course-author/references/{glossary,style-and-difficulty,lesson-template,stack-conventions,authoring-checklist}.md
선별 검증 결과: <버전·API 갱신 사항(있으면)>
지시: lesson.md 초안 + practice/ + labs/ 작성. 윤문은 하지 말 것(스킬이 수행). 코드 정적 검증 후 반환.
```

에이전트는 키트를 직접 읽고, 산출물을 출력 경로에 작성한 뒤 **초안 상태로** 파일 경로 목록과 자가점검을 반환한다.

## Phase 4: 자동 윤문 (humanize-korean)

집필 반환 직후, `lesson.md`의 **산문 부분만** 윤문한다.

1. 윤문 전 `lesson.md`를 백업(메모리 보관 또는 `lesson.draft.md`).
2. `humanize-korean` 스킬을 호출하되 **보존 범위를 명시**한다:
   > 코드블록·명령어·파일경로·URL·수치·버전·완료기준 1줄·영어 약어·토픽 슬러그/번호는 **윤문 대상에서 제외**하고 한 글자도 바꾸지 말 것. 문체·리듬·표현만 자연스러운 한국어로.
3. practice/ 코드 파일과 labs/ 명령은 **윤문하지 않는다**(산문이 아님).

## Phase 5: 보존 검증 (최우선 게이트)

[`authoring-checklist.md`](references/authoring-checklist.md)의 **C. 윤문 후 보존 검증**을 실행한다.

- 윤문 전/후에서 코드블록·명령어·URL·수치·버전·완료기준·영어 약어·슬러그를 1:1 비교(diff).
- **한 글자라도 바뀌었으면 해당 구간만 원문으로 롤백**하고 산문은 윤문본을 유지한다.
- 변경률이 산문 문체 수준을 넘어 비정상적으로 크면 경고하고 재검토.

## Phase 6: 최종 보고

사용자에게 다음을 반환한다.

1. 한 줄 상태: `완료. phase-{N}/{NN} — lesson.md + practice/ + labs/ 작성, 윤문 X% / 보존검증 통과`
2. 작성된 파일 경로 목록
3. 템플릿 6요소 충족 여부(authoring-checklist A)
4. 윤문 변경 요약 + 보존검증 결과(롤백 건수)
5. **완료 기준 1줄 충족 여부** 자가점검
6. 다음 토픽 안내(roadmap 순서상 다음 슬러그)

## 후속 명령

| 사용자 신호 | 처리 |
|---|---|
| "이 토픽 다시" | 같은 타깃으로 Phase 1부터 재실행 |
| "practice만 보강" | kb-agent에 practice/ 범위만 지정해 재호출, lesson 산문 유지 |
| "윤문 다시"·"강도 조정" | 기존 lesson.md 초안 백업으로 Phase 4~5만 재실행 |
| "다음 토픽" | roadmap 순서상 다음 슬러그를 타깃으로 새 실행 |

## 주의 사항

- **roadmap 슬러그·번호 임의 변경 금지.** SSOT는 `docs/study-roadmap.md`.
- **하나의 코퍼스가 단계마다 진화**한다. 토픽 코드는 앞 Phase 산출물을 입력으로 가정한다.
- **이론만 나열 금지.** 개념 직후 실행 가능한 코드(실습 비중 풍부).
- **비용 대안 분기**(Ollama + `bge-m3`)를 상용 API 의존 지점에 명시.
- **콘텐츠·주석·리뷰는 한국어.** 코드 변수·함수명은 영어 관용 허용.
- **윤문은 의미 불변이 철칙.** 코드·수치·출처·완료기준은 보존 대상.

## 참고 자료

- 공유 레퍼런스 키트: [`references/`](references/) (glossary · style-and-difficulty · lesson-template · stack-conventions · authoring-checklist)
- 집필 워커: `kb-agent` 에이전트 (`.claude/agents/docs/kb-agent.md`)
- 윤문: `humanize-korean` 스킬
- 커리큘럼 SSOT: `docs/study-roadmap.md` · 프로젝트 규약: `CLAUDE.md`
