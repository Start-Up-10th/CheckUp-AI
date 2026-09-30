# 하네스와 AI 작업 통합 규칙

## 저장소 역할

- `ALL_harness`: GitHub `origin/main`을 기준으로 하는 하네스 원본 미러. 직접 기능 작업을 하지 않는다.
- `AI-feat`: 얼굴 인식 기능을 개발하는 작업 공간이다.
- `entire-AI`: 하네스와 AI 작업 결과를 함께 보관하는 최종 통합 저장소다.

## 작업 순서

1. 작업을 시작하기 전에 `npm run harness:sync:upstream`으로 `ALL_harness`를 `origin/main` 최신 상태로 맞춘다. 이 명령은 `entire-AI`에 파일을 복사하지 않는다.
2. 얼굴 인식 기능은 `AI-feat`에서 `entire-AI`의 최신 하네스 규칙을 읽고 작업한다.
3. AI 작업이 끝나면 `npm run ai:integrate`로 허용된 AI 파일만 `entire-AI`에 통합한다.
4. 통합 후 `npm run harness:worklog -- "작업 내용과 검증 결과"`로 로컬 작업을 기록한다.
5. `npm run harness:check`와 AI 테스트를 실행하고, 결과를 작업 기록 또는 관련 계획 문서에 남긴다.
6. 최종 커밋은 `entire-AI`에서 하네스와 AI 변경을 함께 검토한 뒤 만든다.

## 동기화 원칙

- 동기화는 `ALL_harness`에서 `origin/main`을 fetch한 뒤 `reset --hard`한다. `ALL_harness`의 tracked 로컬 변경은 보존되지 않는다.
- 이 명령은 `entire-AI`에 파일을 복사하거나 삭제하지 않는다.
- AI 통합은 `harness/ai-integration.json`에 등록된 파일만 복사한다.
- 로컬 작업 기록에는 원본 영상·프레임·얼굴 이미지·토큰·개인정보를 넣지 않는다.

## 금지 사항

- `ALL_harness`에서 제품 기능을 직접 개발하지 않는다.
- `entire-AI`의 하네스 파일을 AI 작업 결과로 덮어쓰지 않는다.
- `AI-feat`의 전체 폴더를 무조건 복사하지 않는다.
- 하네스 검사 통과를 제품 기능 구현·운영 배포 완료로 간주하지 않는다.
