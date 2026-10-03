# notification — 웹 내부 알림 계획

## 담당자·API

- 담당자: 강민우
- `GET /api/v1/notifications`
- `GET /api/v1/notifications/unread`
- `POST /api/v1/notifications/read`

## API

학생 본인의 알림만 다룬다. 알림을 만드는 공개 API는 두지 않고, 서버가 출석·당일 봉사자 지정·공지 처리 안에서 직접 만든다.
시각 필드는 ISO-8601 UTC 문자열이다(QR 계약과 같다).

| API | 설명 | 성공 응답 |
| --- | --- | --- |
| `GET /api/v1/notifications` | 본인 알림 최근 50개, 최신순. 페이지는 두지 않는다. | 200 `{ "hasUnread": boolean, "notifications": [{ "id": number, "type": "ATTENDANCE" \| "VOLUNTEER" \| "NOTICE", "message": string, "createdAt": string, "read": boolean }] }` |
| `GET /api/v1/notifications/unread` | 홈 벨 빨간 점·사이드바 강조용 | 200 `{ "hasUnread": boolean }` |
| `POST /api/v1/notifications/read` | 본인 알림을 모두 읽음 처리. 웹은 알림 목록 화면에 들어오면 호출한다. | 204 |

- 오류: 미로그인 401 `UNAUTHORIZED`, 학생이 아닌 계정 403 `MISSING_STUDENT_INFO`. 형식은 [공통 오류 형식](../../contracts/README.md)을 따른다.
- 목록 조회(`GET`)는 읽음 상태를 바꾸지 않는다. 재시도·미리 불러오기로 읽음 처리되지 않도록 읽음은 `POST`로만 바꾼다.
- `message`는 서버가 만든 표시 문구다. 웹은 `type`으로 문구를 조합하지 않고 그대로 표시하며 상대 시각은 `createdAt`으로 계산한다.
- 알림 클릭 이동은 이번 계약에 넣지 않는다(REQ-COM-005의 담당자 결정 항목).

## 알림 생성

| type | 만드는 때 | 받는 학생 | 원본 |
| --- | --- | --- | --- |
| `ATTENDANCE` | 출석이 실제로 성공 처리될 때. 중복 인증·`DUPLICATE` 결과는 만들지 않는다. | 출석한 학생 | 출석 기록 |
| `VOLUNTEER` | 당일 봉사자로 지정될 때. 지정을 취소하면 그 알림을 지운다. 명단 추가·횟수 `+`/`−`는 만들지 않는다(DEC-020). | 지정된 학생 | 당일 봉사자 지정 |
| `NOTICE` | 새 공지가 등록될 때. 수정·삭제는 만들지 않는다. | 공지 알림 수신(`noticeAlarm`)에 동의한 학생 | 공지 |

- 이 세 유형 외의 알림(얼굴 재등록 요청, QR 만료 임박, 브라우저 푸시)은 만들지 않는다.
- 같은 학생·유형·원본에는 알림을 하나만 둔다. DB unique 제약으로 막아 재시도·동시 요청·중복 인증이 알림을 늘리지 않게 한다.
- 알림 생성은 원본 처리(출석 저장, 당일 봉사자 지정, 공지 등록)와 같은 트랜잭션에서 한다. 원본이 취소되면 알림도 남지 않는다.

## 보관

- `ATTENDANCE` 알림은 당일 출석 기록과 같은 08:00 KST 경계에서 폐기한다(DEC-009). 출석 시각이 알림에 남아 과거 출석을 우회 보관하지 않게 한다.
- `VOLUNTEER`·`NOTICE` 알림의 보관 기간은 운영 담당 결정 항목이다. 정해지기 전까지 목록은 최근 50개만 보여준다.

## 계약 보완

- [ ] 공지 CRUD API가 없어 `NOTICE` 알림은 공지 등록 구현과 함께 연결한다.
- [ ] 당일 봉사자 지정·취소 API 구현과 함께 `VOLUNTEER` 알림 생성·삭제를 연결한다.
- [x] 구현 후 `contracts/`에 OpenAPI를 추가한다([notification.openapi.yaml](../../contracts/notification.openapi.yaml)).
- [ ] `VOLUNTEER`·`NOTICE` 알림 보관 기간을 운영 기록으로 확정한다.

## 기준·검증

- 요구사항: `REQ-COM-004`, `REQ-COM-005`, `REQ-COM-006`, `REQ-ATT-002`
- 수용 시나리오: `ACC-COM-004`, `ACC-COM-005`, `ACC-COM-006`, `ACC-ATT-002`
- 세 유형만 생성되고, 중복 인증·재시도로 알림 수가 늘지 않는지 확인한다.
- 공지 알림이 `noticeAlarm` 동의 학생에게만 생기고, 미동의 학생도 공지 목록은 볼 수 있는지 확인한다.
- 다른 학생의 알림이 목록·미확인 여부·읽음 처리에 섞이지 않는지 확인한다.
- 읽음 처리 후 `hasUnread`가 false가 되고, 목록이 최신순인지 확인한다.
- 08:00 KST 이후 전날 `ATTENDANCE` 알림이 남지 않는지 테스트 clock으로 확인한다.
