---
name: dorm-verify
description: Verify dormitory attendance changes against the requirements, acceptance scenarios, API contracts, authorization, QR lifetime, duplicate processing, and data deletion rules. Use for review or completion checks.
---

# 기숙사 변경 검증

1. 변경 파일과 해당 디렉터리의 지침을 읽고 영향받은 REQ를 찾는다.
2. [검증 기준](../../../docs/verification.md)에 따라 문서/하네스 검사와 제품 테스트를 구분한다.
3. [수용 시나리오](../../../tests/acceptance/scenarios.json)에서 성공뿐 아니라 권한·중복·만료·08시·다수 얼굴·개인정보 폐기를 확인한다.
4. 실제 존재하는 서비스 명령을 실행한다. 미구현 서비스나 mock-only 검사를 실제 카메라/학교 OAuth 검증으로 보고하지 않는다.
5. `npm run harness:check`를 실행한다. 원본 스킬 변경 시 Claude 동기화본과 동일한지 확인한다.
6. 결함은 위치, 재현 조건, 영향, 수정 방향으로 보고한다. 검증 요청만으로 외부 배포나 정책 변경을 수행하지 않는다.

개인정보가 있는 실영상·벡터·토큰을 출력이나 테스트 증빙에 넣지 않는다. 미검증은 실패/통과와 구별한다.
