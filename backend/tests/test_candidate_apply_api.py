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
from test_diagram_generation import REQUEST as DIAGRAM_REQUEST
from test_diagram_generation import StubProvider as DiagramProvider
from test_diagram_generation import diagram_input  # noqa: F401 (픽스처)
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


def test_length_notice_follows_the_candidate_and_unchosen_edits_follow_the_selected_units(store):
    """직접 고친 목록은 처음에 지금 문구라 길이가 그대로지만, 안내는 후보 기준으로 보이고 새 문구로 바꾸면 순번 요소 수정의
    기본 지우기가 다시 계산된다. 사용자가 고른 열쇠만 그 선택을 따른다 (D3c-6 리뷰 G2)."""
    _project(store)
    cards4 = {"template": "cards", "cards": [{"heading": h} for h in "ABCD"]}
    cards3 = {"template": "cards", "cards": [{"heading": h} for h in "XYZ"]}
    deck = store.load_deck("p1")
    deck.structure.chapters[0].template = "cards"
    store.save_deck("p1", deck, snapshot=False)
    with TestClient(create_app(store, provider=ChapterProvider([cards4, cards3])), headers=HEADERS) as client:
        first = _job(client, "chapter-0001")
        assert _apply(client, store, first["id"]).status_code == 200
        edited = {"template": "cards", "cards": [{"heading": h} for h in ["A2", "B", "C", "D"]]}
        _save_slide(store, {"chapter_id": "c1", "slots": edited, "direct_edits": {"card1": {"dx_pt": 30, "dy_pt": 0}}})
        second = _job(client, "chapter-0002")
        initial = _preview(client, second["id"]).json()
        switched = _preview(client, second["id"], {"keep_current": []}).json()
        kept = _preview(client, second["id"], {"keep_current": [], "edit_choices": {"card1": "keep"}}).json()
        response = _apply(client, store, second["id"], {"keep_current": [], "edit_choices": {"card1": "keep"}})
    assert (initial["keep_current"], initial["length_changed_units"], initial["drop_edits"]) == (["cards"], ["cards"], [])
    assert (switched["length_changed_units"], switched["drop_edits"]) == (["cards"], ["card1"])
    assert kept["drop_edits"] == []
    assert response.status_code == 200, response.text
    slide = _slide(store)
    assert [c.heading for c in slide.slots.cards] == ["X", "Y", "Z"] and set(slide.direct_edits) == {"card1"}


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


def test_running_batch_blocks_snapshot_and_draft_restore_and_they_open_after_it_ends(store):
    """묶음 실행 중에는 스냅샷 복원과 보존본 복원도 서버가 막는다. 화면 잠금만으로는 알림을 받지 못한 탭이나 다른 빌드가
    묶음의 사슬을 끊을 수 있다 (최종 리뷰 SC-14, C2 계획 4.4 (2), 리뷰 PR-07). 묶음이 끝나면 다시 복원된다(9절 가정 3)."""
    _project(store)
    _save_slide(store, {"chapter_id": "c1", "slots": slots("처음")})
    store.save_deck("p1", store.load_deck("p1"))  # 스냅샷 하나
    snapshot = store.list_snapshots("p1")[0]
    draft = store.save_draft("p1", deck=store.load_deck("p1").model_dump(mode="json"), reason="conflict", source="editor",
                             base_etag=store.deck_etag("p1"))
    provider = ChapterProvider([slots("묶음")], gate_at=0)
    with TestClient(create_app(store, provider=provider), headers=HEADERS) as client:
        batch = _register_batch(client, store, ["c2"]).json()
        assert provider.entered.wait(10)
        before = store.deck_etag("p1")
        snap = client.post(f"/api/projects/p1/snapshots/{snapshot.id}/restore", headers={"If-Match": _etag(store)})
        drft = client.post(f"/api/projects/p1/drafts/{draft.id}/restore", headers={"If-Match": _etag(store)})
        unchanged = store.deck_etag("p1") == before
        provider.release.set()
        _wait_batch(client, batch["id"])
        after = client.post(f"/api/projects/p1/snapshots/{snapshot.id}/restore", headers={"If-Match": _etag(store)})
    for response in (snap, drft):
        assert response.status_code == 409 and response.json()["code"] == "batch_active", response.text
        assert "복원할 수 없습니다" in response.json()["detail"]
    assert unchanged
    assert after.status_code == 200


def test_restore_without_a_ledger_is_not_blocked_by_the_batch_check(store):
    """원장이 없거나 열지 못한 실행에는 묶음도 없다. 복원 거절 판정이 새 503을 만들지 않는다 (C2 계획 리뷰 PR-07 ①)."""
    _project(store)
    store.save_deck("p1", store.load_deck("p1"))
    snapshot = store.list_snapshots("p1")[0]
    with TestClient(create_app(store), headers=HEADERS) as client:
        runner = client.app.state.job_runner
        ledger, runner.ledger = runner.ledger, None
        try:
            response = client.post(f"/api/projects/p1/snapshots/{snapshot.id}/restore", headers={"If-Match": _etag(store)})
        finally:
            runner.ledger = ledger
    assert response.status_code == 200, response.text


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


@pytest.mark.parametrize("kind", ["chapter", "condense"])
def test_selection_check_comes_before_the_stale_story_plan_at_registration(store, monkeypatch, kind):
    """선택 확인(제공자 없음 503, 연결 선택 변경 409)은 구성 계획 낡음(E9)보다 먼저다. 둘이 함께 성립하면 화면은 AI 연결을
    다시 확인하라고 안내해야 한다. 구성 계획을 다시 만들라고 안내하면, 다시 만든 뒤에도 같은 요청이 선택 확인에 막힌다
    (D3c-7 리뷰 H5)."""
    _project(store)
    _save_slide(store, {"chapter_id": "c1", "slots": slots("지금")})
    monkeypatch.setattr("slidecaptain.server.app.require_current_story",
                        lambda deck, sources: (_ for _ in ()).throw(StaleStoryPlan("보고 계획이 바뀌었습니다.")))
    params = {"chapter_id": "c1", **({"slots": slots("지금")} if kind == "condense" else {})}
    with TestClient(create_app(store), headers=HEADERS) as client:  # 제공자 없음
        response = client.post("/api/projects/p1/jobs", json={"request_id": "req-00000001", "kind": kind, "params": params})
        rows = client.app.state.job_runner.ledger.list_jobs("p1")
    assert response.status_code == 503, response.text
    assert response.json().get("code") != "stale_story_plan"
    assert rows == []


def test_selection_check_comes_before_the_stale_story_plan_at_batch_registration(store, monkeypatch):
    """장 생성 묶음 등록도 선택 확인이 구성 계획 낡음보다 먼저다 (최종 리뷰 SV-09, C2 계획 4.4 (12)). 묶음 등록은
    If-Match가 없으면 428, 내용이 있는 장이면 409를 먼저 내므로, 기준 ETag를 주고 내용이 없는 장으로 등록한다."""
    _project(store)
    monkeypatch.setattr("slidecaptain.server.app.require_current_story",
                        lambda deck, sources: (_ for _ in ()).throw(StaleStoryPlan("보고 계획이 바뀌었습니다.")))
    with TestClient(create_app(store), headers=HEADERS) as client:  # 제공자 없음
        response = client.post("/api/projects/p1/jobs", headers={"If-Match": _etag(store)}, json={
            "request_id": "req-00000001", "kind": "chapters", "params": {"chapter_ids": ["c1"]}})
        rows = client.app.state.job_runner.ledger.list_jobs("p1")
    assert response.status_code == 503, response.text
    assert response.json().get("code") != "stale_story_plan"
    assert rows == []


# -- D3c-5 리뷰 반영---------------------------------------------------------------------------------------


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


def test_restoring_a_draft_resets_the_baseline(store):
    """보존본 복원도 스냅샷 복원처럼 바꾼 장의 "직접 고친 문구" 기준을 없앤다 (D3c 리뷰 F3). 이 무효화를 지워도 전체 시험이
    통과하던 공백이다 (최종 리뷰 SV-12, 변형 SV-M08, C2 계획 4.5 (13))."""
    _project(store)
    provider = ChapterProvider([slots("A"), slots("B")])
    with TestClient(create_app(store, provider=provider), headers=HEADERS) as client:
        _save_slide(store, {"chapter_id": "c1", "slots": slots("처음")})
        draft_deck = store.load_deck("p1").model_dump(mode="json")
        draft = client.post("/api/projects/p1/drafts", json={"deck": draft_deck, "reason": "conflict", "source": "editor",
                                                             "base_etag": _etag(store)})
        assert draft.status_code == 201, draft.text
        a = _job(client, "chapter-0001")
        assert _apply(client, store, a["id"]).status_code == 200
        restored = client.post(f"/api/projects/p1/drafts/{draft.json()['id']}/restore", headers={"If-Match": _etag(store)})
        b = _job(client, "chapter-0002")
        preview = _preview(client, b["id"]).json()
        record = client.app.state.job_runner.ledger.last_apply("p1", "c1")
    assert restored.status_code == 200, restored.text
    assert _slide(store).slots.conclusion == "처음"
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


def test_preview_carries_both_render_plans_for_the_comparison_screen(store):
    """비교 화면의 좌우 미리보기는 서버가 저장할 것과 같은 계획으로 그린다 (D3c-6)."""
    _project(store)
    with TestClient(create_app(store, provider=ChapterProvider([slots("새 결론")])), headers=HEADERS) as client:
        _save_slide(store, {"chapter_id": "c1", "slots": slots("지금 결론")})
        view = _job(client, "chapter-0001")
        preview = _preview(client, view["id"], {"keep_current": ["bullets"]}).json()
        empty = _job(client, "chapter-0002", chapter_id="c2")
        blank = _preview(client, empty["id"]).json()

    def texts(plan):
        return " ".join(p["text"] for f in plan["frames"] for p in f["paras"])
    assert "지금 결론" in texts(preview["current_plan"]) and "새 결론" in texts(preview["merged_plan"])
    assert preview["page_width_pt"] > 0 and preview["style"]["korean_font"]
    assert blank["current_plan"] is None and blank["merged_plan"]["chapter_id"] == "c2"


# -- β 묶음 리뷰 반영 ---------------------------------------------------------------------------------------


def _distinct(tag):
    """단위마다 다른 문구. slots()는 각주가 늘 빈 문자열이라 각주 단위의 판정을 보지 못한다."""
    return {"template": "bullet_box", "bullets": [{"text": f"{tag} 불릿", "level": 0}], "conclusion": f"{tag} 결론",
            "footnote": f"{tag} 각주"}


def test_undoing_an_apply_does_not_turn_every_unit_into_edited_text(store):
    """반영 뒤 되돌리기는 일반 편집이다(계획 4.7의 5). 덱은 이전 AI 결과로 돌아가고 반영 기록은 남는다. 이전 결과와 같은 단위는
    직접 고친 문구가 아니므로 다음 다시 생성의 기본 선택은 새 문구다. 마지막 기록만 기준으로 보면 모든 단위가 지금 문구로
    남고 새 결과는 하나도 들어가지 않은 채 처분된다 (β 묶음 리뷰 S2)."""
    _project(store)
    provider = ChapterProvider([_distinct("A"), _distinct("B"), _distinct("C")])
    with TestClient(create_app(store, provider=provider), headers=HEADERS) as client:
        a = _job(client, "chapter-0001")
        assert _apply(client, store, a["id"]).status_code == 200
        before_b = _slide(store).model_dump(mode="json")
        b = _job(client, "chapter-0002")
        assert _apply(client, store, b["id"]).status_code == 200
        deck = store.load_deck("p1").model_dump(mode="json")
        deck["slides"] = [before_b if s["chapter_id"] == "c1" else s for s in deck["slides"]]
        undo = client.put("/api/projects/p1/deck?snapshot=false", json=deck, headers={"If-Match": _etag(store)})
        c = _job(client, "chapter-0003")
        preview = _preview(client, c["id"]).json()
        response = _apply(client, store, c["id"])
    assert undo.status_code == 200, undo.text
    assert preview["edited_units"] == [] and preview["keep_current"] == [] and not preview["already_applied"]
    assert response.status_code == 200 and _slide(store).slots.conclusion == "C 결론"


def test_previous_ai_text_kept_at_apply_is_not_marked_as_edited(store):
    """반영 때 지금 문구로 남긴 단위가 이전 AI 문구면 다음 비교에서 직접 고친 문구가 아니다 (β 묶음 리뷰 S3)."""
    _project(store)
    provider = ChapterProvider([_distinct("A"), _distinct("B"), _distinct("C")])
    with TestClient(create_app(store, provider=provider), headers=HEADERS) as client:
        a = _job(client, "chapter-0001")
        assert _apply(client, store, a["id"]).status_code == 200
        b = _job(client, "chapter-0002")
        assert _apply(client, store, b["id"], {"keep_current": ["conclusion"]}).status_code == 200
        c = _job(client, "chapter-0003")
        preview = _preview(client, c["id"]).json()
    assert _slide(store).slots.conclusion == "A 결론"
    assert preview["edited_units"] == [] and preview["merged"]["slots"]["conclusion"] == "C 결론"


def test_condense_defaults_to_new_text_even_for_edited_units(store):
    """장 축약은 직접 고친 단위도 기본이 새 문구다. 다시 생성만 고친 단위를 지금 문구로 둔다 (계획 4.1, β 묶음 리뷰 S5)."""
    _project(store)
    with TestClient(create_app(store, provider=ChapterProvider([_distinct("A"), _distinct("짧게")])),
                    headers=HEADERS) as client:
        a = _job(client, "chapter-0001")
        assert _apply(client, store, a["id"]).status_code == 200
        edited = {**_distinct("A"), "conclusion": "직접 고친 결론"}
        _save_slide(store, {"chapter_id": "c1", "slots": edited})
        view = _job(client, "condense-0001", kind="condense", slots=edited)
        preview = _preview(client, view["id"]).json()
    assert preview["blocked_reasons"] == []
    assert preview["edited_units"] == ["conclusion"] and preview["keep_current"] == []
    assert preview["merged"]["slots"]["conclusion"] == "짧게 결론"


def test_a_chapter_back_from_another_template_has_no_baseline_from_before_the_switch(store):
    """템플릿 전환은 덱 PUT이라 기준 무효화를 쓰지 않는다. 불릿 상자 A 반영, 카드 전환, 카드 B 반영, 불릿 상자로 되돌림을 거친
    장에서 A를 기준으로 삼으면 B를 옮겨 온 지금 문구가 모두 직접 고친 문구가 되어 다음 결과가 통째로 버려진다 (β 재리뷰 T1)."""
    _project(store)
    cards = {"template": "cards", "cards": [{"heading": "B 카드1"}, {"heading": "B 카드2"}]}
    provider = ChapterProvider([_distinct("A"), cards, _distinct("C")])
    with TestClient(create_app(store, provider=provider), headers=HEADERS) as client:

        def switch(template, new_slots):
            deck = store.load_deck("p1").model_dump(mode="json")
            next(c for c in deck["structure"]["chapters"] if c["id"] == "c1")["template"] = template
            next(s for s in deck["slides"] if s["chapter_id"] == "c1")["slots"] = new_slots
            response = client.put("/api/projects/p1/deck?snapshot=false", json=deck, headers={"If-Match": _etag(store)})
            assert response.status_code == 200, response.text

        a = _job(client, "chapter-0001")
        assert _apply(client, store, a["id"]).status_code == 200
        switch("cards", {"template": "cards", "cards": [{"heading": "전환1"}, {"heading": "전환2"}]})
        b = _job(client, "chapter-0002")
        assert _apply(client, store, b["id"]).status_code == 200
        switch("bullet_box", {"template": "bullet_box", "bullets": [{"text": "B 카드1", "level": 0}, {"text": "B 카드2", "level": 0}],
                              "conclusion": "", "footnote": ""})
        c = _job(client, "chapter-0003")
        preview = _preview(client, c["id"]).json()
        response = _apply(client, store, c["id"])
    assert preview["edited_units"] is None and preview["keep_current"] == [] and not preview["already_applied"]
    assert response.status_code == 200 and _slide(store).slots.conclusion == "C 결론"


# C1 계획(2026-10-15) W1-a: 새 묶음이 생긴 뒤에도 이전 묶음의 낡은 장 후보를 적용 라우트로 반영한다. 화면(복구 화면)이 기대는
# 서버 계약이다. 묶음 등록은 빈 장만 받으므로 c2의 내용은 첫 묶음이 끝난 뒤 쓰고, 둘째 묶음은 c2를 넣지 않는다
def test_older_batch_candidate_on_a_filled_chapter_applies_after_a_newer_batch(store):
    _project(store)
    provider = ChapterProvider([slots("하나"), slots("둘"), slots("셋")], gate_at=1)
    with TestClient(create_app(store, provider=provider), headers=HEADERS) as client:
        older = _register_batch(client, store, ["c1", "c2"]).json()
        assert provider.entered.wait(10)
        current = store.load_deck("p1")
        current.meta.presenter = "다른 창의 편집"  # 사슬만 끊고 후보의 관련 입력은 바꾸지 않는다
        store.save_deck("p1", current, snapshot=False)
        provider.release.set()
        older_view = _wait_batch(client, older["id"])
        _save_slide(store, {"chapter_id": "c2", "slots": slots("사용자가 쓴 내용")})
        newer = _register_batch(client, store, ["c3"], request_id="batch-0002").json()
        newer_before = _wait_batch(client, newer["id"])
        listed = [j["id"] for j in client.get("/api/projects/p1/jobs").json()]
        preview = _preview(client, older["id"], {"chapter_id": "c2"})
        response = _apply(client, store, older["id"], {"chapter_id": "c2"})
        older_after = client.get(f"/api/projects/p1/jobs/{older['id']}").json()
        newer_after = client.get(f"/api/projects/p1/jobs/{newer['id']}").json()
    assert older_view["chapters"][1]["candidate_status"] == "stale"
    assert older["id"] in listed and newer["id"] in listed  # 복구 화면 목록에 이전 묶음이 남는다
    assert preview.status_code == 200 and preview.json()["blocked_reasons"] == []
    assert preview.json()["current"]["slots"]["conclusion"] == "사용자가 쓴 내용"  # 내용이 있는 장과 비교한다
    assert response.status_code == 200, response.text
    assert _slide(store, "c2").slots.conclusion == "둘"
    assert older_after["chapters"][1]["candidate_status"] == "applied"
    assert newer_after["chapters"] == newer_before["chapters"]


# C1 계획 W1-a 고정: 도식 작업의 등록 본문은 params로 남고 목록 응답에 그대로 실린다. 새 도식에도 mode가 "create"로 있다
# (계획 리뷰 PR-05). 복구 화면이 작성 창의 시작값을 이 값으로 채운다
def test_diagram_job_params_reach_the_job_list_with_the_create_mode(diagram_input, store):
    _, _, payload = diagram_input
    with TestClient(create_app(store, provider=DiagramProvider(payload)), headers=HEADERS) as client:
        etag = f'"{store.deck_etag("diagram")}"'
        job = client.post("/api/projects/diagram/jobs", json={"request_id": "diagram-0001", "kind": "diagram",
                                                              "params": DIAGRAM_REQUEST}, headers={"If-Match": etag})
        assert job.status_code == 202, job.text
        assert client.app.state.job_runner._handles[job.json()["id"]].wait_sync(10) is not None
        listed = next(j for j in client.get("/api/projects/diagram/jobs").json() if j["id"] == job.json()["id"])
    assert listed["candidate_status"] == "held"
    assert listed["params"]["mode"] == "create"
    assert {k: listed["params"][k] for k in DIAGRAM_REQUEST} == DIAGRAM_REQUEST
    assert listed["target"] == DIAGRAM_REQUEST["chapter_id"]


# -- 같은 이름으로 다시 만든 프로젝트의 반영 기록 (최종 리뷰 ST-01, C2 계획 4.4 (10), 사용자 결정 Q4 A) -----------------
# 반영 기록은 원장에 프로젝트 이름을 열쇠로 남고 폴더를 지워도 남는다. 기록은 지우지 않고(원장 무삭제 전제) 생성 때 reset을
# 더해 새 프로젝트를 이전 기준에서 떼어 낸다. 이미 있는 이름이면 생성이 거절되므로 reset을 쓰지 않는다(리뷰 PR-02)

def _applied_then(client, store):
    _save_slide(store, {"chapter_id": "c1", "slots": slots("처음")})
    job = _job(client, "chapter-0001")
    assert _apply(client, store, job["id"]).status_code == 200
    return client.app.state.job_runner.ledger


def test_recreating_a_deleted_project_name_starts_without_the_old_baseline(store):
    import shutil
    _project(store)
    with TestClient(create_app(store, provider=ChapterProvider([slots("A")])), headers=HEADERS) as client:
        ledger = _applied_then(client, store)
        assert ledger.last_apply("p1", "c1")[0] == "applied"
        shutil.rmtree(store.root / "p1")  # 사용자가 폴더를 지웠다
        created = client.post("/api/projects", json={"name": "p1", "title": "새 보고"})
        record = ledger.last_apply("p1", "c1")
    assert created.status_code == 201, created.text
    assert record == ("reset", None)


def test_creating_an_existing_project_name_is_refused_and_keeps_its_baseline(store):
    _project(store)
    with TestClient(create_app(store, provider=ChapterProvider([slots("A")])), headers=HEADERS) as client:
        ledger = _applied_then(client, store)
        refused = client.post("/api/projects", json={"name": "p1", "title": "같은 이름"})
        record = ledger.last_apply("p1", "c1")
    assert refused.status_code == 409
    assert record is not None and record[0] == "applied"


def test_ledger_write_failure_at_creation_creates_no_folder(store, monkeypatch):
    from slidecaptain.storage.job_ledger import LedgerError
    with TestClient(create_app(store), headers=HEADERS) as client:
        ledger = client.app.state.job_runner.ledger
        ledger.record_apply("p9", "c1", "job-x", {"conclusion": "옛"})

        def fail(project, chapter_ids):
            raise LedgerError("시험 주입")
        monkeypatch.setattr(ledger, "record_reset", fail)
        response = client.post("/api/projects", json={"name": "p9", "title": "보고"})
    assert response.status_code == 503, response.text
    assert not (store.root / "p9").exists()
