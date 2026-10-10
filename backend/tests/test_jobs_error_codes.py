"""원인 분류와 오류 코드 (개정판 D3a-4, 계획 4.3, 사실 7, 17).

실제 AI 호출은 없다. 원장 행은 실제 실행기로 만들고, 읽기 관대화는 원장 파일에 값을 직접 써서 확인한다.
"""

import sqlite3

from fastapi.testclient import TestClient

from slidecaptain.server.app import create_app
from slidecaptain.storage.job_ledger import LEDGER_NAME
from tests.test_jobs_api import HEADERS, GateProvider, _project, _register, _wait


def _finished_job(client):
    job = _register(client).json()
    _wait(client, job["id"])
    return job["id"]


# 회귀 RED(사실 17): 지금 코드는 응답 모델이 원인 분류를 고정 목록으로 검증해, 원장 행 하나가 모르는 값을
# 가지면 작업 조회, 작업 목록, 진행 API가 모두 500이다(리뷰 탐침)

def test_unknown_error_class_in_the_ledger_reads_as_internal_and_keeps_the_original(store):
    _project(store)
    provider = GateProvider()
    provider.release.set()
    with TestClient(create_app(store, provider=provider), headers=HEADERS) as client:
        job_id = _finished_job(client)
        with sqlite3.connect(store.root / LEDGER_NAME) as conn:
            conn.execute("UPDATE jobs SET state = 'failed', error_class = 'future_class', error_status = 500, "
                         "error_detail = '다른 빌드가 쓴 값' WHERE id = ?", (job_id,))
        one = client.get(f"/api/projects/p1/jobs/{job_id}")
        listed = client.get("/api/projects/p1/jobs")
        progress = client.get("/api/projects/p1/progress")
    assert (one.status_code, listed.status_code, progress.status_code) == (200, 200, 200)
    error = one.json()["error"]
    assert error["error_class"] == "internal" and error["raw_error_class"] == "future_class"
    assert listed.json()[0]["error"]["error_class"] == "internal"
    assert progress.json()["jobs"][0]["error"]["raw_error_class"] == "future_class"


def test_known_error_class_is_read_as_is_without_a_raw_value(store):
    _project(store)
    provider = GateProvider()
    provider.release.set()
    with TestClient(create_app(store, provider=provider), headers=HEADERS) as client:
        job_id = _finished_job(client)
        with sqlite3.connect(store.root / LEDGER_NAME) as conn:
            conn.execute("UPDATE jobs SET state = 'failed', error_class = 'connection', error_status = 503 WHERE id = ?",
                         (job_id,))
        error = client.get(f"/api/projects/p1/jobs/{job_id}").json()["error"]
    assert (error["error_class"], error["raw_error_class"]) == ("connection", None)
