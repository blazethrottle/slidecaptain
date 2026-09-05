import asyncio
import re

import pytest

from slidecaptain.pipeline.provider import (
    CallUsage,
    ProviderCallFailed,
    ProviderNotAvailable,
    ProviderResponse,
)
import slidecaptain.pipeline.subscription as sub
from slidecaptain.pipeline.subscription import DEFAULT_MODEL, SubscriptionProvider, build_call_usage


def _fake_query(
    result_message=None,
    error: Exception | None = None,
    captured: dict | None = None,
    assistant_model: str | None = None,
):
    async def fake(prompt, options):
        if captured is not None:
            captured["prompt"] = prompt
            captured["options"] = options
        if error is not None:
            raise error
        # 실제 SDK 스트림은 ResultMessage 앞에 System, Assistant 등 다른 메시지를 먼저 낸다.
        # 더미를 선행시켜 isinstance 필터링을 테스트로 고정한다 (2026-08-28 적대 리뷰 반영)
        yield object()
        if assistant_model is not None:
            from claude_agent_sdk import AssistantMessage

            yield AssistantMessage(content=[], model=assistant_model)
        yield result_message

    return fake


def _result(is_error=False, structured=None, text="원문", errors=None, **extra):
    from claude_agent_sdk import ResultMessage

    fields = dict(
        subtype="success", duration_ms=1, duration_api_ms=1, is_error=is_error,
        num_turns=1, session_id="s", result=text, structured_output=structured, errors=errors,
    )
    fields.update(extra)
    return ResultMessage(**fields)


def test_complete_returns_structured_and_raw(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(
        sub, "query", _fake_query(_result(structured={"answer": 2}), captured=captured)
    )
    provider = SubscriptionProvider()
    resp = asyncio.run(provider.complete("질문", {"type": "object"}))
    assert resp.structured == {"answer": 2}
    assert resp.raw_text == "원문"
    assert resp.usage is not None
    assert resp.usage.token_source == "none"  # usage/model_usage 둘 다 없는 기본 _result
    options = captured["options"]
    assert options.model == DEFAULT_MODEL == "sonnet"
    assert options.tools == []
    assert options.setting_sources == []
    assert options.max_turns == 2
    assert options.output_format == {"type": "json_schema", "schema": {"type": "object"}}


def test_model_override():
    assert SubscriptionProvider(model="opus").model == "opus"
    assert SubscriptionProvider().model == "sonnet"


def test_cli_not_found_maps_to_not_available(monkeypatch):
    from claude_agent_sdk import CLINotFoundError

    monkeypatch.setattr(sub, "query", _fake_query(error=CLINotFoundError("claude not found")))
    with pytest.raises(ProviderNotAvailable) as exc_info:
        asyncio.run(SubscriptionProvider().complete("q", {}))
    assert "Claude Code" in str(exc_info.value)
    assert exc_info.value.usage is None


def test_process_error_maps_to_call_failed_without_raw_detail(monkeypatch):
    from claude_agent_sdk import ProcessError

    monkeypatch.setattr(
        sub, "query", _fake_query(error=ProcessError("raw stderr blob", exit_code=2))
    )
    with pytest.raises(ProviderCallFailed) as exc_info:
        asyncio.run(SubscriptionProvider().complete("q", {}))
    assert "로그인" in str(exc_info.value)
    # SDK 예외 원문은 사용자 문구에 넣지 않는다 (설계 결정 14)
    assert "raw stderr blob" not in str(exc_info.value)
    assert exc_info.value.usage is None


def test_cli_connection_error_maps_to_call_failed(monkeypatch):
    from claude_agent_sdk import CLIConnectionError

    monkeypatch.setattr(sub, "query", _fake_query(error=CLIConnectionError("no conn")))
    with pytest.raises(ProviderCallFailed) as exc_info:
        asyncio.run(SubscriptionProvider().complete("q", {}))
    assert exc_info.value.usage is None


def test_error_result_maps_to_call_failed(monkeypatch):
    monkeypatch.setattr(
        sub, "query", _fake_query(_result(is_error=True, errors=["rate limited"]))
    )
    with pytest.raises(ProviderCallFailed) as exc_info:
        asyncio.run(SubscriptionProvider().complete("q", {}))
    assert "rate limited" not in str(exc_info.value)


def test_error_result_with_usage_attaches_usage_to_exception(monkeypatch):
    result = _result(
        is_error=True,
        errors=["rate limited"],
        api_error_status=529,
        usage={
            "input_tokens": 100,
            "output_tokens": 50,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        },
        total_cost_usd=0.004,
    )
    monkeypatch.setattr(sub, "query", _fake_query(result))
    with pytest.raises(ProviderCallFailed) as exc_info:
        asyncio.run(SubscriptionProvider().complete("q", {}))
    usage = exc_info.value.usage
    assert usage is not None
    assert usage.input_tokens == 100
    assert usage.output_tokens == 50
    assert usage.cost_usd == 0.004
    assert usage.api_error_status == 529
    assert usage.token_source == "usage"
    msg = str(exc_info.value)
    assert "rate limited" not in msg
    # 특정 문자열("529") 대신 숫자 전체 부재를 일반화해서 확인한다: 상태 코드가 어떤
    # 값이든 새면 걸린다 (발견 C1-F2). 영문 전체는 블록하지 않는다: "AI"는 이 모듈의
    # 모든 사용자 문구에 쓰이는 의도된 제품 용어이며(subscription.py의 다른 문구들도
    # 전부 "AI 호출"로 시작), 영문 전체 금지는 실제 설계와 맞지 않는 과잉 일반화다.
    assert not re.search(r"\d", msg)


def test_timeout_maps_to_korean_error(monkeypatch):
    async def slow_query(prompt, options):
        await asyncio.sleep(0.2)
        yield object()  # 타임아웃이 먼저 걸려 도달하지 않는다

    monkeypatch.setattr(sub, "query", slow_query)
    provider = SubscriptionProvider(timeout_s=0.05)
    with pytest.raises(ProviderCallFailed) as exc_info:
        asyncio.run(provider.complete("프롬프트", {"type": "object"}))
    assert "오래 걸려" in str(exc_info.value)
    assert exc_info.value.usage is None


def test_returns_immediately_after_result_message_even_if_stream_stalls(monkeypatch):
    """결과 메시지를 본 즉시 반환해야 한다. 스트림이 그 뒤 멈춰도 타임아웃까지 기다리지 않는다."""

    async def stalling_query(prompt, options):
        yield _result(structured={"answer": 1})
        await asyncio.sleep(3600)
        yield object()  # 도달하면 안 된다

    monkeypatch.setattr(sub, "query", stalling_query)
    provider = SubscriptionProvider(timeout_s=0.2)
    resp = asyncio.run(provider.complete("q", {"type": "object"}))
    assert resp.structured == {"answer": 1}


# --- build_call_usage 단위 테스트 (가정 1의 출처 우선순위, token_source, 다중 모델 합산) ---


def test_build_call_usage_model_usage_source():
    result = _result(
        model_usage={
            "claude-sonnet-4-5-20250929": {
                "inputTokens": 12345,
                "outputTokens": 1234,
                "cacheReadInputTokens": 100,
                "cacheCreationInputTokens": 0,
                "webSearchRequests": 0,
                "costUSD": 0.0123,
                "contextWindow": 200000,
                "maxOutputTokens": 8192,
            }
        },
        total_cost_usd=0.0123,
        duration_ms=8200,
        duration_api_ms=7900,
        num_turns=2,
        terminal_reason="completed",
    )
    usage = build_call_usage(result, assistant_model=None)
    assert usage.token_source == "model_usage"
    assert usage.input_tokens == 12345
    assert usage.output_tokens == 1234
    assert usage.cache_read_tokens == 100
    assert usage.cache_creation_tokens == 0
    assert usage.cost_usd == 0.0123
    assert usage.duration_ms == 8200
    assert usage.duration_api_ms == 7900
    assert usage.num_turns == 2
    assert usage.terminal_reason == "completed"
    assert usage.model == "claude-sonnet-4-5-20250929"  # model_usage 키가 1개뿐


def test_build_call_usage_falls_back_to_usage_dict():
    result = _result(
        usage={
            "input_tokens": 10,
            "output_tokens": 5,
            "cache_read_input_tokens": 3,
            "cache_creation_input_tokens": 0,
        }
    )
    usage = build_call_usage(result, assistant_model=None)
    assert usage.token_source == "usage"
    assert usage.input_tokens == 10
    assert usage.output_tokens == 5
    assert usage.cache_read_tokens == 3
    assert usage.cache_creation_tokens == 0


def test_build_call_usage_no_source_leaves_tokens_none_but_keeps_timing():
    result = _result(duration_ms=500, duration_api_ms=400, num_turns=1)
    usage = build_call_usage(result, assistant_model=None)
    assert usage.token_source == "none"
    assert usage.input_tokens is None
    assert usage.output_tokens is None
    assert usage.cache_read_tokens is None
    assert usage.cache_creation_tokens is None
    assert usage.duration_ms == 500
    assert usage.duration_api_ms == 400
    assert usage.num_turns == 1


def test_build_call_usage_multi_model_sums_tokens_and_cost():
    result = _result(
        model_usage={
            "claude-sonnet-4-5-20250929": {
                "inputTokens": 1000,
                "outputTokens": 100,
                "cacheReadInputTokens": 0,
                "cacheCreationInputTokens": 0,
                "webSearchRequests": 0,
                "costUSD": 0.01,
                "contextWindow": 200000,
                "maxOutputTokens": 8192,
            },
            "claude-sonnet-4-5-20250929-cleanup": {
                "inputTokens": 200,
                "outputTokens": 20,
                "cacheReadInputTokens": 0,
                "cacheCreationInputTokens": 0,
                "webSearchRequests": 0,
                "costUSD": 0.002,
                "contextWindow": 200000,
                "maxOutputTokens": 8192,
            },
        },
        total_cost_usd=0.012,  # 개별 costUSD 합(0.01+0.002)과 값이 같지만, 이는 total_cost_usd
        # 패스스루의 결과이지 이 함수가 costUSD를 재합산한 결과가 아니다 (아래 테스트로 구분)
    )
    usage = build_call_usage(result, assistant_model="claude-sonnet-4-5-20250929")
    assert usage.token_source == "model_usage"
    assert usage.input_tokens == 1200
    assert usage.output_tokens == 120
    assert usage.cost_usd == 0.012
    assert usage.model == "claude-sonnet-4-5-20250929"  # AssistantMessage.model 우선


def test_build_call_usage_cost_is_total_cost_usd_passthrough_not_recomputed_sum():
    """cost_usd 는 개별 model_usage 의 costUSD 를 재합산한 값이 아니라 SDK 의
    total_cost_usd 를 그대로 옮긴 값이다. 위 테스트만으로는 "합산"과 "패스스루"를
    구분할 수 없어(둘이 우연히 같은 값을 내므로), 두 값을 의도적으로 어긋나게 준다
    (발견 C1-F1)."""
    result = _result(
        model_usage={
            "claude-sonnet-4-5-20250929": {
                "inputTokens": 1000,
                "outputTokens": 100,
                "cacheReadInputTokens": 0,
                "cacheCreationInputTokens": 0,
                "webSearchRequests": 0,
                "costUSD": 0.01,
                "contextWindow": 200000,
                "maxOutputTokens": 8192,
            },
            "claude-sonnet-4-5-20250929-cleanup": {
                "inputTokens": 200,
                "outputTokens": 20,
                "cacheReadInputTokens": 0,
                "cacheCreationInputTokens": 0,
                "webSearchRequests": 0,
                "costUSD": 0.002,
                "contextWindow": 200000,
                "maxOutputTokens": 8192,
            },
        },
        total_cost_usd=0.02,  # 개별 costUSD 합(0.012)과 일부러 다르게 둔다
    )
    usage = build_call_usage(result, assistant_model=None)
    assert usage.cost_usd == 0.02  # 합산값(0.012)이 아니라 total_cost_usd 그대로


def test_build_call_usage_model_priority_assistant_over_model_usage_key():
    result = _result(model_usage={"m1": {
        "inputTokens": 1, "outputTokens": 1, "cacheReadInputTokens": 0,
        "cacheCreationInputTokens": 0, "webSearchRequests": 0, "costUSD": 0.0,
        "contextWindow": 1, "maxOutputTokens": 1,
    }})
    with_assistant = build_call_usage(result, assistant_model="claude-sonnet-4-5-20250929")
    assert with_assistant.model == "claude-sonnet-4-5-20250929"
    without_assistant = build_call_usage(result, assistant_model=None)
    assert without_assistant.model == "m1"  # model_usage 키가 1개뿐이라 그것을 쓴다


def test_build_call_usage_no_model_when_no_source():
    result = _result()
    usage = build_call_usage(result, assistant_model=None)
    assert usage.model is None


def test_build_call_usage_cost_none_stays_none_not_zero():
    result = _result(total_cost_usd=None)
    usage = build_call_usage(result, assistant_model=None)
    assert usage.cost_usd is None


# --- build_call_usage 의 SDK 원시 사용량 로그 (태스크 D2-5) ---


def test_build_call_usage_logs_raw_usage_with_both_sources(caplog):
    caplog.set_level("INFO", logger="slidecaptain.pipeline.subscription")
    result = _result(
        text="원문 응답 조각",
        usage={
            "input_tokens": 10,
            "output_tokens": 5,
            "cache_read_input_tokens": 3,
            "cache_creation_input_tokens": 1,
        },
        model_usage={
            "claude-sonnet-4-5-20250929": {
                "inputTokens": 12345,
                "outputTokens": 1234,
                "cacheReadInputTokens": 100,
                "cacheCreationInputTokens": 7,
                "webSearchRequests": 0,
                "costUSD": 0.0123,
                "contextWindow": 200000,
                "maxOutputTokens": 8192,
            }
        },
        total_cost_usd=0.0123,
        num_turns=2,
    )

    build_call_usage(result, assistant_model=None)

    records = [r for r in caplog.records if r.name == "slidecaptain.pipeline.subscription"]
    assert len(records) == 1
    msg = records[0].getMessage()
    assert "usage_keys=['cache_creation_input_tokens', 'cache_read_input_tokens', " in msg
    assert "model_usage_keys=['claude-sonnet-4-5-20250929']" in msg
    assert "usage_in=10" in msg
    assert "usage_out=5" in msg
    assert "usage_cache_read=3" in msg
    assert "usage_cache_create=1" in msg
    assert "model_usage_in=12345" in msg
    assert "model_usage_out=1234" in msg
    assert "model_usage_cache_read=100" in msg
    assert "model_usage_cache_create=7" in msg
    assert "num_turns=2" in msg
    assert "total_cost_usd=있음" in msg
    # 프롬프트 조각과 응답 원문은 담지 않는다
    assert "원문" not in msg
    assert "raw_text" not in msg


def test_build_call_usage_logs_raw_usage_model_usage_only(caplog):
    caplog.set_level("INFO", logger="slidecaptain.pipeline.subscription")
    result = _result(
        model_usage={
            "claude-sonnet-4-5-20250929": {
                "inputTokens": 100,
                "outputTokens": 10,
                "cacheReadInputTokens": 0,
                "cacheCreationInputTokens": 0,
                "webSearchRequests": 0,
                "costUSD": 0.001,
                "contextWindow": 200000,
                "maxOutputTokens": 8192,
            }
        },
    )

    build_call_usage(result, assistant_model=None)

    msg = caplog.records[-1].getMessage()
    assert "usage_keys=[]" in msg
    assert "usage_in=None" in msg
    assert "usage_out=None" in msg
    assert "usage_cache_read=None" in msg
    assert "usage_cache_create=None" in msg
    assert "model_usage_in=100" in msg
    assert "model_usage_out=10" in msg


def test_build_call_usage_logs_raw_usage_usage_dict_only(caplog):
    caplog.set_level("INFO", logger="slidecaptain.pipeline.subscription")
    result = _result(
        usage={
            "input_tokens": 7,
            "output_tokens": 2,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        },
    )

    build_call_usage(result, assistant_model=None)

    msg = caplog.records[-1].getMessage()
    assert "model_usage_keys=[]" in msg
    assert "model_usage_in=None" in msg
    assert "model_usage_out=None" in msg
    assert "usage_in=7" in msg
    assert "usage_out=2" in msg


def test_build_call_usage_logs_raw_usage_neither_source_no_exception(caplog):
    caplog.set_level("INFO", logger="slidecaptain.pipeline.subscription")
    result = _result()

    build_call_usage(result, assistant_model=None)  # 예외 없이 끝난다

    msg = caplog.records[-1].getMessage()
    assert "usage_keys=[]" in msg
    assert "model_usage_keys=[]" in msg
    assert "usage_in=None" in msg
    assert "model_usage_in=None" in msg
    assert "num_turns=" in msg


def test_build_call_usage_logs_raw_usage_handles_non_dict_model_usage_value(caplog):
    """`model_usage` 의 값이 dict 가 아닌 이상값이어도 예외 없이 로그가 남는다.

    로그 헬퍼(`_log_raw_usage_line`) 자체만 검증한다: `build_call_usage` 본체의 1순위
    토큰 계산 분기는 이 태스크의 변경 대상이 아니며, 그 분기가 비-dict 값에 예외를
    던지는 것은 이 로그 신설과 무관한 기존 동작이다(수정하면 태스크 범위 밖의 변경이 된다).
    """
    caplog.set_level("INFO", logger="slidecaptain.pipeline.subscription")
    result = _result(model_usage={"weird-model": "not-a-dict"})

    sub._log_raw_usage_line(result)  # 예외 없이 끝난다

    msg = caplog.records[-1].getMessage()
    assert "model_usage_keys=['weird-model']" in msg
    assert "model_usage_in=None" in msg


def test_build_call_usage_logs_raw_usage_on_error_result(caplog):
    """`is_error` 결과에서도 같은 로그가 남는다 (build_call_usage 가 호출되는 모든 경로)."""
    caplog.set_level("INFO", logger="slidecaptain.pipeline.subscription")
    result = _result(
        is_error=True,
        errors=["rate limited"],
        usage={
            "input_tokens": 1,
            "output_tokens": 1,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        },
    )

    build_call_usage(result, assistant_model=None)

    msg = caplog.records[-1].getMessage()
    assert "usage_in=1" in msg
    assert "rate limited" not in msg


def test_complete_uses_first_seen_assistant_model(monkeypatch):
    monkeypatch.setattr(
        sub, "query",
        _fake_query(_result(structured={"a": 1}), assistant_model="claude-sonnet-4-5-20250929"),
    )
    resp = asyncio.run(SubscriptionProvider().complete("q", {"type": "object"}))
    assert resp.usage is not None
    assert resp.usage.model == "claude-sonnet-4-5-20250929"


def test_call_usage_is_frozen():
    usage = CallUsage(
        model=None, input_tokens=None, output_tokens=None, cache_read_tokens=None,
        cache_creation_tokens=None, duration_ms=1, duration_api_ms=1, num_turns=1,
        cost_usd=None, stop_reason=None, terminal_reason=None, api_error_status=None,
        token_source="none",
    )
    with pytest.raises(Exception):
        usage.model = "x"


def test_provider_response_default_usage_is_none():
    """usage 를 명시하지 않고 만들면 기본값은 None 이다 (기존 호출부 호환)."""
    resp = ProviderResponse(structured={"answer": 2}, raw_text="원문")
    assert resp.usage is None
