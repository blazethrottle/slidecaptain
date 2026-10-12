"""구조안 작업의 실행 단계 (개정판 D3b-4, 계획 4.8).

단계는 시간이 드는 경계다: connecting(AI 연결 확인: 임대 대기, 로그인 확인, 재비교), generating(첫 AI 호출),
retrying_format(형식 재시도 호출). 메모리에만 두고 원장 형식은 바꾸지 않는다. 진행 작업 응답과 작업 응답에
step, step_started_at, elapsed_seconds를 싣는다. 단계는 이 실행기가 돌리는 끝나지 않은 구조안 작업만 있고, 경과 초는
이 실행기가 돌리는 끝나지 않은 모든 작업에 있다. 실제 AI 호출은 없다. 가짜 CLI와 웹 모드 서비스를 함께 거치는
확인은 D3b-8의 화면 확인에서 한다(D3b-4 리뷰 R6).
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
from fastapi.testclient import TestClient

from slidecaptain.pipeline.auth_status import LoginStatus
from slidecaptain.pipeline.provider import ProviderResponse
from slidecaptain.pipeline.service import GenerationService
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


class CancelHoldingProvider(StepProvider):
    """취소를 받아도 관문이 열릴 때까지 끝나지 않는 제공자. 취소 요청 중의 응답을 관측한다 (D3b-4 리뷰 R1)."""

    def __init__(self):
        super().__init__(first_valid=True)
        self.cancelled, self.hold = threading.Event(), threading.Event()

    async def complete(self, prompt, schema):
        try:
            return await super().complete(prompt, schema)
        except asyncio.CancelledError:
            self.cancelled.set()
            while not self.hold.is_set():
                try:
                    await asyncio.sleep(0.01)
                except asyncio.CancelledError:
                    pass
            raise


def _assert_cancel_bodies(active, view):
    assert active["stage"] == "cancel_requested" and active["cancel_requested"] is True
    for body in (active, view):
        assert body["step"] is None and body["step_started_at"] is None and body["elapsed_seconds"] is not None


def test_cancel_requested_clears_the_step_while_the_call_winds_down(store):
    _project(store)
    provider = CancelHoldingProvider()
    app = create_app(store, provider=provider, login_checker=lambda: LoginStatus(logged_in=False))
    with TestClient(app, headers=HEADERS) as client:
        job = _register(client).json()
        try:
            assert provider.entered[0].wait(5)
            client.post(f"/api/projects/p1/jobs/{job['id']}/cancel")
            assert provider.cancelled.wait(5)
            active = _active(client)
            view = client.get(f"/api/projects/p1/jobs/{job['id']}").json()
        finally:
            provider.hold.set()
            provider.release[0].set()
        _wait(client, job["id"])
    _assert_cancel_bodies(active, view)
    assert view["state"] == "cancel_requested"


def test_cancel_while_connecting_clears_the_step(store, manager):
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
        try:
            assert entered.wait(5)
            client.post(f"/api/projects/p1/jobs/{job['id']}/cancel")
            active = _active(client)
            view = client.get(f"/api/projects/p1/jobs/{job['id']}").json()
        finally:
            resume.set()
        done = _wait(client, job["id"])
    _assert_cancel_bodies(active, view)
    assert done["state"] == "cancelled"


def test_each_step_has_its_own_start_time(store, manager, monkeypatch):
    """단계가 바뀔 때마다 시작 시각도 바뀐다 (D3b-4 리뷰 R2). Windows의 시계 해상도를 넘도록 단계 사이에 기다린다."""
    _project(store)
    provider = StepProvider()
    monkeypatch.setattr(manager.connections["claude"], "provider", lambda model: provider)
    entered, resume = threading.Event(), threading.Event()
    real_status = manager.connections["claude"].status

    def slow_status():
        entered.set()
        assert resume.wait(5)
        return real_status()

    manager.connections["claude"].status = slow_status
    with TestClient(create_app(store, ai_connections=manager), headers=HEADERS) as client:
        job = _register(client, headers={"X-AI-Selection": manager.selection_id}).json()
        try:
            assert entered.wait(5)
            connecting = _active(client)
            time.sleep(0.05)
            resume.set()
            assert provider.entered[0].wait(5)
            generating = _active(client)
            time.sleep(0.05)
            provider.release[0].set()
            assert provider.entered[1].wait(5)
            retrying = _active(client)
        finally:
            resume.set()
            provider.release[0].set()
            provider.release[1].set()
        _wait(client, job["id"])
    assert [connecting["step"], generating["step"], retrying["step"]] == ["connecting", "generating", "retrying_format"]
    assert connecting["step_started_at"] < generating["step_started_at"] < retrying["step_started_at"]


def _until(read, check, timeout=5.0):
    deadline = time.monotonic() + timeout
    value = read()
    while not check(value) and time.monotonic() < deadline:
        time.sleep(0.02)
        value = read()
    return value


def test_a_settled_job_has_no_step_while_the_lease_is_released(store, manager, monkeypatch):
    """원장이 종결된 뒤 임대 반납이 연결 잠금을 기다리는 동안에도 단계 칸을 싣지 않는다 (D3b-4 리뷰 R3).
    설정 조회가 로그인 확인을 하는 동안 작업이 끝나는 경우와 같다."""
    _project(store)
    provider = StepProvider()
    monkeypatch.setattr(manager.connections["claude"], "provider", lambda model: provider)
    with TestClient(create_app(store, ai_connections=manager), headers=HEADERS) as client:
        job = _register(client, headers={"X-AI-Selection": manager.selection_id}).json()
        url = f"/api/projects/p1/jobs/{job['id']}"
        assert provider.entered[0].wait(5)
        provider.release[0].set()
        assert provider.entered[1].wait(5)
        manager._lock.acquire()  # 임대 반납(release)이 이 잠금을 기다린다
        try:
            provider.release[1].set()
            view = _until(lambda: client.get(url).json(), lambda v: v["state"] == "succeeded")
            active = _until(lambda: _active(client), lambda a: a is None or a["step"] is None)
            handle_open = not client.app.state.job_runner._handles[job["id"]].done
        finally:
            manager._lock.release()
        _wait(client, job["id"])
    assert handle_open  # 반납 전의 창을 실제로 관측했다
    assert view["state"] == "succeeded" and view["step"] is None
    assert view["step_started_at"] is None and view["elapsed_seconds"] is None
    assert active is not None and active["step"] is None and active["elapsed_seconds"] is None


@pytest.mark.parametrize("first_valid", [True, False])
def test_structure_jobs_call_generate_then_at_most_one_format_retry(store, monkeypatch, first_valid):
    """단계 이름은 호출 번호로 정한다. 구조안 생성의 호출 목적 순서가 이와 같음을 고정한다 (D3b-4 리뷰 R5)."""
    purposes = []
    original = GenerationService._complete

    async def recording(self, prompt, schema, purpose, collector):
        purposes.append(purpose)
        return await original(self, prompt, schema, purpose, collector)

    monkeypatch.setattr(GenerationService, "_complete", recording)
    _project(store)
    provider = StepProvider(first_valid=first_valid)
    for event in provider.release:
        event.set()
    app = create_app(store, provider=provider, login_checker=lambda: LoginStatus(logged_in=False))
    with TestClient(app, headers=HEADERS) as client:
        job = _register(client).json()
        _wait(client, job["id"])
    assert purposes == (["generate"] if first_valid else ["generate", "format_retry"])


def test_the_sync_structure_route_records_the_same_steps(store):
    """동기 래퍼(POST /generate/structure)도 같은 실행기로 단계를 남긴다 (계획 리뷰 V11, D3b-4 리뷰 R6)."""
    _project(store)
    provider = StepProvider()
    app = create_app(store, provider=provider, login_checker=lambda: LoginStatus(logged_in=False))
    result = {}
    with TestClient(app, headers=HEADERS) as client:
        thread = threading.Thread(
            target=lambda: result.setdefault("response", client.post("/api/projects/p1/generate/structure", json={})))
        thread.start()
        try:
            assert provider.entered[0].wait(5)
            first = _active(client)
            provider.release[0].set()
            assert provider.entered[1].wait(5)
            second = _active(client)
        finally:
            provider.release[0].set()
            provider.release[1].set()
            thread.join(10)
    assert first["step"] == "generating" and second["step"] == "retrying_format"
    assert result["response"].status_code == 200 and result["response"].json()["format_retried"] is True


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
