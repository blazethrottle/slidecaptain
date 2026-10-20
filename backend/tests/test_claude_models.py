"""D4b: Claude 공식 모델 목록, 해석된 정확 버전, 추론 강도 (2026-10-20 계획 docs/plans/2026-10-20-revision-d4b-claude-models.md).

목록은 공식 SDK의 CLI 초기화 응답에서 읽는다. 프롬프트를 보내지 않으므로 생성 호출이 없다. 시험은 초기화 응답을 가짜로 둔다.
"""

import asyncio

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


def test_missing_cli_fails_before_any_process(monkeypatch):
    monkeypatch.setattr(module, "resolve_cli_path", lambda: None)
    with pytest.raises(ProviderNotAvailable) as raised:
        module._read_claude_catalog()
    assert raised.value.code == "provider_missing"


@pytest.fixture
def claude(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "check_login", lambda: LoginStatus(logged_in=True, auth_method="claude.ai"))
    connection = ClaudeConnection(catalog_reader=Reader())
    manager = AIConnections(tmp_path / "ai.json", connections={"claude": connection})
    yield manager, connection
    manager.close()


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
