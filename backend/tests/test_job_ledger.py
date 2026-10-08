"""작업 원장 저장소와 재시작 판정 (개정판 D2b-1).

원장은 새 기능이라 지금 코드의 틀린 동작을 겨냥한 RED가 없다. 여기의 시험은 계획서 5.1~5.3과
5.6의 계약 시험이다.
"""

import os
import sqlite3
import threading

import pytest

from slidecaptain.storage.job_ledger import (
    BATCH_KIND,
    CANDIDATE_TRANSITIONS,
    HELD_STALE_PLAN,
    LEDGER_FORMAT,
    LEDGER_NAME,
    STATES,
    TRANSITIONS,
    UNFINISHED,
    FixedInputs,
    JobLedger,
    LedgerError,
    LedgerUnavailable,
    RequestIdConflict,
    TransitionRejected,
    parent_outcome,
    reconcile_chapter,
    reconcile_job,
)

INPUTS = FixedInputs(provider="claude", model="sonnet", selection_id="s1",
                     base_etag="e0", sources_fingerprint="f0", relevance_hash=None)


def _batch(ledger, chapter_ids, request_id="r1", instance_id="i0"):
    return ledger.create_job(project="p1", kind=BATCH_KIND, request_id=request_id,
                             params={"chapter_ids": chapter_ids}, instance_id=instance_id,
                             inputs=INPUTS, chapter_ids=chapter_ids)


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
    sent = path[-1] == "remote_completion_unknown"
    for before, after in zip(path, path[1:]):
        extra = {"remote_sent_at": "t1"} if sent and after == "running" else {}
        job = ledger.transition(job.id, expected=before, new=after, **extra)
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
    job, _ = _batch(ledger, ["c2", "c1"])
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
    job, _ = _batch(ledger, ["c1"], request_id="r")
    for before, after in zip(path, path[1:]):
        extra = fields if after == path[-1] else {}
        ledger.transition_chapter(job.id, "c1", expected=before, new=after, **extra)
    return ledger.chapters(job.id)[0]


SLOTS = {"template": "bullet_box", "bullets": [{"text": "시장 규모 500억", "level": 0}], "conclusion": "c", "footnote": ""}
OK = {"status": "ok", "slots": SLOTS}
VALIDATING = ["queued", "running", "validating"]


@pytest.mark.parametrize("path, fields, current_etag, deck_slots, expected", [
    (["queued"], {}, "e0", None, "interrupted"),
    (["queued", "running"], {"remote_sent_at": "t1"}, "e0", None, "remote_completion_unknown"),
    (VALIDATING, {"result": OK}, "e0", None, "resume_apply"),
    (VALIDATING, {"result": OK, "apply_target_etag": "e1"}, "e1", SLOTS, "mark_applied"),
    (VALIDATING, {"result": OK, "apply_target_etag": "e1"}, "e0", None, "resume_apply"),
    (VALIDATING, {"result": OK, "apply_target_etag": "e1"}, "e9", SLOTS, "mark_applied_changed"),
    (VALIDATING, {"result": OK, "apply_target_etag": "e1"}, "e9", None, "mark_stale"),
])
def test_reconcile_chapter(tmp_path, path, fields, current_etag, deck_slots, expected):
    ledger = JobLedger.open(tmp_path)
    row = _chapter(ledger, path, **fields)
    assert reconcile_chapter(row, chain_etag="e0", current_etag=current_etag, deck_slots=deck_slots) == expected
    ledger.close()


# 리뷰 반영 (D2b-1 리뷰 R1~R22): 변형 실험에서 살아남은 계약을 고정한다

def _walk_to(ledger, job_id, state, chapter=None):
    """state까지 가는 가장 짧은 허용 경로로 행을 옮긴다."""
    paths = {"queued": [], "running": ["running"], "validating": ["running", "validating"],
             "cancel_requested": ["running", "cancel_requested"], "succeeded": ["running", "validating", "succeeded"],
             "failed": ["failed"], "cancelled": ["cancelled"], "interrupted": ["interrupted"],
             "remote_completion_unknown": ["running", "remote_completion_unknown"]}
    current = "queued"
    for step in paths[state]:
        extra = {"remote_sent_at": "t"} if step == "running" else {}
        if chapter is None:
            ledger.transition(job_id, expected=current, new=step, **extra)
        else:
            ledger.transition_chapter(job_id, chapter, expected=current, new=step, **extra)
        current = step


# 계획서 5.3 표를 그대로 옮긴 기대값. 원장 코드의 표와 따로 적어 표가 틀리면 시험이 실패하게 한다
PLAN_EDGES = {
    ("queued", "running"), ("queued", "failed"), ("queued", "cancelled"), ("queued", "interrupted"),
    ("running", "validating"), ("running", "failed"), ("running", "cancel_requested"), ("running", "interrupted"),
    ("running", "remote_completion_unknown"),
    ("validating", "succeeded"), ("validating", "failed"),
    ("cancel_requested", "cancelled"), ("cancel_requested", "interrupted"),
    ("cancel_requested", "remote_completion_unknown"),
}


@pytest.mark.parametrize("row_kind", ["job", "chapter"])
@pytest.mark.parametrize("before", STATES)
@pytest.mark.parametrize("after", STATES)
def test_full_transition_table(tmp_path, row_kind, before, after):
    ledger = JobLedger.open(tmp_path)
    if row_kind == "job":
        job, _ = _job(ledger)
        _walk_to(ledger, job.id, before)
        move = lambda: ledger.transition(job.id, expected=before, new=after)
    else:
        job, _ = _batch(ledger, ["c1"])
        _walk_to(ledger, job.id, before, chapter="c1")
        move = lambda: ledger.transition_chapter(job.id, "c1", expected=before, new=after)
    # 원격 호출 시각 조건: _walk_to는 running에서 시각을 남기므로 interrupted는 거절된다
    allowed = (before, after) in PLAN_EDGES and not (
        after == "interrupted" and before in ("running", "cancel_requested"))
    if allowed:
        assert move().state == after
    else:
        with pytest.raises(TransitionRejected):
            move()
    ledger.close()


def test_remote_sent_decides_interrupted_or_unknown(tmp_path):
    ledger = JobLedger.open(tmp_path)
    job, _ = _job(ledger)
    ledger.transition(job.id, expected="queued", new="running")
    with pytest.raises(TransitionRejected):
        ledger.transition(job.id, expected="running", new="remote_completion_unknown")
    assert ledger.transition(job.id, expected="running", new="interrupted").state == "interrupted"
    ledger.close()


def test_started_and_finished_times(tmp_path):
    ledger = JobLedger.open(tmp_path)
    job, _ = _job(ledger)
    assert (job.started_at, job.finished_at) == (None, None)
    running = ledger.transition(job.id, expected="queued", new="running", remote_sent_at="t")
    assert running.started_at and running.finished_at is None
    validating = ledger.transition(job.id, expected="running", new="validating")
    assert validating.finished_at is None
    done = ledger.transition(job.id, expected="validating", new="succeeded", finished_at=None)
    assert done.finished_at
    ledger.close()


def test_unfinished_query_covers_all_states_and_unfinished_chapters(tmp_path):
    ledger = JobLedger.open(tmp_path)
    ids = {}
    for i, state in enumerate(STATES):
        job, _ = _job(ledger, request_id=f"r{i}")
        _walk_to(ledger, job.id, state)
        ids[state] = job.id
    other = {j.id for j in ledger.unfinished_from_other_instances("someone-else")}
    assert other == {ids[s] for s in UNFINISHED}
    assert {j.id for j in ledger.unfinished_of_instance("i1")} == other
    # 부모가 종결이어도 하위 행이 미종결이면 조정 대상이다 (리뷰 R15)
    batch, _ = _batch(ledger, ["c1"], request_id="b")
    ledger.transition(batch.id, expected="queued", new="failed")
    assert batch.id in {j.id for j in ledger.unfinished_from_other_instances("i1")}
    ledger.close()


def test_update_rejects_finished_rows_and_wrong_expected_state(tmp_path):
    ledger = JobLedger.open(tmp_path)
    job, _ = _job(ledger)
    with pytest.raises(TransitionRejected):
        ledger.update_job(job.id, expected="running", attempts=2)
    assert ledger.update_job(job.id, expected="queued", attempts=2).attempts == 2
    ledger.transition(job.id, expected="queued", new="failed")
    with pytest.raises(TransitionRejected):
        ledger.update_job(job.id, expected="failed", error_detail="고침")
    with pytest.raises(ValueError):
        ledger.update_job(job.id, expected="queued", candidate_status="held")
    ledger.close()


@pytest.mark.parametrize("field, value", [("candidate_status", "kept"), ("error_class", "network"),
                                          ("outcome", "fine")])
def test_values_are_checked(tmp_path, field, value):
    ledger = JobLedger.open(tmp_path)
    job, _ = _job(ledger)
    with pytest.raises(ValueError):
        ledger.transition(job.id, expected="queued", new="failed", **{field: value})
    ledger.close()


# 계획서 5.8의 처분 전이를 따로 적은 기대값
PLAN_CANDIDATE_EDGES = {("none", "held"), ("none", "stale"), ("held", "delivered"), ("held", "applied"),
                        ("held", "dismissed"), ("held", "stale"), ("delivered", "applied"), ("delivered", "dismissed"),
                        ("stale", "delivered"), ("stale", "dismissed")}


@pytest.mark.parametrize("before", list(CANDIDATE_TRANSITIONS))
@pytest.mark.parametrize("after", list(CANDIDATE_TRANSITIONS))
def test_candidate_transition_table(tmp_path, before, after):
    ledger = JobLedger.open(tmp_path)
    job, _ = _job(ledger)
    ledger.transition(job.id, expected="queued", new="running", remote_sent_at="t")
    ledger.transition(job.id, expected="running", new="validating", result={"status": "ok"},
                      candidate_status=before)
    ledger.transition(job.id, expected="validating", new="succeeded")
    if (before, after) in PLAN_CANDIDATE_EDGES:
        assert ledger.settle_candidate(job.id, expected=before, new=after).candidate_status == after
    else:
        with pytest.raises(TransitionRejected):
            ledger.settle_candidate(job.id, expected=before, new=after)
    ledger.close()


def test_candidate_settle_is_compare_and_set(tmp_path):
    ledger = JobLedger.open(tmp_path)
    job, _ = _job(ledger)
    ledger.transition(job.id, expected="queued", new="running", remote_sent_at="t")
    ledger.transition(job.id, expected="running", new="validating", candidate_status="held")
    ledger.settle_candidate(job.id, expected="held", new="dismissed")
    with pytest.raises(TransitionRejected):
        ledger.settle_candidate(job.id, expected="held", new="applied")
    assert ledger.get_job(job.id).candidate_status == "dismissed"
    ledger.close()


def test_same_request_id_in_another_project_is_a_new_job(tmp_path):
    ledger = JobLedger.open(tmp_path)
    a, _ = _job(ledger)
    b, created = ledger.create_job(project="p2", kind="structure", request_id="r1",
                                   params={"target_chapters": 3}, instance_id="i1", inputs=INPUTS)
    assert created and a.id != b.id
    ledger.close()


def test_project_names_are_nfc(tmp_path):
    import unicodedata
    ledger = JobLedger.open(tmp_path)
    nfd = unicodedata.normalize("NFD", "보고")
    ledger.create_job(project=nfd, kind="structure", request_id="r1", params={}, instance_id="i1", inputs=INPUTS)
    assert ledger.list_jobs("보고")[0].project == "보고"
    assert ledger.find_job(nfd, "r1") is not None
    ledger.close()


def test_list_order_is_registration_order(tmp_path):
    ledger = JobLedger.open(tmp_path)
    ids = [_job(ledger, request_id=f"r{i}")[0].id for i in range(5)]
    assert [j.id for j in ledger.list_jobs("p1")] == ids[::-1]
    ledger.close()


def test_batch_arguments_are_checked(tmp_path):
    ledger = JobLedger.open(tmp_path)
    with pytest.raises(ValueError):  # 매개변수와 다른 장 목록
        ledger.create_job(project="p1", kind=BATCH_KIND, request_id="a", params={"chapter_ids": ["c1"]},
                          instance_id="i1", inputs=INPUTS, chapter_ids=["c2"])
    with pytest.raises(ValueError):  # 중복 장
        ledger.create_job(project="p1", kind=BATCH_KIND, request_id="b", params={"chapter_ids": ["c1", "c1"]},
                          instance_id="i1", inputs=INPUTS, chapter_ids=["c1", "c1"])
    with pytest.raises(ValueError):  # 기준 ETag 없는 묶음
        ledger.create_job(project="p1", kind=BATCH_KIND, request_id="c", params={"chapter_ids": ["c1"]},
                          instance_id="i1", inputs=FixedInputs(None, None, None, None, None, None),
                          chapter_ids=["c1"])
    with pytest.raises(ValueError):
        ledger.create_job(project="p1", kind="unknown", request_id="d", params={}, instance_id="i1", inputs=INPUTS)
    assert ledger.list_jobs("p1") == []
    ledger.close()


def test_batch_groups_changes_and_rolls_back_all(tmp_path):
    ledger = JobLedger.open(tmp_path)
    job, _ = _batch(ledger, ["c1", "c2"], instance_id="i1")
    with pytest.raises(TransitionRejected):
        with ledger.batch():
            ledger.transition_chapter(job.id, "c1", expected="queued", new="interrupted")
            ledger.transition_chapter(job.id, "c2", expected="running", new="interrupted")  # 거절
    assert [c.state for c in ledger.chapters(job.id)] == ["queued", "queued"]
    ledger.close()


def test_rejected_write_does_not_block_the_next_write(tmp_path):
    ledger = JobLedger.open(tmp_path)
    _job(ledger)
    with pytest.raises(RequestIdConflict):
        _job(ledger, params={"other": 1})
    job, created = _job(ledger, request_id="r2")
    assert created and ledger.get_job(job.id).state == "queued"
    ledger.close()


def test_commit_failure_rolls_back_and_the_ledger_keeps_working(tmp_path):
    # 리뷰 R1: 다른 연결이 읽기 잠금을 쥐면 COMMIT이 실패한다. 연결이 트랜잭션에 갇히지 않아야 한다
    ledger = JobLedger.open(tmp_path)
    job, _ = _job(ledger)
    ledger._conn.execute("PRAGMA busy_timeout = 50")
    reader = sqlite3.connect(tmp_path / LEDGER_NAME)
    reader.execute("BEGIN")
    reader.execute("SELECT * FROM jobs").fetchall()
    with pytest.raises(LedgerError):
        ledger.transition(job.id, expected="queued", new="running", remote_sent_at="t")
    assert not ledger._conn.in_transaction
    assert ledger.get_job(job.id).state == "queued"
    reader.rollback()
    reader.close()
    assert ledger.transition(job.id, expected="queued", new="running", remote_sent_at="t").state == "running"
    ledger.close()


def _wal_file(path, version, table=True):
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    if table:
        conn.execute("CREATE TABLE other(x)")
        conn.execute("INSERT INTO other VALUES (1)")
    conn.execute(f"PRAGMA user_version = {version}")
    conn.commit()
    conn.close()


@pytest.mark.parametrize("version", [0, LEDGER_FORMAT, LEDGER_FORMAT + 1])
def test_foreign_or_newer_files_are_left_untouched(tmp_path, version):
    # 리뷰 R4, R5: 형식 번호 0인데 테이블이 있는 파일, 구조가 다른 형식 1 파일, 더 새 형식
    path = tmp_path / LEDGER_NAME
    _wal_file(path, version)
    before = path.read_bytes()
    with pytest.raises(LedgerUnavailable):
        JobLedger.open(tmp_path)
    assert path.read_bytes() == before


def test_corrupted_middle_page_is_unavailable(tmp_path):
    # 리뷰 R3: 머리는 멀쩡하고 중간 페이지가 손상된 원장
    ledger = JobLedger.open(tmp_path)
    for i in range(300):
        _job(ledger, request_id=f"r{i}", params={"filler": "x" * 200})
    ledger.close()
    path = tmp_path / LEDGER_NAME
    data = bytearray(path.read_bytes())
    page = 4096
    data[page * 3: page * 3 + 200] = b"\xff" * 200
    path.write_bytes(bytes(data))
    with pytest.raises(LedgerUnavailable):
        JobLedger.open(tmp_path)


def test_read_only_ledger_is_unavailable(tmp_path):
    # 리뷰 R2: 쓰기 권한이 없으면 열기에서 거절한다
    if os.name == "nt" or os.geteuid() == 0:
        pytest.skip("POSIX 일반 사용자 권한에서만 의미가 있다")
    JobLedger.open(tmp_path).close()
    path = tmp_path / LEDGER_NAME
    path.chmod(0o444)
    try:
        with pytest.raises(LedgerUnavailable):
            JobLedger.open(tmp_path)
    finally:
        path.chmod(0o644)


def test_reconcile_job_leaves_batch_parents_to_their_chapters(tmp_path):
    ledger = JobLedger.open(tmp_path)
    job, _ = _batch(ledger, ["c1"])
    assert reconcile_job(job) == "reconcile_children"
    ledger.transition(job.id, expected="queued", new="running", remote_sent_at="t")
    assert reconcile_job(ledger.get_job(job.id)) == "reconcile_children"
    ledger.close()


@pytest.mark.parametrize("result", [{"status": "format_error", "raw_text": "x"}, {"status": "ok", "slots": None}])
def test_reconcile_chapter_format_failures(tmp_path, result):
    ledger = JobLedger.open(tmp_path)
    row = _chapter(ledger, VALIDATING, result=result)
    assert reconcile_chapter(row, chain_etag="e0", current_etag="e0", deck_slots=None) == "mark_format_failed"
    ledger.close()


def test_reconcile_chapter_defers_when_the_deck_is_unreadable(tmp_path):
    ledger = JobLedger.open(tmp_path)
    row = _chapter(ledger, VALIDATING, result=OK, apply_target_etag="e1")
    assert reconcile_chapter(row, chain_etag="e0", current_etag=None, deck_slots=None) == "defer_unknown"
    with pytest.raises(ValueError):
        reconcile_chapter(row, chain_etag=None, current_etag="e0", deck_slots=None)
    ledger.close()


def test_reconcile_chapter_compares_normalized_slots(tmp_path):
    from slidecaptain.storage.job_ledger import _SLOTS
    ledger = JobLedger.open(tmp_path)
    row = _chapter(ledger, VALIDATING, result=OK, apply_target_etag="e1")
    model = _SLOTS.validate_python(SLOTS)
    assert reconcile_chapter(row, chain_etag="e0", current_etag="e9", deck_slots=model) == "mark_applied_changed"
    other = {**SLOTS, "conclusion": "다른 결론"}
    assert reconcile_chapter(row, chain_etag="e0", current_etag="e9", deck_slots=other) == "mark_stale"
    ledger.close()


def _finished_chapters(ledger, states):
    job, _ = _batch(ledger, [f"c{i}" for i in range(len(states))], request_id=f"p{len(states)}{states[0][0]}")
    for i, (state, fields) in enumerate(states):
        cid = f"c{i}"
        if state == "succeeded":
            _walk_to(ledger, job.id, "succeeded", chapter=cid)
        elif state == "failed":
            ledger.transition_chapter(job.id, cid, expected="queued", new="failed", **fields)
        elif state == "stale":
            ledger.transition_chapter(job.id, cid, expected="queued", new="running", remote_sent_at="t")
            ledger.transition_chapter(job.id, cid, expected="running", new="validating", result=OK,
                                      candidate_status="stale")
            ledger.transition_chapter(job.id, cid, expected="validating", new="failed", error_class="base_changed")
        else:
            _walk_to(ledger, job.id, state, chapter=cid)
            if fields:
                pass
    return ledger.chapters(job.id)


@pytest.mark.parametrize("states, expected", [
    ([("succeeded", {}), ("succeeded", {})], ("succeeded", "all_applied")),
    ([("succeeded", {}), ("failed", {"error_class": "ai_output"})], ("failed", "partial")),
    ([("succeeded", {}), ("remote_completion_unknown", {})], ("failed", "partial")),
    ([("succeeded", {}), ("interrupted", {})], ("failed", "partial")),
    ([("failed", {"error_code": HELD_STALE_PLAN}), ("succeeded", {})], ("failed", "held_stale_plan")),
    ([("stale", {}), ("interrupted", {})], ("failed", "chain_broken")),
    ([("succeeded", {}), ("cancelled", {})], ("cancelled", "cancelled")),
])
def test_parent_outcome(tmp_path, states, expected):
    ledger = JobLedger.open(tmp_path)
    assert parent_outcome(_finished_chapters(ledger, states)) == expected
    ledger.close()


def test_parent_outcome_needs_finished_chapters(tmp_path):
    ledger = JobLedger.open(tmp_path)
    job, _ = _batch(ledger, ["c1"])
    with pytest.raises(ValueError):
        parent_outcome(ledger.chapters(job.id))
    ledger.close()
