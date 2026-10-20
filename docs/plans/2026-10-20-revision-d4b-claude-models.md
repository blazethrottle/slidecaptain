# 개정판 D4b: Claude 공식 모델 목록, 정확 버전, 추론 강도

작성: 2026-10-20(회사 PC, Windows). 상태: 1판. 브랜치 `feat/d4b-claude-models`(기준 main `e6e3eb8`).

상위 문서: [구현 설계](../architecture/2026-10-02-desktop-revision.md) 4절 `ModelCapability`와 7절 D4, [D4a 계획](2026-10-19-revision-d4a-model-effort.md), 로드맵 D4a 이월표 첫 행("Claude는 기존 별칭이며 공식 모델/해석된 정확 버전/지원 강도 미구현"), [D1 인계](../handoffs/2026-10-02-desktop-d1.md) 「공식 AI 지원 조사」.

## 1. 사용자 결정

2026-10-20 사용자 지시 "D 실행 후 B". B는 직전 보고의 "Claude 공식 모델 목록, 정확한 버전, 지원 강도 연결(D4a의 후속). 공식 조회 방법부터 확인해야 하고, 실제 CLI 호출이 필요할 수 있습니다"다. 세션은 이를 D4a 이월표 첫 행(D4b)의 착수 승인으로 읽는다. 계정 프로필, 영구 동의, 추천(D4c, D4d)과 실제 적용 강도의 계측은 이 단위에서 하지 않는다. 실제 AI 생성 호출은 0회다. CLI의 초기화 응답(모델 메타데이터)만 읽는다.

## 2. 지금 코드와 실측 (기준 `e6e3eb8`)

1. `pipeline/connections.py` `ClaudeConnection.models()`는 별칭 세 개(`sonnet`, `opus`, `haiku`)를 고정으로 돌려주고 지원 강도를 비워 둔다. `_supports_effort`는 ChatGPT에서만 강도를 받는다. `SubscriptionProvider`는 강도를 전달하지 않는다. 화면(`AISettingsPanel.tsx`)도 강도 선택을 ChatGPT에서만 보인다.
2. 설치된 `claude-agent-sdk` 0.2.145는 `ClaudeSDKClient.get_server_info()`로 CLI 초기화 응답을 주고, `ClaudeAgentOptions.effort`(`low`, `medium`, `high`, `xhigh`, `max`)를 CLI `--effort`로 넘긴다.
3. 회사 PC 실측(2026-10-20, 생성 호출 없음, 모델 메타데이터만 출력):
   - 임시 빈 프로필: `default`(→ `claude-opus-5[1m]`), `opus[1m]`(→ `claude-opus-5[1m]`), `sonnet`(→ `claude-sonnet-5`), `haiku`(→ `claude-haiku-4-5-20251001`). 앞 세 개는 강도 5단계를 광고하고 `haiku`는 강도 정보가 없다(`null`).
   - 사용자 프로필: 위 네 개에 `claude-fable-5[1m]`(Fable, → `claude-fable-5`)가 더 있다. 목록은 계정마다 다르다.
   - 기존 별칭 `opus`는 두 목록 모두에 없다(`opus[1m]`만 있다).
   - 초기화 응답에는 계정 정보(`account`)도 들어 있다. 이 단위는 모델 항목만 읽고 계정 정보는 저장하거나 기록하지 않는다.
4. `settings()`와 `generation()`은 부를 때마다 `models()`를 부른다. Codex는 실행 중인 앱 서버에 묻지만, Claude는 조회마다 CLI를 새로 띄워야 한다(몇 초).

## 3. 설계

1. `ModelOption`에 해석된 정확 버전 `resolved_model`(모르면 null)을 더하고, 목록 출처에 `claude_sdk_init`을 더한다.
2. `ClaudeConnection.models()`는 공식 SDK 초기화 응답의 모델 항목을 읽는다. 사용자의 기존 Claude Code 프로필(생성과 같은 프로필)을 쓰고, 도구와 사용자 설정 파일을 읽지 않으며(`tools=[]`, `setting_sources=[]`), 프롬프트를 보내지 않는다. 강도는 SDK가 받는 다섯 단계만 남긴다. 조회는 별도 스레드의 이벤트 루프에서 30초 제한으로 한다.
3. 목록은 10분 동안 캐시한다. 연결 신원(로그인 여부, 인증 방식, 계정)이 바뀌면 캐시를 버린다. 조회가 실패하면 캐시가 있을 때 그 목록을 쓰고, 없으면 원인 코드(`provider_missing`, `provider_timeout`, `provider_call_failed`)와 함께 목록 오류로 알린다.
4. 강도 허용 규칙을 제공자와 관계없이 "선택한 모델의 지원 목록에 있는 값"으로 바꾼다. 지원 정보가 없는 모델(`haiku` 등)은 제공자 기본값만 쓴다. Claude 생성은 고른 강도를 `ClaudeAgentOptions.effort`로 넘긴다. 강도가 없으면 지금처럼 넘기지 않는다.
5. 저장된 선택이 새 목록에 없으면(예: `opus`) D4a와 같이 자동으로 바꾸지 않고, 생성 전에 "선택한 모델을 사용할 수 없습니다. AI 연결 화면에서 다시 선택"으로 막는다. 기본 선택 `sonnet`은 목록에 있다.
6. 화면은 Claude에서도 강도 선택을 보이고, 모델 이름 옆에 해석된 정확 버전을 보인다. 안내 문구에 "목록은 설치된 Claude Code가 이 계정에 알려 준 것이며 사용 권한과 한도는 실제 요청 때 확인된다"를 적는다.

## 4. 수용 기준

1. 가짜 SDK 응답으로 모델 목록, 정확 버전, 강도 필터, `null` 강도, 캐시, 신원 변경 무효화, 실패 시 캐시 사용과 오류 코드가 시험된다.
2. Claude 선택에서 지원 목록 안의 강도는 저장되고 생성 요청에 전달되며, 지원 밖의 강도는 저장과 생성 전에 막힌다.
3. 회사 PC에서 백엔드 함수로 실제 목록을 읽어 2절 3의 사용자 프로필 목록과 같은지 확인한다(생성 호출 없음).
4. 백엔드, 프런트, 데스크톱 전체 시험, 생성 파일 무변경, CI 두 OS 성공. 리뷰어 1명(계획과 코드).

## 5. 하지 않는 것과 이월

- 실제 적용 모델과 강도의 계측(원장/사용량 기록): 실제 생성 호출이 필요하다. 로드맵 D4a 이월표 둘째 행 그대로.
- 계정 프로필, 두 계정 전환, 영구 동의(D4c), 추천과 앱 안 업데이트 안내(D4d).
- 기존 `opus` 선택 사용자의 안내 문구는 업데이트 안내 문서에 더한다(`docs/releases/revision-update-notes.md`, D 브랜치가 머지된 뒤).

## 6. 구현 기록 (2026-10-20)

| 고친 곳 | 내용 |
|---|---|
| `pipeline/connections.py` | `ModelOption.resolved_model`, 출처 `claude_sdk_init`. `_read_claude_catalog`(CLI가 없으면 프로세스를 띄우기 전에 `provider_missing`), `_claude_catalog_models`(SDK가 받는 강도 다섯 단계만, 계정 정보 미사용). `ClaudeConnection.models()`는 10분 캐시, 실패하면 마지막 목록을 쓰고 1분 뒤 다시 조회, 목록이 없으면 원인 코드로 알리고 1분 동안 다시 띄우지 않는다. `invalidate_models()`를 신원 변경 관측에서 부른다. `_supports_effort`는 제공자와 관계없이 지원 목록 기준 |
| `pipeline/subscription.py` | `SubscriptionProvider(effort=...)`를 `ClaudeAgentOptions.effort`로 넘긴다. 강도가 없으면 None(넘기지 않음) |
| 화면 | `AISettingsPanel`은 Claude에서도 강도 칸을 보이고, 모델 이름 옆에 정확 버전을 보인다. 현재 적용 줄, 생성 상태 줄(`AiStatusLine`), 전송 동의 창(`AiConsentDialog`)이 Claude의 요청 강도도 보인다 |
| 오류 코드 표 | 새 raise 자리 2개를 `test_jobs_error_codes.py` 표에 더했다 |

검증:

- 실패 시험 먼저: 백엔드 `test_claude_models.py` 13건(9 실패, 4 오류), 프런트 4건.
- 회사 PC 실측(생성 호출 없음): 새 코드의 `ClaudeConnection().models()`가 사용자 프로필에서 5개(`default`, `opus[1m]`, `claude-fable-5[1m]`, `sonnet`, `haiku`)와 정확 버전, 강도를 돌려주었다(2절 3과 같음). 첫 조회 2.8초, 캐시 조회 0.0초. 설정 라우트는 동기 함수라 작업 스레드에서 돌고, 생성 임대는 작업 실행기 스레드에서 잡으므로 첫 조회가 서버 이벤트 루프를 막지 않는다.
- 백엔드 전체 2,969 통과, 48 건너뜀, 실패 0(두 번에 나눠 실행). 프런트 1,339 통과, 타입 검사, 디자인 토큰 96개 통과. 데스크톱 31 통과.
