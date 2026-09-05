# 단계 5A 묶음 C: AI 사용량과 원가 근거 계획서 (2026-09-04, 적대 리뷰 반영 2026-09-05)

> 마스터 플랜 [2026-09-01-phase5a-master-plan.md](2026-09-01-phase5a-master-plan.md) 묶음 C 의 상세 계획. B 완료(2026-09-04) 뒤 착수한다.
> 브랜치 `codex/phase-5a` 에서 태스크마다 커밋하고, 태스크별 독립 리뷰와 묶음 최종 리뷰를 거친 커밋을 `origin/codex/phase-5a` 에 push 한다. main 머지는 5A 전체 완료 후다(사용자 결정 2026-09-03).
> 리뷰 게이트: 계획서 적대 리뷰(세 관점 병렬, 2026-09-05 25건 반영, 아래 "적대 리뷰 반영" 절) → 태스크별 TDD 구현(태스크마다 커밋, 구현자와 독립 리뷰어 분리, 리뷰어는 구현 직전 커밋에서 RED 재실증) → 묶음 최종 리뷰(세 관점 + 반박자) → 반영과 검증 → push. B 묶음과 같다.
> **실호출 스모크는 사용자 승인 사항**: 실제 AI 호출은 구독 사용량을 쓰므로 이 묶음의 자동 테스트는 전부 가짜 프로바이더와 SDK 자료형으로 한다. SDK 가 실제로 돌려주는 값의 형태(가정 1 의 "실측 필요" 항목)는 D2 의 실기기 관통에서 1회 호출로 확인하고, 그 전까지 코드는 값이 없어도 동작하도록 설계한다.

## 범위와 원인 묶음

| 태스크 | 포함 항목 | 공통 원인 |
|---|---|---|
| C1. 프로바이더 계측 | 원시 호출 1건의 실제 모델, 입력과 출력과 캐시 토큰, 처리 시간, 턴 수, SDK 제공 비용값을 `ProviderResponse` 에 선택 필드로 싣는다. 실패로 끝났어도 SDK 가 결과 메시지를 줬으면 그 사용량을 예외에 실어 보낸다. 결과 메시지를 받은 뒤 스트림 종료를 기다리다 타임아웃으로 결과를 잃는 기존 결함을 함께 고친다 | 이월표 "`ProviderResponse` 가 SDK 의 모델, 토큰, 처리 시간, 호출 수, 비용값을 버려 앱 관리형 AI 의 원가 근거가 없음"(2026-09-01 상업화 감사). `SubscriptionProvider.complete` 가 `ResultMessage` 에서 `structured_output` 과 `result` 만 꺼낸다 |
| C2. 서비스 합산 | 생성 작업 1건(구조안, 장 생성, 수동 축약) 안의 모든 호출(형식 재시도, 자동 축약 포함)을 빠짐없이 세어 합산하고 결과 모델에 싣는다. 실패한 호출도 센다 | `GenerationService` 가 프로바이더를 세 경로에서 각각 부르고 합산 지점이 없다 |
| C3. 로컬 기록과 API | 프로젝트 폴더의 `ai-usage.jsonl` 에 작업 1건 = 1줄로 내용 없이 누적, 응답 모델 확장, OpenAPI 와 프런트 타입 재생성 | 기록 자리가 없다. 재시작하면 `last_generation_at` 조차 사라진다(프로세스 메모리) |
| C4. 화면 표시 | 구조안 화면과 장 생성 패널의 결과 아래에 사용량 한 줄. 값이 없으면 "미확인" | 화면이 사용량을 표시할 데이터가 없다 |

이 묶음에 넣지 않는 것(마스터 플랜 "만들지 않는 것" 과 로드맵 C 행): 결제, 요금제, 구독 한도, 통화 비용의 임의 환산(SDK 값이 없으면 숫자를 만들지 않는다), 원격 분석 서버, 프로젝트 누적 합계 API 와 화면(작업 단위 표시까지가 이 묶음이다. 누적은 기록 파일이 있으니 5B 에서 필요가 확인되면 붙인다. 이월표 등재), 기록 파일의 회전과 삭제(작업 1건이 수백 바이트라 수천 건이라도 수 MB), `AppStatus` 의 확장(마지막 성공 시각은 종전대로 프로세스 메모리), SDK 의 `output_format` 폐기 예정 대응(적대 리뷰 발견. CLI v2.1.260 이 `output_config.format` 을 권하나 설치된 SDK 0.2.145 에는 그 필드가 없다. 이월표에 업그레이드 리스크로 등재).

## 가정 (적대 리뷰가 검증한 것)

1. **SDK 계약은 `claude-agent-sdk==0.2.145` 의 `types.py` 다.** `ResultMessage` 필드(이 Mac 의 가상환경에서 소스로 확인, 2026-09-04. 적대 리뷰가 소스와 설치된 CLI v2.1.260 바이너리 문자열로 재확인): `duration_ms: int`, `duration_api_ms: int`, `num_turns: int`(셋 다 기본값 없는 필수 정수라 성공 시 항상 채워진다), `total_cost_usd: float | None`, `usage: dict[str, Any] | None`, `model_usage: dict[str, ModelUsage] | None`, `stop_reason: str | None`, `terminal_reason: str | None`(쿼리 루프가 왜 끝났는지: `completed`, `max_turns`, `aborted_streaming` 등. `stop_reason` 과 다른 축), `api_error_status: int | None`, `is_error: bool`. `is_error` 는 `usage`, `model_usage`, `total_cost_usd` 와 독립 필드라 **실패한 결과 메시지도 그때까지의 사용량을 가질 수 있다.** `ModelUsage` 는 TypedDict 이고 키가 **camelCase** 다: `inputTokens`, `outputTokens`, `cacheReadInputTokens`, `cacheCreationInputTokens`, `webSearchRequests`, `costUSD`, `contextWindow`, `maxOutputTokens`, 선택 `canonicalModel`, `provider`. `AssistantMessage.model: str` 은 메시지마다 실제 모델 문자열을 준다(파서가 Messages API 응답의 `message.model` 을 그대로 옮긴다). 파서(`_internal/message_parser.py`)는 CLI JSON 의 `usage` 와 `modelUsage` 를 변환 없이 옮긴다. **실측 필요(D2 관통 1회 호출)**: ① `usage` dict 의 키 이름이 snake_case(`input_tokens`, `output_tokens`, `cache_read_input_tokens`, `cache_creation_input_tokens`)인지(CLI 바이너리에 이 네 키가 연속 등장해 강한 정황 증거) ② `model_usage` 가 실제로 채워지는지 ③ **`model_usage` 가 비어 `usage` dict 로 폴백할 때 그 값이 세션 누적인지 마지막 턴 값인지**(CLI 내부 주석에 "per-turn main-loop usage keeps its turn-end value" 서술이 있어, `max_turns=2` 구조에서 정리 턴만 반영될 위험이 있다. 그러면 "미확인" 이 아니라 "그럴듯한데 크게 틀린 값" 이 된다). **실측 결과(2026-09-06 D2 관통, 실호출 1회, 원시 로그 실측)**: ① snake_case 확인(`input_tokens`, `output_tokens`, `cache_read_input_tokens`, `cache_creation_input_tokens` 외 7개 키) ② `model_usage` 채워짐(키 2개: 요청한 sonnet 과 CLI 보조 haiku) ③ **`usage` dict 는 마지막 턴 값**(`input_tokens` 2 대 `model_usage` 합 2,239. 우려가 사실이었다) → bb5a4a4 에서 폴백이 토큰을 채우지 않도록 수정했고 `token_source="usage"` 는 출처 표시로만 남는다. 그래서 토큰의 1순위 출처는 `model_usage`(키가 모델 id, 값이 토큰과 비용. 세션 누적값이라 수동 합산 불필요)이고, 없으면 `usage` dict 를 `.get` 으로 읽되 **`token_source="usage"` 로 표시**해 화면이 "대략" 을 붙이며, 그것도 없으면 `None` 이고 `token_source="none"`. 실제 모델 문자열은 스트림에서 처음 본 `AssistantMessage.model` 을 우선하고 없으면 `model_usage` 의 키(1개일 때), 그것도 없으면 `None`. 별칭(`sonnet`)은 `requested_model` 로 따로 적는다(실제 모델이 아니다). `model_usage` 에 모델이 2개 이상이면 토큰과 비용은 합산하고 모델은 `AssistantMessage.model` 을 쓴다(CLI 문자열상 구조화 출력 재시도는 같은 모델의 자기 재시도라 2개가 될 개연성은 낮다).
2. **수집 단위는 원시 호출 1건, 합산 단위는 생성 작업 1건(API 요청 1건)이다.** 구조안 생성 = 생성 1회 + 형식 재시도 최대 1회. 장 생성 = 생성 1회 + 형식 재시도 최대 1회 + 자동 축약 최대 1회. 수동 축약 = 축약 1회 + 형식 재시도 최대 1회. 호출 목적은 `generate`, `format_retry`, `condense` 셋이고, 형식 게이트 helper 는 최초 호출의 목적을 인자로 받는다(수동 축약의 재시도는 `[condense, format_retry]`). **`calls` 는 시도한 호출 전부(성공 + 실패)이고 `failed_calls` 는 그 부분집합이며 `len(records) == calls` 가 항상 성립한다.** 예외로 끝난 호출은 두 종류다: ⓐ SDK 가 `is_error=True` 결과 메시지를 준 경우는 그 사용량을 예외(`ProviderCallFailed.usage`)에 실어 보내고 `ok=False` 로 기록한다 ⓑ 결과 메시지 없이 끊긴 경우(CLI 부재, 연결 실패, 타임아웃)는 사용량 없이 기록하고 `unmeasured_calls` 로 센다. 축약 호출 실패는 결과를 살리므로 작업은 `ok` 인데 `calls=2, failed_calls=1` 이 된다.
3. **없는 값은 만들지 않는다.** 합계 규칙: **사용량 객체가 있는 호출**(성공 호출과 ⓐ 유형 실패 호출) 전부가 그 필드의 값을 주면 합계, 하나라도 없으면 `None` 이고 `missing` 목록에 필드 이름을 적는다(부분 합계는 과소 집계라 더 해롭다). `cost_usd` 도 같다. ⓑ 유형 호출은 합계에 들어갈 값이 없으므로 `unmeasured_calls` 로 따로 세고 화면이 "측정되지 않은 호출 N회 제외" 를 붙인다. `0.0` 은 값이다(모든 호출이 `0.0` 이면 합계도 `0.0`. SDK 가 가격표로 산정한 값이고 구독에서는 청구액이 아니다). 타입은 토큰 4종과 `duration_ms`, `duration_api_ms` 가 `int | None`, `cost_usd` 가 `float | None` 이다(합계도 같다. 정수 합은 정수다). 처리 시간은 `duration_ms`(CLI 왕복 전체)와 `duration_api_ms`(API 시간) 둘 다 싣고 화면은 전체만 보인다. `num_turns` 는 SDK 가 `complete()` 한 번 안에서 도는 내부 턴 수이고 `calls` 는 서비스가 `complete()` 를 부른 횟수다(다른 축. 필드 주석과 설계서 4.4 에 명시).
4. **로컬 기록에는 내용이 없다.** 파일은 `projects/<이름>/ai-usage.jsonl`, 작업 1건 = 1줄(UTF-8, LF), 필드는 `ts`(ISO, 로컬 시간대), `kind`(`structure`, `chapter`, `condense`), `chapter_id`, `outcome`(`ok`, `format_error`, `failed`), `requested_model`, `summary`(가정 3 의 합계: `calls`, `failed_calls`, `unmeasured_calls`, `models`, 토큰 4종, 시간 2종, `cost_usd`, `missing`), `records`(호출별 `purpose`, `ok`, `usage`: 가정 1 의 `CallUsage` 전체 또는 `null`). **프롬프트, 자료, 지시사항, 응답 원문, 구조화 응답, 슬롯, 오류 메시지 본문(`errors` 문자열 포함)은 어떤 필드에도 넣지 않는다**(설계서 2.6 의 5항 "문서 원문은 수집 대상에서 제외" 를 로컬 기록에도 적용. 적대 리뷰가 필드 전부를 대조해 문서 원문이 들어갈 자리가 없음을 확인했다: 고정 열거값, 숫자, 서버 생성 id 뿐). 기록은 `store.locked(name)` 안에서 append 하고, 기록 쓰기 실패는 로그만 남기고 생성 결과를 막지 않는다(사용자 관점에서 기록은 부가 기능이다). 저장 위치는 감사기의 로컬 데이터 폴더 규칙과 `.gitignore` 의 `/projects/` 에 이미 포함된다.
5. **작업이 실패해도 그때까지의 호출은 기록된다.** 서비스의 세 공개 메서드는 `on_usage` 콜백을 받아 `finally` 에서 한 번 부른다. 프로바이더 예외로 라우트가 503 을 돌려주는 경우에도 `outcome=failed` 로 1줄이 남는다. **프로바이더 호출 전에 나는 `ValueError`(없는 장, 템플릿 불일치)는 `on_usage` 를 부르지 않고 그대로 던진다**(API 경로에서는 라우트가 먼저 걸러 도달하지 않는다). 응답 모델에는 성공 결과에만 `usage` 가 실린다(예외 응답은 종전 형식 그대로). **수집기는 요청별 지역 변수다**: `GenerationService` 는 `create_app` 에서 1회 생성되어 요청 간 공유되므로 수집기를 `self` 에 두면 동시 요청이 섞인다. 각 공개 메서드 진입 시 만들어 `_complete` 에 매개변수로만 전달하고 `self` 에 저장하지 않는다. **우회 방지**: 프로바이더 속성은 `self._provider` 로 두고 `_complete` 만 그것을 부른다. 정적 회귀 테스트가 `service.py` 소스에서 `_provider.complete(` 가 `_complete` 정의부에만 나타나는지 확인한다(새 호출이 합산을 우회하면 테스트가 잡는다).
6. **응답 모델 확장은 필수 필드다.** `StructureResult` 와 `ChapterResult` 에 `usage: GenerationUsage` 를 추가한다(기본값 없음: 합산이 빠진 경로를 타입으로 막는다. 적대 리뷰가 `dump_openapi.py` 로 확인: 현재 `required` 는 `["status"]` 뿐이고 기본값 없는 필드는 pydantic 이 `required` 로 올린다). 그 결과 프런트 타입에서도 필수가 되어 기존 테스트의 결과 목 **20곳**(`StructureScreen.test.tsx` 13, `client.test.ts` 3, `GeneratePanel.test.tsx` 2, `ProjectView.test.tsx` 1, `ProjectView.consent.test.tsx` 1. `raw_text:` 를 표지로 grep 한 실측)이 깨지므로 C3 이 공용 목 helper(`frontend/src/test/usage.ts` 의 `emptyUsage()`)를 두고 전부 갱신한다. `client.test.ts` 의 3곳은 `JSON.stringify` 문자열이라 정적 검사에 걸리지 않지만 일관성을 위해 함께 고친다. `client.ts` 에 `export type GenerationUsage = components["schemas"]["GenerationUsage"]` 재노출 한 줄을 추가한다(테스트가 전부 `../api/client` 에서 타입을 가져오는 관례).
7. **화면은 한 줄이고 숫자를 지어내지 않는다.** 예: "AI 사용량: 호출 2회(형식 재시도 1회 포함), 입력 12,345 토큰, 출력 1,234 토큰, 처리 8.2초, 참고 비용 $0.0123 (AI 도구가 계산한 값으로 실제 청구액이 아닙니다)". 값이 `None` 이면 그 항목만 "미확인" 으로 쓴다("토큰 미확인", "비용 미확인"). `token_source="usage"` 인 호출이 하나라도 있으면 토큰 앞에 "대략" 을 붙인다(가정 1 ③). (2026-09-06 정정: 관통 실측 뒤 폴백은 토큰을 채우지 않으므로 이 경우 화면은 "토큰 미확인" 이 되고 "대략" 분기는 도달하지 않는다. bb5a4a4) `unmeasured_calls > 0` 이면 "측정되지 않은 호출 N회 제외" 를 붙인다. 캐시 토큰은 입력 토큰과 별도 항목이며 0 이면 생략한다. 실제 모델이 있으면 앞에 붙인다("claude-sonnet-4-5 로"). 승인 루프의 합계 줄은 화면이 더하며, 실패한 장은 결과 자체가 없어 합계에서 빠지므로 **실패한 장이 하나라도 있으면 "(실패한 장의 사용량은 이 합계에 포함되지 않았습니다. 정확한 기록은 프로젝트 폴더의 ai-usage.jsonl)" 를 덧붙인다**(서버 기록과 화면 합계가 갈라지는 지점을 숨기지 않는다).

## 태스크 C1: 프로바이더 계측

**변경 (`backend/slidecaptain/pipeline/provider.py`, `subscription.py`)**

- `provider.py`: pydantic `class CallUsage(BaseModel, frozen=True)`: `model: str | None`, `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_creation_tokens`: `int | None`, `duration_ms`, `duration_api_ms`, `num_turns`: `int | None`(주석: SDK 내부 턴 수. 서비스의 호출 수와 다른 축), `cost_usd: float | None`, `stop_reason: str | None`, `terminal_reason: str | None`, `api_error_status: int | None`, `token_source: Literal["model_usage", "usage", "none"]`. `ProviderResponse` 에 `usage: CallUsage | None = None` 추가. `ProviderError.__init__(self, message: str, *, usage: CallUsage | None = None)` 로 예외에 선택 속성 `usage` 를 둔다(기본 `None`. 기존 `raise ProviderCallFailed("문구")` 호출은 그대로 동작).
- `subscription.py`: `_consume` 은 **`ResultMessage` 를 보는 즉시 반환**한다(`break`. 종전에는 스트림이 닫힐 때까지 돌아 CLI 종료 지연이 타임아웃으로 이어지면 이미 받은 결과를 잃었다). 처음 본 `AssistantMessage.model` 을 기억한다. `ResultMessage` 에서 `CallUsage` 를 만드는 순수 함수 `build_call_usage(result, assistant_model) -> CallUsage` 를 두고(가정 1 의 출처 우선순위와 `token_source`, 다중 모델 합산), 성공이면 `ProviderResponse(structured, raw_text, usage=...)`, `is_error` 면 `ProviderCallFailed("종전 문구", usage=build_call_usage(...))`. 결과 없이 끝난 예외(타임아웃, CLI 부재, 연결 실패)는 종전대로 `usage=None`. `api_error_status` 가 있으면 경고 로그에 숫자만 남긴다(사용자 문구는 종전 그대로).

**테스트 (실패부터, `backend/tests/test_subscription_provider.py`)**

- `ResultMessage` 에 `model_usage={"claude-sonnet-4-5-20250929": {...camelCase...}}`, `total_cost_usd=0.0123`, `duration_ms=8200`, `duration_api_ms=7900`, `num_turns=2`, `terminal_reason="completed"` 를 주면 `CallUsage` 가 그대로 채워지고 `token_source="model_usage"`.
- `model_usage` 없이 `usage={"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 3, "cache_creation_input_tokens": 0}` 만 있으면 그 값과 `token_source="usage"`. (2026-09-06 정정: 실측 뒤 토큰 4종은 `None` 이고 `token_source="usage"` 만 남는다. bb5a4a4) 둘 다 없으면 토큰 4종이 `None`, `token_source="none"`, 처리 시간과 턴 수는 채워진다.
- `model_usage` 에 모델 2개면 토큰과 비용이 합산되고 `model` 은 `AssistantMessage.model`.
- 스트림에 `AssistantMessage(model="claude-sonnet-4-5-20250929")` 가 있으면 `model` 이 그 값이고, 없고 `model_usage` 키가 1개면 그 키, 둘 다 없으면 `None`. `total_cost_usd=None` 이면 `cost_usd` 가 `None` 이다(0 으로 바꾸지 않는다).
- `is_error=True, api_error_status=529, usage={...}, total_cost_usd=0.004` 면 `ProviderCallFailed` 이고 `e.usage.input_tokens` 와 `e.usage.cost_usd` 가 채워지며 `e.usage.api_error_status == 529`, 사용자 문구에 숫자나 영문이 섞이지 않는다.
- 가짜 스트림이 `ResultMessage` 를 준 뒤 `asyncio.sleep(3600)` 으로 멈춰도 `complete()` 가 즉시 성공을 돌려준다(타임아웃 전에 반환. 시간 의존 단언 없이 `timeout_s` 를 작게 주고 결과가 예외가 아님을 단언).
- 기존 `test_complete_returns_structured_and_raw` 의 전체 동등 비교(`resp == ProviderResponse(structured=..., raw_text=...)`)는 성공 시 `usage` 가 항상 채워지므로 깨진다. 필드별 비교로 고친다. 나머지 기존 테스트는 그대로 통과한다.

## 태스크 C2: 서비스 합산

**변경 (`backend/slidecaptain/pipeline/service.py`)**

- pydantic 모델 `CallUsageRecord`(`purpose: Literal["generate", "format_retry", "condense"]`, `ok: bool`, `usage: CallUsage | None`. C1 의 `CallUsage` 를 중첩해 필드를 다시 선언하지 않는다), `GenerationUsage`(`calls: int`, `failed_calls: int`, `unmeasured_calls: int`, `models: list[str]`, 토큰 4종과 `duration_ms`, `duration_api_ms`: `int | None`, `cost_usd: float | None`, `missing: list[str]`, `records: list[CallUsageRecord]`), `UsageRecord`(`ts`, `kind`, `chapter_id`, `outcome`, `requested_model`, `summary: GenerationUsage`).
- 내부 `_UsageCollector`: `record(purpose, usage, ok)` 로 호출을 쌓고 `summary()` 가 가정 3 의 규칙으로 합산한다. **각 공개 메서드 진입 시 지역 변수로 만들어 매개변수로만 전달한다(`self` 에 저장 금지).** 프로바이더 속성은 `self._provider` 로 바꾸고 모든 호출은 `_complete(prompt, schema, purpose, collector)` 한 곳을 지난다(성공이면 `response.usage` 기록, `ProviderError` 면 `e.usage` 를 `ok=False` 로 기록한 뒤 재발생). `_call_with_format_gate(prompt, schema, parse, purpose, collector)` 로 시그니처를 바꿔 구조안과 장 생성은 `generate`, 수동 축약은 `condense` 를 넘기고 재시도는 `format_retry` 다. 자동 축약 호출은 `condense`.
- 세 공개 메서드에 `on_usage: Callable[[UsageRecord], None] | None = None` 을 추가하고 `try/finally` 로 작업 종료 시 한 번 부른다(가정 5: 프로바이더 호출 전 `ValueError` 는 `finally` 밖에서 먼저 던진다). 콜백 예외는 삼키고 로그만 남긴다. `StructureResult` 와 `ChapterResult` 에 `usage: GenerationUsage` 를 추가한다. `requested_model` 은 `GenerationService` 생성자 인자(`requested_model: str | None = None`)로 받는다.

**테스트 (실패부터, `backend/tests/test_generation_service.py`)**

- 구조안 생성 성공: `calls=1, failed_calls=0, unmeasured_calls=0`, 토큰 합계와 비용이 `CallUsage` 값과 같고 `models=["claude-sonnet-4-5-20250929"]`, `records[0].purpose == "generate"`, `len(records) == calls`.
- 형식 재시도 경로: `calls=2`, 목적이 `["generate", "format_retry"]`, 토큰이 두 호출의 합. 재시도도 실패해 `format_error` 인 결과에도 `usage.calls == 2`.
- 장 생성에서 자동 축약: 목적 `["generate", "condense"]`(재시도가 있으면 `["generate", "format_retry", "condense"]`). 축약 호출이 `ProviderCallFailed(usage=...)` 로 실패하면 결과는 `ok`, `calls=2, failed_calls=1, unmeasured_calls=0`, `records[-1].ok is False`, 실패 호출의 토큰이 합계에 포함된다. `ProviderCallFailed()`(usage 없음)로 실패하면 `unmeasured_calls=1` 이고 합계는 나머지 호출 값.
- 수동 축약 + 형식 재시도: 목적 `["condense", "format_retry"]`.
- 한 호출만 토큰이 `None` 이면 합계가 `None` 이고 `missing` 에 그 필드가 있다. 비용이 한 호출에서만 없어도 `cost_usd` 는 `None`. 전부 있으면 합계. **모든 호출의 `cost_usd=0.0` 이면 합계도 `0.0`(`None` 아님)**.
- `on_usage` 가 작업마다 정확히 1회 불리고, 첫 호출이 예외로 끝나도 `outcome="failed"` 로 불린다. 콜백이 예외를 던져도 결과가 돌아온다. 없는 장 `ValueError` 에서는 불리지 않는다.
- **동시 요청 격리**: `asyncio.gather` 로 생성 두 건을 동시에 돌려(스텁이 `asyncio.sleep(0)` 으로 양보) 각 `on_usage` 레코드의 `calls` 와 토큰이 자기 호출만 담는다.
- **우회 방지 정적 테스트**: `service.py` 소스에서 `_provider.complete(` 문자열이 정확히 1회(`_complete` 안)만 나타난다.
- `UsageRecord.model_dump_json()` 에 프롬프트 조각(자료 문장 "시장 규모는 500억 원이다"), `raw_text`, 슬롯 텍스트가 없다(문자열 부재 단언).
- 기존 테스트 전부 통과(`on_usage` 기본값 `None`, `self.provider` 를 참조하던 테스트가 있으면 `_provider` 로 갱신).

## 태스크 C3: 로컬 기록과 API

**변경 (`backend/slidecaptain/storage/file_store.py`, `backend/slidecaptain/server/app.py`, 재생성 산출물, `frontend/src/api/client.ts` 타입 재노출, 프런트 테스트 목)**

- `ProjectStore` Protocol 과 `FileProjectStore` 에 `append_usage(name: str, line: str) -> None` 추가: `projects/<이름>/ai-usage.jsonl` 에 `locked(name)` 안에서 한 줄 append(끝에 LF, `encoding="utf-8"`, `newline="\n"`). 파일이 없으면 만든다. 프로젝트 이름 검증은 기존 `_project_dir` 경로를 그대로 탄다.
- `app.py`: 생성 3종 라우트가 `on_usage=lambda rec: _append_usage(name, rec)` 를 넘긴다. `_append_usage` 는 `rec.model_dump_json()` 을 `store.append_usage` 로 쓰고 예외는 경고 로그로 삼킨다. `GenerationService` 생성 시 `requested_model=getattr(provider, "model", None)`.
- (2026-09-05 정정: 이 항목은 실제로 C2 커밋 9401389 에서 수행했다. 아래 "실행 순서" 절의 실행 편차 참조. 최종 리뷰 gate-docs F3) OpenAPI(`backend/openapi.json`)와 프런트 타입(`frontend/src/api/types.ts`) 재생성. `client.ts` 에 `GenerationUsage` 타입 재노출 한 줄(프런트 코드 수정의 유일한 예외). 프런트 결과 목 20곳에 `usage: emptyUsage()` 추가(`frontend/src/test/usage.ts` 신설: `calls: 0, failed_calls: 0, unmeasured_calls: 0, models: [], 토큰과 시간과 비용 null, missing: [], records: []`). 프런트 화면 코드는 C4 범위라 수정하지 않는다.

**테스트 (실패부터, `backend/tests/test_file_store.py`, `test_api_generate.py`)**

- `append_usage` 가 파일을 만들고 두 번 부르면 두 줄이며 각 줄이 JSON 으로 파싱된다. 존재하지 않는 프로젝트면 종전 규칙대로 예외.
- 구조안 생성 API 응답에 `usage` 가 있고 `calls=1`. 응답 뒤 `ai-usage.jsonl` 이 1줄이고 `kind="structure"`, `outcome="ok"`, `summary.calls=1`, `requested_model` 이 스텁의 `model` 속성(없으면 `None`).
- 장 생성(형식 재시도 포함)과 수동 축약도 각각 1줄씩 늘고 `chapter_id` 가 맞다.
- 프로바이더가 `ProviderCallFailed` 를 던지면 응답은 종전 **503** 그대로이고 파일에는 `outcome="failed", summary.failed_calls=1` 1줄이 남는다.
- **내용 누출 부재**: 파일 전체 문자열에 자료 문장, 요청의 `instructions`, 응답 `raw_text`, 슬롯 문장, 프롬프트 고정 문구(`build_structure_prompt` 의 첫 줄), 프로바이더 오류 문구가 없다.
- `append_usage` 가 예외를 던지도록 스텁 저장소를 만들면 생성 응답은 200 이다.
- OpenAPI 와 타입 재생성 뒤 `git diff --exit-code` 통과, 프런트 tsc 와 테스트 통과(목 갱신 뒤).

## 태스크 C4: 화면 표시

**변경 (`frontend/src/api/usage.ts` 신설, `frontend/src/screens/StructureScreen.tsx`, `frontend/src/editor/GeneratePanel.tsx`)**

- `usage.ts`: `formatUsage(usage: GenerationUsage): string` 순수 함수(가정 7 의 문구 규칙. 천 단위 구분은 `toLocaleString("ko-KR")`, 초는 소수 1자리, 비용은 소수 4자리까지에서 뒤 0 제거). `failed_calls > 0` 이면 "실패 1회 포함", `records` 에 `format_retry` 가 있으면 "형식 재시도 1회 포함", `condense` 가 있으면 "축약 1회 포함", `unmeasured_calls > 0` 이면 "측정되지 않은 호출 N회 제외", `token_source="usage"` 인 레코드가 있으면 토큰 앞에 "대략". `sumUsage(list: GenerationUsage[]): GenerationUsage` 는 가정 3 의 `None` 전파 규칙을 그대로 쓰고 `records` 를 이어붙인다.
- `StructureScreen`: 구조안 결과 아래(승인 버튼 위) 일반 문단 `<p className="usage">`. 승인 루프는 장별 결과를 `sumUsage` 로 더해 **루프 합계 한 줄**("장 생성 3회: ...")을 보이고, 실패한 장이 하나라도 있으면 가정 7 의 단서 문장을 덧붙인다.
- `GeneratePanel`: 결과 안내(축약, 재시도 문구) 옆에 같은 한 줄.

**테스트 (실패부터, `usage.test.ts`, `StructureScreen.test.tsx`, `GeneratePanel.test.tsx`)**

- `formatUsage`: 전부 있는 경우의 정확한 문자열, 토큰이 `null` 이면 "토큰 미확인", 비용 `null` 이면 "비용 미확인", `0` 비용은 "$0", 캐시 0 은 생략, 재시도와 축약과 실패 포함 문구, "대략" 과 "측정되지 않은 호출" 문구.
- `sumUsage`: 둘 다 값이면 합계, 하나가 `null` 이면 `null` 과 `missing` 합집합, `records` 이어붙임, `unmeasured_calls` 합.
- 화면: 구조안 생성 뒤 사용량 문단이 보이고, 장 생성 결과에 한 줄이 보이며, `null` 값이면 "미확인" 이 보인다. 승인 루프 뒤 합계 한 줄. 승인 루프에서 한 장이 503 으로 실패하면 합계 줄에 "포함되지 않았습니다" 단서가 보인다.

## 문서 정정 (마지막 커밋)

- 로드맵 이월표 "`ProviderResponse` 가 SDK 의 모델, 토큰, 처리 시간, 호출 수, 비용값을 버려..." 행을 처리 완료로. 새 행 3건: "프로젝트 누적 사용량 합계 API 와 화면"(5B 후보), "SDK `output_format` 폐기 예정(CLI v2.1.260 이 `output_config.format` 권고, SDK 0.2.145 에는 없음)"(SDK 업그레이드 시), "D2 관통 실측 항목: `usage` dict 키 이름, `model_usage` 채움 여부, 폴백 값이 누적인지 마지막 턴 값인지"(D2). 진행 상태에 5A C 항목.
- 설계서: 4절에 "4.4 AI 사용량 기록" 신설(기록 위치와 필드, 내용 없음 규칙, 없는 값 규칙, `calls` 와 `num_turns` 의 구분, 비용값의 의미). 2.6 의 5항 아래에 "로컬 기록 `ai-usage.jsonl` 은 사용량만 담고 문서 내용을 담지 않는다" 한 줄. **9.1 절 항목 6**("AI 호출 횟수, 모델, 토큰, 처리 시간, SDK 비용값을 내용과 분리해 기록")에 구현 완료 표기(적대 리뷰 정정: 종전 "10절 6항" 은 배포 유의점 절이라 무관했다).
- `CLAUDE.md` 관례에 "생성 결과 모델(`StructureResult`, `ChapterResult`)에 필드를 더하면 OpenAPI 와 프런트 타입을 재생성하고 프런트 테스트 목을 함께 갱신한다" 한 줄(B2 와 C3 에서 두 번 겪은 파급).

## 실행 순서

C1 → C2 → C3 → C4 → 문서 정정 → 묶음 최종 리뷰 → 반영 → push. C3 뒤에 OpenAPI 와 프런트 타입을 재생성해 C4 가 그 위에서 시작한다. 검증 명령은 B 와 같다(worktree 백엔드 테스트는 `PYTHONPATH` 필수).

실행 편차 (2026-09-05, 구현자 자진 보고와 독립 리뷰어 실측으로 확인):

- **재생성을 C3 가 아니라 C2 에서 했다.** `StructureResult` 와 `ChapterResult` 에 `usage` 필수 필드를 더하는 순간 `backend/tests/test_openapi.py` 가 `backend/openapi.json` 과 실제 스키마의 동기화를 강제하므로, C2 커밋(9401389)에서 재생성하지 않으면 백엔드 전체 테스트가 통과하지 않는다. 그래서 OpenAPI 와 프런트 타입 재생성, `client.ts` 재노출, `frontend/src/test/usage.ts` 의 `emptyUsage()` 와 결과 목 20곳 갱신을 C2 로 당겼고, C3(47323a7)는 `append_usage` 와 라우트 배선과 그 백엔드 테스트만 다뤘다(C3 의 재생성은 무변경). 이 파급은 B2 에 이어 두 번째라 `CLAUDE.md` 관례에 적었다.
- **다중 모델의 `cost_usd` 는 재합산이 아니라 `total_cost_usd` 패스스루다.** 가정 1 은 "토큰과 비용은 합산" 이라 적었으나 C1 구현은 토큰만 모델별로 합산하고 비용은 `ResultMessage.total_cost_usd` 를 그대로 옮긴다(SDK 값이 이미 세션 총합이라 재합산은 중복 계산 위험만 늘린다). C1 리뷰 F1 이 두 방식을 구분하지 못하는 테스트를 지적해 어긋나는 입력의 테스트를 추가했다(d77f04b).

## 적대 리뷰 반영 (2026-09-05)

세 관점 리뷰어(SDK 계약과 계측, 서비스 합산과 관문, 저장과 API 와 화면과 개인정보)가 병렬로 반박했고 셋 다 "수정 후 승인"(발견 25건: major 11, minor 10, nit 4). 24건 반영, 1건 기록만.

| 관점 | 반영한 것 |
|---|---|
| SDK 와 계측 | `is_error` 결과의 사용량을 예외에 실어 보냄(원가 근거가 가장 필요한 실패 유형을 버리고 있었다), `_consume` 이 결과 즉시 반환(결과 뒤 종료 지연이 타임아웃으로 결과를 잃던 기존 결함), `usage` 폴백이 마지막 턴 값일 위험을 `token_source` 표시와 D2 실측 항목으로, `terminal_reason` 필드 추가, 기존 동등 비교 테스트가 깨진다는 정정, `num_turns` 와 `calls` 의 축 구분, `output_format` 폐기 리스크를 이월표로 |
| 서비스와 관문 | `_provider` 비공개와 우회 방지 정적 테스트, `calls` 는 시도 전부이고 `len(records) == calls`, 수집기는 요청별 지역 변수(동시 요청 격리 테스트), 형식 게이트가 목적을 인자로 받음(수동 축약 재시도 테스트), 목 20곳 정정, 타입 정밀화(정수와 실수 분리), 비용 전부 `0.0` 테스트, `CallUsageRecord` 가 `CallUsage` 를 중첩 |
| 저장과 화면 | 503 정정, 설계서 절 번호 정정(9.1 항목 6), `client.ts` 타입 재노출, 호출 전 `ValueError` 의 콜백 범위, 승인 루프에서 실패한 장이 합계에서 빠지는 불일치를 화면 단서로, 비개발자 문구("참고 비용", "AI 도구가 계산한 값") |

기록만 남긴 것: CLI 는 모델별 `thinkingTokens` 를 보고할 수 있으나 설치된 SDK 의 `ModelUsage` 자료형에 그 키가 없다(`outputTokens` 에 이미 포함되어 합계에는 영향 없음). SDK 가 노출하면 `CallUsage` 에 선택 필드로 추가한다.

## 구현 리뷰 반영 (2026-09-05)

태스크마다 구현자와 독립 리뷰어를 분리했고, 리뷰어는 구현 직전 커밋에서 새 테스트가 실제로 실패하는지 재실증했다. 묶음 최종 리뷰는 세 관점(SDK 계약과 백엔드 계약은 설치된 SDK 소스 대조와 StubProvider 를 주입한 TestClient 재현 12종과 실제 서버의 헤더 관문, 프런트는 재현 테스트, 관문과 문서는 완료 관문 3문장 대조와 문서 정정 커밋의 사실 확인)을 병렬로 돌리고 major 는 반박자 3명씩 적대 검증했다. 실제 AI 호출은 한 번도 하지 않았다.

| 태스크 | 커밋 | 리뷰 판정 | 반영 |
|---|---|---|---|
| C1 프로바이더 계측 | 6911ccb | 수정 후 승인 (minor 2, nit 2, 정보 1) | d77f04b: 다중 모델 비용이 재합산이 아니라 `total_cost_usd` 패스스루임을 구분하는 테스트, 오류 문구의 숫자 부재 검증 일반화(영문 전체 금지는 "AI" 가 제품 용어라 적용하지 않음), `token_source` 지역 변수 타입 힌트, 헬퍼 시그니처 정렬. 비동기 생성기 정리가 GC 파이널라이저에 의존하는 점은 계획서가 D2 로 미룬 리스크의 재확인이라 조치하지 않음 |
| C2 서비스 합산 | 9401389 | 승인 (minor 4) | 응답 모델 `usage` 필수 필드가 OpenAPI 동기화 테스트에 걸려 재생성과 결과 목 20곳 갱신을 C3 에서 이 태스크로 당김. minor 4건(summary 두 번 계산, condense 템플릿 불일치와 format_error outcome 의 전용 테스트 부재, 전부 미측정 시 `missing` 빈 목록)은 최종 리뷰로 넘김 |
| C3 로컬 기록과 API | 47323a7 | 승인 (nit 2, 관찰 3) | 현행 유지: `record` 타입 힌트 부재는 파일 관례와 일치, on_usage 예외의 이중 방어는 의도, append 전용 기록은 계획서가 명시한 한계 |
| C4 화면 표시 | 3c40d5d | 수정 후 승인 (major 2, minor 3, nit 3) | d965996: "다시 생성" 시 이전 승인 루프 사용량 잔존, 전부 실패 시 실패 단서 소실, "대략" 표시를 입력과 출력 양쪽에, GeneratePanel 의 형식 오류 시 사용량 은닉, 주석과 테스트 제목 정정. 반영하지 않음: 입력과 출력 토큰 비대칭(가정 1 상 도달 불가), 아주 작은 비용의 "$0" 표시(저우선순위) |
| 묶음 최종 | 75cd3c8..4a57111 | backend 승인 (minor 2, nit 1), frontend 수정 후 승인 (major 1, minor 2, nit 2), gate-docs 수정 후 승인 (major 1, minor 5, nit 2). major 는 두 관점이 같은 결함을 보고한 1건이며 반박자 6명 전원이 실제 결함으로 확정 | e3cb63f: 구조안 생성이 format_error 로 끝나도 사용량 문단을 표시(GeneratePanel 의 F5 반영을 StructureScreen 최초 생성 경로에 이식. 백엔드는 형식 오류에도 `usage` 를 항상 채우는데 화면이 버리고 있었다), 실패 문구를 "이 중 실패 N회" 로 결합해 형식 재시도 실패가 두 사건처럼 읽히지 않게, `collector.summary()` 를 작업당 한 번만 계산, 테스트 3건 추가(condense 템플릿 불일치 시 on_usage 미호출, format_error outcome, 전부 미측정 시 `missing` 빈 목록과 `unmeasured_calls` 고정). 현행 유지: `usage` dict 폴백의 캐스팅 비대칭(pydantic 강제 변환, D2 실측 전), 승인 루프 진행 라벨의 "실패" 세분화(범위 밖, 이월표), `.usage` CSS 부재(기존 관례), 아주 작은 비용의 "$0"(이월표). D2 실측: SDK 반환 형태 3항목과 `max_turns=2` 구조에서 폴백 값이 정리 턴만 반영할 위험(이월표 기존 행). 문서 정정 2건(설계서 4.4 필드 설명, 이 절 C3 항목의 상호 참조)은 이 문서 커밋에서 처리 |

실행 중 발견: 계획서 적대 리뷰 1차 실행은 세션 한도로 리뷰어 3명이 전멸해 재실행이 완주했고, 태스크 워크플로와 최종 리뷰는 한 번에 완주했다. 태스크 리뷰어가 구현자의 계획서 테스트 목록 밖 시나리오("다시 생성" 뒤 잔존, 전부 실패)를 잡았고, 최종 리뷰는 같은 결함 유형이 자매 화면에 남은 것을 잡았다. 최종: 백엔드 585, 프런트 220.

## 이 계획이 틀렸을 가능성

- `usage` dict 의 키 이름과 `model_usage` 의 실제 채움 여부, 폴백 값의 의미는 실호출 없이 확인하지 못했다(가정 1). `model_usage` 가 비고 폴백이 마지막 턴 값이면 화면의 "대략" 표시가 그 한계를 알리지만 값 자체는 크게 작을 수 있다. D2 관통 1회 호출에서 확인하고, 다르면 `build_call_usage` 한 곳만 고친다.
- 구독 프로바이더의 `total_cost_usd` 는 CLI 가 가격표로 산정한 값이지 청구액이 아니다. 화면 문구로 구분하지만 사용자가 "비용" 이라는 단어만 보고 오해할 수 있다. 5B 파일럿에서 문구를 재점검한다.
- `duration_ms` 에는 CLI 프로세스 기동이 포함된다. 화면의 "처리 8.2초" 가 API 시간보다 크게 보인다. `duration_api_ms` 도 기록하므로 필요하면 표시를 바꾼다.
- 필수 필드 추가(가정 6)는 목 20곳을 한 번에 건드린다. 선택 필드로 두면 갱신은 적지만 합산이 빠진 경로를 타입이 잡지 못한다. 필수를 택했다.
- `ai-usage.jsonl` 은 append 라 원자적 교체가 아니다. 프로세스가 줄 중간에 죽으면 마지막 줄이 깨질 수 있다. 이 묶음에는 읽기 경로가 없어 영향이 없고, 누적 합계를 붙일 때 "깨진 마지막 줄은 건너뛴다" 규칙을 넣는다.
- 승인 루프의 합계(C4)는 화면이 더한다. 서버가 작업 단위로 기록하므로 정본은 파일이고 화면 합계는 표시용이다. 실패한 장은 결과가 없어 합계에서 빠지며 화면이 그 사실을 단서로 알린다.
- `_consume` 이 결과 메시지에서 즉시 반환하면 SDK 의 비동기 생성기가 조기 종료된다. SDK 의 `query()` 는 생성기 정리 시 CLI 연결을 닫도록 되어 있어 안전하다고 보지만, 조기 종료가 CLI 프로세스를 남기는지는 D2 관통에서 프로세스 목록으로 확인한다. (2026-09-06 관통: 실호출 뒤 서버의 자식 프로세스 0, CLI 잔존 없음.)
- 결과 없이 끝난 실패(ⓑ 유형)의 토큰은 어디에도 없다. 구독 사용량에는 차감됐을 수 있으므로 "측정되지 않은 호출" 을 화면에 드러내는 것까지가 이 묶음의 정직한 한계다.
