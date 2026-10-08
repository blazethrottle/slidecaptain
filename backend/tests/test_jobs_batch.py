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
from slidecaptain.storage.job_ledger import BATCH_KIND, FixedInputs, JobLedger, TransitionRejected, parent_outcome

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
    provider = ChapterProvider([slots("하나 100억"), slots("둘"), slots("셋")])
    with TestClient(create_app(store, provider=provider), headers=HEADERS) as client:
        job = _register(client, store, ["c1", "c2", "c3"])
        assert job.status_code == 202
        view = _wait(client, job.json()["id"])
        rows = client.app.state.job_runner.ledger.chapters(job.json()["id"])
    # 저장 직전에 남긴 적용 대상 ETag가 실제 저장 결과와 같다(재시작 판정의 근거, 계획서 5.7 ④)
    assert all(r.apply_target_etag and r.apply_target_etag == r.applied_etag for r in rows)
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


@pytest.mark.parametrize("case, status", [
    ("no_if_match", 428), ("stale_if_match", 412), ("missing", 404), ("duplicate", 422), ("no_sources", 422),
])
def test_registration_checks_create_no_rows(store, case, status):
    _project(store)
    if case == "no_sources":
        (store.root / "p1" / "sources" / "리서치.md").unlink()
    ids = {"missing": ["c1", "c9"], "duplicate": ["c1", "c1"]}.get(case, ["c1"])
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
