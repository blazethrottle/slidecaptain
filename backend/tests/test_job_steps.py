"""구조안 작업의 실행 단계 (개정판 D3b-4, 계획 4.8).

단계는 시간이 드는 경계다: connecting(AI 연결 확인: 임대 대기, 로그인 확인, 재비교), generating(첫 AI 호출),
retrying_format(형식 재시도 호출). 메모리에만 두고 원장 형식은 바꾸지 않는다. 진행 작업 응답과 작업 응답에
step, step_started_at, elapsed_seconds를 싣는다. 이 실행기가 돌리는 구조안 작업만 값이 있다. 실제 AI 호출은 없다.
"""

import asyncio
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

from fastapi.testclient import TestClient

from slidecaptain.pipeline.auth_status import LoginStatus
from slidecaptain.pipeline.provider import ProviderResponse
from slidecaptain.server.app import create_app
from test_jobs_api import HEADERS, STRUCTURE, _project, _register, _wait, manager  # noqa: F401 (픽스처)
from test_jobs_candidates import SLOTS, _two_chapters
from test_jobs_candidates import GateProvider as ChapterGate


class StepProvider:
    """호출마다 따로 멈추는 모의 제공자. 첫 응답은 형식이 맞지 않아 형식 재시도를 부른다."""

    def __init__(self, first_valid: bool = False):
        self.entered = [threading.Event(), threading.Event()]
        self.release = [threading.Event(), threading.Event()]
        self.calls = 0
        self.first_valid = first_valid

    async def complete(self, prompt, schema):
        index = self.calls
        self.calls += 1
        self.entered[index].set()
        while not self.release[index].is_set():
            await asyncio.sleep(0.01)
        if index == 0 and not self.first_valid:
            return ProviderResponse(structured={"wrong": True}, raw_text="형식 오류")
        return ProviderResponse(structured=STRUCTURE, raw_text="r")


def _active(client):
    return client.get("/api/jobs/active").json()["active"]


def test_steps_move_from_generating_to_retrying_format_and_clear_at_the_end(store):
    _project(store)
    provider = StepProvider()
    app = create_app(store, provider=provider, login_checker=lambda: LoginStatus(logged_in=False))
    with TestClient(app, headers=HEADERS) as client:
        job = _register(client).json()
        assert provider.entered[0].wait(5)
        first = _active(client)
        view = client.get(f"/api/projects/p1/jobs/{job['id']}").json()
        provider.release[0].set()
        assert provider.entered[1].wait(5)
        second = _active(client)
        provider.release[1].set()
        done = _wait(client, job["id"])
    assert first["step"] == "generating" and view["step"] == "generating"
    assert first["step_started_at"] and first["elapsed_seconds"] >= 0
    assert second["step"] == "retrying_format" and second["step_started_at"] >= first["step_started_at"]
    assert done["step"] is None and done["elapsed_seconds"] is None


def test_waiting_for_the_connection_is_the_connecting_step(store, manager):
    _project(store)
    entered, resume = threading.Event(), threading.Event()
    real_status = manager.connections["claude"].status

    def slow_status():
        entered.set()
        assert resume.wait(5)
        return real_status()

    manager.connections["claude"].status = slow_status
    with TestClient(create_app(store, ai_connections=manager), headers=HEADERS) as client:
        job = _register(client, headers={"X-AI-Selection": manager.selection_id}).json()
        assert entered.wait(5)
        active = _active(client)
        resume.set()
        _wait(client, job["id"])
    assert active["stage"] == "queued" and active["step"] == "connecting"


def test_cancel_requested_clears_the_step(store):
    _project(store)
    provider = StepProvider(first_valid=True)
    app = create_app(store, provider=provider, login_checker=lambda: LoginStatus(logged_in=False))
    with TestClient(app, headers=HEADERS) as client:
        job = _register(client).json()
        assert provider.entered[0].wait(5)
        client.post(f"/api/projects/p1/jobs/{job['id']}/cancel")
        active = _active(client)
        provider.release[0].set()
        _wait(client, job["id"])
    assert active is None or (active["stage"] == "cancel_requested" and active["step"] is None)


def test_other_kinds_have_no_step(store):
    _two_chapters(store)
    provider = ChapterGate(SLOTS)
    app = create_app(store, provider=provider, login_checker=lambda: LoginStatus(logged_in=False))
    with TestClient(app, headers=HEADERS) as client:
        job = client.post("/api/projects/p1/jobs", json={"request_id": "chapter-0001", "kind": "chapter",
                                                         "params": {"chapter_id": "c1"}}).json()
        assert provider.entered.wait(5)
        active = _active(client)
        provider.release.set()
        client.app.state.job_runner._handles[job["id"]].wait_sync(10)
    assert active["step"] is None and active["elapsed_seconds"] is not None


# -- 가짜 CLI: 호출 번호별 관문과 로그인 확인 지연 ----------------------------------------------

FAKE = Path(__file__).parent / "fakes" / "fake_claude_cli.py"


def test_fake_cli_gate_can_hold_each_call_separately(tmp_path):
    env = {**os.environ, "FAKE_CLAUDE_DIR": str(tmp_path / "rec"), "FAKE_CLAUDE_MODE": "gate",
           "FAKE_CLAUDE_GATE": str(tmp_path / "gate-{index}")}
    (tmp_path / "gate-0").write_text("go", encoding="utf-8")  # 첫 호출만 연다
    message = json.dumps({"type": "user", "message": {"role": "user", "content": "x"}}) + "\n"
    first = subprocess.run([sys.executable, str(FAKE)], input=message, capture_output=True, text=True,
                           env=env, timeout=20)
    assert '"type": "result"' in first.stdout
    second = subprocess.Popen([sys.executable, str(FAKE)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                              text=True, env=env)
    second.stdin.write(message)
    second.stdin.flush()
    try:
        second.wait(timeout=1.0)
        finished_early = True
    except subprocess.TimeoutExpired:
        finished_early = False
    (tmp_path / "gate-1").write_text("go", encoding="utf-8")
    second.stdin.close()
    out = second.stdout.read()
    second.wait(timeout=20)
    assert not finished_early and '"type": "result"' in out


def test_fake_cli_status_can_be_delayed(tmp_path):
    env = {**os.environ, "FAKE_CLAUDE_DIR": str(tmp_path / "rec"), "FAKE_CLAUDE_STATUS_DELAY": "0.6"}
    import time
    start = time.monotonic()
    out = subprocess.run([sys.executable, str(FAKE), "auth", "status"], capture_output=True, text=True,
                         env=env, timeout=20)
    assert time.monotonic() - start >= 0.6 and '"loggedIn": true' in out.stdout
