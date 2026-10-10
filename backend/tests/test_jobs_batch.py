"""장 생성 묶음 작업 (개정판 D2b-4, 계획서 2.1, 5.3, 5.6, 5.7).

지금 승인 루프는 화면이 장마다 생성 요청을 보내고 결과를 메모리에 둔 채 저장한다. 그래서 앱이 저장 중이나
응답 직전에 죽으면 결과와 진행 표시가 사라지고, 제공자 오류 뒤에도 남은 장마다 요청을 보낸다. 여기 시험은
서버 묶음 작업이 이 동작을 바꿨음을 겨냥한다. 재시작 시험은 강제 종료 직후의 원장 상태를 직접 만든 뒤
같은 폴더의 새 앱이 이어받게 한다(실제 프로세스를 죽이는 관통은 D2b-6). 실제 AI 호출은 없다.
"""

import asyncio
import json
import threading
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from slidecaptain.models.deck import Slide
from slidecaptain.pipeline.provider import ProviderCallFailed, ProviderResponse
from slidecaptain.pipeline.rewrite import sources_fingerprint
from slidecaptain.pipeline.story import StaleStoryPlan
from slidecaptain.server.app import create_app
from tests.test_jobs_api import manager  # noqa: F401 (픽스처)
from slidecaptain.storage.job_ledger import (
    BATCH_KIND, FixedInputs, JobLedger, LedgerError, TransitionRejected, parent_outcome,
)

HEADERS = {"X-Requested-With": "SlideCaptain", "X-AI-Consent": "SlideCaptain"}
SOURCES = {"리서치.md": "시장 규모는 500억 원이다"}


def slots(text):
    return {"template": "bullet_box", "bullets": [{"text": text, "level": 0}], "conclusion": text, "footnote": ""}


class ChapterProvider:
    """호출마다 정해진 응답을 돌려준다. gate_at 번째 호출은 관문에서 멈춘다. 다른 스레드에서 불려도 안전하다."""

    def __init__(self, answers, gate_at=None):
        self.answers = list(answers)
        self.calls = 0
        self.gate_at = gate_at
        self.entered, self.release = threading.Event(), threading.Event()

    async def complete(self, prompt, schema):
        index = self.calls
        self.calls += 1
        if index == self.gate_at:
            self.entered.set()
            while not self.release.is_set():
                await asyncio.sleep(0.01)
        answer = self.answers[min(index, len(self.answers) - 1)]
        if isinstance(answer, BaseException):
            raise answer
        return ProviderResponse(structured=deepcopy(answer), raw_text="r")


def _project(store, count=3):
    store.create_project("p1", "보고")
    for name, text in SOURCES.items():
        store.write_source("p1", name, text)
    deck = store.load_deck("p1")
    deck = deck.model_validate({**deck.model_dump(mode="json"), "structure": {"chapters": [
        {"id": f"c{i}", "topic": f"주제 {i}", "conclusion": "결론", "template": "bullet_box",
         "source_refs": ["리서치.md"]} for i in range(1, count + 1)]}})
    store.save_deck("p1", deck, snapshot=False)
    return deck


def _register(client, store, chapter_ids, request_id="batch-0001", if_match=True):
    headers = {"If-Match": f'"{store.deck_etag("p1")}"'} if if_match else {}
    return client.post("/api/projects/p1/jobs", json={"request_id": request_id, "kind": BATCH_KIND,
                                                      "params": {"chapter_ids": chapter_ids}}, headers=headers)


def _wait(client, job_id, timeout=15):
    handle = client.app.state.job_runner._handles[job_id]
    assert handle.wait_sync(timeout) is not None, "묶음이 끝나지 않았습니다"
    return client.get(f"/api/projects/p1/jobs/{job_id}").json()


def _states(view):
    return [(c["chapter_id"], c["state"], c["candidate_status"]) for c in view["chapters"]]


# 고정: 지금 승인 루프와 같은 덱

def test_batch_applies_chapters_in_order_like_the_old_loop(store):
    _project(store)
    snapshots_before = store.list_snapshots("p1")
    provider = ChapterProvider([slots("하나 100억"), slots("둘"), slots("셋")])
    with TestClient(create_app(store, provider=provider), headers=HEADERS) as client:
        job = _register(client, store, ["c1", "c2", "c3"])
        assert job.status_code == 202
        view = _wait(client, job.json()["id"])
        rows = client.app.state.job_runner.ledger.chapters(job.json()["id"])
        assert client.get("/api/status").json()["last_generation_at"] is not None  # 리뷰 R9 M5
    # 저장 직전에 남긴 적용 대상 ETag가 실제 저장 결과와 같다(재시작 판정의 근거, 계획서 5.7 ④)
    assert all(r.apply_target_etag and r.apply_target_etag == r.applied_etag for r in rows)
    # 실행 경로가 장마다 원격 호출 시각을 남긴다. 재시작 분류의 근거다 (D2b-4 리뷰 R9 M1)
    assert all(r.remote_sent_at for r in rows)
    assert rows[-1].applied_etag == store.deck_etag("p1")
    deck = store.load_deck("p1")
    assert [s.chapter_id for s in deck.slides] == ["c1", "c2", "c3"]
    assert all(s.eyebrow == "" and s.subtitle == "" for s in deck.slides)
    assert view["state"] == "succeeded" and view["outcome"] == "all_applied"
    assert _states(view) == [(f"c{i}", "succeeded", "applied") for i in (1, 2, 3)]
    # 화면이 모으던 사용량과 미검증 숫자는 장별 결과에 남는다
    assert all(c["result"]["usage"] is not None for c in view["chapters"])
    assert "100" in "".join(view["chapters"][0]["result"]["unverified_numbers"])
    usage = (store.root / "p1" / "ai-usage.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(usage) == 3
    # 지금 승인 루프처럼 장 저장은 스냅샷을 만들지 않는다 (리뷰 R9 M18)
    assert store.list_snapshots("p1") == snapshots_before


@pytest.mark.parametrize("case, status", [
    ("no_if_match", 428), ("stale_if_match", 412), ("missing", 404), ("duplicate", 422), ("no_sources", 422),
    ("diagram", 422), ("filled", 409), ("stale_plan", 409),
])
def test_registration_checks_create_no_rows(store, case, status, monkeypatch):
    deck = _project(store)
    if case == "no_sources":
        (store.root / "p1" / "sources" / "리서치.md").unlink()
    if case == "diagram":  # 도식 장은 묶음으로 생성하지 않는다 (리뷰 R9 M15). 등록 검사가 읽는 덱만 바꾼다
        load = store.load_deck_with_etag

        def with_diagram(name):
            loaded, etag = load(name)
            chapters = [loaded.structure.chapters[0].model_copy(update={"template": "diagram"}),
                        *loaded.structure.chapters[1:]]
            return loaded.model_copy(update={"structure": loaded.structure.model_copy(
                update={"chapters": chapters})}), etag
        monkeypatch.setattr(store, "load_deck_with_etag", with_diagram)
    if case == "filled":  # 이미 내용이 있는 장은 호출 비용을 쓰기 전에 거절한다 (리뷰 R10)
        store.save_deck("p1", deck.model_copy(update={"slides": [Slide.model_validate(
            {"chapter_id": "c1", "slots": slots("이미 있음")})]}), snapshot=False)
    if case == "stale_plan":  # 리뷰 R9 M16
        monkeypatch.setattr("slidecaptain.server.app.require_current_story",
                            lambda deck, sources: (_ for _ in ()).throw(StaleStoryPlan("보고 계획이 바뀌었습니다.")))
    ids = {"missing": ["c1", "c9"], "duplicate": ["c1", "c1"], "filled": ["c1", "c2"]}.get(case, ["c1"])
    with TestClient(create_app(store, provider=ChapterProvider([slots("x")])), headers=HEADERS) as client:
        if case == "stale_if_match":
            response = client.post("/api/projects/p1/jobs", json={
                "request_id": "batch-0002", "kind": BATCH_KIND, "params": {"chapter_ids": ids}},
                headers={"If-Match": '"old"'})
        else:
            response = _register(client, store, ids, if_match=case != "no_if_match")
        assert response.status_code == status, response.text
        assert client.app.state.job_runner.ledger.list_jobs("p1") == []


def test_format_error_chapter_fails_and_the_next_chapter_continues(store):
    _project(store)
    bad = {"template": "bullet_box"}  # 형식 오류: 재시도 1회까지 같은 응답
    provider = ChapterProvider([slots("하나"), bad, bad, slots("셋")])
    with TestClient(create_app(store, provider=provider), headers=HEADERS) as client:
        view = _wait(client, _register(client, store, ["c1", "c2", "c3"]).json()["id"])
    assert [s for s in _states(view)] == [("c1", "succeeded", "applied"), ("c2", "failed", "none"),
                                          ("c3", "succeeded", "applied")]
    assert view["chapters"][1]["error"]["error_class"] == "ai_output"
    assert view["chapters"][1]["result"]["raw_text"] == "r"  # 원문을 남긴다
    assert view["state"] == "failed" and view["outcome"] == "partial"


# 필수 RED 4: 지금 루프는 제공자 오류 뒤에도 남은 장마다 요청을 보낸다

def test_provider_failure_mid_batch_stops_the_remaining_chapters(store):
    _project(store)
    provider = ChapterProvider([slots("하나"), ProviderCallFailed("로그인이 만료되었습니다."), slots("셋")])
    with TestClient(create_app(store, provider=provider), headers=HEADERS) as client:
        view = _wait(client, _register(client, store, ["c1", "c2", "c3"]).json()["id"])
    assert provider.calls == 2
    assert _states(view) == [("c1", "succeeded", "applied"), ("c2", "failed", "none"), ("c3", "interrupted", "none")]
    assert view["chapters"][1]["error"]["error_class"] == "connection"
    assert view["chapters"][2]["error"]["code"] == "provider_failed"
    assert [s.chapter_id for s in store.load_deck("p1").slides] == ["c1"]


def test_stale_story_plan_holds_the_remaining_chapters(store):
    _project(store)
    provider = ChapterProvider([slots("하나"), StaleStoryPlan("보고 계획이 바뀌었습니다."), slots("셋")])
    with TestClient(create_app(store, provider=provider), headers=HEADERS) as client:
        view = _wait(client, _register(client, store, ["c1", "c2", "c3"]).json()["id"])
    assert view["chapters"][1]["error"]["code"] == "stale_story_plan"
    assert view["chapters"][2]["state"] == "interrupted" and view["chapters"][2]["error"]["code"] == "held_stale_plan"
    assert view["outcome"] == "held_stale_plan"


# 필수 RED 6의 묶음 쪽: 늦게 도착한 결과가 다른 저장을 덮지 않는다

def test_late_answer_after_another_save_is_kept_as_a_stale_candidate(store):
    deck = _project(store)
    provider = ChapterProvider([slots("하나"), slots("둘"), slots("셋")], gate_at=1)
    with TestClient(create_app(store, provider=provider), headers=HEADERS) as client:
        job = _register(client, store, ["c1", "c2", "c3"]).json()
        assert provider.entered.wait(10)
        current = store.load_deck("p1")
        current.meta.presenter = "다른 창의 편집"
        store.save_deck("p1", current, snapshot=False)
        provider.release.set()
        view = _wait(client, job["id"])
    saved = store.load_deck("p1")
    assert saved.meta.presenter == "다른 창의 편집" and [s.chapter_id for s in saved.slides] == ["c1"]
    assert _states(view) == [("c1", "succeeded", "applied"), ("c2", "failed", "stale"), ("c3", "interrupted", "none")]
    assert view["state"] == "failed" and view["outcome"] == "chain_broken"
    assert provider.calls == 2


def test_cancel_mid_batch_keeps_applied_chapters_and_cancels_the_rest(store):
    _project(store)
    provider = ChapterProvider([slots("하나"), slots("둘"), slots("셋")], gate_at=1)
    with TestClient(create_app(store, provider=provider), headers=HEADERS) as client:
        job = _register(client, store, ["c1", "c2", "c3"]).json()
        assert provider.entered.wait(10)
        client.post(f"/api/projects/p1/jobs/{job['id']}/cancel")
        view = _wait(client, job["id"])
    assert _states(view) == [("c1", "succeeded", "applied"), ("c2", "cancelled", "none"), ("c3", "cancelled", "none")]
    assert view["state"] == "cancelled" and view["outcome"] == "cancelled"
    assert [s.chapter_id for s in store.load_deck("p1").slides] == ["c1"]


# 필수 RED 1과 2: 저장 중 종료, 강제 종료 직전 완료. 지금 루프는 화면 메모리의 결과를 잃는다

def _crashed_batch(store, deck, layout):
    """다른 실행이 남긴 묶음 행을 만든다. layout: 장마다 (상태, 결과 여부, 원격 호출 여부)."""
    ledger = JobLedger.open(store.root)
    etag = store.deck_etag("p1")
    ids = [cid for cid, *_ in layout]
    job, _ = ledger.create_job(project="p1", kind=BATCH_KIND, request_id="crashed-0001", params={"chapter_ids": ids},
                               instance_id="previous", inputs=FixedInputs(None, None, None, etag,
                                                                          sources_fingerprint(SOURCES), None),
                               chapter_ids=ids)
    ledger.transition(job.id, expected="queued", new="running", remote_sent_at="t")
    for cid, state, extra in layout:
        if state == "queued":
            continue
        ledger.transition_chapter(job.id, cid, expected="queued", new="running",
                                  remote_sent_at="t" if extra.get("sent", True) else None)
        if state == "validating":
            ledger.transition_chapter(job.id, cid, expected="running", new="validating",
                                      result={"status": "ok", "slots": extra["slots"], "raw_text": ""},
                                      candidate_status="held")
            if "target" in extra:
                ledger.update_chapter(job.id, cid, expected="validating", apply_target_etag=extra["target"])
    ledger.close()
    return job.id, etag


def _restart(store):
    provider = ChapterProvider([slots("재호출되면 안 됨")])
    return provider, TestClient(create_app(store, provider=provider, data_dir_lock="held"), headers=HEADERS)


@pytest.mark.parametrize("crash", ["before_target", "between_target_and_save"])
def test_restart_resumes_the_apply_without_calling_again(store, crash):
    deck = _project(store)
    extra = {"slots": slots("보존된 결과")}
    if crash == "between_target_and_save":
        target_deck = deck.model_copy(update={"slides": [Slide.model_validate(
            {"chapter_id": "c1", "slots": extra["slots"]})]})
        extra["target"] = store.etag_for(target_deck)
    job_id, _ = _crashed_batch(store, deck, [("c1", "validating", extra), ("c2", "queued", {})])
    provider, client = _restart(store)
    with client:
        view = client.get(f"/api/projects/p1/jobs/{job_id}").json()
    assert provider.calls == 0
    assert [s.chapter_id for s in store.load_deck("p1").slides] == ["c1"]
    assert _states(view) == [("c1", "succeeded", "applied"), ("c2", "interrupted", "none")]
    assert view["state"] == "failed" and view["outcome"] == "partial"


def test_restart_after_the_save_marks_the_chapter_applied(store):
    deck = _project(store)
    extra = {"slots": slots("보존된 결과")}
    target_deck = deck.model_copy(update={"slides": [Slide.model_validate({"chapter_id": "c1", "slots": extra["slots"]})]})
    extra["target"] = store.etag_for(target_deck)
    job_id, _ = _crashed_batch(store, deck, [("c1", "validating", extra)])
    store.save_deck("p1", target_deck, snapshot=False)  # ⑤ 저장은 끝났고 ⑥ 기록 전에 죽었다
    assert store.deck_etag("p1") == extra["target"]
    provider, client = _restart(store)
    with client:
        view = client.get(f"/api/projects/p1/jobs/{job_id}").json()
    assert provider.calls == 0 and [s.chapter_id for s in store.load_deck("p1").slides] == ["c1"]
    assert view["state"] == "succeeded" and view["outcome"] == "all_applied"


def test_restart_marks_a_sent_chapter_without_result_as_unknown(store):
    deck = _project(store)
    job_id, _ = _crashed_batch(store, deck, [("c1", "running", {"sent": True}), ("c2", "queued", {})])
    provider, client = _restart(store)
    with client:
        view = client.get(f"/api/projects/p1/jobs/{job_id}").json()
    assert provider.calls == 0
    assert _states(view) == [("c1", "remote_completion_unknown", "none"), ("c2", "interrupted", "none")]
    assert view["state"] == "failed" and store.load_deck("p1").slides == []


def test_restart_without_the_lock_leaves_the_batch_alone(store):
    deck = _project(store)
    job_id, _ = _crashed_batch(store, deck, [("c1", "validating", {"slots": slots("보존")})])
    with TestClient(create_app(store, provider=ChapterProvider([slots("x")]), data_dir_lock="unsupported"),
                    headers=HEADERS) as client:
        view = client.get(f"/api/projects/p1/jobs/{job_id}").json()
    assert view["state"] == "running" and store.load_deck("p1").slides == []


# 묶음 부모의 종결 규칙 (계획서 5.3의 α 묶음 리뷰 A3 정정)

def _finished_batch(tmp_path, chapter_states):
    ledger = JobLedger.open(tmp_path)
    ids = [f"c{i}" for i in range(len(chapter_states))]
    job, _ = ledger.create_job(project="p1", kind=BATCH_KIND, request_id="r", params={"chapter_ids": ids},
                               instance_id="i", inputs=FixedInputs(None, None, None, "e0", None, None), chapter_ids=ids)
    ledger.transition(job.id, expected="queued", new="running", remote_sent_at="t")
    for cid, state in zip(ids, chapter_states):
        if state == "succeeded":
            ledger.transition_chapter(job.id, cid, expected="queued", new="running", remote_sent_at="t")
            ledger.transition_chapter(job.id, cid, expected="running", new="validating")
            ledger.transition_chapter(job.id, cid, expected="validating", new="succeeded")
        else:
            ledger.transition_chapter(job.id, cid, expected="queued", new=state)
    return ledger, job.id


def test_cancel_requested_parent_with_all_chapters_applied_succeeds(tmp_path):
    ledger, job_id = _finished_batch(tmp_path, ["succeeded", "succeeded"])
    ledger.transition(job_id, expected="running", new="cancel_requested")
    state, outcome = parent_outcome(ledger.chapters(job_id), "cancel_requested")
    assert (state, outcome) == ("succeeded", "all_applied")
    assert ledger.finish_parent(job_id, expected="cancel_requested", new=state, outcome=outcome).state == "succeeded"
    ledger.close()


def test_cancel_requested_parent_with_unfinished_work_is_cancelled(tmp_path):
    ledger, job_id = _finished_batch(tmp_path, ["succeeded", "interrupted"])
    assert parent_outcome(ledger.chapters(job_id), "cancel_requested") == ("cancelled", "cancelled")
    assert parent_outcome(ledger.chapters(job_id), "running") == ("failed", "partial")
    ledger.close()


def test_finish_parent_refuses_unfinished_chapters_and_other_kinds(tmp_path):
    ledger = JobLedger.open(tmp_path)
    job, _ = ledger.create_job(project="p1", kind=BATCH_KIND, request_id="r", params={"chapter_ids": ["c1"]},
                               instance_id="i", inputs=FixedInputs(None, None, None, "e0", None, None),
                               chapter_ids=["c1"])
    ledger.transition(job.id, expected="queued", new="running", remote_sent_at="t")
    with pytest.raises(TransitionRejected):
        ledger.finish_parent(job.id, expected="running", new="failed", outcome="partial")
    other, _ = ledger.create_job(project="p1", kind="structure", request_id="s", params={}, instance_id="i",
                                 inputs=FixedInputs(None, None, None, None, None, None))
    ledger.transition(other.id, expected="queued", new="running", remote_sent_at="t")
    with pytest.raises(TransitionRejected):
        ledger.finish_parent(other.id, expected="running", new="failed", outcome="partial")
    ledger.close()


# D2b-4 리뷰 R7: 낡음이 마지막 장에서 나면 남은 장이 없어도 보류로 끝난다

@pytest.mark.parametrize("count", [1, 2])
def test_stale_story_plan_on_the_last_chapter_is_still_held(store, count):
    _project(store, count)
    provider = ChapterProvider([slots("하나")] * (count - 1) + [StaleStoryPlan("보고 계획이 바뀌었습니다.")])
    with TestClient(create_app(store, provider=provider), headers=HEADERS) as client:
        view = _wait(client, _register(client, store, [f"c{i}" for i in range(1, count + 1)]).json()["id"])
    assert view["chapters"][-1]["error"]["code"] == "stale_story_plan"
    assert view["state"] == "failed" and view["outcome"] == "held_stale_plan"


# D2b-4 리뷰 R5: 장 후보를 버리면 그 묶음이 후보 때문에 목록에 남지 않는다

def test_a_stale_chapter_candidate_can_be_dismissed(store):
    _project(store)
    provider = ChapterProvider([slots("하나"), slots("둘"), slots("셋")], gate_at=1)
    with TestClient(create_app(store, provider=provider), headers=HEADERS) as client:
        job = _register(client, store, ["c1", "c2", "c3"]).json()
        assert provider.entered.wait(10)
        current = store.load_deck("p1")
        current.meta.presenter = "다른 창의 편집"
        store.save_deck("p1", current, snapshot=False)
        provider.release.set()
        _wait(client, job["id"])
        url = f"/api/projects/p1/jobs/{job['id']}/candidate"
        # 장 후보는 버리기만 하고, 없는 장과 후보 없는 장은 거절한다
        assert client.post(url, json={"action": "applied", "chapter_id": "c2"}).status_code == 422
        assert client.post(url, json={"action": "dismissed", "chapter_id": "c9"}).status_code == 404
        assert client.post(url, json={"action": "dismissed", "chapter_id": "c3"}).status_code == 409
        later = _register(client, store, ["c3"], request_id="batch-0002").json()
        _wait(client, later["id"])
        ids = [j["id"] for j in client.get("/api/projects/p1/jobs").json()]
        assert job["id"] in ids  # 버리기 전에는 stale 장 후보 때문에 지난 묶음도 목록에 남는다
        response = client.post(url, json={"action": "dismissed", "chapter_id": "c2"})
        assert response.status_code == 200
        assert _states(response.json())[1] == ("c2", "failed", "dismissed")
        assert client.post(url, json={"action": "dismissed", "chapter_id": "c2"}).status_code == 409
        ids = [j["id"] for j in client.get("/api/projects/p1/jobs").json()]
    assert job["id"] not in ids and later["id"] in ids


def test_chapter_candidates_are_dismissed_only_on_batches(store):
    _project(store)
    with TestClient(create_app(store, provider=ChapterProvider([slots("하나")])), headers=HEADERS) as client:
        job = client.post("/api/projects/p1/jobs", json={"request_id": "chapter-0001", "kind": "chapter",
                                                         "params": {"chapter_id": "c1"}},
                          headers={"If-Match": f'"{store.deck_etag("p1")}"'}).json()
        _wait(client, job["id"])
        response = client.post(f"/api/projects/p1/jobs/{job['id']}/candidate",
                               json={"action": "dismissed", "chapter_id": "c1"})
    assert response.status_code == 422


# D2b-4 리뷰 R1: 적용 단계의 예상 밖 예외도 이 실행 안에서 묶음을 끝낸다

def _fail_once(ledger, method, when):
    """원장 메서드를 한 번만 LedgerError로 실패시킨다. when(kwargs)이 참인 호출에서."""
    original, fired = getattr(ledger, method), []

    def wrapper(*args, **kwargs):
        if not fired and when(kwargs):
            fired.append(True)
            raise LedgerError("주입한 원장 쓰기 실패")
        return original(*args, **kwargs)
    setattr(ledger, method, wrapper)
    return fired


@pytest.mark.parametrize("point", ["target", "success"])
def test_ledger_failure_while_applying_still_finishes_the_batch(store, point):
    _project(store)
    provider = ChapterProvider([slots("하나"), slots("둘"), slots("셋")])
    with TestClient(create_app(store, provider=provider), headers=HEADERS) as client:
        runner = client.app.state.job_runner
        if point == "target":  # ④ 적용 대상 ETag 기록 실패: 저장하지 않고 그 장을 적용 실패로 닫는다
            fired = _fail_once(runner.ledger, "update_chapter", lambda kw: "apply_target_etag" in kw)
        else:  # ⑤ 저장 뒤 ⑥ 성공 기록 실패: 실행 안의 조정이 저장을 확인해 적용됨으로 둔다
            fired = _fail_once(runner.ledger, "transition_chapter", lambda kw: kw.get("new") == "succeeded")
        job = _register(client, store, ["c1", "c2", "c3"]).json()
        view = _wait(client, job["id"])
        assert fired and not runner.is_busy() and client.get("/api/jobs/active").json()["active"] is None
        later = _register(client, store, ["c3"], request_id="batch-0002")
        assert later.status_code == 202
        _wait(client, later.json()["id"])
    assert view["state"] not in ("queued", "running", "validating", "cancel_requested")
    assert all(c["state"] not in ("queued", "running", "validating", "cancel_requested") for c in view["chapters"])
    if point == "target":
        assert view["chapters"][0]["state"] == "failed" and view["chapters"][0]["error"]["code"] == "apply_failed"
        assert view["chapters"][0]["error"]["error_class"] == "ledger"  # 원장 쓰기 실패는 ledger (D3a-4, 지금: input)
        assert view["chapters"][0]["candidate_status"] == "held"  # 결과는 후보로 남는다
    else:
        assert _states(view)[0] == ("c1", "succeeded", "applied")
        assert view["chapters"][1]["state"] == "interrupted"


# D2b-4 리뷰 R2: 적용 중 취소가 오면 적용은 끝내고 남은 장은 취소로 닫는다

@pytest.mark.parametrize("save", ["ok", "fails"])
def test_cancel_during_apply_finishes_the_apply_and_cancels_the_rest(store, monkeypatch, save):
    _project(store)
    entered, release = threading.Event(), threading.Event()
    original = store.save_deck

    def gated_save(*args, **kwargs):
        if not entered.is_set():
            entered.set()
            assert release.wait(10)
            if save == "fails":  # 적용이 실패해도 남은 장은 취소다
                raise OSError("디스크 오류")
        return original(*args, **kwargs)
    monkeypatch.setattr(store, "save_deck", gated_save)
    provider = ChapterProvider([slots("하나"), slots("둘"), slots("셋")])
    with TestClient(create_app(store, provider=provider), headers=HEADERS) as client:
        job = _register(client, store, ["c1", "c2", "c3"]).json()
        assert entered.wait(10)
        # 취소 응답의 조회는 프로젝트 잠금을 기다리므로 다른 스레드에서 보내고, 취소가 전달된 뒤 저장을 푼다
        handle = client.app.state.job_runner._handles[job["id"]]
        canceller = threading.Thread(target=lambda: client.post(f"/api/projects/p1/jobs/{job['id']}/cancel"))
        canceller.start()
        for _ in range(500):
            if handle.cancel_sent:
                break
            threading.Event().wait(0.01)
        assert handle.cancel_sent
        release.set()
        canceller.join(10)
        view = _wait(client, job["id"])
        status = client.get("/api/status").json()
    first = ("c1", "succeeded", "applied") if save == "ok" else ("c1", "failed", "held")
    assert _states(view) == [first, ("c2", "cancelled", "none"), ("c3", "cancelled", "none")]
    assert view["state"] == "cancelled" and view["outcome"] == "cancelled"
    assert [s.chapter_id for s in store.load_deck("p1").slides] == (["c1"] if save == "ok" else [])
    if save == "ok":
        assert status["last_generation_at"] is not None  # 적용된 장의 성공도 기록한다


# D2b-4 리뷰 R3: 원격 호출 시각을 남기지 못하면 호출하지 않고 원장 오류로 기록한다

def test_ledger_failure_before_the_call_is_recorded_as_a_ledger_error(store):
    _project(store)
    provider = ChapterProvider([slots("하나"), slots("둘")])
    with TestClient(create_app(store, provider=provider), headers=HEADERS) as client:
        _fail_once(client.app.state.job_runner.ledger, "update_chapter", lambda kw: "remote_sent_at" in kw)
        view = _wait(client, _register(client, store, ["c1", "c2"]).json()["id"])
    assert provider.calls == 0
    assert view["chapters"][0]["error"] == {"error_class": "ledger", "status": 503,
                                            "detail": "작업 기록을 쓰지 못했습니다. 잠시 뒤 다시 시도해 주세요.",
                                            "code": "ledger_write_failed",
                                            "raw_error_class": None}  # 다시 씀(D3a-4): 읽기 관대화의 원래 값 칸
    assert view["chapters"][1]["state"] == "interrupted" and view["chapters"][1]["error"]["code"] == "ledger_failed"


# D2b-4 리뷰 R6: 취소 요청 뒤 제공자가 오류나 값으로 끝나도 취소로 닫고 적용하지 않는다

class CancelEndingProvider(ChapterProvider):
    """관문에서 취소를 받으면 CancelledError 대신 정해진 오류나 값으로 끝난다."""

    def __init__(self, answers, gate_at, on_cancel):
        super().__init__(answers, gate_at)
        self.on_cancel = on_cancel

    async def complete(self, prompt, schema):
        try:
            return await super().complete(prompt, schema)
        except asyncio.CancelledError:
            if isinstance(self.on_cancel, BaseException):
                raise self.on_cancel from None
            return ProviderResponse(structured=deepcopy(self.on_cancel), raw_text="r")


@pytest.mark.parametrize("ending", ["error", "value"])
def test_cancel_ending_with_an_error_or_a_value_is_still_cancelled(store, ending):
    _project(store)
    on_cancel = ProviderCallFailed("연결을 정리하다 실패했습니다.") if ending == "error" else slots("늦은 값")
    provider = CancelEndingProvider([slots("하나"), slots("둘"), slots("셋")], gate_at=1, on_cancel=on_cancel)
    with TestClient(create_app(store, provider=provider), headers=HEADERS) as client:
        job = _register(client, store, ["c1", "c2", "c3"]).json()
        assert provider.entered.wait(10)
        client.post(f"/api/projects/p1/jobs/{job['id']}/cancel")
        view = _wait(client, job["id"])
    assert [s.chapter_id for s in store.load_deck("p1").slides] == ["c1"]  # 취소 뒤 값은 적용하지 않는다
    expected_candidate = "held" if ending == "value" else "none"
    assert _states(view) == [("c1", "succeeded", "applied"), ("c2", "cancelled", expected_candidate),
                             ("c3", "cancelled", "none")]
    assert view["chapters"][1]["error"]["error_class"] == "cancelled"
    if ending == "error":
        assert view["chapters"][1]["error"]["detail"] == "연결을 정리하다 실패했습니다."
    assert view["state"] == "cancelled" and view["outcome"] == "cancelled"


# D2b-4 리뷰 R4: 원장의 결과가 지금 슬롯 형식에 맞지 않아도 앱은 시작하고 그 장을 닫는다

@pytest.mark.parametrize("path", ["resume", "changed"])
def test_restart_with_an_unreadable_result_still_starts(store, path):
    deck = _project(store)
    bad = {"template": "bullet_box", "bullets": "목록이 아님", "conclusion": "", "footnote": ""}
    extra = {"slots": bad} if path == "resume" else {"slots": bad, "target": "적용 뒤 다른 저장이 덮은 ETag"}
    job_id, _ = _crashed_batch(store, deck, [("c1", "validating", extra), ("c2", "queued", {})])
    if path == "changed":  # 저장본에 그 장의 슬라이드가 있어 결과 슬롯과 비교하는 경로
        store.save_deck("p1", deck.model_copy(update={"slides": [Slide.model_validate(
            {"chapter_id": "c1", "slots": slots("다른 내용")})]}), snapshot=False)
    provider, client = _restart(store)
    with client:
        view = client.get(f"/api/projects/p1/jobs/{job_id}").json()
    assert provider.calls == 0
    assert view["chapters"][0]["state"] == "failed"
    assert view["chapters"][0]["error"]["code"] == ("apply_failed" if path == "resume" else "result_unreadable")
    assert view["chapters"][0]["error"]["error_class"] == "storage"  # 저장과 결과 읽기 실패 (D3a-4, 지금: input)
    assert view["state"] not in ("queued", "running", "validating", "cancel_requested")



# D2b-4 리뷰 R9: 사슬 검사와 실행 전 재비교, 재시작 조정의 남은 경우

def test_sources_changed_during_a_chapter_keeps_its_result_as_a_stale_candidate(store):
    _project(store)
    provider = ChapterProvider([slots("하나"), slots("둘"), slots("셋")], gate_at=1)
    with TestClient(create_app(store, provider=provider), headers=HEADERS) as client:
        job = _register(client, store, ["c1", "c2", "c3"]).json()
        assert provider.entered.wait(10)
        store.write_source("p1", "추가.md", "새 자료")  # 덱은 그대로, 자료만 바뀐다 (M10)
        provider.release.set()
        view = _wait(client, job["id"])
    assert _states(view)[:2] == [("c1", "succeeded", "applied"), ("c2", "failed", "stale")]
    assert [s.chapter_id for s in store.load_deck("p1").slides] == ["c1"]


def test_a_save_between_chapters_stops_before_the_next_call(store, monkeypatch):
    """장과 장 사이에 다른 저장이 끼면 다음 장을 보내지 않는다 (리뷰 R11)."""
    _project(store)
    original, saves = store.save_deck, []

    def save_then_edit(*args, **kwargs):
        saved = original(*args, **kwargs)
        if not saves:
            saves.append(True)
            current = store.load_deck("p1")
            current.meta.presenter = "다른 창의 편집"
            return original("p1", current, snapshot=False) and saved
        return saved
    monkeypatch.setattr(store, "save_deck", save_then_edit)
    provider = ChapterProvider([slots("하나"), slots("둘"), slots("셋")])
    with TestClient(create_app(store, provider=provider), headers=HEADERS) as client:
        view = _wait(client, _register(client, store, ["c1", "c2", "c3"]).json()["id"])
    assert provider.calls == 1
    assert _states(view) == [("c1", "succeeded", "applied"), ("c2", "interrupted", "none"), ("c3", "interrupted", "none")]
    assert view["chapters"][1]["error"]["code"] == "chain_broken"
    assert view["state"] == "failed" and view["outcome"] == "chain_broken"


def test_a_save_before_the_run_ends_the_batch_without_calls(store):
    """등록 뒤 실행 전에 다른 저장이 끼면 호출 0회로 끝나고 장에 같은 사유가 남는다 (리뷰 R9 M6, M20, R12)."""
    _project(store)
    provider = ChapterProvider([slots("하나")])
    with TestClient(create_app(store, provider=provider), headers=HEADERS) as client:
        runner = client.app.state.job_runner
        acquire = runner._acquire

        def acquire_after_another_save(*args, **kwargs):
            current = store.load_deck("p1")
            current.meta.presenter = "다른 창의 편집"
            store.save_deck("p1", current, snapshot=False)
            return acquire(*args, **kwargs)
        runner._acquire = acquire_after_another_save
        view = _wait(client, _register(client, store, ["c1", "c2"]).json()["id"])
    assert provider.calls == 0 and store.load_deck("p1").slides == []
    assert [c["state"] for c in view["chapters"]] == ["interrupted", "interrupted"]
    assert view["error"]["code"] and all(c["error"]["code"] == view["error"]["code"] for c in view["chapters"])


def test_restart_closes_a_batch_that_never_started(store):
    """부모가 queued인 채 끝난 묶음은 장과 부모를 모두 중단으로 닫는다 (리뷰 R9 M3)."""
    _project(store)
    ledger = JobLedger.open(store.root)
    job, _ = ledger.create_job(project="p1", kind=BATCH_KIND, request_id="queued-0001",
                               params={"chapter_ids": ["c1", "c2"]}, instance_id="previous",
                               inputs=FixedInputs(None, None, None, store.deck_etag("p1"),
                                                  sources_fingerprint(SOURCES), None), chapter_ids=["c1", "c2"])
    ledger.close()
    provider, client = _restart(store)
    with client:
        view = client.get(f"/api/projects/p1/jobs/{job.id}").json()
    assert provider.calls == 0 and view["state"] == "interrupted"
    assert [c["state"] for c in view["chapters"]] == ["interrupted", "interrupted"]


def test_restart_defers_when_the_deck_is_unreadable_and_resumes_later(store):
    """덱을 읽을 수 없으면 판정을 미루고, 고친 뒤 시작에서 호출 없이 적용한다 (리뷰 R9 M4)."""
    deck = _project(store)
    job_id, _ = _crashed_batch(store, deck, [("c1", "validating", {"slots": slots("보존")})])
    deck_file = store.root / "p1" / "deck.json"
    good = deck_file.read_bytes()
    deck_file.write_text("{깨진 덱", encoding="utf-8")
    provider, client = _restart(store)
    with client:
        view = client.get(f"/api/projects/p1/jobs/{job_id}").json()
    assert view["state"] == "running" and _states(view) == [("c1", "validating", "held")]
    deck_file.write_bytes(good)
    provider, client = _restart(store)
    with client:
        view = client.get(f"/api/projects/p1/jobs/{job_id}").json()
    assert provider.calls == 0 and _states(view) == [("c1", "succeeded", "applied")]
    assert [s.chapter_id for s in store.load_deck("p1").slides] == ["c1"]


def test_restart_marks_a_chapter_applied_even_if_the_deck_changed_after(store):
    """적용 뒤 다른 저장이 덱을 바꿨어도 그 장의 슬롯이 덱에 있으면 적용됨이다 (리뷰 R9 M9)."""
    deck = _project(store)
    extra = {"slots": slots("보존된 결과")}
    applied = deck.model_copy(update={"slides": [Slide.model_validate({"chapter_id": "c1", "slots": extra["slots"]})]})
    extra["target"] = store.etag_for(applied)
    job_id, _ = _crashed_batch(store, deck, [("c1", "validating", extra)])
    applied.meta.presenter = "적용 뒤 다른 창의 편집"
    store.save_deck("p1", applied, snapshot=False)
    provider, client = _restart(store)
    with client:
        view = client.get(f"/api/projects/p1/jobs/{job_id}").json()
    assert provider.calls == 0 and _states(view) == [("c1", "succeeded", "applied")]
    assert store.load_deck("p1").meta.presenter == "적용 뒤 다른 창의 편집"


def test_shutdown_does_not_resume_an_apply(store):
    """종료 처리는 적용을 재개하지 않고 다음 시작에 맡긴다 (계획서 5.5 ④, 리뷰 R9 M13)."""
    _project(store)
    with TestClient(create_app(store, provider=ChapterProvider([slots("x")])), headers=HEADERS) as client:
        runner = client.app.state.job_runner
        etag = store.deck_etag("p1")
        job, _ = runner.ledger.create_job(project="p1", kind=BATCH_KIND, request_id="mine-0001",
                                          params={"chapter_ids": ["c1"]}, instance_id=runner.instance_id,
                                          inputs=FixedInputs(None, None, None, etag, sources_fingerprint(SOURCES), None),
                                          chapter_ids=["c1"])
        runner.ledger.transition(job.id, expected="queued", new="running", remote_sent_at="t")
        runner.ledger.transition_chapter(job.id, "c1", expected="queued", new="running", remote_sent_at="t")
        runner.ledger.transition_chapter(job.id, "c1", expected="running", new="validating",
                                         result={"status": "ok", "slots": slots("보존"), "raw_text": ""},
                                         candidate_status="held")
        runner.shutdown(wait_seconds=0)
        assert runner.ledger.chapters(job.id)[0].state == "validating"
    assert store.load_deck("p1").slides == []


def test_a_batch_whose_project_is_gone_is_closed_at_restart(store):
    """프로젝트 폴더가 없어진 묶음은 미루지 않고 닫는다 (리뷰 R14)."""
    deck = _project(store)
    job_id, _ = _crashed_batch(store, deck, [("c1", "validating", {"slots": slots("보존")}), ("c2", "queued", {})])
    (store.root / "p1").rename(store.root / "p1-moved")
    provider, client = _restart(store)
    with client:
        row = client.app.state.job_runner.ledger.get_job(job_id)
        chapters = client.app.state.job_runner.ledger.chapters(job_id)
    assert row.state == "failed"
    # 결과가 있는 장은 결과를 남긴 실패로, 시작하지 않은 장은 재시작 규칙대로 중단으로 닫는다
    assert [(c.state, c.error_code, c.candidate_status) for c in chapters] == [
        ("failed", "project_missing", "held"), ("interrupted", None, "none")]
    assert chapters[0].error_class == "storage"  # 프로젝트 없음은 storage (D3a-4, 지금: input)


class SlowCancelProvider(ChapterProvider):
    """취소를 받아도 release가 올 때까지 정리하다가 취소로 끝난다(Claude 정리 최대 15초를 흉내 낸다)."""

    async def complete(self, prompt, schema):
        try:
            return await super().complete(prompt, schema)
        except asyncio.CancelledError:
            while not self.release.is_set():
                await asyncio.sleep(0.01)
            raise


def test_cancel_marks_the_running_chapter_as_cancel_requested_at_once(store):
    """취소를 전달하면 제공자가 끝나기 전에도 생성 중인 장이 취소 요청으로 보인다 (리뷰 R13)."""
    _project(store)
    provider = SlowCancelProvider([slots("하나"), slots("둘")], gate_at=0)
    with TestClient(create_app(store, provider=provider), headers=HEADERS) as client:
        job = _register(client, store, ["c1", "c2"]).json()
        assert provider.entered.wait(10)
        view = client.post(f"/api/projects/p1/jobs/{job['id']}/cancel").json()
        assert view["chapters"][0]["state"] == "cancel_requested"  # 제공자는 아직 정리 중이다
        provider.release.set()
        view = _wait(client, job["id"])
    assert _states(view) == [("c1", "cancelled", "none"), ("c2", "cancelled", "none")]


def test_registration_rejects_a_changed_selection_without_rows(store, manager):
    """화면이 본 AI 선택과 지금 선택이 다르면 등록 단계에서 409이고 행을 만들지 않는다 (리뷰 R9 M17)."""
    _project(store)
    with TestClient(create_app(store, ai_connections=manager), headers=HEADERS) as client:
        response = client.post("/api/projects/p1/jobs", json={
            "request_id": "batch-0009", "kind": BATCH_KIND, "params": {"chapter_ids": ["c1"]}},
            headers={"If-Match": f'"{store.deck_etag("p1")}"', "X-AI-Selection": "other-selection"})
        assert response.status_code == 409, response.text
        assert client.app.state.job_runner.ledger.list_jobs("p1") == []
    assert not any(c.calls for c in manager.connections.values())


def test_an_unexpected_error_while_saving_resumes_the_apply_in_process(store, monkeypatch):
    """저장 중 예상 밖 오류로 실행이 끝나면, 종료 중이 아닌 한 같은 실행 안에서 적용을 재개한다 (리뷰 R1)."""
    _project(store)
    original, failed = store.save_deck, []

    def fail_once(*args, **kwargs):
        if not failed:
            failed.append(True)
            raise RuntimeError("주입한 예상 밖 오류")
        return original(*args, **kwargs)
    monkeypatch.setattr(store, "save_deck", fail_once)
    provider = ChapterProvider([slots("하나"), slots("둘")])
    with TestClient(create_app(store, provider=provider), headers=HEADERS) as client:
        view = _wait(client, _register(client, store, ["c1", "c2"]).json()["id"])
        assert not client.app.state.job_runner.is_busy()
    assert failed and provider.calls == 1
    assert _states(view) == [("c1", "succeeded", "applied"), ("c2", "interrupted", "none")]
    assert [s.chapter_id for s in store.load_deck("p1").slides] == ["c1"]


def test_an_unfinished_chapter_candidate_cannot_be_dismissed(store):
    """적용 여부를 판정하지 못한 장의 후보를 버리면 다음 시작의 정리가 그 결과를 덱에 넣을 수 있다 (D2b-5c 리뷰 R6)."""
    deck = _project(store)
    job_id, _ = _crashed_batch(store, deck, [("c1", "validating", {"slots": slots("보존")})])
    with TestClient(create_app(store, provider=ChapterProvider([slots("x")])), headers=HEADERS) as client:
        response = client.post(f"/api/projects/p1/jobs/{job_id}/candidate", json={"action": "dismissed", "chapter_id": "c1"})
        assert response.status_code == 409
        assert client.app.state.job_runner.ledger.chapters(job_id)[0].candidate_status == "held"


# β 묶음 리뷰 R5 (D2b-4 리뷰 R18): 적용 때 덱을 읽지 못한 것은 판정 불가라 결과를 후보로 남기고,
# 자료만 바뀐 것은 덱이 바뀐 사슬 끊김과 다른 코드로 남긴다

def test_an_unreadable_deck_at_apply_keeps_the_result_as_a_candidate(store):
    _project(store)
    provider = ChapterProvider([slots("하나"), slots("둘")], gate_at=0)
    with TestClient(create_app(store, provider=provider), headers=HEADERS) as client:
        job = _register(client, store, ["c1", "c2"]).json()
        assert provider.entered.wait(10)
        deck_file = store.root / "p1" / "deck.json"
        good = deck_file.read_bytes()
        deck_file.write_text("{깨진 덱", encoding="utf-8")
        provider.release.set()
        view = _wait(client, job["id"])
        deck_file.write_bytes(good)
    assert view["chapters"][0]["state"] == "failed" and view["chapters"][0]["candidate_status"] == "held"
    assert view["chapters"][0]["error"]["code"] == "apply_failed"
    assert view["chapters"][0]["error"]["error_class"] == "storage"  # 적용 때 덱을 읽지 못함 (D3a-4, 지금: input)
    assert view["outcome"] == "partial"


def test_sources_changed_at_apply_is_told_apart_from_a_deck_change(store):
    _project(store)
    provider = ChapterProvider([slots("하나"), slots("둘")], gate_at=0)
    with TestClient(create_app(store, provider=provider), headers=HEADERS) as client:
        job = _register(client, store, ["c1", "c2"]).json()
        assert provider.entered.wait(10)
        store.write_source("p1", "추가.md", "새 자료")
        provider.release.set()
        view = _wait(client, job["id"])
    assert view["chapters"][0]["candidate_status"] == "stale"
    assert view["chapters"][0]["error"]["code"] == "sources_changed"


# β 묶음 리뷰 R14: 장 사이 사슬 확인 중에 들어온 취소는 남은 장을 사유 없는 중단이 아니라 취소로 닫는다

def test_cancel_during_the_chain_check_between_chapters_cancels_the_rest(store, monkeypatch):
    _project(store)
    entered, release = threading.Event(), threading.Event()
    provider = ChapterProvider([slots("하나"), slots("둘"), slots("셋")])
    original = store.deck_etag

    def gated_etag(name):
        # 작업 루프의 to_thread 호출만 멈춘다. 첫 장을 보낸 뒤의 첫 확인이 장 사이 사슬 확인이다
        if (provider.calls >= 1 and not entered.is_set()
                and threading.current_thread().name.startswith("asyncio")):
            entered.set()
            assert release.wait(10)
        return original(name)
    monkeypatch.setattr(store, "deck_etag", gated_etag)
    with TestClient(create_app(store, provider=provider), headers=HEADERS) as client:
        job = _register(client, store, ["c1", "c2", "c3"]).json()
        assert entered.wait(10)
        handle = client.app.state.job_runner._handles[job["id"]]
        canceller = threading.Thread(target=lambda: client.post(f"/api/projects/p1/jobs/{job['id']}/cancel"))
        canceller.start()
        for _ in range(500):
            if handle.cancel_sent:
                break
            threading.Event().wait(0.01)
        assert handle.cancel_sent
        release.set()
        canceller.join(10)
        view = _wait(client, job["id"])
    assert _states(view) == [("c1", "succeeded", "applied"), ("c2", "cancelled", "none"), ("c3", "cancelled", "none")]
    assert all(c["error"] is None or c["error"]["code"] != "chain_broken" for c in view["chapters"])
    assert view["state"] == "cancelled" and view["outcome"] == "cancelled" and provider.calls == 1


# D3a-4 회귀 RED(사실 8): 앞 장이 예기치 않은 오류로 실패해도 남은 장의 코드가 provider_failed였다(리뷰 탐침)

def test_an_unexpected_error_stops_the_rest_with_its_own_code(store):
    _project(store)
    provider = ChapterProvider([slots("하나"), RuntimeError("예기치 않음"), slots("셋")])
    with TestClient(create_app(store, provider=provider), headers=HEADERS) as client:
        view = _wait(client, _register(client, store, ["c1", "c2", "c3"]).json()["id"])
    assert view["chapters"][1]["error"]["error_class"] == "internal"
    assert view["chapters"][2]["state"] == "interrupted"
    assert view["chapters"][2]["error"]["code"] == "stopped_after_error"
