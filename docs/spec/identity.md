# 로그인·권한·학생 정보

### REQ-AUTH-001 — DataGSM OAuth

학생과 관리자는 DataGSM으로 로그인한다. 자체 회원가입·비밀번호 입력 폼은 없다.
로그인 버튼은 `DataGSM으로 계속하기`다.

| 항목 | 사용자 제공 값 |
| --- | --- |
| 인가 | `https://oauth.authorization.datagsm.kr/v1/oauth/authorize` |
| 토큰 교환 | `https://oauth.authorization.datagsm.kr/v1/oauth/token` |
| 사용자 정보 | `https://oauth.resource.datagsm.kr/userinfo` |
| 개발 Redirect URI | `http://localhost:3000/callback` |
| 운영 Redirect URI | `https://실제-서비스-주소/callback` |

Client ID·Secret·scope와 정확한 운영 주소는 연동/배포 때 확보한다. 가짜 값을 실서비스 값으로 사용하지 않는다.
실제 인증 없이 화면·도메인 로직 개발은 가능하며 mock 모드는 운영에서 사용하지 않는다.
OAuth state, 콜백 검증, 토큰 교환과 세션 보호는 백엔드 책임이다.
DataGSM 사용자 계정 상태는 `userinfo.status`로 받고 내부에서는 `accountStatus`로 구분한다.
OAuth 요청과 callback 사이의 CSRF 검증값은 사용자 정보가 아닌 `oauthState`로 별도 관리한다.
QR 스캔 후 로그인할 때 인증 대상의 용도와 QR 정보를 보존하되 로그인 완료 시 만료를 다시 검사한다.

근거: SRC-DATAGSM, SRC-USER-UI.

### REQ-AUTH-002 — 데이터 매핑과 명단

| DataGSM | 서비스 내부 의미 |
| --- | --- |
| 최상위 `id` | `externalUserId` |
| `student.id` | 내부 canonical `studentId` |
| `student.studentNumber` | `studentNumber`(화면 표시용 학번) |
| `student.name` 또는 `teacher.name` | `name` |
| `student.dormitoryRoom` | `dormitoryRoom` |
| 최상위 `status` | `accountStatus` |
| 최상위 `objectType` | `subjectType` |
| `student.role` | 학생 관리자 권한 판정 |
| `teacher.department` | 교사 관리자 권한 판정 |

DataGSM `userinfo`는 최상위 `id`, `email`, `role`, `status`, `objectType`과
`student` 또는 `teacher` 중첩 객체를 반환한다. 학생의 식별자는 `student.id`이고
`student.studentNumber`는 화면에 표시하는 학번이다. 둘을 같은 필드로 취급하지 않는다.
DataGSM 원본 DTO의 숫자형 `id`는 원본 경계에서 `Long`으로 처리하고, 기존 내부 계약이
문자열이면 어댑터에서만 문자열로 변환한다.

최상위 `role`은 DataGSM 계정 역할(`USER`/`ADMIN`)이며 서비스의 사감 관리자 권한과
직접 연결하지 않는다. 서비스 내부 Principal은 원본 DTO와 분리해 다음 정보를 갖는다.
학생은 `studentId`, `studentNumber`, `name`, `dormitoryRoom`, `accountStatus`를 매핑하고,
교사는 학생 식별자와 호실을 갖지 않으며 `name`, `accountStatus`를 매핑한다.

층은 유효한 `dormitoryRoom`의 `floor(dormitoryRoom / 100)`으로 계산한다. 소수 나눗셈 결과를 층으로 쓰지 않는다.
전체 학생은 기숙사생이다. 호실 구성과 인원은 DataGSM 배정 정보를 기준으로 만든다.
`userinfo`는 현재 로그인한 한 명의 정보만 반환하므로 전체 학생 명단으로 사용하지 않는다.
전체 학생·호실 명단은 별도 학생 API `GET https://openapi.datagsm.kr/v1/students`를
`X-API-KEY`와 `STUDENT_READ` 권한, 페이지네이션으로 조회한다.
`userinfo`만으로 전체 학생 명단·전학/퇴사 상태를 조회할 수 있다고 가정하지 않는다.
학생 API의 실제 권한·페이지네이션 응답·졸업/전학/퇴사 신호는 연동 단계에서 확인하며,
제공되지 않은 필드나 상태값을 임의로 추가하지 않는다.

근거: SRC-DATAGSM, SRC-INTERVIEW.

### REQ-AUTH-003 — 역할과 접근 범위

사감과 자치위원은 동일한 관리자 권한을 가진다. 학생 관리자 여부는
`objectType == STUDENT`, `student != null`인 경우의 `student.role`로 판별한다.
`student.role`이 `DORMITORY_MANAGER` 또는 `STUDENT_COUNCIL`이면 관리자다.
사감 선생님은 `objectType == TEACHER`, `teacher != null`인 경우의
`teacher.department == DORMITORY`이면 관리자다.
최상위 `role == ADMIN`은 DataGSM 계정 역할일 뿐 서비스 관리자 권한으로 자동 승격하지 않는다.
`status != ACTIVE` 계정, 지원하지 않는 `objectType`, 해당 중첩 객체가 없는 응답은 인증을 거부한다.
QR 생성·얼굴 인식 운영·관리자 전개도·수동 출석 수정·봉사 관리·공지 변경은 관리자 전용이다.
학생은 본인과 본인 호실 화면에서 허용된 정보만 읽는다. 다른 학생 봉사 정보나 얼굴 벡터는 볼 수 없다.
관리자 화면을 숨기는 것뿐 아니라 API에서도 역할을 검증한다. 로그인하지 않으면 로그인으로 이동한다.
관리자 로그인의 권한 부족 문구는 `관리자 권한이 없는 계정입니다.`다.
관리자 로그인 후에는 관리자 홈으로 이동한다. 관리자에게 학생 얼굴 등록을 강제하는 흐름은 만들지 않는다.

근거: SRC-DATAGSM, SRC-INTERVIEW, SRC-ADMIN-UI. 관리자 온보딩 분기는 구현 기본값 DEC-001.

### REQ-AUTH-004 — 최초 동의와 온보딩

학생 최초 이용: DataGSM 로그인 → 개인정보 동의 → 얼굴 등록 → 학생 홈.
이미 완료한 동의·등록은 매 로그인마다 반복하지 않는다. 미등록 학생의 홈 접근은 등록 화면으로 연결한다.

동의 화면은 제목 `서비스 이용에 동의해 주세요`, 안내, 전체 동의, 구분선, 개별 항목, `동의하고 계속하기` 버튼으로 구성한다.

| 항목 | 상태 |
| --- | --- |
| 개인정보 수집 및 이용 동의 | 필수 |
| 얼굴 정보 처리 동의 | 필수 |
| 기숙사 공지 알림 수신 | 선택, 기본 해제 |

필수 두 항목을 모두 선택해야 계속할 수 있다. 전체 동의는 세 항목을 선택한다.
어떤 항목이든 해제하면 전체 동의도 해제한다. 선택 알림을 끄더라도 필수 동의가 충족되면 진행 가능하다.
얼굴 동의 거부 후 QR만 사용하는 흐름은 제공하지 않는다.
모바일 버튼은 하단 고정, 노트북은 중앙 동의 카드 안에 표시한다.
동의 문구의 최종 전문은 학교가 제공하는 문안에 연결한다. 화면 예시를 법적 검토 완료 문구로 표기하지 않는다.

근거: SRC-USER-UI의 `개인정보 동의`, SRC-CONSENT-IMAGE, SRC-INTERVIEW.

### REQ-AUTH-005 — 프로필·로그아웃

프로필 사진 기본값은 비어 있다. 학생이 추후 원하는 사진으로 설정할 수 있다.
얼굴 등록 영상/프레임과 프로필 사진을 연결하거나 재사용하지 않는다.
학생 로그아웃 후 DG 로그인으로 이동한다. 관리자 로그아웃은 컴퓨터·패드의 사이드바/레일 하단에, 휴대폰의 다섯 번째 하단 탭 맨 오른쪽에 둔다.
로그아웃 확인 모달은 없다. 로그아웃은 로그인 세션과 그 사용자가 운영하던 인증 세션을 정리한다.

근거: SRC-INTERVIEW, SRC-USER-UI, SRC-ADMIN-UI. 세션 정리는 구현 기준.
