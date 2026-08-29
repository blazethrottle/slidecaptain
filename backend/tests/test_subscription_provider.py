import asyncio

import pytest

from slidecaptain.pipeline.provider import ProviderCallFailed, ProviderNotAvailable, ProviderResponse
import slidecaptain.pipeline.subscription as sub
from slidecaptain.pipeline.subscription import DEFAULT_MODEL, SubscriptionProvider


def _fake_query(result_message=None, error: Exception | None = None, captured: dict | None = None):
    async def fake(prompt, options):
        if captured is not None:
            captured["prompt"] = prompt
            captured["options"] = options
        if error is not None:
            raise error
        # 실제 SDK 스트림은 ResultMessage 앞에 System, Assistant 등 다른 메시지를 먼저 낸다.
        # 더미를 선행시켜 isinstance 필터링을 테스트로 고정한다 (2026-08-28 적대 리뷰 반영)
        yield object()
        yield result_message

    return fake


def _result(is_error=False, structured=None, text="원문", errors=None):
    from claude_agent_sdk import ResultMessage

    return ResultMessage(
        subtype="success", duration_ms=1, duration_api_ms=1, is_error=is_error,
        num_turns=1, session_id="s", result=text, structured_output=structured, errors=errors,
    )


def test_complete_returns_structured_and_raw(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(
        sub, "query", _fake_query(_result(structured={"answer": 2}), captured=captured)
    )
    provider = SubscriptionProvider()
    resp = asyncio.run(provider.complete("질문", {"type": "object"}))
    assert resp == ProviderResponse(structured={"answer": 2}, raw_text="원문")
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


def test_cli_connection_error_maps_to_call_failed(monkeypatch):
    from claude_agent_sdk import CLIConnectionError

    monkeypatch.setattr(sub, "query", _fake_query(error=CLIConnectionError("no conn")))
    with pytest.raises(ProviderCallFailed):
        asyncio.run(SubscriptionProvider().complete("q", {}))


def test_error_result_maps_to_call_failed(monkeypatch):
    monkeypatch.setattr(
        sub, "query", _fake_query(_result(is_error=True, errors=["rate limited"]))
    )
    with pytest.raises(ProviderCallFailed) as exc_info:
        asyncio.run(SubscriptionProvider().complete("q", {}))
    assert "rate limited" not in str(exc_info.value)


def test_timeout_maps_to_korean_error(monkeypatch):
    async def slow_query(prompt, options):
        await asyncio.sleep(0.2)
        yield object()  # 타임아웃이 먼저 걸려 도달하지 않는다

    monkeypatch.setattr(sub, "query", slow_query)
    provider = SubscriptionProvider(timeout_s=0.05)
    with pytest.raises(ProviderCallFailed) as exc_info:
        asyncio.run(provider.complete("프롬프트", {"type": "object"}))
    assert "오래 걸려" in str(exc_info.value)
