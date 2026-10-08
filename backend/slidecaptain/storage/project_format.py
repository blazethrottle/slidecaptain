"""프로젝트 형식 판정과 기록 (개정판 D2a-1).

형식 1은 0.2.0이 읽을 수 있는 덱이고, 형식 2는 그렇지 않은 덱이다. 판정은 manifest가 아니라
덱 내용으로 한다. 배포된 0.2.0은 manifest를 모른 채 deck.json만 다시 쓰므로(저장, 스냅샷 복원)
manifest만 믿으면 두 파일이 어긋난다. manifest는 판정 결과의 기록이며, 쓰기 때마다 덱 내용으로
다시 계산해 바로잡는다. 앱 버전은 판정에 쓰지 않고 진단용으로만 남긴다.

Deck.schema_version은 1로 둔다. 0.2.0은 필드 검증이 끝난 뒤에야 버전을 검사하므로, 버전을
올려도 새 보고 유형 덱에 대한 0.2.0의 표시는 나아지지 않는다(2026-10-08 실측).
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Callable, Literal

from pydantic import BaseModel, ValidationError

from slidecaptain import __version__

MANIFEST_NAME = "manifest.json"
FORMAT_NAME = "slidecaptain-project"
MAX_SUPPORTED_FORMAT = 2
# 0.2.0(v0.2.0)의 ReportType. 이후 덱 계약의 차이는 보고 유형 6개 추가 하나뿐이다.
LEGACY_REPORT_TYPES = frozenset({"research", "approval", "strategy"})
# Deck.model_json_schema()의 SHA-256. 스키마가 바뀌면 test_project_format이 실패해 형식 판정을
# 다시 검토하게 한다 (모르는 필드를 버리는 이전 앱이 새 필드를 경고 없이 지우지 않게).
PINNED_DECK_SCHEMA_SHA256 = "48a623744b319353400654baf927df73e2458316c8b43bfd2fe24893e3ffbf3d"


class MigrationRecord(BaseModel):
    at: str
    kind: Literal["upgrade", "downgrade"]
    from_format: int
    to_format: int
    snapshot_id: str | None = None
    # pending: 덱 교체 전 기록. done: 교체 확인. interrupted: 교체 전에 끊겨 덱이 이전 형식으로 남음
    status: Literal["pending", "done", "interrupted"] = "done"


class ProjectManifest(BaseModel):
    format: str = FORMAT_NAME
    format_version: int
    written_by: str = __version__  # 진단용. 판정에 쓰지 않는다
    migrations: list[MigrationRecord] = []


def _format_of_report_type(report_type: object) -> int:
    return 1 if report_type in LEGACY_REPORT_TYPES else 2


def deck_format(deck) -> int:
    """덱이 요구하는 형식. 0.2.0이 읽을 수 있으면 1, 아니면 2."""
    return _format_of_report_type(deck.meta.report_type)


def deck_format_of_bytes(data: bytes) -> int | None:
    """디스크의 deck.json 바이트가 요구하는 형식. JSON으로 읽을 수 없으면 None.

    0.2.0이 쓴 덱도 판정해야 하므로 현재 모델로 검증하지 않고 보고 유형만 본다.
    보고 유형이 없으면 0.2.0의 기본값(research)과 같게 본다.
    """
    try:
        payload = json.loads(data)
    except ValueError:
        return None
    meta = payload.get("meta") if isinstance(payload, dict) else None
    if not isinstance(meta, dict):
        return None
    return _format_of_report_type(meta.get("report_type", "research"))


def manifest_format_version(project_dir: Path) -> int | None:
    """manifest의 형식 번호만 느슨하게 읽는다. 더 새 앱의 manifest는 이 앱의 모델과 모양이
    다를 수 있으므로, 더 새 형식 판정에는 이 함수를 쓴다. 없거나 읽을 수 없으면 None."""
    try:
        payload = json.loads((project_dir / MANIFEST_NAME).read_bytes())
    except (OSError, ValueError):
        return None
    value = payload.get("format_version") if isinstance(payload, dict) else None
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def read_manifest(project_dir: Path) -> ProjectManifest | None:
    try:
        return ProjectManifest.model_validate_json((project_dir / MANIFEST_NAME).read_bytes())
    except (OSError, ValueError, ValidationError):
        return None


def write_manifest(
    project_dir: Path, manifest: ProjectManifest, atomic_write: Callable[..., None]
) -> None:
    data = manifest.model_dump_json(indent=2).encode("utf-8")
    atomic_write(project_dir, MANIFEST_NAME, data, prefix=".manifest-", suffix=".tmp")


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def reconcile(manifest: ProjectManifest | None, disk_format: int | None) -> ProjectManifest:
    """끊긴 이전 기록을 디스크의 덱 내용으로 마무리하고 형식 번호를 현재 덱에 맞춘다."""
    if manifest is None:
        manifest = ProjectManifest(format_version=disk_format or 1)
    for record in manifest.migrations:
        if record.status == "pending":
            record.status = "done" if disk_format == record.to_format else "interrupted"
    if disk_format is not None:
        manifest.format_version = disk_format
    manifest.written_by = __version__
    return manifest


def pre_migration_snapshot_ids(project_dir: Path) -> set[str]:
    manifest = read_manifest(project_dir)
    if manifest is None:
        return set()
    return {m.snapshot_id for m in manifest.migrations if m.kind == "upgrade" and m.snapshot_id}
