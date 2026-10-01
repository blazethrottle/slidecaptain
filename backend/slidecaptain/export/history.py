"""Read-only observations of direct export children. Never repair stored files."""

import hashlib
import json
import os
import re
import stat
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from slidecaptain.models.export_history import ExportHistoryDetail, ExportHistoryItem, ExportHistoryPage
from slidecaptain.models.quality import QualityReport

_ID = re.compile(r'[^\\/:*?"<>|\x00-\x1f]+_v[0-9]{3,}')
_SHA256 = re.compile(r"[0-9a-f]{64}")
_MAX_RECORD_BYTES = 8 * 1024 * 1024
_READ_CHUNK = 1024 * 1024


class HistoryReadError(ValueError):
    pass


class HistoryNotFound(ValueError):
    pass


class _Directory:
    def __init__(self, path: Path, fd: int | None = None, windows=None):
        self.path, self.fd, self.windows = path, fd, windows

    def stat(self, name: str):
        return os.stat(name, dir_fd=self.fd, follow_symlinks=False) if self.fd is not None else (self.path / name).lstat()

    def open(self, name: str, flags: int):
        fd = os.open(name, flags, dir_fd=self.fd) if self.fd is not None else os.open(self.path / name, flags)
        try:
            if self.windows is not None:
                self.windows.verify_fd(fd, name)
            return fd
        except BaseException:
            os.close(fd)
            raise

    def scan(self):
        return os.scandir(self.fd if self.fd is not None else self.path)


@contextmanager
def _pin_directory(directory: Path, identity: tuple):
    """Bind every read to the original directory, including temporary path swaps."""
    try:
        if os.name == "nt":
            from slidecaptain.export.windows_history import pinned_directory
            with pinned_directory(directory) as pinned:
                if _directory_identity(pinned.path) != identity:
                    raise OSError("Directory replaced")
                yield _Directory(pinned.path, windows=pinned)
        else:
            fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                opened = os.fstat(fd)
                if (opened.st_dev, opened.st_ino) != identity:
                    raise OSError("Directory replaced")
                yield _Directory(directory, fd)
            finally:
                os.close(fd)
    except OSError as exc:
        raise HistoryReadError("출력 폴더를 안전하게 읽지 못했습니다. 로컬 폴더와 접근 권한을 확인해 주세요.") from exc


def validate_export_id(export_id: str) -> None:
    if not _ID.fullmatch(export_id):
        raise HistoryReadError("내보내기 파일 이름이 올바르지 않습니다.")


def _signature(info: os.stat_result) -> tuple:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _directory_identity(directory: Path) -> tuple | None:
    try:
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
            raise OSError("Not a direct directory")
        return (info.st_dev, info.st_ino)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise HistoryReadError("출력 폴더를 읽지 못했습니다. 로컬 폴더와 접근 권한을 확인해 주세요.") from exc


def _read_regular(path: Path, *, reader: _Directory, digest: bool = False) -> tuple[bytes | str, tuple]:
    """Reject special files and detect replacement/change during the read."""
    before = reader.stat(path.name)
    if not stat.S_ISREG(before.st_mode):
        raise OSError("Not a regular file")
    if not digest and before.st_size > _MAX_RECORD_BYTES:
        raise OSError("Record too large")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    fd = reader.open(path.name, flags)
    with os.fdopen(fd, "rb") as stream:
        opened = os.fstat(stream.fileno())
        if _signature(opened) != _signature(before) or not stat.S_ISREG(opened.st_mode):
            raise OSError("File replaced")
        if digest:
            sha = hashlib.sha256()
            while chunk := stream.read(_READ_CHUNK):
                sha.update(chunk)
            value = sha.hexdigest()
        else:
            value = stream.read(_MAX_RECORD_BYTES + 1)
            if len(value) > _MAX_RECORD_BYTES:
                raise OSError("Record too large")
        if _signature(os.fstat(stream.fileno())) != _signature(before):
            raise OSError("File changed")
    if _signature(reader.stat(path.name)) != _signature(before):
        raise OSError("File replaced")
    return value, _signature(before)


def _object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError("Duplicate key")
        obj[key] = value
    return obj


def _record(raw: bytes) -> tuple[str, QualityReport | None]:
    try:
        data = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_object)
        if not isinstance(data, dict) or not isinstance(data.get("gate_version"), str):
            return "invalid", None
        if data["gate_version"] not in ("preflight-v1", "preflight-v2"):
            return "unsupported", None
        if not isinstance(data.get("input_fingerprint"), str) or not _SHA256.fullmatch(data["input_fingerprint"]):
            return "invalid", None
        artifact_hash = data.get("artifact_sha256")
        if artifact_hash is not None and (not isinstance(artifact_hash, str) or not _SHA256.fullmatch(artifact_hash)):
            return "invalid", None
        return "readable", QualityReport.model_validate(data, strict=True)
    except (ValueError, UnicodeError, ValidationError, RecursionError):
        return "invalid", None


def _still_same(path: Path, signature: tuple | None, reader: _Directory) -> bool:
    try:
        return signature is not None and _signature(reader.stat(path.name)) == signature
    except OSError:
        return False


def _inspect(directory: Path, export_id: str, current_fingerprint: str | None, *, reader: _Directory):
    record_path = directory / f"{export_id}.quality.json"
    artifact_path = directory / f"{export_id}.pptx"
    quality = None
    record_signature = artifact_signature = None
    artifact_hash = None
    try:
        raw, record_signature = _read_regular(record_path, reader=reader)
        record_status, quality = _record(raw)
    except FileNotFoundError:
        record_status = "missing"
    except OSError:
        record_status = "unreadable"
    try:
        artifact_hash, artifact_signature = _read_regular(artifact_path, reader=reader, digest=True)
        artifact_status = "unverified"
    except FileNotFoundError:
        artifact_status = "missing"
    except OSError:
        artifact_status = "unreadable"

    # Recheck both paths after reading the pair; a replaced sidecar cannot bind a new artifact.
    if record_signature is not None and not _still_same(record_path, record_signature, reader):
        record_status, quality = "unreadable", None
    if artifact_signature is not None and not _still_same(artifact_path, artifact_signature, reader):
        artifact_status, artifact_hash = "unreadable", None
    if quality and quality.artifact_sha256 and artifact_hash:
        artifact_status = "matched" if quality.artifact_sha256 == artifact_hash else "mismatch"
    input_status = "unavailable"
    if quality:
        if quality.gate_version == "preflight-v1":
            input_status = "legacy"
        elif current_fingerprint is not None:
            input_status = "current" if quality.input_fingerprint == current_fingerprint else "stale"
    modified = []
    for path in (record_path, artifact_path):
        try:
            modified.append(reader.stat(path.name).st_mtime)
        except OSError:
            pass
    item = ExportHistoryItem(
        id=export_id,
        file_modified_at=datetime.fromtimestamp(max(modified), timezone.utc).isoformat() if modified else None,
        record_status=record_status, artifact_status=artifact_status, input_status=input_status,
        quality_status=quality.status if quality else None, slide_count=quality.slide_count if quality else None,
        gate_version=quality.gate_version if quality else None,
    )
    return item, quality, artifact_hash


def _scan(reader: _Directory) -> list[str]:
    modified: dict[str, int] = {}
    try:
        with reader.scan() as entries:
            for entry in entries:
                suffix = next((s for s in (".quality.json", ".pptx") if entry.name.endswith(s)), None)
                if suffix is None:
                    continue
                export_id = entry.name[:-len(suffix)]
                if not _ID.fullmatch(export_id):
                    continue
                if reader.windows is not None:
                    try:
                        reader.windows.verify_entry(entry.name)
                    except FileNotFoundError:
                        continue  # An entry disappeared after enumeration.
                try:
                    stamp = entry.stat(follow_symlinks=False).st_mtime_ns
                except OSError:
                    stamp = 0
                modified[export_id] = max(stamp, modified.get(export_id, 0))
    except OSError as exc:
        raise HistoryReadError("출력 폴더를 읽지 못했습니다. 접근 권한을 확인한 뒤 다시 조회해 주세요.") from exc
    return sorted(modified, key=lambda key: (modified[key], key), reverse=True)


def read_export_history(
    directory: Path, *, current_fingerprint: str | None, current_error: str | None,
    export_id: str | None = None, offset: int = 0, limit: int = 20,
) -> ExportHistoryPage | ExportHistoryDetail:
    if export_id is not None:
        validate_export_id(export_id)
    identity = _directory_identity(directory)
    ids, results = [], []
    if identity is not None:
        with _pin_directory(directory, identity) as reader:
            ids = _scan(reader)
            if export_id is not None and export_id not in ids:
                raise HistoryNotFound("내보내기 이력을 찾지 못했습니다. 목록을 새로고침해 주세요.")
            selected = [export_id] if export_id is not None else ids[offset:offset + limit]
            results = [_inspect(directory, name, current_fingerprint, reader=reader) for name in selected]
    elif export_id is not None:
        raise HistoryNotFound("내보내기 이력을 찾지 못했습니다. 목록을 새로고침해 주세요.")
    if _directory_identity(directory) != identity:
        raise HistoryReadError("조회 중 출력 폴더가 바뀌었습니다. 다시 조회해 주세요.")
    context = dict(
        checked_at=datetime.now(timezone.utc).isoformat(), current_input_fingerprint=current_fingerprint,
        current_input_error=current_error,
    )
    if export_id is not None:
        item, quality, artifact_hash = results[0]
        return ExportHistoryDetail(**context, item=item, quality=quality, artifact_sha256=artifact_hash)
    return ExportHistoryPage(**context, items=[r[0] for r in results], total=len(ids), offset=offset, limit=limit)
