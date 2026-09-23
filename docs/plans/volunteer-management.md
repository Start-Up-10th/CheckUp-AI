# volunteer-management — 봉사 관리 계획

## 담당자·API

- 주 담당자: 김성찬
- 공동 담당자: 강민우
- `POST /api/v1/volunteer/{student_id}`
- `DELETE /api/v1/volunteer/{student_id}`
- `PATCH /api/v1/volunteer/{student_id}/count/increase`
- `PATCH /api/v1/volunteer/{student_id}/count/decrease`
- `GET /api/v1/volunteer`

## 구현

- 관리자만 봉사자 추가·제외·명단 조회
- 봉사자 제외 후 누적 횟수 유지
- 목록의 `+`/`−` 클릭으로 1회 즉시 가감하고 조정 날짜 기록; 활동명은 비움
- 0회이면 `−`를 비활성화하고 서버도 음수 누적을 거부
- 명단 추가·제외와 봉사 1회 적립을 별도 동작으로 유지
- 학생 본인 누적 조회는 `student-attendance.md`와 범위를 맞춘다.

## 계약 보완

- [ ] `student_id` path/body는 서버에서 존재 학생·관리자 권한을 검증한다.
- [ ] 같은 클릭의 재시도는 idempotency로 막고 새 클릭은 별도 1회로 처리한다.
- [ ] 증가·차감 API 모두 관리자 권한과 학생 존재 여부를 확인하고, 재시도 멱등성을 보장한다.
- [ ] 차감은 0회 미만이 되지 않도록 원자적으로 검증한다.
- [ ] 공지 CRUD·내부 알림 API는 현재 명세에 없으므로 임의 구현하지 않는다.

## 기준·검증

- 요구사항: `REQ-AUTH-003`, `REQ-COM-001~005`, `REQ-UI-004~006`
- 수용 시나리오: `ACC-AUTH-003`, `ACC-COM-001~005`, `ACC-UI-004~006`
- 일반 학생이 봉사 명단·타인 횟수·관리 mutation을 호출하지 못하게 한다.
- 추가 중복, 제외 후 재추가, 두 번의 새 클릭, 동일 요청 재전송을 구분한다.
- 봉사 누적은 08:00 출석 정리 때 삭제하지 않는다.
