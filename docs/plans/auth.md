# auth — 확인된 OAuth 계약

## 검토 범위

이 문서는 2026-09-30에 고정한 CheckUp-server 및 CheckUp-Client 소스 계약을 기록한다. 배포 SHA와 DataGSM 콘솔 설정은 확인하지 않았으므로 현재 운영 동작으로 단정하지 않는다.

| 대상 | 확인한 커밋 |
| --- | --- |
| CheckUp-server main | `aa21ad21d4bcb0399f9c633f5eb4a75baf7266c0` |
| CheckUp-server develop | `cfd612cd5d34b2772c02aed03790be28a0ff4738` |
| CheckUp-Client main | `24c72c2da7e0fef257c79f6cfc41f68b6f86f120` |
| CheckUp-Client develop | `156915fd186b0595d40c718a126e0b44f025c9fc` |

## OAuth 진입과 callback

웹은 body 없는 `GET /api/v1/auth/login`으로 Spring 로그인을 시작한다. 확인한 Client develop 흐름에서 Spring은 DataGSM 인가 URL로 `302` 응답한다. DataGSM은 등록된 Spring callback에 `code`, `state`를 전달한다. Spring이 state/PKCE를 검증하고 토큰을 교환한 뒤 userinfo를 조회한다. 웹은 이 과정을 직접 수행하지 않는다.

callback 성공 응답은 서버 브랜치에 따라 다르다. 둘을 하나의 계약으로 합쳐 설명하지 않는다.

| CheckUp-server 소스 | callback 성공 응답 | 웹과의 결과 |
| --- | --- | --- |
| develop `cfd612c…` | `SESSION` 쿠키 설정 후 `302 /login/complete`; 선택적 상대 경로 `redirect` 지원 | Client develop이 로그인 완료 화면에서 `/auth/me`를 조회하는 흐름과 일치 |
| main `aa21ad2…` | `SESSION` 쿠키 설정 후 `200` JSON `{ "name": string, "role": "STUDENT" \| "ADMIN" }` | Client develop은 웹 복귀 `302`를 기대하므로 이 조합은 불일치 |

DataGSM `accessToken`은 Spring 내부 userinfo 조회에만 사용한다. 브라우저나 AI로 전달하지 않는다. Spring이 AI를 호출할 때는 별도 서비스 간 자격증명 `FACE_SERVICE_TOKEN`만 사용한다.

## 현재 회원 조회 계약

확인한 `GET /api/v1/auth/me`는 로그인된 `SESSION` 쿠키를 요구한다. 응답은 직접 JSON 객체이며 현재 필드는 다음 두 개뿐이다.

| 필드 | 타입 | 의미 |
| --- | --- | --- |
| `name` | `string` | 현재 회원 이름 |
| `role` | `"STUDENT" \| "ADMIN"` | CheckUp 서비스 역할 |

이 응답에는 canonical 학생 ID, 학번, 호실, 개인정보 동의 상태, 얼굴 등록 상태가 없다. 그러므로 `/auth/me`가 현재 학생 프로필이나 온보딩 진행 상태를 제공한다고 문서화하지 않는다. 인증되지 않은 요청은 로그인 세션을 제공하지 않은 요청으로 처리한다.

## 제안 계약 — 미구현

학생 프로필과 온보딩 상태가 필요하면 현재 callback 응답과 분리된 `CurrentMemberResponse` 확장을 제안한다. 이 이름과 필드는 구현 계약이 아니다. 개인정보 동의와 얼굴 등록 상태를 DB에 저장하고 조회하는 도메인 처리가 생기기 전에는 상수나 추정값을 응답한다고 약속하지 않는다. 확장 시 학생 canonical ID·화면용 프로필·실제 저장 상태를 제공하고, 교사 관리자와 학생 자치위원의 학생 정보 유무도 표현해야 한다.

CheckUp-server의 `POST /api/v1/auth/logout`은 세션 종료 경로로 확인됐다. 다만 검토한 Client develop은 이 API를 호출하지 않는다. 서버 endpoint가 존재하는 것과 웹에서 로그아웃 연동이 완료된 것은 구분한다.

## 근거와 검증 한계

- [OAuth 요청·응답 호환성 검토](../reviews/oauth-contract-review-2026-09-30.md)는 서버·웹의 실제 요청, callback 응답, 최소 회원 DTO와 미구현 제안을 비교한다.
- 서버 소스: [main AuthController](https://github.com/Start-Up-10th/CheckUp-server/blob/aa21ad21d4bcb0399f9c633f5eb4a75baf7266c0/src/main/java/com/checkup/checkup/domain/auth/controller/AuthController.java), [develop AuthController](https://github.com/Start-Up-10th/CheckUp-server/blob/cfd612cd5d34b2772c02aed03790be28a0ff4738/src/main/java/com/checkup/checkup/domain/auth/controller/AuthController.java), [develop AuthService](https://github.com/Start-Up-10th/CheckUp-server/blob/cfd612cd5d34b2772c02aed03790be28a0ff4738/src/main/java/com/checkup/checkup/domain/auth/service/AuthService.java), [develop OAuthLoginResponse](https://github.com/Start-Up-10th/CheckUp-server/blob/cfd612cd5d34b2772c02aed03790be28a0ff4738/src/main/java/com/checkup/checkup/domain/auth/dto/response/OAuthLoginResponse.java).
- 웹 소스: [develop auth-api](https://github.com/Start-Up-10th/CheckUp-Client/blob/156915fd186b0595d40c718a126e0b44f025c9fc/web/src/lib/auth/auth-api.ts), [develop 로그인 완료 화면](https://github.com/Start-Up-10th/CheckUp-Client/blob/156915fd186b0595d40c718a126e0b44f025c9fc/web/src/components/student/StudentLoginComplete.tsx).
- 실제 배포 callback·HTTPS·학교 계정 OAuth end-to-end는 검증하지 않았다.
