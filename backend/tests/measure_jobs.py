"""작업 원장의 실측 (개정판 D2b-6, 계획서 7절 가정 4, D2b-4 리뷰 R15). pytest가 모으지 않는 실행 스크립트다.

실행: `.venv/bin/python tests/measure_jobs.py <결과 JSON 경로>`. 가짜 Claude CLI를 쓰므로 실제 AI 호출은 없다.

재는 것
1. 장당 원장 쓰기 시간: 같은 프로세스에서 5장 묶음을 돌리며 작업 루프 위의 원장 쓰기(전이, 갱신)를 잰다
2. 조회 응답 시간: 별도 프로세스 서비스에 `GET .../jobs/{id}`를 반복해 잰다(화면은 1초마다 한 번 부른다)
3. 취소 응답: 가짜 CLI가 응답하지 않는 동안 취소를 요청하고, 취소 라우트의 응답 시간과 작업이 종결될 때까지의 시간을 잰다
4. 원장 크기: 묶음 뒤 원장 파일 크기와 가장 큰 결과 JSON의 길이
"""

import json
import sqlite3
import statistics
import sys
import tempfile
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
    durations: list[float] = []
    originals = {name: getattr(JobLedger, name) for name in ("transition_chapter", "update_chapter", "transition")}

    def timed(name):
        def call(self, *args, **kwargs):
            started = time.perf_counter()
            try:
                return originals[name](self, *args, **kwargs)
            finally:
                durations.append(time.perf_counter() - started)
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
    return {**_ledger_size(store.root), "chapters": 5, "ledger_write_calls": len(durations), "per_write": _ms(durations),
            "ledger_ms_per_chapter": round(sum(durations) / 5 * 1000, 2), "batch_total_ms": round(elapsed * 1000, 1)}


def service_timings(tmp: Path) -> dict:
    data = tmp / "data-service"
    store = FileProjectStore(data)
    _project(store, count=3)
    (tmp / "responses.json").write_text(json.dumps([SLOTS]), encoding="utf-8")
    service = Service(tmp, data, "measure-1", cli_mode="gate")  # 가짜 CLI가 응답하지 않고 기다린다
    try:
        status, settings = service.request("GET", "/api/ai/settings")
        status, job = service.request("POST", "/api/projects/p1/jobs", {
            "request_id": "measure-0001", "kind": "chapters", "params": {"chapter_ids": ["c1", "c2", "c3"]},
        }, {"If-Match": f'"{store.deck_etag("p1")}"', "X-AI-Consent": "SlideCaptain",
            "X-AI-Selection": settings["selection_id"]})
        assert status == 202, job
        polls = []
        for _ in range(30):
            started = time.perf_counter()
            status, view = service.request("GET", f"/api/projects/p1/jobs/{job['id']}")
            polls.append(time.perf_counter() - started)
        started = time.perf_counter()
        status, _ = service.request("POST", f"/api/projects/p1/jobs/{job['id']}/cancel")
        cancel_response = time.perf_counter() - started
        while True:
            status, view = service.request("GET", f"/api/projects/p1/jobs/{job['id']}")
            if view["state"] in ("succeeded", "failed", "cancelled", "interrupted", "remote_completion_unknown"):
                break
            if time.perf_counter() - started > 60:
                raise AssertionError("취소가 60초 안에 종결되지 않았습니다")
            time.sleep(0.05)
        cancel_to_terminal = time.perf_counter() - started
    finally:
        service.stop()
    return {"poll": _ms(polls), "cancel_route_ms": round(cancel_response * 1000, 1),
            "cancel_to_terminal_ms": round(cancel_to_terminal * 1000, 1), "terminal_state": view["state"],
            "chapter_states": [c["state"] for c in view["chapters"]]}


if __name__ == "__main__":
    out = Path(sys.argv[1])
    with tempfile.TemporaryDirectory() as folder:
        tmp = Path(folder)
        result = {"ledger": ledger_writes(tmp), "service": service_timings(tmp)}
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
