# 얼굴 인식 지연 개선 기록 — 2026-10-07

사용자가 승인한 범위는 AI 후보 비교·임베딩 최적화와 Spring 프레임 간격 개선이다.
기존 3개 품질 프레임 조건, 모델·전처리, threshold/margin, 응답 계약은 유지한다.
실제 얼굴 데이터 수집이나 임계값 보정, 운영 배포는 이번 작업에 포함하지 않았다.

## 구현

- [CandidateGallery](../../face_pipeline.py)는 세션 PUT 시 정규화한 후보를 연속 float32 행렬에 준비한다. 프레임마다 후보를 재정규화하지 않고 행렬 곱으로 비교한다. 학생별 상위 최대 3개 평균, 1·2위 margin, 동점 순서를 유지한다. 임계값·margin·순위 경계 근처에서는 기존 scalar dot 연산으로 재확인한다.
- [InferenceModels](../../face_models.py)의 `detect_faces()`는 검출·랜드마크·품질만 계산한다. [프레임 API](../../face_api.py)는 트랙별 기존 품질·쿨다운 조건과 설정을 통과한 얼굴에만 `embed_face()`를 호출한다. 처음 두 품질 프레임, 저품질 프레임, 쿨다운에서는 임베딩을 계산하지 않는다. 등록 추출의 `detect()`는 기존처럼 모든 검출 얼굴의 임베딩을 추출한다.
- 세션 교체·삭제·종료는 사용 중인 갤러리를 먼저 지우지 않는다. 처리 중 요청을 별도로 소유하고 마지막 요청이 해제된 뒤 갤러리·트랙을 지운다. 정상 lifespan 종료도 이 해제를 기다리고 런타임을 닫는다.
- 임시 벡터, 정렬 이미지, 요청 이미지·body를 성공·예외·취소 경로에서 정리한다. 0 또는 유한하지 않은 L2 norm은 거부한다. 원본·후보·probe 벡터를 진단 로그에 넣지 않는다. 이는 Python/native 내부의 모든 복사본까지 없다는 증명은 아니다.
- Spring `FaceRecognitionSession`에는 nullable `last_frame_started_at`를 추가했다. 새 세션의 첫 프레임은 즉시 허용한다. claim은 이전 **시작 시각 + 200ms**와 기존 잠금을 한 UPDATE에서 확인하고 시작·활동 시각을 갱신한다. release는 완료 활동 시각만 갱신한다. 300ms 걸린 프레임은 완료 후 추가 200ms를 기다릴 필요가 없다. 동시 처리 잠금, 404 복구 lease/token, AI 호출 전 출석 인증 시각은 유지한다.

Spring 변경은 형제 저장소 `StartUp-Onboding-back/CheckUp-server`의 entity, repository,
`FaceSessionStore`, `FaceRecognitionService`와
`src/main/resources/db/migration/V17__separate_face_frame_start_time.sql`에 있다.

## 진단

AI는 `face_api` logger를 DEBUG로 설정할 때만 `face_frame_timing_ms`를 기록한다.
기존 로깅 설정에서 해당 logger의 level과 handler를 설정한다. Uvicorn 자체 로그 레벨만 변경하면
애플리케이션 logger까지 활성화된다고 보장하지 않는다.

단계는 `read`, `decode`, `detect`, `embed`, `match`, `cleanup`, `total`이다. 실행하지 않은 단계는 생략할 수 있다.
추가 필드는 얼굴·임베딩 개수와 `success`/`error` 결과뿐이다. 세션·학생·프레임 ID, 이미지,
랜드마크, 벡터, 유사도는 기록하지 않는다.

Spring은 기존 Micrometer registry의 `checkup.face.frame.duration`을 사용한다.
태그는 `stage={total,pre_ai,ai,result,release}`, `outcome={success,error,busy,rate_limited}`로 제한한다.
`ai`는 404 복구를 포함하고 `total`은 요청 정리·잠금 해제·이미지 폐기를 포함한다.
새 공개 metrics 경로나 응답 필드는 추가하지 않는다. 계측 오류가 정리 동작을 방해하지 않도록 보호한다.

## 자동 검증

AI 저장소 `StartUp-Onboding-AI/entire-AI`에서 실행했다. 환경은 Windows, Python 3.12.0,
NumPy 1.26.4이며 테스트 입력은 합성 데이터다.

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
npm.cmd run harness:check
.\.venv\Scripts\python.exe benchmarks\face_matching.py --students 1 50 200
```

- pytest: 114개 통과. 제3자 라이브러리 deprecation 경고 3개.
- Ruff: 전체 검사 통과.
- 하네스: 23개 통과, 39 REQ·39 시나리오·61 Markdown 검사 통과. 구현 파일과 벤치마크 링크를 확인할 수 있도록 격리 fixture 복사 목록도 보완했다.
- [gallery 테스트](../../tests/face_service/test_gallery.py): 1·50·200명, 후보 1·2·3·20개, 음수 점수·패딩·상위 3개 평균·동점·threshold/margin 경계, 입력 무변경·폐기 검증.
- [모델 테스트](../../tests/face_service/test_models.py): 품질·원래 픽셀 랜드마크·전처리 유지, 등록 eager 동작, 임시 입력·모델 출력 폐기 검증.
- [프레임 테스트](../../tests/face_service/test_api_latency.py): 3품질 프레임, 5품질 프레임 쿨다운, 4번째 실패 QR, 성공 초기화, 다수 얼굴 분리, 진단 로그 필드, 성공·실패·취소 폐기 검증. 실제 ASGI 스트리밍 요청으로 세션 교체·삭제·종료 중 업로드도 확인했다.

추가로 설치된 OpenVINO 2026.3.1 CPU와 기존 0095 XML을 사용해 합성 128×128 BGR 입력을 두 번
`embed()`에 전달했다. 반환값은 유한한 float32 256차원 단위 벡터였고 재호출 후 첫 반환 복사본도 유지됐다.
실제 `OVDict`의 writable 출력과 입력 blob은 처리 후 0으로 정리됐다. 이는 출력 메모리 정리와 런타임
호환성을 확인하는 검사이며 얼굴 정확도 검사가 아니다. 새 파일·다운로드·실제 얼굴 데이터는 사용하지 않았다.

Spring 저장소에서 `gradlew.bat build`와 `npm.cmd run harness:check`를 실행했다.
실제 로컬 PostgreSQL/Redis를 사용했으며 카메라·AI 실제 서비스 E2E는 실행하지 않았다.
PostgreSQL 저장소 테스트 10개가 첫 프레임, 199ms 거부/200ms 허용, 300ms 처리 후 즉시 시작,
미해제·연장된 lease, 오래된 token, 동시 요청 중 1개 claim, 소유자·inactive·idle 보호,
V16→V17 backfill을 검증한다. 서비스 테스트는 인증 시각 유지, 단계별 계측과 실패 시 정리를 확인한다.
최종 전체 빌드는 53초에 성공했다. 512개 중 511개 통과, 실패/오류 0, 기존 live-AI 선택 테스트 1개 건너뜀이다.
얼굴 서비스 15개와 실제 PostgreSQL 테스트 10개가 통과했다. Spring 하네스는 20개 통과,
39 REQ·39 시나리오 검사 통과다. 초기 계측 또는 release 시작의 시계 장애와 registry 등록 오류가
응답·잠금 해제·permit 반환·이미지 폐기를 방해하지 않는 테스트도 포함했다.

기존 로컬 public 스키마에는 V3 Flyway 체크섬 불일치가 있어 최초 전체 빌드의 context 테스트가 실패했다.
repair/reset을 하지 않고 생성한 독립 스키마에서 전체 빌드를 검증했다. 테스트 후 생성한 스키마만
삭제했으며 기존 데이터·마이그레이션 이력은 변경하지 않았다. 동일 로컬 DB를 기본 설정으로 실행하려면
이 기존 이력 불일치를 별도로 해결해야 한다.

전체 빌드 재현 시 기존 DB와 다른 일회용 스키마를 지정한다. 아래는 테스트용 이름 예시다.
DB·Redis 및 기존 테스트의 비밀이 아닌 설정값은 테스트 환경에 맞게 준비한다.

```powershell
$env:DB_URL='jdbc:postgresql://localhost:5433/checkup?currentSchema=face_latency_check'
$env:SPRING_FLYWAY_SCHEMAS='face_latency_check'
$env:SPRING_FLYWAY_DEFAULT_SCHEMA='face_latency_check'
$env:SPRING_FLYWAY_CREATE_SCHEMAS='true'
.\gradlew.bat build
```

## 후보 비교 벤치마크

[측정 스크립트](../../benchmarks/face_matching.py)는 scalar reference와 갤러리 비교를 같은 프로세스에서
번갈아 실행한다. 준비 비용은 분리하며 warmup 10회, 반복 100회, probe 8개, seed 20261007을 사용한다.
`0.6`/`0.1`은 합성 비교용 설정이고 운영 임계값의 적정성을 증명하지 않는다.

최종 코드 실행 결과:

| 학생 × 후보 | scalar 중앙값 | gallery 중앙값 | gallery p95 | gallery 최초 준비 | 중앙값 비율 |
| --- | --- | --- | --- | --- | --- |
| 1 × 20 | 0.304ms | 0.026ms | 0.030ms | 0.269ms | 11.7배 |
| 50 × 20 | 18.250ms | 0.220ms | 0.315ms | 14.946ms | 83.1배 |
| 200 × 20 | 91.288ms | 0.626ms | 0.774ms | 68.893ms | 145.8배 |

세 경우 모두 8개 probe의 status·student 결정이 일치했다. 최대 점수 오차는 `1.59e-7`이었다.
앞선 실행의 200 × 20 결과는 58.570ms→0.505ms였다. 실행 간 부하와 코드 정리 비용에 따라
시간은 달라지므로 고정 성능 보장으로 해석하지 않는다. 최대 갤러리 행렬은 세션당 약 3.9MiB다.

이 수치는 **후보 비교 단계만** 측정했다. 촬영·업로드·얼굴 검출·임베딩·DB 출석 반영·화면 갱신을
포함한 전체 지연 개선율은 측정하지 않았다. 품질 3프레임을 모으는 대기 시간은 그대로다.

## 배포·롤백

1. 새 프레임 유입을 멈추고 처리 중 요청을 완료시킨 뒤 기존 Spring 인스턴스를 모두 종료한다.
2. V17을 적용하고 새 Spring 버전을 기동한다. 구버전과 신버전을 동시에 처리에 투입하지 않는다.
   구버전은 새 시작 시각을 갱신하지 않아 간격 판단이 서로 달라질 수 있다.
3. 새 AI를 기존 단일 worker/replica 구성으로 기동한다. readiness와 등록·다수 얼굴·QR 흐름을 실제 장비에서 확인한다.
4. 롤백은 다시 유입을 멈추고 요청을 완료시킨 뒤 **V17이 포함된 롤백 산출물**로 수행한다.
   추가 컬럼과 Flyway 이력은 유지하며 migration 삭제나 checksum repair로 되돌리지 않는다.

실제 운영 배포·Docker 이미지 빌드·실기기 지연·오인식률·UI E2E는 미검증이다.
`FACE_MATCH_THRESHOLD`와 `FACE_MATCH_MARGIN`의 운영값은 승인된 실제 검증 데이터로 별도 보정해야 한다.
