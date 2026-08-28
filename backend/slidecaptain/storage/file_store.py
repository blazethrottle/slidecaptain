"""프로젝트 폴더 저장소 (설계서 3.1, 7.2).

projects/<프로젝트명>/
  deck.json      # 진본
  sources/       # 입력 자료 원문 (수치 대조의 기준)
  snapshots/     # 저장 시점 스냅샷
  exports/       # 내보낸 PPTX

- 저장은 원자적: 같은 폴더의 임시 파일에 쓴 뒤 os.replace로 교체
- 저장마다 직전 deck.json을 스냅샷으로 보존 (복구 경로)
"""

import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ValidationError

from slidecaptain.models.deck import Deck, DeckMeta

_NAME_RE = re.compile(r"^[0-9A-Za-z가-힣][0-9A-Za-z가-힣 ._\-]{0,79}$")
_WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)}
_SNAPSHOT_RE = re.compile(r"^deck-(\d{8}-\d{6}-\d{6})(?:-\d+)?$")


class StorageError(Exception):
    """사용자에게 쉬운 말로 보여줄 저장소 오류."""


class InvalidName(StorageError):
    pass


class ProjectNotFound(StorageError):
    pass


class ProjectExists(StorageError):
    pass


class SnapshotNotFound(StorageError):
    pass


class SourceNotFound(StorageError):
    pass


class ProjectInfo(BaseModel):
    name: str
    title: str
    updated_at: str  # ISO 8601


class SnapshotInfo(BaseModel):
    id: str  # 파일 이름에서 확장자를 뺀 것 (예: deck-20260828-153000-123456)
    saved_at: str


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


class ProjectStore(Protocol):
    """저장소 인터페이스 (설계서 2.2). 파일 구현 외의 구현(DB 등)으로 교체 가능하게 한다."""

    def list_projects(self) -> list[ProjectInfo]: ...
    def create_project(self, name: str, title: str = "") -> ProjectInfo: ...
    def load_deck(self, name: str) -> Deck: ...
    def save_deck(self, name: str, deck: Deck) -> None: ...
    def list_snapshots(self, name: str) -> list[SnapshotInfo]: ...
    def restore_snapshot(self, name: str, snapshot_id: str) -> Deck: ...
    def list_sources(self, name: str) -> list[str]: ...
    def read_source(self, name: str, filename: str) -> str: ...
    def write_source(self, name: str, filename: str, text: str) -> None: ...
    def exports_dir(self, name: str) -> Path: ...


class FileProjectStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    # -- 내부 공통 ---------------------------------------------------------

    def _project_dir(self, name: str) -> Path:
        _validate_name(name, "프로젝트")
        d = self.root / name
        if not (d / "deck.json").exists():
            raise ProjectNotFound(f"프로젝트를 찾지 못했습니다: {name}")
        return d

    def _write_deck(self, project_dir: Path, deck: Deck) -> None:
        tmp = project_dir / "deck.json.tmp"
        tmp.write_text(deck.model_dump_json(indent=2), encoding="utf-8")
        os.replace(tmp, project_dir / "deck.json")

    def _snapshot_current(self, project_dir: Path) -> None:
        src = project_dir / "deck.json"
        if not src.exists():
            return
        ts = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        dst = project_dir / "snapshots" / f"deck-{ts}.json"
        n = 1
        while dst.exists():  # 같은 마이크로초 충돌 백스톱
            dst = project_dir / "snapshots" / f"deck-{ts}-{n}.json"
            n += 1
        shutil.copy2(src, dst)

    # -- 프로젝트 ----------------------------------------------------------

    def create_project(self, name: str, title: str = "") -> ProjectInfo:
        _validate_name(name, "프로젝트")
        d = self.root / name
        if d.exists():
            raise ProjectExists(f"같은 이름의 프로젝트가 이미 있습니다: {name}")
        (d / "sources").mkdir(parents=True)
        (d / "snapshots").mkdir()
        (d / "exports").mkdir()
        self._write_deck(d, Deck(meta=DeckMeta(title=title or name)))
        return self._info(d)

    def list_projects(self) -> list[ProjectInfo]:
        infos = []
        for d in sorted(self.root.iterdir()):
            if d.is_dir() and (d / "deck.json").exists():
                infos.append(self._info(d))
        return infos

    def _info(self, d: Path) -> ProjectInfo:
        deck_path = d / "deck.json"
        try:
            title = Deck.model_validate_json(deck_path.read_text(encoding="utf-8")).meta.title
        except (ValueError, ValidationError):
            title = "(deck.json 읽기 실패: 스냅샷 복구가 필요합니다)"
        mtime = datetime.fromtimestamp(deck_path.stat().st_mtime).astimezone()
        return ProjectInfo(name=d.name, title=title, updated_at=mtime.isoformat(timespec="seconds"))

    # -- 덱 ---------------------------------------------------------------

    def load_deck(self, name: str) -> Deck:
        d = self._project_dir(name)
        try:
            return Deck.model_validate_json((d / "deck.json").read_text(encoding="utf-8"))
        except (ValueError, ValidationError) as e:
            raise StorageError(
                f"프로젝트 {name}의 deck.json을 읽지 못했습니다. "
                f"스냅샷 복구 기능으로 이전 저장 시점으로 되돌릴 수 있습니다. 원인: {e}"
            ) from e

    def save_deck(self, name: str, deck: Deck) -> None:
        d = self._project_dir(name)
        self._snapshot_current(d)
        self._write_deck(d, deck)

    # -- 스냅샷 ------------------------------------------------------------

    def list_snapshots(self, name: str) -> list[SnapshotInfo]:
        d = self._project_dir(name)
        infos = []
        for p in sorted((d / "snapshots").glob("deck-*.json")):
            m = _SNAPSHOT_RE.match(p.stem)
            if m is None:
                continue
            ts = datetime.strptime(m.group(1), "%Y%m%d-%H%M%S-%f").astimezone()
            infos.append(SnapshotInfo(id=p.stem, saved_at=ts.isoformat(timespec="seconds")))
        return infos

    def restore_snapshot(self, name: str, snapshot_id: str) -> Deck:
        d = self._project_dir(name)
        _validate_name(snapshot_id, "스냅샷")
        path = d / "snapshots" / f"{snapshot_id}.json"
        if not path.exists():
            raise SnapshotNotFound(f"스냅샷을 찾지 못했습니다: {snapshot_id}")
        try:
            deck = Deck.model_validate_json(path.read_text(encoding="utf-8"))
        except (ValueError, ValidationError) as e:
            raise StorageError(f"스냅샷 {snapshot_id}을 읽지 못했습니다. 다른 스냅샷을 골라 주세요. 원인: {e}") from e
        self._snapshot_current(d)  # 복원 직전 상태도 스냅샷으로 남긴다
        self._write_deck(d, deck)
        return deck

    # -- 입력 자료 ----------------------------------------------------------

    def list_sources(self, name: str) -> list[str]:
        d = self._project_dir(name)
        return sorted(p.name for p in (d / "sources").iterdir() if p.is_file())

    def read_source(self, name: str, filename: str) -> str:
        d = self._project_dir(name)
        _validate_name(filename, "자료 파일")
        path = d / "sources" / filename
        if not path.exists():
            raise SourceNotFound(f"자료 파일을 찾지 못했습니다: {filename}")
        return path.read_text(encoding="utf-8")

    def write_source(self, name: str, filename: str, text: str) -> None:
        d = self._project_dir(name)
        _validate_name(filename, "자료 파일")
        tmp = d / "sources" / (filename + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, d / "sources" / filename)

    # -- 내보내기 -----------------------------------------------------------

    def exports_dir(self, name: str) -> Path:
        return self._project_dir(name) / "exports"
