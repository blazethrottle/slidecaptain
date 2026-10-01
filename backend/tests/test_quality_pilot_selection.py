"""The pilot follows an explicit provider choice without fallback or auth copying."""
import json

import pytest

from scripts import quality_pilot
from slidecaptain.pipeline.auth_status import LoginStatus
from slidecaptain.pipeline.connections import ModelOption


@pytest.mark.parametrize("mode", ["prepare", "offline"])
@pytest.mark.parametrize("provider,model", [("claude", "sonnet"), ("codex", "gpt-6-luna")])
def test_cli_selection_without_live_mode_never_opens_a_connection(tmp_path, monkeypatch, mode, provider, model):
    def forbidden(*args, **kwargs):
        pytest.fail("non-live selection must not access authentication")
    monkeypatch.setattr(quality_pilot, "ClaudeConnection", forbidden)
    monkeypatch.setattr(quality_pilot, "CodexConnection", forbidden)
    output = tmp_path / "run"
    home = tmp_path / "auth"
    flags = ["--offline"] if mode == "offline" else []
    assert quality_pilot.main(["--output", str(output), "--provider", provider,
                               "--codex-home", str(home), *flags]) == 0
    report = json.loads((output / "report.json").read_text())
    assert report["requested_provider"] == ("chatgpt" if provider == "codex" else "claude")
    assert report["requested_model"] == model
    assert report["external_calls"] == 0
    assert not home.exists()


class FakeCodexConnection:
    def __init__(self, *, logged_in=True, models=("gpt-6-luna",)):
        self.logged_in, self.model_ids = logged_in, models
        self.selected = []
        self.calls = 0
        self.closed = False

    def status(self):
        return LoginStatus(logged_in=self.logged_in, auth_method="ChatGPT")

    def models(self):
        return [ModelOption(id=model, label=model) for model in self.model_ids]

    def provider(self, model):
        self.selected.append(model)
        parent = self

        class Provider:
            async def complete(self, prompt, schema):
                parent.calls += 1
                return await quality_pilot.OfflineProvider().complete(prompt, schema)
        return Provider()

    def close(self):
        self.closed = True


@pytest.mark.parametrize("logged_in,models,expected_calls,status", [
    (True, ("gpt-6-luna",), 2, "completed"),
    (False, ("gpt-6-luna",), 0, "blocked"),
    (True, ("gpt-6-sol",), 0, "blocked"),
])
def test_live_codex_uses_selected_profile_and_never_falls_back(
    tmp_path, monkeypatch, logged_in, models, expected_calls, status,
):
    connection = FakeCodexConnection(logged_in=logged_in, models=models)
    homes = []
    def create(home):
        homes.append(home)
        return connection
    def forbidden():
        pytest.fail("Codex selection must not open Claude")
    monkeypatch.setattr(quality_pilot, "ClaudeConnection", forbidden)
    monkeypatch.setattr(quality_pilot, "CodexConnection", create)
    home = tmp_path / "app-data" / ".slidecaptain-codex"
    result = quality_pilot.run_pilot(tmp_path / "run", mode="live", consent=True,
                                    max_calls=3, ai_provider="chatgpt", codex_home=home)
    assert result["status"] == status
    assert result["requested_provider"] == "chatgpt"
    assert result["requested_model"] == "gpt-6-luna"
    assert result["external_calls"] == connection.calls == expected_calls
    assert homes == [home]
    assert connection.selected == ["gpt-6-luna"]
    assert connection.closed


def test_codex_budget_remains_shared_between_chapter_and_rewrite(tmp_path):
    result = quality_pilot.run_pilot(tmp_path / "run", mode="offline", max_calls=1,
                                    ai_provider="chatgpt", model="gpt-6-luna")
    assert result["status"] == "blocked"
    assert result["provider_calls"] == 1
    assert result["blocked_calls"] == 1
    assert (tmp_path / "run" / "before-rewrite.json").exists()
    assert not (tmp_path / "run" / "rewrite-result.json").exists()


@pytest.mark.parametrize("kwargs", [
    {"ai_provider": "other"},
    {"ai_provider": "chatgpt", "model": "invalid model"},
    {"ai_provider": "claude", "model": "gpt-6-luna"},
])
def test_invalid_selection_does_not_create_output(tmp_path, kwargs):
    output = tmp_path / "run"
    with pytest.raises(ValueError):
        quality_pilot.run_pilot(output, **kwargs)
    assert not output.exists()


def test_explicit_codex_model_is_not_replaced_by_luna(tmp_path):
    result = quality_pilot.run_pilot(tmp_path / "run", ai_provider="chatgpt", model="gpt-6-sol")
    assert result["requested_model"] == "gpt-6-sol"


def test_codex_live_cli_also_requires_explicit_consent_and_budget(tmp_path):
    with pytest.raises(SystemExit) as exc:
        quality_pilot.main(["--output", str(tmp_path / "run"), "--provider", "codex", "--live"])
    assert exc.value.code == 2
    assert not (tmp_path / "run").exists()
