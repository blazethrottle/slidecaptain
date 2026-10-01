import asyncio
import json
import threading

import pytest
from fastapi.testclient import TestClient

from slidecaptain.pipeline.auth_status import LoginStatus
from slidecaptain.pipeline.connections import (
    AIConnections, AISelection, ConnectionConflict, LoginAttempt, ModelOption,
)
from slidecaptain.pipeline.provider import ProviderResponse
from slidecaptain.server.app import create_app


class FakeConnection:
    def __init__(self, model):
        self.model = model
        self.login = LoginStatus(logged_in=True, auth_method="subscription", account="te***@example.com")
        self.attempt = LoginAttempt(state="idle")
        self.calls = []

    def status(self):
        return self.login

    def models(self):
        return [ModelOption(id=self.model, label=self.model)]

    def start_login(self):
        self.attempt = LoginAttempt(state="pending", message="공식 브라우저에서 완료해 주세요.")
        return self.attempt

    def login_status(self):
        return self.attempt

    def cancel_login(self):
        self.attempt = LoginAttempt(state="cancelled")
        return self.attempt

    def provider(self, model):
        parent = self

        class Provider:
            async def complete(self, prompt, schema):
                parent.calls.append((model, prompt))
                return ProviderResponse(structured={"chapters": [
                    {"topic": "표지", "conclusion": "", "template": "cover", "source_refs": []},
                ]}, raw_text="")
        return Provider()

    def close(self):
        pass


@pytest.fixture
def manager(tmp_path):
    value = AIConnections(tmp_path / "settings.json", connections={
        "claude": FakeConnection("sonnet"), "chatgpt": FakeConnection("gpt-test"),
    })
    yield value
    value.close()


def test_selection_persists_only_nonsecret_settings(manager):
    manager.select(AISelection(provider="chatgpt", model="gpt-test"))
    data = json.loads(manager.settings_path.read_text())
    assert data == {"provider": "chatgpt", "model": "gpt-test"}
    reloaded = AIConnections(manager.settings_path, connections=manager.connections)
    assert reloaded.selection == manager.selection


def test_model_must_belong_to_selected_provider(manager):
    with pytest.raises(ValueError):
        manager.select(AISelection(provider="chatgpt", model="sonnet"))
    assert manager.selection.provider == "claude"


def test_bad_saved_settings_fail_closed(manager):
    manager.settings_path.write_text('{"provider":"bad","model":"secret"}')
    with pytest.raises(ValueError, match="연결 설정"):
        AIConnections(manager.settings_path, connections=manager.connections)


def test_busy_generation_pins_provider_and_rejects_changes(manager):
    token = manager.selection_id
    with manager.generation(token) as provider:
        with pytest.raises(ConnectionConflict):
            manager.select(AISelection(provider="chatgpt", model="gpt-test"))
        with pytest.raises(ConnectionConflict):
            manager.start_login("claude")
        asyncio.run(provider.complete("document", {}))
    assert manager.connections["claude"].calls == [("sonnet", "document")]
    assert manager.connections["chatgpt"].calls == []
    manager.select(AISelection(provider="chatgpt", model="gpt-test"))
    with pytest.raises(ConnectionConflict):
        with manager.generation(token):
            pytest.fail("stale consent must not run")


def test_unconnected_generation_does_not_call_any_model(manager):
    manager.connections["claude"].login = LoginStatus(logged_in=False)
    from slidecaptain.pipeline.provider import ProviderNotAvailable
    with pytest.raises(ProviderNotAvailable):
        with manager.generation(manager.selection_id):
            pytest.fail("not logged in")


def test_external_account_change_invalidates_disclosure(manager):
    _, token, _ = manager.selected_status()
    manager.connections["claude"].login = LoginStatus(logged_in=True, account="an***@example.com")
    with pytest.raises(ConnectionConflict):
        with manager.generation(token):
            pytest.fail("account changed")
    assert manager.selection_id != token


def test_api_selection_consent_and_both_routes(store, manager):
    headers = {"X-Requested-With": "SlideCaptain", "X-AI-Consent": "SlideCaptain"}
    with TestClient(create_app(store, ai_connections=manager), headers=headers) as client:
        client.post("/api/projects", json={"name": "p", "title": "report"})
        client.put("/api/projects/p/sources/input.md", json={"text": "자료"})
        initial = client.get("/api/status").json()
        assert initial["provider"] == "claude"
        route = "/api/projects/p/generate/structure"
        assert client.post(route, json={}).status_code == 409
        result = client.post(route, json={}, headers={"X-AI-Selection": initial["selection_id"]})
        assert result.status_code == 200
        result = client.put("/api/ai/selection", json={"provider": "chatgpt", "model": "gpt-test"})
        assert result.status_code == 200
        assert client.post(route, json={}, headers={"X-AI-Selection": initial["selection_id"]}).status_code == 409
        selected = client.get("/api/status").json()
        assert selected["provider"] == "chatgpt"
        assert selected["last_generation_at"] is None
        assert client.post(route, json={}, headers={"X-AI-Selection": selected["selection_id"]}).status_code == 200
        assert len(manager.connections["claude"].calls) == len(manager.connections["chatgpt"].calls) == 1


def test_connection_mutations_protected_and_login_is_not_generation(store, manager):
    with TestClient(create_app(store, ai_connections=manager)) as client:
        path = "/api/ai/providers/chatgpt/login"
        assert client.post(path).status_code == 403
        headers = {"X-Requested-With": "SlideCaptain"}
        assert client.post(path, headers={**headers, "Origin": "https://evil.example"}).status_code == 403
        assert client.post(path, headers=headers).json()["state"] == "pending"
        assert client.get(path).json()["state"] == "pending"
        assert client.delete(path, headers=headers).json()["state"] == "cancelled"
        assert client.get("/api/ai/settings").status_code == 200
        assert client.get(path).headers["cache-control"] == "no-store"
        assert not any(x.calls for x in manager.connections.values())


def test_request_cancelled_during_login_check_releases_generation_lease(store, manager):
    import httpx
    store.create_project("p", "report")
    store.write_source("p", "source.md", "자료")
    entered, resume = threading.Event(), threading.Event()
    def slow_status():
        entered.set()
        assert resume.wait(3)
        return LoginStatus(logged_in=True)
    manager.connections["claude"].status = slow_status

    async def scenario():
        app = create_app(store, ai_connections=manager)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
            task = asyncio.create_task(client.post("/api/projects/p/generate/structure", json={}, headers={
                "X-Requested-With": "SlideCaptain", "X-AI-Consent": "SlideCaptain", "X-AI-Selection": manager.selection_id,
            }))
            assert await asyncio.to_thread(entered.wait, 2)
            task.cancel()
            resume.set()
            with pytest.raises(asyncio.CancelledError):
                await task
        # A leaked lease would reject this change forever.
        manager.select(AISelection(provider="chatgpt", model="gpt-test"))
        assert not manager.connections["claude"].calls
    asyncio.run(scenario())


def test_claude_login_uses_official_cli_and_requires_verified_completion(tmp_path, monkeypatch):
    import slidecaptain.pipeline.connections as module
    launched = []
    class Process:
        code = None
        def poll(self): return self.code
        def terminate(self): self.code = -15
        def wait(self, timeout): return self.code
    process = Process()
    cli = tmp_path / "claude.exe"
    monkeypatch.setattr(module, "resolve_cli_path", lambda: cli)
    monkeypatch.setattr(module, "check_login", lambda: LoginStatus(logged_in=True, auth_method="claude.ai"))
    def spawn(args, **kwargs):
        launched.append((args, kwargs))
        return process
    monkeypatch.setattr(module.subprocess, "Popen", spawn)
    connection = module.ClaudeConnection()
    assert connection.start_login().state == "pending"
    assert connection.start_login().state == "pending"
    assert len(launched) == 1
    assert launched[0][0] == [str(cli), "auth", "login"]
    assert not launched[0][1].get("shell")
    process.code = 0
    assert connection.login_status().state == "succeeded"
    process.code = None
    connection.start_login()
    assert connection.cancel_login().state == "cancelled"
    assert process.code == -15


def test_claude_api_auth_is_not_presented_as_subscription(monkeypatch):
    import slidecaptain.pipeline.connections as module
    monkeypatch.setattr(module, "check_login", lambda: LoginStatus(logged_in=True, auth_method="api_key"))
    status = module.ClaudeConnection().status()
    assert status.logged_in is not True
    assert "API 인증" in status.error


def test_login_expires_without_browser_polling(manager):
    manager.start_login("chatgpt")
    timer = manager._login_timers["chatgpt"]
    timer.cancel()  # Trigger the deadline deterministically, without sleeping.
    timer.function()
    assert manager.connections["chatgpt"].attempt.state == "cancelled"
    assert manager.login_status("chatgpt").state == "failed"
    assert "대기 시간" in manager.login_status("chatgpt").message
    assert manager.start_login("chatgpt").state == "pending"
