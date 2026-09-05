import asyncio

import pytest

from slidecaptain.pipeline.provider import (
    CallUsage,
    ProviderCallFailed,
    ProviderNotAvailable,
    ProviderResponse,
)
import slidecaptain.pipeline.subscription as sub
from slidecaptain.pipeline.subscription import DEFAULT_MODEL, SubscriptionProvider, build_call_usage


def _fake_query(result_message=None, error: Exception | None = None, captured: dict | None = None,
                assistant_model: str | None = None):
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
    assert "529" not in msg


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
        total_cost_usd=0.012,
    )
    usage = build_call_usage(result, assistant_model="claude-sonnet-4-5-20250929")
    assert usage.token_source == "model_usage"
    assert usage.input_tokens == 1200
    assert usage.output_tokens == 120
    assert usage.cost_usd == 0.012
    assert usage.model == "claude-sonnet-4-5-20250929"  # AssistantMessage.model 우선


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
