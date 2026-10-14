"""Short, cross-process publication locks shared by every export entry point."""

import errno
import os
import stat
import time
from contextlib import contextmanager
from pathlib import Path

from slidecaptain.export import history

from slidecaptain.file_locks import try_lock as _try_lock, unlock as _unlock


class ExportBusyError(TimeoutError):
    """Another exporter did not finish publishing before the wait limit."""


_LOCK_NAME = ".slidecaptain-export.lock"
_CHANGED = "출력 폴더나 게시 잠금 파일이 바뀌었습니다. 로컬 폴더를 확인한 뒤 다시 시도해 주세요."


def _regular(info) -> bool:
    return (stat.S_ISREG(info.st_mode)
            and not getattr(info, "st_file_attributes", 0) & 0x400)


def _lock_identity(info) -> tuple:
    # Lock contents and timestamps have no meaning in the publication protocol.
    return info.st_dev, info.st_ino, info.st_mode


def require_directory_identity(directory: Path, identity: tuple) -> None:
    try:
        current = history._directory_identity(directory)
    except history.HistoryReadError as exc:
        raise OSError(errno.EINVAL, _CHANGED) from exc
    if current != identity:
        raise OSError(errno.EINVAL, _CHANGED)


def require_publication_identity(reader, identity: tuple) -> None:
    require_directory_identity(reader.path, identity)
    current = reader.stat(_LOCK_NAME)
    if not _regular(current) or _lock_identity(current) != reader.publication_lock_signature:
        raise OSError(errno.EINVAL, _CHANGED)


@contextmanager
def pinned_export_directory(directory: Path, identity: tuple):
    # History translates read/pin errors, but must not reclassify a publisher's
    # lock timeout or write failure raised through its context manager.
    failure = None
    try:
        with history._pin_directory(directory, identity) as reader:
            try:
                yield reader
            except BaseException as exc:
                failure = exc
    except history.HistoryReadError as exc:
        raise OSError(errno.EINVAL, _CHANGED) from exc
    if failure is not None:
        raise failure


@contextmanager
def _safe_lock_handle(reader):
    fd = None
    try:
        before = reader.stat(_LOCK_NAME)
    except FileNotFoundError:
        flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(_LOCK_NAME, flags, 0o600, dir_fd=reader.fd) if reader.fd is not None else os.open(reader.path / _LOCK_NAME, flags, 0o600)
        except FileExistsError:
            before = reader.stat(_LOCK_NAME)
        else:
            before = os.fstat(fd)
    try:
        if not _regular(before):
            raise OSError(errno.EINVAL, _CHANGED)
        if fd is None:
            fd = reader.open(_LOCK_NAME, os.O_RDWR | getattr(os, "O_BINARY", 0)
                             | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
        elif reader.windows is not None:
            reader.windows.verify_fd(fd, _LOCK_NAME)
        signature = _lock_identity(before)
        opened = os.fstat(fd)
        if not _regular(opened) or _lock_identity(opened) != signature:
            raise OSError(errno.EINVAL, _CHANGED)
        current = reader.stat(_LOCK_NAME)
        if not _regular(current) or _lock_identity(current) != signature:
            raise OSError(errno.EINVAL, _CHANGED)
        # fdopen owns the descriptor from this point on.
        opened_fd, fd = fd, None
        with os.fdopen(opened_fd, "r+b") as handle:
            yield handle, signature
    finally:
        if fd is not None:
            os.close(fd)


@contextmanager
def _locked(handle, timeout: float):
    deadline = time.monotonic() + timeout
    while True:
        try:
            _try_lock(handle.fileno())
            break
        except OSError as exc:
            if exc.errno not in (errno.EACCES, errno.EAGAIN):
                raise
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ExportBusyError(
                    "같은 폴더에 다른 내보내기를 저장하고 있습니다. 잠시 후 다시 시도해 주세요."
                ) from exc
            time.sleep(min(0.05, remaining))
    try:
        yield
    finally:
        _unlock(handle.fileno())


@contextmanager
def export_directory_lock(out_dir: Path, *, timeout: float = 5.0, handle=None):
    """Use the same stable regular inode for default and caller-pinned publishers.

    Aliases resolve once before pinning. POSIX operations use a directory fd;
    Windows pins ancestor handles and verifies opened file destinations. Never
    remove the lock. Caller-provided handles remain owned by their caller.
    """
    if handle is not None:
        if not _regular(os.fstat(handle.fileno())):
            raise OSError(errno.EINVAL, _CHANGED)
        with _locked(handle, timeout):
            yield
        return
    try:
        directory = Path(out_dir).resolve(strict=True)
        identity = history._directory_identity(directory)
        if identity is None:
            raise OSError(errno.ENOENT, _CHANGED)
        with pinned_export_directory(directory, identity) as reader:
            with _safe_lock_handle(reader) as (opened, signature):
                with _locked(opened, timeout):
                    require_directory_identity(directory, identity)
                    reader.publication_lock_signature = signature
                    require_publication_identity(reader, identity)
                    yield reader
    except history.HistoryReadError as exc:
        raise OSError(errno.EINVAL, _CHANGED) from exc
