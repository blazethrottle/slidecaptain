"""가짜 Claude CLI가 실제 앱 코드와 SDK 0.2.145에서 동작하는지 고정한다 (개정판 D2b-2).

SDK 버전이 바뀌면 stream-json 규약이 달라질 수 있으므로 버전을 단언한다. 실제 AI 호출은 없다.
"""

import asyncio
import json
import os
import time

import claude_agent_sdk
import pytest

from slidecaptain.pipeline.auth_status import check_login
from slidecaptain.pipeline.subscription import SubscriptionProvider
from tests.fakes import make_fake_cli

pytestmark = pytest.mark.skipif(os.name == "nt", reason="가짜 CLI 래퍼는 POSIX 전용 (D2b-6에서 Windows 형태 결정)")


@pytest.fixture
def fake(tmp_path, monkeypatch):
    cli = make_fake_cli(tmp_path / "bin")
    record = tmp_path / "record"
    responses = tmp_path / "responses.json"
    responses.write_text(json.dumps([{"answer": 1}, {"answer": 2}]), encoding="utf-8")
    monkeypatch.setenv("SLIDECAPTAIN_CLAUDE_CLI", str(cli))
    monkeypatch.setenv("FAKE_CLAUDE_DIR", str(record))
    monkeypatch.setenv("FAKE_CLAUDE_RESPONSES", str(responses))
    return record


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    state = os.popen(f"ps -o stat= -p {pid}").read().strip()
    return bool(state) and not state.startswith("Z")


def test_sdk_version_is_the_one_the_fake_follows():
    assert claude_agent_sdk.__version__ == "0.2.145"


def test_login_status_reads_the_fake(fake):
    status = check_login()
    assert (status.logged_in, status.auth_method) == (True, "claude.ai")


def test_logged_out_mode(fake, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_LOGGED_IN", "0")
    assert check_login().logged_in is False


def test_provider_receives_structured_output_and_calls_are_recorded(fake):
    async def run():
        provider = SubscriptionProvider(model="sonnet", timeout_s=30)
        first = await provider.complete("x", {"type": "object"})
        second = await provider.complete("y", {"type": "object"})
        return first, second

    first, second = asyncio.run(run())
    assert (first.structured, second.structured) == ({"answer": 1}, {"answer": 2})
    assert first.usage is not None and first.usage.model == "claude-fake-model"
    assert len((fake / "calls.log").read_text().splitlines()) == 2


def test_gate_mode_waits_for_the_gate_file(fake, monkeypatch, tmp_path):
    gate = tmp_path / "gate"
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "gate")
    monkeypatch.setenv("FAKE_CLAUDE_GATE", str(gate))

    async def run():
        task = asyncio.create_task(SubscriptionProvider(model="sonnet", timeout_s=30).complete("x", {}))
        for _ in range(500):
            if (fake / "calls.log").exists():
                break
            await asyncio.sleep(0.02)
        assert not task.done()
        gate.touch()
        return await task

    assert asyncio.run(run()).structured == {"answer": 1}


def test_hang_mode_process_is_cleaned_up_by_one_cancel(fake, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "hang")

    async def run():
        task = asyncio.create_task(SubscriptionProvider(model="sonnet", timeout_s=300).complete("x", {}))
        for _ in range(500):
            if (fake / "pids.log").exists():
                break
            await asyncio.sleep(0.02)
        pid = int((fake / "pids.log").read_text().split()[0])
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return pid

    pid = asyncio.run(run())
    deadline = time.monotonic() + 20
    while _alive(pid) and time.monotonic() < deadline:
        time.sleep(0.2)
    assert not _alive(pid)


# -- D3a-4: 오류 모드와 Claude 연결의 원인 코드 ---------------------------------------------------

@pytest.mark.parametrize("mode, api_status, code", [
    ("error", None, "provider_call_failed"),   # 오류 결과: 미로그인과 한도를 가를 수 없다
    ("error", "429", "provider_limit"),        # HTTP 표준 상태 429만 한도 초과로 가른다
    ("exit", None, "provider_call_failed"),    # 결과 없이 끝난 CLI(ProcessError): 로그인과 한도가 한 자리로 온다
])
def test_claude_failures_carry_the_raise_site_code(fake, monkeypatch, mode, api_status, code):
    from slidecaptain.pipeline.provider import ProviderCallFailed

    monkeypatch.setenv("FAKE_CLAUDE_MODE", mode)
    if api_status:
        monkeypatch.setenv("FAKE_CLAUDE_API_STATUS", api_status)
    with pytest.raises(ProviderCallFailed) as info:
        asyncio.run(SubscriptionProvider(model="sonnet", timeout_s=30).complete("x", {}))
    assert info.value.code == code


def test_missing_claude_cli_is_provider_missing(fake, monkeypatch, tmp_path):
    from slidecaptain.pipeline.provider import ProviderNotAvailable

    monkeypatch.setenv("SLIDECAPTAIN_CLAUDE_CLI", str(tmp_path / "no-such-cli"))
    with pytest.raises(ProviderNotAvailable) as info:
        asyncio.run(SubscriptionProvider(model="sonnet", timeout_s=30).complete("x", {}))
    assert info.value.code == "provider_missing"
