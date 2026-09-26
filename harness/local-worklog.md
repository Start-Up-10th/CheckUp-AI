# entire-AI 로컬 작업 기록

`entire-AI`의 하네스나 AI 기능을 사용하면서 생긴 설계 결정, 명세 변경, 검증 결과, 통합 작업은 이 파일에 기록한다.

기록 명령:

```powershell
npm run harness:worklog -- "작업 내용과 검증 결과"
```

자동 기록이 아니라 작업 단위가 끝날 때 의미 있는 요약을 남긴다. 원본 영상·프레임·토큰·개인정보는 기록하지 않는다.

## 기록

- 2026-09-26: `ALL_harness`를 하네스 원본으로, `AI-feat`를 AI 작업 원본으로 분리하고 `entire-AI`에서 최종 통합하는 작업 흐름을 정의함.

- 2026-09-26: ALL_harness 동기화, AI-feat 허용 목록 통합, 통합 훅 안내와 작업 기록 규칙 추가; harness:check 38/38 요구사항 및 21개 테스트 통과

- 2026-09-26: harness:sync:upstream이 ALL_harness를 origin/main으로 fetch/reset한 뒤 entire-AI에 동기화하도록 고정

- 2026-09-26: ALL_harness에 없는 entire-AI 전용 훅과 통합 파일을 preservePaths로 고정하고 삭제 방지 회귀 테스트를 추가
