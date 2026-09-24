# 배포·운영 작업 지침

Docker + GitHub Actions + GSM SV Ubuntu 22.04. [운영 명세](../docs/spec/operations.md)를 읽는다.

Dockerfile·Compose·컨테이너 빌드/기동·볼륨·컨테이너 장애 작업은 [dorm-docker 스킬](../.agents/skills/dorm-docker/SKILL.md)을 사용한다.

- VM 크기·Compose 구조·레지스트리·배포 트리거·TLS·rollback·backup은 담당자가 결정하고 문서화한다.
- 실제 PROJECT_OWNER 권한과 포워딩 주소를 확인한다. USER 30일 만료 VM을 영구 운영으로 보고하지 않는다.
- 모델·DB·Redis·AI 자원을 계측하고 CPU/GPU 지원을 실측한다.
- HTTPS 카메라·OAuth 운영 callback·내부 네트워크 접근을 실기기에서 확인한다.
- secret은 GitHub Secrets/서버 env로 주입한다. `.env.example`에는 값이나 실제 키를 넣지 않는다.
- PostgreSQL 볼륨 영속성과 백업은 다른 것이다. 원본 얼굴과 당일 출석은 백업하지 않는다.
- 삭제된 학생 벡터가 복원 후 재출현하지 않도록 검증한다. 전체 DB dump로 보관 원칙을 우회하지 않는다.
- CI/CD 구성·트리거·정적 검사는 서비스 개발 전에 준비할 수 있다. 실행 가능한 서비스 골격과 명령부터 테스트·빌드를 연결하며 전체 기능 완성을 선행 조건으로 삼지 않는다.
- 하네스 검사, 서비스 테스트/빌드, 배포 설정 검증, 실제 배포 결과를 구분한다. 미구현·비활성·건너뛴 작업은 검증 완료가 아니다. 실제 배포에는 배포 가능한 산출물과 확인된 대상 환경이 필요하다.
- 실제 학교 서버 변경·운영 배포는 요청 범위에 포함된 경우에만 실행한다.
