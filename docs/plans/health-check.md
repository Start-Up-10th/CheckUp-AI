# health-check — 서비스 상태 확인 계획

## 담당자·API

- 담당자: 김준수
- `PATCH /api/v1/health`

## 구현

- 로그인 없이 호출 가능한 운영 상태 API로 제공한다.
- 전체 HealthIndicator가 정상이면 `{ "status": "UP" }`를 반환한다.
- 필수 상태가 `DOWN` 또는 `OUT_OF_SERVICE`이면 `503`과 `{ "status": "DOWN" }`을 반환한다.
- 일반 API envelope·`requestId`로 감싸지 않는 Actuator 표준 응답을 유지한다.
- `show-details=never`로 DB·Redis 주소나 상세 장애 원인을 노출하지 않는다.

## 확인 사항

- [ ] 명세의 `PATCH` method가 실제 Actuator 노출 방식과 호환되는지 확인한다.
- [ ] 인증 없이 접근되며 민감한 health detail은 외부에 보이지 않는지 확인한다.
- [ ] DB·Redis 장애별 상태와 복구 후 상태를 통합 테스트한다.
- [ ] Docker Compose health check와 배포 readiness 기준에 연결한다.

## 기준

- 요구사항: `REQ-OPS-001~002`
- 수용 시나리오: `ACC-OPS-001~002`

health 통과는 제품 기능 완료나 배포 완료를 의미하지 않는다.
