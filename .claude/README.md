# Claude Code 연결

[CLAUDE.md](../CLAUDE.md)는 `@AGENTS.md`로 공통 규칙을 가져온다. 담당 폴더의 CLAUDE.md도 같은 폴더 AGENTS.md를 가져온다.

- `/dorm-implement`: 구현/이어하기.
- `/dorm-verify`: 명세와 변경 검증.
- `/dorm-spec-update`: 명시적인 요구사항 변경.
- `/dorm-docker`: Dockerfile·Compose·컨테이너 배포/장애 처리.

`.claude/skills`는 `.agents/skills`의 생성된 복사본이다. 직접 수정하지 않고 원본 수정 후 `npm run harness:sync`를 실행한다.
두 경로의 깊이가 같아서 스킬의 상대 문서 링크도 그대로 동작한다. Windows 심볼릭 링크 설정은 필요 없다.
settings.json은 하네스의 읽기/검증 명령만 허용하며 광범위한 셸 권한이나 권한 우회 모드를 설정하지 않는다.
settings.json의 PreToolUse/PostToolUse 훅은 `harness/hooks.mjs`에 연결되어 secret·위험 명령을 차단하고 하네스 관련 변경 뒤 검사를 안내한다. 훅 자체는 `npm run harness:test`로 검증한다.
전역 모델·계정·개인 설정은 변경하지 않는다. 별도 자동 Stop 훅에 의존하지 않는다.
현재 호스트에서 Claude Code 자체를 실행해 확인한 것은 아니다. 새 세션에서 `/context`와 스킬 목록을 확인한다.
