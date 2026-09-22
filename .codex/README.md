# Codex 연결

프로젝트 루트의 [AGENTS.md](../AGENTS.md)가 진입점이다. [.agents/skills](../.agents/skills)에서 프로젝트 스킬을 검색한다.

- `$dorm-implement`: 구현/이어하기.
- `$dorm-verify`: 명세와 변경 검증.
- `$dorm-spec-update`: 명시적인 요구사항 변경.
- `$dorm-docker`: Dockerfile·Compose·컨테이너 배포/장애 처리.

이 폴더는 모델·개인 계정·전역 설정을 고정하지 않는다. 로컬 프로젝트 설정의 적용은 사용하는 Codex의 프로젝트 신뢰 설정에 따른다.
루트에서 시작해 담당 폴더의 지침을 읽는다. Git 저장소가 없는 하위 폴더에서 바로 시작하면 상위 지침 탐색이 달라질 수 있다.

프로젝트 훅은 `.codex/hooks.json`에 연결되어 있다. `harness/hooks.mjs`가 secret·위험 명령을 차단하고, 명세·스킬 변경 뒤 `harness:check`를 안내한다. 훅이 동작하지 않아도 수동 검사와 CI가 최종 기준이다.
Codex가 루트 지침과 초기 프로젝트 스킬을 검색해 제공한 것을 확인했다. 현재 공통 스킬 목록은 README에서 관리한다.
별도 새 세션의 실제 구현 작업까지 시험한 것은 아니다. 새 세션에서 지침/스킬 목록을 확인한다.
