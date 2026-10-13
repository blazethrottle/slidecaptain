"""장 후보 서버 적용 라우트 (개정판 D3c-5, 계획 4.7, 4.8).

장 생성, 장 축약, 묶음 하위 행의 결과를 서버가 지금 덱에 합쳐 스냅샷과 함께 저장하고 처분을 applied로 바꾼다. 판정(관련 입력,
축약 슬롯, 이미 반영된 결과의 정리), 상태 코드, 묶음의 장별 해시와 이전 행 거절, 원자성(저장 실패와 커밋 실패), 범용 처분
라우트의 applied 거절, 작업 API 등록 단계의 구성 계획 낡음을 지킨다. 실제 AI 호출은 없다.
"""

import hashlib
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from slidecaptain.models.deck import Slide
from slidecaptain.pipeline.relevance import BATCH_MARKER, batch_parts
from slidecaptain.pipeline.story import StaleStoryPlan
from slidecaptain.server.app import create_app
from slidecaptain.storage.file_store import StorageError
from tests.test_jobs_batch import HEADERS, ChapterProvider, _project, slots
from tests.test_jobs_batch import _register as _register_batch
from tests.test_jobs_batch import _wait as _wait_batch


def _job(client, request_id, chapter_id="c1", kind="chapter", **params):
    response = client.post("/api/projects/p1/jobs", json={
        "request_id": request_id, "kind": kind, "params": {"chapter_id": chapter_id, **params}})
    assert response.status_code == 202, response.text
    handle = client.app.state.job_runner._handles[response.json()["id"]]
    assert handle.wait_sync(10) is not None
    return client.get(f"/api/projects/p1/jobs/{response.json()['id']}").json()


def _etag(store):
    return f'"{store.deck_etag("p1")}"'


def _apply(client, store, job_id, body=None, if_match=True):
    headers = {"If-Match": _etag(store)} if if_match else {}
    return client.post(f"/api/projects/p1/jobs/{job_id}/apply", json=body or {}, headers=headers)


def _preview(client, job_id, body=None):
    return client.post(f"/api/projects/p1/jobs/{job_id}/apply/preview", json=body or {})


def _candidate(client, job_id):
    return client.get(f"/api/projects/p1/jobs/{job_id}").json()["candidate_status"]


def _slide(store, chapter_id="c1"):
    return next(s for s in store.load_deck("p1").slides if s.chapter_id == chapter_id)


def _save_slide(store, slide: dict):
    deck = store.load_deck("p1")
    others = [s for s in deck.slides if s.chapter_id != slide["chapter_id"]]
    store.save_deck("p1", deck.model_copy(update={"slides": [*others, Slide.model_validate(slide)]}), snapshot=False)


def _span(slot, text, index=None):
    return {"slot": slot, "index": index, "start": 0, "end": 2, "role": "bold",
            "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}


def test_held_chapter_candidate_is_applied_by_the_server_with_a_snapshot(store):
    _project(store)
    with TestClient(create_app(store, provider=ChapterProvider([slots("새 내용")])), headers=HEADERS) as client:
        view = _job(client, "chapter-0001")
        snapshots = len(store.list_snapshots("p1"))
        response = _apply(client, store, view["id"])
        status = _candidate(client, view["id"])
    assert view["candidate_status"] == "held"
    assert response.status_code == 200, response.text
    assert response.headers["ETag"] == _etag(store)
    assert response.json() == store.load_deck("p1").model_dump(mode="json")
    assert _slide(store).slots.conclusion == "새 내용"
    assert status == "applied" and len(store.list_snapshots("p1")) == snapshots + 1


def test_regeneration_keeps_directly_edited_text_spans_and_edits_by_default(store):
    _project(store)
    again = {**slots("다시 생성"), "conclusion": "새 결론"}
    with TestClient(create_app(store, provider=ChapterProvider([slots("첫 생성"), again])), headers=HEADERS) as client:
        first = _job(client, "chapter-0001")
        assert _apply(client, store, first["id"]).status_code == 200
        _save_slide(store, {"chapter_id": "c1", "slots": {**slots("첫 생성"), "conclusion": "직접 고친 결론"},
                            "text_spans": [_span("conclusion", "직접 고친 결론")],
                            "direct_edits": {"conclusion": {"dx_pt": 12, "dy_pt": 0}, "bullets": {"text_color": "danger"}}})
        second = _job(client, "chapter-0002")
        preview = _preview(client, second["id"]).json()
        response = _apply(client, store, second["id"])
    assert preview["edited_units"] == ["conclusion"] and preview["keep_current"] == ["conclusion"]
    assert preview["blocked_reasons"] == [] and preview["units"] == ["bullets", "conclusion", "footnote"]
    assert response.status_code == 200, response.text
    slide = _slide(store)
    assert slide.slots.conclusion == "직접 고친 결론" and slide.slots.bullets[0].text == "다시 생성"
    assert len(slide.text_spans) == 1  # 지금 문구로 둔 결론의 강조는 남는다
    assert set(slide.direct_edits) == {"bullets", "conclusion"}  # 목록이 아닌 요소의 수정은 남는다


def test_explicit_selection_overrides_the_defaults_and_the_response_reports_it(store):
    _project(store)
    with TestClient(create_app(store, provider=ChapterProvider([slots("새")])), headers=HEADERS) as client:
        _save_slide(store, {"chapter_id": "c1", "slots": slots("지금"),
                            "direct_edits": {"conclusion": {"dx_pt": 3, "dy_pt": 3, "hidden": True}}})
        view = _job(client, "chapter-0001")
        preview = _preview(client, view["id"], {"keep_current": ["bullets"], "drop_edits": [],
                                                "unhide": ["conclusion"]}).json()
        response = _apply(client, store, view["id"], {"keep_current": ["bullets"], "unhide": ["conclusion"]})
    assert preview["edited_units"] is None  # 반영 기록이 없는 장: 표시 없음
    assert (preview["keep_current"], preview["unhide"], preview["unhidden"]) == (["bullets"], ["conclusion"], ["conclusion"])
    assert response.status_code == 200
    slide = _slide(store)
    assert slide.slots.bullets[0].text == "지금" and slide.slots.conclusion == "새"
    assert slide.direct_edits["conclusion"].model_dump() == {"dx_pt": 3, "dy_pt": 3}


def test_list_items_whose_count_changed_lose_their_indexed_edits_by_default(store):
    _project(store)
    cards4 = {"template": "cards", "cards": [{"heading": h} for h in "ABCD"]}
    cards3 = {"template": "cards", "cards": [{"heading": h} for h in "XYZ"]}
    deck = store.load_deck("p1")
    deck.structure.chapters[0].template = "cards"
    store.save_deck("p1", deck, snapshot=False)
    with TestClient(create_app(store, provider=ChapterProvider([cards3])), headers=HEADERS) as client:
        _save_slide(store, {"chapter_id": "c1", "slots": cards4,
                            "direct_edits": {"card1": {"dx_pt": 4, "dy_pt": 0}, "title": {"font_scale": 1.2}}})
        view = _job(client, "chapter-0001")
        preview = _preview(client, view["id"]).json()
        assert _apply(client, store, view["id"]).status_code == 200
    assert preview["length_changed_units"] == ["cards"] and preview["drop_edits"] == ["card1"]
    assert preview["removed_edits"] == ["card1"]
    assert set(_slide(store).direct_edits) == {"title"}


def test_condense_takes_all_new_text_and_is_blocked_when_the_slots_changed_after_the_request(store):
    _project(store)
    current = {**slots("길게 쓴 내용"), "conclusion": "직접 고친 결론"}
    with TestClient(create_app(store, provider=ChapterProvider([slots("짧게")])), headers=HEADERS) as client:
        _save_slide(store, {"chapter_id": "c1", "slots": current})
        view = _job(client, "condense-0001", kind="condense", slots=current)
        preview = _preview(client, view["id"]).json()
        _save_slide(store, {"chapter_id": "c1", "slots": {**current, "footnote": "요청 뒤에 더한 각주"}})
        blocked = _preview(client, view["id"]).json()
        response = _apply(client, store, view["id"])
    assert preview["kind"] == "condense" and preview["keep_current"] == [] and preview["blocked_reasons"] == []
    assert blocked["blocked_reasons"] == ["slots_changed"]
    assert response.status_code == 409 and response.json()["code"] == "slots_changed"
    assert _slide(store).slots.footnote == "요청 뒤에 더한 각주"


def test_if_match_is_required_and_must_be_the_current_deck(store):
    _project(store)
    with TestClient(create_app(store, provider=ChapterProvider([slots("새")])), headers=HEADERS) as client:
        view = _job(client, "chapter-0001")
        missing = _apply(client, store, view["id"], if_match=False)
        stale = client.post(f"/api/projects/p1/jobs/{view['id']}/apply", json={}, headers={"If-Match": '"old"'})
        status = _candidate(client, view["id"])
    assert missing.status_code == 428 and stale.status_code == 412
    assert status == "held" and store.load_deck("p1").slides == []


def test_changed_chapter_title_blocks_the_apply_but_the_preview_still_compares(store):
    _project(store)
    with TestClient(create_app(store, provider=ChapterProvider([slots("새")])), headers=HEADERS) as client:
        _save_slide(store, {"chapter_id": "c1", "slots": slots("지금")})
        view = _job(client, "chapter-0001")
        deck = store.load_deck("p1")
        deck.structure.chapters[0].topic = "고친 제목"
        store.save_deck("p1", deck, snapshot=False)
        preview = _preview(client, view["id"])
        response = _apply(client, store, view["id"])
    assert preview.status_code == 200 and preview.json()["blocked_reasons"] == ["chapter_changed"]
    assert preview.json()["merged"]["slots"]["conclusion"] == "새"
    assert response.status_code == 409 and response.json()["code"] == "chapter_changed"
    assert _slide(store).slots.conclusion == "지금"


def test_stale_candidate_applies_once_its_reason_is_gone(store):
    """stale -> applied는 범용 전이표에 없고 적용 라우트 안에서만 허용한다 (리뷰 서버 S1)."""
    _project(store)
    provider = ChapterProvider([slots("새")], gate_at=0)
    with TestClient(create_app(store, provider=provider), headers=HEADERS) as client:
        job = client.post("/api/projects/p1/jobs", json={"request_id": "chapter-0001", "kind": "chapter",
                                                         "params": {"chapter_id": "c1"}}).json()
        assert provider.entered.wait(10)
        store.write_source("p1", "리서치.md", "바뀐 자료")
        provider.release.set()
        client.app.state.job_runner._handles[job["id"]].wait_sync(10)
        stale = _apply(client, store, job["id"])
        store.write_source("p1", "리서치.md", "시장 규모는 500억 원이다")  # 되돌리면 낡음 사유가 사라진다
        response = _apply(client, store, job["id"])
        status = _candidate(client, job["id"])
    assert stale.status_code == 409 and stale.json()["code"] == "sources_changed"
    assert response.status_code == 200 and status == "applied"


def test_stale_batch_chapter_is_applied_with_its_own_relevance_and_notices_other_changes(store):
    _project(store)
    provider = ChapterProvider([slots("하나"), slots("둘")], gate_at=1)
    with TestClient(create_app(store, provider=provider), headers=HEADERS) as client:
        job = _register_batch(client, store, ["c1", "c2"]).json()
        assert provider.entered.wait(10)
        current = store.load_deck("p1")
        current.meta.presenter = "다른 창의 편집"  # 장 지시문이 읽지 않는 값: 사슬은 끊기지만 후보는 낡지 않는다
        store.save_deck("p1", current, snapshot=False)
        provider.release.set()
        view = _wait_batch(client, job["id"])
        parent = client.app.state.job_runner.ledger.get_job(job["id"])
        without_chapter = _apply(client, store, job["id"])
        preview = _preview(client, job["id"], {"chapter_id": "c2"}).json()
        response = _apply(client, store, job["id"], {"chapter_id": "c2"})
        after = client.get(f"/api/projects/p1/jobs/{job['id']}").json()
    assert view["chapters"][1]["candidate_status"] == "stale"
    assert parent.relevance_hash.startswith(BATCH_MARKER) and set(batch_parts(parent.relevance_hash)) == {"c1", "c2"}
    assert without_chapter.status_code == 422
    assert preview["notices"] == ["deck_changed_elsewhere"] and preview["blocked_reasons"] == []
    assert response.status_code == 200, response.text
    assert _slide(store, "c2").slots.conclusion == "둘"
    assert after["chapters"][1]["candidate_status"] == "applied"


def test_batch_rows_from_before_d3c_are_not_applicable(store):
    _project(store)
    provider = ChapterProvider([slots("하나"), slots("둘")], gate_at=1)
    with TestClient(create_app(store, provider=provider), headers=HEADERS) as client:
        job = _register_batch(client, store, ["c1", "c2"]).json()
        assert provider.entered.wait(10)
        current = store.load_deck("p1")
        current.meta.presenter = "다른 창의 편집"
        store.save_deck("p1", current, snapshot=False)
        provider.release.set()
        _wait_batch(client, job["id"])
        ledger = client.app.state.job_runner.ledger
        ledger._conn.execute("UPDATE jobs SET relevance_hash = NULL WHERE id = ?", (job["id"],))  # D3b 빌드가 쓴 행
        response = _apply(client, store, job["id"], {"chapter_id": "c2"})
    assert response.status_code == 409 and response.json()["code"] == "not_applicable"


def test_running_batch_blocks_both_routes_and_unfinished_jobs_are_not_terminal(store):
    _project(store)
    provider = ChapterProvider([slots("단독"), slots("묶음")], gate_at=1)
    with TestClient(create_app(store, provider=provider), headers=HEADERS) as client:
        single = _job(client, "chapter-0001", chapter_id="c1")
        batch = _register_batch(client, store, ["c2"]).json()
        assert provider.entered.wait(10)
        active = _apply(client, store, single["id"])
        active_preview = _preview(client, single["id"])
        own = _apply(client, store, batch["id"], {"chapter_id": "c2"})
        stale_tab = client.post(f"/api/projects/p1/jobs/{single['id']}/apply", json={}, headers={"If-Match": '"old"'})
        provider.release.set()
        _wait_batch(client, batch["id"])
        after = _apply(client, store, single["id"])
    assert active.status_code == 409 and active.json()["code"] == "batch_active"
    # 비교는 보이되 반영은 막는다(계획 4.8 비교 화면). 낡은 탭은 다른 판정보다 412가 먼저다 (리뷰 F10)
    assert active_preview.status_code == 200 and active_preview.json()["blocked_reasons"][0] == "batch_active"
    assert stale_tab.status_code == 412
    assert own.status_code == 409
    assert after.status_code == 200


def test_running_single_job_is_not_terminal(store):
    _project(store)
    provider = ChapterProvider([slots("새")], gate_at=0)
    with TestClient(create_app(store, provider=provider), headers=HEADERS) as client:
        job = client.post("/api/projects/p1/jobs", json={"request_id": "chapter-0001", "kind": "chapter",
                                                         "params": {"chapter_id": "c1"}}).json()
        assert provider.entered.wait(10)
        response = _apply(client, store, job["id"])
        provider.release.set()
        client.app.state.job_runner._handles[job["id"]].wait_sync(10)
    assert response.status_code == 409 and response.json()["code"] == "not_terminal"


def test_settled_candidates_and_bad_requests(store):
    _project(store)
    with TestClient(create_app(store, provider=ChapterProvider([slots("하나"), slots("둘")])), headers=HEADERS) as client:
        first = _job(client, "chapter-0001")
        assert _apply(client, store, first["id"]).status_code == 200
        again = _apply(client, store, first["id"])
        stale_tab = client.post(f"/api/projects/p1/jobs/{first['id']}/apply", json={}, headers={"If-Match": '"old"'})
        second = _job(client, "chapter-0002")
        unknown_unit = _apply(client, store, second["id"], {"keep_current": ["card0"]})
        other_chapter = _apply(client, store, second["id"], {"chapter_id": "c2"})
        unknown_edit = _apply(client, store, second["id"], {"drop_edits": ["title"]})
        ledger = client.app.state.job_runner.ledger
        ledger._conn.execute("UPDATE jobs SET result = ? WHERE id = ?",
                             (json.dumps({"status": "ok", "slots": {"template": "bullet_box"}}), second["id"]))
        unreadable = _apply(client, store, second["id"])
    assert again.status_code == 409 and again.json()["code"] == "candidate_settled"
    assert stale_tab.status_code == 412  # 낡은 탭은 처분 판정보다 다시 읽기가 먼저다 (리뷰 F10)
    assert [r.status_code for r in (unknown_unit, other_chapter, unknown_edit, unreadable)] == [422] * 4


class _CommitFails:
    """원장 연결을 감싸 COMMIT 한 번을 실패시킨다(디스크 오류 흉내). sqlite3 연결의 메서드는 바꿔 끼울 수 없어 감싼다."""

    def __init__(self, conn):
        self._conn, self.armed = conn, True

    def execute(self, sql, *args):
        if self.armed and sql == "COMMIT":
            self.armed = False
            raise sqlite3.OperationalError("disk I/O error")
        return self._conn.execute(sql, *args)

    def __getattr__(self, name):
        return getattr(self._conn, name)


def test_deck_save_failure_rolls_back_the_disposition(store, monkeypatch):
    _project(store)
    with TestClient(create_app(store, provider=ChapterProvider([slots("새")])), headers=HEADERS) as client:
        view = _job(client, "chapter-0001")
        before = (store.root / "p1" / "deck.json").read_bytes()
        snapshots = len(store.list_snapshots("p1"))

        def fail(*args, **kwargs):
            raise StorageError("저장 공간이 부족합니다.")
        monkeypatch.setattr(store, "save_deck", fail)
        response = _apply(client, store, view["id"])
        status = _candidate(client, view["id"])
    assert response.status_code == 503 and response.json()["code"] == "deck_write_failed"
    assert response.json()["detail"] == "저장 공간이 부족합니다."
    assert status == "held"
    assert (store.root / "p1" / "deck.json").read_bytes() == before and len(store.list_snapshots("p1")) == snapshots


def test_commit_failure_after_the_save_is_settled_by_reapplying_without_a_second_write(store):
    """남는 틈: 덱은 반영됐고 처분은 held다. 같은 후보를 다시 반영하면 덱을 다시 쓰지 않고 처분만 정리한다. 축약은 이 판정을
    slots_changed보다 먼저 봐야 다시 반영이 막히지 않는다 (재리뷰 RR8)."""
    _project(store)
    current = slots("길게 쓴 내용")
    with TestClient(create_app(store, provider=ChapterProvider([slots("짧게")])), headers=HEADERS) as client:
        _save_slide(store, {"chapter_id": "c1", "slots": current})
        view = _job(client, "condense-0001", kind="condense", slots=current)
        ledger = client.app.state.job_runner.ledger
        ledger._conn = _CommitFails(ledger._conn)
        failed = _apply(client, store, view["id"])
        held = _candidate(client, view["id"])
        written = (store.root / "p1" / "deck.json").read_bytes()
        snapshots = len(store.list_snapshots("p1"))
        preview = _preview(client, view["id"]).json()
        response = _apply(client, store, view["id"])
        status = _candidate(client, view["id"])
    assert failed.status_code == 503 and failed.json()["code"] == "ledger_write_failed"
    assert held == "held" and _slide(store).slots.conclusion == "짧게"
    assert preview["already_applied"] and preview["blocked_reasons"] == []
    assert response.status_code == 200 and status == "applied"
    assert (store.root / "p1" / "deck.json").read_bytes() == written and len(store.list_snapshots("p1")) == snapshots
    assert response.headers["ETag"] == _etag(store)


def test_generic_candidate_route_refuses_applied_for_chapter_rows(store):
    _project(store)
    with TestClient(create_app(store, provider=ChapterProvider([slots("새"), slots("둘")])), headers=HEADERS) as client:
        view = _job(client, "chapter-0001")
        applied = client.post(f"/api/projects/p1/jobs/{view['id']}/candidate", json={"action": "applied"})
        dismissed = client.post(f"/api/projects/p1/jobs/{view['id']}/candidate", json={"action": "dismissed"})
    assert applied.status_code == 409 and applied.json()["code"] == "apply_route_required"
    assert dismissed.status_code == 200 and dismissed.json()["candidate_status"] == "dismissed"
    assert store.load_deck("p1").slides == []


@pytest.mark.parametrize("kind", ["chapter", "condense"])
def test_job_api_rejects_a_stale_story_plan_at_registration_without_a_row(store, monkeypatch, kind):
    """E9: 등록(202) 뒤 실패하던 구성 계획 낡음을 등록 단계의 409로 낸다. 자료 읽기(422) 뒤에 본다."""
    _project(store)
    _save_slide(store, {"chapter_id": "c1", "slots": slots("지금")})
    monkeypatch.setattr("slidecaptain.server.app.require_current_story",
                        lambda deck, sources: (_ for _ in ()).throw(StaleStoryPlan("보고 계획이 바뀌었습니다.")))
    params = {"chapter_id": "c1", **({"slots": slots("지금")} if kind == "condense" else {})}
    provider = ChapterProvider([slots("새")])
    with TestClient(create_app(store, provider=provider), headers=HEADERS) as client:
        response = client.post("/api/projects/p1/jobs", json={"request_id": "req-00000001", "kind": kind, "params": params})
        (store.root / "p1" / "sources" / "리서치.md").unlink()
        no_sources = client.post("/api/projects/p1/jobs", json={"request_id": "req-00000002", "kind": kind, "params": params})
        rows = client.app.state.job_runner.ledger.list_jobs("p1")
    assert response.status_code == 409 and response.json()["code"] == "stale_story_plan"
    assert no_sources.status_code == 422  # 자료 읽기가 먼저다
    assert rows == [] and provider.calls == 0


# -- D3c-5 리뷰 반영 ---------------------------------------------------------------------------------------


def test_edited_text_baseline_follows_the_apply_order_not_the_registration_order(store):
    """A와 B를 등록하고 B, A 순서로 반영하면 지금 슬라이드는 A의 결과다. 등록 순서로 기준을 고르면 B가 기준이 되어 모든 단위가
    "직접 고친 문구"로 보이고, 다음 다시 생성의 새 내용이 기본 선택에서 통째로 버려진다 (리뷰 F2)."""
    _project(store)
    provider = ChapterProvider([slots("A"), slots("B"), slots("C")])
    with TestClient(create_app(store, provider=provider), headers=HEADERS) as client:
        a = _job(client, "chapter-0001")
        b = _job(client, "chapter-0002")
        assert _apply(client, store, b["id"]).status_code == 200
        assert _apply(client, store, a["id"]).status_code == 200
        c = _job(client, "chapter-0003")
        preview = _preview(client, c["id"]).json()
        response = _apply(client, store, c["id"])
    assert preview["edited_units"] == [] and preview["keep_current"] == [] and not preview["already_applied"]
    assert response.status_code == 200 and _slide(store).slots.conclusion == "C"


def test_batch_and_single_results_use_the_last_applied_one_as_the_baseline(store):
    _project(store)
    provider = ChapterProvider([slots("묶음"), slots("단독"), slots("셋째")], gate_at=0)
    with TestClient(create_app(store, provider=provider), headers=HEADERS) as client:
        batch = _register_batch(client, store, ["c1"]).json()
        assert provider.entered.wait(10)
        _save_slide(store, {"chapter_id": "c1", "slots": slots("그사이 생긴 내용")})  # 묶음의 c1은 낡은 후보로 남는다
        provider.release.set()
        _wait_batch(client, batch["id"])
        single = _job(client, "chapter-0001")
        assert _apply(client, store, single["id"]).status_code == 200
        assert _apply(client, store, batch["id"], {"chapter_id": "c1"}).status_code == 200
        third = _job(client, "chapter-0002")
        preview = _preview(client, third["id"]).json()
    assert preview["edited_units"] == [] and preview["merged"]["slots"]["conclusion"] == "셋째"


def test_restoring_a_snapshot_resets_the_baseline(store):
    """후보가 아닌 경로가 장을 바꾸면 기준이 없다: 표시 없이 모두 새 문구다 (리뷰 F3, 계획 4.1)."""
    _project(store)
    provider = ChapterProvider([slots("A"), slots("B")])
    with TestClient(create_app(store, provider=provider), headers=HEADERS) as client:
        _save_slide(store, {"chapter_id": "c1", "slots": slots("처음")})
        a = _job(client, "chapter-0001")
        assert _apply(client, store, a["id"]).status_code == 200
        snapshot = store.list_snapshots("p1")[0]
        restored = client.post(f"/api/projects/p1/snapshots/{snapshot.id}/restore", headers={"If-Match": _etag(store)})
        b = _job(client, "chapter-0002")
        preview = _preview(client, b["id"]).json()
        ledger = client.app.state.job_runner.ledger
        record = ledger.last_apply("p1", "c1")
    assert restored.status_code == 200 and _slide(store).slots.conclusion == "처음"
    assert record == ("reset", None) and preview["edited_units"] is None


def test_single_rows_without_relevance_or_success_are_not_applicable(store):
    _project(store)
    with TestClient(create_app(store, provider=ChapterProvider([slots("하나"), slots("둘")])), headers=HEADERS) as client:
        first = _job(client, "chapter-0001")
        second = _job(client, "chapter-0002")
        conn = client.app.state.job_runner.ledger._conn
        conn.execute("UPDATE jobs SET relevance_hash = NULL WHERE id = ?", (first["id"],))
        conn.execute("UPDATE jobs SET state = 'cancelled' WHERE id = ?", (second["id"],))  # 취소 뒤 결과가 남은 행
        no_hash = _apply(client, store, first["id"])
        cancelled = _apply(client, store, second["id"])
    assert (no_hash.status_code, no_hash.json()["code"]) == (409, "not_applicable")
    assert (cancelled.status_code, cancelled.json()["code"]) == (409, "not_applicable")


def test_preview_reports_capacity_warnings_of_the_merged_slide(store):
    _project(store)
    long = {"template": "bullet_box", "bullets": [{"text": "아주 긴 문장 " * 40, "level": 0} for _ in range(12)],
            "conclusion": "결론 " * 80, "footnote": ""}
    with TestClient(create_app(store, provider=ChapterProvider([long])), headers=HEADERS) as client:
        view = _job(client, "chapter-0001")
        preview = _preview(client, view["id"]).json()
    assert preview["warnings"], "넘치는 후보는 반영 전에 경고가 보여야 한다 (계획 재리뷰 RR26)"


def test_default_keeps_the_hidden_state_and_same_slots_with_dropped_edits_still_write(store):
    _project(store)
    with TestClient(create_app(store, provider=ChapterProvider([slots("지금")])), headers=HEADERS) as client:
        _save_slide(store, {"chapter_id": "c1", "slots": slots("지금"),
                            "direct_edits": {"conclusion": {"hidden": True}, "bullets": {"dx_pt": 5, "dy_pt": 0}}})
        view = _job(client, "chapter-0001")
        preview = _preview(client, view["id"]).json()
        response = _apply(client, store, view["id"], {"drop_edits": ["bullets"]})
    assert preview["unhide"] == [] and preview["merged"]["direct_edits"]["conclusion"] == {"hidden": True}
    assert preview["already_applied"]  # 슬롯과 수정이 같으면 덱을 다시 쓰지 않는다
    assert response.status_code == 200 and set(_slide(store).direct_edits) == {"conclusion"}  # 수정만 달라도 쓴다


def test_condense_judgement_normalizes_the_requested_slots(store):
    """화면이 기본값 칸을 빼고 보낸 슬롯이 거짓 slots_changed를 내지 않는다 (리뷰 F8 M10)."""
    _project(store)
    with TestClient(create_app(store, provider=ChapterProvider([slots("짧게")])), headers=HEADERS) as client:
        _save_slide(store, {"chapter_id": "c1", "slots": slots("길게")})
        sparse = {"template": "bullet_box", "bullets": [{"text": "길게"}], "conclusion": "길게"}
        view = _job(client, "condense-0001", kind="condense", slots=sparse)
        preview = _preview(client, view["id"]).json()
    assert preview["blocked_reasons"] == []


@pytest.mark.parametrize("kind", ["chapter", "condense"])
def test_generic_route_refuses_applied_for_both_chapter_kinds(store, kind):
    _project(store)
    with TestClient(create_app(store, provider=ChapterProvider([slots("새")])), headers=HEADERS) as client:
        _save_slide(store, {"chapter_id": "c1", "slots": slots("지금")})
        params = {"slots": slots("지금")} if kind == "condense" else {}
        view = _job(client, f"{kind}-0001", kind=kind, **params)
        applied = client.post(f"/api/projects/p1/jobs/{view['id']}/candidate", json={"action": "applied"})
    assert applied.status_code == 409 and applied.json()["code"] == "apply_route_required"


def test_batch_apply_to_an_empty_chapter_becomes_the_baseline(store):
    """묶음이 빈 장에 쓴 결과도 반영 순서에 남는다. 그 뒤 다시 생성하면 고친 단위가 없다 (리뷰 F2)."""
    _project(store)
    with TestClient(create_app(store, provider=ChapterProvider([slots("묶음"), slots("다시")])), headers=HEADERS) as client:
        batch = _register_batch(client, store, ["c1"]).json()
        _wait_batch(client, batch["id"])
        again = _job(client, "chapter-0001")
        preview = _preview(client, again["id"]).json()
    assert _slide(store).slots.conclusion == "묶음"
    assert preview["edited_units"] == [] and preview["merged"]["slots"]["conclusion"] == "다시"
