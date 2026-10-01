"""SDK 결측이 모델별 합산, API, 로컬 기록을 지나서도 숫자로 바뀌지 않아야 한다."""

import asyncio
import json
from pathlib import Path

import pytest
from claude_agent_sdk import ResultMessage
from fastapi.testclient import TestClient

import slidecaptain.pipeline.subscription as sub
from slidecaptain.pipeline.provider import ProviderCallFailed
from slidecaptain.server.app import create_app


FIELDS = (
    ("inputTokens", "input_tokens", "model_usage_in"),
    ("outputTokens", "output_tokens", "model_usage_out"),
    ("cacheReadInputTokens", "cache_read_tokens", "model_usage_cache_read"),
    ("cacheCreationInputTokens", "cache_creation_tokens", "model_usage_cache_create"),
)
TOKENS = dict(inputTokens=7, outputTokens=3, cacheReadInputTokens=0, cacheCreationInputTokens=4)


def result(**overrides):
    fields = dict(
        subtype="success", duration_ms=100, duration_api_ms=90, is_error=False,
        num_turns=1, session_id="synthetic", total_cost_usd=0.0,
        model_usage={"fixture-model": dict(TOKENS)},
    )
    fields.update(overrides)
    return ResultMessage(**fields)


@pytest.mark.parametrize("sdk_field,app_field,log_field", FIELDS)
@pytest.mark.parametrize("null_value", [False, True], ids=["missing", "null"])
@pytest.mark.parametrize("multi_model", [False, True], ids=["single", "multiple"])
def test_missing_model_field_stays_unknown_in_usage_and_log(
    sdk_field, app_field, log_field, null_value, multi_model, caplog,
):
    caplog.set_level("INFO", logger=sub.__name__)
    partial = dict(TOKENS)
    partial.pop(sdk_field)
    if null_value:
        partial[sdk_field] = None
    models = {"partial": partial}
    if multi_model:
        models["complete"] = dict(TOKENS)
    usage = sub.build_call_usage(result(model_usage=models), None)

    assert getattr(usage, app_field) is None
    for key, attr, _ in FIELDS:
        if key != sdk_field:
            assert getattr(usage, attr) == TOKENS[key] * (2 if multi_model else 1)
    assert usage.token_source == "model_usage"
    assert f"{log_field}=None" in caplog.records[-1].getMessage()
    assert usage.cost_usd == 0.0 and usage.duration_ms == 100


@pytest.mark.parametrize("invalid", [True, False, -1, "3", "bad", 3.0, 3.5, float("nan"), float("inf"), {}, []])
def test_invalid_token_count_is_unknown_without_discarding_other_fields(invalid):
    partial = {**TOKENS, "outputTokens": invalid}
    usage = sub.build_call_usage(result(model_usage={"one": TOKENS, "two": partial}), None)
    assert usage.output_tokens is None
    assert usage.input_tokens == 14
    assert usage.cache_read_tokens == 0
    assert usage.cache_creation_tokens == 8


@pytest.mark.parametrize("invalid", [None, "bad", [], True, 7])
def test_malformed_model_entry_prevents_partial_totals_and_model_guess(invalid, caplog):
    caplog.set_level("INFO", logger=sub.__name__)
    message = result(model_usage={"complete": TOKENS, "unknown": invalid})
    usage = sub.build_call_usage(message, None)
    assert usage.token_source == "model_usage"
    assert usage.model is None
    for _, attr, log_field in FIELDS:
        assert getattr(usage, attr) is None
        assert f"{log_field}=None" in caplog.records[-1].getMessage()
    assert sub.build_call_usage(message, "observed-model").model == "observed-model"


@pytest.mark.parametrize("invalid", ["bad", [TOKENS], 7])
def test_malformed_top_level_model_usage_keeps_fallback_tokens_unknown(invalid):
    usage = sub.build_call_usage(result(model_usage=invalid, usage={"input_tokens": 999}), None)
    assert usage.token_source == "usage"
    assert all(getattr(usage, attr) is None for _, attr, _ in FIELDS)
    assert usage.model is None


def test_explicit_zero_is_measured_for_every_model():
    zeros = {key: 0 for key, _, _ in FIELDS}
    usage = sub.build_call_usage(result(model_usage={"one": zeros, "two": zeros}), None)
    assert all(getattr(usage, attr) == 0 for _, attr, _ in FIELDS)
    assert usage.cost_usd == 0.0


def test_different_missing_fields_and_zero_are_not_filled_from_other_models():
    usage = sub.build_call_usage(result(model_usage={
        "one": {"inputTokens": 0, "cacheReadInputTokens": 0, "cacheCreationInputTokens": 0},
        "two": {"outputTokens": 0, "cacheReadInputTokens": 0, "cacheCreationInputTokens": None},
    }), None)
    assert usage.input_tokens is None and usage.output_tokens is None
    assert usage.cache_read_tokens == 0
    assert usage.cache_creation_tokens is None


@pytest.mark.parametrize("fails", [False, True])
def test_provider_preserves_partial_usage_in_success_and_failure(monkeypatch, fails):
    async def fake_query(prompt, options):
        yield result(is_error=fails, model_usage={"fixture-model": {"inputTokens": 7}},
                     structured_output={"ok": True})

    monkeypatch.setattr(sub, "resolve_cli_path", lambda: "/synthetic/claude")
    monkeypatch.setattr(sub, "query", fake_query)
    provider = sub.SubscriptionProvider()
    if fails:
        with pytest.raises(ProviderCallFailed) as caught:
            asyncio.run(provider.complete("synthetic", {}))
        usage = caught.value.usage
    else:
        usage = asyncio.run(provider.complete("synthetic", {})).usage
    assert usage.input_tokens == 7
    assert usage.output_tokens is None and usage.cache_read_tokens is None
    assert usage.cache_creation_tokens is None


def test_sdk_to_api_retry_and_jsonl_match_shared_frontend_fixture(store, monkeypatch):
    structure = {"chapters": [
        {"topic": "표지", "conclusion": "", "template": "cover", "source_refs": []},
        {"topic": "현황", "conclusion": "검토", "template": "bullet_box", "source_refs": ["source.md"]},
    ]}
    messages = [
        result(structured_output={"invalid": True}),
        result(structured_output=structure,
               model_usage={"fixture-model": {"inputTokens": 5, "cacheReadInputTokens": 0}}),
    ]

    async def fake_query(prompt, options):
        yield messages.pop(0)

    monkeypatch.setattr(sub, "resolve_cli_path", lambda: "/synthetic/claude")
    monkeypatch.setattr(sub, "query", fake_query)
    headers = {"X-Requested-With": "SlideCaptain", "X-AI-Consent": "SlideCaptain"}
    with TestClient(create_app(store, provider=sub.SubscriptionProvider()), headers=headers) as client:
        assert client.post("/api/projects", json={"name": "usage-fixture"}).status_code == 201
        assert client.put("/api/projects/usage-fixture/sources/source.md", json={"text": "synthetic source"}).status_code == 200
        response = client.post("/api/projects/usage-fixture/generate/structure", json={"target_chapters": 2})
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["format_retried"] is True
    assert not messages

    expected = json.loads((Path(__file__).parent / "fixtures/usage-missing.json").read_text(encoding="utf-8"))
    assert response.json()["usage"] == expected
    lines = (store.root / "usage-fixture/ai-usage.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["summary"] == expected
    assert "synthetic source" not in lines[0]
    assert "invalid" not in lines[0]
