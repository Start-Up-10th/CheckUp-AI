# 서비스 간 계약

제품 정책은 [명세](../docs/spec/index.md), 기술 경계는 [아키텍처](../docs/architecture.md)를 따른다.
QR 출석 API 계약은 [qr.openapi.yaml](qr.openapi.yaml)에 기록한다.
얼굴 등록 및 AI 추론 API는 [ai-face.openapi.yaml](ai-face.openapi.yaml)에 기록한다. 얼굴 등록은 MediaRecorder 영상 업로드를 받도록 정의한다.

`/internal/*`은 Spring 백엔드와 AI 서버 사이의 비공개 계약이다. Spring은 `Authorization: Bearer {FACE_SERVICE_TOKEN}`으로 AI를 호출한다. 이는 OAuth 토큰이 아닌 서비스 간 인증 값이며 웹 브라우저에 노출하면 안 된다. AI는 `SESSION` 쿠키나 DataGSM `accessToken`을 받거나 검증하지 않는다.

얼굴 후보의 `student_id`는 Spring이 DataGSM `student.id`에서 변환한 canonical 학생 ID의 문자열이다. AI는 이를 불투명한 식별자로 취급해 `KNOWN` 결과에 그대로 반환한다. CheckUp DB 기본 키나 화면 표시용 `studentNumber`로 변환하지 않는다. `UNKNOWN` 결과의 `studentId`는 `null`이다.

브라우저는 Spring에 로그인 세션 쿠키 `SESSION`으로 인증한다. 얼굴 등록 시 Spring 공개 API가 사용자·동의·중복 여부를 확인하고, AI의 `POST /internal/v1/face/enrollments/extract`에 MediaRecorder 원본 영상 body를 전달한다. AI는 대표 벡터와 모델 정보를 반환하고, 학생 연결·중복 검사·벡터 저장·사용자용 성공 응답은 Spring이 담당한다. CheckUp-server main에는 Spring-AI 얼굴 등록 연동 경로가 아직 없으므로 API 계약은 실제 연동 전 제공자/소비자 검토가 필요하다.

계약을 구현과 함께 갱신하고 웹/백엔드/AI 담당자가 같은 경로와 예제로 확인한다. OpenAPI 파일이 있다는 사실만으로 프론트엔드 연동이 완료되지는 않는다.

## 인증 (CheckUp-server 소스 확인)

- 웹은 body 없는 `GET /api/v1/auth/login`으로 Spring 로그인을 시작한다. callback에는 `code`, `state`가 오며 state/PKCE 검증, 토큰 교환, userinfo 조회와 DataGSM access token 처리는 Spring 책임이다.
- callback 성공 응답은 브랜치별로 다르다. 2026-09-30에 확인한 CheckUp-server develop은 `SESSION` 쿠키와 `302 /login/complete`를 반환하고, main은 `SESSION` 쿠키와 `200 {"name": string, "role": "STUDENT" | "ADMIN"}`을 반환한다. 고정 SHA와 웹 조합은 [인증 계약 계획](../docs/plans/auth.md)에 기록한다. 이 응답들을 한 흐름으로 섞거나 배포 동작이라고 단정하지 않는다.
- 현재 `GET /api/v1/auth/me`는 `SESSION` 쿠키 인증 후 `{ "name": string, "role": "STUDENT" | "ADMIN" }`만 반환한다. 학생 프로필·동의 상태·얼굴 등록 상태는 현재 계약에 없다. 미구현 `CurrentMemberResponse` 확장은 저장된 실제 상태를 조회할 도메인 구현 후 별도 계약으로 정한다.
- OAuth 로그인 상태는 `SESSION` 쿠키로 전달한다. 웹은 쿠키를 포함해 Spring API를 요청하며 `Authorization`·`RefreshToken` 헤더로 로그인 상태를 전달하지 않는다.
- Spring에는 `POST /api/v1/auth/logout` 경로가 있지만, 검토한 CheckUp-Client develop은 이를 호출하지 않는다. endpoint 존재를 웹 로그아웃 연동 완료로 간주하지 않는다.
- Spring에서 AI를 호출하는 경우에만 `FACE_SERVICE_TOKEN` Bearer 인증을 사용한다. DataGSM access token은 서버 안에서 userinfo를 조회하는 용도이며 AI 호출용이 아니다.
- 공통 오류 envelope는 아직 없다.

## 알림 계약

- [notification.openapi.yaml](notification.openapi.yaml): `GET /api/v1/notifications`, `GET /api/v1/notifications/unread`, `POST /api/v1/notifications/read`를 정의한다.
- 학생 본인의 알림만 조회·읽음 처리한다. 목록은 최신순 최대 50개이며, 조회 요청은 읽음 상태를 바꾸지 않는다.
- 정책은 REQ-COM-005·DEC-019를 따른다. 알림 유형은 `ATTENDANCE`, `VOLUNTEER`, `NOTICE`며, 생성 규칙과 보관 기준은 [알림 계획](../docs/plans/notification.md)에 둔다.

계약에 반드시 표현할 내용:

- 현재 `/auth/me` 응답은 역할만 포함한다. 동의/등록 상태와 학생 데이터 범위는 저장·권한 검증 구현 후 확장 계약에 추가하며, 현행 응답으로 약속하지 않는다.
- 자습실/기숙사 purpose와 운영일, 서버 UTC 시각·08:00 KST 경계.
- 페이지별 독립 QR/카메라 session ID, 토큰 만료 시각, 종료/갱신 오류.
- 출석 단일 처리의 event ID/중복 판정, 원래 발생 시각과 서버 수신 시각.
- 수동 수정과 늦은 동기화의 순서 규칙.
- AI 결과의 얼굴별 track ID, known/unknown, 모델 버전/점수. unknown 학생 ID는 null.
- 대표 벡터의 모델/차원/정규화 호환성. 벡터 API는 일반 학생에게 공개하지 않음.
- 봉사 명단 소속과 +1 적립, 재시도 idempotency, 공지 알림 동의.
- 오류 코드와 UI 문구를 분리하여 권한·만료·중복·일시 장애를 구별.

계약 변경 시 제공자/소비자와 시나리오를 같은 변경에서 갱신한다. 예제에는 실제 이름·학번·벡터·secret을 넣지 않는다.
