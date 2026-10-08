"""실제 프로세스를 끊었다 다시 띄우는 관통 시험 (개정판 D2b-6, 계획서 6절 D2b-6, 8절 수용 기준).

다른 시험은 강제 종료 직후의 원장을 직접 만든다. 여기서는 데스크톱 서비스를 별도 프로세스로 띄워 장 생성 묶음을
등록하고, 장 처리의 세 지점에서 SIGKILL로 끊은 뒤 같은 폴더로 다시 띄운다. 가짜 Claude CLI를 쓰므로 실제 AI
호출은 없다. 끊는 지점은 5.7의 ①과 ② 사이(호출이 나간 뒤 응답 전), ②와 ③ 사이(결과를 원장에 쓴 뒤 적용 전),
④와 ⑤ 사이(적용 대상 ETag를 쓴 뒤 저장 전)다.
"""

import json
import os
import select
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from slidecaptain.storage.file_store import FileProjectStore
from slidecaptain.storage.job_ledger import JobLedger
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
        self.stderr = tmp / f"stderr-{instance}.log"
        self.process = subprocess.Popen([sys.executable, str(HARNESS), "--data-dir", str(data)], env=env,
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.stderr.open("wb"))
        # 준비 신호를 30초까지 기다린다. 못 받으면 프로세스를 끊고 오류 출력을 붙인다 (D2b-6 리뷰 R19)
        line = self.process.stdout.readline() if select.select([self.process.stdout], [], [], 30)[0] else b""
        if not line:
            self.process.kill()
            self.process.wait(10)
            raise AssertionError("서비스가 준비되지 않았습니다: " + self.stderr.read_text(errors="replace")[-2000:])
        ready = json.loads(line)
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


BAD = {"template": "bullet_box"}  # 형식 오류: 재시도 1회까지 같은 응답이면 그 장은 실패로 끝난다


def _orphans(tmp: Path) -> list[int]:
    """끝난 뒤에도 살아 있는 가짜 CLI 프로세스 (D2b-6 리뷰 R1)."""
    log = tmp / "record" / "pids.log"
    alive = []
    for pid in (int(x) for x in log.read_text(encoding="utf-8").split()) if log.exists() else []:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            continue
        state = os.popen(f"ps -o stat= -p {pid}").read().strip()
        if state and not state.startswith("Z"):
            alive.append(pid)
    return alive


# (끊는 지점, 응답 목록, 재시작 뒤 장 상태, 끊기 전 호출 수, 덱에 적용된 장)
CASES = [
    ("sent", [SLOTS], ["remote_completion_unknown", "interrupted"], 1, []),   # ①과 ② 사이: 결과가 없어 완료 여부를 모른다
    ("apply", [SLOTS], ["succeeded", "interrupted"], 1, ["c1"]),            # ②와 ③ 사이: 원장의 결과로 적용을 재개한다
    ("save", [SLOTS], ["succeeded", "interrupted"], 1, ["c1"]),             # ④와 ⑤ 사이: 적용 대상만 기록됐고 저장 전이다
    ("saved", [SLOTS], ["succeeded", "interrupted"], 1, ["c1"]),            # ⑤와 ⑥ 사이: 저장은 됐고 성공 기록 전이다 (R7)
    # 첫 장은 형식 오류로 실패하고, 둘째 장의 적용 전에 끊긴다: 실패, 적용, 중단을 원장과 덱에서 구분한다 (R10)
    ("apply", [BAD, BAD, SLOTS], ["failed", "succeeded"], 3, ["c2"]),
]


@pytest.mark.parametrize("point, answers, expected, calls_before, applied", CASES)
def test_killed_service_resumes_without_calling_again(project, point, answers, expected, calls_before, applied):
    tmp, data, store = project
    (tmp / "responses.json").write_text(json.dumps(answers), encoding="utf-8")
    pause = "" if point == "sent" else point
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
    before = [s.chapter_id for s in store.load_deck("p1").slides]
    assert before == (["c1"] if point == "saved" else [])  # ⑤ 뒤에 끊긴 경우만 저장이 끝나 있다
    etag_before = store.deck_etag("p1")

    second = Service(tmp, data, "run-2")
    try:
        status, view = second.request("GET", f"/api/projects/p1/jobs/{job_id}")
        assert status == 200, view
    finally:
        second.stop()
    assert [c["state"] for c in view["chapters"]] == expected
    # 부모는 결과를 계산해 종결하고(R8), 사유 없이 중단된 남은 장은 코드가 없다
    assert view["state"] == "failed" and view["outcome"] == "partial"
    for chapter in view["chapters"]:
        if chapter["state"] == "interrupted":
            assert chapter["error"] is None or chapter["error"]["code"] is None
        if chapter["state"] == "failed":
            assert chapter["error"]["error_class"] == "ai_output"
    assert _calls(tmp) == calls_before  # 재시작 뒤 다시 부르지 않았다
    slides = [s.chapter_id for s in store.load_deck("p1").slides]
    assert slides == applied
    rows = {c.chapter_id: c for c in JobLedger.open(data).chapters(job_id)}
    for chapter_id in applied:
        assert rows[chapter_id].candidate_status == "applied"
        assert rows[chapter_id].applied_etag == store.deck_etag("p1")  # 적용 결과 ETag가 지금 덱과 같다 (R9)
    if point == "saved":
        assert store.deck_etag("p1") == etag_before  # 저장을 다시 하지 않았다
    _wait(lambda: not _orphans(tmp), timeout=5)  # 서비스를 끊어도 가짜 CLI가 남지 않는다 (R1)
