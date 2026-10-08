"""작업 실행기와 작업 API (개정판 D2b-2, 계획서 2.3, 5.4~5.6, 5.9).

백그라운드 실행을 보는 시험은 `with TestClient`로 만들고, 고정 시간 대기 대신 실행기의 대기
(`wait_sync`)와 관문 제공자(threading.Event)를 쓴다. 실제 AI 호출은 없다.
"""

import asyncio
import json
import os
import threading
import time

import pytest
from fastapi.testclient import TestClient

from slidecaptain.pipeline.auth_status import LoginStatus
from slidecaptain.pipeline.connections import AIConnections, AISelection
from slidecaptain.pipeline.provider import ProviderResponse
from slidecaptain.server.app import create_app
from slidecaptain.storage.job_ledger import LEDGER_NAME, FixedInputs, JobLedger
from tests.test_ai_connections import FakeConnection

STRUCTURE = {"chapters": [{"topic": "표지", "conclusion": "", "template": "cover", "source_refs": []}]}
HEADERS = {"X-Requested-With": "SlideCaptain", "X-AI-Consent": "SlideCaptain"}


class GateProvider:
    """응답 전에 관문에서 멈추는 모의 제공자. 다른 스레드(작업 루프)에서 불려도 안전하다."""

    def __init__(self, on_cancel="raise"):
        self.entered, self.release = threading.Event(), threading.Event()
        self.calls = self.cancels = 0
        self.on_cancel = on_cancel  # raise(즉시), late(늦게 다시 던짐), value(값을 돌려줌)

    async def complete(self, prompt, schema):
        self.calls += 1
        self.entered.set()
        try:
            while not self.release.is_set():
                await asyncio.sleep(0.01)
        except asyncio.CancelledError:
            self.cancels += 1
            if self.on_cancel == "raise":
                raise
            while not self.release.is_set():  # 취소를 받은 뒤에도 정리가 늦는 제공자
                try:
                    await asyncio.sleep(0.01)
                except asyncio.CancelledError:
                    self.cancels += 1
            if self.on_cancel == "late":
                raise asyncio.CancelledError()
        return ProviderResponse(structured=STRUCTURE, raw_text="r")


def _project(store, name="p1"):
    store.create_project(name, "보고")
    store.write_source(name, "자료.md", "시장 규모는 500억 원이다")


def _runner(client):
    return client.app.state.job_runner


def _wait(client, job_id, timeout=10):
    handle = _runner(client)._handles[job_id]
    assert handle.wait_sync(timeout) is not None, "작업이 끝나지 않았습니다"
    return client.get(f"/api/projects/p1/jobs/{job_id}").json()


def _register(client, request_id="req-00000001", headers=None, **params):
    return client.post("/api/projects/p1/jobs", json={"request_id": request_id, "kind": "structure",
                                                      "params": params}, headers=headers or {})


@pytest.fixture
def manager(tmp_path):
    value = AIConnections(tmp_path / "settings.json", connections={
        "claude": FakeConnection("sonnet"), "chatgpt": FakeConnection("gpt-test")})
    yield value
    value.close()


# RED: 지금 코드는 생성 결과를 응답으로만 돌려주고 서버에 남기지 않는다

def test_job_api_generation_finishes_after_the_registering_request_and_keeps_the_result(store):
    _project(store)
    provider = GateProvider()
    with TestClient(create_app(store, provider=provider), headers=HEADERS) as client:
        registered = _register(client, target_chapters=1)
        assert registered.status_code == 202 and registered.json()["state"] in ("queued", "running")
        assert provider.entered.wait(5)
        provider.release.set()
        view = _wait(client, registered.json()["id"])
    assert view["state"] == "succeeded" and view["candidate_status"] == "held"
    assert view["result"]["structure"]["chapters"][0]["topic"] == "표지"
    assert view["stale_reasons"] == []


def test_wrapper_result_is_also_kept_in_the_ledger(store):
    _project(store)
    provider = GateProvider()
    provider.release.set()
    with TestClient(create_app(store, provider=provider), headers=HEADERS) as client:
        assert client.post("/api/projects/p1/generate/structure", json={}).status_code == 200
        [job] = client.get("/api/projects/p1/jobs").json()
    assert job["kind"] == "structure" and job["state"] == "succeeded" and job["result"]["status"] == "ok"


# 계약 시험

def test_second_registration_while_a_job_runs_is_rejected_with_its_summary(store):
    _project(store)
    _project(store, "p2")
    provider = GateProvider()
    with TestClient(create_app(store, provider=provider), headers=HEADERS) as client:
        first = _register(client).json()
        assert provider.entered.wait(5)
        other = client.post("/api/projects/p2/jobs", json={"request_id": "req-00000002", "kind": "structure",
                                                           "params": {}})
        assert other.status_code == 409
        body = other.json()
        assert body["code"] == "generation_active" and body["active"]["id"] == first["id"]
        assert client.get("/api/jobs/active").json()["active"]["project"] == "p1"
        same = _register(client)  # 같은 요청 ID는 병합한다
        assert same.status_code == 200 and same.json()["id"] == first["id"]
        provider.release.set()
        _wait(client, first["id"])
        assert client.get("/api/jobs/active").json()["active"] is None
    assert provider.calls == 1


def test_same_request_id_with_other_params_is_409(store):
    _project(store)
    provider = GateProvider()
    provider.release.set()
    with TestClient(create_app(store, provider=provider), headers=HEADERS) as client:
        first = _register(client, target_chapters=1).json()
        _wait(client, first["id"])
        again = _register(client, target_chapters=2)
    assert again.status_code == 409 and again.json()["code"] == "request_id_conflict"


def test_sources_changed_between_registration_and_start_makes_no_call(store, manager):
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
        store.write_source("p1", "자료.md", "바뀐 자료")
        resume.set()
        view = _wait(client, job["id"])
    assert view["state"] == "failed" and view["error"]["code"] == "sources_changed"
    assert view["error"]["error_class"] == "base_changed" and view["error"]["status"] == 409
    assert manager.connections["claude"].calls == []


def test_selection_changed_between_registration_and_start_does_not_rebind(store, manager):
    _project(store)
    entered, resume = threading.Event(), threading.Event()

    def slow_status():
        entered.set()
        assert resume.wait(5)
        return LoginStatus(logged_in=True, auth_method="subscription", account="ot***@example.com")

    manager.selected_status()  # 계정 정체성을 한 번 관측해 둔다
    manager.connections["claude"].status = slow_status
    with TestClient(create_app(store, ai_connections=manager), headers=HEADERS) as client:
        job = _register(client, headers={"X-AI-Selection": manager.selection_id}).json()
        assert entered.wait(5)
        resume.set()
        view = _wait(client, job["id"])
    assert view["state"] == "failed" and view["error"]["error_class"] == "connection"
    assert view["error"]["status"] == 409
    assert not any(c.calls for c in manager.connections.values())


@pytest.mark.parametrize("observed_before, status", [(False, 503), (True, 409)])
def test_expired_login_makes_no_call(store, manager, observed_before, status):
    # 계정 만료(계획서 사실 2): 처음 보는 로그아웃은 503, 이전에 로그인을 본 뒤의 만료는 정체성 변경 409
    _project(store)
    if observed_before:
        manager.selected_status()
    manager.connections["claude"].login = LoginStatus(logged_in=False)
    with TestClient(create_app(store, ai_connections=manager), headers=HEADERS) as client:
        response = client.post("/api/projects/p1/generate/structure", json={},
                               headers={"X-AI-Selection": manager.selection_id})
    assert response.status_code == status
    assert manager.connections["claude"].calls == []


@pytest.mark.parametrize("on_cancel, has_result", [("raise", False), ("late", False), ("value", True)])
def test_cancel_waits_for_the_provider_and_never_applies(store, on_cancel, has_result):
    # 취소 응답 지연(필수 RED 3의 세 형태): 제공자가 실제로 끝나기 전에는 cancel_requested다
    _project(store)
    provider = GateProvider(on_cancel=on_cancel)
    with TestClient(create_app(store, provider=provider), headers=HEADERS) as client:
        job = _register(client).json()
        assert provider.entered.wait(5)
        first = client.post(f"/api/projects/p1/jobs/{job['id']}/cancel").json()
        if on_cancel != "raise":
            assert first["state"] == "cancel_requested"
            client.post(f"/api/projects/p1/jobs/{job['id']}/cancel")  # 두 번째 요청은 아무것도 보내지 않는다
            assert client.get(f"/api/projects/p1/jobs/{job['id']}").json()["state"] == "cancel_requested"
            provider.release.set()
        view = _wait(client, job["id"])
    assert view["state"] == "cancelled" and view["error"]["error_class"] == "cancelled"
    assert (view["result"] is not None) == has_result
    assert provider.cancels == 1
    deck = store.load_deck("p1")
    assert deck.structure.chapters == []


def test_double_cancel_request_releases_the_lease(store, manager, monkeypatch):
    _project(store)
    provider = GateProvider(on_cancel="late")
    monkeypatch.setattr(manager.connections["claude"], "provider", lambda _: provider)
    with TestClient(create_app(store, ai_connections=manager), headers=HEADERS) as client:
        job = _register(client, headers={"X-AI-Selection": manager.selection_id}).json()
        assert provider.entered.wait(5)
        for _ in range(3):
            client.post(f"/api/projects/p1/jobs/{job['id']}/cancel")
        provider.release.set()
        _wait(client, job["id"])
    assert provider.cancels == 1
    manager.select(AISelection(provider="chatgpt", model="gpt-test"))  # 임대가 남았으면 409


def test_shutdown_marks_a_running_job_and_a_late_answer_does_not_overwrite(store):
    _project(store)
    provider = GateProvider(on_cancel="value")
    app = create_app(store, provider=provider)
    with TestClient(app, headers=HEADERS) as client:
        job = _register(client).json()
        assert provider.entered.wait(5)
        _runner(client).shutdown(wait_seconds=0.2)  # 제공자가 취소 뒤에도 끝나지 않는다
        assert client.post("/api/projects/p1/jobs", json={"request_id": "req-00000009", "kind": "structure",
                                                          "params": {}}).json()["code"] == "service_stopping"
        assert client.get(f"/api/projects/p1/jobs/{job['id']}").json()["state"] == "remote_completion_unknown"
        provider.release.set()
        handle = _runner(client)._handles[job["id"]]
        handle.wait_sync(5)
        view = client.get(f"/api/projects/p1/jobs/{job['id']}").json()
    assert view["state"] == "remote_completion_unknown" and view["result"] is None


def _left_over(store, state_path, remote=False):
    ledger = JobLedger.open(store.root)
    job, _ = ledger.create_job(project="p1", kind="structure", request_id="old-00000001", params={},
                               instance_id="previous", inputs=FixedInputs(None, None, None, None, None, None))
    for before, after in zip(state_path, state_path[1:]):
        extra = {"remote_sent_at": "t"} if remote and after == "running" else {}
        ledger.transition(job.id, expected=before, new=after, **extra)
    ledger.close()
    return job.id


@pytest.mark.parametrize("lock, expected", [("held", "remote_completion_unknown"), ("unsupported", "running"),
                                            ("none", "running")])
def test_restart_reconciles_other_instances_only_with_the_lock(store, lock, expected):
    _project(store)
    job_id = _left_over(store, ["queued", "running"], remote=True)
    with TestClient(create_app(store, provider=GateProvider(), data_dir_lock=lock), headers=HEADERS) as client:
        view = client.get(f"/api/projects/p1/jobs/{job_id}").json()
        assert view["state"] == expected
        assert view["owner"] == "other_instance"
        # 다른 실행의 미종결 행은 409 판정에 쓰지 않는다
        assert client.get("/api/jobs/active").json()["active"] is None


def test_unreadable_ledger_blocks_only_generation(store):
    _project(store)
    (store.root / LEDGER_NAME).write_bytes(b"broken" * 50)
    with TestClient(create_app(store, provider=GateProvider()), headers=HEADERS) as client:
        deck = client.get("/api/projects/p1/deck")
        saved = client.put("/api/projects/p1/deck", json=deck.json(), headers={"If-Match": deck.headers["etag"]})
        assert saved.status_code == 200
        blocked = client.post("/api/projects/p1/generate/structure", json={})
        assert blocked.status_code == 503 and blocked.json()["code"] == "job_ledger_unavailable"
        assert client.get("/api/projects/p1/progress").json()["jobs"] is None


def test_candidate_disposition(store):
    _project(store)
    provider = GateProvider()
    provider.release.set()
    with TestClient(create_app(store, provider=provider), headers=HEADERS) as client:
        job = _register(client).json()
        _wait(client, job["id"])
        settled = client.post(f"/api/projects/p1/jobs/{job['id']}/candidate", json={"action": "dismissed"})
        assert settled.json()["candidate_status"] == "dismissed"
        again = client.post(f"/api/projects/p1/jobs/{job['id']}/candidate", json={"action": "applied"})
    assert again.status_code == 409


def test_stale_reasons_after_the_deck_changes(store):
    _project(store)
    provider = GateProvider()
    provider.release.set()
    with TestClient(create_app(store, provider=provider), headers=HEADERS) as client:
        job = _register(client).json()
        _wait(client, job["id"])
        deck = client.get("/api/projects/p1/deck")
        body = deck.json()
        body["meta"]["title"] = "바뀐 제목"
        client.put("/api/projects/p1/deck", json=body, headers={"If-Match": deck.headers["etag"]})
        view = client.get(f"/api/projects/p1/jobs/{job['id']}").json()
        progress = client.get("/api/projects/p1/progress").json()
    assert view["stale_reasons"] == ["deck_changed"] and view["current_etag"] != view["base_etag"]
    assert [j["id"] for j in progress["jobs"]] == [job["id"]]


def test_record_success_uses_the_fixed_model(store, manager):
    # 고정: 지금도 임대 중에는 선택을 바꿀 수 없어 시작 때 모델로 기록된다
    _project(store)
    with TestClient(create_app(store, ai_connections=manager), headers=HEADERS) as client:
        assert client.post("/api/projects/p1/generate/structure", json={},
                           headers={"X-AI-Selection": manager.selection_id}).status_code == 200
        manager.select(AISelection(provider="chatgpt", model="gpt-test"))
        manager.select(AISelection(provider="claude", model="sonnet"))
        assert client.get("/api/status").json()["last_generation_at"] is not None


def test_settings_busy_while_a_job_runs(store, manager, monkeypatch):
    _project(store)
    provider = GateProvider()
    monkeypatch.setattr(manager.connections["claude"], "provider", lambda _: provider)
    with TestClient(create_app(store, ai_connections=manager), headers=HEADERS) as client:
        job = _register(client, headers={"X-AI-Selection": manager.selection_id}).json()
        assert provider.entered.wait(5)
        assert client.get("/api/ai/settings").json()["busy"] is True
        provider.release.set()
        _wait(client, job["id"])
        assert client.get("/api/ai/settings").json()["busy"] is False


# Claude 취소 확인 (계획서 가정 1): 실제 SubscriptionProvider와 stdin을 읽지 않는 가짜 CLI

def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    state = os.popen(f"ps -o stat= -p {pid}").read().strip()
    return bool(state) and not state.startswith("Z")


@pytest.mark.skipif(os.name == "nt", reason="가짜 CLI 래퍼는 POSIX 전용 (D2b-6에서 Windows 형태 결정)")
@pytest.mark.parametrize("case", ["cancel_once", "cancel_repeated", "cancel_then_shutdown"])
def test_claude_cli_process_is_cleaned_up_after_cancel(store, manager, monkeypatch, tmp_path, case):
    from slidecaptain.pipeline.subscription import SubscriptionProvider
    from tests.fakes import make_fake_cli

    record = tmp_path / "record"
    monkeypatch.setenv("SLIDECAPTAIN_CLAUDE_CLI", str(make_fake_cli(tmp_path / "bin")))
    monkeypatch.setenv("FAKE_CLAUDE_DIR", str(record))
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "hang")
    monkeypatch.setattr(manager.connections["claude"], "provider",
                        lambda model: SubscriptionProvider(model=model, timeout_s=300))
    _project(store)
    with TestClient(create_app(store, ai_connections=manager), headers=HEADERS) as client:
        job = _register(client, headers={"X-AI-Selection": manager.selection_id}).json()
        deadline = time.monotonic() + 15
        while not (record / "pids.log").exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        pid = int((record / "pids.log").read_text().split()[0])
        client.post(f"/api/projects/p1/jobs/{job['id']}/cancel")
        if case == "cancel_repeated":
            for _ in range(3):
                client.post(f"/api/projects/p1/jobs/{job['id']}/cancel")
        if case == "cancel_then_shutdown":
            _runner(client).shutdown(wait_seconds=0.2)
        handle = _runner(client)._handles[job["id"]]
        assert handle.wait_sync(20) is not None
        state = client.get(f"/api/projects/p1/jobs/{job['id']}").json()["state"]
    deadline = time.monotonic() + 20
    while _alive(pid) and time.monotonic() < deadline:
        time.sleep(0.2)
    assert not _alive(pid)
    # 종료 처리가 먼저 행을 정리하면 완료 여부 불명이고, 아니면 취소로 끝난다
    assert state == ("remote_completion_unknown" if case == "cancel_then_shutdown" else "cancelled")
