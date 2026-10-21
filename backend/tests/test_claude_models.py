"""D4b: Claude 공식 모델 목록, 해석된 정확 버전, 추론 강도 (2026-10-20 계획 docs/plans/2026-10-20-revision-d4b-claude-models.md).

목록은 공식 SDK의 CLI 초기화 응답에서 읽는다. 프롬프트를 보내지 않으므로 생성 호출이 없다. 시험은 초기화 응답을 가짜로 둔다.
"""

import asyncio
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

import slidecaptain.pipeline.connections as module
from slidecaptain.pipeline.auth_status import LoginStatus
from slidecaptain.pipeline.connections import AIConnections, AISelection, ClaudeConnection
from slidecaptain.pipeline.provider import ProviderNotAvailable

# 2026-10-20 회사 PC 사용자 프로필 실측의 모양(설명 문구와 비용은 줄였다). 계정 정보는 읽지 않는다
CATALOG = {
    "account": {"email": "someone@example.com"},
    "models": [
        {"value": "default", "displayName": "Default (recommended)", "resolvedModel": "claude-opus-5[1m]",
         "supportedEffortLevels": ["low", "medium", "high", "xhigh", "max"]},
        {"value": "opus[1m]", "displayName": "Opus (1M context)", "resolvedModel": "claude-opus-5[1m]",
         "supportedEffortLevels": ["low", "medium", "high", "xhigh", "max"]},
        {"value": "claude-fable-5[1m]", "displayName": "Fable", "resolvedModel": "claude-fable-5",
         "supportedEffortLevels": ["low", "medium", "high", "xhigh", "max", "ultra"]},
        {"value": "sonnet", "displayName": "Sonnet", "resolvedModel": "claude-sonnet-5",
         "supportedEffortLevels": ["low", "medium", "high", "xhigh", "max"]},
        {"value": "haiku", "displayName": "Haiku", "resolvedModel": "claude-haiku-4-5-20251001",
         "supportedEffortLevels": None},
        {"displayName": "값 없는 항목"},
    ],
}


class Reader:
    def __init__(self, result=CATALOG):
        self.result, self.calls = result, 0

    def __call__(self):
        self.calls += 1
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


def test_catalog_reads_models_exact_versions_and_supported_efforts():
    models = ClaudeConnection(catalog_reader=Reader()).models()
    assert [m.id for m in models] == ["default", "opus[1m]", "claude-fable-5[1m]", "sonnet", "haiku"]
    by_id = {m.id: m for m in models}
    assert by_id["sonnet"].resolved_model == "claude-sonnet-5" and by_id["sonnet"].label == "Sonnet"
    # SDK가 받는 다섯 단계만 남긴다(ultra는 ClaudeAgentOptions.effort가 받지 않는다)
    assert by_id["claude-fable-5[1m]"].supported_efforts == ["low", "medium", "high", "xhigh", "max"]
    assert by_id["haiku"].supported_efforts == []
    assert {m.capability_source for m in models} == {"claude_sdk_init"}
    assert all(m.capabilities_checked_at is not None for m in models)
    assert "account" not in repr(models) and "example.com" not in repr(models)


def test_catalog_is_cached_and_reread_after_the_identity_changes(tmp_path, monkeypatch):
    reader = Reader()
    statuses = [LoginStatus(logged_in=True, auth_method="claude.ai", account="a***@example.com")]
    monkeypatch.setattr(module, "check_login", lambda: statuses[-1])
    connection = ClaudeConnection(catalog_reader=reader)
    manager = AIConnections(tmp_path / "ai.json", connections={"claude": connection})
    try:
        manager.settings()
        manager.settings()
        assert reader.calls == 1
        statuses.append(LoginStatus(logged_in=True, auth_method="claude.ai", account="b***@example.com"))
        manager.settings()  # 신원 변경을 관측하면 다음 조회부터 새 계정의 목록을 읽는다
        manager.settings()
        assert reader.calls == 2
    finally:
        manager.close()


def test_catalog_expires_after_the_ttl(monkeypatch):
    reader = Reader()
    now = [1000.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: now[0])
    connection = ClaudeConnection(catalog_reader=reader)
    connection.models()
    now[0] += module.CLAUDE_CATALOG_TTL_S - 1
    connection.models()
    assert reader.calls == 1
    now[0] += 2
    connection.models()
    assert reader.calls == 2


@pytest.mark.parametrize("error,code", [
    (asyncio.TimeoutError(), "provider_timeout"),
    (RuntimeError("cli exited"), "provider_call_failed"),
    (ProviderNotAvailable("Claude Code를 찾지 못했습니다.", code="provider_missing"), "provider_missing"),
])
def test_failed_lookup_uses_the_last_catalog_or_reports_the_cause(monkeypatch, error, code):
    now = [1000.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: now[0])
    reader = Reader(error)
    with pytest.raises(ProviderNotAvailable) as raised:
        ClaudeConnection(catalog_reader=reader).models()
    assert raised.value.code == code
    reader = Reader()
    connection = ClaudeConnection(catalog_reader=reader)
    first = connection.models()
    now[0] += module.CLAUDE_CATALOG_TTL_S + 1
    reader.result = error
    assert connection.models() == first  # 조회가 실패해도 마지막 목록으로 계속 쓴다


def test_fake_cli_lists_the_default_selection(tmp_path):
    """가짜 CLI의 초기화 응답에 기본 선택 모델이 있어야 한다. 없으면 생성 직전의 모델 확인에서 막혀, 가짜 CLI를 쓰는 POSIX
    관통 시험(test_process_restart)이 호출 전에 실패한다(2026-10-20 macOS CI 실측). Windows는 그 시험을 건너뛰므로 여기서
    가짜 CLI를 직접 띄워 고정한다."""
    from tests.fakes import FAKE_CLAUDE_SCRIPT
    request = {"type": "control_request", "request_id": "r1", "request": {"subtype": "initialize"}}
    done = subprocess.run([sys.executable, str(FAKE_CLAUDE_SCRIPT)], input=json.dumps(request) + "\n",
                          capture_output=True, text=True, encoding="utf-8", timeout=30,
                          env={**os.environ, "FAKE_CLAUDE_DIR": str(tmp_path / "record")})
    assert done.returncode == 0, done.stderr
    reply = json.loads(done.stdout.splitlines()[0])
    assert reply["response"]["request_id"] == "r1"
    models = {m.id: m for m in module._claude_catalog_models(reply["response"]["response"])}
    assert AISelection().model in models


def test_missing_cli_fails_before_any_process(monkeypatch):
    monkeypatch.setattr(module, "resolve_cli_path", lambda: None)
    with pytest.raises(ProviderNotAvailable) as raised:
        module._read_claude_catalog()
    assert raised.value.code == "provider_missing"


class FakeSDKClient:
    """claude_agent_sdk.ClaudeSDKClient 대역. 받은 옵션을 남기고, 연결(SDK 초기화)에 걸리는 시간을 정한다."""
    delay = 0.0
    made: list["FakeSDKClient"] = []

    def __init__(self, options=None):
        self.options, self.queried = options, False
        FakeSDKClient.made.append(self)

    async def __aenter__(self):
        await asyncio.sleep(self.delay)
        return self

    async def __aexit__(self, *exc):
        return False

    async def get_server_info(self):
        return CATALOG

    async def query(self, *args, **kwargs):
        self.queried = True


@pytest.fixture
def sdk(monkeypatch):
    import claude_agent_sdk
    FakeSDKClient.delay, FakeSDKClient.made = 0.0, []
    monkeypatch.setattr(claude_agent_sdk, "ClaudeSDKClient", FakeSDKClient)
    monkeypatch.setattr(module, "resolve_cli_path", lambda: "claude")
    return FakeSDKClient


def test_catalog_read_sends_no_prompt_and_isolates_settings_tools_and_mcp(sdk):
    # 리뷰 CMR-08, CMR-07: 목록 조회는 초기화만 하고 프롬프트를 보내지 않는다. 사용자 설정, 도구, 사용자 MCP 서버를 쓰지 않는다
    assert module._read_claude_catalog() == CATALOG
    [client] = sdk.made
    assert client.options.tools == [] and client.options.setting_sources == []
    assert client.options.strict_mcp_config is True
    assert client.queried is False
    assert not Path(client.options.cwd).exists()  # 임시 작업 폴더를 남기지 않는다 (CMR-09)


def test_catalog_read_is_bounded_including_the_connect_step(sdk, monkeypatch):
    # 리뷰 CMR-02: 실제 대기는 연결(SDK 초기화) 단계에서 일어난다. 제한 시간이 그 단계까지 덮고, 호출자는 정리를 기다리지 않는다
    monkeypatch.setattr(module, "CLAUDE_CATALOG_TIMEOUT_S", 0.3)
    sdk.delay = 3.0
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        module._read_claude_catalog()
    assert time.monotonic() - started < 1.5
    with pytest.raises(ProviderNotAvailable) as raised:
        ClaudeConnection().models()
    assert raised.value.code == "provider_timeout"


def test_catalog_work_folder_is_removed_even_if_the_cli_still_holds_it(sdk, monkeypatch):
    # 리뷰 CMR-09: Windows에서는 CLI가 끝나기 전에 폴더를 지우면 WinError 32가 난다. 다시 지워 빈 폴더를 남기지 않는다
    real, calls = module.shutil.rmtree, []

    def busy_once(path, *args, **kwargs):
        calls.append(path)
        if len(calls) == 1:
            raise PermissionError(32, "다른 프로세스가 사용 중")
        return real(path, *args, **kwargs)

    monkeypatch.setattr(module.shutil, "rmtree", busy_once)
    module._read_claude_catalog()
    folder = Path(sdk.made[0].options.cwd)
    deadline = time.monotonic() + 5
    while folder.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not folder.exists() and len(calls) >= 2


def test_catalog_skips_ids_the_selection_cannot_store():
    # 리뷰 CMR-12: 선택 저장 규칙(150자, 허용 글자)에 맞지 않는 ID는 목록에 올리지 않는다. 올리면 고른 뒤 저장이 422로 막힌다
    info = {"models": [{"value": "sonnet"}, {"value": "has space"}, {"value": "a" * 151}, {"value": "-first"}]}
    assert [m.id for m in module._claude_catalog_models(info)] == ["sonnet"]


def test_settings_reads_the_list_after_observing_a_new_login(tmp_path, monkeypatch):
    # 리뷰 CMR-04: 로그인 직후의 첫 설정 화면이 로그인 전에 실패한 목록을 그대로 보이지 않는다
    statuses = [LoginStatus(logged_in=False)]
    monkeypatch.setattr(module, "check_login", lambda: statuses[-1])
    reader = Reader(RuntimeError("logged out"))
    manager = AIConnections(tmp_path / "ai.json", connections={"claude": ClaudeConnection(catalog_reader=reader)})
    try:
        first = manager.settings().providers[0]
        assert first.models == [] and first.models_error
        statuses.append(LoginStatus(logged_in=True, auth_method="claude.ai", account="a***@example.com"))
        reader.result = CATALOG
        second = manager.settings().providers[0]
        assert second.models_error is None and "sonnet" in [m.id for m in second.models]
    finally:
        manager.close()


@pytest.fixture
def claude(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "check_login", lambda: LoginStatus(logged_in=True, auth_method="claude.ai"))
    connection = ClaudeConnection(catalog_reader=Reader())
    manager = AIConnections(tmp_path / "ai.json", connections={"claude": connection})
    yield manager, connection
    manager.close()


def test_slow_catalog_read_does_not_hold_the_connection_lock(claude):
    # 리뷰 CMR-03: 목록 조회(Claude CLI 기동, 몇 초)를 하는 동안 상태 조회와 생성 임대 반납이 기다리지 않는다.
    # 반납은 작업 루프 스레드가 동기로 부르므로, 기다리면 작업 루프 전체가 멈춘다
    manager, connection = claude
    manager.settings()
    gate, entered = threading.Event(), threading.Event()

    def slow():
        entered.set()
        gate.wait(3)
        return CATALOG

    reader = threading.Thread(target=manager.settings)
    try:
        with manager.generation(manager.selection_id):
            connection._read_catalog = slow
            connection.invalidate_models()
            reader.start()
            assert entered.wait(5)
            started = time.monotonic()
            manager.selected_status()
        elapsed = time.monotonic() - started  # 상태 조회와 임대 반납
    finally:
        gate.set()
        if reader.ident is not None:
            reader.join(10)
    assert elapsed < 1.0


def test_claude_effort_in_the_catalog_is_saved_and_reaches_the_provider(claude):
    manager, connection = claude
    manager.select(AISelection(provider="claude", model="sonnet", effort="high"))
    with manager.generation(manager.selection_id) as provider:
        assert provider.model == "sonnet" and provider.effort == "high"


@pytest.mark.parametrize("model,effort", [("haiku", "high"), ("sonnet", "ultra")])
def test_claude_effort_outside_the_catalog_is_rejected(claude, model, effort):
    manager, _connection = claude
    with pytest.raises(ValueError, match="추론 강도"):
        manager.select(AISelection(provider="claude", model=model, effort=effort))


def test_saved_alias_missing_from_the_catalog_blocks_generation_without_replacement(claude):
    # 2026-10-20 실측: 기존 별칭 opus는 목록에 없다(opus[1m]만 있다). D4a처럼 자동으로 바꾸지 않고 다시 고르게 한다
    manager, _connection = claude
    manager.selection = AISelection(provider="claude", model="opus")
    with pytest.raises(ProviderNotAvailable) as raised:
        with manager.generation(manager.selection_id):
            pytest.fail("must not generate")
    assert raised.value.code == "model_unavailable"


@pytest.mark.parametrize("effort", ["high", None])
def test_subscription_provider_passes_effort_only_when_chosen(monkeypatch, effort):
    import slidecaptain.pipeline.subscription as subscription
    captured = []

    async def fake_query(prompt, options):
        captured.append(options)
        if False:
            yield None

    monkeypatch.setattr(subscription, "resolve_cli_path", lambda: "claude")
    monkeypatch.setattr(subscription, "query", fake_query)
    provider = subscription.SubscriptionProvider(model="sonnet", effort=effort)
    with pytest.raises(Exception):
        asyncio.run(provider.complete("prompt", {"type": "object"}))
    assert captured and captured[0].effort == effort and captured[0].model == "sonnet"
