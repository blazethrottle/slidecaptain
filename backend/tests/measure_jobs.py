"""작업 원장의 실측 (개정판 D2b-6, 계획서 7절 가정 4, D2b-4 리뷰 R15). pytest가 모으지 않는 실행 스크립트다.

실행: `.venv/bin/python tests/measure_jobs.py <결과 JSON 경로>`. 가짜 Claude CLI를 쓰므로 실제 AI 호출은 없다.

재는 것
1. 장당 원장 쓰기 시간: 같은 프로세스에서 5장 묶음을 돌리며 원장 쓰기 메서드 3종(전이, 장 전이, 장 갱신)의 합을
   잰다. 작업 루프 스레드(slidecaptain-jobs) 위의 쓰기와 작업 스레드 쓰기를 나눠 적는다 (D2b-6 리뷰 R11)
2. 조회 응답 시간: 별도 프로세스 서비스에 진행 중 작업, 종결 작업, 목록 조회를 30번씩 보내 잰다(R12)
3. 취소 응답: 가짜 CLI가 요청을 받은 것을 확인한 뒤 취소를 요청해, 취소 라우트의 응답 시간과 종결까지의 시간을
   3번 잰다. 가짜 CLI가 뜨기 전의 취소는 다른 구간이라 따로 적는다 (R2)
4. 원장 크기: 묶음 뒤 원장 파일 크기와 가장 큰 결과 JSON의 길이
"""

import json
import sqlite3
import statistics
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from slidecaptain.server.app import create_app  # noqa: E402
from slidecaptain.storage.file_store import FileProjectStore  # noqa: E402
from slidecaptain.storage.job_ledger import JobLedger  # noqa: E402
from tests.test_jobs_batch import HEADERS, ChapterProvider, _project, _register, _wait, slots  # noqa: E402
from tests.test_process_restart import SLOTS, Service  # noqa: E402


def _ledger_size(data: Path) -> dict:
    ledger_file = data / ".slidecaptain-jobs.sqlite3"
    with sqlite3.connect(ledger_file) as conn:
        rows = [len(r[0] or "") for r in conn.execute("SELECT result FROM job_chapters UNION ALL SELECT result FROM jobs")]
    return {"ledger_bytes": ledger_file.stat().st_size, "largest_result_json_chars": max(rows + [0])}


def _ms(values):
    return {"n": len(values), "median_ms": round(statistics.median(values) * 1000, 2),
            "max_ms": round(max(values) * 1000, 2)}


def ledger_writes(tmp: Path) -> dict:
    store = FileProjectStore(tmp / "data-ledger")
    _project(store, count=5)
    durations: list[tuple[str, float]] = []
    originals = {name: getattr(JobLedger, name) for name in ("transition_chapter", "update_chapter", "transition")}

    def timed(name):
        def call(self, *args, **kwargs):
            started = time.perf_counter()
            try:
                return originals[name](self, *args, **kwargs)
            finally:
                durations.append((threading.current_thread().name, time.perf_counter() - started))
        return call
    for name in originals:
        setattr(JobLedger, name, timed(name))
    try:
        provider = ChapterProvider([slots(f"장 {i}") for i in range(5)])
        with TestClient(create_app(store, provider=provider), headers=HEADERS) as client:
            durations.clear()
            started = time.perf_counter()
            view = _wait(client, _register(client, store, [f"c{i}" for i in range(1, 6)]).json()["id"])
            elapsed = time.perf_counter() - started
    finally:
        for name, original in originals.items():
            setattr(JobLedger, name, original)
    assert view["state"] == "succeeded", view["state"]
    on_loop = [d for name, d in durations if name == "slidecaptain-jobs"]
    elsewhere = [d for name, d in durations if name != "slidecaptain-jobs"]
    return {**_ledger_size(store.root), "chapters": 5, "ledger_write_calls": len(durations),
            "per_write": _ms([d for _, d in durations]),
            "job_loop_writes": len(on_loop), "job_loop_ms_per_chapter": round(sum(on_loop) / 5 * 1000, 2),
            "worker_thread_writes": len(elsewhere), "worker_thread_ms_per_chapter": round(sum(elsewhere) / 5 * 1000, 2),
            "ledger_ms_per_chapter": round(sum(d for _, d in durations) / 5 * 1000, 2),
            "batch_total_ms": round(elapsed * 1000, 1)}


def _poll(service: Service, path: str, times: int = 30) -> dict:
    durations = []
    for _ in range(times):
        started = time.perf_counter()
        status, _ = service.request("GET", path)
        durations.append(time.perf_counter() - started)
        assert status == 200, (path, status)
    return _ms(durations)


def _register_batch(service: Service, store: FileProjectStore, request_id: str) -> str:
    status, settings = service.request("GET", "/api/ai/settings")
    status, job = service.request("POST", "/api/projects/p1/jobs", {
        "request_id": request_id, "kind": "chapters", "params": {"chapter_ids": ["c1", "c2", "c3"]},
    }, {"If-Match": f'"{store.deck_etag("p1")}"', "X-AI-Consent": "SlideCaptain",
        "X-AI-Selection": settings["selection_id"]})
    assert status == 202, job
    return job["id"]


def _cancel(service: Service, job_id: str) -> tuple[float, float, str]:
    started = time.perf_counter()
    status, _ = service.request("POST", f"/api/projects/p1/jobs/{job_id}/cancel")
    route = time.perf_counter() - started
    while True:
        status, view = service.request("GET", f"/api/projects/p1/jobs/{job_id}")
        if view["state"] in ("succeeded", "failed", "cancelled", "interrupted", "remote_completion_unknown"):
            return route, time.perf_counter() - started, view["state"]
        if time.perf_counter() - started > 60:
            raise AssertionError("취소가 60초 안에 종결되지 않았습니다")
        time.sleep(0.02)


def _calls(tmp: Path) -> int:
    log = tmp / "record" / "calls.log"
    return len(log.read_text(encoding="utf-8").splitlines()) if log.exists() else 0


def service_timings(tmp: Path) -> dict:
    (tmp / "responses.json").write_text(json.dumps([SLOTS]), encoding="utf-8")
    result: dict = {"cancel_after_call": [], "cancel_before_call": None}
    for run in range(3):
        data = tmp / f"data-service-{run}"
        store = FileProjectStore(data)
        _project(store, count=3)
        service = Service(tmp, data, f"measure-{run}", cli_mode="gate")  # 가짜 CLI가 응답하지 않고 기다린다
        try:
            before = _calls(tmp)
            job_id = _register_batch(service, store, f"measure{run:04d}")
            if run == 0:
                result["poll_running"] = _poll(service, f"/api/projects/p1/jobs/{job_id}")
                result["poll_list"] = _poll(service, "/api/projects/p1/jobs")
            deadline = time.perf_counter() + 30
            while _calls(tmp) == before and time.perf_counter() < deadline:  # 가짜 CLI가 요청을 받을 때까지
                time.sleep(0.02)
            assert _calls(tmp) > before, "가짜 CLI가 요청을 받지 않았습니다"
            route, total, state = _cancel(service, job_id)
            result["cancel_after_call"].append({"route_ms": round(route * 1000, 1), "to_terminal_ms": round(total * 1000, 1),
                                                "state": state})
            if run == 0:
                result["poll_terminal"] = _poll(service, f"/api/projects/p1/jobs/{job_id}")
                # 가짜 CLI가 뜨기 전에 보낸 취소(다른 구간): 등록 직후 바로 취소한다
                second = _register_batch(service, store, "measure-early")
                route, total, state = _cancel(service, second)
                result["cancel_before_call"] = {"route_ms": round(route * 1000, 1), "to_terminal_ms": round(total * 1000, 1),
                                                "state": state}
        finally:
            service.stop()
    return result


if __name__ == "__main__":
    out = Path(sys.argv[1])
    with tempfile.TemporaryDirectory() as folder:
        tmp = Path(folder)
        result = {"ledger": ledger_writes(tmp), "service": service_timings(tmp)}
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
