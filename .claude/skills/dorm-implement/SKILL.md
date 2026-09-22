---
name: dorm-implement
description: Implement or continue a dormitory attendance feature across Next.js, Spring, FastAPI, or infrastructure using this repository's requirements and acceptance scenarios. Use for feature work, not read-only status questions.
---

# 기숙사 기능 구현

작업 기준 경로는 저장소 루트다. 스킬이 자동으로 로드됐더라도 사용자 요청 범위를 넓히지 않는다.

1. [명세 목차](../../../docs/spec/index.md)에서 관련 REQ와 [개발 계획](../../../docs/plans/implementation.md)의 작업 단계를 찾는다.
2. 담당 디렉터리 `AGENTS.md`, [기술 결정](../../../docs/decisions.md), [계약 지침](../../../contracts/README.md)을 읽는다.
3. 선택한 REQ의 [수용 시나리오](../../../tests/acceptance/scenarios.json)를 완료 기준으로 삼는다. 단일 기능은 바로 구현하고 여러 서비스 변경은 계획에 진행 단위를 남긴다.
4. 외부 API·모델·오프라인 지원은 실문서/실험으로 확인한다. 데이터가 없으면 명시적인 개발용 대역으로 독립 작업을 계속하며 연동 완료로 표시하지 않는다.
5. 세로 기능 단위로 계약·도메인 처리·화면·검증을 연결한다. QR/얼굴 인증은 같은 출석 정책을 사용하고 개인정보 원본을 보관하지 않는다.
6. 의미 있는 변경 검사를 실행하고 시나리오의 구현 근거·검증 근거를 기록한다. `npm run harness:check`도 실행한다.
7. 계획의 완료/미완료·실제 실행 결과·다음 단계를 갱신한다. 실제 배포·외부 메시지·개인정보 수집은 현재 요청이 허용한 범위만 수행한다.

후속 작업자가 대화 기록 없이 이어갈 수 있어야 한다. 기술 선택을 사용자 확정 정책처럼 쓰지 않는다.
