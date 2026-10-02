"""Publication must never follow substituted lock files or output directories."""

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from slidecaptain.export import exporter, locking
from slidecaptain.models.deck import Bullet, BulletBoxSlots, Chapter, Deck, DeckMeta, Slide, Structure


LOCK = ".slidecaptain-export.lock"


def _symlink(path, target, *, directory=False):
    try:
        path.symlink_to(target, target_is_directory=directory)
    except OSError:
        pytest.skip("symlink creation unavailable on this device")


def _deck():
    return Deck(meta=DeckMeta(title="safe"),
                structure=Structure(chapters=[Chapter(id="c1", topic="Overview", template="bullet_box")]),
                slides=[Slide(chapter_id="c1", slots=BulletBoxSlots(
                    bullets=[Bullet(text="Synthetic input")], conclusion="Draft conclusion"))])


@pytest.mark.parametrize("existing", [True, False])
def test_lock_symlink_never_opens_or_creates_target(tmp_path, existing):
    output = tmp_path / "output"
    output.mkdir()
    target = tmp_path / "outside"
    if existing:
        target.write_bytes(b"unchanged")
    _symlink(output / LOCK, target)
    with pytest.raises((OSError, ValueError)):
        with locking.export_directory_lock(output):
            pytest.fail("symlink lock accepted")
    assert target.exists() is existing
    if existing:
        assert target.read_bytes() == b"unchanged"


def test_nonregular_lock_rejected_before_open(tmp_path):
    (tmp_path / LOCK).mkdir()
    with pytest.raises((OSError, ValueError)):
        with locking.export_directory_lock(tmp_path):
            pytest.fail("directory lock accepted")


@pytest.mark.skipif(os.name == "nt", reason="POSIX injected rename/unlink boundary; Windows pins deny replacement")
def test_lock_replacement_during_wait_rejected(tmp_path, monkeypatch):
    path = tmp_path / LOCK
    path.touch()
    real_try = locking._try_lock

    def replace(fd):
        real_try(fd)
        path.rename(tmp_path / "original-lock")
        path.touch()

    monkeypatch.setattr(locking, "_try_lock", replace)
    with pytest.raises((OSError, ValueError)):
        with locking.export_directory_lock(tmp_path):
            pytest.fail("substituted inode accepted")


@pytest.mark.skipif(os.name == "nt", reason="POSIX injected rename/unlink boundary; Windows pins deny replacement")
def test_export_output_replaced_during_render_never_publishes(tmp_path, monkeypatch):
    output = tmp_path / "output"
    output.mkdir()
    moved = tmp_path / "moved"
    real_write = exporter.write_pptx

    def replace(plan, destination):
        real_write(plan, destination)
        stage_name = next(output.glob(".slidecaptain-export-*")).name
        output.rename(moved)
        output.mkdir()
        _symlink(output / stage_name, moved / stage_name, directory=True)

    monkeypatch.setattr(exporter, "write_pptx", replace)
    with pytest.raises((OSError, ValueError)):
        exporter.export_deck_data(_deck(), output)
    assert not list(output.glob("*.pptx"))
    assert not list(output.glob("*.quality.json"))


def test_lock_reparse_attribute_rejected_before_open(tmp_path, monkeypatch):
    # Synthetic stat verifies the cross-platform boundary; this is not Windows execution.
    (tmp_path / LOCK).touch()
    real_stat = locking.os.stat

    def reparse(path, *args, **kwargs):
        result = real_stat(path, *args, **kwargs)
        if str(path).endswith(LOCK):
            values = {name: getattr(result, name) for name in dir(result) if name.startswith("st_")}
            values["st_file_attributes"] = 0x400
            return SimpleNamespace(**values)
        return result

    monkeypatch.setattr(locking.os, "stat", reparse)
    with pytest.raises((OSError, ValueError)):
        with locking.export_directory_lock(tmp_path):
            pytest.fail("reparse lock accepted")


@pytest.mark.skipif(os.name == "nt", reason="POSIX injected rename/unlink boundary; Windows pins deny replacement")
def test_existing_lock_swapped_to_symlink_during_open_rejected(tmp_path, monkeypatch):
    lock = tmp_path / LOCK
    lock.touch()
    target = tmp_path / "outside"
    target.write_bytes(b"preserve")
    real_open = locking.os.open

    def swapped(path, flags, *args, **kwargs):
        if Path(path).name == LOCK and not flags & os.O_CREAT:
            lock.unlink()
            _symlink(lock, target)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(locking.os, "open", swapped)
    with pytest.raises((OSError, ValueError)):
        with locking.export_directory_lock(tmp_path):
            pytest.fail("swapped lock accepted")
    assert target.read_bytes() == b"preserve"


@pytest.mark.skipif(os.name == "nt", reason="POSIX injected rename/unlink boundary; Windows pins deny replacement")
def test_render_stream_does_not_write_substituted_staging_file_or_cleanup_it(tmp_path, monkeypatch):
    outside = tmp_path / "outside"
    outside.write_bytes(b"foreign user file")
    real_write = exporter.write_pptx
    stage = []

    def substitute(plan, destination):
        path = next(tmp_path.glob(".slidecaptain-export-*"))
        stage.append(path)
        (path / "deck.pptx").unlink()
        _symlink(path / "deck.pptx", outside)
        real_write(plan, destination)

    monkeypatch.setattr(exporter, "write_pptx", substitute)
    with pytest.raises((OSError, ValueError)):
        exporter.export_deck_data(_deck(), tmp_path)
    assert outside.read_bytes() == b"foreign user file"
    assert (stage[0] / "deck.pptx").is_symlink()
    assert not list(tmp_path.glob("*.pptx"))


@pytest.mark.skipif(os.name == "nt", reason="POSIX injected rename/unlink boundary; Windows pins deny replacement")
def test_staging_directory_substitution_preserves_foreign_tree(tmp_path, monkeypatch):
    real_write = exporter.write_pptx
    moved = tmp_path / "original-stage"
    substituted = []

    def substitute(plan, destination):
        path = next(tmp_path.glob(".slidecaptain-export-*"))
        path.rename(moved)
        path.mkdir()
        (path / "deck.pptx").write_bytes(b"foreign staged bytes")
        (path / "user-file").write_bytes(b"preserve")
        substituted.append(path)
        real_write(plan, destination)

    monkeypatch.setattr(exporter, "write_pptx", substitute)
    with pytest.raises((OSError, ValueError)):
        exporter.export_deck_data(_deck(), tmp_path)
    assert (substituted[0] / "deck.pptx").read_bytes() == b"foreign staged bytes"
    assert (substituted[0] / "user-file").read_bytes() == b"preserve"
    assert (moved / "deck.pptx").exists()  # original private staging is intentionally retained
    assert not list(tmp_path.glob("*.pptx"))


@pytest.mark.skipif(os.name == "nt", reason="POSIX injected rename/unlink boundary; Windows pins deny replacement")
def test_output_substituted_after_version_selection_never_receives_exports(tmp_path, monkeypatch):
    output = tmp_path / "output"
    output.mkdir()
    original = tmp_path / "original-output"
    real_next = exporter._next_version_path

    def substitute(*args):
        result = real_next(*args)
        output.rename(original)
        output.mkdir()
        (output / "user-file").write_bytes(b"preserve")
        return result

    monkeypatch.setattr(exporter, "_next_version_path", substitute)
    with pytest.raises((OSError, ValueError)):
        exporter.export_deck_data(_deck(), output)
    assert (output / "user-file").read_bytes() == b"preserve"
    assert not list(output.glob("*.pptx"))
    assert not list(output.glob("*.quality.json"))


@pytest.mark.skipif(os.name == "nt", reason="POSIX injected rename/unlink boundary; Windows pins deny replacement")
def test_lock_substituted_after_version_selection_never_publishes(tmp_path, monkeypatch):
    real_next = exporter._next_version_path

    def substitute(*args):
        result = real_next(*args)
        (tmp_path / LOCK).rename(tmp_path / "old-lock")
        (tmp_path / LOCK).touch()
        return result

    monkeypatch.setattr(exporter, "_next_version_path", substitute)
    with pytest.raises((OSError, ValueError)):
        exporter.export_deck_data(_deck(), tmp_path)
    assert not list(tmp_path.glob("*.pptx"))
    assert not list(tmp_path.glob("*.quality.json"))
