"""실측 도구의 강도 전달, 장 생성까지만 실행, CLI 지정, 진단 로그 (개정판 D4 실제 생성 확인 계획 3.4).

실제 AI 호출은 없다. 실제 연결은 가짜로 바꾼다.
"""
import json
import logging
import os

import pytest

from scripts import quality_pilot
import slidecaptain.pipeline.subscription as sub
from slidecaptain.pipeline.auth_status import LoginStatus
from slidecaptain.pipeline.connections import ModelOption


class FakeClaudeConnection:
    """목록(id → 지원 강도)을 돌려주고, 만든 프로바이더의 모델과 강도를 기록한다."""

    def __init__(self, catalog):
        self.catalog = catalog
        self.created = []
        self.calls = 0
        self.cli_at_creation = os.environ.get("SLIDECAPTAIN_CLAUDE_CLI")
        self.closed = False

    def status(self):
        return LoginStatus(logged_in=True, auth_method="claude.ai")

    def models(self):
        return [ModelOption(id=key, label=key, supported_efforts=list(efforts)) for key, efforts in self.catalog.items()]

    def provider(self, model, *, effort=None):
        self.created.append((model, effort))
        parent = self

        class Provider:
            async def complete(self, prompt, schema):
                parent.calls += 1
                logging.getLogger("slidecaptain.pipeline.subscription").info("응답 관측 Claude init: 시험")
                return await quality_pilot.OfflineProvider().complete(prompt, schema)
        return Provider()

    def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def _no_real_cli_version(monkeypatch):
    """실제 모드 시험이 동봉 CLI의 --version을 띄우지 않게 한다 (코드 리뷰 LCC-04). 필요한 시험은 다시 바꾼다."""
    monkeypatch.setattr(quality_pilot, "_cli_version", lambda path, timeout: "test")


def _live(tmp_path, monkeypatch, catalog, **kwargs):
    connections = []

    def create():
        connections.append(FakeClaudeConnection(catalog))
        return connections[-1]

    monkeypatch.setattr(quality_pilot, "ClaudeConnection", create)
    monkeypatch.setattr(quality_pilot, "CodexConnection", lambda *a, **k: pytest.fail("Claude 실행이 Codex를 열었습니다"))
    result = quality_pilot.run_pilot(tmp_path / "run", mode="live", consent=True, **kwargs)
    return result, connections


def test_offline_effort_stops_after_chapter_and_checks_requested_effort_records(tmp_path):
    result = quality_pilot.run_pilot(tmp_path / "run", mode="offline", max_calls=1, effort="low",
                                    stop_after="chapter")
    assert result["status"] == "completed" and result["stage"] == "done"
    assert result["requested_effort"] == "low"
    assert result["provider_calls"] == 1 and result["external_calls"] == 0
    assert result["checks"]["ledger_effort_matches"] is True
    assert result["checks"]["usage_effort_matches"] is True
    assert (tmp_path / "run" / "chapter-result.json").exists()
    assert not (tmp_path / "run" / "rewrite-result.json").exists()


def test_live_catalog_value_with_effort_reaches_the_connection(tmp_path, monkeypatch):
    result, [connection] = _live(tmp_path, monkeypatch, {"default": ["low", "high"], "sonnet": []},
                                 max_calls=1, model="default", effort="low", stop_after="chapter")
    assert result["status"] == "completed"
    assert connection.created == [("default", "low")]
    assert result["external_calls"] == connection.calls == 1
    assert result["checks"]["ledger_effort_matches"] is True and result["checks"]["usage_effort_matches"] is True
    assert connection.closed


@pytest.mark.parametrize("model,effort", [("gpt-6-luna", None), ("default", "max")])
def test_live_claude_model_or_effort_outside_the_catalog_stops_before_any_call(tmp_path, monkeypatch, model, effort):
    result, [connection] = _live(tmp_path, monkeypatch, {"default": ["low"]},
                                 max_calls=1, model=model, effort=effort, stop_after="chapter")
    # 프로바이더 객체는 준비 단계에서 미리 만든다(기존 구조). 보내지 않았는지는 호출 수로 본다
    assert result["status"] == "blocked"
    assert result["external_calls"] == connection.calls == 0
    assert result["checks"]["chapter_error_code"] == "model_unavailable"
    # 사용량 줄이 없으면 불일치(False)가 아니라 판정 없음(None)이다 (코드 리뷰 LCC-06)
    assert result["checks"]["usage_records"] == 0 and result["checks"]["usage_effort_matches"] is None


def test_claude_cli_option_is_used_while_running_and_only_kind_and_version_are_reported(tmp_path, monkeypatch):
    cli = tmp_path / "bin" / "claude.exe"
    cli.parent.mkdir()
    cli.write_bytes(b"")
    monkeypatch.delenv("SLIDECAPTAIN_CLAUDE_CLI", raising=False)
    monkeypatch.setattr(quality_pilot, "_cli_version", lambda path, timeout: "9.9.9")
    result, [connection] = _live(tmp_path, monkeypatch, {"sonnet": ["low"]}, max_calls=1, model="sonnet",
                                 stop_after="chapter", claude_cli=cli)
    assert connection.cli_at_creation == str(cli)
    assert "SLIDECAPTAIN_CLAUDE_CLI" not in os.environ
    assert (result["cli_kind"], result["cli_version"]) == ("other", "9.9.9")
    report_text = (tmp_path / "run" / "report.json").read_text(encoding="utf-8")
    assert str(cli.parent) not in report_text and str(cli.parent).replace("\\", "\\\\") not in report_text


def test_diagnostic_log_keeps_observation_lines_and_detaches_after_the_run(tmp_path, monkeypatch):
    root = logging.getLogger("slidecaptain")
    handlers, level = list(root.handlers), root.level
    _live(tmp_path, monkeypatch, {"sonnet": ["low"]}, max_calls=1, model="sonnet", stop_after="chapter")
    log = (tmp_path / "run" / "diagnostic.log").read_text(encoding="utf-8")
    assert "응답 관측 Claude init" in log
    assert root.handlers == handlers and root.level == level


class _BadShapeProvider:
    def __init__(self):
        self.calls = 0

    async def complete(self, prompt, schema):
        from slidecaptain.pipeline.provider import ProviderResponse
        self.calls += 1
        return ProviderResponse(structured={"unexpected": True}, raw_text="synthetic bad shape")


def test_chapter_stop_records_checks_when_the_format_retry_is_blocked(tmp_path):
    """형식 재시도가 1회 상한에 막혀 작업이 결과 없이 끝나도 검사를 기록한다 (리뷰 LCR-04)."""
    provider = _BadShapeProvider()
    result = quality_pilot.run_pilot(tmp_path / "run", mode="offline", max_calls=1, effort="low",
                                    stop_after="chapter", provider=provider)
    assert provider.calls == 1 and result["provider_calls"] == 1 and result["blocked_calls"] == 1
    assert result["status"] == "completed"  # 호출이 나갔고 장 작업이 종결됐다. 판정은 calls[0]으로 한다
    assert result["checks"]["chapter_job_state"] == "failed"
    assert result["checks"]["ledger_effort_matches"] is True


def test_live_run_hides_claude_session_variables_and_reports_names_only(tmp_path, monkeypatch):
    """이 세션의 연결 변수만 CLI에 물려지지 않게 한다. 사용자가 둔 설정(CLAUDE_CONFIG_DIR 등)은 데스크톱 앱처럼 남긴다
    (리뷰 LCR-06, 코드 리뷰 LCC-03). 실행 동안 표준 오류 진단 스위치를 켜고 끝나면 되돌린다 (LCC-01)."""
    for name in list(os.environ):  # 개발자 환경의 다른 변수가 단언을 흔들지 않게 한다 (LCC-05)
        if name.startswith(("ANTHROPIC_", "CLAUDE")) and not name.startswith(quality_pilot._SESSION_ENV_PREFIXES):
            monkeypatch.delenv(name)
    monkeypatch.delenv(sub.ENV_STDERR_LOG, raising=False)
    monkeypatch.setenv("CLAUDE_CODE_CHILD_SESSION", "1")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "session-secret")
    monkeypatch.setenv("CLAUDE_EFFORT", "xhigh")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "config-dir")
    monkeypatch.setenv("ANTHROPIC_MODEL", "some-model")
    seen = {}

    class Recording(FakeClaudeConnection):
        def provider(self, model, *, effort=None):
            seen["env"] = {k for k in os.environ if k.startswith(("CLAUDE", "ANTHROPIC"))}
            seen["stderr_switch"] = os.environ.get(sub.ENV_STDERR_LOG)
            return super().provider(model, effort=effort)

    monkeypatch.setattr(quality_pilot, "ClaudeConnection", lambda: Recording({"sonnet": ["low"]}))
    result = quality_pilot.run_pilot(tmp_path / "run", mode="live", consent=True, max_calls=1, model="sonnet",
                                    effort="low", stop_after="chapter")
    assert not {"CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_SESSION_ID", "CLAUDE_EFFORT"} & seen["env"]
    assert "CLAUDE_CONFIG_DIR" in seen["env"] and seen["stderr_switch"] == "1"
    assert {"CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_SESSION_ID", "CLAUDE_EFFORT"} <= set(result["env_removed"])
    assert result["env_present_overrides"] == ["ANTHROPIC_MODEL", "CLAUDE_CONFIG_DIR"]
    assert os.environ["CLAUDE_EFFORT"] == "xhigh" and os.environ["CLAUDE_CODE_CHILD_SESSION"] == "1"
    assert sub.ENV_STDERR_LOG not in os.environ
    report = (tmp_path / "run" / "report.json").read_text(encoding="utf-8")
    assert "xhigh" not in report and "session-secret" not in report and "config-dir" not in report


def test_failure_while_closing_still_restores_environment_and_logging(tmp_path, monkeypatch):
    """연결을 닫다가 예외가 나도 환경 변수와 로그 처리기를 되돌린다. 시험 프로세스에서 다음 시험으로 상태가 새지 않는다 (LCC-02)."""
    root = logging.getLogger("slidecaptain")
    handlers, level = list(root.handlers), root.level
    monkeypatch.setenv("CLAUDE_CODE_CHILD_SESSION", "1")
    monkeypatch.delenv(sub.ENV_STDERR_LOG, raising=False)
    monkeypatch.delenv("SLIDECAPTAIN_CLAUDE_CLI", raising=False)

    class BrokenClose(FakeClaudeConnection):
        def close(self):
            raise RuntimeError("close failed")

    monkeypatch.setattr(quality_pilot, "ClaudeConnection", lambda: BrokenClose({"sonnet": ["low"]}))
    with pytest.raises(RuntimeError, match="close failed"):
        quality_pilot.run_pilot(tmp_path / "run", mode="live", consent=True, max_calls=1, model="sonnet",
                                stop_after="chapter", claude_cli=tmp_path / "claude.exe")
    assert os.environ["CLAUDE_CODE_CHILD_SESSION"] == "1"
    assert sub.ENV_STDERR_LOG not in os.environ and "SLIDECAPTAIN_CLAUDE_CLI" not in os.environ
    assert root.handlers == handlers and root.level == level


def test_live_report_has_provider_effort_and_catalog_resolved_model(tmp_path, monkeypatch):
    class Resolved(FakeClaudeConnection):
        def models(self):
            return [ModelOption(id="default", label="Default", resolved_model="claude-test-9", supported_efforts=["low"])]

        def provider(self, model, *, effort=None):
            made = super().provider(model, effort=effort)
            made.effort = effort
            return made

    monkeypatch.setattr(quality_pilot, "ClaudeConnection", lambda: Resolved({}))
    result = quality_pilot.run_pilot(tmp_path / "run", mode="live", consent=True, max_calls=1, model="default",
                                    effort="low", stop_after="chapter")
    assert result["provider_effort"] == "low"
    assert result["catalog_resolved_model"] == "claude-test-9"


def test_cli_flags_reach_the_pilot(tmp_path, monkeypatch):
    seen = {}

    def fake_run(output, **kwargs):
        seen.update(kwargs)
        return {"status": "completed", "stage": "done", "provider_calls": 0, "external_calls": 0}

    monkeypatch.setattr(quality_pilot, "run_pilot", fake_run)
    assert quality_pilot.main(["--output", str(tmp_path / "run"), "--offline", "--effort", "low",
                               "--stop-after", "chapter", "--claude-cli", str(tmp_path / "claude.exe")]) == 0
    assert seen["effort"] == "low" and seen["stop_after"] == "chapter"
    assert seen["claude_cli"] == tmp_path / "claude.exe"
