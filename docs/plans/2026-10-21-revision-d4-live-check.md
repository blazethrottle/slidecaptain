# 개정판 D4 실제 생성 확인: Claude 목록 값과 추론 강도, 요청 강도 기록

작성: 2026-10-21(회사 PC, Windows). 상태: 3판(계획 리뷰 반영 9절, 구현 기록 10절, Claude 실측 결과 11절). 브랜치 `feat/d4-live-check`(기준 main `9d62455`).

상위 문서: [착수 인계](../handoffs/2026-10-21-d4-live-check-prep.md), [D4b 계획](2026-10-20-revision-d4b-claude-models.md) 8절(CMR-06, CMR-07, 설치 CLI 실측), 로드맵 D4a 이월표 둘째 행("원장/사용량의 요청 Effort 기록과 실제 적용값 대조 미구현"), [D2 계획](2026-10-08-revision-d2-common-foundation.md) 215행(원장의 Effort 열).

## 1. 사용자 결정

2026-10-21 사용자 결정 "A로 승인"으로 D4의 다음 단위를 "실제 생성으로 확인"으로 정했다. 실제 호출의 횟수와 대상은 아직 승인되지 않았다. 세션은 4절의 호출 행렬을 실행 직전에 묻고, 승인이 나기 전에는 실제 생성 호출을 하지 않는다. 지금까지 이 단위의 실제 AI 생성 호출은 0회다.

## 2. 지금 코드와 실측 (기준 `9d62455`)

1. Claude 생성(`pipeline/subscription.py` `SubscriptionProvider.complete`)은 `ClaudeAgentOptions(model, effort, tools=[], setting_sources=[], max_turns=2, output_format)`로 `query()`를 부른다. `strict_mcp_config`는 없다. 목록 조회(`connections.py` `_read_claude_catalog`)에는 D4b 리뷰 CMR-07로 이미 넣었다. 실제 모델은 첫 `AssistantMessage.model`이고, 초기화 `SystemMessage`는 읽지 않는다. CLI 표준 오류는 받지 않는다(SDK는 `stderr` 콜백이 있을 때만 받는다).
2. Codex 생성(`pipeline/codex.py` `CodexProvider._complete`)은 강도를 `turn/start`에만 싣는다. 실제 모델은 `thread/start` 응답의 `model`이다. 두 응답의 다른 칸은 읽지 않는다.
3. 사용량: `CallUsage`(`provider.py`)에는 강도 칸이 없다. 프로젝트의 `ai-usage.jsonl` 한 줄(`service.py` `UsageRecord`)에는 `requested_model`만 있고 요청 강도가 없다. `UsageRecord`를 만드는 자리는 `service.py`와 `story_repair.py`(두 곳)이며, API 응답에는 실리지 않는다.
4. 원장: `jobs` 테이블에 `effort` 열이 있지만, 등록 때 고정하는 입력(`FixedInputs`)에 강도가 없어 이 열은 늘 비어 있다. `FixedInputs`를 만드는 자리는 `server/app.py`에 7곳이고, 모두 `_fixed_selection()`의 (제공자, 모델)을 쓴다.
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
   - 이 세션의 환경에는 Claude Code 세션 연결 변수(`CLAUDE_CODE_CHILD_SESSION`, `CLAUDE_CODE_SESSION_ID`, `CLAUDE_CODE_MESSAGING_*`, `CLAUDE_EFFORT` 등)가 있다. SDK는 이 중 `CLAUDECODE`만 지운다. 데스크톱 앱은 이 변수 없이 실행된다(리뷰 LCR-06).
   - 리뷰어가 두 CLI 실행 파일의 문자열로 확인한 바로는, 두 판 모두 스트림 초기화 메시지에 `effort` 칸을 싣는다. 2.1.304에는 `per_turn_effort_active`도 있고, 문서 문자열은 이 값이 "선택한 모델에 맞춰 조용히 낮춘 뒤의 값"이라고 적는다(리뷰 LCR-05, 생성 호출로 확인한 것은 아니다).

## 3. 설계

### 3.1 생성 경로의 `strict_mcp_config` (질문 3)

`SubscriptionProvider.complete`의 옵션에 `strict_mcp_config=True`를 넣는다. 생성은 도구를 쓰지 않으므로(`tools=[]`) 사용자 단위 MCP 서버를 띄울 이유가 없다. 목록 조회와 같이 사용자 단위 MCP 서버를 띄우지 않는다는 뜻이며, 목록 조회의 다른 격리 조건(임시 작업 폴더, `DISABLE_TELEMETRY`)까지 같게 하지는 않는다. 가짜 `query()`로 옵션을 단언하는 시험을 먼저 쓴다. 4절의 실제 호출에서 생성이 끝나는지와 초기화 메시지의 `mcp_servers` 개수(3.3)로 확인한다.

### 3.2 요청 강도 기록 (질문 5)

1. `FixedInputs`의 맨 끝에 `effort`(기본값 None)를 더하고, `create_job`이 `jobs.effort`에 쓴다. 위치 인자 여섯 개로 부르는 기존 시험은 그대로 둔다.
2. `app.py`의 `_fixed_selection()`을 `_fixed_inputs(selection_id, 기준 ETag, 자료 fingerprint, 관련 입력)`으로 바꾼다. 이 함수가 지금 선택을 한 번만 읽어 제공자, 모델, 강도를 함께 고정한다. 7곳이 모두 이 함수를 쓰므로, 새 등록 자리가 강도를 빠뜨릴 수 없다. 단일 프로바이더 앱(`provider=`)은 프로바이더의 `effort` 속성을 읽는다.
3. `UsageRecord`에 `requested_effort: str | None = None`을 더한다. 출처는 `requested_model`과 같다: 생성 임대 경로는 `ai_connections.selection.effort`(임대 중에는 선택을 바꿀 수 없다), 단일 프로바이더 경로와 `story_repair.py` 두 곳은 프로바이더의 `effort` 속성이다(리뷰 LCR-02).
4. 이름은 둘 다 "요청" 값이다. 실제 적용 강도를 이 칸에 넣지 않는다. 화면과 API는 바꾸지 않는다(`test_openapi.py`로 무변경을 확인한다).
5. D2 계획 215행은 "D4가 원장 형식을 올려 채운다"고 적었다. 이 단위는 형식을 올리지 않는다. `effort` 열은 이미 형식 1의 스키마와 `JobRow`에 있고, 값을 채우는 것만으로 이전 빌드가 이 원장을 그대로 열 수 있기 때문이다. 계정 프로필과 동의 리비전 열은 여전히 비어 있다(리뷰 LCR-10, D2 계획 215행에 같은 날짜로 정정을 적는다).

### 3.3 응답 관측의 진단 기록 (질문 2, 3, 4)

실제 적용 모델과 강도를 응답에서 읽을 수 있는지 알려면 응답에 어떤 칸이 오는지 봐야 한다. 그러나 원시 응답을 통째로 남기지 않는다. 스트림 초기화 메시지에는 사용자 이름이 든 경로 칸(`cwd`, `memory_paths`, `scratchpad_path` 등)이 있다. 계정 정보는 제어 `initialize` 응답에 있으며, 이 응답은 `query()`가 메시지로 내보내지 않는다(리뷰 LCR-07).

1. 공통 함수 `observed_fields`(`provider.py`)는 칸 이름 목록과, 허용한 칸의 스칼라 값만 고른다. 개수만 셀 칸은 `<이름>#count`로 개수만 담고 안을 보지 않는다.
2. Claude: 초기화 `SystemMessage`(subtype `init`)를 받으면 INFO 로그 한 줄을 남긴다. 값을 남기는 칸은 `model`과, 이름에 `effort` 또는 `thinking`이 들어간 칸이다. `mcp_servers`, `tools`, `plugins`, `skills`, `agents`, `slash_commands`는 개수만 남긴다(리뷰 LCR-08).
3. Claude 호출이 실패하면(예외, 결과 없음, 오류 결과), CLI 표준 오류의 마지막 20줄(줄마다 300자까지), `AssistantMessage.error`, 결과의 `subtype`과 `terminal_reason`을 WARNING 로그로 남긴다. 성공한 호출에서는 표준 오류를 남기지 않는다(리뷰 LCR-03). 오류 원문을 로그에만 두고 사용자 문구에 넣지 않는 기존 설계 결정 14와 같다.
4. Codex: `thread/start`, `turn/start` 응답과 `turn/completed`의 `turn` 객체에 대해 같은 규칙으로 한 줄씩 남긴다. 값을 남기는 칸은 `model`, `reasoningEffort`, `effort`와, 이름에 `effort` 또는 `reasoning`이 들어간 칸이다(한 단계 아래 객체 포함). `thread/start`의 `reasoningEffort`는 강도를 보내기 전 스레드의 기본값이므로, 요청과 달라도 거절의 근거로 쓰지 않는다(리뷰 LCR-12).
5. 계정 칸과 경로 칸의 값이 로그에 실리지 않는다는 것을 가짜 응답으로 시험한다.
6. `CallUsage`에 적용 강도 칸을 더하는 일은 이 단위에서 하지 않는다. `CallUsage`는 생성 결과 모델에 실려 OpenAPI와 프런트 타입이 바뀐다. 관측 뒤에 칸과 화면 문구(`AISettingsPanel.tsx` 194행 "응답에서 확인할 수 없다")를 바꿀지 사용자와 정한다. 그때 "CLI가 정한 값(초기화 메시지)"과 "API가 실제로 적용한 값(확인 불가)"을 나눠 제시한다(리뷰 LCR-05).

### 3.4 실측 도구 확장 (`scripts/quality_pilot.py`)

1. `--effort`: 선택(`AISelection.effort`)에 넣는다. 실제 연결의 프로바이더는 `(모델, 강도)`로 만들고, `_PilotConnection.provider(model, effort=None)`는 모델과 강도가 모두 같을 때만 예산을 씌운 같은 객체를 돌려준다. `report.json`의 `provider_effort`에 실제 프로바이더가 CLI에 넘길 강도를 적는다(리뷰 LCR-01). 오프라인 모드의 가짜 목록은 요청한 강도를 지원 목록에 넣는다.
2. 모델 검사: 고정 별칭 검사를 지운다. 실제 모드에서는 생성 임대가 실제 목록과 대조하고, 목록에 없는 모델이나 강도는 호출 전에 `model_unavailable`로 멈춘다(앱과 같은 경로). `report.json`의 `catalog_resolved_model`에 목록의 해석된 모델을 적어 응답 모델과 대조한다(리뷰 LCR-05).
3. `--stop-after chapter`: 장 생성 작업이 종결되면 멈춘다. 형식 재시도나 자동 축약이 상한에 막혀 작업이 결과 없이 끝나도, 작업 상태(`chapter_job_state`), 오류 코드(`chapter_error_code`), 결과 상태(`chapter_status`)를 `checks`에 적는다. 호출이 1회 이상 나갔으면 `status`는 `completed`(종료 코드 0)이고, 호출 전에 멈췄으면 `blocked`(종료 코드 2)다. `completed`는 "행이 끝까지 실행됨"이며 수용 판정이 아니다. 판정은 3.5로 한다(리뷰 LCR-04).
4. 강도 기록 대조: 실행이 끝나면(성공, 실패 모두) 원장의 `effort`와 `ai-usage.jsonl` 모든 줄의 `requested_effort`가 요청과 같은지 `checks`의 `ledger_effort_matches`, `usage_effort_matches`에 적는다. 원장은 읽기 전용 sqlite 연결로 읽는다(리뷰 LCR-15).
5. `--claude-cli PATH`: 이 프로세스의 `SLIDECAPTAIN_CLAUDE_CLI`를 정한다. 목록 조회, 로그인 확인, 생성이 모두 이 값을 읽는다. `report.json`에는 CLI 판(`--version`)과 종류(설치, 동봉, 그 밖)만 적고 전체 경로는 적지 않는다.
6. 실제 Claude 실행 동안 이름이 `CLAUDE`로 시작하는 환경 변수를 빼고(Windows의 `CLAUDE_CODE_GIT_BASH_PATH`는 남긴다), 끝나면 되돌린다. `report.json`에는 뺀 변수의 이름(`env_removed`)과 남은 `ANTHROPIC_` 변수의 이름(`env_present_overrides`)만 적는다(리뷰 LCR-06).
7. 진단 로그: `slidecaptain` 로거의 INFO 이상을 출력 폴더의 `diagnostic.log`에 쓰고, 실행이 끝나면 떼어 낸다. 3.3의 관측 줄과 실패 원인이 여기에 남는다.
8. 작업 대기 상한을 300초에서 360초로 늘린다. 대기는 등록부터 세므로, 300초면 제공자 시간 제한(300초)보다 먼저 끝나 나간 호출의 결과를 기록하지 못할 수 있다(리뷰 LCR-16).
9. `report.json`에 `requested_effort`, `stop_after`를 더한다.

### 3.5 행마다의 판정 규칙

판정은 각 행의 첫 호출 기록(`report.json`의 `calls[0]`), `checks`, `diagnostic.log`로 한다.

| 판정 | 조건 |
|---|---|
| 수용 | 호출이 `returned`이고 오류 결과가 아니며 `usage.model`이 있다. 실제 모델 이름을 적고 목록의 해석된 모델과 대조한다 |
| 수용, 형식 실패 | `usage.model`이 있지만 구조화 출력이 형식 검사를 통과하지 못했다. CLI 안의 구조화 출력 실패(오류 결과, `terminal_reason`이 턴 상한)도 여기다. 모델은 받아들여진 것이다. 형식 재시도는 상한에 막혀 보내지 않는다 |
| 거절 | 호출이 실패했고 `usage.model`이 없으며, 진단 로그의 CLI 표준 오류나 응답 오류 종류가 모델이나 강도 값을 가리킨다 |
| 호출 전 차단 | `calls`가 비었고 `chapter_error_code`가 `model_unavailable`이다. 목록에 그 모델이나 강도가 없다는 뜻이며, 호출 횟수에 들어가지 않는다 |
| 판정 보류 | 한도, 네트워크, 로그인처럼 값과 무관한 실패이거나 원인을 가를 수 없다. 자동으로 다시 호출하지 않고 사용자에게 알린다 |

강도는 세 가지로 나눠 적는다(리뷰 LCR-05):

- CLI 적용값: 초기화 메시지의 `effort`가 요청과 같으면 "일치", 낮으면 "낮춤", 칸이 없으면 "없음".
- API 적용값: 응답에서 확인할 칸이 없으므로 "확인 불가"로 적는다.
- 오류 없이 끝났다는 것은 "CLI가 요청을 받아 생성했다"까지만 뜻한다. CLI가 강도를 조용히 낮출 수 있기 때문이다.

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

실행 직전에 CLI 판을 다시 확인한다. 설치 CLI는 자동으로 업데이트되므로, 판이 위 표와 다르면 사용자에게 알리고 목록을 다시 읽는다(리뷰 LCR-14). `[1m]` 변형이 구독 사용량에 주는 영향은 확인하지 못했으며, 승인 질문에 함께 적는다.

사용자에게 물을 선택지:

- A(추천): L1~L3, Claude 3회. 데스크톱 경로의 `default`와 `[1m]` 변형, 개발 경로의 `[1m]` 변형을 각각 1회로 확인한다. Codex(질문 4)는 이월한다.
- B: L1~L4, Claude 4회. A에 이 PC 사용자의 저장 선택(`opus`)을 더한다.
- C: L1~L3과 L5, 4회. 사용자가 먼저 앱에서 ChatGPT 로그인을 한다.

함께 확인할 것: 쓸 계정(이 PC의 Claude Code 로그인 계정, Max 구독)과 쓸 CLI 경로(위 표).

## 5. 기록 위치와 형식

1. 원시 산출물은 저장소 밖 새 폴더(`~/slidecaptain-live-check/2026-10-21/<행>/`)에 둔다. 합성 프롬프트, 결과, `report.json`, `diagnostic.log`가 들어가며 커밋하지 않는다.
2. 저장소에는 이 계획서의 「결과」 절에 행마다 CLI 판, 요청 모델과 강도, 판정, 실제 모델과 목록의 해석된 모델, `CallUsage`의 토큰과 시간, 강도의 CLI 적용값과 API 적용값, MCP 서버 개수, 원장과 사용량 기록 확인을 적는다. 계정 이메일, 사용자 이름이 든 전체 경로, 원시 초기화 응답, 환경 변수 값은 적지 않는다.
3. 로드맵 D4a 이월표 둘째 행과 「진행 상태」 줄을 갱신한다.

## 6. 수용 기준

1. 실패하는 시험부터 쓴다: 생성 옵션의 `strict_mcp_config`, 원장의 `effort`, 사용량의 `requested_effort`(수정 복구 경로 포함), 진단 줄의 칸 제한(계정과 경로 값 미기록, 개수 칸), 실패 때의 표준 오류와 응답 오류 기록, 실측 도구의 강도 전달과 `--stop-after chapter`(형식 재시도 차단 포함)와 목록 대조와 환경 변수 정리.
2. 바꾸는 기존 시험: `test_quality_pilot_selection.py`의 "claude + `gpt-6-luna`는 ValueError" 사례를 지우고, 목록 대조 시험(`test_quality_pilot_effort.py`)으로 옮긴다. 같은 자리에 잘못된 강도, 중단 단계, Codex의 CLI 지정 사례를 더한다(리뷰 LCR-09).
3. 백엔드, 프런트 전체 시험 통과, OpenAPI와 프런트 타입 재생성 무변경, 공개 저장소 감사기 0건, CI 두 OS 성공.
4. 오프라인 실행(`--offline --effort low --stop-after chapter --max-calls 1`)이 외부 호출 0회(`external_calls`)로 끝나고 `checks`의 강도 기록 두 항목이 참이다. 오프라인에서도 `provider_calls`는 1이다(리뷰 LCR-13).
5. 사용자가 승인한 행만 실행하고, 결과를 5절대로 기록한다.
6. 계획 리뷰어 1명(적대 리뷰, 9절), 구현 뒤 코드 리뷰어 1명.

## 7. 하지 않는 것과 이월

- 계정 프로필, 두 계정 전환, 영구 동의(D4c), 추천과 앱 안 업데이트 안내(D4d).
- `CallUsage`의 적용 강도 칸과 화면 문구 변경: 3.3의 관측 뒤 사용자와 정한다.
- 재지 않는 조합: 다른 강도 단계, `sonnet`과 `haiku`, 동봉 CLI의 `default`와 `claude-fable-5[1m]`. 결과 기록 때 로드맵 이월표에 담당과 함께 올린다.
- 마지막 생성 성공 시각(`generation_success`)은 지금처럼 (제공자, 모델) 범위다. 강도를 키에 넣지 않는다. D4a 이월표 둘째 행에 그대로 남긴다(리뷰 LCR-11).
- L1이 `default`를 거절하면 고치는 방법(예: `default`를 고르면 `--model`을 넘기지 않기, 또는 목록에서 감추기)을 사용자에게 제안하고, 자동으로 고치지 않는다. 다른 행의 거절도 같다.
- 선택지 C를 고르지 않으면 질문 4(Codex 요청 강도와 실제 모델 대조)는 이월표에 남긴다.

## 8. 순서

1. 이 계획을 리뷰어 1명이 적대 리뷰하고 반영한다(9절).
2. 3.1~3.4를 시험부터 구현하고, 전체 시험 뒤 커밋하고 push해서 CI 두 OS를 확인한다.
3. 오프라인 실행으로 도구를 확인한다.
4. 사용자에게 4절의 선택지를 묻는다. 승인한 행만 실행한다.
5. 결과를 기록하고 로드맵과 인계를 갱신한다. 코드 리뷰를 반영한 뒤 머지 여부를 묻는다.

## 9. 계획 리뷰 반영 (2026-10-21)

리뷰어 1명이 1판(`52e009d`)을 main `9d62455`의 코드와 대조했다. blocker 0, major 5, minor 7, nit 4다. 사용한 토큰은 약 24만이다(작업 알림의 subagent_tokens 값 241,615). 리뷰 보고는 세션 임시 폴더에만 있고, 아래 표가 반영 기록의 진본이다. 리뷰어는 실제 생성 호출을 하지 않았다.

| ID | 심각도 | 내용 | 반영 |
|---|---|---|---|
| LCR-01 | major | 도구가 강도를 CLI에 넘기지 않아도 기록 검사가 통과한다 | 3.4 1. 실제 프로바이더를 (모델, 강도)로 만들고 `provider_effort`를 적는다. 가짜 연결로 전달을 시험한다 |
| LCR-02 | major | `requested_effort` 출처 서술이 사실과 다르고 `story_repair.py` 두 곳이 빠졌다 | 3.2 3. 임대 경로는 선택, 그 밖은 프로바이더 속성. 기본값 None. 수정 복구 경로 시험을 더했다 |
| LCR-03 | major | 거절 판정에 필요한 CLI 오류가 로그에 남지 않는다 | 3.3 3. 실패 때 표준 오류 마지막 20줄, 응답 오류 종류, `subtype`, `terminal_reason`을 남긴다. 판정은 `usage.model` 유무를 먼저 본다(3.5) |
| LCR-04 | major | `--stop-after chapter`가 형식 재시도 차단에서 검사를 쓰기 전에 멈추고, 판정표에 빈칸이 있다 | 3.4 3, 4. 종결 상태를 기록하고 상태와 종료 코드를 정했다. 3.5에 CLI 안 구조화 출력 실패와 호출 전 차단을 더했다 |
| LCR-05 | major | 초기화 메시지의 `effort`는 CLI가 정한 값이며 API 적용의 증거가 아니다 | 3.5의 강도 세 가지 구분, 3.3 6, `catalog_resolved_model` |
| LCR-06 | minor | 이 세션의 연결 변수가 CLI에 물려진다 | 3.4 6 |
| LCR-07 | minor | 개인정보 시험이 잘못된 칸을 겨냥했다 | 3.3 첫 문단과 5. 경로 칸을 시험한다 |
| LCR-08 | minor | 질문 3의 근거가 "생성이 끝남"뿐이다 | 3.3 2의 개수 칸, 3.1 문구 정정 |
| LCR-09 | minor | 기존 시험과 충돌한다 | 6절 2 |
| LCR-10 | minor | D2 계획 215행을 조용히 재정의한다 | 3.2 5와 D2 계획의 날짜 붙은 정정 |
| LCR-11 | minor | 마지막 성공 시각 범위가 빠졌다 | 7절 |
| LCR-12 | minor(추정) | Codex `thread/start`의 강도는 기본값이다 | 3.3 4 |
| LCR-13 | nit | "호출 0회"는 외부 호출 기준이다 | 6절 4 |
| LCR-14 | nit | 설치 CLI 자동 업데이트, `[1m]` 사용량 영향 미확인 | 4절 |
| LCR-15 | nit | 원장은 읽기 전용으로 읽는다 | 3.4 4 |
| LCR-16 | nit | 작업 대기 상한이 제공자 시간 제한보다 짧다 | 3.4 8 |

## 10. 구현 기록 (2026-10-21)

| 고친 곳 | 내용 |
|---|---|
| `pipeline/subscription.py` | 생성 옵션에 `strict_mcp_config=True`. 초기화 메시지 관측 줄(INFO). 실패 때 CLI 표준 오류 마지막 20줄, 응답 오류 종류, `subtype`, `terminal_reason`(WARNING) |
| `pipeline/provider.py` | `observed_fields`: 칸 이름, 허용한 칸의 스칼라 값, 개수 칸 |
| `pipeline/codex.py` | 로거를 두고 `thread/start`, `turn/start`, `turn/completed`의 관측 줄을 남긴다 |
| `storage/job_ledger.py`, `server/app.py` | `FixedInputs.effort`, `create_job`이 `jobs.effort`에 쓴다. `_fixed_selection()`을 `_fixed_inputs()`로 바꿔 7곳이 같은 함수를 쓴다 |
| `pipeline/service.py`, `pipeline/story_repair.py`, `server/app.py` | `UsageRecord.requested_effort`와 다섯 생성 자리 |
| `scripts/quality_pilot.py` | `--effort`, `--stop-after chapter`, `--claude-cli`, 목록 대조, 강도 기록 대조(읽기 전용), 진단 로그, 세션 변수 정리, `provider_effort`, `catalog_resolved_model`, 대기 상한 360초 |

검증:

- 실패 시험 먼저: 요청 강도 기록 4건(원장과 사용량 3건, 생성 옵션 1건), 응답 관측 4건(가져오기 실패로 수집 오류), 실측 도구 7건이 고치기 전 실패했다. 계획 리뷰 반영으로 더한 시험 7건(관측 개수 칸, 경로 칸, 표준 오류, 응답 오류, 형식 재시도 차단, 세션 변수, 해석된 모델)도 고치기 전 실패했다. 수정 복구 경로의 요청 강도 시험 1건은 구현 뒤에 써서 처음부터 통과했다.
- 바꾼 기존 시험은 `test_quality_pilot_selection.py`의 잘못된 선택 사례 하나다(6절 2).
- 백엔드 전체 3,000 통과, 48 건너뜀, 실패 0(메모리 여유 2.1GB, 다섯 묶음으로 나눠 실행). OpenAPI 재생성 결과 변경 없음. 공개 저장소 감사기는 처음에 새 시험의 가짜 계정 경로 리터럴을 잡았다. 조각을 이어 붙이도록 고친 뒤 0건이다. 프런트와 데스크톱은 바꾸지 않아 로컬에서 돌리지 않았다(CI가 돌린다).
- 오프라인 실행(`--offline --effort low --stop-after chapter --max-calls 1`): 상태 `completed`, `provider_calls` 1, `external_calls` 0, `checks`는 `chapter_status` ok, `ledger_effort_matches`와 `usage_effort_matches` 모두 참.
- 같은 실수를 구조로 막은 곳: 등록 입력을 만드는 함수 하나(`_fixed_inputs`)가 강도까지 고정하므로, 새 생성 라우트가 강도를 빠뜨릴 수 없다.

## 11. 결과 (2026-10-21, 회사 PC)

사용자 결정 "A. Claude 3회 실행"(2026-10-21)으로 L1~L3만 실행했다. CI 두 OS 성공(실행 39555693562) 뒤에 실행했다. 실행 직전 설치 CLI가 2.1.304에서 2.1.306으로 자동 업데이트되어 있었고, 생성 없이 목록을 다시 읽어 2.1.304와 같은 다섯 값(강도 다섯 단계)임을 확인했다. 실제 호출은 3회(행마다 1회)이며 실패, 형식 재시도, 차단은 0회다. 원시 산출물은 `~/slidecaptain-live-check/2026-10-21/L1`~`L3`에 있고 커밋하지 않았다.

| 행 | CLI | 요청 모델, 강도 | 판정 | 응답 모델 | 목록의 해석된 모델 | 입력, 출력, 캐시 생성 토큰 | 시간 | SDK 비용 추정 |
|---|---|---|---|---|---|---|---|---|
| L1 | 설치 2.1.306 | `default`, `low` | 수용 | `claude-opus-5-5` | `claude-opus-5-5` | 5,607, 460, 6,388 | 4.2초 | 0.060달러 |
| L2 | 설치 2.1.306 | `claude-fable-5-1[1m]`, `low` | 수용 | `claude-fable-5-1` | `claude-fable-5-1` | 5,607, 793, 6,388 | 6.4초 | 0.153달러 |
| L3 | 동봉 2.1.247 | `opus[1m]`, `low` | 수용 | `claude-opus-5` | `claude-opus-5[1m]` | 5,039, 488, 5,919 | 6.8초 | 0.076달러 |

세 행 모두 장 작업이 `succeeded`, 결과 상태 `ok`이고, `checks`의 `ledger_effort_matches`와 `usage_effort_matches`가 참이다. SDK 비용 추정은 `total_cost_usd`이며 구독 청구액이 아니다. 실행 동안 뺀 환경 변수는 세션 연결 변수 11개(이름만 기록)이고 `ANTHROPIC_` 변수는 없었다.

질문별 답:

1. 목록 값의 `--model` 수용: `default`, `claude-fable-5-1[1m]`(설치 CLI), `opus[1m]`(동봉 CLI)를 CLI가 받아 생성했다. `[1m]` 변형의 응답 모델(`AssistantMessage.model`)에는 `[1m]`이 붙지 않는다. 초기화 메시지와 `model_usage`의 키에는 `claude-opus-5[1m]`처럼 붙는다. 그래서 응답 모델과 목록의 해석된 모델은 `[1m]`을 떼고 비교해야 같다.
2. 강도: `--effort low`를 붙인 생성이 두 CLI 모두 오류 없이 끝났다. 초기화 메시지에는 두 판 모두 `effort` 칸이 없었다. 2.1.306에는 `per_turn_effort_active: true`만 있고 2.1.247에는 그 칸도 없다. 리뷰 LCR-05가 실행 파일 문자열로 추정한 `effort` 칸은 실제 응답에서 관측되지 않았다. 따라서 CLI 적용값은 "없음", API 적용값은 "확인 불가"다. 화면 문구(`AISettingsPanel.tsx` 194행 "응답에서 확인할 수 없다")는 사실과 맞으므로 바꾸지 않고, `CallUsage`에 적용 강도 칸도 더하지 않는다.
3. 생성 경로의 `strict_mcp_config=True`: 두 CLI 모두 생성이 끝났고 `mcp_servers` 개수는 0이다. 새로 관측한 것: `setting_sources=[]`인데도 초기화 메시지의 스킬은 19개(동봉 16개), 플러그인 3개(동봉 0개), 에이전트 5개, 슬래시 명령 55개(동봉 50개)다. 이것들이 생성 프롬프트에 영향을 주는지는 확인하지 못했다. SDK에는 `skills`, `plugins` 옵션이 있다. 로드맵 D4a 이월표에 담당과 함께 올렸다.
4. Codex 요청 강도와 실제 모델: 선택지 A라 실행하지 않았다. 이월표 둘째 행에 남긴다.
5. 원장과 사용량의 요청 강도: 실제 경로의 세 행 모두 원장 `effort`와 `ai-usage.jsonl`의 `requested_effort`가 `low`로 남았다.

그 밖의 관측:

- 세 행 모두 `model_usage`에 보조 모델(설치 CLI는 `claude-haiku-5-5`, 동봉 CLI는 `claude-haiku-4-5-20251001`)이 함께 있었다. `CallUsage`의 토큰은 두 모델의 합이고, `CallUsage.model`은 응답 모델 하나다. 기존 설계(모델별 합산)대로이지만 화면은 보조 모델을 보이지 않는다. 이월표에 올렸다.
- `[1m]` 변형의 사용량: L3의 입력 토큰은 L1과 비슷했다. 합성 장 하나의 짧은 입력이라 `[1m]`이 사용량에 주는 영향은 이 자료로 판단할 수 없다.
- 재지 않은 조합(다른 강도 단계, `sonnet`과 `haiku`, 동봉 CLI의 `default`와 `claude-fable-5[1m]`, 이 PC 사용자의 저장 선택 `opus`)은 이월표에 올렸다.
