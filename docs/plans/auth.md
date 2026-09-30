# auth — 인증 계약

## CheckUp-server main의 API

- 담당자: 강민우
- `GET /api/v1/auth/login` — DataGSM 로그인으로 302 이동
- `GET /api/v1/auth/callback?code={code}&state={state}` — 인가 코드 처리
- `GET /api/v1/auth/me` — 현재 로그인 회원 조회
- `POST /api/v1/auth/logout` — 세션 종료, 204 응답

## 인증 방식

- DataGSM OAuth Authorization Code + PKCE의 state 검증과 토큰 교환은 Spring 서버가 처리한다.
- DataGSM `accessToken`은 서버에서 userinfo를 조회하는 데 사용하며 브라우저 응답이나 AI 요청에 전달하지 않는다.
- 로그인 성공 시 Spring이 회원 `name`, `role`을 응답하고 `SESSION` 쿠키 기반 로그인 세션을 만든다.
- 브라우저는 보호된 Spring API에 `SESSION` 쿠키를 포함해 요청한다. 이 흐름은 애플리케이션 `Authorization: Bearer {accessToken}` 또는 `RefreshToken` 헤더를 사용하지 않는다.
- AI는 Spring의 사용자 세션을 검증하지 않는다. Spring이 사용자를 인증한 뒤 AI 내부 경로에만 `Authorization: Bearer {FACE_SERVICE_TOKEN}`을 보낸다.

## 계약·검증

- CheckUp-server 소스: [AuthController](https://github.com/Start-Up-10th/CheckUp-server/blob/main/src/main/java/com/checkup/checkup/domain/auth/controller/AuthController.java), [AuthService](https://github.com/Start-Up-10th/CheckUp-server/blob/main/src/main/java/com/checkup/checkup/domain/auth/service/AuthService.java), [SecurityConfig](https://github.com/Start-Up-10th/CheckUp-server/blob/main/src/main/java/com/checkup/checkup/global/security/SecurityConfig.java).
- `/api/v1/auth/reissue`, 클라이언트 Access Token 발급, refresh-token 재발급은 현재 main 구현에 없으므로 AI/API 명세에 추가하지 않는다.
- 잘못되거나 재사용된 state, 만료 code, DataGSM 장애, 비활성 계정, 권한 부족을 구분한다.
- OAuth secret과 DataGSM 토큰을 브라우저 번들·응답·HTTP 로그·fixture에 넣지 않는다.
- 학생이 다른 학생의 `/auth/me`나 보호 API 데이터 범위를 얻지 못하는지 확인한다.
- 공통 오류 envelope와 `requestId`는 별도 계약으로 확정한다.
