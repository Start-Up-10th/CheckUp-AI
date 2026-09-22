---
name: dorm-docker
description: Build, review, or troubleshoot Dockerfiles, Docker Compose, container networking, volumes, health checks, and container delivery for this dormitory project's GSM SV deployment. Use for Docker work, not unrelated application features or automatic production deployment.
---

# 기숙사 Docker 작업

저장소 루트에서 작업한다. [배포 지침](../../../infra/AGENTS.md), [운영 명세](../../../docs/spec/operations.md),
[아키텍처](../../../docs/architecture.md)를 먼저 읽고 관련 결정은 [DEC-011](../../../docs/decisions.md)에 기록한다.
이 스킬은 Docker 구현·진단 절차이며 운영 서버 변경 권한을 추가로 부여하지 않는다.

## 현재 코드부터 확인

- 실제 Dockerfile/Compose 파일, 각 서비스의 빌드 명령·산출물·lockfile·포트·health 경로를 찾는다. 아직 앱이 없으면 경로나 성공하는 빈 컨테이너를 발명하지 않는다.
- Next.js, Spring, FastAPI, PostgreSQL, Redis의 경계를 유지한다. 카메라는 사용자 브라우저에서 사용하며 VM의 카메라 장치를 컨테이너에 넘기는 방식으로 바꾸지 않는다.
- Docker를 실행할 때는 선택된 context·Compose 프로젝트·환경 파일·대상 호스트를 확인한다. 로컬 검증 요청을 운영 재배포로 확대하지 않는다.

## 이미지와 Compose

- 앱 이미지에는 필요한 실행 산출물만 넣고 빌드/실행 단계를 분리한다. 실제 지원 버전과 이미지 식별자를 기록하고 운영 롤백에 재사용할 태그 또는 digest를 남긴다.
- `.dockerignore`에서 `.env`, 키, 얼굴 원본/벡터, DB 덤프·백업, 로컬 산출물을 제외한다. 개인 데이터나 secret을 이미지에 COPY하지 않는다.
- 빌드용 비밀값은 필요할 때 BuildKit secret mount를 사용한다. ARG/ENV에 secret을 넣지 않는다. OAuth·DB 런타임 비밀값은 서버 env/secret으로 주입하고 프론트 공개 변수로 넘기지 않는다.
- 앱 컨테이너는 비루트 사용자와 필요한 쓰기 경로만 사용한다. DB 공식 이미지의 사용자·데이터 디렉터리 규칙은 해당 버전 문서를 확인한다.
- PostgreSQL과 Redis는 내부 서비스 이름으로 연결한다. 외부 공개는 필요한 웹 진입점으로 제한하며, 로컬 DB 디버깅 포트는 의도적으로 설정한 경우에만 연다.
- 시작 순서와 준비 완료를 구분한다. 실제 healthcheck와 필요한 `service_healthy` 의존성을 사용하고, 실행 중 장애에 대한 앱 재연결도 검증한다. 단순 sleep이나 항상 성공하는 probe를 사용하지 않는다.
- PostgreSQL 데이터는 영속 볼륨에 둔다. Redis 데이터 영속 여부는 세션/캐시 역할과 만료 정책에 맞춘다. 볼륨이 백업을 대신한다고 보고하지 않는다.
- 얼굴 프레임이 프록시/업로드 임시 파일·컨테이너 로그·볼륨에 남지 않도록 확인한다. 서버/작업의 시간 처리는 08:00 Asia/Seoul 정리 규칙과 일치시킨다.
- FastAPI/MediaPipe의 OS 라이브러리·모델 파일·CPU 아키텍처를 확인한다. GSM SV VM에 GPU가 할당됐다고 가정하지 않는다.

## 검증 순서

1. 실제 Compose 파일과 개발용 환경 값으로 `docker compose ... config --quiet`를 실행한다. `...`에는 확인한 `-f`, `--env-file`, 프로젝트 옵션을 넣는다. 병합된 비밀값 전체를 출력하지 않는다.
2. 요청 범위의 격리된 개발 환경에서 이미지를 빌드하고 필요한 서비스를 기동한다. 운영 볼륨·DB에 연결된 환경을 테스트 데이터로 사용하지 않는다.
3. 준비 상태, 웹→Spring→AI/DB 통신, 앱 재시작 후 데이터 유지, 정상 종료를 확인한다. 실패하면 관련 서비스 상태와 민감값을 제거한 제한된 로그로 원인을 좁힌다.
4. GitHub Actions를 변경한다면 실제 이미지 빌드·테스트와 운영 배포 단계를 구분한다. 운영은 GSM SV의 정확한 포워딩·TLS·OAuth callback·VM 만료 여부를 확인한 후 요청 범위에서 배포한다.
5. 이전 이미지로 돌아가는 절차와 DB migration 호환성을 함께 기록한다. 이미지 rollback만으로 스키마도 되돌아갔다고 가정하지 않는다.
6. [검증 문서](../../../docs/verification.md)에 실제 명령·환경·결과를, [개발 계획](../../../docs/plans/implementation.md)에 다음 단계를 남긴다. `npm run harness:check`도 실행한다.

Docker가 없거나 앱이 아직 없으면 실행하지 못한 검사를 표시한다. 문서 검사 통과를 컨테이너 실행 성공으로 보고하지 않는다.
정리할 때는 이번 작업에서 만든 프로젝트 자원만 대상으로 삼는다. `docker compose down -v`, volume 제거, 광범위한 prune은 기본 정리 명령으로 넣지 않는다.
실제 데이터 삭제가 요청됐으면 정확한 볼륨·범위·복구 가능성을 확인한 뒤 수행한다.

## 필요한 공식 문서

- 이미지 구성 변경: [Docker build best practices](https://docs.docker.com/build/building/best-practices/).
- 준비 상태 의존성: [Compose startup order](https://docs.docker.com/compose/how-tos/startup-order/).
- 조용한 설정 검증: [docker compose config](https://docs.docker.com/reference/cli/docker/compose/config/).
- 빌드 인증: [Build secrets](https://docs.docker.com/build/building/secrets/).

최신 명령 옵션과 이미지별 차이는 작업에 관련된 공식 문서만 확인한다.
