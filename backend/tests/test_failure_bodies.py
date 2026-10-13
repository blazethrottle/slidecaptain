"""화면 시험이 쓰는 실제 오류 응답 본문 (개정판 D3a-4, 계획 5절).

화면 시험의 모의 오류 본문이 서버 계약을 지어내지 않도록, 실제 실행기와 실제 라우트가 만든 본문을 모아
tests/fixtures/failure-bodies.json과 대조한다. 서버가 본문을 바꾸면 이 시험이 먼저 깨지고, 고정 파일을
다시 써야 화면 시험이 새 본문으로 돈다. 다시 쓰기: SLIDECAPTAIN_UPDATE_FIXTURES=1. 실제 AI 호출은 없다.
"""

import json
import os
import threading
from pathlib import Path

from fastapi.testclient import TestClient

from slidecaptain.pipeline.auth_status import LoginStatus
from slidecaptain.pipeline.provider import PROVIDER_ERROR_CODES, ProviderNotAvailable
from slidecaptain.server.app import create_app
from slidecaptain.storage.file_store import DeckUnreadable, ProjectNotFound
from slidecaptain.storage.job_ledger import LEDGER_NAME
from tests import test_jobs_batch as batch
from tests.test_jobs_api import HEADERS, GateProvider, _project, _register, _wait, manager  # noqa: F401
from tests.job_runs import post_generation

FIXTURE = Path(__file__).parent / "fixtures" / "failure-bodies.json"


class _Raising:
    def __init__(self, exc):
        self.exc = exc

    async def complete(self, prompt, schema):
        raise self.exc


def _job_error(tmp_path_factory, name, exc):
    from slidecaptain.storage.file_store import FileProjectStore

    store = FileProjectStore(tmp_path_factory.mktemp(name))
    _project(store)
    with TestClient(create_app(store, provider=_Raising(exc)), headers=HEADERS) as client:
        return _wait(client, _register(client).json()["id"])["error"]


def _batch_chapters(store, provider, ids, during=None):
    with TestClient(create_app(store, provider=provider), headers=HEADERS) as client:
        job = batch._register(client, store, ids).json()
        if during:
            during(client)
        view = batch._wait(client, job["id"])
    return [{k: c[k] for k in ("chapter_id", "state", "candidate_status", "error")} for c in view["chapters"]]


def _collect(tmp_path_factory) -> dict:
    from slidecaptain.storage.file_store import FileProjectStore

    jobs = {"internal": _job_error(tmp_path_factory, "internal", RuntimeError("예기치 않음")),
            "project_missing": _job_error(tmp_path_factory, "storage", ProjectNotFound("프로젝트를 찾지 못했습니다")),
            "storage": _job_error(tmp_path_factory, "unreadable", DeckUnreadable("저장본을 읽지 못했습니다"))}
    for code in sorted(PROVIDER_ERROR_CODES):
        jobs[code] = _job_error(tmp_path_factory, code, ProviderNotAvailable("제공자 오류", code=code))

    chapters = {}
    store = FileProjectStore(tmp_path_factory.mktemp("stopped"))
    batch._project(store)
    rows = _batch_chapters(store, batch.ChapterProvider([batch.slots("하나"), RuntimeError("예기치 않음"), batch.slots("셋")]),
                           ["c1", "c2", "c3"])
    chapters["internal"], chapters["stopped_after_error"] = rows[1], rows[2]
    store = FileProjectStore(tmp_path_factory.mktemp("provider"))
    batch._project(store)
    rows = _batch_chapters(store, batch.ChapterProvider([ProviderNotAvailable("시간 초과", code="provider_timeout"),
                                                         batch.slots("둘")]), ["c1", "c2"])
    chapters["provider_timeout"], chapters["provider_failed"] = rows[0], rows[1]
    store = FileProjectStore(tmp_path_factory.mktemp("format"))
    batch._project(store)
    chapters["ai_output"] = _batch_chapters(store, batch.ChapterProvider([{"template": "bullet_box"}]), ["c1"])[0]
    store = FileProjectStore(tmp_path_factory.mktemp("stale"))
    batch._project(store)
    from slidecaptain.pipeline.story import StaleStoryPlan
    rows = _batch_chapters(store, batch.ChapterProvider([StaleStoryPlan("보고 계획이 바뀌었습니다."), batch.slots("둘")]),
                           ["c1", "c2"])
    chapters["stale_story_plan"], chapters["held_stale_plan"] = rows[0], rows[1]
    store = FileProjectStore(tmp_path_factory.mktemp("sources"))
    batch._project(store)
    provider = batch.ChapterProvider([batch.slots("하나")], gate_at=0)

    def change_sources(client):
        assert provider.entered.wait(10)
        store.write_source("p1", "자료.md", "바뀐 자료")
        provider.release.set()
    chapters["sources_changed"] = _batch_chapters(store, provider, ["c1"], during=change_sources)[0]

    http = {}
    store = FileProjectStore(tmp_path_factory.mktemp("http"))
    _project(store)
    gate = GateProvider()
    with TestClient(create_app(store, provider=gate), headers=HEADERS) as client:
        first = _register(client)
        assert gate.entered.wait(5)
        busy = _register(client, request_id="req-00000002")
        body = busy.json()
        body["active"] = {**body["active"], "id": "job-1", "created_at": "2026-10-10T10:00:00+09:00"}  # 매번 다른 값
        if body["active"].get("step_started_at"):  # 실행 단계의 시각과 경과 초도 매번 다르다 (D3b-4)
            body["active"]["step_started_at"] = "2026-10-10T10:00:00+09:00"
        if body["active"].get("elapsed_seconds") is not None:
            body["active"]["elapsed_seconds"] = 0
        http["generation_active"] = {"status": busy.status_code, "body": body}
        gate.release.set()
        _wait(client, first.json()["id"])
        deck = client.get("/api/projects/p1/deck")
        stale = client.put("/api/projects/p1/deck", json=deck.json(), headers={"If-Match": '"old"'})
        http["deck_conflict"] = {"status": stale.status_code, "body": stale.json()}
        invalid = client.post("/api/projects/p1/jobs", json={"request_id": "x", "kind": "structure", "params": {}})
        http["validation"] = {"status": invalid.status_code, "body": invalid.json()}
        # 등록 단계 실제 본문 더하기 (D3a-4 리뷰 R14): 없는 프로젝트, 전송 동의 헤더 누락
        missing = client.post("/api/projects/nope/jobs",
                              json={"request_id": "req-00000003", "kind": "structure", "params": {}})
        http["project_missing"] = {"status": missing.status_code, "body": missing.json()}
        consent = post_generation(client, "/api/projects/p1/generate/structure", json={}, headers={"X-AI-Consent": "no"})
        http["consent_missing"] = {"status": consent.status_code, "body": consent.json()}
        # 다른 탭이 보고 정보를 바꾼 뒤 옛 화면이 구조안을 등록한다 (D3b-2 리뷰 R1)
        mismatch = _register(client, request_id="req-00000004",
                             brief={"decision_question": "확대할 것인가?", "audience": "", "report_type": "weekly"})
        http["brief_mismatch"] = {"status": mismatch.status_code, "body": mismatch.json()}
    store = FileProjectStore(tmp_path_factory.mktemp("ledger"))
    _project(store)
    (store.root / LEDGER_NAME).write_bytes(b"broken" * 50)
    with TestClient(create_app(store, provider=GateProvider()), headers=HEADERS) as client:
        blocked = post_generation(client, "/api/projects/p1/generate/structure", json={})
        assert blocked.run.rejected  # 등록 단계의 503 (D3c-7 리뷰 H1)
        http["job_ledger_unavailable"] = {"status": blocked.status_code, "body": blocked.json()}
    return {"jobs": jobs, "chapters": chapters, "http": http}


def _apply_bodies(tmp_path_factory) -> dict:
    """장 후보 적용 라우트의 실제 오류 본문 (D3c-5, 계획 4.7, 4.8). 화면의 생성 패널이 코드마다 다르게 처리한다:
    412는 충돌 경로, 5xx는 "다시 읽기" 안내, 판정 409는 낡은 후보 표시, 그 밖은 원인별 안내다."""
    from slidecaptain.storage.file_store import FileProjectStore, StorageError
    from tests import test_candidate_apply_api as apply

    def body(response):
        return {"status": response.status_code, "body": response.json()}

    bodies = {}
    store = FileProjectStore(tmp_path_factory.mktemp("apply"))
    batch._project(store)
    current = batch.slots("지금")
    provider = batch.ChapterProvider([batch.slots("하나"), batch.slots("둘"), batch.slots("셋"), batch.slots("넷")], gate_at=3)
    with TestClient(create_app(store, provider=provider), headers=HEADERS) as client:
        first = apply._job(client, "chapter-0001")
        bodies["precondition"] = body(apply._apply(client, store, first["id"], if_match=False))
        bodies["deck_conflict"] = body(client.post(f"/api/projects/p1/jobs/{first['id']}/apply", json={},
                                                   headers={"If-Match": '"old"'}))
        store.write_source("p1", "리서치.md", "바뀐 자료")
        bodies["sources_changed"] = body(apply._apply(client, store, first["id"]))
        store.write_source("p1", "리서치.md", batch.SOURCES["리서치.md"])
        bodies["apply_route_required"] = body(client.post(f"/api/projects/p1/jobs/{first['id']}/candidate",
                                                          json={"action": "applied"}))
        save = store.save_deck

        def fail(*args, **kwargs):
            raise StorageError("저장 공간이 부족합니다.")
        store.save_deck = fail
        bodies["deck_write_failed"] = body(apply._apply(client, store, first["id"]))
        store.save_deck = save
        ledger = client.app.state.job_runner.ledger
        real = ledger._conn
        ledger._conn = apply._CommitFails(real)
        bodies["ledger_write_failed"] = body(apply._apply(client, store, first["id"]))
        ledger._conn = real
        assert apply._apply(client, store, first["id"]).status_code == 200
        bodies["candidate_settled"] = body(apply._apply(client, store, first["id"]))
        apply._save_slide(store, {"chapter_id": "c2", "slots": current})
        condense = apply._job(client, "condense-0001", chapter_id="c2", kind="condense", slots=current)
        apply._save_slide(store, {"chapter_id": "c2", "slots": {**current, "footnote": "더한 각주"}})
        bodies["slots_changed"] = body(apply._apply(client, store, condense["id"]))
        third = apply._job(client, "chapter-0002", chapter_id="c3")
        running = batch._register(client, store, ["c1"], request_id="batch-0001")  # 이미 내용이 있어 409
        assert running.status_code == 409
        apply._save_slide(store, {"chapter_id": "c1", "slots": current})
        deck = store.load_deck("p1")
        deck.slides = [s for s in deck.slides if s.chapter_id != "c1"]
        store.save_deck("p1", deck, snapshot=False)
        job = batch._register(client, store, ["c1"], request_id="batch-0002").json()
        assert provider.entered.wait(10)
        bodies["batch_active"] = body(apply._apply(client, store, third["id"]))
        provider.release.set()
        batch._wait(client, job["id"])
        ledger._conn.execute("UPDATE jobs SET relevance_hash = NULL WHERE id = ?", (job["id"],))
        bodies["not_applicable"] = body(apply._apply(client, store, job["id"], {"chapter_id": "c1"}))
    return bodies


def test_failure_bodies_match_the_fixture_the_screen_tests_use(tmp_path_factory, manager):
    from slidecaptain.storage.file_store import FileProjectStore

    collected = _collect(tmp_path_factory)
    # 연결 상태 확인에서 나는 오류. 선택 변경은 등록 단계의 409 응답 본문이다. 처음 보는 로그아웃과 CLI 없음은 임대 뒤
    # 실행 단계의 실패이고, 고정 파일의 본문은 작업 오류(error.status, detail, code)에서 만든 값이다 (D3c-7 리뷰 H11).
    # 화면의 jobResult(frontend/src/api/jobs.ts)도 같은 규칙으로 작업 오류를 본문으로 바꾼다
    store = FileProjectStore(tmp_path_factory.mktemp("conn"))
    _project(store)
    with TestClient(create_app(store, ai_connections=manager), headers=HEADERS) as client:
        changed = post_generation(client, "/api/projects/p1/generate/structure", json={},
                              headers={"X-AI-Selection": "other-selection"})
        # 처음 보는 로그아웃, 그 뒤 상태 확인이 CLI를 찾지 못함(실제 check_login 문구와 코드)
        manager.connections["claude"].login = LoginStatus(logged_in=False)
        logout = post_generation(client, "/api/projects/p1/generate/structure", json={},
                             headers={"X-AI-Selection": manager.selection_id})
        manager.connections["claude"].login = LoginStatus(
            error="Claude CLI를 찾지 못했습니다. Claude Code가 설치되어 있는지 확인해 주세요.", error_code="provider_missing")
        manager.selected_status()  # 화면은 생성 전에 상태를 읽는다. 상태가 바뀐 것을 먼저 관찰해 선택 ID가 새로 난다
        no_cli = post_generation(client, "/api/projects/p1/generate/structure", json={},
                             headers={"X-AI-Selection": manager.selection_id})
    assert changed.run.rejected and logout.category == "failure" and no_cli.category == "failure"
    collected["http"]["selection_changed"] = {"status": changed.status_code, "body": changed.json()}
    collected["http"]["login_required"] = {"status": logout.status_code, "body": logout.json()}
    collected["http"]["provider_missing"] = {"status": no_cli.status_code, "body": no_cli.json()}
    collected["apply"] = _apply_bodies(tmp_path_factory)
    text = json.dumps(collected, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    if os.environ.get("SLIDECAPTAIN_UPDATE_FIXTURES") == "1":
        FIXTURE.write_text(text, encoding="utf-8")
    assert FIXTURE.read_text(encoding="utf-8") == text, "서버 오류 본문이 바뀌었습니다. 고정 파일을 다시 써 주세요"
