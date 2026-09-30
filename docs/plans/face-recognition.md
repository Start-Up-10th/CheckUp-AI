# face-recognition — 얼굴 등록·인식 계획

## 담당자·API

- 담당자: 임서하
- AI private API contract: [`contracts/ai-face.openapi.yaml`](../../contracts/ai-face.openapi.yaml)
- Enrollment extraction: `POST /internal/v1/face/enrollments/extract`
- Recognition: `PUT /internal/v1/face/sessions/{session_id}`, `POST /internal/v1/face/sessions/{session_id}/frames`, `DELETE /internal/v1/face/sessions/{session_id}`
- The browser authenticates to Spring with its `SESSION` cookie. It must not call AI endpoints or receive `FACE_SERVICE_TOKEN`.

## 구현

- 동의 완료 학생의 휴대폰 최초 얼굴 등록
- 진입 즉시 카메라 자동 실행, 카운트다운 → 촬영 중 → 완료 3단계로 진행; 셔터 버튼 없음
- `다시 찍기`는 촬영본을 폐기하고 카운트다운부터 반복, `완료`는 등록 요청 후 학생 홈으로 이동
- 약 100프레임 품질 평가와 약 20개 대표 벡터 저장
- 원본 영상·프레임을 성공·실패·취소·오류 후 즉시 폐기
- MediaPipe 검출/랜드마크와 신원 임베딩 모델 분리·실측
- 관리자 카메라의 목적별 인식 세션, 다수 얼굴 트랙, unknown, 실패 안내
- AI 결과만 반환하고 권위 있는 출석 확정은 Spring이 담당

## 계약 보완

- [ ] Spring 공개 등록 API는 `SESSION` 세션에서 학생을 확인하고 동의·중복 여부를 검사한다. 실제 Spring API 경로와 request/response는 server 구현자와 별도 계약한다.
- [ ] Spring은 MediaRecorder 영상 body를 AI `POST /internal/v1/face/enrollments/extract`에 raw `video/webm` 또는 `video/mp4`로 전달하고, AI 대표 벡터 응답을 저장한다.
- [ ] Spring은 AI 호출에 `FACE_SERVICE_TOKEN`만 사용한다. DataGSM OAuth `accessToken`과 `SESSION` 쿠키는 AI에 전달하지 않는다.
- [ ] CheckUp-server main에 AI 연동 client/얼굴 API가 추가되면 이 OpenAPI와 Spring DTO의 제공자·소비자 계약 테스트를 맞춘다.
- [ ] Spring 출석 API가 AI의 얼굴별 `trackId`, known/unknown, `studentId`, score, model version을 어떻게 반영하는지 별도 계약한다. unknown ID는 `null`로 둔다.
- [ ] unknown을 임의 학생 ID로 바꾸지 않고 `null` 신원으로 전달한다.
- [ ] 얼굴 인식 결과의 Spring 출석 반영과 offline sync 계약을 `qr-attendance.md`와 맞춘다.
- [ ] 브라우저 오프라인 인식은 실제 모델 실행을 검증하기 전 지원 완료로 표시하지 않는다.

## 기준·검증

- 요구사항: `REQ-FACE-001~008`, `REQ-ATT-002`, `REQ-ATT-007`, `REQ-UI-005~006`
- 수용 시나리오: `ACC-FACE-001~008`, `ACC-ATT-002`, `ACC-ATT-007`, `ACC-UI-005~006`
- 같은 사람·다른 사람·미등록·저조도·다수 얼굴·점수 경계를 승인된 테스트 데이터로 확인한다.
- 성공·실패 얼굴의 이름·실패 횟수·출석 상태를 섞지 않는다.
- raw 얼굴·프레임이 DB·캐시·로그·임시 파일·백업에 남지 않는지 확인한다.
- 벡터 삭제 후 기기 캐시와 백업 복원에서 재출현하지 않는지 확인한다.
