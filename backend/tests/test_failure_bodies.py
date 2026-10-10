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
        consent = client.post("/api/projects/p1/generate/structure", json={}, headers={"X-AI-Consent": "no"})
        http["consent_missing"] = {"status": consent.status_code, "body": consent.json()}
    store = FileProjectStore(tmp_path_factory.mktemp("ledger"))
    _project(store)
    (store.root / LEDGER_NAME).write_bytes(b"broken" * 50)
    with TestClient(create_app(store, provider=GateProvider()), headers=HEADERS) as client:
        blocked = client.post("/api/projects/p1/generate/structure", json={})
        http["job_ledger_unavailable"] = {"status": blocked.status_code, "body": blocked.json()}
    return {"jobs": jobs, "chapters": chapters, "http": http}


def test_failure_bodies_match_the_fixture_the_screen_tests_use(tmp_path_factory, manager):
    from slidecaptain.storage.file_store import FileProjectStore

    collected = _collect(tmp_path_factory)
    # 연결 상태 확인에서 나는 등록 단계 오류: 처음 보는 로그아웃과 선택 변경
    store = FileProjectStore(tmp_path_factory.mktemp("conn"))
    _project(store)
    with TestClient(create_app(store, ai_connections=manager), headers=HEADERS) as client:
        changed = client.post("/api/projects/p1/generate/structure", json={},
                              headers={"X-AI-Selection": "other-selection"})
        # 처음 보는 로그아웃, 그 뒤 상태 확인이 CLI를 찾지 못함(실제 check_login 문구와 코드)
        manager.connections["claude"].login = LoginStatus(logged_in=False)
        logout = client.post("/api/projects/p1/generate/structure", json={},
                             headers={"X-AI-Selection": manager.selection_id})
        manager.connections["claude"].login = LoginStatus(
            error="Claude CLI를 찾지 못했습니다. Claude Code가 설치되어 있는지 확인해 주세요.", error_code="provider_missing")
        manager.selected_status()  # 화면은 생성 전에 상태를 읽는다. 상태가 바뀐 것을 먼저 관찰해 선택 ID가 새로 난다
        no_cli = client.post("/api/projects/p1/generate/structure", json={},
                             headers={"X-AI-Selection": manager.selection_id})
    collected["http"]["selection_changed"] = {"status": changed.status_code, "body": changed.json()}
    collected["http"]["login_required"] = {"status": logout.status_code, "body": logout.json()}
    collected["http"]["provider_missing"] = {"status": no_cli.status_code, "body": no_cli.json()}
    text = json.dumps(collected, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    if os.environ.get("SLIDECAPTAIN_UPDATE_FIXTURES") == "1":
        FIXTURE.write_text(text, encoding="utf-8")
    assert FIXTURE.read_text(encoding="utf-8") == text, "서버 오류 본문이 바뀌었습니다. 고정 파일을 다시 써 주세요"
