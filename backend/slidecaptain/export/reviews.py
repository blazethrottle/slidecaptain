"""Append immutable manual review files under the export publication lock.

The application holds its project lock before entering this module. Sequence,
not a wall clock, orders records. File reads/writes bind to the same directory
handle used for history so path swaps cannot redirect publication elsewhere.
"""

import hashlib
import json
import os
import re
import stat
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from slidecaptain.export import exporter, history
from slidecaptain.export.locking import ExportBusyError, export_directory_lock
from slidecaptain.models.export_reviews import (
    CATEGORIES, ExportReviewCategoryState, ExportReviewRecord, ExportReviewRequest, ExportReviews,
)


class ReviewConflict(ValueError):
    pass


class ReviewDeckConflict(ReviewConflict):
    pass


class ReviewPagesError(ValueError):
    pass


class ReviewReadLimit(OSError):
    pass


@dataclass(frozen=True)
class ReviewInputs:
    base_etag: str | None
    fingerprint: str | None
    error: str | None


_LOCK_NAME = ".slidecaptain-export.lock"
_SEQUENCE = re.compile(r"[0-9]{8}")
_MAX_RECORDS = 1000
_MAX_RECORD_BYTES = 128 * 1024
_MAX_TOTAL_BYTES = 8 * 1024 * 1024
_CHANGED = "검수 기준이 바뀌었거나 파일을 안전하게 확인하지 못했습니다. 입력을 보존한 뒤 다시 조회해 주세요."
_UNAVAILABLE = "게시 기록, 출력 파일 또는 현재 입력을 확인하지 못했습니다. 과거 검수 기록은 보존하지만 새 기록은 저장할 수 없습니다."
_STALE = "내보낸 뒤 입력이나 출력 파일이 바뀌었습니다. 현재 입력으로 다시 내보내거나 원래 파일을 복원한 뒤 확인해 주세요."
_BROKEN = "검수 저장소에 손상되었거나 읽지 못한 기록이 있습니다. 이전 통과 판정으로 대신하지 않으며 새 기록은 저장하지 않습니다."
_LIMIT = "검수 기록의 조회 한도(1,000개, 파일당 128KB, 합계 8MB)를 초과했습니다. 일부 기록으로 판정하지 않으며 새 기록은 저장하지 않습니다."


def _review_names(reader, export_id: str) -> list[str]:
    prefix = f"{export_id}.review."
    names = []
    with reader.scan() as entries:
        for entry in entries:
            if entry.name.startswith(prefix) and entry.name.endswith(".json"):
                names.append(entry.name)
                if len(names) > _MAX_RECORDS:
                    raise ReviewReadLimit(_LIMIT)
    return sorted(names)


def _read_records(directory: Path, export_id: str, reader):
    records, signatures = [], {}
    try:
        names = _review_names(reader, export_id)
    except ReviewReadLimit:
        return [], "unreadable", {}, [], _LIMIT
    except OSError:
        return [], "unreadable", {}, [], _BROKEN
    status = "readable" if names else "empty"
    sequences = []
    total_bytes = 0
    for name in names:
        number = name[len(f"{export_id}.review."):-len(".json")]
        if not _SEQUENCE.fullmatch(number) or int(number) < 1:
            if status != "unreadable":
                status = "invalid"
            continue
        sequences.append(int(number))
        try:
            size = reader.stat(name).st_size
            total_bytes += size
            if size > _MAX_RECORD_BYTES or total_bytes > _MAX_TOTAL_BYTES:
                return [], "unreadable", {}, names, _LIMIT
            raw, signatures[name] = history._read_regular(directory / name, reader=reader)
            if len(raw) > _MAX_RECORD_BYTES:
                return [], "unreadable", {}, names, _LIMIT
            data = json.loads(raw.decode("utf-8"), object_pairs_hook=history._object)
            record = ExportReviewRecord.model_validate(data, strict=True)
            if record.export_id != export_id or record.sequence != int(number):
                raise ValueError("Record identity mismatch")
            # Timestamps display server time; only the locked sequence defines order.
            if datetime.fromisoformat(record.reviewed_at).tzinfo is None:
                raise ValueError("Review timestamp has no timezone")
            records.append(record)
        except OSError:
            status = "unreadable"
        except (ValueError, UnicodeError, RecursionError):
            if status != "unreadable":
                status = "invalid"
    # A missing earlier record is observable damage. Whole-tail deletion cannot
    # be authenticated by this local, unsigned store and is outside this contract.
    if sequences != list(range(1, len(sequences) + 1)) and status != "unreadable":
        status = "invalid"
    if len({record.id for record in records}) != len(records) and status != "unreadable":
        status = "invalid"
    return sorted(records, key=lambda record: record.sequence, reverse=True), status, signatures, names, None


def _snapshot(directory: Path, export_id: str, inputs: ReviewInputs, reader) -> ExportReviews:
    records, storage_status, signatures, names, storage_error = _read_records(directory, export_id, reader)
    item, quality, artifact_hash = history._inspect(directory, export_id, inputs.fingerprint, reader=reader)
    if not names and storage_status == "empty" and item.record_status == "missing" and item.artifact_status == "missing":
        raise history.HistoryNotFound("내보내기 이력을 찾지 못했습니다. 목록을 새로고침해 주세요.")
    try:
        if (_review_names(reader, export_id) != names or any(
            not history._still_same(directory / name, signature, reader)
            for name, signature in signatures.items()
        )):
            storage_status = "unreadable"
    except ReviewReadLimit:
        storage_status, storage_error = "unreadable", _LIMIT
    except OSError:
        storage_status = "unreadable"

    if (quality is None or item.record_status != "readable" or quality.gate_version != "preflight-v2"
            or item.input_status in ("legacy", "unavailable")
            or item.artifact_status not in ("matched", "mismatch") or quality.slide_count <= 0):
        status, reason = "unavailable", inputs.error or _UNAVAILABLE
    elif item.input_status == "stale" or item.artifact_status == "mismatch":
        status, reason = "stale", _STALE
    else:
        status, reason = "current", None
    if storage_status in ("invalid", "unreadable"):
        status, reason = "unavailable", storage_error or _BROKEN
    can_record = status == "current" and len(records) < _MAX_RECORDS
    if status == "current" and not can_record:
        reason = _LIMIT

    categories = []
    for category in CATEGORIES:
        latest = next((record for record in records if record.category == category), None)
        if storage_status in ("invalid", "unreadable"):
            verdict = "unavailable"
        elif latest is None:
            verdict = "not_run"
        elif status != "current":
            verdict = status
        elif latest.input_fingerprint != quality.input_fingerprint or latest.artifact_sha256 != artifact_hash:
            verdict = "stale"
        else:
            verdict = latest.status
        categories.append(ExportReviewCategoryState(
            category=category, status=verdict, latest_record_id=latest.id if latest else None,
        ))
    return ExportReviews(
        export_id=export_id, checked_at=datetime.now(timezone.utc).isoformat(),
        base_etag=inputs.base_etag, input_fingerprint=quality.input_fingerprint if quality else None,
        artifact_sha256=artifact_hash, current_input_fingerprint=inputs.fingerprint,
        slide_count=quality.slide_count if quality else None, status=status, storage_status=storage_status,
        can_record=can_record, reason=reason, categories=categories, records=records,
        final_export_allowed=False,
    )


@contextmanager
def _pin_review_directory(directory: Path, identity: tuple):
    # Pin the project first, then open exports relative to that project. Pinning
    # only the last component could follow a concurrently substituted project
    # symlink before the final exports descriptor is opened.
    parent_identity = history._directory_identity(directory.parent)
    if parent_identity is None:
        raise history.HistoryReadError(_CHANGED)
    with history._pin_directory(directory.parent, parent_identity) as parent:
        if parent.fd is None:
            with history._pin_directory(directory, identity) as reader:
                yield reader
        else:
            fd = os.open(directory.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent.fd)
            try:
                info = os.fstat(fd)
                if (info.st_dev, info.st_ino) != identity:
                    raise history.HistoryReadError(_CHANGED)
                yield history._Directory(directory, fd)
            finally:
                os.close(fd)


def read_export_reviews(directory: Path, export_id: str, inputs: ReviewInputs) -> ExportReviews:
    history.validate_export_id(export_id)
    identity = history._directory_identity(directory)
    if identity is None:
        raise history.HistoryNotFound("내보내기 이력을 찾지 못했습니다. 목록을 새로고침해 주세요.")
    with _pin_review_directory(directory, identity) as reader:
        result = _snapshot(directory, export_id, inputs, reader)
    if history._directory_identity(directory) != identity:
        raise history.HistoryReadError(_CHANGED)
    return result


def _create_regular(reader, name: str) -> int:
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    if reader.fd is not None:
        fd = os.open(name, flags, 0o600, dir_fd=reader.fd)
    else:
        fd = os.open(reader.path / name, flags, 0o600)
    try:
        if reader.windows is not None:
            reader.windows.verify_fd(fd, name)
        return fd
    except BaseException:
        os.close(fd)
        raise


@contextmanager
def _review_lock(directory: Path, reader):
    fd = None
    try:
        before = reader.stat(_LOCK_NAME)
    except FileNotFoundError:
        try:
            fd = _create_regular(reader, _LOCK_NAME)
        except FileExistsError:
            # Another publisher created the same stable lock inode. Open without
            # O_CREAT so a substituted symlink cannot create an external file.
            before = reader.stat(_LOCK_NAME)
        else:
            try:
                before = reader.stat(_LOCK_NAME)
            except BaseException:
                os.close(fd)
                raise
    if fd is None:
        if not stat.S_ISREG(before.st_mode):
            raise ReviewConflict(_CHANGED)
        fd = reader.open(_LOCK_NAME, os.O_RDWR | getattr(os, "O_BINARY", 0)
                         | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    with os.fdopen(fd, "r+b") as handle:
        signature = history._signature(before)
        opened = os.fstat(handle.fileno())
        windows = os.name == "nt"
        if (not stat.S_ISREG(opened.st_mode)
                or history._path_fd_signature(opened, windows=windows)
                    != history._path_fd_signature(before, windows=windows)
                or not history._still_same(directory / _LOCK_NAME, signature, reader)):
            raise ReviewConflict(_CHANGED)
        with export_directory_lock(directory, handle=handle):
            if (history._signature(os.fstat(handle.fileno())) != history._signature(opened)
                    or not history._still_same(directory / _LOCK_NAME, signature, reader)):
                raise ReviewConflict(_CHANGED)
            yield signature


def _require_basis(snapshot: ExportReviews, request: ExportReviewRequest, if_match: str) -> None:
    if snapshot.base_etag is None:
        raise ReviewConflict(_CHANGED)
    if if_match.strip('"') != snapshot.base_etag.strip('"'):
        raise ReviewDeckConflict("검수를 시작한 뒤 덱이 바뀌었습니다. 입력을 보존한 뒤 다시 조회해 주세요.")
    if (not snapshot.can_record or snapshot.input_fingerprint != request.expected_input_fingerprint
            or snapshot.artifact_sha256 != request.expected_artifact_sha256):
        raise ReviewConflict(snapshot.reason or _CHANGED)
    count = snapshot.slide_count
    if any(page > count for page in request.pages):
        raise ReviewPagesError("확인한 페이지 번호가 출력 파일의 페이지 범위를 벗어났습니다.")
    if request.status == "passed" and (len(request.pages) != count or sorted(request.pages) != list(range(1, len(request.pages) + 1))):
        raise ReviewPagesError("통과 기록에는 출력 파일의 모든 페이지를 확인했다고 입력해야 합니다.")


def _publish_record(directory: Path, record: ExportReviewRecord, reader, verify: Callable[[], None]) -> None:
    temp_name = f".slidecaptain-review-{uuid.uuid4().hex}.tmp"
    final_name = f"{record.export_id}.review.{record.sequence:08d}.json"
    data = (record.model_dump_json(indent=2) + "\n").encode("utf-8")
    existing_bytes = sum(reader.stat(name).st_size for name in _review_names(reader, record.export_id))
    if len(data) > _MAX_RECORD_BYTES or existing_bytes + len(data) > _MAX_TOTAL_BYTES:
        raise ReviewConflict(_LIMIT)
    signature = None
    fd = _create_regular(reader, temp_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            signature = history._signature(os.fstat(stream.fileno()))
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
            written_info = os.fstat(stream.fileno())
            signature = history._signature(written_info)
        _, signature = exporter._seal_staged(directory / temp_name, written_info,
                                              hashlib.sha256(data).hexdigest(), reader)
        verify()
        if not history._still_same(directory / temp_name, signature, reader):
            raise ReviewConflict(_CHANGED)
        # Hard-link publication never replaces an existing record or follows its
        # destination. Both paths stay relative to the pinned directory on POSIX.
        if reader.fd is not None:
            os.link(temp_name, final_name, src_dir_fd=reader.fd, dst_dir_fd=reader.fd, follow_symlinks=False)
        else:
            os.link(reader.path / temp_name, reader.path / final_name, follow_symlinks=False)
    finally:
        # The link changes ctime, so compare inode identity when cleaning only our
        # staging name. A foreign file that replaced it is never removed.
        try:
            current = reader.stat(temp_name)
            if signature is not None and (current.st_dev, current.st_ino) == signature[:2]:
                if reader.fd is not None:
                    os.unlink(temp_name, dir_fd=reader.fd)
                else:
                    (reader.path / temp_name).unlink()
        except OSError:
            pass


@contextmanager
def _write_errors():
    # The history pin translates OSError into a read error. Classify write/lock
    # failures here, before unwinding that pin, so API conflicts remain 409.
    try:
        yield
    except ExportBusyError as exc:
        raise ReviewConflict(str(exc)) from exc
    except OSError as exc:
        raise ReviewConflict(_CHANGED) from exc


def append_export_review(
    directory: Path, export_id: str, request: ExportReviewRequest, if_match: str,
    get_inputs: Callable[[], ReviewInputs],
) -> ExportReviews:
    history.validate_export_id(export_id)
    identity = history._directory_identity(directory)
    if identity is None:
        raise history.HistoryNotFound("내보내기 이력을 찾지 못했습니다. 목록을 새로고침해 주세요.")
    with _pin_review_directory(directory, identity) as reader, _write_errors():
        with _review_lock(directory, reader) as lock_signature:
            snapshot = _snapshot(directory, export_id, get_inputs(), reader)
            _require_basis(snapshot, request, if_match)
            sequence = max((record.sequence for record in snapshot.records), default=0) + 1
            if sequence > _MAX_RECORDS:
                raise ReviewConflict(_LIMIT)
            record = ExportReviewRecord(
                **request.model_dump(exclude={"expected_input_fingerprint", "expected_artifact_sha256"}),
                id=uuid.uuid4().hex, sequence=sequence, rule_version="manual-review-v1",
                export_id=export_id, input_fingerprint=request.expected_input_fingerprint,
                artifact_sha256=request.expected_artifact_sha256, reviewed_at=datetime.now(timezone.utc).isoformat(),
            )

            def verify():
                if (history._directory_identity(directory) != identity
                        or not history._still_same(directory / _LOCK_NAME, lock_signature, reader)):
                    raise ReviewConflict(_CHANGED)
                current = _snapshot(directory, export_id, get_inputs(), reader)
                _require_basis(current, request, if_match)
                if current.records != snapshot.records:
                    raise ReviewConflict(_CHANGED)

            _publish_record(directory, record, reader, verify)
            result = _snapshot(directory, export_id, get_inputs(), reader)
    if history._directory_identity(directory) != identity:
        raise ReviewConflict(_CHANGED)
    return result
