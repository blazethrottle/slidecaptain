"""프로젝트 폴더 저장소 (설계서 3.1, 7.2).

projects/<프로젝트명>/
  deck.json      # 진본
  sources/       # 입력 자료 원문 (수치 대조의 기준)
  snapshots/     # 저장 시점 스냅샷
  exports/       # 내보낸 PPTX
  manifest.json  # 형식 기록 (D2a-1, storage/project_format.py). 판정은 덱 내용으로 한다

- 저장은 원자적: 같은 폴더의 임시 파일에 쓴 뒤 os.replace로 교체
- 저장마다 직전 deck.json을 스냅샷으로 보존 (복구 경로)
"""

import hashlib
import json
import logging
import os
import re
import tempfile
import threading
import unicodedata
from contextlib import AbstractContextManager, contextmanager
from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, ValidationError

from slidecaptain.models.deck import Deck, DeckMeta
from slidecaptain.models.diagram import _evidence_input
from slidecaptain.models.preset import Preset
from slidecaptain.storage import project_format

_NAME_RE = re.compile(r"^[0-9A-Za-z가-힣][0-9A-Za-z가-힣 ._\-]{0,79}$")
_WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)}
_SNAPSHOT_RE = re.compile(r"^deck-(\d{8}-\d{6}-\d{6})(?:-\d+)?$")
_DRAFT_RE = re.compile(r"^draft-(\d{8}-\d{6}-\d{6})(?:-\d+)?$")
# 보존본 한 건의 덱 크기 상한. 독립 앱 브리지의 요청 본문 상한(desktop/runtime.cjs MAX_FILE)과 같다
DRAFT_MAX_BYTES = 20 * 1024 * 1024
# save_deck과 restore_snapshot이 같은 문구를 축자 중복으로 썼다 (A1 리뷰 minor, A2에서 상수로 묶는다)
_DECK_CONFLICT_MESSAGE = (
    "다른 창이나 프로그램에서 이 프로젝트가 먼저 저장되었습니다. "
    "서버 내용을 다시 읽은 뒤 이어서 편집해 주세요. 편집 단계의 저장하지 않은 변경은 다시 읽을 때 보존합니다."
)


class StorageError(Exception):
    """사용자에게 쉬운 말로 보여줄 저장소 오류."""


class InvalidName(StorageError):
    pass


class ProjectNotFound(StorageError):
    pass


class ProjectExists(StorageError):
    pass


class DeckConflict(StorageError):
    """expected_etag가 저장소의 현재 내용과 어긋날 때 (A2가 412로 매핑한다)."""


class SnapshotNotFound(StorageError):
    pass


class DraftNotFound(StorageError):
    pass


class DraftTooLarge(StorageError):
    """보존본이 상한(DRAFT_MAX_BYTES)을 넘는다 (D2a-2. A가 413으로 매핑한다)."""


class DeckUnreadable(StorageError):
    """deck.json을 덱으로 읽지 못했다(복구 필요). 이름 검증 같은 다른 저장소 오류와 구별한다 (D2a 최종 리뷰 F1)."""


class ProjectFormatTooNew(StorageError):
    """이 앱이 읽을 수 있는 것보다 새 형식의 프로젝트 (D2a-1). 모르는 필드를 버린 채 열거나
    내보내지 않도록 모든 접근을 거절한다. 파일은 바꾸지 않는다."""

    code = "project_format_too_new"


class ProjectManifestUnreadable(ProjectFormatTooNew):
    """형식 기록(manifest.json)을 이 앱이 해석할 수 없다 (D2a-1 리뷰 R2, R4). 덮어쓰면 이후 앱의
    기록이 사라지므로 더 새 형식과 같이 열지 않는다."""

    code = "project_manifest_unreadable"


class SourceNotFound(StorageError):
    pass


class SourceConflict(StorageError):
    """대소문자만 다른 자료 이름이 이미 있을 때 (A4가 409로 매핑한다). 정확히 같은 이름은
    이 예외 없이 덮어쓴다 (자료 저장 버튼의 의미)."""


class InvalidSourceEncoding(StorageError):
    pass


class ProjectInfo(BaseModel):
    name: str
    title: str
    updated_at: str  # ISO 8601
    status: Literal["ok", "needs_recovery", "newer_format", "unreadable_manifest"] = "ok"


class SnapshotInfo(BaseModel):
    id: str  # 파일 이름에서 확장자를 뺀 것 (예: deck-20260828-153000-123456)
    saved_at: str
    # pre_migration: 형식 1 덱을 형식 2로 처음 바꾸기 직전의 복사본 (0.2.0으로 되돌릴 지점)
    kind: Literal["snapshot", "pre_migration"] = "snapshot"


class DraftInfo(BaseModel):
    """충돌이나 저장 실패로 저장본에 반영하지 못한 덱의 보존본 (D2a-2)."""

    id: str  # draft-<시각>[-n]
    saved_at: str
    # 저장 요청은 아래 값만 받는다(SaveDraftRequest). 목록은 이후 버전이 늘린 값도 그대로 보인다
    # (리뷰 R5: 모르는 값 때문에 보존본이 목록에서 사라지거나 다음 보존이 실패하지 않게)
    reason: str  # conflict | generation_unsaved
    source: str  # editor | structure_approval
    base_etag: str | None = None  # 이 편집이 기준으로 삼은 저장본. 서버 쪽 변경과 비교할 때 쓴다


_NEWER_FORMAT_MESSAGE = (
    "이 프로젝트는 더 새 버전의 SlideCaptain이 만들었습니다. 이 버전에서는 열 수 없습니다. "
    "프로젝트 파일은 바꾸지 않았습니다. 새 버전의 앱으로 열어 주세요."
)
_UNREADABLE_MANIFEST_MESSAGE = (
    "이 프로젝트의 형식 기록 파일(manifest.json)을 읽지 못했습니다. 기록을 지우지 않도록 프로젝트를 "
    "열지 않았습니다. 새 버전의 앱으로 열거나, 파일을 다른 곳에 보관한 뒤 지우면 다시 열 수 있습니다."
)
_LOG = logging.getLogger("slidecaptain.storage.file_store")


def _nfc(value: str) -> str:
    """Finder가 만드는 NFD(자모 분리) 이름을 이 앱이 다루는 NFC(완성형)로 맞춘다 (A4, 가정: macOS APFS는
    NFD로 만든 폴더를 NFC 이름으로 열어도 같은 폴더로 해석한다). 이름을 받는 모든 공개 메서드 진입에서 쓴다."""
    return unicodedata.normalize("NFC", value)


def _casefold_conflict(dir_path: Path, filename: str) -> str | None:
    """filename과 정확히 같지 않지만 대소문자만 다른 기존 파일이 있으면 그 실제 이름을 돌려준다.
    판정은 casefold()로 하므로 파일 시스템의 대소문자 구분 여부와 무관하게 같은 규칙이 적용된다."""
    target = _nfc(filename).casefold()
    for p in dir_path.iterdir():
        if not p.is_file() or p.name.startswith("."):
            continue
        existing = _nfc(p.name)  # 탐색기가 NFD 로 만든 이름도 같은 규칙으로 비교한다 (리뷰 A4-F1)
        if existing == _nfc(filename):
            continue
        if existing.casefold() == target:
            return p.name
    return None


def _validate_name(name: str, kind: str) -> None:
    stem = name.split(".")[0].upper()
    if (
        not _NAME_RE.match(name)
        or name != name.strip()
        or ".." in name
        or name.endswith(".")  # Windows가 끝 마침표를 조용히 지워 폴더 이름이 어긋난다
        or stem in _WINDOWS_RESERVED
    ):
        raise InvalidName(
            f"{kind} 이름으로 쓸 수 없습니다: {name!r}. "
            "한글, 영문, 숫자로 시작하고 공백, 점, 밑줄, 붙임표만 섞어 80자 이내로 지어 주세요 "
            "(마침표로 끝나는 이름은 안 됩니다)."
        )


def validate_name(name: str, kind: str) -> None:
    """이름 규칙 검증의 공개 진입점. 라우트가 무거운 처리(XLSX 추출 등)를 시작하기 전에 미리
    검사할 때 쓴다 (계획서 B2 리뷰 F3). 규칙 자체는 _validate_name과 같다."""
    _validate_name(name, kind)


def decode_source_bytes(data: bytes, filename: str) -> str:
    """자료 바이트를 텍스트로 해석한다. utf-8-sig가 BOM 유무 양쪽을 흡수하고, cp949는 한국어
    Windows 메모장의 ANSI 저장을 위한 폴백이다 (단계 3 결정 7). 파일 읽기와 업로드가 같은 규칙을 쓴다."""
    for encoding in ("utf-8-sig", "cp949"):
        try:
            text = data.decode(encoding)
        except UnicodeDecodeError:
            continue
        # read_text()가 하던 universal newline 변환을 그대로 유지한다 (CRLF와 CR을 LF로).
        # 2026-09-01 리뷰 반영: 바이트 디코딩으로 바꾸면서 빠졌던 부분. 없으면 CRLF 자료에 \r이 남아
        # 글자 수 집계와 AI 프롬프트 원문에 섞인다
        return text.replace("\r\n", "\n").replace("\r", "\n")
    raise InvalidSourceEncoding(
        f"자료 파일 {filename}을 텍스트로 읽지 못했습니다. "
        "PDF나 이미지 같은 텍스트 아닌 파일은 자료로 쓸 수 없습니다. "
        "텍스트 파일이라면 UTF-8 인코딩으로 다시 저장해 주세요."
    )


def _validate_read_name(name: str) -> None:
    """읽기용 최소 검증: 탐색기로 넣은 파일(괄호 등 생성 문법 밖 이름)도 읽히도록, 폴더 탈출 방지만 확인한다."""
    stem = name.split(".")[0].upper()
    if (
        not name
        or "/" in name
        or "\\" in name
        or ":" in name
        or ".." in name
        or name.endswith(".")
        or stem in _WINDOWS_RESERVED
    ):
        raise InvalidName(
            f"자료 파일 이름으로 쓸 수 없습니다: {name!r}. 폴더 경로 없이 파일 이름만 적어 주세요."
        )


def load_source_directory(directory: Path) -> dict[str, str]:
    """Read CLI source inputs with the same names and encoding as project sources."""
    if not directory.exists():
        return {}
    return {
        _nfc(path.name): decode_source_bytes(path.read_bytes(), path.name)
        for path in sorted(directory.iterdir())
        if path.is_file() and not path.name.startswith(".")
    }


class ProjectStore(Protocol):
    """저장소 인터페이스 (설계서 2.2). 파일 구현 외의 구현(DB 등)으로 교체 가능하게 한다."""

    def list_projects(self) -> list[ProjectInfo]: ...
    def create_project(self, name: str, title: str = "") -> ProjectInfo: ...
    def locked(self, name: str) -> AbstractContextManager[None]: ...
    def load_deck(self, name: str) -> Deck: ...
    def deck_etag(self, name: str) -> str: ...
    def load_deck_with_etag(self, name: str) -> tuple[Deck, str]: ...
    def save_deck(
        self, name: str, deck: Deck, snapshot: bool = True, expected_etag: str | None = None
    ) -> str: ...
    def snapshot_now(self, name: str) -> None: ...
    def etag_for(self, deck: Deck) -> str: ...
    def list_snapshots(self, name: str) -> list[SnapshotInfo]: ...
    def restore_snapshot(
        self, name: str, snapshot_id: str, expected_etag: str | None = None
    ) -> tuple[Deck, str]: ...
    def save_draft(
        self, name: str, *, deck: object, reason: str, source: str, base_etag: str | None
    ) -> DraftInfo: ...
    def list_drafts(self, name: str) -> list[DraftInfo]: ...
    def restore_draft(
        self, name: str, draft_id: str, expected_etag: str | None = None
    ) -> tuple[Deck, str]: ...
    def delete_draft(self, name: str, draft_id: str) -> None: ...
    def list_sources(self, name: str) -> list[str]: ...
    def read_source(self, name: str, filename: str) -> str: ...
    def write_source(self, name: str, filename: str, text: str) -> None: ...
    def source_exists(self, name: str, filename: str) -> bool: ...
    def write_upload(self, name: str, filename: str, data: bytes) -> None: ...
    def read_upload(self, name: str, filename: str) -> bytes | None: ...
    def delete_upload(self, name: str, filename: str) -> None: ...
    def exports_dir(self, name: str) -> Path: ...
    def export_history_dir(self, name: str) -> Path: ...
    def append_usage(self, name: str, line: str) -> None: ...
    def load_global_preset(self) -> Preset: ...
    def save_global_preset(self, preset: Preset) -> None: ...


class FileProjectStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._locks: dict[str, threading.RLock] = {}
        self._locks_guard = threading.Lock()  # _locks 딕셔너리 자체의 동시 접근 보호 (전역 잠금)

    # -- 잠금 ---------------------------------------------------------------

    def _lock_for(self, name: str) -> threading.RLock:
        with self._locks_guard:
            lock = self._locks.get(name)
            if lock is None:
                lock = threading.RLock()
                self._locks[name] = lock
            return lock

    @contextmanager
    def locked(self, name: str):
        """프로젝트별 재진입 잠금. 같은 스레드가 안에서 다시 잠가도(라우트가 잠근 채 저장소
        메서드를 불러도) 막히지 않는다. 같은 프로세스 안의 겹친 요청만 막는다 (설계상 범위, 가정 4).
        NFC로 정규화한 뒤 잠그므로, 같은 프로젝트를 NFC와 NFD 양쪽 이름으로 부르는 호출도 같은 잠금을 쓴다."""
        name = _nfc(name)
        lock = self._lock_for(name)
        lock.acquire()
        try:
            yield
        finally:
            lock.release()

    # -- 내부 공통 ---------------------------------------------------------

    def _atomic_write(self, dir_path: Path, filename: str, data: bytes, *, prefix: str, suffix: str) -> None:
        """같은 폴더에 고유 이름의 임시 파일을 만들어 쓰고 닫은 뒤 os.replace로 교체한다.
        NamedTemporaryFile의 무작위 이름이 동시 호출끼리 같은 임시 경로를 다투는 경합을 없앤다.
        with 블록으로 쓰기를 마쳐 닫은 뒤 교체해야 한다 (Windows는 자기 핸들이 열려 있어도 교체가 실패한다).
        """
        tmp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=dir_path, prefix=prefix, suffix=suffix, delete=False) as f:
                tmp_path = Path(f.name)
                f.write(data)
            os.replace(tmp_path, dir_path / filename)
        except Exception:
            if tmp_path is not None and tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass  # 삭제 실패가 원래 예외를 가리면 안 된다
            raise

    def _project_dir(self, name: str) -> Path:
        _validate_name(name, "프로젝트")
        d = self.root / name
        if not (d / "deck.json").exists():
            raise ProjectNotFound(f"프로젝트를 찾지 못했습니다: {name}")
        self._require_supported_format(d)
        return d

    def _project_dir_any(self, name: str) -> Path:
        """스냅샷 경로용: deck.json이 없어도(복구 대상) 프로젝트 폴더에 접근한다."""
        _validate_name(name, "프로젝트")
        d = self.root / name
        if not d.is_dir():
            raise ProjectNotFound(f"프로젝트를 찾지 못했습니다: {name}")
        self._require_supported_format(d)
        return d

    def _require_supported_format(self, project_dir: Path) -> None:
        state = project_format.manifest_state(project_dir)
        if state == "newer":
            raise ProjectFormatTooNew(_NEWER_FORMAT_MESSAGE)
        if state == "unreadable":
            raise ProjectManifestUnreadable(_UNREADABLE_MANIFEST_MESSAGE)

    def _write_deck(self, project_dir: Path, deck: Deck) -> str:
        """deck.json을 원자적으로 쓰고 그 바이트의 SHA-256 16진수(ETag)를 돌려준다."""
        data = deck.model_dump_json(indent=2).encode("utf-8")
        self._atomic_write(project_dir, "deck.json", data, prefix=".deck-", suffix=".tmp")
        return hashlib.sha256(data).hexdigest()

    def _snapshot_current(self, project_dir: Path) -> str | None:
        """현재 deck.json을 스냅샷으로 남기고 그 ID를 돌려준다. 임시 파일에 쓴 뒤 교체하므로
        중간에 끊겨도 잘린 스냅샷이 목록에 남지 않는다 (D2a-1, 이전 전 복사본이 복구 지점이다)."""
        src = project_dir / "deck.json"
        if not src.exists():
            return None
        data = src.read_bytes()
        source_stat = src.stat()
        snapshots_dir = project_dir / "snapshots"
        snapshots_dir.mkdir(exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        stem = f"deck-{ts}"
        n = 1
        while (snapshots_dir / f"{stem}.json").exists():  # 같은 마이크로초 충돌 백스톱
            stem = f"deck-{ts}-{n}"
            n += 1
        self._atomic_write(snapshots_dir, f"{stem}.json", data, prefix=".snapshot-", suffix=".tmp")
        try:
            # 복사(copy2)였을 때처럼 원본 덱의 수정 시각을 남긴다: 복구 필요 목록이 이 시각을 쓴다
            os.utime(snapshots_dir / f"{stem}.json", ns=(source_stat.st_atime_ns, source_stat.st_mtime_ns))
        except OSError:
            pass  # 시각 복사 실패는 복구 지점의 내용과 무관하다
        return stem

    def _write_deck_recorded(self, project_dir: Path, deck: Deck, *, snapshot: bool) -> str:
        """덱을 쓰고 형식 기록을 덱 내용에 맞춘다 (D2a-1).

        디스크의 덱이 형식 1이고 새 덱이 형식 2이면, 화면의 스냅샷 요청과 관계없이 먼저 스냅샷을
        남긴다. 몇 번째 저장이든 같다: 0.2.0이 manifest를 모른 채 형식 1 덱을 써 넣은 뒤에도
        다시 복구 지점이 생긴다. 순서는 스냅샷, pending 기록, 덱 교체, 완료 기록이다. 끊기면
        다음 쓰기가 덱 내용으로 pending을 마무리한다.
        """
        deck_path = project_dir / "deck.json"
        old_bytes = deck_path.read_bytes() if deck_path.exists() else None
        old = project_format.deck_format_of_bytes(old_bytes) if old_bytes is not None else None
        new = project_format.deck_format(deck)
        manifest = project_format.reconcile(project_format.read_manifest(project_dir), old)
        if old == 1 and new == 2:
            # 형식 1에서 2로 바꾸는 저장은 화면의 스냅샷 요청과 관계없이 복구 지점을 남긴다 (최종 리뷰 F16).
            # 그 복구 지점을 "새 형식으로 바꾸기 전"(0.2.0으로 되돌릴 지점)으로 기록하는 것은 0.2.0이
            # 실제로 열 수 있는 덱일 때만이다 (리뷰 R9: 깨진 덱 제외)
            snapshot_id = self._snapshot_current(project_dir)
            if project_format.legacy_readable(old_bytes):
                etag = self._write_with_pending(project_dir, deck, manifest, project_format.MigrationRecord(
                    at=project_format.now_iso(), kind="upgrade", from_format=1, to_format=2,
                    snapshot_id=snapshot_id, status="pending",
                ))
            else:
                etag = self._write_deck(project_dir, deck)
        elif old == 2 and new == 1:
            # 형식이 내려가는 저장도 덱 교체 전에 pending을 남긴다. 그래야 마지막 기록이 실패해도 다음
            # 쓰기가 이 앱의 저장으로 마무리하고, 0.2.0의 외부 되돌림으로 잘못 기록하지 않는다 (최종 리뷰 F3)
            snapshot_id = self._snapshot_current(project_dir) if snapshot else None
            etag = self._write_with_pending(project_dir, deck, manifest, project_format.MigrationRecord(
                at=project_format.now_iso(), kind="downgrade", from_format=2, to_format=1,
                snapshot_id=snapshot_id, status="pending",
            ))
        else:
            if snapshot:
                self._snapshot_current(project_dir)
            etag = self._write_deck(project_dir, deck)
        manifest.format_version = new
        try:
            project_format.write_manifest(project_dir, manifest, self._atomic_write)
        except OSError:
            # 덱은 이미 저장됐다. 기록 실패를 저장 실패로 돌려주면 화면이 새 ETag를 모른 채 다시
            # 저장해 자기 저장과 충돌한다(리뷰 R5). 다음 쓰기의 reconcile이 기록을 바로잡는다
            _LOG.warning("형식 기록(manifest.json) 쓰기 실패: %s", project_dir, exc_info=True)
        return etag

    def _write_with_pending(self, project_dir: Path, deck: Deck, manifest, record) -> str:
        """pending 이전 기록을 먼저 쓰고 덱을 교체한다. 완료 기록은 호출자의 마지막 manifest 쓰기가 남긴다."""
        manifest.migrations.append(record)
        project_format.write_manifest(project_dir, manifest, self._atomic_write)
        etag = self._write_deck(project_dir, deck)
        record.status = "done"
        return etag

    # -- 프로젝트 ----------------------------------------------------------

    def create_project(self, name: str, title: str = "") -> ProjectInfo:
        name = _nfc(name)
        _validate_name(name, "프로젝트")
        if name in ("preset.json", "preset.json.tmp"):
            # preset.json.tmp는 구 고정 임시 파일명(현재는 .preset-<무작위>.tmp)과의 충돌 방지용으로
            # 계속 막는다: 과거에 이 이름으로 만든 프로젝트가 남아 있을 수 있어 이름 자체를 계속 예약해 둔다.
            raise InvalidName(
                f"프로젝트 이름으로 쓸 수 없습니다: {name!r}. "
                "전역 프리셋 파일과 이름이 겹칩니다. 다른 이름을 지어 주세요."
            )
        with self.locked(name):
            d = self.root / name
            if d.exists():
                raise ProjectExists(f"같은 이름의 프로젝트가 이미 있습니다: {name}")
            try:
                (d / "sources").mkdir(parents=True)
            except FileExistsError as e:
                # exists() 확인과 mkdir 사이의 경합 백스톱: 잠금이 있으면 같은 이름끼리는 직렬화되므로
                # 이론상 드물지만, 새는 순간 500 대신 사용자에게 뜻이 통하는 오류로 바꾼다
                raise ProjectExists(f"같은 이름의 프로젝트가 이미 있습니다: {name}") from e
            (d / "snapshots").mkdir()
            (d / "exports").mkdir()
            (d / "uploads").mkdir()  # 원본 업로드 보존 (계획서 B2, sources/는 AI 입력용 추출본만 둔다)
            self._write_deck_recorded(d, Deck(meta=DeckMeta(title=title or name)), snapshot=False)
            return self._info(d)

    def list_projects(self) -> list[ProjectInfo]:
        infos = []
        for d in sorted(self.root.iterdir()):
            if not d.is_dir():
                continue
            state = project_format.manifest_state(d)
            if state in ("newer", "unreadable"):  # 덱 검증보다 먼저: 복구 필요로 잘못 안내하지 않는다
                manifest_path = d / project_format.MANIFEST_NAME
                mtime = datetime.fromtimestamp(manifest_path.stat().st_mtime).astimezone()
                infos.append(ProjectInfo(
                    name=_nfc(d.name),
                    title=("(더 새 버전의 SlideCaptain이 만든 프로젝트입니다)" if state == "newer"
                           else "(형식 기록 파일을 읽을 수 없는 프로젝트입니다)"),
                    updated_at=mtime.isoformat(timespec="seconds"),
                    status="newer_format" if state == "newer" else "unreadable_manifest",
                ))
                continue
            if (d / "deck.json").exists():
                infos.append(self._info(d))
                continue
            snapshots_dir = d / "snapshots"
            snapshots = sorted(snapshots_dir.glob("deck-*.json")) if snapshots_dir.is_dir() else []
            if snapshots:  # deck.json은 사라졌지만 복구 지점이 남은 프로젝트
                mtime = datetime.fromtimestamp(snapshots[-1].stat().st_mtime).astimezone()
                infos.append(ProjectInfo(
                    name=_nfc(d.name),
                    title="(deck.json 없음: 스냅샷 복구가 필요합니다)",
                    updated_at=mtime.isoformat(timespec="seconds"),
                    status="needs_recovery",
                ))
        return infos

    def _info(self, d: Path) -> ProjectInfo:
        # d.name은 실제 폴더 이름(Finder가 만든 것이면 NFD일 수 있다)이라 응답 직전에 NFC로 맞춘다 (A4).
        deck_path = d / "deck.json"
        status: Literal["ok", "needs_recovery", "newer_format", "unreadable_manifest"] = "ok"
        try:
            title = Deck.model_validate_json(deck_path.read_text(encoding="utf-8")).meta.title
        except (ValueError, ValidationError):
            title = "(deck.json 읽기 실패: 스냅샷 복구가 필요합니다)"
            status = "needs_recovery"
        mtime = datetime.fromtimestamp(deck_path.stat().st_mtime).astimezone()
        return ProjectInfo(
            name=_nfc(d.name), title=title, updated_at=mtime.isoformat(timespec="seconds"), status=status
        )

    # -- 덱 ---------------------------------------------------------------

    def load_deck(self, name: str) -> Deck:
        name = _nfc(name)
        d = self._project_dir(name)
        try:
            return Deck.model_validate_json((d / "deck.json").read_text(encoding="utf-8"))
        except (ValueError, ValidationError) as e:
            raise DeckUnreadable(
                f"프로젝트 {name}의 deck.json을 읽지 못했습니다. "
                f"스냅샷 복구 기능으로 이전 저장 시점으로 되돌릴 수 있습니다. 원인: {e}"
            ) from e

    def deck_etag(self, name: str) -> str:
        """deck.json 바이트의 SHA-256 16진수(따옴표 없음)."""
        name = _nfc(name)
        d = self._project_dir(name)
        return hashlib.sha256((d / "deck.json").read_bytes()).hexdigest()

    def load_deck_with_etag(self, name: str) -> tuple[Deck, str]:
        name = _nfc(name)
        d = self._project_dir(name)
        data = (d / "deck.json").read_bytes()
        try:
            deck = Deck.model_validate_json(data)
        except (ValueError, ValidationError) as e:
            raise DeckUnreadable(
                f"프로젝트 {name}의 deck.json을 읽지 못했습니다. "
                f"스냅샷 복구 기능으로 이전 저장 시점으로 되돌릴 수 있습니다. 원인: {e}"
            ) from e
        return deck, hashlib.sha256(data).hexdigest()

    def save_deck(
        self, name: str, deck: Deck, snapshot: bool = True, expected_etag: str | None = None
    ) -> str:
        # 모델을 직접 편집해 도식 참조나 필드를 훼손했어도 저장/스냅샷을 쓰지 않는다.
        deck = Deck.model_validate(_evidence_input(deck))
        name = _nfc(name)
        with self.locked(name):
            d = self._project_dir(name)
            if expected_etag is not None:
                current = hashlib.sha256((d / "deck.json").read_bytes()).hexdigest()
                if current != expected_etag:
                    raise DeckConflict(_DECK_CONFLICT_MESSAGE)
            return self._write_deck_recorded(d, deck, snapshot=snapshot)

    def etag_for(self, deck: Deck) -> str:
        """save_deck이 이 덱을 쓰면 될 ETag. 저장과 같은 검증과 직렬화를 쓴다 (D2b-4, 계획서 5.7 ④)."""
        deck = Deck.model_validate(_evidence_input(deck))
        return hashlib.sha256(deck.model_dump_json(indent=2).encode("utf-8")).hexdigest()

    def snapshot_now(self, name: str) -> None:
        """의미 시점 스냅샷 (단계 4 결정 1): 내보내기 직전 등 명시적 복구 지점."""
        name = _nfc(name)
        with self.locked(name):
            self._snapshot_current(self._project_dir(name))

    # -- 스냅샷 ------------------------------------------------------------

    def list_snapshots(self, name: str) -> list[SnapshotInfo]:
        name = _nfc(name)
        d = self._project_dir_any(name)
        pre_migration = project_format.pre_migration_snapshot_ids(d)
        infos = []
        for p in sorted((d / "snapshots").glob("deck-*.json")):
            m = _SNAPSHOT_RE.match(p.stem)
            if m is None:
                continue
            ts = datetime.strptime(m.group(1), "%Y%m%d-%H%M%S-%f").astimezone()
            infos.append(SnapshotInfo(
                id=p.stem, saved_at=ts.isoformat(timespec="seconds"),
                kind="pre_migration" if p.stem in pre_migration else "snapshot",
            ))
        return infos

    def restore_snapshot(
        self, name: str, snapshot_id: str, expected_etag: str | None = None
    ) -> tuple[Deck, str]:
        name = _nfc(name)
        with self.locked(name):
            d = self._project_dir_any(name)
            if expected_etag is not None:
                deck_path = d / "deck.json"
                current = hashlib.sha256(deck_path.read_bytes()).hexdigest() if deck_path.exists() else None
                if current != expected_etag:
                    raise DeckConflict(_DECK_CONFLICT_MESSAGE)
            _validate_name(snapshot_id, "스냅샷")
            path = d / "snapshots" / f"{snapshot_id}.json"
            if not path.exists():
                raise SnapshotNotFound(f"스냅샷을 찾지 못했습니다: {snapshot_id}")
            try:
                deck = Deck.model_validate_json(path.read_text(encoding="utf-8"))
            except (ValueError, ValidationError) as e:
                raise StorageError(
                    f"스냅샷 {snapshot_id}을 읽지 못했습니다. 다른 스냅샷을 골라 주세요. 원인: {e}"
                ) from e
            # 복원 직전 상태도 스냅샷으로 남긴다. 형식이 바뀌면 형식 기록도 함께 쓴다 (D2a-1)
            etag = self._write_deck_recorded(d, deck, snapshot=True)
            return deck, etag

    # -- 미저장본 보존 (D2a-2) ---------------------------------------------------

    def _draft_path(self, project_dir: Path, draft_id: str) -> Path:
        if not _DRAFT_RE.match(draft_id):
            raise InvalidName(f"보존한 변경의 식별자가 올바르지 않습니다: {draft_id!r}")
        return project_dir / "drafts" / f"{draft_id}.json"

    @staticmethod
    def _draft_info(envelope: dict) -> DraftInfo:
        return DraftInfo.model_validate({k: envelope.get(k) for k in DraftInfo.model_fields})

    def save_draft(
        self, name: str, *, deck: object, reason: str, source: str, base_etag: str | None
    ) -> DraftInfo:
        """덱 원문을 검증하지 않고 보존한다. 검증에 실패한 덱도 사용자 내용이라 버리지 않는다.
        같은 내용은 새로 만들지 않는다. 개수 상한과 자동 삭제는 없다."""
        name = _nfc(name)
        # 화면이 보내는 압축 JSON과 같은 기준으로 잰다(리뷰 R7: 브리지 상한과 측정 대상을 맞춘다)
        deck_bytes = json.dumps(deck, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        content_sha256 = hashlib.sha256(deck_bytes).hexdigest()
        with self.locked(name):
            d = self._project_dir(name)  # 존재와 형식 검사를 크기 검사보다 먼저 한다
            if len(deck_bytes) > DRAFT_MAX_BYTES:
                raise DraftTooLarge(
                    "보존할 변경이 너무 커서 저장하지 못했습니다. 변경 내용을 복사해 따로 보관해 주세요."
                )
            drafts_dir = d / "drafts"
            drafts_dir.mkdir(exist_ok=True)
            # 연속 클릭 병합: 내용, 사유, 출처, 기준 저장본이 모두 같은 요청만 묶는다 (리뷰 R4)
            key = (content_sha256, reason, source, base_etag)
            for existing in self._read_draft_envelopes(drafts_dir):
                existing_key = (existing.get("content_sha256"), existing.get("reason"),
                                existing.get("source"), existing.get("base_etag"))
                if existing_key == key:
                    try:
                        return self._draft_info(existing)
                    except ValidationError:
                        continue  # 모양이 맞지 않는 보존본은 건너뛰고 새로 만든다 (리뷰 R5)
            ts = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            stem = f"draft-{ts}"
            n = 1
            while (drafts_dir / f"{stem}.json").exists():  # 같은 마이크로초 충돌 백스톱
                stem = f"draft-{ts}-{n}"
                n += 1
            envelope = {
                "id": stem,
                "saved_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "reason": reason,
                "source": source,
                "base_etag": base_etag,
                "content_sha256": content_sha256,
                "deck": deck,
            }
            info = self._draft_info(envelope)  # 사유와 출처의 값 검증을 쓰기 전에 한다
            data = json.dumps(envelope, ensure_ascii=False, indent=2).encode("utf-8")
            self._atomic_write(drafts_dir, f"{stem}.json", data, prefix=".draft-", suffix=".tmp")
            return info

    @staticmethod
    def _read_draft_envelopes(drafts_dir: Path) -> list[dict]:
        envelopes = []
        if not drafts_dir.is_dir():
            return envelopes

        def order(path: Path) -> tuple[str, int]:
            # 파일 이름 정렬은 "-1"을 원래 이름보다 앞에 둔다. 시각과 충돌 번호로 정렬한다 (리뷰 R6)
            m = _DRAFT_RE.match(path.stem)
            suffix = path.stem[len(f"draft-{m.group(1)}"):] if m else ""
            return (m.group(1) if m else "", int(suffix[1:]) if suffix else 0)

        for path in sorted(drafts_dir.glob("draft-*.json"), key=order):
            if not _DRAFT_RE.match(path.stem):
                continue
            try:
                envelope = json.loads(path.read_bytes())
            except (OSError, ValueError):
                continue  # 읽을 수 없는 보존본은 목록에서 빼되 지우지 않는다
            if isinstance(envelope, dict) and envelope.get("id") == path.stem:
                envelopes.append(envelope)
        return envelopes

    def list_drafts(self, name: str) -> list[DraftInfo]:
        name = _nfc(name)
        d = self._project_dir_any(name)
        infos = []
        for envelope in self._read_draft_envelopes(d / "drafts"):
            try:
                infos.append(self._draft_info(envelope))
            except ValidationError:
                continue
        return infos

    def restore_draft(
        self, name: str, draft_id: str, expected_etag: str | None = None
    ) -> tuple[Deck, str]:
        """보존본의 덱을 검증해 저장본으로 쓴다. 복원 직전 덱은 스냅샷으로 남고 보존본은 그대로 둔다."""
        name = _nfc(name)
        with self.locked(name):
            d = self._project_dir_any(name)
            if expected_etag is not None:
                deck_path = d / "deck.json"
                current = hashlib.sha256(deck_path.read_bytes()).hexdigest() if deck_path.exists() else None
                if current != expected_etag:
                    raise DeckConflict(_DECK_CONFLICT_MESSAGE)
            path = self._draft_path(d, draft_id)
            if not path.is_file():
                raise DraftNotFound(f"보존한 변경을 찾지 못했습니다: {draft_id}")
            try:
                envelope = json.loads(path.read_bytes())
                deck = Deck.model_validate(_evidence_input(Deck.model_validate(envelope["deck"])))
            except (OSError, ValueError, KeyError, TypeError, ValidationError) as e:
                raise StorageError(
                    "보존한 변경을 덱으로 읽지 못해 복원하지 않았습니다. 현재 저장본은 바뀌지 않았습니다. "
                    f"원인: {e}"
                ) from e
            etag = self._write_deck_recorded(d, deck, snapshot=True)
            return deck, etag

    def delete_draft(self, name: str, draft_id: str) -> None:
        """사용자가 고른 보존본 하나만 지운다."""
        name = _nfc(name)
        with self.locked(name):
            d = self._project_dir_any(name)
            path = self._draft_path(d, draft_id)
            if not path.is_file():
                raise DraftNotFound(f"보존한 변경을 찾지 못했습니다: {draft_id}")
            path.unlink()

    # -- 입력 자료 ----------------------------------------------------------

    def list_sources(self, name: str) -> list[str]:
        name = _nfc(name)
        d = self._project_dir(name)
        return sorted(
            _nfc(p.name)
            for p in (d / "sources").iterdir()
            # 점으로 시작하는 이름 제외: ".tmp-" 저장 잔재와 숨김 파일
            if p.is_file() and not p.name.startswith(".")
        )

    def read_source(self, name: str, filename: str) -> str:
        name = _nfc(name)
        filename = _nfc(filename)
        d = self._project_dir(name)
        _validate_read_name(filename)
        path = d / "sources" / filename
        if not path.exists():
            raise SourceNotFound(f"자료 파일을 찾지 못했습니다: {filename}")
        return decode_source_bytes(path.read_bytes(), filename)

    def source_exists(self, name: str, filename: str) -> bool:
        """앱이 만드는 이름 규칙으로 검증한 뒤 존재 여부를 돌려준다 (업로드의 덮어쓰기 판정용)."""
        name = _nfc(name)
        filename = _nfc(filename)
        d = self._project_dir(name)
        _validate_name(filename, "자료 파일")
        return (d / "sources" / filename).is_file()

    def write_source(self, name: str, filename: str, text: str) -> None:
        name = _nfc(name)
        filename = _nfc(filename)
        _validate_name(filename, "자료 파일")
        with self.locked(name):
            d = self._project_dir(name)
            # 대소문자만 다른 기존 파일이 있으면 거부한다 (A4). 정확히 같은 이름은 여기 걸리지 않고
            # 아래에서 그대로 덮어쓴다 (자료 저장 버튼의 의미).
            conflict = _casefold_conflict(d / "sources", filename)
            if conflict is not None:
                raise SourceConflict(
                    f"대소문자만 다른 자료가 이미 있습니다: {conflict}. "
                    "같은 이름으로 저장하거나 다른 이름을 써 주세요."
                )
            # 접두사 + 무작위 문자열 + "-파일명" 형태(.tmp-<무작위>-<이름>): 정식 자료명
            # "a.md.tmp"와의 충돌을 피하면서도 동시 저장끼리 임시 경로가 겹치지 않는다
            self._atomic_write(d / "sources", filename, text.encode("utf-8"), prefix=".tmp-", suffix="-" + filename)

    def write_upload(self, name: str, filename: str, data: bytes) -> None:
        """원본 업로드 바이트를 uploads/에 그대로 보존한다 (계획서 B2). write_source와 같은
        규약을 쓴다: NFC 정규화, 이름 검증, 대소문자만 다른 기존 파일은 SourceConflict로 거부,
        원자적 쓰기. uploads/가 없는 옛 프로젝트(B2 이전에 만든 프로젝트)는 처음 쓸 때 만든다
        (exists 확인 뒤 mkdir을 하면 그 사이 경합이 생기므로 exist_ok=True로 한 번에 처리한다)."""
        name = _nfc(name)
        filename = _nfc(filename)
        _validate_name(filename, "자료 파일")
        with self.locked(name):
            d = self._project_dir(name)
            uploads_dir = d / "uploads"
            uploads_dir.mkdir(parents=True, exist_ok=True)
            conflict = _casefold_conflict(uploads_dir, filename)
            if conflict is not None:
                raise SourceConflict(
                    f"대소문자만 다른 자료가 이미 있습니다: {conflict}. "
                    "같은 이름으로 저장하거나 다른 이름을 써 주세요."
                )
            self._atomic_write(uploads_dir, filename, data, prefix=".tmp-", suffix="-" + filename)

    def read_upload(self, name: str, filename: str) -> bytes | None:
        """uploads/의 원본 바이트를 읽는다. 파일이 없으면 None을 돌려준다(예외가 아니다: 없는
        것이 정상 경로인 신규 업로드에도 쓰인다). overwrite 재업로드 중 추출본 쓰기가 실패했을 때
        이전 원본으로 되돌리기 위한 백업용이다 (계획서 B2 리뷰 F1)."""
        name = _nfc(name)
        filename = _nfc(filename)
        d = self._project_dir(name)
        _validate_name(filename, "자료 파일")
        path = d / "uploads" / filename
        if not path.is_file():
            return None
        return path.read_bytes()

    def delete_upload(self, name: str, filename: str) -> None:
        """write_upload 직후 write_source가 실패했을 때 원본만 남는 상태를 만들지 않기 위한
        되돌리기용이다 (계획서 B2). 파일이 이미 없으면 조용히 넘어간다(멱등)."""
        name = _nfc(name)
        filename = _nfc(filename)
        with self.locked(name):
            d = self._project_dir(name)
            (d / "uploads" / filename).unlink(missing_ok=True)

    # -- 내보내기 -----------------------------------------------------------

    def exports_dir(self, name: str) -> Path:
        name = _nfc(name)
        return self._project_dir(name) / "exports"

    def export_history_dir(self, name: str) -> Path:
        """History remains accessible when the deck needs recovery; never mkdir."""
        name = _nfc(name)
        directory = self._project_dir_any(name)
        if directory.is_symlink():
            raise InvalidName("프로젝트 폴더의 바로가기로 검수 이력을 조회할 수 없습니다.")
        return directory / "exports"

    # -- AI 사용량 기록 ------------------------------------------------------

    def append_usage(self, name: str, line: str) -> None:
        """AI 사용량 기록 1줄을 project/<이름>/ai-usage.jsonl에 덧붙인다 (단계 5A 묶음 C 태스크 C3,
        가정 4). 내용은 담지 않는 사용량 요약 한 줄이며, 파일이 없으면 새로 만든다. 없는 프로젝트는
        다른 쓰기 메서드와 같이 ProjectNotFound를 낸다."""
        name = _nfc(name)
        with self.locked(name):
            d = self._project_dir(name)
            with (d / "ai-usage.jsonl").open("a", encoding="utf-8", newline="\n") as f:
                f.write(line + "\n")

    # -- 전역 프리셋 --------------------------------------------------------

    def load_global_preset(self) -> Preset:
        path = self.root / "preset.json"
        if not path.exists():
            return Preset()
        try:
            return Preset.model_validate_json(path.read_text(encoding="utf-8"))
        except (ValueError, ValidationError) as e:
            raise StorageError(
                "전역 프리셋 파일(preset.json)을 읽지 못했습니다. "
                f"파일을 지우면 기본값으로 돌아갑니다. 원인: {e}"
            ) from e

    def save_global_preset(self, preset: Preset) -> None:
        data = preset.model_dump_json(indent=2).encode("utf-8")
        self._atomic_write(self.root, "preset.json", data, prefix=".preset-", suffix=".tmp")
