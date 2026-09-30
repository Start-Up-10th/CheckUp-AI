# 기숙사 얼굴 AI 서비스

FastAPI + MediaPipe 기반 얼굴 검출·랜드마크·신원 임베딩 서비스입니다.

백엔드는 AI 결과를 받아 출석 정책과 출석 DB 반영을 담당합니다. 이 서비스는 출석 DB를 직접 변경하지 않습니다.

## 백엔드 연동 가이드

상세 요청·응답 스키마는 [얼굴 AI OpenAPI 계약](contracts/ai-face.openapi.yaml)을 기준으로 사용하세요.

### 1. 실행 및 readiness 확인

Python 3.12와 모델 파일을 준비한 뒤 서비스 토큰과 실측된 비교 임계값을 설정합니다.

```powershell
$env:FACE_SERVICE_TOKEN = "service-token"
$env:FACE_MATCH_THRESHOLD = "0.6"
$env:FACE_MATCH_MARGIN = "0.1"
python -m uvicorn face_api:app
```

- `GET /health/live`: 프로세스 생존 확인
- `GET /health/ready`: 모델과 threshold/margin 준비 확인

`/health/ready`가 `200`일 때만 얼굴 추론 요청을 보내세요.

### 인증 경계와 얼굴 등록

CheckUp 웹은 Spring에 `SESSION` 쿠키로 인증합니다. Spring이 DataGSM OAuth 콜백을 처리하고 사용자·동의·중복 여부를 확인합니다. 브라우저의 세션 쿠키와 DataGSM `accessToken`은 AI 서비스에 보내지 않습니다.

Spring은 AI의 비공개 경로를 `Authorization: Bearer {FACE_SERVICE_TOKEN}`으로 호출합니다. 이 값은 OAuth 사용자 토큰이 아니라 Spring-AI 간 서비스 인증 토큰이며 브라우저에 노출하면 안 됩니다.

얼굴 등록은 Spring 공개 API가 브라우저의 MediaRecorder 영상을 받고, AI의 `POST /internal/v1/face/enrollments/extract`에 `video/webm` 또는 `video/mp4` 원본 body로 전달하는 구조로 둡니다. AI는 대표 벡터와 모델 정보를 반환하며, 얼굴 등록 성공 응답·학생 연결·중복 검사·벡터 저장은 Spring이 담당합니다. AI에는 OAuth 세션 쿠키를 검증하는 공개 등록 경로가 없습니다. CheckUp-server main에는 이 Spring-AI 얼굴 등록 연동이 아직 구현되어 있지 않으므로 실제 연동 완료로 간주하지 않습니다.

### 2. 얼굴 등록 흐름

1. `POST /internal/v1/face/enrollments/extract`에 서비스 Bearer 인증을 넣고 `video/webm` 또는 `video/mp4` 원본 body를 보냅니다.
2. AI 서비스가 최대 약 100개 프레임을 검토합니다.
3. 품질이 충분한 단일 얼굴에서 대표 임베딩 약 20개를 반환합니다.
4. Spring은 반환된 `model` 정보와 벡터를 같은 모델 버전으로 관리하고, 등록 성공·중복·동의 정책을 처리합니다.

원본 영상과 디코딩 프레임은 요청 처리 중에만 사용되며, 처리 후 폐기됩니다.

### 3. 얼굴 인식 흐름

1. `PUT /internal/v1/face/sessions/{session_id}`로 후보 학생의 모델 정보와 벡터를 전달합니다.
2. 프레임마다 `POST /internal/v1/face/sessions/{session_id}/frames`를 호출합니다.
3. `faces[]`를 얼굴별로 처리합니다. 결과를 하나의 학생으로 합치지 마세요.

각 얼굴 결과에는 `trackId`, `bbox`, `landmarks`, `quality`, `recognition`이 포함됩니다.

### 인식 상태 해석

- `KNOWN`: 임계값과 후보 간 margin을 모두 통과했습니다. 이때만 `studentId`를 사용합니다.
- `UNKNOWN`: 후보와 충분히 가깝지 않거나 후보 간 구분이 부족합니다. `studentId`는 반드시 `null`입니다.
- `NOT_ATTEMPTED`: 저조도, 흐림, 작은 얼굴, 극단적 자세 등으로 인식을 시도하지 않았습니다.

MediaPipe의 검출·랜드마크 결과는 학생 신원 확인 결과가 아닙니다. 신원은 별도 임베딩 모델과 후보 벡터 비교로만 판정합니다.

### 오류 및 fallback

- `401`: 서비스 토큰 오류
- `404`: 세션 없음
- `422`: 얼굴·품질·신원 일관성 문제
- `503`: 모델 미준비

`MULTIPLE_IDENTITIES`, `LOW_LIGHT`, `INSUFFICIENT_QUALITY_FRAMES`가 반환되면 학생을 임의 추정하지 말고 재촬영 또는 QR fallback으로 연결하세요.

원본 영상, 프레임, 임시 임베딩을 로그·브라우저 번들·출석 DB에 저장하지 마세요.

## 개발 및 검증

```powershell
python -m pytest -q
python -m ruff check .
npm run harness:check
```

하네스 및 개발 절차는 [AGENTS.md](AGENTS.md), [ai/AGENTS.md](ai/AGENTS.md), `docs/`에서 확인할 수 있습니다. 개인용 기존 README는 `README.local.md`에 보존되어 있으며 Git에는 포함하지 않습니다.
