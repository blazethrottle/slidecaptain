"""Manual review records bind a user's verdict to exact, current export bytes."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from slidecaptain.__main__ import main
from slidecaptain.server.app import create_app
from slidecaptain.storage.file_store import FileProjectStore
from test_export_history import publish, rewrite_record


CATEGORIES = ["narrative", "evidence", "representation", "visual", "target_renderer"]


def url(exported):
    return f"/api/projects/synthetic/exports/{quote(Path(exported['path']).stem, safe='')}/reviews"


def request_for(basis, **changes):
    return {
        "expected_input_fingerprint": basis["input_fingerprint"],
        "expected_artifact_sha256": basis["artifact_sha256"],
        "category": "narrative", "status": "passed", "reviewer": "합성 검수자",
        "note": "합성 테스트에서 모든 페이지의 흐름을 확인했다.",
        "pages": list(range(1, basis["slide_count"] + 1)), **changes,
    }


def record(client, exported, basis, **changes):
    return client.post(url(exported), headers={"If-Match": basis["base_etag"]},
                       json=request_for(basis, **changes))


def states(data):
    return {item["category"]: item for item in data["categories"]}


def stored_records(exported):
    return sorted(Path(exported["path"]).parent.glob(f"{Path(exported['path']).stem}.review.*.json"))


def test_manual_reviews_roundtrip_append_only_and_latest_failure_wins(client, store):
    exported = publish(client, store)
    before = {p: p.read_bytes() for p in store.root.rglob("*") if p.is_file()}
    response = client.get(url(exported))
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    basis = response.json()
    assert basis["base_etag"] == client.get("/api/projects/synthetic/deck").headers["etag"]
    assert basis["input_fingerprint"] == exported["quality"]["input_fingerprint"]
    assert basis["artifact_sha256"] == exported["quality"]["artifact_sha256"]
    assert basis["status"] == "current" and basis["can_record"] is True
    assert basis["storage_status"] == "empty" and basis["records"] == []
    assert list(states(basis)) == CATEGORIES
    assert all(item["status"] == "not_run" for item in basis["categories"])
    assert {p: p.read_bytes() for p in store.root.rglob("*") if p.is_file()} == before

    first = record(client, exported, basis)
    assert first.status_code == 200
    saved = first.json()["records"][0]
    assert saved["rule_version"] == "manual-review-v1"
    assert saved["id"] and saved["sequence"] == 1 and saved["reviewed_at"]
    assert saved["export_id"] == Path(exported["path"]).stem
    assert saved["input_fingerprint"] == basis["input_fingerprint"]
    assert saved["artifact_sha256"] == basis["artifact_sha256"]
    first_bytes = stored_records(exported)[0].read_bytes()
    second = record(client, exported, basis, status="needs_revision", note="첫 페이지의 결론을 수정해야 한다.")
    assert second.status_code == 200
    data = second.json()
    assert [item["sequence"] for item in data["records"]] == [2, 1]
    assert data["records"][1] == saved
    assert states(data)["narrative"]["status"] == "needs_revision"
    assert states(data)["narrative"]["latest_record_id"] == data["records"][0]["id"]
    assert data["final_export_allowed"] is False
    assert stored_records(exported)[0].read_bytes() == first_bytes
    assert {p: p.read_bytes() for p in before} == before


@pytest.mark.parametrize("changes", [
    {"pages": []}, {"pages": [0]}, {"pages": [2]}, {"pages": [1, 1]},
    {"pages": [True]}, {"pages": [1.0]}, {"pages": ["1"]},
    {"reviewer": "   "}, {"note": " \n "}, {"category": "automated"},
    {"status": "not_run"}, {"id": "client-id"}, {"sequence": 999},
    {"reviewed_at": "2000-01-01"}, {"expected_artifact_sha256": "bad"},
])
def test_bad_or_client_owned_fields_cannot_create_a_record(client, store, changes):
    exported = publish(client, store)
    basis = client.get(url(exported)).json()
    assert record(client, exported, basis, **changes).status_code == 422
    assert stored_records(exported) == []


def test_pass_requires_all_pages_but_revision_can_identify_a_subset(client, store):
    exported = publish(client, store)
    rewrite_record(exported, lambda data: data.update(slide_count=2))
    basis = client.get(url(exported)).json()
    assert record(client, exported, basis, pages=[1]).status_code == 422
    assert record(client, exported, basis, status="needs_revision", pages=[2]).status_code == 200
    assert record(client, exported, basis, pages=[2, 1]).status_code == 200


def test_zero_target_cannot_record_pass(client, store):
    exported = publish(client, store)
    rewrite_record(exported, lambda data: data.update(slide_count=0))
    basis = client.get(url(exported)).json()
    assert basis["can_record"] is False
    assert record(client, exported, basis, pages=[1]).status_code == 409


def test_review_requires_app_header_and_explicit_original_etag(client, store):
    exported = publish(client, store)
    basis = client.get(url(exported)).json()
    with TestClient(create_app(store)) as unguarded:
        assert unguarded.post(url(exported), headers={"If-Match": basis["base_etag"]},
                              json=request_for(basis)).status_code == 403
    assert client.post(url(exported), json=request_for(basis)).status_code == 428
    for token in ("*", '"different"'):
        assert client.post(url(exported), headers={"If-Match": token},
                           json=request_for(basis)).status_code == 412
    assert stored_records(exported) == []


@pytest.mark.parametrize("kind", ["source", "deck", "preset", "artifact"])
def test_changes_invalidate_reviews_and_exact_restoration_restores_currentness(client, store, kind):
    exported = publish(client, store)
    basis = client.get(url(exported)).json()
    assert record(client, exported, basis).status_code == 200
    path = {
        "source": store.root / "synthetic/sources/synthetic.md",
        "deck": store.root / "synthetic/deck.json",
        "preset": store.root / "preset.json",
        "artifact": Path(exported["path"]),
    }[kind]
    if kind == "preset":
        store.save_global_preset(store.load_global_preset())
    old = path.read_bytes()
    if kind in ("source", "artifact"):
        path.write_bytes(old + b"\nchanged")
    else:
        data = json.loads(old)
        if kind == "deck":
            data["meta"]["title"] = "Changed report"
        else:
            data["colors"]["accent"] = "BB0000"
        path.write_text(json.dumps(data), encoding="utf-8")
    stale = client.get(url(exported)).json()
    assert stale["status"] == "stale" and stale["can_record"] is False
    assert states(stale)["narrative"]["status"] == "stale"
    assert len(stale["records"]) == 1
    assert record(client, exported, basis).status_code == (412 if kind == "deck" else 409)
    path.write_bytes(old)
    restored = client.get(url(exported)).json()
    assert restored["status"] == "current" and restored["can_record"] is True
    assert states(restored)["narrative"]["status"] == "passed"


@pytest.mark.parametrize("kind", ["legacy", "broken_quality", "missing_hash", "missing_artifact", "missing_deck"])
def test_unverifiable_export_is_readable_but_cannot_record(client, store, kind):
    exported = publish(client, store)
    basis = client.get(url(exported)).json()
    assert record(client, exported, basis).status_code == 200
    if kind == "legacy":
        rewrite_record(exported, lambda data: data.update(gate_version="preflight-v1"))
    elif kind == "missing_hash":
        rewrite_record(exported, lambda data: data.pop("artifact_sha256"))
    elif kind == "broken_quality":
        Path(exported["quality_path"]).write_text("{broken", encoding="utf-8")
    elif kind == "missing_artifact":
        Path(exported["path"]).unlink()
    else:
        (store.root / "synthetic/deck.json").unlink()
    response = client.get(url(exported))
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "unavailable" and data["can_record"] is False
    assert len(data["records"]) == 1 and data["reason"]
    assert record(client, exported, basis).status_code == 409


@pytest.mark.parametrize("damage", ["json", "unknown_version", "identity", "duplicate_key", "symlink", "directory"])
def test_damaged_latest_record_never_revives_older_pass(client, store, tmp_path, damage, symlink_or_skip):
    exported = publish(client, store)
    basis = client.get(url(exported)).json()
    assert record(client, exported, basis).status_code == 200
    assert record(client, exported, basis, status="needs_revision").status_code == 200
    target = stored_records(exported)[-1]
    if damage == "json":
        target.write_text("{broken", encoding="utf-8")
    elif damage in ("unknown_version", "identity"):
        data = json.loads(target.read_text(encoding="utf-8"))
        data["rule_version" if damage == "unknown_version" else "export_id"] = "wrong"
        target.write_text(json.dumps(data), encoding="utf-8")
    elif damage == "duplicate_key":
        target.write_text('{"sequence":2,"sequence":1}', encoding="utf-8")
    else:
        target.unlink()
        if damage == "directory":
            target.mkdir()
        else:
            outside = tmp_path / "private.json"
            outside.write_text("PRIVATE RECORD", encoding="utf-8")
            symlink_or_skip(target, outside)
    response = client.get(url(exported))
    assert response.status_code == 200 and "PRIVATE RECORD" not in response.text
    data = response.json()
    assert data["status"] == "unavailable" and data["can_record"] is False
    assert data["storage_status"] in ("invalid", "unreadable")
    assert all(item["status"] == "unavailable" for item in data["categories"])
    assert record(client, exported, basis).status_code == 409


def test_bound_identity_tokens_cannot_be_silently_rebased(client, store):
    exported = publish(client, store)
    basis = client.get(url(exported)).json()
    for field in ("expected_input_fingerprint", "expected_artifact_sha256"):
        assert record(client, exported, basis, **{field: "0" * 64}).status_code == 409
    assert stored_records(exported) == []


def test_all_manual_passes_leave_web_and_cli_final_export_blocked(client, store, capsys):
    exported = publish(client, store)
    basis = client.get(url(exported)).json()
    for category in CATEGORIES:
        response = record(client, exported, basis, category=category)
        assert response.status_code == 200 and response.json()["final_export_allowed"] is False
    before = {p: p.read_bytes() for p in Path(exported["path"]).parent.iterdir() if p.is_file()}
    assert client.post("/api/projects/synthetic/export?final=true").status_code == 422
    assert main(["export", str(store.root / "synthetic/deck.json"), "--out", str(Path(exported["path"]).parent), "--final"]) == 1
    assert {p: p.read_bytes() for p in before} == before
    assert "검수" in capsys.readouterr().err


def test_concurrent_stores_append_distinct_sequences_without_overwrite(client, store):
    exported = publish(client, store)
    basis = client.get(url(exported)).json()
    def save(number):
        with TestClient(create_app(FileProjectStore(store.root)), headers={"X-Requested-With": "SlideCaptain"}) as other:
            return record(other, exported, basis, note=f"합성 동시 검수 {number}")
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(save, range(4)))
    assert [response.status_code for response in responses] == [200] * 4
    data = client.get(url(exported)).json()
    assert [item["sequence"] for item in data["records"]] == [4, 3, 2, 1]
    assert len({item["id"] for item in data["records"]}) == 4
    assert {item["note"] for item in data["records"]} == {f"합성 동시 검수 {number}" for number in range(4)}


@pytest.mark.parametrize("component", ["lock", "exports", "artifact", "quality"])
def test_review_writes_never_follow_symlinks(client, store, tmp_path, component, symlink_or_skip):
    exported = publish(client, store)
    basis = client.get(url(exported)).json()
    directory = Path(exported["path"]).parent
    outside = tmp_path / "outside"
    outside.mkdir()
    protected = outside / "private.txt"
    protected.write_text("PRIVATE BYTES", encoding="utf-8")
    if component == "exports":
        directory.rename(directory.with_name("original-exports"))
        symlink_or_skip(directory, outside, target_is_directory=True)
    else:
        target = {"lock": directory / ".slidecaptain-export.lock", "artifact": Path(exported["path"]),
                  "quality": Path(exported["quality_path"])}[component]
        target.unlink()
        symlink_or_skip(target, protected)
    response = record(client, exported, basis)
    assert response.status_code in (409, 422)
    assert protected.read_text(encoding="utf-8") == "PRIVATE BYTES"
    assert list(outside.iterdir()) == [protected]
    assert "PRIVATE BYTES" not in response.text


@pytest.mark.parametrize("export_id", ["..\\escape_v001", "C:escape_v001", "bad.json"])
def test_review_path_ids_are_validated(client, store, export_id):
    exported = publish(client, store)
    basis = client.get(url(exported)).json()
    path = f"/api/projects/synthetic/exports/{quote(export_id, safe='')}/reviews"
    assert client.get(path).status_code == 422
    assert client.post(path, headers={"If-Match": basis["base_etag"]}, json=request_for(basis)).status_code == 422


@pytest.mark.parametrize("kind", ["source", "deck", "artifact", "quality"])
def test_inputs_are_rechecked_immediately_before_record_publication(client, store, monkeypatch, kind):
    from slidecaptain.export import reviews
    exported = publish(client, store)
    basis = client.get(url(exported)).json()
    original_publish = reviews._publish_record
    def changed(directory, value, reader, verify):
        if kind == "source":
            store.write_source("synthetic", "extra.md", "Changed source")
        elif kind == "deck":
            deck = store.load_deck("synthetic")
            deck.meta.title = "Changed deck"
            store.save_deck("synthetic", deck)
        elif kind == "artifact":
            Path(exported["path"]).write_bytes(b"Changed artifact")
        else:
            Path(exported["quality_path"]).write_text("{}", encoding="utf-8")
        return original_publish(directory, value, reader, verify)
    monkeypatch.setattr(reviews, "_publish_record", changed)
    response = record(client, exported, basis)
    assert response.status_code == (412 if kind == "deck" else 409)
    assert stored_records(exported) == []
    assert list(Path(exported["path"]).parent.glob(".slidecaptain-review-*.tmp")) == []


def test_published_destination_appearing_after_scan_is_never_overwritten(client, store, monkeypatch):
    from slidecaptain.export import reviews
    exported = publish(client, store)
    basis = client.get(url(exported)).json()
    original_link = reviews.os.link
    def occupied(source, destination, *args, **kwargs):
        (Path(exported["path"]).parent / Path(destination).name).write_bytes(b"EXTERNAL RECORD")
        return original_link(source, destination, *args, **kwargs)
    monkeypatch.setattr(reviews.os, "link", occupied)
    assert record(client, exported, basis).status_code == 409
    assert [path.read_bytes() for path in stored_records(exported)] == [b"EXTERNAL RECORD"]


def test_export_lock_timeout_is_retryable_without_writing_a_review(client, store, monkeypatch):
    from slidecaptain.export import reviews
    from slidecaptain.export.locking import export_directory_lock
    exported = publish(client, store)
    basis = client.get(url(exported)).json()
    monkeypatch.setattr(reviews, "export_directory_lock", lambda directory, **kwargs:
                        export_directory_lock(directory, timeout=0, **kwargs))
    with export_directory_lock(Path(exported["path"]).parent):
        assert record(client, exported, basis).status_code == 409
    assert stored_records(exported) == []
    assert record(client, exported, basis).status_code == 200


def test_replaced_lock_cannot_publish_using_the_original_lock_inode(client, store, monkeypatch):
    from slidecaptain.export import reviews
    exported = publish(client, store)
    basis = client.get(url(exported)).json()
    original_publish = reviews._publish_record
    def replaced(directory, *args):
        path = directory / ".slidecaptain-export.lock"
        path.unlink()
        path.write_bytes(b"External lock replacement")
        return original_publish(directory, *args)
    monkeypatch.setattr(reviews, "_publish_record", replaced)
    assert record(client, exported, basis).status_code == 409
    assert stored_records(exported) == []


@pytest.mark.skipif(os.name == "nt", reason="Windows pins directory names against rename")
def test_transient_directory_swap_cannot_redirect_review_publication(client, store, tmp_path, monkeypatch):
    from slidecaptain.export import reviews
    exported = publish(client, store)
    basis = client.get(url(exported)).json()
    directory = Path(exported["path"]).parent
    backup = directory.with_name("exports-pinned")
    outside = tmp_path / "outside"
    outside.mkdir()
    original_link = reviews.os.link
    def swapped(source, destination, *args, **kwargs):
        directory.rename(backup)
        directory.symlink_to(outside, target_is_directory=True)
        try:
            return original_link(source, destination, *args, **kwargs)
        finally:
            directory.unlink()
            backup.rename(directory)
    monkeypatch.setattr(reviews.os, "link", swapped)
    assert record(client, exported, basis).status_code == 200
    assert list(outside.iterdir()) == []
    assert len(stored_records(exported)) == 1


@pytest.mark.skipif(os.name == "nt", reason="Windows pins directory names against rename")
def test_transient_project_symlink_never_reads_an_external_export(client, store, tmp_path, monkeypatch):
    from slidecaptain.export import reviews
    exported = publish(client, store)
    project = Path(exported["path"]).parent.parent
    backup = project.with_name("original-project")
    outside = tmp_path / "outside"
    (outside / "exports").mkdir(parents=True)
    for path in (Path(exported["path"]), Path(exported["quality_path"])):
        (outside / "exports" / path.name).write_bytes(path.read_bytes())
    original_open = reviews.os.open
    def swapped(path, flags, *args, **kwargs):
        if path == "exports" and kwargs.get("dir_fd") is not None:
            project.rename(backup)
            project.symlink_to(outside, target_is_directory=True)
            try:
                return original_open(path, flags, *args, **kwargs)
            finally:
                project.unlink()
                backup.rename(project)
        return original_open(path, flags, *args, **kwargs)
    monkeypatch.setattr(reviews.os, "open", swapped)
    response = client.get(url(exported))
    assert response.status_code == 200
    assert response.json()["can_record"] is True


@pytest.mark.parametrize("damage", ["gap", "sequence", "duplicate_id", "oversize", "too_many", "total_bytes"])
def test_broken_sequences_and_limits_are_visible_without_using_a_partial_history(client, store, monkeypatch, damage):
    from slidecaptain.export import reviews
    exported = publish(client, store)
    basis = client.get(url(exported)).json()
    assert record(client, exported, basis).status_code == 200
    assert record(client, exported, basis, status="needs_revision").status_code == 200
    first, second = stored_records(exported)
    if damage == "gap":
        first.unlink()
    elif damage in ("sequence", "duplicate_id"):
        data = json.loads(second.read_text(encoding="utf-8"))
        data["sequence" if damage == "sequence" else "id"] = (
            1 if damage == "sequence" else json.loads(first.read_text(encoding="utf-8"))["id"])
        second.write_text(json.dumps(data), encoding="utf-8")
    elif damage == "oversize":
        monkeypatch.setattr(reviews, "_MAX_RECORD_BYTES", 10)
    elif damage == "too_many":
        monkeypatch.setattr(reviews, "_MAX_RECORDS", 1)
    else:
        monkeypatch.setattr(reviews, "_MAX_TOTAL_BYTES", first.stat().st_size + 1)
    data = client.get(url(exported)).json()
    assert data["status"] == "unavailable" and data["can_record"] is False
    assert all(item["status"] == "unavailable" for item in data["categories"])
    assert record(client, exported, basis).status_code == 409
    if damage in ("oversize", "too_many", "total_bytes"):
        assert "한도" in data["reason"]


def test_reaching_record_limit_does_not_append_an_unreadable_tail(client, store, monkeypatch):
    from slidecaptain.export import reviews
    exported = publish(client, store)
    basis = client.get(url(exported)).json()
    monkeypatch.setattr(reviews, "_MAX_RECORDS", 1)
    response = record(client, exported, basis)
    assert response.status_code == 200
    assert response.json()["status"] == "current"
    assert response.json()["can_record"] is False
    assert record(client, exported, basis).status_code == 409
    assert len(stored_records(exported)) == 1


def test_append_cannot_cross_the_aggregate_read_limit(client, store, monkeypatch):
    from slidecaptain.export import reviews
    exported = publish(client, store)
    basis = client.get(url(exported)).json()
    assert record(client, exported, basis).status_code == 200
    first = stored_records(exported)[0]
    before = first.read_bytes()
    monkeypatch.setattr(reviews, "_MAX_TOTAL_BYTES", len(before) * 2 - 1)
    assert record(client, exported, basis).status_code == 409
    assert stored_records(exported) == [first] and first.read_bytes() == before
    data = client.get(url(exported)).json()
    assert data["storage_status"] == "readable"
    assert states(data)["narrative"]["status"] == "passed"


def test_failed_fsync_removes_only_the_unpublished_owned_staging_file(client, store, monkeypatch):
    from slidecaptain.export import reviews
    exported = publish(client, store)
    basis = client.get(url(exported)).json()
    assert record(client, exported, basis).status_code == 200
    first = stored_records(exported)[0]
    before = first.read_bytes()
    def fail_fsync(_):
        raise OSError("synthetic fsync failure")
    monkeypatch.setattr(reviews.os, "fsync", fail_fsync)
    assert record(client, exported, basis).status_code == 409
    assert stored_records(exported) == [first] and first.read_bytes() == before
    assert list(first.parent.glob(".slidecaptain-review-*.tmp")) == []
