"""본인 구독 프로바이더 (설계서 2.4의 1단계): Agent SDK로 로그인된 Claude Code를 구동한다.

실증(2026-08-28, 로드맵 미확인 리스크 해소): API 키 없이 호출이 성공하며
이 PC의 Claude Code 구독 로그인이 자동으로 쓰인다. output_format(json_schema)
지정 시 ResultMessage.structured_output으로 파싱 완료된 JSON이 돌아온다.

오류 원문(영문 stderr 등)은 로그로만 남기고 사용자 문구에는 넣지 않는다 (설계 결정 14).
"""

import asyncio
import logging
from typing import Literal

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKError,
    CLIConnectionError,
    CLINotFoundError,
    ProcessError,
    ResultMessage,
    query,
)

from slidecaptain.pipeline.provider import (
    CallUsage,
    ProviderCallFailed,
    ProviderNotAvailable,
    ProviderResponse,
)
from slidecaptain.pipeline.auth_status import resolve_cli_path

_LOG = logging.getLogger("slidecaptain.pipeline.subscription")

# CLI 기본 모델(opus 계열)은 사소한 호출에도 사용량이 크다 (2026-08-28 스파이크 실측).
# 별칭을 써서 세부 버전 교체에 흔들리지 않게 한다.
DEFAULT_MODEL = "sonnet"


def _sum_model_tokens(model_usage: dict, field: str) -> int | None:
    """전 모델이 명시한 음이 아닌 정수만 합산한다. 부분 합계는 반환하지 않는다."""
    if not model_usage:
        return None
    total = 0
    for entry in model_usage.values():
        if not isinstance(entry, dict):
            return None
        value = entry.get(field)
        # bool은 int의 하위 타입이다. 문자열/실수의 강제 변환도 측정값을 만들므로 금지한다.
        if type(value) is not int or value < 0:
            return None
        total += value
    return total


def _log_raw_usage_line(result: ResultMessage) -> None:
    """`ResultMessage` 의 `usage`/`model_usage` 원시 형태를 INFO 로그 한 줄로 남긴다 (태스크 D2-5).

    C 계획서 가정 1 의 실측 필요 3항목(① `usage` dict 키가 snake_case 인지 ② `model_usage`
    가 실제로 채워지는지 ③ `model_usage` 없이 `usage` 로 폴백한 값이 세션 누적인지 마지막 턴
    값인지)을 실호출 1회로 판정하려면, 원시 키와 두 출처의 합계가 같은 호출의 로그에 함께
    보여야 한다. 그래서 `build_call_usage` 의 if/elif 분기(1순위 출처만 채택)와 무관하게
    `usage` dict 와 `model_usage` 를 각각 독립적으로 합산한다(분기 지역 변수를 재사용하면
    한쪽이 있을 때 다른 쪽 합계가 항상 `None` 이 되어 이 로그의 존재 이유가 사라진다).
    프롬프트와 응답과 오류 문구는 참조하지 않는다. 로그 조립 자체의 실패가 사용량 계산이라는
    본 동작에 영향을 주면 안 되므로 예외를 삼킨다.
    """
    try:
        usage_dict = result.usage if isinstance(result.usage, dict) else {}
        model_usage_raw = result.model_usage if isinstance(result.model_usage, dict) else {}

        usage_keys = sorted(usage_dict.keys()) if usage_dict else []
        model_usage_keys = sorted(model_usage_raw.keys()) if model_usage_raw else []

        if usage_dict:
            usage_in = usage_dict.get("input_tokens")
            usage_out = usage_dict.get("output_tokens")
            usage_cache_read = usage_dict.get("cache_read_input_tokens")
            usage_cache_create = usage_dict.get("cache_creation_input_tokens")
        else:
            usage_in = usage_out = usage_cache_read = usage_cache_create = None

        # 진단 로그도 앱 값과 같은 결측 규칙을 따른다. 정상 모델만 더하면 과소 집계된다.
        model_usage_in = _sum_model_tokens(model_usage_raw, "inputTokens")
        model_usage_out = _sum_model_tokens(model_usage_raw, "outputTokens")
        model_usage_cache_read = _sum_model_tokens(model_usage_raw, "cacheReadInputTokens")
        model_usage_cache_create = _sum_model_tokens(model_usage_raw, "cacheCreationInputTokens")

        cost_present = "있음" if result.total_cost_usd is not None else "없음"

        _LOG.info(
            "SDK 사용량 원시 형태: "
            f"usage_keys={usage_keys} model_usage_keys={model_usage_keys} "
            f"usage_in={usage_in} usage_out={usage_out} "
            f"usage_cache_read={usage_cache_read} usage_cache_create={usage_cache_create} "
            f"model_usage_in={model_usage_in} model_usage_out={model_usage_out} "
            f"model_usage_cache_read={model_usage_cache_read} "
            f"model_usage_cache_create={model_usage_cache_create} "
            f"num_turns={result.num_turns} total_cost_usd={cost_present}"
        )
    except Exception:  # 로그 조립 실패가 사용량 계산에 영향을 주지 않는다
        _LOG.debug("SDK 사용량 원시 로그 조립 실패", exc_info=True)


def build_call_usage(result: ResultMessage, assistant_model: str | None) -> CallUsage:
    """`ResultMessage` 하나에서 `CallUsage` 를 만드는 순수 함수 (단계 5A 묶음 C 가정 1).

    토큰의 유일한 출처는 `model_usage`(모델별 dict, 2개 이상이면 합산)다. `usage` dict 만 있으면
    `token_source="usage"` 로 표시하되 토큰은 채우지 않는다(D2 관통 실측: 마지막 턴 값이라 신뢰 불가),
    둘 다 없으면 `token_source="none"`. 어느 경우든 토큰이 없으면 화면은 "토큰 미확인" 을 쓴다. 모델 문자열은 스트림에서
    처음 본 `AssistantMessage.model` 을 우선하고, 없으면 `model_usage` 의 키가
    1개일 때만 그것을 쓴다. 비용은 SDK 가 이미 합산해 주는 `total_cost_usd` 를
    그대로 옮긴다(없는 값을 0으로 바꾸지 않는다). 토큰은 모델마다 해당 필드가
    유효해야 합산하며, 누락되거나 잘못된 필드는 None으로 남긴다.
    """
    _log_raw_usage_line(result)

    # SDK 파서는 CLI 값을 그대로 옮긴다. 잘못된 모델 항목을 버리면 부분 합계가 되므로
    # 보존하고 필드별 합산에서 미확인으로 처리한다 (2026-09-28 결측 계약 정정).
    model_usage = result.model_usage if isinstance(result.model_usage, dict) else {}
    has_model_entry = any(isinstance(entry, dict) for entry in model_usage.values())
    usage_dict = result.usage if isinstance(result.usage, dict) else {}

    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_creation_tokens: int | None = None
    token_source: Literal["model_usage", "usage", "none"]

    if has_model_entry:
        token_source = "model_usage"
        input_tokens = _sum_model_tokens(model_usage, "inputTokens")
        output_tokens = _sum_model_tokens(model_usage, "outputTokens")
        cache_read_tokens = _sum_model_tokens(model_usage, "cacheReadInputTokens")
        cache_creation_tokens = _sum_model_tokens(model_usage, "cacheCreationInputTokens")
    elif usage_dict:
        # D2 관통 실측(2026-09-06, 실호출 1회): usage dict 는 세션 누적이 아니라 마지막 턴의 값이다
        # (input_tokens 2 대 model_usage 합 2,239). 그 값을 "대략" 으로 보여주면 천 배 작은 숫자가 되므로
        # 출처만 usage 로 표시하고 토큰 4종은 채우지 않는다(가정 3: 없는 값은 만들지 않는다). 원시 값은
        # _log_raw_usage_line 의 로그로 진단할 수 있다.
        token_source = "usage"
    else:
        token_source = "none"

    if assistant_model:
        model = assistant_model
    elif has_model_entry and len(model_usage) == 1:
        model = next(iter(model_usage))
    else:
        model = None

    return CallUsage(
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_creation_tokens=cache_creation_tokens,
        duration_ms=result.duration_ms,
        duration_api_ms=result.duration_api_ms,
        num_turns=result.num_turns,
        cost_usd=result.total_cost_usd,  # SDK가 이미 합산한 값을 그대로 옮긴다(재합산 아님)
        stop_reason=result.stop_reason,
        terminal_reason=result.terminal_reason,
        api_error_status=result.api_error_status,
        token_source=token_source,
    )


class SubscriptionProvider:
    def __init__(self, model: str | None = None, timeout_s: float = 300.0) -> None:
        self.model = model or DEFAULT_MODEL
        self.timeout_s = timeout_s

    async def complete(self, prompt: str, schema: dict) -> ProviderResponse:
        cli = resolve_cli_path()
        if cli is None:
            raise ProviderNotAvailable("Claude Code를 찾지 못했습니다. 네이티브 CLI 설치와 경로 설정을 확인해 주세요.", code="provider_missing")
        options = ClaudeAgentOptions(
            cli_path=cli,
            tools=[],  # 도구 없이 순수 생성만
            setting_sources=[],  # 사용자 설정 격리: CLAUDE.md와 스킬이 생성에 개입하지 못하게
            # 구조화 출력 경로는 생성 1턴 + 구조화 출력 정리 1턴을 쓴다: 2가 실측 최소값이다
            # (2026-08-28 스모크 격리 진단. 트리비얼 프롬프트에서만 통과하던 max_turns=1로는
            # 실제 생성 프롬프트가 "Reached maximum number of turns (1)"로 거부됐다).
            # 스키마 불일치 시 SDK 자체의 재프롬프트 여지는 없다: 그 경우는 앱의 형식 게이트가 담당한다.
            max_turns=2,
            model=self.model,
            output_format={"type": "json_schema", "schema": schema},
        )

        assistant_model: str | None = None

        async def _consume() -> ResultMessage | None:
            nonlocal assistant_model
            found: ResultMessage | None = None
            async for message in query(prompt=prompt, options=options):
                if assistant_model is None and isinstance(message, AssistantMessage):
                    assistant_model = message.model
                if isinstance(message, ResultMessage):
                    found = message
                    # 결과를 본 즉시 반환한다: 스트림이 그 뒤 닫히지 않고 멈춰도
                    # 이미 받은 결과를 타임아웃으로 잃지 않는다 (적대 리뷰 반영).
                    break
            return found

        result: ResultMessage | None = None
        try:
            result = await asyncio.wait_for(_consume(), timeout=self.timeout_s)
        except TimeoutError as e:
            _LOG.warning("AI 호출 타임아웃: %.0f초", self.timeout_s)
            raise ProviderCallFailed(
                f"AI 응답이 너무 오래 걸려 중단했습니다({self.timeout_s:.0f}초 한도). "
                "잠시 후 다시 시도해 주세요.", code="provider_timeout",
            ) from e
        except CLINotFoundError as e:
            raise ProviderNotAvailable(
                "Claude Code를 찾지 못했습니다. 이 앱의 AI 생성에는 Claude Code 설치와 "
                "구독 로그인이 필요합니다.", code="provider_missing",
            ) from e
        except (CLIConnectionError, ProcessError, ClaudeSDKError) as e:
            _LOG.warning("AI 호출 실패: %s", e)
            # 미로그인과 한도 초과가 이 한 자리로 온다. 서버가 가를 수 없으므로 넓은 코드다 (계획 4.3)
            raise ProviderCallFailed(
                "AI 호출에 실패했습니다. Claude Code 로그인 상태와 구독 사용 한도를 "
                "확인한 뒤 잠시 후 다시 시도해 주세요.", code="provider_call_failed",
            ) from e
        if result is None:
            _LOG.warning("AI 호출 비정상 종료: 응답 없음")
            raise ProviderCallFailed(
                "AI 호출이 정상적으로 끝나지 않았습니다. 잠시 후 다시 시도해 주세요.", code="provider_disconnected",
            )

        usage = build_call_usage(result, assistant_model)

        if result.is_error:
            if result.api_error_status is not None:
                _LOG.warning("AI 호출 오류 상태 코드: %s", result.api_error_status)
            _LOG.warning("AI 호출 비정상 종료: %s", result.errors)
            # 사용 한도 초과는 HTTP 표준 상태 429(RFC 6585)로 온 경우만 가른다. 구독 한도가 실제로 이 상태로
            # 오는지는 실제 호출 없이 확인하지 못했다(D3a-4 구현 기록). 그 밖은 넓은 코드다
            raise ProviderCallFailed(
                "AI 호출이 정상적으로 끝나지 않았습니다. 잠시 후 다시 시도해 주세요.",
                usage=usage, code="provider_limit" if result.api_error_status == 429 else "provider_call_failed",
            )
        return ProviderResponse(
            structured=result.structured_output, raw_text=result.result or "", usage=usage
        )
