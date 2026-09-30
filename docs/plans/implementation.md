# 개발 계획과 인계 — API 기능 기준

## 현재 상태

- CheckUp-server main은 DataGSM OAuth Authorization Code + PKCE와 `SESSION` 쿠키 인증을 사용한다.
- AI FastAPI는 서비스 간 Bearer 인증을 쓰는 내부 얼굴 등록 추출·세션 인식 API를 제공한다.
- 브라우저 → Spring OAuth 세션과 Spring → AI 서비스 토큰의 실제 얼굴 기능 end-to-end 연동은 아직 확인되지 않았다.
- 과거 API 문서와 계획 상태는 현재 CheckUp-server main 코드 및 `contracts/`의 제공자 계약과 대조해 갱신한다.

## 하네스 개선과 CI 선구축

초기 하네스 정리 이후의 결함과 개선 과제는 [2026-09-23 평가](../reviews/harness-assessment-2026-09-23.md) 및 [하네스 개선 계획](harness-improvements.md)에서 관리한다.
CI/CD 구성·정적 검사는 서비스 개발 전에 준비할 수 있고, 테스트·빌드는 실행 가능한 골격·명령부터 연결한다(DEC-013).
이 작업 흐름은 아래 제품 API 개발과 병행할 수 있다. 하네스 개선 전체 완료를 제품 개발의 새 선행 조건으로 만들지 않는다.

## API 그룹별 계획

| API 그룹 | 계획 파일 | API 범위 | 담당자 | 상태 |
| --- | --- | --- | --- | --- |
| 인증 | [auth.md](auth.md) | `/api/v1/auth/*` | 강민우 | 미착수 |
| 상태 확인 | [health-check.md](health-check.md) | `/api/v1/health` | 김준수 | 미착수 |
| 학생·출석 | [student-attendance.md](student-attendance.md) | `/api/v1/student`, `/api/v1/attend` | 김준수 | 미착수 |
| 호실 명단 | [room-roster.md](room-roster.md) | `/api/v1/room/student` | 임서하 | 미착수 |
| QR 출석 | [qr-attendance.md](qr-attendance.md) | `/api/v1/qr*` | 김성찬 | 미착수 |
| 얼굴 인식 | [face-recognition.md](face-recognition.md) | Spring 공개 경로 TBD; AI 내부 `/internal/v1/face/*` | 임서하 | 연동 미확인 |
| 봉사 관리 | [volunteer-management.md](volunteer-management.md) | `/api/v1/volunteer/*` | 김성찬·강민우 | 미착수 |
| DataGSM 동기화 | [datagsm-webhook.md](datagsm-webhook.md) | `/api/v1/webhook` | 강민우 | 미착수 |

## 공통 선행 작업

- [x] 브라우저→Spring 인증은 `SESSION` 쿠키, Spring→AI 인증은 `FACE_SERVICE_TOKEN` bearer로 구분한다.
- [ ] 사용자 식별자 타입, 공통 오류 envelope, `requestId`를 정한다.
- [ ] 서버 UTC 시각과 Asia/Seoul 08:00 운영일 계산을 공통화한다.
- [ ] `student_id`, `studentId`, `studentNumber`, `dormitoryRoom` 매핑을 고정한다.
- [ ] DB migration, 테스트용 clock, 민감정보 없는 로그·fixture를 준비한다.
- [ ] 실제 구현 뒤 비어 있지 않은 OpenAPI 계약을 `contracts/`에 생성한다.
- [ ] 관리자·본인·본인 호실 권한을 서버에서 검증한다.

## 기능 간 의존성

인증과 DataGSM 동기화가 먼저다. 이후 학생·출석, 호실, QR, 얼굴, 봉사 기능을 병렬 진행하고 마지막에 웹·운영·수용 검증을 연결한다.

## API 문서와 제품 명세의 보완 목록

1. QR 발급 문서에 `purpose`, 독립 세션 ID, lease/heartbeat, 종료, 15분 갱신이 없다.
2. QR 출석 문서에 운영일·중복 결과·현재 사용자 범위가 없다.
3. AI 얼굴 등록 추출과 관리자 인식은 `contracts/ai-face.openapi.yaml`의 비공개 POST/session 계약을 사용한다. Spring 공개 얼굴 API는 SESSION 인증 및 해당 AI 계약 호출 규칙을 별도 구현·검증해야 한다.
4. 얼굴 인식 결과의 출석 확정·오프라인 임시 기록 동기화 API가 없다.
5. 관리자 호실 수동 출석 저장 API가 없다.
6. 공지 CRUD·내부 알림 API가 없다.
7. 호실 API는 단일 호실 조회만 정의해 관리자 층 전개도 전체 조회를 직접 지원하지 않는다.
8. webhook의 event 값, 서명 방식, old/new 실제 필드, 재전송 idempotency가 미정이다.
9. CheckUp-server auth 계약은 GET login/callback/me와 POST logout, `SESSION` 쿠키다. 애플리케이션 Bearer/RefreshToken 재발급 흐름은 main에 없으며, 공통 오류 envelope는 별도 계약이 필요하다.
10. 봉사 증가·차감 API의 재시도 idempotency와 0회 하한 검증을 구현 계약에 반영한다. UI 노출은 SRC-NOTION-CHECKUPZIP 승인으로 `+ / −` 모두 확정됐다.

없는 경로를 임의로 구현하지 않고, 제공자·소비자·관련 REQ·수용 시나리오를 정한 뒤 `contracts/`에 반영한다.

## 웹·운영 통합

- [ ] OAuth, 학생 홈·마이·QR, 관리자 홈·QR·얼굴·봉사 화면을 각 API와 연결한다.
- [ ] 로딩·빈 상태·권한 부족·만료·중복·일시 장애를 오류 코드와 분리한다.
- [ ] 카메라 track·타이머·구독을 이탈/로그아웃 때 정리한다.
- [ ] Docker Compose, PostgreSQL/Redis 볼륨, health check, secret 주입을 구성한다.
- [ ] GSM SV 권한·VM 만료·자원·포트/TLS·OAuth callback을 확인한다.
- [ ] 원본 얼굴·당일 출석·임시 기록을 백업에서 제외하고 삭제 복원을 검사한다.

## 완료 기준

- API 요청·응답·권한·오류가 각 계획과 `contracts/`에 연결된다.
- 출석은 학생+용도+운영일 DB 원자성과 가장 이른 유효 기록 규칙을 갖는다.
- 얼굴 원본·프레임·벡터·당일 출석의 수명을 DB·캐시·로그·백업까지 검증한다.
- 실제 제품 테스트 전에는 수용 시나리오를 `verified`로 표시하지 않는다.
- 실제 서비스 테스트 후 `npm run harness:check`를 실행한다.

## 실행 기록

| 시점 | 실행 | 결과 |
| --- | --- | --- |
| 2026-09-21 | `npm run harness:sync` | 공통 스킬 동기화 완료 |
| 2026-09-21 | `npm run harness:check` | 하네스·명세·스킬 검사 통과, 제품 서비스는 미구현 |
| 2026-09-22 | API 명세 폴더 대조 | 8개 API 그룹별 기능 계획으로 재편 |
| 2026-09-23 | CI 선구축 지침 반영·공식 문서/공개 저장소 비교·로컬 진단 | DEC-013 추가, 평가와 개선 계획 작성. 기준 검사 20/20 통과와 별개로 훅 입력/경로 및 검증 증빙의 허점을 재현. 실제 에이전트 새 세션·원격 CI·제품 실행은 미검증. |
| 2026-09-24 | Notion ZIP 항목 3개 사용자 승인 반영 | 얼굴 자동 촬영, 관리자 휴대폰 5탭, 봉사 횟수 `+ / −`를 출처·명세·수용 시나리오·분야별 계획에 반영. 제품 코드는 미구현. 이번 변경 뒤 자동 검사는 실행하지 않음. |
| 2026-09-30 | AI 이슈 #6 인증 경계 구현 | AI `/internal/*` 선행 인증 미들웨어와 4개 경로의 credential 거부 매트릭스 추가. Ruff 통과, `npm run harness:check` 통과(하네스 테스트 23/23). `pytest`는 제거된 Python 3.12 기반을 참조하는 로컬 venv 때문에 미실행. |

AI FastAPI 내부 얼굴 API와 서비스 토큰 경계는 구현돼 있다. Spring 공개 API, 브라우저 연동, 제품 E2E와 실기기 검증은 미완료다.
