# CLAUDE.md

Next.js 기반 풀스택 서비스를 빠르게 시작하기 위한 템플릿입니다.
Next.js App Router + TailwindCSS v4 + shadcn/ui 구조를 기본으로 하며, Vercel AI SDK가 미리 통합되어 있습니다.

## 기술 스택

- **Framework**: Next.js 15 (App Router), React 19, TypeScript
- **Styling**: TailwindCSS v4, shadcn/ui (New York, baseColor: zinc)
- **AI/LLM**: Vercel AI SDK (`ai`, `@ai-sdk/anthropic`, `@ai-sdk/openai`)
- **Package manager**: npm
- **Linter/Formatter**: ESLint (next flat config), Prettier (+ prettier-plugin-tailwindcss)
- **Test**: Vitest + React Testing Library (jsdom)
- **Runtime**: Node.js 20+

## 디렉토리 구조

```
.
├── src/                       # 모든 애플리케이션 소스 코드
│   ├── app/                   # Next.js App Router
│   │   ├── layout.tsx
│   │   ├── page.tsx
│   │   ├── globals.css        # Tailwind v4 엔트리 + shadcn CSS 변수
│   │   └── api/
│   │       ├── health/route.ts  # 헬스체크 엔드포인트
│   │       └── chat/route.ts    # Vercel AI SDK 스트리밍 예제
│   ├── components/
│   │   └── ui/                # shadcn/ui 컴포넌트
│   ├── lib/
│   │   ├── utils.ts           # shadcn cn() 유틸
│   │   ├── config.ts          # configs/ 로더 (JSON/텍스트/프롬프트)
│   │   └── paths.ts           # 프로젝트 경로 상수
│   └── __tests__/             # Vitest 테스트
├── public/                    # 정적 자산
├── configs/
│   └── prompts/               # 프롬프트 템플릿
├── data/
│   ├── raw/
│   ├── intermediate/
│   └── processed/
├── docs/                      # 문서 및 PRD 템플릿
└── img/                       # 이미지 자산
```

## 개발 워크플로우

### 환경 설정

```bash
npm install

cp .env.example .env.local
# .env.local 에 ANTHROPIC_API_KEY 또는 OPENAI_API_KEY 입력
```

### 개발 서버

```bash
npm run dev
# http://localhost:3000
```

### 빌드 / 실행

```bash
npm run build
npm run start
```

### 테스트

```bash
npm test           # 1회 실행
npm run test:watch # watch 모드
```

### 린트 / 포맷 / 타입체크

```bash
npm run lint
npm run format
npm run typecheck
```

### Docker

```bash
docker compose up --build
```

## 주요 경로 별칭

`tsconfig.json`에 `@/*` → `./src/*` 별칭이 설정되어 있습니다.

- `@/components/ui/button` → `src/components/ui/button.tsx`
- `@/lib/utils` → `src/lib/utils.ts`
- `@/lib/paths` → `src/lib/paths.ts`

## shadcn/ui 컴포넌트 추가

```bash
npx shadcn@latest add card dialog input
```

설정(`components.json`):
- style: `new-york`
- baseColor: `zinc`
- Tailwind v4 사용 → `tailwind.config`는 빈 문자열

## AI SDK 사용

`src/app/api/chat/route.ts`에 기본 채팅 엔드포인트가 구현되어 있습니다.
`AI_PROVIDER` 환경 변수로 `anthropic` 또는 `openai`를 선택할 수 있습니다.

```bash
curl -X POST http://localhost:3000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"hi"}]}'
```

## Claude 에이전트 목록

`.claude/agents/` 에 프리셋 에이전트가 준비되어 있습니다.

### Dev 에이전트

| 에이전트 | 용도 |
|---------|------|
| `development-planner` | ROADMAP.md 작성 및 개발 계획 수립 |
| `nextjs-app-developer` | Next.js App Router 구조 설계 및 구현 |
| `starter-cleaner` | 스타터킷 보일러플레이트 정리 |
| `ui-markup-specialist` | UI 컴포넌트 마크업 및 스타일링 |
| `code-reviewer` | 코드 리뷰 |

### Docs 에이전트

| 에이전트 | 용도 |
|---------|------|
| `prd-generator` | PRD 문서 생성 |
| `prd-validator` | PRD 기술적 타당성 검증 |

> 참고: `backend-developer` 에이전트는 FastAPI/LangGraph 전용이므로 본 템플릿에서는 사용하지 않습니다.

## 디자인 시스템

프론트엔드 작업(페이지/컴포넌트 생성·수정, 스타일링, 레이아웃 변경 등)을 수행할 때는 반드시 [DESIGN.md](DESIGN.md)를 먼저 참고하세요.

- 색상, 타이포그래피, 간격(spacing), 모서리(radius), 컴포넌트 스펙은 `DESIGN.md` 프론트매터의 토큰을 기준으로 사용합니다.
- 인라인 hex/px 값을 새로 도입하지 말고 정의된 토큰(`{colors.*}`, `{typography.*}`, `{spacing.*}`, `{rounded.*}`, `{component.*}`)을 참조하세요.
- "Do's and Don'ts" 섹션의 규칙(단일 액센트 컬러, 그림자 사용 제한, 라운드 규격 등)을 반드시 준수합니다.
- 새 컴포넌트를 만들기 전에 `DESIGN.md`의 `components:` 항목에 유사한 정의가 있는지 먼저 확인하세요.

## 코딩 컨벤션

- TypeScript strict 모드 준수
- Next.js App Router: 서버 컴포넌트 기본, 인터랙션이 필요한 경우에만 `"use client"`
- 스타일: TailwindCSS 유틸리티 + shadcn/ui 프리미티브, `cn()`으로 클래스 병합
- 경로 별칭 `@/*` 사용 (상대 경로 지양)
- 설정 파일은 `configs/`에, 런타임 상수는 `src/lib/paths.ts`에서 관리
- 환경 변수는 `.env.local` 사용 (git에 커밋하지 않음)
- 커밋 전 `npm run lint && npm run typecheck && npm test` 실행 권장
