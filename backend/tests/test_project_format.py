"""프로젝트 형식 기록과 이전 (개정판 D2a-1).

형식 1은 0.2.0이 읽을 수 있는 덱, 형식 2는 그렇지 않은 덱이다. 판정 근거는 manifest가 아니라
덱 내용이다. 0.2.0은 manifest를 모른 채 deck.json만 다시 쓰기 때문이다.
"""

import hashlib
import json

import pytest

from slidecaptain.models.deck import Deck, DeckMeta
from slidecaptain.storage import project_format
from slidecaptain.storage.file_store import FileProjectStore, ProjectFormatTooNew
from slidecaptain.storage.project_format import (
    MAX_SUPPORTED_FORMAT,
    deck_format,
    read_manifest,
)


@pytest.fixture
def store(tmp_path):
    return FileProjectStore(tmp_path / "projects")


def _deck(report_type="research", title="보고"):
    return Deck(meta=DeckMeta(title=title, report_type=report_type))


def _manifest(store, name="p1"):
    return read_manifest(store.root / name)


def _write_legacy_deck(store, name="p1", report_type="research"):
    """0.2.0이 하듯 manifest를 건드리지 않고 deck.json만 교체한다."""
    path = store.root / name / "deck.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["meta"]["report_type"] = report_type
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_deck_format_is_one_for_legacy_report_types_and_two_otherwise():
    for legacy in ("research", "approval", "strategy"):
        assert deck_format(_deck(legacy)) == 1
    for new in ("weekly", "business", "monthly", "data", "project", "results"):
        assert deck_format(_deck(new)) == 2
    assert MAX_SUPPORTED_FORMAT == 2


def test_create_project_writes_manifest_after_deck(store):
    store.create_project("p1")
    manifest = _manifest(store)
    assert manifest is not None
    assert manifest.format_version == 1
    assert manifest.migrations == []


def test_reading_a_project_without_manifest_does_not_create_one(store):
    store.create_project("p1")
    (store.root / "p1" / "manifest.json").unlink()
    store.load_deck("p1")
    store.list_projects()
    store.list_snapshots("p1")
    assert not (store.root / "p1" / "manifest.json").exists()


def test_upgrade_save_forces_snapshot_and_records_done_migration(store):
    store.create_project("p1")
    before = (store.root / "p1" / "deck.json").read_bytes()
    store.save_deck("p1", _deck("weekly"), snapshot=False)
    manifest = _manifest(store)
    assert manifest.format_version == 2
    [record] = manifest.migrations
    assert (record.kind, record.from_format, record.to_format, record.status) == ("upgrade", 1, 2, "done")
    snapshot = store.root / "p1" / "snapshots" / f"{record.snapshot_id}.json"
    assert snapshot.read_bytes() == before


def test_second_save_in_new_format_does_not_force_snapshot(store):
    store.create_project("p1")
    store.save_deck("p1", _deck("weekly"), snapshot=False)
    count = len(store.list_snapshots("p1"))
    store.save_deck("p1", _deck("weekly", title="다시"), snapshot=False)
    assert len(store.list_snapshots("p1")) == count
    assert len(_manifest(store).migrations) == 1


def test_legacy_rewrite_by_old_app_triggers_a_new_forced_snapshot(store):
    """0.2.0이 manifest를 모른 채 형식 1 덱을 써 넣으면 manifest는 형식 2로 남는다.
    다음 형식 2 저장은 manifest가 아니라 디스크 내용을 보고 다시 강제 스냅샷을 남긴다."""
    store.create_project("p1")
    store.save_deck("p1", _deck("weekly"), snapshot=False)
    _write_legacy_deck(store, report_type="approval")
    assert _manifest(store).format_version == 2  # 0.2.0은 manifest를 고치지 않는다
    legacy_bytes = (store.root / "p1" / "deck.json").read_bytes()
    store.save_deck("p1", _deck("monthly"), snapshot=False)
    upgrades = [m for m in _manifest(store).migrations if m.kind == "upgrade"]
    assert len(upgrades) == 2
    snapshot = store.root / "p1" / "snapshots" / f"{upgrades[-1].snapshot_id}.json"
    assert snapshot.read_bytes() == legacy_bytes


def test_project_without_manifest_holding_new_type_gets_format_two_manifest(store):
    store.create_project("p1")
    (store.root / "p1" / "manifest.json").unlink()
    _write_legacy_deck(store, report_type="weekly")  # D2a 이전 개발본이 만든 프로젝트
    store.save_deck("p1", _deck("weekly", title="편집"), snapshot=False)
    manifest = _manifest(store)
    assert manifest.format_version == 2
    assert [m for m in manifest.migrations if m.kind == "upgrade"] == []


def test_downgrade_save_records_format_one(store):
    store.create_project("p1")
    store.save_deck("p1", _deck("weekly"), snapshot=False)
    store.save_deck("p1", _deck("research"), snapshot=False)
    manifest = _manifest(store)
    assert manifest.format_version == 1
    assert manifest.migrations[-1].kind == "downgrade"


def test_interrupted_upgrade_after_pending_record_is_repaired_on_next_write(store, monkeypatch):
    store.create_project("p1")
    original = store._write_deck

    def boom(project_dir, deck):
        raise OSError("디스크 오류 흉내")

    monkeypatch.setattr(store, "_write_deck", boom)
    with pytest.raises(OSError):
        store.save_deck("p1", _deck("weekly"), snapshot=False)
    assert _manifest(store).migrations[-1].status == "pending"
    monkeypatch.setattr(store, "_write_deck", original)
    store.save_deck("p1", _deck("research", title="다음"), snapshot=False)
    statuses = [m.status for m in _manifest(store).migrations]
    assert "pending" not in statuses
    assert statuses[0] == "not_applied"  # deck.json은 형식 1 그대로였다
    assert _manifest(store).format_version == 1


def test_manifest_failure_after_deck_does_not_fail_the_save_and_next_write_repairs(store, monkeypatch):
    """덱 교체 뒤의 기록 실패는 저장 실패가 아니다 (리뷰 R5). 저장은 ETag를 돌려주고,
    다음 쓰기가 pending 기록을 덱 내용으로 마무리한다."""
    store.create_project("p1")
    calls = {"n": 0}
    original = project_format.write_manifest

    def flaky(project_dir, manifest, atomic_write):
        calls["n"] += 1
        if calls["n"] == 2:  # pending 기록 다음의 완료 기록에서 끊긴다
            raise OSError("디스크 오류 흉내")
        return original(project_dir, manifest, atomic_write)

    monkeypatch.setattr(project_format, "write_manifest", flaky)
    etag = store.save_deck("p1", _deck("weekly"), snapshot=False)
    assert etag == store.deck_etag("p1")
    monkeypatch.setattr(project_format, "write_manifest", original)
    assert _manifest(store).migrations[-1].status == "pending"
    store.save_deck("p1", _deck("weekly", title="다음"), snapshot=False)
    manifest = _manifest(store)
    assert manifest.format_version == 2
    assert [m.status for m in manifest.migrations] == ["done"]


def test_pending_record_failure_before_deck_still_fails_and_keeps_deck(store, monkeypatch):
    store.create_project("p1")
    before = (store.root / "p1" / "deck.json").read_bytes()

    def boom(project_dir, manifest, atomic_write):
        raise OSError("디스크 오류 흉내")

    monkeypatch.setattr(project_format, "write_manifest", boom)
    with pytest.raises(OSError):
        store.save_deck("p1", _deck("weekly"), snapshot=False)
    assert (store.root / "p1" / "deck.json").read_bytes() == before


def test_snapshot_writes_are_atomic(store, monkeypatch):
    """스냅샷도 임시 파일에 쓴 뒤 교체한다. 중간에 끊겨도 잘린 스냅샷이 목록에 남지 않는다."""
    store.create_project("p1")
    import os

    real_replace = os.replace

    def failing_replace(src, dst):
        if "snapshots" in str(dst):
            raise OSError("교체 실패 흉내")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", failing_replace)
    with pytest.raises(OSError):
        store.save_deck("p1", _deck(), snapshot=True)
    monkeypatch.setattr(os, "replace", real_replace)
    snapshots_dir = store.root / "p1" / "snapshots"
    assert list(snapshots_dir.glob("deck-*.json")) == []
    assert [p for p in snapshots_dir.iterdir() if p.name.startswith(".")] == []


def test_pre_migration_snapshot_is_marked_in_listing(store):
    store.create_project("p1")
    store.save_deck("p1", _deck("research", title="일반"), snapshot=True)
    store.save_deck("p1", _deck("weekly"), snapshot=False)
    kinds = {s.id: s.kind for s in store.list_snapshots("p1")}
    [record] = _manifest(store).migrations
    assert kinds[record.snapshot_id] == "pre_migration"
    assert sorted(kinds.values()) == ["pre_migration", "snapshot"]


def test_restoring_pre_migration_snapshot_records_downgrade_and_format_one(store):
    store.create_project("p1")
    store.save_deck("p1", _deck("weekly"), snapshot=False)
    [record] = _manifest(store).migrations
    store.restore_snapshot("p1", record.snapshot_id)
    manifest = _manifest(store)
    assert manifest.format_version == 1
    assert manifest.migrations[-1].kind == "downgrade"
    assert store.load_deck("p1").meta.report_type == "research"


def _make_newer(store, name="p1"):
    path = store.root / name / "manifest.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["format_version"] = MAX_SUPPORTED_FORMAT + 1
    data["future_field"] = {"x": 1}
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_newer_format_project_is_listed_without_reading_deck(store):
    store.create_project("p1")
    _make_newer(store)
    (store.root / "p1" / "deck.json").write_text('{"schema_version": 1, "meta": {"title": "x"}, "future": 1}', encoding="utf-8")
    [info] = store.list_projects()
    assert info.status == "newer_format"


@pytest.mark.parametrize(
    "operation",
    [
        lambda s: s.load_deck("p1"),
        lambda s: s.load_deck_with_etag("p1"),
        lambda s: s.deck_etag("p1"),
        lambda s: s.save_deck("p1", _deck()),
        lambda s: s.snapshot_now("p1"),
        lambda s: s.list_snapshots("p1"),
        lambda s: s.restore_snapshot("p1", "deck-20260101-000000-000000"),
        lambda s: s.list_sources("p1"),
        lambda s: s.write_source("p1", "a.md", "x"),
        lambda s: s.write_upload("p1", "a.md", b"x"),
        lambda s: s.exports_dir("p1"),
        lambda s: s.export_history_dir("p1"),
        lambda s: s.append_usage("p1", "{}"),
        lambda s: s.read_source("p1", "a.md"),
        lambda s: s.source_exists("p1", "a.md"),
        lambda s: s.read_upload("p1", "a.md"),
        lambda s: s.delete_upload("p1", "a.md"),
    ],
)
def test_newer_format_project_refuses_every_access_and_keeps_files(store, operation):
    store.create_project("p1")
    store.save_deck("p1", _deck(), snapshot=True)
    _make_newer(store)
    project = store.root / "p1"
    before = {p.relative_to(project): p.read_bytes() for p in project.rglob("*") if p.is_file()}
    with pytest.raises(ProjectFormatTooNew):
        operation(store)
    after = {p.relative_to(project): p.read_bytes() for p in project.rglob("*") if p.is_file()}
    assert after == before


def test_deck_json_schema_is_pinned_to_the_supported_format():
    """덱 스키마가 바뀌면 deck_format과 MAX_SUPPORTED_FORMAT을 함께 검토해야 한다.

    이 앱은 모르는 필드를 읽을 때 버린다. 새 필드를 더하면서 형식을 올리지 않으면 이전 앱이
    그 필드를 경고 없이 지운다. 스키마를 바꿨다면 형식 판정을 갱신한 뒤 아래 해시를 바꾼다.
    """
    schema = json.dumps(Deck.model_json_schema(), sort_keys=True, ensure_ascii=False)
    digest = hashlib.sha256(schema.encode("utf-8")).hexdigest()
    assert (MAX_SUPPORTED_FORMAT, digest) == (2, project_format.PINNED_DECK_SCHEMA_SHA256), (
        "덱 스키마가 바뀌었습니다. storage/project_format.py의 deck_format과 MAX_SUPPORTED_FORMAT을 "
        f"검토하고 PINNED_DECK_SCHEMA_SHA256을 {digest}로 갱신해 주세요"
    )


# -- 독립 리뷰 반영 (2026-10-08, R1~R12) -------------------------------------------------

FIXTURES = __import__("pathlib").Path(__file__).parent / "fixtures"


def _story_deck(meta_type="research", brief_type="approval"):
    payload = json.loads((FIXTURES / "q2a-story-deck.json").read_text(encoding="utf-8"))["deck"]
    payload["meta"]["report_type"] = meta_type
    payload["structure"]["story_plan"]["brief"]["report_type"] = brief_type
    return Deck.model_validate(payload)


def test_report_type_inside_the_story_plan_also_decides_the_format():
    """0.2.0은 구성 계획의 보고 유형도 검증한다 (리뷰 R1)."""
    assert deck_format(_story_deck("research", "approval")) == 1
    assert deck_format(_story_deck("research", "weekly")) == 2
    data = _story_deck("research", "weekly").model_dump_json().encode("utf-8")
    assert project_format.deck_format_of_bytes(data) == 2


def test_format_judgement_covers_every_report_type_location_in_the_schema():
    schema = Deck.model_json_schema()
    found = set()
    for definition, body in schema["$defs"].items():
        for prop, spec in body.get("properties", {}).items():
            if "weekly" in json.dumps(spec):
                found.add((definition, prop))
    assert found == project_format.REPORT_TYPE_LOCATIONS


def test_reverting_meta_type_while_plan_keeps_new_type_stays_format_two(store):
    store.create_project("p1")
    store.save_deck("p1", _story_deck("weekly", "weekly"), snapshot=False)
    store.save_deck("p1", _story_deck("research", "weekly"), snapshot=False)  # 자료 화면의 유형 되돌림
    manifest = _manifest(store)
    assert manifest.format_version == 2
    assert [m.kind for m in manifest.migrations] == ["upgrade"]


def test_unknown_manifest_fields_and_record_kinds_are_preserved(store):
    store.create_project("p1")
    store.save_deck("p1", _deck("weekly"), snapshot=False)
    path = store.root / "p1" / "manifest.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["future_field"] = {"x": 1}
    data["migrations"].append({"at": "2026-12-01T00:00:00+09:00", "kind": "repair", "from_format": 2,
                               "to_format": 2, "status": "verified", "note": "이후 앱"})
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    store.save_deck("p1", _deck("weekly", title="다시"), snapshot=False)
    after = json.loads(path.read_text(encoding="utf-8"))
    assert after["future_field"] == {"x": 1}
    assert [m["kind"] for m in after["migrations"]] == ["upgrade", "repair"]
    assert after["migrations"][1]["note"] == "이후 앱"
    assert [s.kind for s in store.list_snapshots("p1")] == ["pre_migration"]


@pytest.mark.parametrize("content", [
    b"{not json", b"[]", b'{"format_version": "3"}', b'{"format_version": 3.0}',
    b'{"format_version": 0}', b'{"format_version": -1}', b'{"format_version": true}',
    b'{"format_version": 2, "migrations": "x"}',
])
def test_unreadable_manifest_blocks_the_project_and_is_never_overwritten(store, content):
    from slidecaptain.storage.file_store import ProjectManifestUnreadable

    store.create_project("p1")
    path = store.root / "p1" / "manifest.json"
    path.write_bytes(content)
    [info] = store.list_projects()
    assert info.status == "unreadable_manifest"
    with pytest.raises(ProjectManifestUnreadable):
        store.save_deck("p1", _deck())
    with pytest.raises(ProjectManifestUnreadable):
        store.load_deck("p1")
    assert path.read_bytes() == content


def test_interrupted_between_snapshot_and_pending_loses_nothing_and_next_save_marks_a_new_copy(store, monkeypatch):
    """리뷰 R6: 덱은 그대로이고, 다음 형식 2 저장이 새 복구 지점을 만든다."""
    store.create_project("p1")
    before = (store.root / "p1" / "deck.json").read_bytes()

    def boom(project_dir, manifest, atomic_write):
        raise OSError("pending 기록 실패 흉내")

    monkeypatch.setattr(project_format, "write_manifest", boom)
    with pytest.raises(OSError):
        store.save_deck("p1", _deck("weekly"), snapshot=False)
    monkeypatch.undo()
    assert (store.root / "p1" / "deck.json").read_bytes() == before
    store.save_deck("p1", _deck("weekly"), snapshot=False)
    kinds = [s.kind for s in store.list_snapshots("p1")]
    assert kinds.count("pre_migration") == 1


def test_not_applied_upgrade_snapshot_is_not_marked_pre_migration(store, monkeypatch):
    store.create_project("p1")

    def boom(project_dir, deck):
        raise OSError("덱 교체 실패 흉내")

    monkeypatch.setattr(store, "_write_deck", boom)
    with pytest.raises(OSError):
        store.save_deck("p1", _deck("weekly"), snapshot=False)
    monkeypatch.undo()
    store.save_deck("p1", _deck("research", title="다음"), snapshot=False)
    assert [m.status for m in _manifest(store).migrations] == ["not_applied"]
    assert "pre_migration" not in [s.kind for s in store.list_snapshots("p1")]


def test_external_revert_by_old_app_is_recorded(store):
    store.create_project("p1")
    store.save_deck("p1", _deck("weekly"), snapshot=False)
    _write_legacy_deck(store, report_type="approval")  # 0.2.0의 저장이나 복원
    store.save_deck("p1", _deck("approval", title="새 앱"), snapshot=False)
    kinds = [m.kind for m in _manifest(store).migrations]
    assert kinds == ["upgrade", "external_downgrade"]
    assert _manifest(store).format_version == 1


def test_broken_legacy_typed_deck_is_not_offered_as_pre_migration_copy(store):
    """리뷰 R9: 형식 판정이 1이어도 0.2.0이 열지 못하는 깨진 덱은 이전 전 복사본이 아니다."""
    store.create_project("p1")
    path = store.root / "p1" / "deck.json"
    path.write_text('{"schema_version": 1, "meta": {"title": "x", "report_type": "research"}, "slides": 5}',
                    encoding="utf-8")
    store.save_deck("p1", _deck("weekly"), snapshot=False)
    assert [m.kind for m in _manifest(store).migrations if m.kind == "upgrade"] == []
    assert "pre_migration" not in [s.kind for s in store.list_snapshots("p1")]


def test_snapshot_keeps_the_saved_deck_modification_time(store):
    import os

    store.create_project("p1")
    deck_path = store.root / "p1" / "deck.json"
    os.utime(deck_path, ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000))
    store.save_deck("p1", _deck(title="다음"), snapshot=True)
    [snapshot] = list((store.root / "p1" / "snapshots").glob("deck-*.json"))
    assert snapshot.stat().st_mtime_ns == 1_700_000_000_000_000_000


def test_unchanged_manifest_is_not_rewritten(store, monkeypatch):
    store.create_project("p1")
    store.save_deck("p1", _deck(title="한 번"), snapshot=False)
    writes = []
    original = store._atomic_write

    def spy(dir_path, filename, data, **kwargs):
        writes.append(filename)
        return original(dir_path, filename, data, **kwargs)

    monkeypatch.setattr(store, "_atomic_write", spy)
    store.save_deck("p1", _deck(title="두 번"), snapshot=False)
    assert writes == ["deck.json"]


def test_cli_export_and_quality_refuse_a_newer_format_project(store):
    import subprocess
    import sys

    store.create_project("p1")
    _make_newer(store)
    deck = store.root / "p1" / "deck.json"
    for command in ("export", "quality"):
        result = subprocess.run([sys.executable, "-m", "slidecaptain", command, str(deck)],
                                capture_output=True, text=True, encoding="utf-8", errors="replace",
                                env={**__import__("os").environ, "PYTHONUTF8": "1"})
        assert result.returncode == 1, (command, result.stdout, result.stderr)
        assert "더 새 버전" in result.stderr
    assert not any((store.root / "p1" / "exports").iterdir())


# -- D2a 묶음 최종 리뷰 반영 (F3, F16) ----------------------------------------------------


def test_own_downgrade_with_failed_final_record_is_not_reported_as_external(store, monkeypatch):
    """이 앱의 형식 2→1 저장에서 마지막 기록이 실패해도, 다음 쓰기가 0.2.0의 되돌림으로 잘못 기록하지 않는다 (F3)."""
    store.create_project("p1")
    store.save_deck("p1", _deck("weekly"), snapshot=False)
    original = project_format.write_manifest

    def flaky(project_dir, manifest, atomic_write):
        # 덱 교체 뒤의 마지막 기록(pending이 없는 기록)에서 끊긴다. 쓰기 횟수와 무관하게 같은 지점이다
        if not any(m.status == "pending" for m in manifest.migrations):
            raise OSError("디스크 오류 흉내")
        return original(project_dir, manifest, atomic_write)

    monkeypatch.setattr(project_format, "write_manifest", flaky)
    store.save_deck("p1", _deck("research"), snapshot=False)
    monkeypatch.setattr(project_format, "write_manifest", original)
    store.save_deck("p1", _deck("research", title="다음"), snapshot=False)
    kinds = [(m.kind, m.status) for m in _manifest(store).migrations]
    assert kinds == [("upgrade", "done"), ("downgrade", "done")]


def test_upgrade_over_a_broken_legacy_deck_still_leaves_a_snapshot(store):
    """깨진 형식 1 덱 위의 형식 2 저장도 복구 지점을 남긴다. 다만 이전 전 복사본으로 표시하지 않는다 (F16)."""
    store.create_project("p1")
    path = store.root / "p1" / "deck.json"
    broken = '{"schema_version": 1, "meta": {"title": "x", "report_type": "research"}, "slides": 5}'
    path.write_text(broken, encoding="utf-8")
    store.save_deck("p1", _deck("weekly"), snapshot=False)
    snapshots = list((store.root / "p1" / "snapshots").glob("deck-*.json"))
    assert [s.read_text(encoding="utf-8") for s in snapshots] == [broken]
    assert [s.kind for s in store.list_snapshots("p1")] == ["snapshot"]
