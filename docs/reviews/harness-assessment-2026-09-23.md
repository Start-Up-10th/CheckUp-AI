# 하네스 평가 — 2026-09-23

판정: 요구사항을 보존하고 두 코딩 도구에 전달하는 개발 준비 구조는 양호하다. 실제 도구 입력을 처리하는 훅과 검증 완료 판정에는 재현되는 허점이 있다. 장시간 작업의 이어하기와 두 도구의 동등한 실행 품질은 아직 실증되지 않았다.

제품 코드가 없는 것은 현재 단계의 범위이므로 감점 사유로 삼지 않았다. 공개 사례와 같은 프레임워크를 쓰는지, 에이전트 수가 많은지, GitHub 별이 많은지도 품질 기준으로 삼지 않았다. 아래 평가는 로컬 검사·소스 대조·안전한 진단으로 확인한 사실과 설계 제안을 구분한다. 총점이나 업계 순위는 산출하지 않는다.

## 범위와 기준 상태

- 기준 커밋: `e1341661660316c0762d3af3fba4bf1e954e7273`. 평가 시작 시 작업 트리는 깨끗했다.
- 환경: Windows x64, Node.js `v24.15.0`. CI 설정의 Node 22·Ubuntu 실행 결과는 이번 로컬 결과에 포함하지 않는다.
- `npm run harness:check`: REQ 38개, 수용 시나리오 38개, 공통 스킬 4개, 기준 Markdown 48개, 자체 테스트 20/20 통과.
- 제품 시나리오: 38개 모두 `specified`, `verified` 0개. REQ 연결률 38/38은 실행 테스트 커버리지가 아니다.
- 읽은 대상: 루트/영역 지침, 설정·훅·검사기·자체 테스트·동기화 도구·CI, 명세/출처/아키텍처, 개발 계획, 계약 지침, 시나리오 구조.
- 공개 저장소는 문서와 소스를 열어 비교했다. 설치·외부 코드 실행·전체 벤치마크는 하지 않았다.

이번 변경으로 CI 선구축 지침과 평가/계획 문서를 추가했다. 아래 훅·검사기 결함의 코드는 아직 수정하지 않았다. 세부 작업은 [개선 계획](../plans/harness-improvements.md)에 있다.

## 비교 자료와 적용 범위

모두 2026-09-23 열람한 작성자/관리자의 1차 자료다. 가변 `main` 문서의 내용은 이후 달라질 수 있다.

| 자료 | 확인한 방식 | 이 저장소에 적용할 판단 |
| --- | --- | --- |
| [OpenAI 실행 계획 가이드](https://developers.openai.com/cookbook/articles/codex_exec_plans) | 재개 가능한 계획에 진행 상황·발견·결정·검증 가능한 마일스톤 유지 | 기존 계획에 다음 실행 작업·명령·관찰 결과를 보강; 문서 형식 전체를 복제할 필요는 없음 |
| [Anthropic 장기 작업 하네스](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents) | 기능별 상태, 초기 환경 준비, 점진 구현, 세션 인계 | 현재 REQ/시나리오 구조를 유지하며 실제 시작·검증·이어하기 경로 보강 |
| [anthropics/claude-quickstarts autonomous-coding](https://github.com/anthropics/claude-quickstarts/blob/main/autonomous-coding/README.md) | 초기화/구현 역할, 기능 상태·Git을 통한 진행 보존, 실행 환경 제한 | 앱별 실행 준비와 재개 절차 참고. 데모의 작업 수·모델·자동 반복을 그대로 채택하지 않음 |
| [anthropics/cwc-long-running-agents](https://github.com/anthropics/cwc-long-running-agents/blob/main/README.md) | 증빙 확인, 별도 평가자, 인계의 작은 구성요소 | 증빙 검증을 우선 보강. 저장소가 명시한 행사 데모·미유지보수 성격을 고려해 운영 의존성으로 설치하지 않음 |
| [github/spec-kit 작업 템플릿](https://github.com/github/spec-kit/blob/main/templates/tasks-template.md) | 작업 ID, 대상 파일, 의존성, 독립 검증, 병렬 표시 | 계획을 실행 가능한 작업으로 분해. 선택적 테스트 정책과 광범위한 선행 단계 제한은 이 프로젝트에 그대로 적용하지 않음 |
| [Anthropic 2026 하네스 설계](https://www.anthropic.com/engineering/harness-design-long-running-apps) | 모델 성능 변화에 따른 구조 축소와 평가자 효과 비교 | 에이전트/훅을 늘리기 전에 비용·오류 감소를 측정 |
| [Anthropic 에이전트 평가](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents) | 과제·반복 시행·채점 기준·실제 결과 분리 | 지침 준수와 재개 성공을 고정 과제로 측정 |

호환성 판정은 [Codex 훅](https://learn.chatgpt.com/docs/hooks)과 [Claude 훅](https://code.claude.com/docs/en/hooks)의 공식 입력/출력 규약을 기준으로 했다. CI의 건너뜀 해석은 [GitHub 조건부 작업 문서](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-jobs-with-conditions)를 사용했다.

## 항목별 평가

| 평가 축 | 관찰된 강점 | 부족한 근거·기능 | 판정 |
| --- | --- | --- | --- |
| 요구사항·출처 | 38개 REQ에 출처와 시나리오 연결, 폐기 정책 정정 표 | 원문 누락·문장 의미까지 자동 보장하지는 않음 | 강점 |
| 문맥 구성 | 짧은 루트 지침, 분야별 지침·명세·스킬 분리, 32 KiB 검사 | 전체 선행 문서의 실제 읽기 비용·불필요한 읽기 양 미측정 | 양호 |
| 공통 규칙 유지 | 단일 스킬 원본, 생성본 동기화, 불일치/경로 이탈 테스트 | SKILL.md 외 보조 자산 동기화는 현재 없음; 현재 스킬에는 필요하지 않음 | 현재 범위에 적합 |
| 훅 실행 신뢰성 | 핵심 처리 함수와 단위 테스트 존재 | 실제 입력·PowerShell·절대 경로·하위 cwd 결함 | 우선 보완 |
| 완료 판정 | `specified/implemented/verified`와 증빙 경로 분리 | 파일 존재만으로 `verified` 통과, 결과·대상 버전 확인 없음 | 우선 보완 |
| CI 기반 | PR/push/수동 트리거, Ubuntu/Windows 설정, 읽기 전용 권한 | 워크플로 정적 검사·독립 secret 검사·실행 증빙 없음 | 기반 있음, 확장 필요 |
| 작업 재개 | 기능별 계획과 인계 지침 | 작업 단위 상태·막힘·다음 명령·실행 환경 확인의 표준화 부족 | 부분 준비 |
| 에이전트 행동 평가 | 실제 앱 검사와 문서 검사를 구분하는 원칙 | 새 세션·도구별 시행 결과, 재개/비개입/정책 준수 비교 없음 | 미실증 |

## 우선순위별 발견

P1은 개발에 활용하기 전에 보완 가치가 큰 실행·검증 결함, P2는 반복 작업의 신뢰성과 효율을 높일 개선이다. 사고 발생이나 실제 개인정보 유출이 관찰됐다는 뜻은 아니다.

### H-01 · P1 · Codex 패치 내용이 secret 검사에서 빠짐

위치: [harness/hooks.mjs](../../harness/hooks.mjs)의 `contentFrom()`(52행 부근), `inspectPreTool()`(83행 부근).

Codex 공식 훅 규약은 `apply_patch`의 본문을 `tool_input.command`로 전달한다. 현재 `contentFrom()`은 `content/new_string/patch/diff/text`만 읽는다. 따라서 해당 공식 형식에서는 문자열 검사를 위한 본문이 비게 된다. [공식 규약](https://learn.chatgpt.com/docs/hooks#pretooluse)

토큰 형태의 합성 문자열을 넣은 동일 내용을 Claude `Write`로 전달하면 `blocked: true`, Codex 공식 패치 형식으로 전달하면 `blocked: false`였다. 실제 파일 쓰기나 유효한 토큰 사용은 없었다.

수정 방향: 도구별 입력을 공통 구조로 정규화하고 패치 대상별 추가 내용을 검사한다. 파일별 환경값 예외를 구분하며, 실제 문서 형식의 입력과 출력 프로토콜을 회귀 테스트에 넣는다.

### H-02 · P1 · Claude PowerShell 도구가 검사에서 빠짐

위치: [Claude 설정](../../.claude/settings.json)의 PreToolUse matcher(13행 부근), [harness/hooks.mjs](../../harness/hooks.mjs)의 `SHELL_TOOLS`(3행).

설정은 `Bash|Edit|Write`만 선택하고 코드의 도구 집합에도 `PowerShell`이 없다. 공식 문서는 Windows에서 PowerShell 도구를 사용하는 경우 `Bash`만 선택한 훅이 실행되지 않는다고 설명한다. [공식 규약](https://code.claude.com/docs/en/hooks)

`tool_name: PowerShell`과 위험한 Git 명령을 담은 합성 이벤트를 함수에 전달하자 `blocked: false`였다. 명령 문자열을 검사 함수에만 넣었고 Git 명령을 실행하지 않았다. 사용자의 실제 Claude 버전/활성 도구는 별도로 검증해야 한다.

수정 방향: matcher와 입력 정규화를 함께 고치고, Windows와 Bash 경로를 모두 테스트한다. 현재 권한·샌드박스 설정을 변경하는 작업은 아니다.

### H-03 · P1 · 하위 폴더에서 Codex 훅을 시작하면 파일을 못 찾음

위치: [Codex 훅 설정](../../.codex/hooks.json)의 8·18행 부근.

명령이 `node harness/hooks.mjs ...`로 고정되어 있다. 동일 명령은 루트에서는 종료 코드 0, `server/`에서는 `MODULE_NOT_FOUND`와 종료 코드 1이었다. Codex 훅은 세션 cwd에서 실행된다는 공식 설명과 일치한다. [cwd 규칙](https://learn.chatgpt.com/docs/hooks)

루트 시작을 권장하는 현재 안내로 일반 경로는 피할 수 있지만 하위 경로·worktree에서의 안정성은 보장되지 않는다. 이 진단은 Node 자식 프로세스 실행이며 Codex 자체의 실패 처리까지 시험한 것은 아니다.

수정 방향: 프로젝트 루트를 해석해 훅 절대 경로를 구성한다. 공백 포함 경로·하위 시작·별도 worktree·Windows/Ubuntu를 테스트한다. 실제 로딩·신뢰 상태와 버전은 smoke 기록으로 남긴다.

### H-04 · P1 · README만으로 제품 검증 완료를 표시할 수 있음

위치: [harness/check.mjs](../../harness/check.mjs)의 시나리오 검사(112~121행 부근).

시나리오의 구현과 증빙은 비어 있지 않은 파일이 존재하는지만 확인한다. `ACC-AUTH-001`을 `verified`로 바꾸고 `implementation`과 `evidence`를 모두 `README.md`로 채운 메모리상 카탈로그로 검사했을 때 `errors: []`, `verifiedScenarios: 1`이었다. 저장소의 실제 JSON과 상태는 수정하지 않았다.

현재 [시나리오 안내](../../tests/acceptance/README.md)는 이 한계를 이미 밝히므로 숨겨진 기능이라고 평가하지 않는다. 다만 문서에 적힌 증빙 요구를 검사기가 강제하지 못하므로 완료 판정에 사용하기에는 부족하다.

수정 방향: 실행 ID·시나리오 ID·명령/cwd·결과·환경·검사 대상 revision 또는 입력 digest를 가진 결과 기록을 정의한다. 단순 테스트 소스 경로와 실제 통과 결과를 구분한다. stale/실패/건너뜀 증빙을 거부하고, 실행 가능한 검사로 결과를 재확인한다. 사람이 수동 작성한 결과 파일만으로 부정확한 판정을 완전히 방지할 수 있다고 주장하지 않는다.

### H-05 · P2 · 변경 후 검사 안내가 실제 파일 입력을 놓침

위치: [harness/hooks.mjs](../../harness/hooks.mjs)의 `filePathFrom()`과 `postToolNotice()`.

상대 경로 `docs/spec/face.md`는 안내가 나오지만 절대 경로는 `null`이다. Claude Write/Edit는 절대 경로를 사용한다. Codex 패치에서는 별도 `file_path`가 없어 안내 대상 파일도 추출하지 못한다. [Claude 입력 규약](https://code.claude.com/docs/en/hooks), [Codex 입력 규약](https://learn.chatgpt.com/docs/hooks)

또한 현재 post 실행부는 안내를 stderr에만 쓰고 정상 종료한다. 함수 반환만 확인하는 테스트는 모델에게 안내가 전달되는지 증명하지 못한다. 출력은 각 런타임의 `additionalContext` 등 공식 지원 형태로 검증할 필요가 있다.

수정 방향: 경로를 루트 상대 경로로 정규화하고 다중 파일 패치를 처리한다. 루트 AGENTS·검증 기준·계획·워크플로 변경도 영향 범위를 정의한다. 단순 안내 누락이므로 모든 편집마다 무거운 전체 검사를 강제할 필요는 없다.

### H-06 · P1 · 훅 외부에서 들어온 변경을 검사할 CI 보강 필요

위치: [harness/check.mjs](../../harness/check.mjs), [CI](../../.github/workflows/harness.yml).

검사기는 훅 이벤트 배열의 존재를 확인하지만 hook command의 실행 가능성이나 실제 이벤트 처리를 검증하지 않는다. 워크플로 YAML과 Codex TOML을 해석하는 정적 검증도 없다. 기존 CI에는 독립적인 저장소 secret 스캔이 없으므로 훅이 놓친 쓰기나 다른 편집기가 만든 변경은 이 검사로 탐지되지 않는다.

수정 방향: 훅 통합 회귀 검사, 설정 스키마 검사, 워크플로 정적 검사, 마스킹된 secret 검사 결과를 CI에 연결한다. 후보 도구는 공식 저장소를 확인한 [actionlint](https://github.com/rhysd/actionlint)와 [Gitleaks](https://github.com/gitleaks/gitleaks)다. 이번에는 설치·스캔하지 않았으며 버전과 실행 방법은 도입 변경에서 확정한다.

### H-07 · P2 · 계획과 현재 상태 문서의 일관성 부족

위치: [개발 계획](../plans/implementation.md), [아키텍처](../architecture.md), [계약 지침](../../contracts/README.md), [검증 기준](../verification.md).

- 계획은 인증/DataGSM 동기화가 먼저라고 적지만 아키텍처는 외부 확인을 기다리는 동안 출석 도메인·UI·QR 계약·테스트 개발을 허용한다. 실제 의존하는 작업만 막히도록 분해할 필요가 있다.
- 계획에는 내부 API 경로가 있으나 계약 안내에는 내부 경로/schema가 없다고 적혀 있다. 계획상 초안과 확정 계약의 구분이 부족하다.
- 계획이 참조하는 `API명세서/API명세서`는 이 checkout에 없다. 이전 외부 자료일 수 있으므로 출처의 현재 접근 가능성을 명시해야 한다. 내용을 복원하거나 사실로 단정하지 않는다.
- 평가 시작 시 검증 기준은 스킬 3개, manifest는 4개였다. 이번에는 검증 기준의 수량을 정정했다. 지속적으로 바뀌는 수치를 여러 문서에 반복하는 방식은 후속 정리 대상이다.
- 현재 API별 계획은 범위와 체크리스트 중심이다. 실행 단위 ID·의존성·막힘 이유·다음 명령·최근 증빙을 일관되게 전달하는 형식은 없다.

수정 방향: 최소 작업 레코드와 공통 실행 환경 점검을 정의한다. 내부 계약 초안은 구현 전에 작성 가능하게 하되 제공되지 않은 외부 DataGSM 계약과 구분한다. 문서 정리와 환경 준비를 전 서비스 완성의 선행 조건으로 확대하지 않는다.

### H-08 · P2 · 이 하네스가 실제 에이전트 행동을 개선하는지 미측정

위치: 현재 `harness/`의 테스트와 도구별 README.

단위/문서 검사는 있으나 같은 과제를 새 Codex/Claude 세션에 실행해 지침 준수·변경 범위·검증 실행·재개 성공을 채점한 자료는 없다. 테스트가 통과한 것과 에이전트가 규칙을 지킨 것은 다른 관찰이다.

수정 방향: 고정된 작은 과제에서 최종 파일·검사 결과를 채점하고, 명시적으로 기록 가능한 시간·도구 호출·사용량을 비교한다. 초기에는 과제별 1회 smoke, 구조 변경 효과 비교에는 도구별 반복 시행을 사용한다. 생산성을 개선했다고 단정할 통계는 아직 없다. [평가 방법 근거](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)

## 진단 결과 원장

파괴적 명령은 실행하지 않았다. 토큰 모양은 런타임에 만든 무효 합성 문자열이며 출력에 포함하지 않았다. 실제 원본 코드·시나리오 파일을 변조하지 않고 함수 호출과 메모리상 입력 대체로 진단했다.

| 진단 | 관찰 결과 |
| --- | --- |
| 기존 `npm run harness:check` | 20/20 통과, 제품 verified 0/38 |
| Claude Write 대조 입력 | `blocked: true` |
| Codex 공식 `apply_patch` 입력 | `blocked: false` |
| Claude PowerShell 입력 | `blocked: false` |
| 상대 경로 편집 안내 | 안내 문자열 반환 |
| 절대 경로 편집 안내 | `null` |
| Codex 패치 편집 안내 | `null` |
| 루트에서 훅 명령 기동 | 종료 0 |
| server에서 같은 훅 명령 기동 | 종료 1, `MODULE_NOT_FOUND` |
| README만 구현/검증 근거로 넣은 메모리상 시나리오 | `errors: []`, verified 1 |

핵심 훅 재현은 루트에서 아래 Node 코드를 stdin으로 전달해 실행할 수 있다. PowerShell에서는 단일 인용 here-string을 `node --input-type=module -`로 파이프한다. 이 코드는 패치 본문을 함수에 넘기기만 한다.

```js
import { inspectPreTool, postToolNotice } from './harness/hooks.mjs';
import path from 'node:path';
const fake = 'ghp_' + '0'.repeat(30);
const patch = [
  '*** Begin Patch', '*** Add File: server/src/audit-only.ts',
  '+const token = "' + fake + '";', '*** End Patch'
].join('\n');
console.log(inspectPreTool({
  tool_name: 'apply_patch', tool_input: { command: patch }
}));
console.log(postToolNotice({
  tool_name: 'Edit',
  tool_input: { file_path: path.join(process.cwd(), 'docs/spec/face.md') }
}));
```

証빙 진단은 `check.mjs`의 파일 읽기를 메모리상에서 대체해 나머지 입력을 그대로 유지했고, 카탈로그의 한 시나리오만 변경했다. 원본과 메모리상 변형을 혼동하지 않도록 실제 파일의 38개 상태는 모두 `specified`로 유지했다.

## 이번 반영과 남은 한계

CI/CD 구성을 먼저 준비할 수 있다는 DEC-013을 루트·infra 지침과 검증 기준에 반영했다. 실제 테스트·빌드는 실행 가능한 골격부터 연결하며, 전체 서비스 기능 완성을 기다리지 않는다. 실제 배포에는 배포 가능한 산출물과 대상 환경이 필요하다. 건너뛴 작업은 서비스 검증 완료로 집계하지 않는다.

서비스 기능 정책 변경이 아니므로 제품 REQ/수용 시나리오를 추가하거나 verified로 올리지 않았다. `dorm-spec-update`에 따라 개발 절차 변경의 출처·기술 결정·계획을 함께 남겼고, `dorm-verify`에 따라 문서 검사와 제품/실기기 검증을 구분했다.

실제 에이전트의 새 세션, 원격 GitHub Actions, Ubuntu/Node 22, DataGSM·카메라·GSM SV 배포는 미검증이다. 공개 하네스보다 성능이 좋거나 나쁘다는 실행 비교 결과도 없다. 다음 작업은 [개선 계획](../plans/harness-improvements.md)의 M1이며 M2/M3와 제품의 독립 개발은 병행할 수 있다.
