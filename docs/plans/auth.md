# auth — 인증 계획

## 담당자·API

- 담당자: 강민우
- `POST /api/v1/auth/oauth/callback`
- `GET /api/v1/auth/me`
- `POST /api/v1/auth/logout`
- `PUT /api/v1/auth/reissue`

## 구현

- OAuth state·PKCE codeVerifier·콜백 검증, DataGSM 토큰 교환, 서버 세션/JWT 발급
- `/auth/me`의 학생 ID·이름·학번·호실·관리자 여부·얼굴 등록 상태 반환
- `DORMITORY_MANAGER` 기반 서버 권한 판정
- 로그아웃 시 로그인 세션과 사용자 인증 세션 정리
- Access Token 재발급 및 refresh token 만료·위조·재사용 거부
- QR 로그인 복귀 시 원래 QR의 만료·종료·용도 재검사

## 계약 보완

- [ ] API 예시의 JSON 쉼표와 토큰 반환 타입을 정리한다.
- [ ] `RefreshToken` 헤더와 일반 `Authorization` 헤더 규칙을 공통 계약에 기록한다.
- [ ] 공통 오류 envelope와 `requestId`를 정한다.
- [ ] OAuth secret·refresh token을 프론트 번들·HTTP 로그·fixture에서 제외한다.

## 기준·검증

- 요구사항: `REQ-AUTH-001~005`
- 수용 시나리오: `ACC-AUTH-001~005`
- 잘못된 state/codeVerifier, 만료 code, DataGSM 장애, 권한 부족을 구분한다.
- 만료·위조·재사용 refresh token을 거부한다.
- 학생이 다른 학생의 `/auth/me`·보호 API 범위를 얻지 못하는지 확인한다.

선행 조건은 공통 인증·시간·오류 계약이다. DataGSM 실제 userinfo 필드·전체 명단은 아직 확인하지 않았다.
