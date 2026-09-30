# entire-AI 로컬 작업 기록

`entire-AI`의 하네스나 AI 기능을 사용하면서 생긴 설계 결정, 명세 변경, 검증 결과, 통합 작업은 이 파일에 기록한다.

기록 명령:

```powershell
npm run harness:worklog -- "작업 내용과 검증 결과"
```

자동 기록이 아니라 작업 단위가 끝날 때 의미 있는 요약을 남긴다. 원본 영상·프레임·토큰·개인정보는 기록하지 않는다.

## 기록

- 2026-09-26: `ALL_harness`를 하네스 원본으로, `AI-feat`를 AI 작업 원본으로 분리하고 `entire-AI`에서 최종 통합하는 작업 흐름을 정의함.

- 2026-09-26: ALL_harness 동기화, AI-feat 허용 목록 통합, 통합 훅 안내와 작업 기록 규칙 추가; harness:check 38/38 요구사항 및 21개 테스트 통과

- 2026-09-26: harness:sync:upstream이 ALL_harness를 origin/main으로 fetch/reset한 뒤 entire-AI에 동기화하도록 고정

- 2026-09-26: ALL_harness에 없는 entire-AI 전용 훅과 통합 파일을 preservePaths로 고정하고 삭제 방지 회귀 테스트를 추가

- 2026-09-29: 공식 MediaPipe FaceLandmarker task 및 OpenVINO face-reidentification-retail-0095 2023.0 FP32 XML/BIN 다운로드. 기존 0바이트 파일 교체. OpenVINO 공식 SHA384/크기, MediaPipe ZIP CRC 검증 통과. models/download-manifest.json에 출처와 SHA256 기록. 실제 추론과 카메라 검증은 미실행.

- 2026-09-29: readiness 503 진단: 실행 프로세스에서 FACE_MATCH_THRESHOLD 및 FACE_MATCH_MARGIN 미설정 확인. 실제 MediaPipe/OpenVINO 로드, 빈 이미지 검출, 합성 입력 256차원 정규화 임베딩 검사 통과. .local/face-dev.env에 로컬 테스트 설정 및 모델 절대 경로 저장, .venv 환경으로 localhost:8000 재시작 후 live/ready HTTP 200 확인. 임계값 0.6/마진 0.1은 미보정 테스트 값이며 실제 얼굴 정확도 미검증.

- 2026-09-29: 로컬 검증 도구 .local/face_lab.py 및 face-lab.html 추가, http://127.0.0.1:8001 실행. 카메라는 동의 후 수동 시작, 등록영상과 프레임을 기존 AI API로 전달, 벡터는 로컬 서버 메모리만 보관. 세션 격리/만료/삭제재시도/등록실패/입력제한 5개 테스트와 lint/JS 초기화 검사 통과. 실제 AI에 합성 JPEG/WebM을 보내 얼굴없음/등록거절/세션삭제 확인. 브라우저 제어 연결이 없어 시각 QA와 실제 카메라/사람 정확도 검증은 미실행. 사용법 .local/README-face-lab.md.

- 2026-09-29: 얼굴 인식 UI AI_ERROR 재현. 실제 MediaPipe landmarks가 numpy.float32라 FastAPI/Pydantic JSON 직렬화가 500으로 실패함. face_models detect에서 native float 좌표 변환, face_api 프레임 응답에서도 경계 변환. Mock API 회귀테스트가 이전 코드에 실패하고 수정 후 AI 서비스 전체9 + 로컬도구5 총14 통과. Ruff 통과. AI-feat→entire-AI 허용 경로 통합. 수정된 AI를 127.0.0.1:8000에서 재시작, readiness200; 로컬 UI 서버를 통해 실제 모델로 빈 JPEG POST 200과 얼굴0개, 세션 정리 확인. 사람/실제 카메라 정확도는 미검증.

- 2026-09-29: 얼굴 등록 요청을 MediaRecorder video multipart 업로드로 변경하고 공통 영상 추출 처리를 내부 추출 API와 공유. 합성 MP4 등록 회귀검증, AI 테스트 10 passed, Ruff 및 harness:check 23 passed; 실제 브라우저/Spring 연동은 미검증.
- 2026-09-30: harness:sync:upstream이 ALL_harness만 origin/main으로 갱신하도록 변경. entire-AI 복사 단계 제거.
- 2026-09-30: CheckUp-server main의 DataGSM OAuth Authorization Code+PKCE와 SESSION cookie 인증에 맞춰 AI 사용자 access-token 프로토타입 경로/설정을 제거하고 모든 얼굴 API를 Spring→AI FACE_SERVICE_TOKEN bearer 내부 계약으로 제한. FastAPI Swagger와 OpenAPI를 동영상 raw body·벡터 응답·에러 응답 타입에 맞추고 인증/얼굴 계획 문서를 갱신. AI 테스트 12 통과, Ruff 통과, OpenAPI YAML 파싱 및 harness:check(38 요구사항·38 시나리오/23 테스트) 통과. 실제 CheckUp-server→AI 얼굴 API 연동은 main에 없어 미검증.
