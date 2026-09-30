# OAuth 요청·응답 호환성 검토와 변경 계획

검토일: 2026-09-30. 제품 코드와 배포 설정은 수정하지 않았다. 아래 제안 응답과 작업 순서는 아직 구현되지 않은 계획이다.

## 비교 기준

| 대상 | 확인한 커밋 / 상태 |
| --- | --- |
| CheckUp-server main | `aa21ad21d4bcb0399f9c633f5eb4a75baf7266c0` |
| CheckUp-server develop | `cfd612cd5d34b2772c02aed03790be28a0ff4738` |
| CheckUp-Client main | `24c72c2da7e0fef257c79f6cfc41f68b6f86f120` |
| CheckUp-Client develop | `156915fd186b0595d40c718a126e0b44f025c9fc` |
| ALL_harness main | `bbda7260e88c646b470be71ddb5f65341ee30967` |
| entire-AI | HEAD `283fa5385472defeee3f0ca83be4262e32dbd194`와 현재 작업 파일. 기존 미커밋 변경은 보존 |
| DataGSM Java SDK 1.6.0 | tag의 실제 커밋 `d02c9b0608718a4d98994f82a969d496b97980ca` |

로컬 `web/`, `server/`에는 OAuth 구현이 없으므로 공식 CheckUp-Client까지 읽어 실제 소비자 요청을 비교했다. 배포된 서비스의 브랜치·환경변수·DataGSM 콘솔 설정은 확인하지 않았다.

## 결론

**서버 develop과 프론트 develop의 기본 로그인 요청·세션·최소 응답은 맞는다. main/develop을 섞으면 콜백 계약이 달라지고, 학생 프로필·온보딩·로그아웃은 추가 연동이 필요하다.**

DataGSM 토큰을 웹이나 AI에 보내도록 바꿀 필요는 없다. 웹은 Spring `SESSION` 쿠키를 사용하고, Spring→AI는 별도의 `FACE_SERVICE_TOKEN`을 사용한다. DataGSM 신원 매핑과 서비스 관리자 판정은 현재 명세의 기본 방향과 일치한다.

## 실제 요청·응답

| 경계 | 요청 | 실제 반환 / 소비 | 판정 |
| --- | --- | --- | --- |
| 웹 develop → Spring develop | 페이지 이동 `GET /api/v1/auth/login`, body 없음 | 302 DataGSM 인가 URL | 일치 |
| DataGSM → Spring callback | query `code`, `state` | 서버가 state·PKCE 검증, 토큰 교환, userinfo 조회 | 프론트가 직접 처리하지 않는 구조로 일치 |
| Spring develop → 웹 | 성공 시 `SESSION` + 302 `/login/complete`; optional `redirect` 상대 경로 지원 | 웹의 로그인 완료 화면에서 `/auth/me` 요청 | 일치 |
| Spring main → 웹 | callback에서 200 JSON `{name, role}` + `SESSION` | 프론트 develop은 302 웹 복귀를 기대 | **불일치** |
| 웹 develop → `/api/v1/auth/me` | GET, `credentials: "include"`, body·Bearer 없음 | 직접 JSON `{name: string, role: "STUDENT" \| "ADMIN"}` | 현재 최소 모델은 일치. 프로필·온보딩에는 부족 |
| 웹 → `/api/v1/auth/logout` | 서버 계약은 POST + 세션 쿠키, body 없음 | 204 및 세션 종료 | 프론트는 API를 호출하지 않음 |
| Spring → AI | `Authorization: Bearer {FACE_SERVICE_TOKEN}` | AI는 이 서비스 토큰만 검사 | 인증 경계는 일치. Spring 얼굴 어댑터는 미구현 |

근거: [서버 main AuthController](https://github.com/Start-Up-10th/CheckUp-server/blob/aa21ad21d4bcb0399f9c633f5eb4a75baf7266c0/src/main/java/com/checkup/checkup/domain/auth/controller/AuthController.java), [서버 develop AuthController](https://github.com/Start-Up-10th/CheckUp-server/blob/cfd612cd5d34b2772c02aed03790be28a0ff4738/src/main/java/com/checkup/checkup/domain/auth/controller/AuthController.java), [서버 응답 DTO](https://github.com/Start-Up-10th/CheckUp-server/blob/cfd612cd5d34b2772c02aed03790be28a0ff4738/src/main/java/com/checkup/checkup/domain/auth/dto/response/OAuthLoginResponse.java), [프론트 auth-api](https://github.com/Start-Up-10th/CheckUp-Client/blob/156915fd186b0595d40c718a126e0b44f025c9fc/web/src/lib/auth/auth-api.ts), [프론트 로그인 완료](https://github.com/Start-Up-10th/CheckUp-Client/blob/156915fd186b0595d40c718a126e0b44f025c9fc/web/src/components/student/StudentLoginComplete.tsx).

### DataGSM → Spring의 공급자 계약

| 단계 | 실제 SDK 요청/반환 | 서버와의 대조 |
| --- | --- | --- |
| 인가 요청 | `response_type=code`, `client_id`, `redirect_uri`, `state`, `code_challenge`, `code_challenge_method` | 서버가 `.state(...).enablePkce()`로 생성. 프론트가 codeVerifier를 보내지 않음 |
| 인가 반환 | 등록된 callback에 `code`, 요청한 `state` | 서버가 Redis state를 한 번 소비하고 verifier를 복구 |
| 토큰 교환 | POST JSON: `grant_type=authorization_code`, `code`, `client_id`, `redirect_uri`, `code_verifier` | PKCE 경로에서는 client_secret을 body에 같이 보내지 않는 SDK 동작. 공식 PKCE 계약과 일치 |
| 토큰 반환 | `access_token`, `token_type`, `expires_in`, `refresh_token`, `scope` | SDK가 `getAccessToken()` 등으로 매핑. 웹에 이 응답을 반환하지 않음 |
| userinfo 조회 | GET + `Authorization: Bearer <DataGSM access_token>` | 서버 내부 조회에만 사용 |
| userinfo 반환 | 최상위 id/email/role/status/objectType와 student 또는 teacher 중첩 객체 | 서버가 계정과 학생 ID·서비스 역할을 분리해 저장 |

서버는 인가 URL에 scope를 명시하지 않는다. 공식 인가 문서는 생략 시 클라이언트에 등록된 전체 권한을 적용하며 생략을 권장한다. 따라서 이 요청 형식은 맞는다. `/userinfo`에 필요한 `datagsm:self_read`의 앱 등록 여부와 Redirect URI 등록은 콘솔에서 확인해야 한다.

근거: [서버 AuthService](https://github.com/Start-Up-10th/CheckUp-server/blob/cfd612cd5d34b2772c02aed03790be28a0ff4738/src/main/java/com/checkup/checkup/domain/auth/service/AuthService.java), [SDK 인가 URL](https://github.com/themoment-team/datagsm-oauth-sdk-java/blob/d02c9b0608718a4d98994f82a969d496b97980ca/src/main/java/team/themoment/datagsm/sdk/oauth/model/AuthorizationUrlBuilder.java), [SDK 토큰 요청](https://github.com/themoment-team/datagsm-oauth-sdk-java/blob/d02c9b0608718a4d98994f82a969d496b97980ca/src/main/java/team/themoment/datagsm/sdk/oauth/client/OAuthApiImpl.java), [SDK 토큰 응답 모델](https://github.com/themoment-team/datagsm-oauth-sdk-java/blob/d02c9b0608718a4d98994f82a969d496b97980ca/src/main/java/team/themoment/datagsm/sdk/oauth/model/TokenResponse.java), [공식 인가 문서](https://docs.datagsm.kr/oauth/http/authorize), [공식 토큰 교환 문서](https://docs.datagsm.kr/oauth/http/token-exchange).

## 신원과 역할 매핑

| 원본 | 현재 서버 저장/용도 | AI·웹 계약에서 지킬 의미 |
| --- | --- | --- |
| `userinfo.id` | `Member.datagsmId` (`Long`) | 외부 계정 ID. 학생 ID로 사용하지 않음 |
| `userinfo.student.id` | `Student.datagsmStudentId` (`Long`) | canonical 학생 ID. AI에서는 문자열로 변환 |
| Spring `Member.id` | 세션 principal | CheckUp 회원 DB PK |
| Spring `Student.id` | 출석 DB FK | CheckUp 학생 DB PK. AI canonical ID와 구별 |
| `student.studentNumber` | 표시용 학번 | 학생 식별자 대신 사용하지 않음 |
| `student.classNum` | `Student.classNumber` | 필드명 변환은 현재 정상 |
| `student.dormitoryRoom` | nullable `Integer` | 미배정 null 처리 필요. 층은 유효 호실의 정수 `/ 100` |
| `userinfo.status` | 로그인 시 ACTIVE 검사 | 계정 상태. OAuth query `state`와 구별 |
| 최상위 `userinfo.role` | 서비스 관리자 판정에 사용하지 않음 | DataGSM 계정 역할과 CheckUp 역할을 구별 |

현재 학생 자치위원 `DORMITORY_MANAGER`와 기숙사부 교사 `DORMITORY`는 ADMIN이다. 학생회 `STUDENT_COUNCIL`와 일반 활성 학생은 STUDENT다. 자치위원은 ADMIN이면서 student 정보도 갖고, 교사 ADMIN은 student가 없는 것이 정상이다.

근거: [MemberService](https://github.com/Start-Up-10th/CheckUp-server/blob/cfd612cd5d34b2772c02aed03790be28a0ff4738/src/main/java/com/checkup/checkup/domain/member/service/MemberService.java), [AuthService](https://github.com/Start-Up-10th/CheckUp-server/blob/cfd612cd5d34b2772c02aed03790be28a0ff4738/src/main/java/com/checkup/checkup/domain/auth/service/AuthService.java), [Student](https://github.com/Start-Up-10th/CheckUp-server/blob/cfd612cd5d34b2772c02aed03790be28a0ff4738/src/main/java/com/checkup/checkup/domain/member/entity/Student.java), [AttendanceRepository](https://github.com/Start-Up-10th/CheckUp-server/blob/cfd612cd5d34b2772c02aed03790be28a0ff4738/src/main/java/com/checkup/checkup/domain/attendance/repository/AttendanceRepository.java), [로컬 신원 명세](../spec/identity.md), [AI 계약](../../contracts/ai-face.openapi.yaml).

## 확인한 차이와 영향

### 1. 브랜치에 따른 콜백 차이 — 우선 해결

서버 main에는 develop의 웹 복귀 기능이 없다. 프론트 develop과 조합하면 인가 후 JSON 화면에 남아 `/login/complete`가 실행되지 않는다. 서버에 `redirect` 쿼리를 보내도 main은 그 계약을 지원하지 않는다.

프론트 main도 연동 전 상태다. 학생 로그인은 곧바로 `/consent`로 이동한다. 관리자 로그인은 DataGSM 인가 URL을 직접 조립하고 `client_id`, `redirect_uri`, `response_type`만 보내므로 서버의 Redis state·PKCE 흐름과 맞지 않는다.

변경 방향: 서버의 웹 복귀 기능과 프론트의 서버 로그인 진입 기능을 같은 릴리스에 포함한다. 학생·관리자 모두 Spring `/api/v1/auth/login`으로 시작한다. main을 현재 배포 상태라고 단정하지 않고 실제 배포 SHA를 확인한다.

근거: [프론트 main 학생 로그인](https://github.com/Start-Up-10th/CheckUp-Client/blob/24c72c2da7e0fef257c79f6cfc41f68b6f86f120/web/src/components/student/StudentLogin.tsx), [프론트 main 관리자 로그인](https://github.com/Start-Up-10th/CheckUp-Client/blob/24c72c2da7e0fef257c79f6cfc41f68b6f86f120/web/src/app/admin/%28auth%29/login/page.tsx), [서버 복귀 경로 검증](https://github.com/Start-Up-10th/CheckUp-server/blob/cfd612cd5d34b2772c02aed03790be28a0ff4738/src/main/java/com/checkup/checkup/domain/auth/service/LoginRedirectPath.java).

### 2. `/auth/me`와 화면에 필요한 정보 차이

서버와 프론트의 현재 DTO는 name·role만 일치한다. 학생 홈·마이페이지는 여전히 mock 이름·학번·호실을 사용한다. 로그인 완료 화면은 동의·등록 상태를 몰라 모든 일반 학생을 `/consent`로 보낸다. 동의 저장과 얼굴 등록 완료 처리도 현재 UI에서는 서버와 연결되지 않았다.

변경 방향: `/auth/me`에 canonical 학생 ID, 표시용 프로필, CheckUp DB에서 조회한 온보딩 상태를 추가한다. 이 상태는 DataGSM OAuth가 제공하는 정보가 아니다. 동의 저장 및 얼굴 등록 API의 성공 결과로 갱신해야 한다. 응답 필드 추가와 함께 프론트의 응답 검증·타입·mock 의존을 바꾼다.

근거: [로그인 완료 분기](https://github.com/Start-Up-10th/CheckUp-Client/blob/156915fd186b0595d40c718a126e0b44f025c9fc/web/src/components/student/StudentLoginComplete.tsx), [학생 홈](https://github.com/Start-Up-10th/CheckUp-Client/blob/156915fd186b0595d40c718a126e0b44f025c9fc/web/src/components/student/StudentMain.tsx), [마이페이지](https://github.com/Start-Up-10th/CheckUp-Client/blob/156915fd186b0595d40c718a126e0b44f025c9fc/web/src/components/student/StudentMyPage.tsx), [동의 화면](https://github.com/Start-Up-10th/CheckUp-Client/blob/156915fd186b0595d40c718a126e0b44f025c9fc/web/src/components/student/StudentConsent.tsx), [얼굴 화면](https://github.com/Start-Up-10th/CheckUp-Client/blob/156915fd186b0595d40c718a126e0b44f025c9fc/web/src/components/student/StudentFaceCapture.tsx).

### 3. null을 받을 수 있는 SDK 타입과 서버 필수값 가정

SDK의 ID는 Long, 학년·반·번호·학번은 Integer다. 현재 MemberService는 필수값 검증 없이 primitive int 저장 함수에 전달한다. null이면 자동 언박싱 NPE가 가능하다. `student.id`도 검증하지 않고 nullable DB 컬럼에 저장할 수 있다. develop callback은 이런 예외를 OAuth 실패 리다이렉트로 처리하지 못하고 500 JSON을 반환할 수 있다.

이는 공급자가 정상 학생 값을 실제로 누락한다는 관측이 아니다. 공개 공급자 스키마의 필수값과 SDK가 역직렬화할 수 있는 null 경계를 구분해 검증해야 한다. 미배정 호실 null과 교사의 student 부재는 정상 케이스로 취급한다.

변경 방향: SDK 객체를 내부 모델로 변환하는 어댑터에서 필수 식별자·이름·학생 필수 숫자 필드를 검증한다. 잘못된 응답을 명시적 오류로 처리하고, 임의의 0·학번·DB PK로 대체하지 않는다. 검증 후에만 회원/학생 저장 및 세션을 생성한다.

근거: [MemberService](https://github.com/Start-Up-10th/CheckUp-server/blob/cfd612cd5d34b2772c02aed03790be28a0ff4738/src/main/java/com/checkup/checkup/domain/member/service/MemberService.java), [canonical ID 컬럼](https://github.com/Start-Up-10th/CheckUp-server/blob/cfd612cd5d34b2772c02aed03790be28a0ff4738/src/main/resources/db/migration/V2__add_student_datagsm_student_id.sql), [전역 오류 처리](https://github.com/Start-Up-10th/CheckUp-server/blob/cfd612cd5d34b2772c02aed03790be28a0ff4738/src/main/java/com/checkup/checkup/global/exception/GlobalExceptionHandler.java).

### 4. 웹 로그아웃과 서버 세션 종료 차이

프론트의 학생·관리자 로그아웃은 화면 이동만 수행한다. 서버의 POST logout을 호출하지 않으므로 이 동작만으로 SESSION이 종료되지는 않는다.

변경 방향: 공통 logout 함수에서 POST + credentials를 보내고 204 뒤 로그인 화면으로 이동한다. 로그아웃 뒤 같은 쿠키의 `/auth/me`가 401인지 검증한다. QR·인식 운영 세션 정리는 관련 서버 도메인에 연결한다.

근거: [학생 로그아웃](https://github.com/Start-Up-10th/CheckUp-Client/blob/156915fd186b0595d40c718a126e0b44f025c9fc/web/src/lib/student/use-logout.ts), [관리자 로그아웃](https://github.com/Start-Up-10th/CheckUp-Client/blob/156915fd186b0595d40c718a126e0b44f025c9fc/web/src/lib/admin/use-admin-logout.ts).

### 5. AI 연동 시 ID 변환을 명시해야 함

현재 Spring의 공개 얼굴 연동은 아직 구현되지 않았다. AI 입력 `candidates[].student_id`와 출력 `recognition.studentId`는 DataGSM student.id 기반 문자열이다. 출석 저장은 Spring Student.id FK를 사용한다. 같은 이름의 studentId를 그대로 전달하면 다른 ID 체계를 섞게 된다.

변경 방향: Spring→AI에서 `Long.toString(student.datagsmStudentId)`를 사용한다. AI 결과를 받을 때 canonical ID로 Student를 찾은 뒤 그 DB PK로 출석을 처리한다. 기존 canonical ID가 비어 있는 학생은 검증된 로그인/동기화로 채우고, 값이 없는 상태로 AI 등록·인식 후보에 넣지 않는다.

### 6. 설정과 오류 표시 — 연동 검증 필요

- 프론트 `/api` rewrite는 서버로 요청을 전달하지만 `API_PROXY_TARGET=` 빈 값에는 `??` 기본값이 적용되지 않는다. 빈 문자열 정규화와 유효 origin 검증을 추가한다. 실제 환경에서 이 값이 비어 있는지는 확인하지 않았다.
- 웹은 서버가 보내는 `error=CODE`를 현재 generic 로그인 실패로 처리한다. 형태는 호환되지만 관리자 권한 부족 안내 등 요구된 문구는 별도 연결이 필요하다.
- 서버에서 credential CORS 설정이나 cookie domain 설정은 확인되지 않았다. 프론트 프록시와 직접 API 호출을 섞지 말고 공개 origin·callback URL·쿠키가 붙는 host를 함께 결정한다. 권장 구성은 한 공개 origin의 `/api/v1/**`를 Spring으로 라우팅하는 것이다. 별도 API origin을 쓰면 credentials CORS와 host별 쿠키 전달을 확인한다.
- 운영에서는 SESSION Secure 설정과 HTTPS를 함께 적용한다. same-site만 같아도 host-only 쿠키가 다른 host로 전달되는 것은 아니다.
- 세션 role은 로그인 시점 값이다. 역할 변경 후 기존 세션을 무효화하거나 요청마다 최신 권한을 확인하는 작업은 [서버 issue #25](https://github.com/Start-Up-10th/CheckUp-server/issues/25)와 연결한다.

근거: [프론트 proxy 설정](https://github.com/Start-Up-10th/CheckUp-Client/blob/156915fd186b0595d40c718a126e0b44f025c9fc/web/next.config.mjs), [프론트 로그인 오류 UI](https://github.com/Start-Up-10th/CheckUp-Client/blob/156915fd186b0595d40c718a126e0b44f025c9fc/web/src/app/%28user%29/login/page.tsx), [서버 쿠키 설정](https://github.com/Start-Up-10th/CheckUp-server/blob/cfd612cd5d34b2772c02aed03790be28a0ff4738/src/main/resources/application.yaml), [서버 SecurityConfig](https://github.com/Start-Up-10th/CheckUp-server/blob/cfd612cd5d34b2772c02aed03790be28a0ff4738/src/main/java/com/checkup/checkup/global/security/SecurityConfig.java).

### 7. 현재 공식 문서와 SDK 1.6.0의 학생 역할 enum 차이

공식 userinfo 문서는 `GRADUATE`, `WITHDRAWN`을 학생 역할로 안내하지만 SDK 1.6.0에는 `GENERAL_STUDENT`, `STUDENT_COUNCIL`, `DORMITORY_MANAGER`만 있다. SDK가 사용하는 Gson은 지원하지 않는 enum 문자열을 null로 읽는다. 따라서 두 역할이 반환되면 서버의 null role 검사에서 인증이 거부된다. 현재 구현이 이 값을 일반 학생이나 관리자로 승격하는 것은 아니다.

변경 방향: 공급자 문서와 SDK가 표현하는 역할을 동일하게 맞출 수 있는 SDK 업데이트/공급자 수정 여부를 확인하고, 알려진 졸업·자퇴와 형식이 잘못된 응답을 구별한다. 지원하지 않는 값을 GENERAL_STUDENT로 대체하지 않는다. 실제 공급자가 이 역할을 반환하는지, SDK의 `isLeaveSchool`이 어떤 상태를 뜻하는지는 실연동에서 확인하며 자동 학생 삭제 정책을 새로 만들지 않는다.

공식 문서의 학년·반·번호·학번은 필수 Int, 호실/층은 nullable Int다. SDK는 모두 참조형 Integer이므로 항목 3의 null 검증은 불완전한 공급자 응답에 대한 방어다.

근거: [현재 공식 userinfo 문서](https://docs.datagsm.kr/oauth/http/userinfo), [SDK StudentRole](https://github.com/themoment-team/datagsm-oauth-sdk-java/blob/d02c9b0608718a4d98994f82a969d496b97980ca/src/main/java/team/themoment/datagsm/sdk/oauth/model/StudentRole.java), [SDK Student](https://github.com/themoment-team/datagsm-oauth-sdk-java/blob/d02c9b0608718a4d98994f82a969d496b97980ca/src/main/java/team/themoment/datagsm/sdk/oauth/model/Student.java), [Gson enum 처리](https://github.com/google/gson/blob/gson-parent-2.11.0/gson/src/main/java/com/google/gson/internal/bind/TypeAdapters.java).

## 제안하는 `/auth/me` 계약

기존 name·role을 유지하고 다음 정보를 추가하는 초안이다. 정확한 DTO 이름과 nullable 규칙은 서버·프론트 담당자가 같은 계약에서 확정한다.

```json
{
  "name": "테스트 학생",
  "role": "STUDENT",
  "student": {
    "studentId": "123",
    "studentNumber": 1101,
    "grade": 1,
    "classNumber": 1,
    "number": 1,
    "dormitoryRoom": 301
  },
  "onboardingStep": "CONSENT"
}
```

- studentId는 DataGSM canonical ID의 문자열이다. 교사는 `student: null`, 자치위원 ADMIN은 student 정보를 유지한다.
- 호실 미배정은 `dormitoryRoom: null`. 층은 유효 호실에서 계산한다.
- onboardingStep 초안은 `ADMIN_HOME`, `CONSENT`, `FACE_ENROLLMENT`, `STUDENT_HOME`이다. 최신 필수 동의와 실제 얼굴 등록 상태를 서버 DB에서 조회해 정한다.
- 일반 학생은 상태에 따라 `/consent` → `/face` → `/main`으로 이동한다. 관리자는 `/admin`으로 이동한다.
- QR 복귀 문맥은 유지한다. 일반 학생의 필요한 온보딩을 건너뛰지 않도록 상태를 먼저 판단하고, 최종 QR 제출 시 서버가 만료·종료·학생 자격을 다시 검사한다.
- 동의 상태·등록 상태 도메인을 구현하지 않은 채 상수 응답이나 mock 데이터를 운영 상태처럼 반환하지 않는다.
- `OAuthLoginResponse`는 현재 main의 콜백 반환 DTO이기도 하므로, `/me` 확장은 별도 CurrentMemberResponse로 분리해 웹 복귀와 독립적으로 관리하는 것을 권장한다.

## 변경 순서와 완료 기준

| 순서 | 작업 / 수정 대상 | 완료 기준 |
| --- | --- | --- |
| 1 | 서버·웹 배포 SHA와 계약 기준 고정. 서버 develop의 AuthController/state/redirect와 프론트 develop auth-api/login-complete 기능을 함께 릴리스 후보에 포함 | 학생·관리자 버튼 → DataGSM → 웹 완료 화면 → 쿠키 포함 `/me` 200. 실패는 웹 로그인 오류 화면 |
| 2 | 서버 SDK 어댑터와 MemberService 필수값 검증, 교사/미배정 호실 처리. 공식 SDK와 userinfo enum 차이 확인 | 잘못된 응답은 명시적 오류. NPE/DB 오류로 로그인 화면을 이탈하지 않음. 저장/세션 생성 전에 검증 |
| 3 | `/me` OpenAPI 계약과 CurrentMemberResponse, 학생 조회, 실제 온보딩 상태 구현 | 일반 학생·자치위원·교사 응답과 canonical ID 의미 고정. `/me`는 인증된 본인만 조회 |
| 4 | 프론트 CurrentMember 타입/검증, 홈·프로필 mock 교체, 상태별 분기, 동의 저장·얼굴 등록 성공 처리, logout 연결 | 기존 등록자는 동의/촬영 반복 없음. UI 타이머만으로 등록 완료 처리하지 않음. logout 후 `/me` 401 |
| 5 | Spring→AI canonical ID 변환과 결과→DB PK 조회, 쿠키/proxy/운영 callback 설정 정렬 | 서로 다른 member PK·student PK·canonical ID·학번 fixture로 오매핑 없음. 실제 얼굴 연동은 별도 제품 테스트 |
| 6 | 공통 하네스의 auth 계획·신원 명세·수용 시나리오·계약을 선택한 릴리스 기준으로 갱신 | main/develop 상태와 미구현 영역을 구별. entire-AI 기존 수정은 선택적으로 반영하고 전체 upstream 덮어쓰기 금지 |

계획은 제품 정책의 변경을 승인한 것으로 해석하지 않는다. 기존 `REQ-AUTH-001~005`, `ACC-AUTH-001~005`, AI canonical ID 규칙을 구현으로 맞추는 작업이다. `userinfo`는 현재 로그인한 한 명의 정보이므로 전체 학생 명단은 별도 학생 OpenAPI와 페이지네이션에서 조회한다.

## 검증 계획과 이번 확인 범위

- 일반 학생, 학생회, 자치위원, 기숙사 교사, 비기숙사 교사, 비활성 계정의 역할과 student nullable 응답.
- 최상위 계정 ID·DB 회원 ID·DB 학생 ID·canonical ID·학번을 모두 다르게 구성한 합성 fixture.
- 필수 ID/학년/반/번호/학번 누락, 미배정 호실 null, 지원하지 않는 role/objectType, SDK enum 미지원 값.
- state 누락·만료·재사용, provider error callback, 토큰 교환 실패, 성공/실패 리다이렉트, 상대 복귀 경로 검증.
- 쿠키 포함 `/me`, 다른 사용자 조회 차단, 새 세션 발급, logout 뒤 동일 쿠키 401, 실제 배포 host에서 쿠키 전달.
- 동의 전·동의 후 미등록·등록 완료 학생 및 관리자 분기, QR 복귀 시 만료 재검사.

이번에는 고정 커밋의 소스, 공식 공급자 계약, 기존 테스트와 로컬 명세를 대조했다. 실제 학교 계정 로그인, DataGSM 토큰/userinfo 호출, 브라우저 E2E, 서버/프론트 제품 테스트와 배포는 실행하지 않았다. 하네스 문서 검사는 아래 실행 기록에 별도로 적는다.

### 실행 기록

- `npm.cmd run harness:check`: 통과. 38 REQ·38 수용 시나리오·59 Markdown 파일 검사, 하네스 테스트 23/23 통과.
- 제품 수용 시나리오는 0/38 verified다. 이번 하네스 통과는 OAuth 실연동 성공을 뜻하지 않는다.
