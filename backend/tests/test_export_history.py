"""Published bytes and current inputs, not file presence, establish a match."""

import hashlib
import json
import os
from pathlib import Path
from urllib.parse import quote

import pytest

from test_export_quality import setup_project


BASE = "/api/projects/synthetic/exports"


def publish(client, store):
    setup_project(store)
    response = client.post("/api/projects/synthetic/export")
    assert response.status_code == 200
    return response.json()


def detail(client, exported):
    return client.get(f"{BASE}/{quote(Path(exported['path']).stem, safe='')}")


def rewrite_record(exported, change):
    path = Path(exported["quality_path"])
    record = json.loads(path.read_text(encoding="utf-8"))
    change(record)
    path.write_text(json.dumps(record), encoding="utf-8")


def test_history_roundtrip_is_read_only_and_does_not_approve_quality(client, store):
    exported = publish(client, store)
    before = {p: p.read_bytes() for p in store.root.rglob("*") if p.is_file()}
    listing = client.get(BASE)
    assert listing.status_code == 200
    assert listing.headers["cache-control"] == "no-store"
    page = listing.json()
    assert page["total"] == 1
    assert page["current_input_fingerprint"] == exported["quality"]["input_fingerprint"]
    assert page["current_input_error"] is None
    response = detail(client, exported)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    data = response.json()
    assert page["items"] == [data["item"]]
    assert data["quality"] == exported["quality"]
    assert data["artifact_sha256"] == hashlib.sha256(Path(exported["path"]).read_bytes()).hexdigest()
    assert (data["item"]["record_status"], data["item"]["artifact_status"], data["item"]["input_status"]) == (
        "readable", "matched", "current",
    )
    assert data["quality"]["final_export_allowed"] is False
    assert {p: p.read_bytes() for p in store.root.rglob("*") if p.is_file()} == before


@pytest.mark.parametrize("change", ["source", "deck", "preset"])
def test_input_edits_invalidate_history_without_changing_original_and_restore_matches(client, store, change):
    exported = publish(client, store)
    before = Path(exported["quality_path"]).read_bytes()
    if change == "source":
        target = store.root / "synthetic/sources/synthetic.md"
    elif change == "deck":
        target = store.root / "synthetic/deck.json"
    else:
        store.save_global_preset(store.load_global_preset())
        target = store.root / "preset.json"
    original = target.read_bytes()
    if change == "source":
        target.write_bytes(original + b"\nChanged")
    else:
        data = json.loads(original)
        if change == "deck":
            data["meta"]["title"] = "Renamed report"
        else:
            data["colors"]["accent"] = "BB0000"
        target.write_text(json.dumps(data), encoding="utf-8")
    item = detail(client, exported).json()["item"]
    assert item["input_status"] == "stale"
    assert item["artifact_status"] == "matched"
    assert client.get(BASE).json()["total"] == 1  # Renaming does not hide old titles.
    target.write_bytes(original)
    assert detail(client, exported).json()["item"]["input_status"] == "current"
    assert Path(exported["quality_path"]).read_bytes() == before


@pytest.mark.parametrize("kind,record_status,artifact_status,input_status", [
    ("missing_pptx", "readable", "missing", "current"),
    ("changed_pptx", "readable", "mismatch", "current"),
    ("missing_record", "missing", "unverified", "unavailable"),
    ("broken_record", "invalid", "unverified", "unavailable"),
    ("unsupported", "unsupported", "unverified", "unavailable"),
    ("legacy", "readable", "matched", "legacy"),
    ("missing_hash", "readable", "unverified", "current"),
    ("missing_version", "invalid", "unverified", "unavailable"),
    ("invalid_fingerprint", "invalid", "unverified", "unavailable"),
])
def test_independent_history_states(client, store, kind, record_status, artifact_status, input_status):
    exported = publish(client, store)
    artifact, record = Path(exported["path"]), Path(exported["quality_path"])
    if kind == "missing_pptx":
        artifact.unlink()
    elif kind == "changed_pptx":
        artifact.write_bytes(b"externally edited PPTX")
    elif kind == "missing_record":
        record.unlink()
    elif kind == "broken_record":
        record.write_text("{broken", encoding="utf-8")
    elif kind == "unsupported":
        rewrite_record(exported, lambda r: r.update(gate_version="preflight-v99"))
    elif kind == "legacy":
        rewrite_record(exported, lambda r: (r.update(gate_version="preflight-v1"), r.pop("numeric_review")))
    elif kind == "missing_hash":
        rewrite_record(exported, lambda r: r.pop("artifact_sha256"))
    elif kind == "missing_version":
        rewrite_record(exported, lambda r: r.pop("gate_version"))
    else:
        rewrite_record(exported, lambda r: r.update(input_fingerprint=""))
    result = detail(client, exported)
    assert result.status_code == 200
    item = result.json()["item"]
    assert (item["record_status"], item["artifact_status"], item["input_status"]) == (
        record_status, artifact_status, input_status,
    )
    assert client.get(BASE).json()["items"] == [item]


def test_combined_damage_is_not_hidden_by_stale_input(client, store):
    exported = publish(client, store)
    Path(exported["path"]).unlink()
    store.write_source("synthetic", "extra.md", "Changed sources")
    item = detail(client, exported).json()["item"]
    assert (item["artifact_status"], item["input_status"]) == ("missing", "stale")


@pytest.mark.parametrize("broken", ["source", "deck", "preset"])
def test_current_input_failure_keeps_history_readable(client, store, broken):
    exported = publish(client, store)
    target = {"source": "synthetic/sources/synthetic.md", "deck": "synthetic/deck.json", "preset": "preset.json"}[broken]
    (store.root / target).write_bytes(b"\xff")
    result = detail(client, exported)
    assert result.status_code == 200
    data = result.json()
    assert data["quality"] == exported["quality"]
    assert data["item"]["input_status"] == "unavailable"
    assert data["item"]["artifact_status"] == "matched"
    assert data["current_input_fingerprint"] is None
    assert data["current_input_error"]


def test_empty_missing_directory_does_not_create_files_or_lock(client, store):
    setup_project(store)
    directory = store.exports_dir("synthetic")
    directory.rmdir()
    before = set(store.root.rglob("*"))
    response = client.get(BASE)
    assert response.status_code == 200
    assert response.json()["total"] == 0
    assert response.json()["items"] == []
    assert set(store.root.rglob("*")) == before


def test_pagination_includes_orphans_ignores_temp_files_and_orders_by_file_mtime(client, store):
    exported = publish(client, store)
    directory = Path(exported["path"]).parent
    for number in range(2, 7):
        path = directory / f"old_title_v{number:03d}.quality.json"
        path.write_text("{}", encoding="utf-8")
        os.utime(path, (2_000_000_000 + number, 2_000_000_000 + number))
    (directory / ".slidecaptain-export-temp").mkdir()
    (directory / "unrelated.json").write_text("{}", encoding="utf-8")
    page1 = client.get(BASE, params={"offset": 0, "limit": 2}).json()
    page2 = client.get(BASE, params={"offset": 2, "limit": 2}).json()
    assert page1["total"] == page2["total"] == 6
    assert [i["id"] for i in page1["items"]] == ["old_title_v006", "old_title_v005"]
    assert [i["id"] for i in page2["items"]] == ["old_title_v004", "old_title_v003"]
    assert client.get(BASE, params={"offset": 999}).json()["items"] == []


@pytest.mark.parametrize("params", [{"offset": -1}, {"limit": 0}, {"limit": 101}])
def test_pagination_is_bounded(client, store, params):
    setup_project(store)
    assert client.get(BASE, params=params).status_code == 422


def test_unknown_project_and_export_are_not_found(client, store):
    assert client.get(BASE).status_code == 404
    setup_project(store)
    assert client.get(f"{BASE}/absent_v001").status_code == 404


@pytest.mark.parametrize("name", ["..\\escape_v001", "C:escape_v001", "bad.json"])
def test_bad_record_ids_are_rejected(client, store, name):
    setup_project(store)
    assert client.get(f"{BASE}/{quote(name, safe='')}").status_code == 422


@pytest.mark.parametrize("component", ["pptx", "quality.json"])
def test_file_symlinks_never_expose_external_bytes(client, store, tmp_path, component):
    exported = publish(client, store)
    path = Path(exported["path"] if component == "pptx" else exported["quality_path"])
    outside = tmp_path / "private.txt"
    outside.write_text("PRIVATE CONTENT", encoding="utf-8")
    path.unlink()
    path.symlink_to(outside)
    response = detail(client, exported)
    assert response.status_code == 200
    item = response.json()["item"]
    assert item["artifact_status" if component == "pptx" else "record_status"] == "unreadable"
    assert "PRIVATE CONTENT" not in response.text
    assert outside.read_text(encoding="utf-8") == "PRIVATE CONTENT"


def test_exports_symlink_is_not_followed(client, store, tmp_path):
    setup_project(store)
    directory = store.exports_dir("synthetic")
    directory.rmdir()
    directory.symlink_to(tmp_path, target_is_directory=True)
    assert client.get(BASE).status_code == 422


def test_nonregular_files_are_unreadable_without_opening(client, store):
    exported = publish(client, store)
    path = Path(exported["path"])
    path.unlink()
    path.mkdir()
    assert detail(client, exported).json()["item"]["artifact_status"] == "unreadable"


def test_missing_deck_still_allows_history_lookup(client, store):
    exported = publish(client, store)
    (store.root / "synthetic/deck.json").unlink()
    assert client.get(BASE).status_code == 200
    data = detail(client, exported).json()
    assert data["quality"] == exported["quality"]
    assert data["item"]["input_status"] == "unavailable"


@pytest.mark.parametrize("title", ["보고서 (초안)", ".hidden title", "v1..0 결과"])
def test_all_exporter_titles_remain_accessible(client, store, title):
    setup_project(store)
    deck = store.load_deck("synthetic")
    deck.meta.title = title
    store.save_deck("synthetic", deck)
    exported = client.post("/api/projects/synthetic/export").json()
    assert client.get(BASE).json()["total"] == 1
    assert detail(client, exported).json()["item"]["artifact_status"] == "matched"


@pytest.mark.parametrize("component", ["pptx", "quality.json"])
def test_file_read_errors_are_not_reported_as_missing(client, store, monkeypatch, component):
    from slidecaptain.export import history
    exported = publish(client, store)
    original = history._read_regular
    def denied(path, **kwargs):
        if path.name.endswith(component):
            raise PermissionError("private details must not be returned")
        return original(path, **kwargs)
    monkeypatch.setattr(history, "_read_regular", denied)
    response = detail(client, exported)
    assert response.status_code == 200
    field = "artifact_status" if component == "pptx" else "record_status"
    assert response.json()["item"][field] == "unreadable"
    assert "private details" not in response.text


def test_directory_read_error_is_not_empty_history(client, store, monkeypatch):
    from slidecaptain.export import history
    publish(client, store)
    def denied(_):
        raise PermissionError("private directory")
    monkeypatch.setattr(history.os, "scandir", denied)
    response = client.get(BASE)
    assert response.status_code == 422
    assert "private directory" not in response.text


def test_large_record_is_not_loaded(client, store, monkeypatch):
    from slidecaptain.export import history
    exported = publish(client, store)
    monkeypatch.setattr(history, "_MAX_RECORD_BYTES", 10)
    assert detail(client, exported).json()["item"]["record_status"] == "unreadable"


def test_replaced_record_after_artifact_read_cannot_produce_match(client, store, monkeypatch):
    from slidecaptain.export import history
    exported = publish(client, store)
    original = history._read_regular
    def replace_record(path, **kwargs):
        result = original(path, **kwargs)
        if kwargs.get("digest"):
            Path(exported["quality_path"]).write_text("{}", encoding="utf-8")
        return result
    monkeypatch.setattr(history, "_read_regular", replace_record)
    data = detail(client, exported).json()
    assert data["quality"] is None
    assert (data["item"]["record_status"], data["item"]["artifact_status"], data["item"]["input_status"]) == (
        "unreadable", "unverified", "unavailable",
    )


def test_file_replacement_between_stat_and_open_is_rejected(client, store, monkeypatch, tmp_path):
    from slidecaptain.export import history
    exported = publish(client, store)
    target = Path(exported["path"])
    replacement = tmp_path / "replacement.pptx"
    replacement.write_bytes(target.read_bytes())
    original = history.os.open
    def replaced(path, flags, *args, **kwargs):
        if path == target or path == target.name:
            os.replace(replacement, target)
        return original(path, flags, *args, **kwargs)
    monkeypatch.setattr(history.os, "open", replaced)
    assert detail(client, exported).json()["item"]["artifact_status"] == "unreadable"


def test_only_selected_page_artifacts_are_read(client, store, monkeypatch):
    from slidecaptain.export import history
    exported = publish(client, store)
    directory = Path(exported["path"]).parent
    for number in range(2, 6):
        (directory / f"report_v{number:03d}.pptx").write_bytes(b"synthetic")
    original = history._read_regular
    artifacts = []
    def counted(path, **kwargs):
        if kwargs.get("digest"):
            artifacts.append(path.name)
        return original(path, **kwargs)
    monkeypatch.setattr(history, "_read_regular", counted)
    response = client.get(BASE, params={"limit": 2})
    assert response.json()["total"] == 5
    assert len(artifacts) == 2


@pytest.mark.skipif(os.name == "nt", reason="Windows pins directory names against rename")
def test_transient_directory_symlink_never_returns_external_records(client, store, monkeypatch, tmp_path):
    from slidecaptain.export import history
    exported = publish(client, store)
    directory = Path(exported["path"]).parent
    backup = directory.with_name("exports-original")
    outside = tmp_path / "outside"
    outside.mkdir()
    record = dict(exported["quality"], notice="OUTSIDE PRIVATE RECORD")
    (outside / Path(exported["quality_path"]).name).write_text(json.dumps(record), encoding="utf-8")
    (outside / Path(exported["path"]).name).write_bytes(Path(exported["path"]).read_bytes())
    original = history._inspect
    def swapped(path, *args, **kwargs):
        directory.rename(backup)
        directory.symlink_to(outside, target_is_directory=True)
        try:
            return original(path, *args, **kwargs)
        finally:
            directory.unlink()
            backup.rename(directory)
    monkeypatch.setattr(history, "_inspect", swapped)
    response = detail(client, exported)
    assert response.status_code in (200, 422)
    assert "OUTSIDE PRIVATE RECORD" not in response.text


@pytest.mark.skipif(os.name != "nt", reason="Requires native Windows file handles")
def test_windows_directory_handles_prevent_rename_and_release_after_query(client, store):
    from slidecaptain.export import history
    exported = publish(client, store)
    directory = Path(exported["path"]).parent
    moved = directory.with_name("exports-moved")
    with history._pin_directory(directory, history._directory_identity(directory)) as reader:
        with pytest.raises(OSError):
            directory.rename(moved)
        data, _ = history._read_regular(Path(exported["path"]), reader=reader, digest=True)
        assert data == exported["quality"]["artifact_sha256"]
    directory.rename(moved)
    moved.rename(directory)
