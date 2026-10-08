"""작업 원장 저장소와 재시작 판정 (개정판 D2b-1).

원장은 새 기능이라 지금 코드의 틀린 동작을 겨냥한 RED가 없다. 여기의 시험은 계획서 5.1~5.3과
5.6의 계약 시험이다.
"""

import sqlite3
import threading

import pytest

from slidecaptain.storage.job_ledger import (
    LEDGER_FORMAT,
    LEDGER_NAME,
    FixedInputs,
    JobLedger,
    LedgerUnavailable,
    RequestIdConflict,
    TransitionRejected,
    reconcile_chapter,
    reconcile_job,
)

INPUTS = FixedInputs(provider="claude", model="sonnet", selection_id="s1",
                     base_etag="e0", sources_fingerprint="f0", relevance_hash=None)


def _job(ledger, request_id="r1", params=None, **kw):
    return ledger.create_job(project="p1", kind="structure", request_id=request_id,
                             params=params if params is not None else {"target_chapters": 3},
                             instance_id="i1", inputs=INPUTS, **kw)


def test_new_ledger_file_records_format_and_journal_mode(tmp_path):
    ledger = JobLedger.open(tmp_path)
    ledger.close()
    conn = sqlite3.connect(tmp_path / LEDGER_NAME)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == LEDGER_FORMAT
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    conn.close()


def test_reopening_keeps_rows(tmp_path):
    ledger = JobLedger.open(tmp_path)
    job, _ = _job(ledger)
    ledger.close()
    again = JobLedger.open(tmp_path)
    assert again.get_job(job.id).state == "queued"
    again.close()


@pytest.mark.parametrize("path", [
    ["queued", "running", "validating", "succeeded"],
    ["queued", "failed"],
    ["queued", "cancelled"],
    ["queued", "running", "cancel_requested", "cancelled"],
    ["queued", "running", "cancel_requested", "interrupted"],
    ["queued", "running", "cancel_requested", "remote_completion_unknown"],
    ["queued", "running", "remote_completion_unknown"],
    ["queued", "running", "validating", "failed"],
])
def test_allowed_paths(tmp_path, path):
    ledger = JobLedger.open(tmp_path)
    job, _ = _job(ledger)
    for before, after in zip(path, path[1:]):
        job = ledger.transition(job.id, expected=before, new=after)
    assert job.state == path[-1]
    ledger.close()


@pytest.mark.parametrize("path", [
    ["queued", "running", "validating", "succeeded", "running"],
    ["queued", "cancelled", "running"],
    ["queued", "interrupted", "succeeded"],
    ["queued", "succeeded"],
    ["queued", "running", "validating", "cancel_requested"],
])
def test_edges_outside_the_table_are_rejected(tmp_path, path):
    ledger = JobLedger.open(tmp_path)
    job, _ = _job(ledger)
    for before, after in zip(path[:-2], path[1:-1]):
        job = ledger.transition(job.id, expected=before, new=after)
    with pytest.raises(TransitionRejected):
        ledger.transition(job.id, expected=path[-2], new=path[-1])
    assert ledger.get_job(job.id).state == path[-2]
    ledger.close()


def test_compare_and_set_does_not_overwrite_a_state_written_first(tmp_path):
    # 종료 처리가 먼저 interrupted를 쓰면, 늦게 깨어난 실행 코루틴의 running→validating은 실패한다
    ledger = JobLedger.open(tmp_path)
    job, _ = _job(ledger)
    ledger.transition(job.id, expected="queued", new="running", remote_sent_at="t1")
    ledger.transition(job.id, expected="running", new="remote_completion_unknown")
    with pytest.raises(TransitionRejected):
        ledger.transition(job.id, expected="running", new="validating", result={"status": "ok"})
    row = ledger.get_job(job.id)
    assert row.state == "remote_completion_unknown" and row.result is None
    ledger.close()


def test_transition_writes_fields_in_the_same_change(tmp_path):
    ledger = JobLedger.open(tmp_path)
    job, _ = _job(ledger)
    ledger.transition(job.id, expected="queued", new="running", remote_sent_at="t1", attempts=1)
    row = ledger.transition(job.id, expected="running", new="validating",
                            result={"status": "ok", "usage": {"calls": 1}}, candidate_status="held")
    assert (row.remote_sent_at, row.attempts, row.result["usage"], row.candidate_status) == (
        "t1", 1, {"calls": 1}, "held")
    ledger.close()


def test_unknown_field_is_rejected(tmp_path):
    ledger = JobLedger.open(tmp_path)
    job, _ = _job(ledger)
    with pytest.raises(ValueError):
        ledger.transition(job.id, expected="queued", new="running", project="other")
    ledger.close()


def test_same_request_id_and_params_returns_the_same_job(tmp_path):
    ledger = JobLedger.open(tmp_path)
    first, created = _job(ledger)
    again, created_again = _job(ledger)
    assert created and not created_again and again.id == first.id
    ledger.close()


def test_same_request_id_merges_with_a_finished_job(tmp_path):
    ledger = JobLedger.open(tmp_path)
    first, _ = _job(ledger)
    ledger.transition(first.id, expected="queued", new="failed", error_code="selection_changed")
    again, created = _job(ledger)
    assert not created and again.state == "failed"
    ledger.close()


def test_same_request_id_with_other_params_is_a_conflict(tmp_path):
    ledger = JobLedger.open(tmp_path)
    _job(ledger)
    with pytest.raises(RequestIdConflict):
        _job(ledger, params={"target_chapters": 4})
    assert len(ledger.list_jobs("p1")) == 1
    ledger.close()


def test_params_hash_ignores_key_order(tmp_path):
    ledger = JobLedger.open(tmp_path)
    a, _ = _job(ledger, params={"a": 1, "b": 2})
    b, created = _job(ledger, params={"b": 2, "a": 1})
    assert not created and a.id == b.id
    ledger.close()


def test_batch_job_creates_queued_chapter_rows_in_order(tmp_path):
    ledger = JobLedger.open(tmp_path)
    job, _ = ledger.create_job(project="p1", kind="chapters", request_id="r1",
                               params={"chapter_ids": ["c2", "c1"]}, instance_id="i1",
                               inputs=INPUTS, chapter_ids=["c2", "c1"])
    rows = ledger.chapters(job.id)
    assert [(c.chapter_id, c.position, c.state) for c in rows] == [("c2", 0, "queued"), ("c1", 1, "queued")]
    ledger.transition_chapter(job.id, "c2", expected="queued", new="running", remote_sent_at="t1")
    with pytest.raises(TransitionRejected):
        ledger.transition_chapter(job.id, "c2", expected="queued", new="running")
    ledger.close()


def test_optional_d4_columns_exist_and_are_empty(tmp_path):
    ledger = JobLedger.open(tmp_path)
    job, _ = _job(ledger)
    assert (job.account_profile, job.effort, job.consent_revision) == (None, None, None)
    ledger.close()


def test_unfinished_from_other_instances(tmp_path):
    ledger = JobLedger.open(tmp_path)
    mine, _ = _job(ledger, request_id="a")
    other, _ = ledger.create_job(project="p1", kind="structure", request_id="b", params={},
                                 instance_id="i0", inputs=INPUTS)
    done, _ = ledger.create_job(project="p1", kind="structure", request_id="c", params={},
                                instance_id="i0", inputs=INPUTS)
    ledger.transition(done.id, expected="queued", new="cancelled")
    assert [j.id for j in ledger.unfinished_from_other_instances("i1")] == [other.id]
    ledger.close()


def test_corrupted_file_is_unavailable_and_left_untouched(tmp_path):
    path = tmp_path / LEDGER_NAME
    path.write_bytes(b"not a database" * 100)
    before = path.read_bytes()
    with pytest.raises(LedgerUnavailable) as e:
        JobLedger.open(tmp_path)
    assert e.value.code == "job_ledger_unavailable"
    assert path.read_bytes() == before


def test_newer_format_is_unavailable_and_left_untouched(tmp_path):
    conn = sqlite3.connect(tmp_path / LEDGER_NAME)
    conn.execute(f"PRAGMA user_version = {LEDGER_FORMAT + 1}")
    conn.execute("CREATE TABLE future(x)")
    conn.commit()
    conn.close()
    before = (tmp_path / LEDGER_NAME).read_bytes()
    with pytest.raises(LedgerUnavailable):
        JobLedger.open(tmp_path)
    assert (tmp_path / LEDGER_NAME).read_bytes() == before


def test_memory_ledger_is_one_shared_connection_across_threads():
    ledger = JobLedger.open(None)
    job, _ = _job(ledger)
    seen = []
    t = threading.Thread(target=lambda: seen.append(ledger.get_job(job.id).state))
    t.start()
    t.join()
    assert seen == ["queued"]
    ledger.close()


def test_project_listing_ignores_the_ledger_file(store):
    store.create_project("p1")
    JobLedger.open(store.root).close()
    assert [p.name for p in store.list_projects()] == ["p1"]


# 재시작 판정(계획서 5.6 표). 입력은 행과 현재 덱 상태이고 출력은 조정 결과다

def _row(ledger, state_path, **fields):
    job, _ = _job(ledger)
    for before, after in zip(state_path, state_path[1:]):
        extra = fields if after == state_path[-1] else {}
        job = ledger.transition(job.id, expected=before, new=after, **extra)
    return job


@pytest.mark.parametrize("path, fields, expected", [
    (["queued"], {}, "interrupted"),
    (["queued", "running"], {}, "interrupted"),
    (["queued", "running"], {"remote_sent_at": "t1"}, "remote_completion_unknown"),
    (["queued", "running", "cancel_requested"], {}, "interrupted"),
    (["queued", "running", "cancel_requested"], {"remote_sent_at": "t1"}, "remote_completion_unknown"),
    (["queued", "running", "validating"], {"result": {"status": "ok"}}, "rejudge_candidate"),
    (["queued", "running", "validating", "succeeded"], {}, None),
])
def test_reconcile_job(tmp_path, path, fields, expected):
    ledger = JobLedger.open(tmp_path)
    assert reconcile_job(_row(ledger, path, **fields)) == expected
    ledger.close()


def _chapter(ledger, path, **fields):
    job, _ = ledger.create_job(project="p1", kind="chapters", request_id="r", params={},
                               instance_id="i0", inputs=INPUTS, chapter_ids=["c1"])
    for before, after in zip(path, path[1:]):
        extra = fields if after == path[-1] else {}
        ledger.transition_chapter(job.id, "c1", expected=before, new=after, **extra)
    return ledger.chapters(job.id)[0]


SLOTS = {"template": "bullet_box", "bullets": [], "conclusion": "c", "footnote": ""}
VALIDATING = ["queued", "running", "validating"]


@pytest.mark.parametrize("path, fields, current_etag, deck_slots, expected", [
    (["queued"], {}, "e0", None, "interrupted"),
    (["queued", "running"], {"remote_sent_at": "t1"}, "e0", None, "remote_completion_unknown"),
    (VALIDATING, {"result": {"slots": SLOTS}}, "e0", None, "resume_apply"),
    (VALIDATING, {"result": {"slots": SLOTS}, "apply_target_etag": "e1"}, "e1", SLOTS, "mark_applied"),
    (VALIDATING, {"result": {"slots": SLOTS}, "apply_target_etag": "e1"}, "e0", None, "resume_apply"),
    (VALIDATING, {"result": {"slots": SLOTS}, "apply_target_etag": "e1"}, "e9", SLOTS, "mark_applied_changed"),
    (VALIDATING, {"result": {"slots": SLOTS}, "apply_target_etag": "e1"}, "e9", None, "mark_stale"),
])
def test_reconcile_chapter(tmp_path, path, fields, current_etag, deck_slots, expected):
    ledger = JobLedger.open(tmp_path)
    row = _chapter(ledger, path, **fields)
    assert reconcile_chapter(row, chain_etag="e0", current_etag=current_etag, deck_slots=deck_slots) == expected
    ledger.close()
