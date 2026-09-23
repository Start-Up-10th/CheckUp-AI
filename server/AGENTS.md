# 백엔드 작업 지침

Java + Spring + PostgreSQL + Redis. 루트 지침과 관련 명세를 읽는다.

- [인증](../docs/spec/identity.md), [출석](../docs/spec/attendance.md), [운영](../docs/spec/operations.md), [공지·봉사](../docs/spec/community.md)가 도메인 기준이다.
- 외부 DataGSM 요청은 어댑터 뒤에 두고 실응답/권한을 확인한다. userinfo를 전체 명단 API라고 가정하지 않는다.
- API는 서버에서 관리자·본인·본인 호실 범위를 검사한다. 클라이언트 role/studentId/success를 그대로 신뢰하지 않는다.
- 봉사 횟수는 관리자 `+1`/`−1` 조정을 지원하고 0 미만을 허용하지 않는다. 재시도는 중복 반영하지 않게 한다.
- 학생+purpose+운영일 출석을 DB 원자성으로 보장한다. Redis는 영속 출석의 유일한 원장이 아니다.
- QR session과 교체 token 수명을 분리한다. 다른 관리자 페이지 종료가 전역 종료가 되지 않게 한다.
- 테스트 가능한 clock을 주입해 08:00 KST·만료·지연 동기화를 검증한다.
- 수동 수정 이후 들어온 과거 이벤트와 새 인증을 구별한다. 삭제된 운영일의 이벤트는 부활시키지 않는다.
- FastAPI는 인식 결과를 제공하고 출석 확정은 백엔드가 담당한다.
- raw 얼굴·벡터·OAuth token을 HTTP body logging과 fixture에서 제외한다.
- 첫 구현에 실제 migration·계약·검증 명령을 함께 추가한다.
