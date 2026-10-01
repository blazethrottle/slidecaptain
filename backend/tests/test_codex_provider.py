import asyncio
import json
import queue
import sys
from pathlib import Path

import pytest

from slidecaptain.pipeline.codex import CodexConnection, CodexProvider, CodexRPC, codex_command, validated_auth_url, strict_output_schema
from slidecaptain.pipeline.provider import ProviderCallFailed, ProviderNotAvailable


class FakeRPC:
    def __init__(self, home):
        self.cwd = str(home)
        self.events = queue.Queue()
        self.calls = []
        self.closed = False
        self.account = {"type": "chatgpt", "email": "test@example.com"}
        self.finish = "completed"
        self.raw = '{"answer": 42}'

    def request(self, method, params=None):
        self.calls.append((method, params))
        if method == "account/read":
            return {"account": self.account}
        if method == "account/login/start":
            return {"loginId": "test-id", "authUrl": "https://auth.openai.com/authorize?state=not-a-secret"}
        if method == "model/list":
            return {"data": [{"model": "gpt-test", "displayName": "GPT Test"},
                             {"model": "hidden", "hidden": True}, {"model": "image-only", "inputModalities": ["image"]}], "nextCursor": None}
        if method == "thread/start":
            return {"thread": {"id": "thread-1"}, "model": "gpt-resolved"}
        if method == "turn/start":
            def event(name, **kwargs):
                self.events.put({"method": name, "params": {"threadId": "thread-1", "turnId": "turn-1", **kwargs}})
            event("item/completed", item={"type": "agentMessage", "text": self.raw})
            event("thread/tokenUsage/updated", tokenUsage={"total": {"inputTokens": 120, "outputTokens": 45, "cachedInputTokens": 20}})
            event("turn/completed", turn={"id": "turn-1", "status": self.finish})
            return {"turn": {"id": "turn-1"}}
        return {}

    def close(self):
        self.closed = True


def test_structured_generation_pins_model_schema_and_reports_real_usage(tmp_path):
    rpc = FakeRPC(tmp_path)
    schema = {"type": "object", "properties": {"answer": {"type": "integer"}}}
    result = asyncio.run(CodexProvider(tmp_path, model="gpt-test", rpc_factory=lambda _: rpc).complete("question", schema))
    assert result.structured == {"answer": 42}
    assert result.usage.model == "gpt-resolved"
    assert result.usage.input_tokens == 120
    assert result.usage.cost_usd is None
    assert result.usage.cache_creation_tokens is None
    thread = next(p for method, p in rpc.calls if method == "thread/start")
    turn = next(p for method, p in rpc.calls if method == "turn/start")
    assert thread["ephemeral"] is True
    assert thread["sandbox"] == "read-only"
    assert thread["model"] == turn["model"] == "gpt-test"
    assert turn["outputSchema"] == strict_output_schema(schema)
    assert turn["sandboxPolicy"]["networkAccess"] is False
    assert rpc.closed


@pytest.mark.parametrize("mode", ["api_key", "failed", "invalid_json", "timeout"])
def test_failure_and_raw_text_paths_close_process(tmp_path, mode):
    rpc = FakeRPC(tmp_path)
    if mode == "api_key": rpc.account = {"type": "apiKey"}
    if mode == "failed": rpc.finish = "failed"
    if mode == "invalid_json": rpc.raw = "invalid JSON"
    provider = CodexProvider(tmp_path, model="gpt-test", timeout_s=0 if mode == "timeout" else 10, rpc_factory=lambda _: rpc)
    if mode == "invalid_json":
        result = asyncio.run(provider.complete("question", {}))
        assert result.structured is None
        assert result.raw_text == "invalid JSON"
    else:
        with pytest.raises((ProviderNotAvailable, ProviderCallFailed)):
            asyncio.run(provider.complete("question", {}))
    assert rpc.closed


@pytest.mark.parametrize("url", ["javascript:alert(1)", "https://auth.openai.com.evil.test/login",
    "http://auth.openai.com/login", "https://attacker@auth.openai.com/login", "https://auth.openai.com:444/login", None])
def test_only_official_https_login_urls(url):
    with pytest.raises(ProviderNotAvailable):
        validated_auth_url(url)


def test_login_matches_attempt_checks_account_and_never_calls_model(tmp_path):
    rpc = FakeRPC(tmp_path)
    connection = CodexConnection(tmp_path, rpc_factory=lambda _: rpc)
    assert connection.status().account == "te***@example.com"
    assert [m.id for m in connection.models()] == ["gpt-test"]
    assert connection.start_login().state == "pending"
    rpc.events.put({"method": "account/login/completed", "params": {"loginId": "unrelated", "success": True}})
    assert connection.login_status().state == "pending"
    rpc.events.put({"method": "account/login/completed", "params": {"loginId": "test-id", "success": True}})
    assert connection.login_status().state == "succeeded"
    assert not any(method in {"thread/start", "turn/start"} for method, _ in rpc.calls)
    connection.close()
    assert rpc.closed


def test_cancellation_and_expiry_do_not_report_connected(tmp_path, monkeypatch):
    rpc = FakeRPC(tmp_path)
    connection = CodexConnection(tmp_path, rpc_factory=lambda _: rpc)
    connection.start_login()
    assert connection.cancel_login().state == "cancelled"
    assert ("account/login/cancel", {"loginId": "test-id"}) in rpc.calls
    connection.start_login()
    monkeypatch.setattr("slidecaptain.pipeline.codex.time.monotonic", lambda: connection._started + 181)
    assert connection.login_status().state == "failed"


def test_launch_settings_disable_tools_and_keep_sandbox():
    cli = Path("/native/codex")
    args = codex_command(cli)
    assert args[:2] == [str(cli), "app-server"]
    for value in ['features.shell_tool=false', 'features.browser_use=false', 'features.hooks=false',
                  'features.apps=false', 'web_search="disabled"', 'sandbox_mode="read-only"']:
        assert value in args
    assert not any("bypass" in x or "danger-full-access" in x for x in args)


def test_all_real_generation_schemas_satisfy_closed_required_object_contract():
    from slidecaptain.pipeline.prompts import structure_response_schema, chapter_response_schema, _SLOTS_BY_TEMPLATE
    def check(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node["additionalProperties"] is False
                assert set(node["required"]) == set(node["properties"])
            assert "default" not in node
            for value in node.values(): check(value)
        elif isinstance(node, list):
            for value in node: check(value)
    schemas = [structure_response_schema(), structure_response_schema(True),
               *[chapter_response_schema(t) for t in _SLOTS_BY_TEMPLATE]]
    for schema in schemas:
        original = json.dumps(schema)
        check(strict_output_schema(schema))
        assert json.dumps(schema) == original


def test_rpc_handles_interleaving_and_denies_server_tool_requests(tmp_path, monkeypatch):
    import slidecaptain.pipeline.codex as module
    script = tmp_path / "fake_server.py"
    script.write_text('''import json, sys
for line in sys.stdin:
    m = json.loads(line)
    if m.get("method") == "initialize":
        print(json.dumps({"id": m["id"], "result": {}}), flush=True)
    elif m.get("method") == "probe":
        print(json.dumps({"id": "tool", "method": "item/commandExecution/requestApproval", "params": {}}), flush=True)
        print(json.dumps({"method": "account/updated", "params": {"authMode": "chatgpt"}}), flush=True)
        print(json.dumps({"id": m["id"], "result": {"ok": True}}), flush=True)
    elif m.get("method") == "denial":
        print(json.dumps({"id": m["id"], "result": {"denied": denied}}), flush=True)
    elif m.get("id") == "tool":
        denied = m.get("error", {}).get("code") == -32601
''')
    monkeypatch.setattr(module, "resolve_codex_path", lambda: Path(sys.executable))
    monkeypatch.setattr(module, "codex_command", lambda cli: [str(cli), str(script)])
    rpc = CodexRPC(tmp_path / "profile", timeout=2)
    try:
        assert rpc.request("probe") == {"ok": True}
        assert rpc.events.get(timeout=1)["method"] == "account/updated"
        assert rpc.request("denial") == {"denied": True}
    finally:
        rpc.close()
    assert rpc._process.poll() is not None
