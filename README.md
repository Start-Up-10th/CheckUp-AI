# 기숙사 출석 관리 · Claude Code / Codex 하네스

약 200명의 기숙사생, 출입구 3곳, 얼굴 인식·QR 출석을 위한 개발 하네스다. 서비스 구현 전 단계이며 애플리케이션 코드는 아직 없다.

이 저장소에서 Claude Code와 Codex가 같은 요구사항, 개발 절차, 검증 기준을 사용한다. 인터뷰 전체를 매번 프롬프트에 붙이지 않아도 작업을 이어갈 수 있다.

## 시작

1. 이 폴더를 프로젝트 루트로 연다.
2. Node.js 22 이상에서 `npm run harness:check`를 실행한다. 패키지 설치는 필요 없다.
3. 아래 시작 프롬프트를 Claude Code 또는 Codex에 전달한다.

```text
AGENTS.md를 읽고 docs/plans/implementation.md의 첫 미완료 단계를 구현해.
관련 명세와 담당 영역 지침을 먼저 읽고, 구현·검증 결과와 다음 단계를 계획 파일에 남겨.
기술 선택은 docs/decisions.md에 근거와 함께 기록해. 서비스 정책은 임의로 변경하지 마.
```

Claude Code는 [CLAUDE.md](CLAUDE.md)에서 공통 지침을 가져온다. Codex 진입점은 [AGENTS.md](AGENTS.md)다. 새 세션에서 사용하는 것을 권장한다. 실제 모델 호출이나 두 도구 실행은 이 하네스 검사에 포함되지 않는다.

## 구조

```text
.
├── AGENTS.md / CLAUDE.md      공통 진입 규칙과 Claude 연결
├── .agents/skills/           공통 스킬 원본, Codex 검색 경로
├── .claude/skills/           Claude용 동기화본
├── .codex/                  프로젝트 설정과 사용 안내
├── docs/
│   ├── spec/                분야별 제품 명세: REQ 식별자로 추적
│   ├── sources/             사용자 제공 원문·화면과 출처 지도
│   ├── architecture.md      서비스 경계와 기술 검증 사항
│   ├── decisions.md         확정 정책과 구분한 기술 결정
│   ├── workflow.md          읽기 → 구현 → 검증 → 인계
│   ├── verification.md      실행 가능한 검사와 제품 검증 구분
│   └── plans/               단계별 개발 계획과 진행 상황
├── contracts/               API 계약 관리 경계
├── web/                     Next.js 담당 지침
├── server/                  Spring 담당 지침
├── ai/                      FastAPI·MediaPipe 담당 지침
├── infra/                   Docker·GitHub Actions·GSM SV 지침
├── tests/acceptance/         요구사항별 수용 시나리오
├── harness/                 문서·스킬·추적성 검사·안전 훅과 자체 테스트
└── .github/workflows/       하네스 검사 CI
```

각 서비스 폴더는 향후 코드 위치다. 현재 들어 있는 파일은 담당 지침이며, 작동하는 서비스를 가장한 빈 앱·가짜 API는 만들지 않았다.

## 공통 스킬

| 용도 | Codex | Claude Code |
| --- | --- | --- |
| 기능 구현·이어하기 | `$dorm-implement` | `/dorm-implement` |
| 변경 검증·명세 대조 | `$dorm-verify` | `/dorm-verify` |
| 요구사항 변경 반영 | `$dorm-spec-update` | `/dorm-spec-update` |
| Docker·Compose·컨테이너 배포/장애 | `$dorm-docker` | `/dorm-docker` |

스킬 원본은 `.agents/skills`에서만 수정한다. `npm run harness:sync`로 Claude 복사본을 갱신하고 함께 커밋한다. Windows에서 별도 심볼릭 링크 권한 없이 작동한다.

`harness/hooks.mjs`는 Claude Code와 Codex에 공통 연결되어 credential 형태의 문자열과 위험한 Git·Docker·데이터베이스 삭제 명령을 차단한다. 명세·스킬·하네스 변경 뒤에는 검사를 안내하며, 최종 기준은 `npm run harness:check`와 CI다.

## 문서 찾기

- 전체 명세 목차: [docs/spec/index.md](docs/spec/index.md)
- 이전 요약의 정정·출처 우선순위: [docs/sources/README.md](docs/sources/README.md)
- 개발자가 판단할 기술 항목: [docs/decisions.md](docs/decisions.md)
- 사용자가 다시 정할 필요 없는 개발 순서: [docs/plans/implementation.md](docs/plans/implementation.md)
- 검증 범위·명령: [docs/verification.md](docs/verification.md)

GitHub 저장소 생성·커밋·푸시·실제 배포는 수행하지 않았다. 운영 OAuth 값과 서버 접속 정보는 연동 단계에서 제공한다.
