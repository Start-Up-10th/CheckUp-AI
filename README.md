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

브라우저는 Spring의 `POST /api/v1/face/enrollments`에 `multipart/form-data`의 `video` 파트로 영상을 보냅니다. Spring은 영상을 AI의 `POST /internal/v1/face/enrollments/extract`에 `video/webm` 또는 `video/mp4` 원본 body로 전달하고, AI가 반환한 벡터를 Spring이 학생과 연결해 저장합니다. AI에는 브라우저 로그인이나 공개 등록 경로가 없습니다.

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

## Docker 이미지

FastAPI 이미지는 Python 3.12 CPU 실행 환경과 모델 파일을 함께 담습니다. 모델 바이너리는 Git에 넣지 않습니다. 이미지 빌드 중 [모델 manifest](models/download-manifest.json)의 공식 주소에서 파일을 받고, 파일 크기와 SHA-256을 확인한 뒤 이미지에 복사합니다. XML과 BIN 임베딩 모델 파일은 같은 디렉터리에 들어갑니다.

저장소 루트에서 이미지를 빌드합니다.

```powershell
docker build -t checkup-face-ai:dev .
```

로컬 실행 설정 파일을 만들고, `FACE_SERVICE_TOKEN`과 실제 측정·승인된 `FACE_MATCH_THRESHOLD`, `FACE_MATCH_MARGIN` 값을 채웁니다. 이 파일은 Git에 올리지 않습니다.

```powershell
New-Item -ItemType Directory -Force .local | Out-Null
Copy-Item infra/face-ai.env.example .local/face-ai.env
docker run --rm --env-file .local/face-ai.env -p 8000:8000 checkup-face-ai:dev
```

`GET http://localhost:8000/health/ready`가 `200`이고 컨테이너 상태가 `healthy`여야 사용할 준비가 된 것입니다. Spring에는 컨테이너끼리 통신 가능한 내부 주소를 `FACE_AI_BASE_URL`로 넣고 같은 서비스 토큰을 주입합니다. 브라우저는 FastAPI가 아니라 Spring만 호출합니다.

인식 세션은 FastAPI 프로세스 메모리에 있으므로 우선 이미지 하나·worker 하나로 실행합니다. 여러 worker나 replica를 쓰려면 세션 공유 또는 고정 라우팅을 먼저 설계해야 합니다. 공개 이미지 배포 전에는 모델 바이너리별 배포 조건도 별도로 확인하세요.

## 프론트 연결 안내

### 연결 주소와 로그인

브라우저는 **Spring 공개 주소만** 사용합니다. FastAPI 주소와 `FACE_SERVICE_TOKEN`을 프론트 환경 변수나 브라우저 코드에 넣지 마세요.

Next.js 브라우저 코드에서는 공개 API 주소를 환경 변수로 둡니다. 개발 중 같은 컴퓨터에서 실행한다면 예를 들어 `http://localhost:8080`, 배포 후에는 Spring의 공개 HTTPS 주소를 사용합니다.

```dotenv
NEXT_PUBLIC_API_BASE_URL=http://localhost:8080
```

로그인은 `fetch`가 아니라 브라우저 페이지 이동으로 시작합니다. Spring이 DataGSM으로 이동시키고, 로그인 뒤 `PUBLIC_ORIGIN`에 지정된 웹 주소로 돌려보냅니다.

```ts
const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL!;
window.location.assign(`${apiBaseUrl}/api/v1/auth/login?redirect=/login/complete`);
```

로그인 상태는 `GET /api/v1/auth/me`로 확인하고, 로그아웃은 `POST /api/v1/auth/logout`으로 요청합니다. 브라우저에서 세션 쿠키를 포함하도록 인증이 필요한 API 요청에는 `credentials: "include"`를 넣습니다.

```ts
const response = await fetch(`${apiBaseUrl}/api/v1/auth/me`, {
  credentials: "include",
});
```

`SESSION` 쿠키는 HttpOnly라 프론트 코드가 직접 읽지 않습니다. 브라우저가 요청에 자동으로 붙이도록 두세요. 운영 웹과 API는 같은 site에 배치합니다. 포트나 서브도메인이 달라 origin이 다르면 개발·운영 모두 Spring이 실제 프론트 origin만 CORS 허용 목록에 넣고 credentials를 허용해야 합니다. 현재 Spring Security 설정에는 CORS 허용 설정이 없으므로 브라우저 연동 전에 백엔드 작업이 필요합니다. `Access-Control-Allow-Origin: *`와 credentials를 함께 쓰면 안 됩니다.

### 얼굴 API 연결

학생 얼굴 상태는 `GET /api/v1/face/me`이며 `{ "consented": boolean, "enrolled": boolean }`을 반환합니다. 등록 영상은 Spring 공개 API의 multipart `video` 파트로 전송합니다.

```ts
const form = new FormData();
form.append("video", videoBlob, "face.webm");

const response = await fetch(`${apiBaseUrl}/api/v1/face/enrollments`, {
  method: "POST",
  credentials: "include",
  body: form,
});
```

`FormData`를 보낼 때 `Content-Type`을 직접 지정하지 마세요. 브라우저가 multipart boundary를 포함해 설정합니다. 성공하면 Spring 응답을 화면에 표시하고, 실패하면 Spring 오류 응답의 상태와 오류 코드를 처리합니다.

관리자 카메라 화면은 Spring의 `POST /api/v1/face/sessions`로 세션을 만든 뒤, 각 JPEG/WebP 프레임을 `POST /api/v1/face/sessions/{sessionId}/frames`로 보냅니다. 화면을 나가거나 인식을 마치면 `DELETE /api/v1/face/sessions/{sessionId}`를 호출해 세션을 닫습니다. 이 API들은 로그인한 관리자만 사용할 수 있습니다. 정확한 요청·응답 필드는 Spring Swagger 문서를 기준으로 맞추세요.

- 세션 생성 body는 `{"purpose":"DORMITORY"}` 또는 `{"purpose":"STUDY_ROOM"}`입니다. 응답의 `sessionId`를 다음 요청에 사용합니다.
- 프레임 API는 multipart가 아니라 이미지 원본 바이트를 body로 보냅니다. `Content-Type`은 `image/jpeg` 또는 `image/webp`이며 `X-Frame-Id`는 선택 헤더입니다.
- 세션 생성과 프레임 전송 모두 로그인 쿠키를 포함합니다. `sessionId`는 카메라 화면 단위로 보관하고, 화면 종료 시 해당 세션만 닫습니다.

브라우저 카메라 권한은 HTTPS에서 필요합니다(개발 중 `localhost`는 예외). 영상·프레임·얼굴 벡터를 브라우저 로그나 영구 저장소에 남기지 마세요. Spring API 전체 목록은 Spring 서버의 `/swagger-ui/index.html`에서 확인하고, 이 저장소의 AI OpenAPI는 Spring이 FastAPI를 호출할 때만 참고하세요.

## 데브옵스 배포 안내

### 배포 순서

1. 이 저장소 루트에서 FastAPI 이미지를 빌드합니다. 모델 바이너리는 빌드 중 manifest의 출처·크기·SHA-256을 확인해 이미지에 들어갑니다.

   ```bash
   docker build -t checkup-face-ai:20261003 .
   ```

2. 예시의 날짜 태그는 실제 배포 버전에 맞는 commit 또는 release 태그로 바꿉니다. 이미지를 컨테이너 레지스트리에 올리고 테스트 서버에 배포합니다. 실제 레지스트리와 배포 명령은 팀의 서버 설정에 맞춰 정합니다. `dev`처럼 계속 바뀌는 태그 대신 commit 또는 release별 고정 태그를 사용하세요.
3. FastAPI를 사설 네트워크에 두고 포트 `8000`(또는 플랫폼이 전달하는 `PORT`)을 Spring에서만 접근 가능하게 엽니다. 브라우저에 FastAPI를 공개하거나 프론트에서 직접 호출하지 않습니다.
4. FastAPI에 `FACE_SERVICE_TOKEN`, `FACE_MATCH_THRESHOLD`, `FACE_MATCH_MARGIN`을 secret/environment로 주입합니다. 토큰은 Spring에도 같은 값으로 주입하고, 프론트에는 전달하지 않습니다. 임계값은 실제 운영 전에 측정·승인한 값을 사용하며 빈 값이나 예시 값을 운영에 쓰지 않습니다.
5. FastAPI의 `/health/live`와 `/health/ready`를 확인합니다. `/health/ready`와 컨테이너 상태가 healthy가 된 뒤 Spring의 `FACE_AI_BASE_URL`을 FastAPI의 사설 주소로 설정합니다. Docker Compose에서 같은 네트워크를 쓴다면 서비스 이름 주소(예: `http://face-ai:8000`)를 쓰고, 별도 배포라면 Spring에서 라우팅 가능한 사설 주소를 씁니다. 두 컨테이너가 따로라면 `localhost:8000`은 FastAPI 주소가 아닙니다.
6. Spring을 배포해 Spring→FastAPI 세션·프레임 요청과 등록 요청을 확인합니다. 이후 프론트 설정 `NEXT_PUBLIC_API_BASE_URL`에는 Spring의 공개 주소를 넣습니다.

### 환경 변수와 운영 조건

| 변수 | 설정 위치 | 용도 |
| --- | --- | --- |
| `FACE_SERVICE_TOKEN` | FastAPI와 Spring의 서버 secret | Spring→FastAPI 서비스 인증. 두 곳에 같은 값을 설정 |
| `FACE_MATCH_THRESHOLD`, `FACE_MATCH_MARGIN` | FastAPI 환경 변수 | 인식 판정 기준. 실제 측정된 값을 사용 |
| `FACE_AI_BASE_URL` | Spring 환경 변수 | FastAPI의 내부 주소 |
| `PORT` | FastAPI 실행 환경 | 수신 포트. 기본값 `8000` |
| `PUBLIC_ORIGIN` | Spring 환경 변수 | 로그인 완료 후 브라우저가 돌아갈 프론트 주소 |
| `DATAGSM_REDIRECT_URI` | Spring/DataGSM 설정 | Spring의 `/api/v1/auth/callback` 주소 |
| `NEXT_PUBLIC_API_BASE_URL` | 프론트 공개 환경 변수 | 브라우저가 호출할 Spring 주소. secret은 넣지 않음 |

얼굴 인식 세션은 프로세스 메모리에 저장되므로 초기에는 FastAPI worker와 replica를 각각 하나로 둡니다. 여러 개로 늘리려면 세션 고정 라우팅 또는 공유 저장 구조를 먼저 마련해야 합니다. CPU 추론으로 구성했으며, 서버 메모리·CPU 용량과 실제 첫 기동 시간을 배포 대상에서 측정하세요. GPU가 있다고 가정하지 않습니다.

실제 배포 전에 웹과 API의 same-site 주소, HTTPS, CORS의 정확한 프론트 origin, DataGSM callback, Spring에서 AI 사설 주소로의 통신, 토큰 secret 주입을 확인합니다. 현재 문서는 이미지와 연결 방법을 설명하며 레지스트리·GitHub Actions 배포·특정 클라우드 설정이나 실제 서버 배포까지 구성한 것은 아닙니다.

## 개발 및 검증

```powershell
python -m pytest -q
python -m ruff check .
npm run harness:check
```

하네스 및 개발 절차는 [AGENTS.md](AGENTS.md), [ai/AGENTS.md](ai/AGENTS.md), `docs/`에서 확인할 수 있습니다. 개인용 기존 README는 `README.local.md`에 보존되어 있으며 Git에는 포함하지 않습니다.
