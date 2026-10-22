"""응답 관측 진단 (개정판 D4 실제 생성 확인 계획 3.3).

실제 적용 모델과 강도를 응답에서 읽을 수 있는지 보려고 칸 이름과 허용한 칸의 값만 로그에 남긴다.
원시 응답에는 계정 정보가 들어 있으므로 다른 칸의 값은 남기지 않는다. 실제 AI 호출은 없다.
"""

import asyncio
import logging

from claude_agent_sdk import SystemMessage

import slidecaptain.pipeline.subscription as sub
from slidecaptain.pipeline.codex import CodexProvider
from slidecaptain.pipeline.provider import observed_fields
from slidecaptain.pipeline.subscription import SubscriptionProvider
from tests.test_codex_provider import FakeRPC
from tests.test_subscription_provider import _result

SECRET_EMAIL = "someone@example.com"
# 계정 경로를 리터럴로 두면 공개 저장소 감사기에 걸린다. 조각을 이어 붙인다 (test_public_repo_audit.py와 같은 방식)
SECRET_PATH = "/".join(["C:", "Users", "someone", "AppData"])


def test_observed_fields_keeps_names_and_only_allowed_values():
    seen = observed_fields(
        {"model": "m-1", "effortLevel": "low", "thinking": {"type": "adaptive", "budget": 10},
         "account": {"email": SECRET_EMAIL, "plan": "max"}, "cwd": SECRET_PATH, "tools": ["a"]},
        value_keys={"model"}, value_hints=("effort", "thinking"))
    assert seen["values"] == {"model": "m-1", "effortLevel": "low", "thinking.type": "adaptive", "thinking.budget": 10}
    assert {"account", "account.email", "account.plan", "cwd", "tools"} <= set(seen["keys"])
    assert SECRET_EMAIL not in repr(seen) and SECRET_PATH not in repr(seen) and "max" not in repr(seen)


def test_observed_fields_drops_odd_key_names_and_truncates_long_values():
    seen = observed_fields({SECRET_EMAIL: 1, "model": "x" * 500}, value_keys={"model"}, value_hints=())
    assert SECRET_EMAIL not in repr(seen)
    assert len(seen["values"]["model"]) <= 80


def test_observed_fields_counts_listed_items_without_their_values():
    seen = observed_fields({"mcp_servers": [{"path": SECRET_EMAIL}], "tools": [], "skills": {"a": SECRET_PATH}},
                           value_keys=set(), value_hints=(), count_keys={"mcp_servers", "tools", "skills"})
    assert seen["values"] == {"mcp_servers#count": 1, "tools#count": 0, "skills#count": 1}
    assert SECRET_EMAIL not in repr(seen) and SECRET_PATH not in repr(seen)


def test_observed_fields_lists_item_names_but_not_paths():
    """정체를 모르는 플러그인을 가리려고 개수 칸에 이름 목록을 더한다. 경로 같은 다른 칸은 담지 않는다 (D4 생성 격리 3절 2)."""
    plugins = [{"name": "builtin-design", "path": SECRET_PATH}, {"path": SECRET_PATH}]
    seen = observed_fields({"plugins": plugins, "slash_commands": ["loop", "x" * 100] + [f"c{n}" for n in range(50)]},
                           value_keys=set(), value_hints=(), count_keys={"plugins", "slash_commands"})
    assert seen["values"]["plugins#count"] == 2 and seen["values"]["plugins#names"] == ["builtin-design"]
    names = seen["values"]["slash_commands#names"]
    assert names[0] == "loop" and len(names[1]) == 60 and len(names) == 40
    assert SECRET_PATH not in repr(seen)


def test_claude_init_message_is_logged_without_path_values(monkeypatch, caplog):
    """스트림 초기화 메시지에는 계정 칸 대신 사용자 이름이 든 경로 칸이 있다 (리뷰 LCR-07). 값은 남기지 않는다."""
    init = SystemMessage(subtype="init", data={
        "type": "system", "subtype": "init", "model": "claude-test-1", "effort": "low",
        "per_turn_effort_active": False, "account": {"email": SECRET_EMAIL}, "cwd": SECRET_PATH,
        "memory_paths": {"user": SECRET_PATH}, "scratchpad_path": SECRET_PATH, "apiKeySource": "none",
        "mcp_servers": [], "tools": [], "plugins": [{"path": SECRET_PATH}]})

    async def fake(prompt, options):
        yield init
        yield _result(structured={})

    monkeypatch.setattr(sub, "query", fake)
    with caplog.at_level(logging.INFO, logger="slidecaptain.pipeline.subscription"):
        asyncio.run(SubscriptionProvider(effort="low").complete("q", {}))
    [line] = [r.getMessage() for r in caplog.records if "응답 관측" in r.getMessage()]
    assert "claude-test-1" in line and "'effort': 'low'" in line and "'per_turn_effort_active': False" in line
    assert "'mcp_servers#count': 0" in line and "'plugins#count': 1" in line and "memory_paths.user" in line
    assert SECRET_EMAIL not in caplog.text and SECRET_PATH not in caplog.text


def _failing_query(*, stderr_lines, error=None, result=None, assistant_error=None):
    async def fake(prompt, options):
        for line in stderr_lines:
            options.stderr(line)
        if assistant_error is not None:
            from claude_agent_sdk import AssistantMessage
            yield AssistantMessage(content=[], model="claude-test-1", error=assistant_error)
        if error is not None:
            raise error
        yield result
    return fake


def test_cli_stderr_tail_is_logged_only_when_the_call_fails(monkeypatch, caplog):
    """거절 판정에는 CLI 오류 원문이 필요하다 (리뷰 LCR-03). SDK는 콜백이 있을 때만 표준 오류를 받는다."""
    from claude_agent_sdk import ProcessError
    from slidecaptain.pipeline.provider import ProviderCallFailed
    import pytest

    lines = [f"line {n}" for n in range(30)] + ["Error: model 'x[1m]' is not available"]
    monkeypatch.setenv(sub.ENV_STDERR_LOG, "1")
    monkeypatch.setattr(sub, "query", _failing_query(stderr_lines=lines, error=ProcessError("failed", exit_code=1)))
    with caplog.at_level(logging.INFO, logger="slidecaptain.pipeline.subscription"):
        with pytest.raises(ProviderCallFailed):
            asyncio.run(SubscriptionProvider().complete("q", {}))
    assert "is not available" in caplog.text and "line 29" in caplog.text
    assert "line 0\n" not in caplog.text and "'line 0'" not in caplog.text  # 마지막 몇 줄만 남긴다
    caplog.clear()
    monkeypatch.setattr(sub, "query", _failing_query(stderr_lines=["harmless note"], result=_result(structured={})))
    with caplog.at_level(logging.INFO, logger="slidecaptain.pipeline.subscription"):
        asyncio.run(SubscriptionProvider().complete("q", {}))
    assert "harmless note" not in caplog.text


def test_error_result_logs_subtype_and_assistant_error(monkeypatch, caplog):
    from slidecaptain.pipeline.provider import ProviderCallFailed
    import pytest

    failed = _result(is_error=True, subtype="error_during_execution", errors=["boom"])
    monkeypatch.setattr(sub, "query", _failing_query(stderr_lines=[], result=failed, assistant_error="invalid_request"))
    with caplog.at_level(logging.INFO, logger="slidecaptain.pipeline.subscription"):
        with pytest.raises(ProviderCallFailed):
            asyncio.run(SubscriptionProvider().complete("q", {}))
    assert "error_during_execution" in caplog.text and "invalid_request" in caplog.text


def test_codex_thread_and_turn_responses_are_logged_without_account_values(tmp_path, caplog):
    rpc = FakeRPC(tmp_path)
    rpc.account = {"type": "chatgpt", "email": SECRET_EMAIL}
    original = rpc.request

    def request(method, params=None):
        result = original(method, params)
        if method == "thread/start":
            result = {**result, "reasoningEffort": "medium", "cwd": SECRET_PATH}
        return result

    rpc.request = request
    with caplog.at_level(logging.INFO, logger="slidecaptain.pipeline.codex"):
        asyncio.run(CodexProvider(tmp_path, model="gpt-test", effort="low", rpc_factory=lambda _: rpc)
                    .complete("question", {"type": "object", "properties": {"answer": {"type": "integer"}}}))
    lines = [r.getMessage() for r in caplog.records if "응답 관측" in r.getMessage()]
    assert len(lines) == 3  # thread/start, turn/start, turn/completed
    assert "'reasoningEffort': 'medium'" in lines[0] and "'model': 'gpt-resolved'" in lines[0]
    assert SECRET_EMAIL not in caplog.text and SECRET_PATH not in caplog.text


def test_stderr_is_not_piped_unless_the_diagnostic_switch_is_on(monkeypatch):
    """표준 오류를 파이프로 받으면 읽기 작업이 디코딩 오류로 끝난 뒤 파이프가 차서 CLI가 멈출 수 있다. 데스크톱 앱은 백엔드
    로그를 버리므로 제품 경로에서는 받지 않는다. 실측 도구만 켠다 (코드 리뷰 LCC-01)."""
    captured = {}
    monkeypatch.delenv(sub.ENV_STDERR_LOG, raising=False)

    async def fake(prompt, options):
        captured["options"] = options
        yield _result(structured={})

    monkeypatch.setattr(sub, "query", fake)
    asyncio.run(SubscriptionProvider().complete("q", {}))
    assert captured["options"].stderr is None
    monkeypatch.setenv(sub.ENV_STDERR_LOG, "1")
    asyncio.run(SubscriptionProvider().complete("q", {}))
    assert callable(captured["options"].stderr)


def test_stderr_tail_hides_home_path_and_email(monkeypatch, caplog):
    """표준 오류에는 사용자 이름이 든 경로나 계정이 들어갈 수 있다. 홈 경로는 ~로, 이메일은 가려서 남긴다 (LCC-07)."""
    from pathlib import Path
    from claude_agent_sdk import ProcessError
    from slidecaptain.pipeline.provider import ProviderCallFailed
    import pytest

    home = str(Path.home())
    line = f"Error reading {home}{chr(92)}.claude{chr(92)}settings.json for {SECRET_EMAIL}"
    monkeypatch.setenv(sub.ENV_STDERR_LOG, "1")
    monkeypatch.setattr(sub, "query", _failing_query(stderr_lines=[line, home.replace(chr(92), "/") + "/x"],
                                                     error=ProcessError("failed", exit_code=1)))
    with caplog.at_level(logging.INFO, logger="slidecaptain.pipeline.subscription"):
        with pytest.raises(ProviderCallFailed):
            asyncio.run(SubscriptionProvider().complete("q", {}))
    assert "~" in caplog.text and "so***@example.com" in caplog.text
    assert home not in caplog.text and home.replace(chr(92), "/") not in caplog.text
    assert SECRET_EMAIL not in caplog.text
