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

### 공개 호환 API

백엔드 API 명세와 호환되는 공개 엔드포인트도 제공합니다.

- `POST /api/v1/face/registration`: `multipart/form-data`의 `images` 파일 배열을 받아 얼굴을 등록하고 `201 {"success": true}`를 반환합니다.
- `GET /api/v1/face/detect`: 같은 `images` 파일 배열을 받아 `201 {"student_id": 7, "success": true}` 형식으로 반환합니다.
- 두 엔드포인트 모두 `Authorization: Bearer {accessToken}`이 필요합니다.
- 등록 중 얼굴 미검출·저조도·대표 데이터 부족은 `422`, 잘못된 이미지·요청은 `400`, 인증 실패는 `401`, 학생 정보 미확인은 `403`, 중복 등록은 `409`입니다. `409`는 등록 API에만 적용됩니다.
- 미확인 또는 다수 얼굴인 공개 감지 결과는 `{"student_id": null, "success": false}`입니다. unknown을 임의의 학생으로 변환하지 않습니다.

공개 감지 응답은 기존 백엔드 계약의 단일 결과 형식이고, 다수 얼굴의 얼굴별 결과가 필요할 때는 아래 내부 세션 API를 사용하세요.

### 2. 얼굴 등록 흐름

1. `POST /internal/v1/face/enrollments/extract`로 `video/webm` 또는 `video/mp4`를 보냅니다.
2. AI 서비스가 최대 약 100개 프레임을 검토합니다.
3. 품질이 충분한 단일 얼굴에서 대표 임베딩 약 20개를 반환합니다.
4. 백엔드는 반환된 `model` 정보와 벡터를 같은 모델 버전으로 관리합니다.

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
