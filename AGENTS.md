# 기숙사 출석 관리 — 공통 작업 지침

이 파일은 Codex와 Claude Code가 공유한다. 작업 위치별 `AGENTS.md`도 직접 읽는다.

## 먼저 읽기

1. [명세 목차](docs/spec/index.md)에서 작업 관련 문서를 고른다.
2. [아키텍처](docs/architecture.md), [기술 결정](docs/decisions.md)을 확인한다.
3. 작업 폴더의 `AGENTS.md`와 [개발 계획](docs/plans/implementation.md)을 읽는다.
4. 구현 후 [검증 기준](docs/verification.md)에 따라 검증하고 진행 상황을 남긴다.

## 변경 원칙

- 최신 사용자의 명시적 결정이 최우선이다. 출처가 다른 항목은 [출처 지도](docs/sources/README.md)로 확인한다.
- `docs/spec`의 REQ 항목이 제품 정책의 기준이다. 원문 자료와 이전 대화 요약의 폐기된 내용으로 되돌리지 않는다.
- API 경로, 라이브러리 버전, 모델, VM 크기, CI 방식 등 기술 세부사항은 담당자가 근거를 남기고 결정한다. 재인터뷰를 개발 시작 조건으로 만들지 않는다.
- 사용자 결정·문서에 나온 사실·개발자의 구현 가정을 구분한다. 제공되지 않은 DataGSM 필드나 API를 만들어 내지 않는다.
- 개인정보 동의 필수, 원본 영상·프레임 즉시 폐기, 졸업 전 벡터 보관, 당일 기록 08:00 폐기를 지킨다.
- 관리자 권한과 학생 데이터 범위는 서버에서 검증한다. OAuth Secret과 얼굴 벡터를 프론트 번들·로그·fixture에 넣지 않는다.
- 얼굴 검출·랜드마크를 학생 신원 확인과 동일시하지 않는다. 임베딩 모델과 웹 오프라인 인식은 기술 검증 사항이다.
- 출석 중복 방지는 학생·용도·운영일 단위다. 인식 실패로 타인의 이름을 만들거나 이미 출석한 상태를 지우지 않는다.
- 문서 변경은 관련 REQ, 수용 시나리오, 기술 결정까지 함께 반영한다. 모든 명세를 여러 파일에 복제하지 않는다.
- 실제 앱 테스트가 없거나 실행되지 않았으면 명시한다. 문서 검사 통과를 서비스 구현 완료로 보고하지 않는다.

## 담당 위치

| 변경 대상 | 지침 |
| --- | --- |
| 웹·카메라·화면 | [web/AGENTS.md](web/AGENTS.md) |
| OAuth·권한·DB·출석 | [server/AGENTS.md](server/AGENTS.md) |
| 얼굴 검출·임베딩·대조 | [ai/AGENTS.md](ai/AGENTS.md) |
| 배포·백업·운영 | [infra/AGENTS.md](infra/AGENTS.md) |
| 서비스 간 계약 | [contracts/README.md](contracts/README.md) |

## 작업·검증

- 기능 작업은 `.agents/skills/dorm-implement/SKILL.md`, 검증은 `dorm-verify`, 정책 변경은 `dorm-spec-update`를 사용한다.
- Dockerfile·Compose·컨테이너 배포/장애 작업은 `.agents/skills/dorm-docker/SKILL.md`를 사용한다.
- 작업 절차: [docs/workflow.md](docs/workflow.md).
- 로컬 검사: `npm run harness:check`.
- 자동 훅은 secret·위험 명령을 차단하고 하네스 관련 변경 뒤 검사를 안내한다. 훅 자체의 동작은 `harness/hooks.test.mjs`에서 검증한다.
- 스킬 동기화: `npm run harness:sync` 후 검사. `.claude/skills`를 직접 수정하지 않는다.
- 테스트·빌드 명령은 실제 서비스가 생성될 때 등록한다. 존재하지 않는 명령을 성공 처리하지 않는다.
- 결과에는 구현 내용, 실행한 검사, 미검증 부분, 다음 작업을 기록한다.

## Code Review Rules

권한 우회, 다른 용도 출석의 합침, QR 세션 간 종료 전파, 만료 QR 연장, 다수 얼굴 결과 혼합,
개인정보 원본의 영속 저장, 삭제 후 오래된 오프라인 기록 부활, 근거 없는 외부 API 가정을 우선 확인한다.
