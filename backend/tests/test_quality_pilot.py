"""대표 보고서 실행 도구의 무호출 기본값, 상한과 산출물 보존."""
import asyncio
import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from scripts.quality_pilot import BudgetedProvider, _PilotConnection, main, run_pilot, scenario
from slidecaptain.models.deck import Deck
from slidecaptain.pipeline.connections import AIConnections
from slidecaptain.pipeline.provider import CallUsage, ProviderCallFailed, ProviderResponse
from slidecaptain.server.app import create_app
from slidecaptain.storage.file_store import FileProjectStore


class CountingProvider:
    def __init__(self, response=None, error=None):
        self.calls = 0
        self.response = response or ProviderResponse(structured={}, raw_text="")
        self.error = error

    async def complete(self, prompt, schema):
        self.calls += 1
        if self.error:
            raise self.error
        return self.response


def test_prepare_does_not_instantiate_live_provider_or_check_login(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("preparation must not touch real connections")
    monkeypatch.setattr("scripts.quality_pilot.ClaudeConnection", forbidden)
    output = tmp_path / "prepare"
    assert main(["--output", str(output)]) == 0
    result = json.loads((output / "report.json").read_text())
    assert result["status"] == "prepared"
    assert result["external_calls"] == 0
    data = json.loads((output / "input.json").read_text())
    assert data["synthetic"] is True
    assert len(data["deck"]["structure"]["chapters"]) == 3


@pytest.mark.parametrize("flags", [[], ["--consent"], ["--max-calls", "5"], ["--consent", "--max-calls", "0"]])
def test_live_requires_consent_and_positive_explicit_budget(tmp_path, flags):
    output = tmp_path / "live"
    with pytest.raises(SystemExit) as exc:
        main(["--live", "--output", str(output), *flags])
    assert exc.value.code == 2
    assert not output.exists()


@pytest.mark.parametrize("failure", [False, True])
def test_provider_limit_counts_failed_attempts_and_stops_before_dispatch(failure):
    upstream = CountingProvider(error=ProviderCallFailed("failed") if failure else None)
    bounded = BudgetedProvider(upstream, max_calls=1)
    if failure:
        with pytest.raises(ProviderCallFailed):
            asyncio.run(bounded.complete("synthetic", {}))
    else:
        asyncio.run(bounded.complete("synthetic", {}))
    with pytest.raises(ProviderCallFailed):
        asyncio.run(bounded.complete("synthetic", {}))
    assert upstream.calls == bounded.calls == 1
    assert bounded.blocked_calls == 1


def test_offline_roundtrip_exports_three_editable_slides_and_preserves_rewrite(tmp_path):
    result = run_pilot(tmp_path / "offline", mode="offline", max_calls=5)
    assert result["status"] == "completed"
    assert result["external_calls"] == 0
    assert result["provider_calls"] == 2
    assert result["checks"]["pptx_slide_count"] == 3
    assert result["checks"]["rewrite_preserved_slides"] is True
    assert result["checks"]["preview_did_not_save"] is True
    assert result["checks"]["pptx_hash_matches"] is True
    assert result["checks"]["editable_diagram"] is True
    assert result["checks"]["final_export_blocked"] is True
    assert result["review"]["powerpoint"] == "not_run"
    assert result["review"]["reader"] == "not_run"
    assert result["calls"][0]["usage"] is None
    for call in result["calls"]:
        request = json.loads((tmp_path / "offline" / f'call-{call["number"]:02d}-input.json').read_text())
        assert hashlib.sha256(request["prompt"].encode("utf-8")).hexdigest() == call["prompt_sha256"]
        assert hashlib.sha256(json.dumps(request["schema"], sort_keys=True).encode("utf-8")).hexdigest() == call["schema_sha256"]


def test_format_retries_share_one_budget_and_leave_original_draft(tmp_path):
    upstream = CountingProvider()
    output = tmp_path / "bad-format"
    result = run_pilot(output, mode="offline", max_calls=1, provider=upstream)
    assert result["status"] == "blocked"
    assert upstream.calls == 1
    assert result["provider_calls"] == 1
    assert result["blocked_calls"] == 1
    initial = json.loads((output / "input.json").read_text())["deck"]
    saved = json.loads((output / "projects" / "quality-pilot" / "deck.json").read_text())
    assert saved == initial
    assert json.loads((output / "report.json").read_text())["status"] == "blocked"


def test_rewrite_budget_stop_keeps_generated_body(tmp_path):
    output = tmp_path / "stopped"
    result = run_pilot(output, mode="offline", max_calls=1)
    assert result["status"] == "blocked"
    assert result["provider_calls"] == 1
    assert (output / "chapter-result.json").exists()
    assert (output / "before-rewrite.json").exists()
    assert not (output / "rewrite-result.json").exists()
    before = json.loads((output / "before-rewrite.json").read_text())
    saved = json.loads((output / "projects" / "quality-pilot" / "deck.json").read_text())
    assert saved == before


def test_condense_budget_stop_is_not_hidden_by_successful_draft(tmp_path):
    upstream = CountingProvider(response=ProviderResponse(structured={
        "template": "bullet_box", "bullets": [{"text": "검토 담당자에게 요청을 전달한다."}] * 60,
        "conclusion": "확인 필요", "footnote": "합성 자료",
    }, raw_text="synthetic"))
    output = tmp_path / "condense-limit"
    result = run_pilot(output, mode="offline", max_calls=1, provider=upstream)
    assert result["status"] == "blocked"
    assert result["stage"] == "chapter"
    assert upstream.calls == 1
    assert result["blocked_calls"] == 1
    saved = json.loads((output / "before-rewrite.json").read_text())
    body = next(s for s in saved["slides"] if s["chapter_id"] == "pilot-action")
    assert len(body["slots"]["bullets"]) == 60


def test_provider_failure_records_unavailable_usage_without_raw_exception(tmp_path):
    upstream = CountingProvider(error=ProviderCallFailed("secret failure details"))
    output = tmp_path / "failure"
    result = run_pilot(output, mode="offline", max_calls=5, provider=upstream)
    assert result["status"] == "blocked"
    assert result["calls"][0]["usage"] is None
    assert result["calls"][0]["status"] == "failed"
    assert "secret failure details" not in (output / "report.json").read_text()
    assert (output / "projects" / "quality-pilot" / "deck.json").exists()


def test_existing_output_is_untouched_and_no_provider_call_occurs(tmp_path):
    output = tmp_path / "existing"
    output.mkdir()
    sentinel = output / "report.json"
    sentinel.write_text("existing")
    upstream = CountingProvider()
    with pytest.raises(FileExistsError):
        run_pilot(output, mode="offline", max_calls=5, provider=upstream)
    assert sentinel.read_text() == "existing"
    assert upstream.calls == 0


@pytest.mark.parametrize("headers,status", [
    ({"X-AI-Consent": "SlideCaptain"}, 409),
    ({"X-AI-Consent": "SlideCaptain", "X-AI-Selection": "old"}, 409),
    ({}, 428),
])
def test_pilot_connection_enforces_consent_and_selection_before_calls(tmp_path, headers, status):
    store = FileProjectStore(tmp_path / "projects")
    data = scenario()
    store.create_project("quality-pilot")
    store.save_deck("quality-pilot", Deck.model_validate(data["deck"]), snapshot=False)
    for name, text in data["sources"].items():
        store.write_source("quality-pilot", name, text)
    provider = CountingProvider()
    bounded = BudgetedProvider(provider, max_calls=5)
    manager = AIConnections(tmp_path / "settings.json", connections={"claude": _PilotConnection(bounded, "sonnet")})
    with TestClient(create_app(store, ai_connections=manager), headers={"X-Requested-With": "SlideCaptain"}) as client:
        response = client.post("/api/projects/quality-pilot/generate/chapter/pilot-action", json={}, headers=headers)
    assert response.status_code == status
    assert provider.calls == 0


def test_offline_never_touches_real_connection(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("offline must not instantiate live connections")
    monkeypatch.setattr("scripts.quality_pilot.ClaudeConnection", forbidden)
    assert run_pilot(tmp_path / "offline", mode="offline", max_calls=2)["status"] == "completed"


def test_two_format_failures_do_not_start_rewrite(tmp_path):
    provider = CountingProvider()
    output = tmp_path / "format-fail"
    result = run_pilot(output, mode="offline", max_calls=5, provider=provider)
    assert result["status"] == "blocked"
    assert result["stage"] == "chapter"
    assert provider.calls == 2
    assert not (output / "before-rewrite.json").exists()
    assert not (output / "rewrite-result.json").exists()


@pytest.mark.parametrize("fails", [False, True])
def test_usage_preserves_known_zero_missing_fields_and_observed_model(fails):
    usage = CallUsage(**{name: None for name in CallUsage.model_fields if name != "token_source"}, token_source="none")
    usage = usage.model_copy(update={"input_tokens": 0, "model": "observed-model"})
    provider = CountingProvider(error=ProviderCallFailed("failed", usage=usage) if fails else None,
                                response=ProviderResponse(structured={}, raw_text="", usage=usage))
    bounded = BudgetedProvider(provider, max_calls=1)
    if fails:
        with pytest.raises(ProviderCallFailed):
            asyncio.run(bounded.complete("synthetic", {}))
    else:
        asyncio.run(bounded.complete("synthetic", {}))
    assert bounded.records[0]["usage"] == usage.model_dump(mode="json")


def test_journal_failure_before_dispatch_stops_without_sending():
    provider = CountingProvider()
    def cannot_write():
        raise OSError("disk unavailable")
    bounded = BudgetedProvider(provider, max_calls=2, on_change=cannot_write)
    with pytest.raises(OSError):
        asyncio.run(bounded.complete("synthetic", {}))
    assert provider.calls == bounded.calls == 0


def test_journal_failure_after_response_stops_next_dispatch(tmp_path, monkeypatch):
    from scripts import quality_pilot
    original_write = quality_pilot._write
    provider = CountingProvider()
    writes = 0
    def write(path, data):
        nonlocal writes
        if path.name == "report.json":
            writes += 1
            if writes == 2:
                raise OSError("synthetic write failure")
        original_write(path, data)
    monkeypatch.setattr(quality_pilot, "_write", write)
    result = run_pilot(tmp_path / "journal-failure", mode="offline", max_calls=5, provider=provider)
    assert result["status"] == "blocked"
    assert provider.calls == 1
