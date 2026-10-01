"""Windows close/stat differences must not disable file-change detection."""

import hashlib
from types import SimpleNamespace

import pytest

from slidecaptain.export import exporter, history


def info(stat, **changes):
    values = {name: getattr(stat, name) for name in dir(stat) if name.startswith('st_')}
    values.setdefault('st_birthtime_ns', 100)
    values.update(changes)
    return SimpleNamespace(**values)


def reader_for(path):
    class Reader(history._Directory):
        def stat(self, name):
            return info(super().stat(name))
    return Reader(path)


def test_cross_kind_windows_time_normalization_preserves_raw_change_time(tmp_path):
    path = tmp_path / 'file'
    path.write_bytes(b'data')
    original = info(path.stat(), st_ctime_ns=100)
    opened = info(path.stat(), st_ctime_ns=200)
    assert history._path_fd_signature(original, windows=True) == history._path_fd_signature(opened, windows=True)
    assert history._signature(original) != history._signature(opened)
    assert history._path_fd_signature(original, windows=False) != history._path_fd_signature(opened, windows=False)


def test_windows_close_can_finalize_write_time_with_identical_identity_and_bytes(tmp_path):
    path = tmp_path / 'file'
    path.write_bytes(b'data')
    written = info(path.stat(), st_mtime_ns=1, st_ctime_ns=200)
    digest = hashlib.sha256(b'data').hexdigest()
    actual, signature = exporter._seal_staged(path, written, digest, reader_for(tmp_path), windows=True)
    assert actual == digest and signature == history._signature(path.stat())


@pytest.mark.parametrize('damage', ['different_inode', 'same_inode_bytes'])
def test_windows_close_bridge_rejects_replacement_or_same_size_rewrite(tmp_path, damage):
    path = tmp_path / 'file'
    path.write_bytes(b'data')
    written = info(path.stat(), st_mtime_ns=1, st_ctime_ns=200)
    if damage == 'different_inode':
        replacement = tmp_path / 'replacement'
        replacement.write_bytes(b'data')
        replacement.replace(path)
    else:
        path.write_bytes(b'evil')
    with pytest.raises(OSError, match='Staged export'):
        exporter._seal_staged(path, written, hashlib.sha256(b'data').hexdigest(), reader_for(tmp_path), windows=True)


def test_same_handle_change_time_is_checked_even_when_size_and_mtime_match(tmp_path, monkeypatch):
    path = tmp_path / 'file'
    path.write_bytes(b'data')
    real_fstat = history.os.fstat
    calls = 0
    def changed(fd):
        nonlocal calls
        actual = real_fstat(fd)
        calls += 1
        return info(actual, st_ctime_ns=actual.st_ctime_ns + (1 if calls > 1 else 0))
    monkeypatch.setattr(history.os, 'fstat', changed)
    with pytest.raises(OSError, match='File changed'):
        history._read_regular(path, reader=reader_for(tmp_path), digest=True)


def test_same_bytes_replacement_between_seal_stat_and_verified_read_is_rejected(tmp_path):
    path = tmp_path / 'file'
    path.write_bytes(b'data')
    written = info(path.stat(), st_mtime_ns=1, st_ctime_ns=200)
    replacement = tmp_path / 'replacement'
    replacement.write_bytes(b'data')
    reader = reader_for(tmp_path)
    original_stat = reader.stat
    calls = 0
    def swapped(name):
        nonlocal calls
        calls += 1
        if calls == 2:
            replacement.replace(path)
        return original_stat(name)
    reader.stat = swapped
    with pytest.raises(OSError, match='Staged export file changed'):
        exporter._seal_staged(path, written, hashlib.sha256(b'data').hexdigest(), reader, windows=True)
