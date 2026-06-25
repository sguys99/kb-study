# Simple Next.js Fullstack Template

Next.js 15 App Router, TailwindCSS v4, shadcn/ui, Vercel AI SDK가 미리 통합된 풀스택 스타터 템플릿입니다. 단일 Next.js 앱으로 UI와 API를 함께 개발할 수 있도록 구성되어 있습니다.

## 기술 스택

- **Framework**: Next.js 15 (App Router) · React 19 · TypeScript
- **Styling**: TailwindCSS v4 · shadcn/ui (new-york / zinc)
- **AI**: Vercel AI SDK (Anthropic / OpenAI)
- **Testing**: Vitest · React Testing Library
- **Tooling**: ESLint · Prettier · Docker

## 빠른 시작

```bash
# 1. 의존성 설치
npm install

# 2. 환경 변수 설정
cp .env.example .env.local
# .env.local 에 ANTHROPIC_API_KEY 또는 OPENAI_API_KEY 입력

# 3. 개발 서버 실행
npm run dev
```

브라우저에서 [http://localhost:3000](http://localhost:3000) 접속.

## 스크립트

| 명령 | 설명 |
|------|------|
| `npm run dev` | 개발 서버 실행 |
| `npm run build` | 프로덕션 빌드 (`output: standalone`) |
| `npm run start` | 빌드된 앱 실행 |
| `npm run lint` | ESLint 검사 |
| `npm run format` | Prettier 포맷팅 |
| `npm run typecheck` | TypeScript 타입체크 |
| `npm test` | Vitest 1회 실행 |
| `npm run test:watch` | Vitest watch 모드 |

## 디렉토리 구조

```
.
├── src/
│   ├── app/            # App Router (layout, page, api/*)
│   ├── components/ui/  # shadcn/ui 컴포넌트
│   ├── lib/            # 유틸, 경로 상수, 설정 로더
│   └── __tests__/      # Vitest 테스트
├── public/             # 정적 자산
├── configs/            # 프롬프트/설정 파일
├── data/               # 데이터 (raw, intermediate, processed)
├── docs/               # PRD/가이드 템플릿
└── img/                # 이미지
```

## shadcn/ui 컴포넌트 추가

```bash
npx shadcn@latest add card input dialog
```

## Docker

```bash
docker compose up --build
```

## 라이선스

Apache 2.0. [LICENSE](LICENSE) 참고.
