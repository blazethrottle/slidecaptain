"""실제 프로세스를 끊었다 다시 띄우는 관통 시험 (개정판 D2b-6, 계획서 6절 D2b-6, 8절 수용 기준).

다른 시험은 강제 종료 직후의 원장을 직접 만든다. 여기서는 데스크톱 서비스를 별도 프로세스로 띄워 장 생성 묶음을
등록하고, 장 처리의 세 지점에서 SIGKILL로 끊은 뒤 같은 폴더로 다시 띄운다. 가짜 Claude CLI를 쓰므로 실제 AI
호출은 없다. 끊는 지점은 5.7의 ①과 ② 사이(호출이 나간 뒤 응답 전), ②와 ③ 사이(결과를 원장에 쓴 뒤 적용 전),
④와 ⑤ 사이(적용 대상 ETag를 쓴 뒤 저장 전)다.
"""

import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from slidecaptain.storage.file_store import FileProjectStore
from tests.fakes import make_fake_cli

pytestmark = pytest.mark.skipif(os.name == "nt", reason="가짜 CLI 래퍼와 SIGKILL은 POSIX 전용 (Windows는 회사 PC 확인)")

HARNESS = Path(__file__).with_name("process_harness.py")
TOKEN = "a1" * 32  # 서비스가 요구하는 형식: 64자 16진수
SLOTS = {"template": "bullet_box", "bullets": [{"text": "합성 내용", "level": 0}], "conclusion": "결론", "footnote": ""}


class Service:
    def __init__(self, tmp: Path, data: Path, instance: str, pause_at: str = "", cli_mode: str = "respond"):
        self.paused = tmp / f"paused-{instance}"
        ui = tmp / "ui"
        ui.mkdir(exist_ok=True)
        (ui / "index.html").write_text("<!doctype html><title>시험</title>", encoding="utf-8")
        # 실행 식별자는 32자 16진수다. 재시작은 다른 실행이어야 조정이 돈다
        env = {**os.environ, "SLIDECAPTAIN_DESKTOP_SESSION": TOKEN,
               "SLIDECAPTAIN_DESKTOP_INSTANCE": instance.encode().hex().ljust(32, "0")[:32],
               "SLIDECAPTAIN_CLAUDE_CLI": str(make_fake_cli(tmp / "bin")), "FAKE_CLAUDE_DIR": str(tmp / "record"),
               "FAKE_CLAUDE_RESPONSES": str(tmp / "responses.json"), "FAKE_CLAUDE_MODE": cli_mode,
               "FAKE_CLAUDE_GATE": str(tmp / "never-opened-gate"), "HARNESS_PAUSE_AT": pause_at,
               "HARNESS_PAUSED": str(self.paused), "HARNESS_UI": str(ui)}
        self.process = subprocess.Popen([sys.executable, str(HARNESS), "--data-dir", str(data)], env=env,
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        ready = json.loads(self.process.stdout.readline())
        assert ready["event"] == "ready", ready
        self.origin = f"http://127.0.0.1:{ready['port']}"

    def request(self, method: str, path: str, body=None, headers=None):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.origin + path, data=data, method=method, headers={
            "X-SlideCaptain-Session": TOKEN, "X-Requested-With": "SlideCaptain", "Content-Type": "application/json",
            **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                return response.status, json.loads(response.read() or b"null")
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read() or b"null")

    def kill(self):
        self.process.send_signal(signal.SIGKILL)
        self.process.wait(10)

    def stop(self):
        if self.process.poll() is None:
            self.process.stdin.close()  # 부모 종료 신호(EOF)로 정상 종료
            self.process.wait(15)


def _wait(condition, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.05)
    raise AssertionError("기다린 상태가 오지 않았습니다")


def _calls(tmp: Path) -> int:
    log = tmp / "record" / "calls.log"
    return len(log.read_text(encoding="utf-8").splitlines()) if log.exists() else 0


@pytest.fixture
def project(tmp_path):
    data = tmp_path / "data"
    store = FileProjectStore(data)
    store.create_project("p1", "보고")
    store.write_source("p1", "리서치.md", "시장 규모는 500억 원이다")
    deck = store.load_deck("p1")
    deck = deck.model_validate({**deck.model_dump(mode="json"), "structure": {"chapters": [
        {"id": f"c{i}", "topic": f"주제 {i}", "conclusion": "결론", "template": "bullet_box",
         "source_refs": ["리서치.md"]} for i in (1, 2)]}})
    store.save_deck("p1", deck, snapshot=False)
    (tmp_path / "responses.json").write_text(json.dumps([SLOTS]), encoding="utf-8")
    return tmp_path, data, store


def _register(service: Service, store: FileProjectStore):
    status, settings = service.request("GET", "/api/ai/settings")
    assert status == 200, settings
    status, job = service.request("POST", "/api/projects/p1/jobs", {
        "request_id": "process-0001", "kind": "chapters", "params": {"chapter_ids": ["c1", "c2"]},
    }, {"If-Match": f'"{store.deck_etag("p1")}"', "X-AI-Consent": "SlideCaptain",
        "X-AI-Selection": settings["selection_id"]})
    assert status == 202, job
    return job["id"]


@pytest.mark.parametrize("point, expected_c1, calls_before, applied", [
    ("sent", "remote_completion_unknown", 1, False),   # ①과 ② 사이: 결과가 없어 완료 여부를 모른다
    ("apply", "succeeded", 1, True),                    # ②와 ③ 사이: 원장의 결과로 호출 없이 적용을 재개한다
    ("save", "succeeded", 1, True),                     # ④와 ⑤ 사이: 적용 대상만 기록됐고 저장 전이다
])
def test_killed_service_resumes_without_calling_again(project, point, expected_c1, calls_before, applied):
    tmp, data, store = project
    pause = {"sent": "", "apply": "apply", "save": "save"}[point]
    first = Service(tmp, data, "run-1", pause_at=pause, cli_mode="gate" if point == "sent" else "respond")
    try:
        job_id = _register(first, store)
        if point == "sent":
            _wait(lambda: _calls(tmp) == 1)  # 가짜 CLI가 요청을 받고 관문에서 기다린다
        else:
            _wait(first.paused.exists)
        first.kill()
    finally:
        if first.process.poll() is None:
            first.kill()
    assert _calls(tmp) == calls_before
    assert store.load_deck("p1").slides == []  # 끊긴 시점에는 저장되지 않았다

    second = Service(tmp, data, "run-2")
    try:
        status, view = second.request("GET", f"/api/projects/p1/jobs/{job_id}")
        assert status == 200, view
    finally:
        second.stop()
    states = [(c["chapter_id"], c["state"]) for c in view["chapters"]]
    assert states == [("c1", expected_c1), ("c2", "interrupted")]
    assert view["state"] not in ("queued", "running", "validating", "cancel_requested")
    assert _calls(tmp) == calls_before  # 재시작 뒤 다시 부르지 않았다
    slides = [s.chapter_id for s in store.load_deck("p1").slides]
    assert slides == (["c1"] if applied else [])
    if applied:
        assert view["chapters"][0]["candidate_status"] == "applied"
