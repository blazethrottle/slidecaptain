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

_LOG = logging.getLogger("slidecaptain.pipeline.subscription")

# CLI 기본 모델(opus 계열)은 사소한 호출에도 사용량이 크다 (2026-08-28 스파이크 실측).
# 별칭을 써서 세부 버전 교체에 흔들리지 않게 한다.
DEFAULT_MODEL = "sonnet"


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
        usage_dict = result.usage
        model_usage_raw = result.model_usage

        usage_keys = sorted(usage_dict.keys()) if usage_dict else []
        model_usage_keys = sorted(model_usage_raw.keys()) if model_usage_raw else []

        if usage_dict:
            usage_in = usage_dict.get("input_tokens")
            usage_out = usage_dict.get("output_tokens")
            usage_cache_read = usage_dict.get("cache_read_input_tokens")
            usage_cache_create = usage_dict.get("cache_creation_input_tokens")
        else:
            usage_in = usage_out = usage_cache_read = usage_cache_create = None

        # model_usage 의 값이 dict 가 아닌 이상값이어도(실측되지 않은 SDK 버전 등) 예외 없이
        # 넘어간다: 유효한 항목이 하나도 없으면 0이 아니라 None(미확인)으로 남긴다.
        valid_entries = (
            [mu for mu in model_usage_raw.values() if isinstance(mu, dict)] if model_usage_raw else []
        )
        if valid_entries:
            model_usage_in = sum(int(mu.get("inputTokens", 0)) for mu in valid_entries)
            model_usage_out = sum(int(mu.get("outputTokens", 0)) for mu in valid_entries)
            model_usage_cache_read = sum(int(mu.get("cacheReadInputTokens", 0)) for mu in valid_entries)
            model_usage_cache_create = sum(
                int(mu.get("cacheCreationInputTokens", 0)) for mu in valid_entries
            )
        else:
            model_usage_in = model_usage_out = model_usage_cache_read = model_usage_cache_create = None

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
    그대로 옮긴다(없는 값을 0으로 바꾸지 않는다).
    """
    _log_raw_usage_line(result)

    # D2-5 리뷰 반영: SDK 파서는 CLI 의 modelUsage 를 변환 없이 옮기므로 값이 dict 가 아닌 항목이 올 수
    # 있다. 그런 항목은 없는 것으로 보고(합산과 모델 추정에서 제외) 유효 항목이 없으면 usage dict 로 폴백한다.
    model_usage = {
        key: value for key, value in (result.model_usage or {}).items() if isinstance(value, dict)
    }
    usage_dict = result.usage if isinstance(result.usage, dict) else {}  # model_usage 항목 필터와 대칭

    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_creation_tokens: int | None = None
    token_source: Literal["model_usage", "usage", "none"]

    if model_usage:
        token_source = "model_usage"
        input_tokens = sum(int(mu.get("inputTokens", 0)) for mu in model_usage.values())
        output_tokens = sum(int(mu.get("outputTokens", 0)) for mu in model_usage.values())
        cache_read_tokens = sum(int(mu.get("cacheReadInputTokens", 0)) for mu in model_usage.values())
        cache_creation_tokens = sum(
            int(mu.get("cacheCreationInputTokens", 0)) for mu in model_usage.values()
        )
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
    elif len(model_usage) == 1:
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
        options = ClaudeAgentOptions(
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
                "잠시 후 다시 시도해 주세요."
            ) from e
        except CLINotFoundError as e:
            raise ProviderNotAvailable(
                "Claude Code를 찾지 못했습니다. 이 앱의 AI 생성에는 Claude Code 설치와 "
                "구독 로그인이 필요합니다."
            ) from e
        except (CLIConnectionError, ProcessError, ClaudeSDKError) as e:
            _LOG.warning("AI 호출 실패: %s", e)
            raise ProviderCallFailed(
                "AI 호출에 실패했습니다. Claude Code 로그인 상태와 구독 사용 한도를 "
                "확인한 뒤 잠시 후 다시 시도해 주세요."
            ) from e
        if result is None:
            _LOG.warning("AI 호출 비정상 종료: 응답 없음")
            raise ProviderCallFailed(
                "AI 호출이 정상적으로 끝나지 않았습니다. 잠시 후 다시 시도해 주세요."
            )

        usage = build_call_usage(result, assistant_model)

        if result.is_error:
            if result.api_error_status is not None:
                _LOG.warning("AI 호출 오류 상태 코드: %s", result.api_error_status)
            _LOG.warning("AI 호출 비정상 종료: %s", result.errors)
            raise ProviderCallFailed(
                "AI 호출이 정상적으로 끝나지 않았습니다. 잠시 후 다시 시도해 주세요.",
                usage=usage,
            )
        return ProviderResponse(
            structured=result.structured_output, raw_text=result.result or "", usage=usage
        )
