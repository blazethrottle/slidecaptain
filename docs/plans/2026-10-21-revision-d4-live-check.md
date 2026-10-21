# 개정판 D4 실제 생성 확인: Claude 목록 값과 추론 강도, 요청 강도 기록

작성: 2026-10-21(회사 PC, Windows). 상태: 1판(리뷰 전). 브랜치 `feat/d4-live-check`(기준 main `9d62455`).

상위 문서: [착수 인계](../handoffs/2026-10-21-d4-live-check-prep.md), [D4b 계획](2026-10-20-revision-d4b-claude-models.md) 8절(CMR-06, CMR-07, 설치 CLI 실측), 로드맵 D4a 이월표 둘째 행("원장/사용량의 요청 Effort 기록과 실제 적용값 대조 미구현").

## 1. 사용자 결정

2026-10-21 사용자 결정 "A로 승인"으로 D4의 다음 단위를 "실제 생성으로 확인"으로 정했다. 실제 호출의 횟수와 대상은 아직 승인되지 않았다. 세션은 4절의 호출 행렬을 실행 직전에 묻고, 승인이 나기 전에는 실제 생성 호출을 하지 않는다. 지금까지 이 단위의 실제 AI 생성 호출은 0회다.

## 2. 지금 코드와 실측 (기준 `9d62455`)

1. Claude 생성(`pipeline/subscription.py` `SubscriptionProvider.complete`)은 `ClaudeAgentOptions(model, effort, tools=[], setting_sources=[], max_turns=2, output_format)`로 `query()`를 부른다. `strict_mcp_config`는 없다. 목록 조회(`connections.py` `_read_claude_catalog`)에는 D4b 리뷰 CMR-07로 이미 넣었다. 실제 모델은 첫 `AssistantMessage.model`이고, 초기화 `SystemMessage`는 읽지 않는다.
2. Codex 생성(`pipeline/codex.py` `CodexProvider._complete`)은 강도를 `turn/start`에만 싣는다. 실제 모델은 `thread/start` 응답의 `model`이다. 두 응답의 다른 칸은 읽지 않는다.
3. 사용량: `CallUsage`(`provider.py`)에는 강도 칸이 없다. 프로젝트의 `ai-usage.jsonl` 한 줄(`service.py` `UsageRecord`)에는 `requested_model`만 있고 요청 강도가 없다. `UsageRecord`는 API 응답에 실리지 않는다.
4. 원장: `jobs` 테이블에 `effort` 열이 있지만, 등록 때 고정하는 입력(`FixedInputs`)에 강도가 없어 이 열은 늘 비어 있다. `FixedInputs`의 설명문도 "D4의 계정 프로필, Effort, 동의 리비전은 빈 열로 둔다"이다. `FixedInputs`를 만드는 자리는 `server/app.py`에 7곳이고, 모두 `_fixed_selection()`의 (제공자, 모델)을 쓴다.
5. 실측 도구 `scripts/quality_pilot.py`:
   - Claude 모델을 `sonnet`, `opus`, `haiku`로만 받는다. D4b 뒤의 목록 값(`default`, `opus[1m]`, `claude-fable-5-1[1m]`)을 넣으면 실행 전에 거절한다.
   - 강도 옵션이 없다. 게다가 `_PilotConnection.provider(model)`이 `effort` 인자를 받지 않아, 선택에 강도를 넣으면 생성 임대(`AIConnections.generation`)가 `provider(model, effort=...)`를 부르다 `TypeError`로 멈춘다.
   - 한 번 실행하면 장 생성과 재작성을 모두 하므로 최소 2회를 호출한다. 행렬의 한 칸을 재는 데 필요한 것보다 많다.
   - 쓸 CLI를 고르는 옵션이 없다. CLI는 환경 변수 `SLIDECAPTAIN_CLAUDE_CLI`, SDK 동봉 CLI, PATH 순서로 정해진다.
6. 이 PC의 실측(2026-10-21, 생성 호출 없음):
   - 설치 CLI는 2.1.304(`~/.local/bin/claude.exe`, 데스크톱 앱 경로)이고, SDK 0.2.145에 동봉된 CLI는 2.1.247(개발 실행 경로)이다.
   - `claude auth status`는 로그인됨, claude.ai 로그인, Max 구독이다. 계정 이메일은 출력하지 않았다.
   - Codex CLI 0.163.0은 있지만, 앱 전용 ChatGPT 프로필(`~/slidecaptain-projects/.slidecaptain-codex`)이 이 PC에 없다. 그래서 Codex 생성을 재려면 사용자가 앱의 AI 연결 화면에서 ChatGPT 로그인을 먼저 해야 한다.
   - 이 PC 사용자의 저장된 선택은 Claude `opus`다. `opus`는 설치 CLI 목록에만 있고 동봉 CLI 목록에는 없다(D4b 계획 8절).

## 3. 설계

### 3.1 생성 경로의 `strict_mcp_config` (질문 3)

`SubscriptionProvider.complete`의 옵션에 `strict_mcp_config=True`를 넣는다. 생성은 도구를 쓰지 않으므로(`tools=[]`) 사용자 단위 MCP 서버를 띄울 이유가 없고, 목록 조회와 같은 격리 조건이 된다. 가짜 `query()`로 옵션을 단언하는 시험을 먼저 쓴다. 4절의 실제 호출이 이 옵션을 켠 채 생성이 끝나는지 확인한다.

### 3.2 요청 강도 기록 (질문 5)

1. `FixedInputs`에 `effort`를 더하고, `create_job`이 `jobs.effort`에 쓴다. `_fixed_selection()`은 (제공자, 모델, 강도)를 돌려주고 7곳이 그 값을 넘긴다. 열은 이미 있으므로 형식 번호와 이전 빌드의 호환은 바뀌지 않는다.
2. `UsageRecord`에 `requested_effort`를 더한다. 값은 `requested_model`과 같은 방식으로 프로바이더의 `effort` 속성에서 읽는다. null은 "제공자 기본값을 요청함"이며 실제 적용값이 아니다.
3. 이름은 둘 다 "요청" 값이다. 실제 적용 강도를 이 칸에 넣지 않는다. 화면과 API는 바꾸지 않는다(`test_openapi.py`로 무변경을 확인한다).

### 3.3 응답 관측의 진단 기록 (질문 2, 4)

실제 적용 강도를 응답에서 읽을 수 있는지 알려면 응답에 어떤 칸이 오는지 봐야 한다. 그러나 원시 초기화 응답에는 계정 정보가 들어 있으므로 통째로 남기지 않는다.

1. Claude: `SubscriptionProvider`가 초기화 `SystemMessage`(subtype `init`)를 받으면 INFO 로그 한 줄을 남긴다. 담는 것은 칸 이름 목록(정렬), `model` 값, 이름에 `effort` 또는 `thinking`이 들어간 칸의 값뿐이다.
2. Codex: `CodexProvider`가 `thread/start`와 `turn/start` 응답에 대해 같은 규칙으로 한 줄씩 남긴다. 값을 남기는 칸은 `model`, `reasoningEffort`, `effort`다.
3. 계정 칸(`account`, `email` 등)의 값이 로그에 실리지 않는다는 것을 가짜 응답으로 시험한다.
4. `CallUsage`에 적용 강도 칸을 더하는 일은 이 단위에서 하지 않는다. `CallUsage`는 생성 결과 모델에 실려 OpenAPI와 프런트 타입이 바뀐다. 관측 결과 응답에서 적용 강도를 읽을 수 있으면, 그때 칸과 화면 문구(`AISettingsPanel.tsx` 194행 "응답에서 확인할 수 없다")를 바꿀지 사용자와 정한다.

### 3.4 실측 도구 확장 (`scripts/quality_pilot.py`)

1. `--effort`: 선택(`AISelection.effort`)에 넣고, `_PilotConnection.provider(model, effort=None)`가 실제 연결에 그대로 넘긴다. 오프라인 모드의 가짜 목록은 요청한 강도를 지원 목록에 넣는다.
2. Claude 모델 검사: 고정 별칭 검사를 지운다. 실제 모드에서는 생성 임대가 실제 목록과 대조하고, 목록에 없으면 호출 전에 `model_unavailable`로 멈춘다(앱과 같은 경로).
3. `--stop-after chapter`: 장 생성 작업이 끝나면 멈춘다. 행렬의 한 칸은 이 옵션으로 1회만 호출한다. 멈추기 전에 원장의 `effort`와 `ai-usage.jsonl` 마지막 줄의 `requested_effort`가 요청과 같은지 `report.json`의 `checks`에 적는다.
4. `--claude-cli PATH`: 이 프로세스의 `SLIDECAPTAIN_CLAUDE_CLI`를 정한다. `report.json`에는 CLI 판(`--version`)과 종류(설치, 동봉, 그 밖)만 적고 전체 경로는 적지 않는다.
5. 진단 로그: `slidecaptain` 로거의 INFO 이상을 출력 폴더의 `diagnostic.log`에 쓴다. 3.3의 관측 줄과 호출 실패 원인이 여기에 남는다.
6. `report.json`에 `requested_effort`를 더한다.

### 3.5 행마다의 판정 규칙

판정은 각 행의 첫 호출 기록(`report.json`의 `calls[0]`)과 `diagnostic.log`로 한다.

| 판정 | 조건 |
|---|---|
| 수용 | 호출이 `returned`이고 오류 종료가 아니며 `usage.model`이 있다. 실제 모델 이름을 적는다 |
| 수용, 형식 실패 | 응답은 왔지만 구조화 출력이 형식 검사를 통과하지 못했다. 모델과 강도는 받아들여진 것이다. 형식 재시도는 상한 1회에 막혀 보내지 않는다 |
| 거절 | 호출이 실패했고, 진단 로그의 CLI 오류가 모델이나 강도 값을 가리킨다 |
| 판정 보류 | 한도, 네트워크, 로그인처럼 값과 무관한 실패다. 자동으로 다시 호출하지 않고 사용자에게 알린다 |

강도의 실제 적용은 3.3의 관측 칸에 요청과 같은 값이 있을 때만 "확인됨"으로 적고, 없으면 "응답에서 확인 불가"로 적는다. 오류 없이 끝났다는 것은 "CLI가 값을 받았다"까지만 뜻한다.

## 4. 호출 행렬 (승인 대상)

모든 행은 합성 입력(`quality_pilot.py`의 장 하나, `tests/fixtures/q3b-project.json` 기반)만 쓰고 실제 회사 자료는 쓰지 않는다. 행마다 `--max-calls 1 --stop-after chapter`로 실행한다. 실패도 그 1회에 포함하며, 형식 재시도와 자동 축약은 상한에 막혀 보내지 않는다. 자동 제공자 전환과 자동 재실행은 없다. 다시 돌리려면 새 승인을 받는다.

| 행 | 제공자 | CLI | 모델 | 강도 | 답하는 질문 |
|---|---|---|---|---|---|
| L1 | Claude | 설치 2.1.304(데스크톱 경로) | `default` | `low` | 1(`default`), 2, 3, 5 |
| L2 | Claude | 설치 2.1.304 | `claude-fable-5-1[1m]` | `low` | 1(`[1m]` 변형), 2, 3 |
| L3 | Claude | 동봉 2.1.247(개발 경로) | `opus[1m]` | `low` | 1(동봉 판의 `[1m]`), 2, 3 |
| L4(선택) | Claude | 설치 2.1.304 | `opus` | 없음 | 이 PC 사용자의 저장 선택이 그대로 생성되는지 |
| L5(선택) | ChatGPT | Codex 0.163.0 | 그 계정 목록의 기본 모델 | 그 모델이 광고하는 가장 낮은 강도 | 4, 5 |

강도를 `low`로 둔 이유는 사용량을 줄이기 위해서다. 이 행렬은 CLI가 `--effort` 값을 받는지를 한 단계로만 확인한다. 다른 단계(`medium`부터 `max`까지)의 수용은 재지 않으며, 앱은 목록이 광고한 단계만 보낸다는 점(D4b 3절 4)에 기댄다.

사용자에게 물을 선택지:

- A(추천): L1~L3, Claude 3회. 데스크톱 경로의 `default`와 `[1m]` 변형, 개발 경로의 `[1m]` 변형을 각각 1회로 확인한다. Codex(질문 4)는 이월한다.
- B: L1~L4, Claude 4회. A에 이 PC 사용자의 저장 선택(`opus`)을 더한다.
- C: L1~L3과 L5, 4회. 사용자가 먼저 앱에서 ChatGPT 로그인을 한다.

함께 확인할 것: 쓸 계정(이 PC의 Claude Code 로그인 계정, Max 구독)과 쓸 CLI 경로(위 표).

## 5. 기록 위치와 형식

1. 원시 산출물은 저장소 밖 새 폴더(`~/slidecaptain-live-check/2026-10-21/<행>/`)에 둔다. 합성 프롬프트, 결과, `report.json`, `diagnostic.log`가 들어가며 커밋하지 않는다.
2. 저장소에는 이 계획서의 「결과」 절에 행마다 CLI 판, 요청 모델과 강도, 판정, 실제 모델, `CallUsage`의 토큰과 시간, 강도 관측 결과, 원장과 사용량 기록 확인을 적는다. 계정 이메일, 사용자 이름이 든 전체 경로, 원시 초기화 응답은 적지 않는다.
3. 로드맵 D4a 이월표 둘째 행과 「진행 상태」 줄을 갱신한다.

## 6. 수용 기준

1. 실패하는 시험부터 쓴다: 생성 옵션의 `strict_mcp_config`, 원장의 `effort`, 사용량의 `requested_effort`, 진단 줄의 칸 제한(계정 값 미기록), 실측 도구의 강도 전달과 `--stop-after chapter`와 목록 값 모델 허용.
2. 백엔드, 프런트 전체 시험 통과, OpenAPI와 프런트 타입 재생성 무변경, 공개 저장소 감사기 0건, CI 두 OS 성공.
3. 오프라인 실행(`--offline --effort low --stop-after chapter`)이 호출 0회로 끝나고 `checks`의 강도 기록 두 항목이 참이다.
4. 사용자가 승인한 행만 실행하고, 결과를 5절대로 기록한다.
5. 계획 리뷰어 1명(적대 리뷰), 구현 뒤 코드 리뷰어 1명.

## 7. 하지 않는 것과 이월

- 계정 프로필, 두 계정 전환, 영구 동의(D4c), 추천과 앱 안 업데이트 안내(D4d).
- `CallUsage`의 적용 강도 칸과 화면 문구 변경: 3.3의 관측 뒤 사용자와 정한다.
- 재지 않는 조합: 다른 강도 단계, `sonnet`과 `haiku`, 동봉 CLI의 `default`와 `claude-fable-5[1m]`. 결과 기록 때 로드맵 이월표에 담당과 함께 올린다.
- L1이 `default`를 거절하면 고치는 방법(예: `default`를 고르면 `--model`을 넘기지 않기, 또는 목록에서 감추기)을 사용자에게 제안하고, 자동으로 고치지 않는다. 다른 행의 거절도 같다.
- 선택지 C를 고르지 않으면 질문 4(Codex 요청 강도와 실제 모델 대조)는 이월표에 남긴다.

## 8. 순서

1. 이 계획을 리뷰어 1명이 적대 리뷰하고 반영한다.
2. 3.1~3.4를 시험부터 구현하고, 전체 시험 뒤 커밋하고 push해서 CI 두 OS를 확인한다.
3. 오프라인 실행으로 도구를 확인한다.
4. 사용자에게 4절의 선택지를 묻는다. 승인한 행만 실행한다.
5. 결과를 기록하고 로드맵과 인계를 갱신한다. 코드 리뷰를 반영한 뒤 머지 여부를 묻는다.
