"""프로젝트 형식 판정과 기록 (개정판 D2a-1).

형식 1은 0.2.0이 읽을 수 있는 덱이고, 형식 2는 그렇지 않은 덱이다. 판정은 manifest가 아니라
덱 내용으로 한다. 배포된 0.2.0은 manifest를 모른 채 deck.json만 다시 쓰므로(저장, 스냅샷 복원)
manifest만 믿으면 두 파일이 어긋난다. manifest는 판정 결과의 기록이며, 쓰기 때마다 덱 내용으로
다시 계산해 바로잡는다. 앱 버전은 판정에 쓰지 않고 진단용으로만 남긴다.

이 앱이 이해할 수 없는 manifest(형식 번호가 더 크거나 정수가 아니거나 JSON이 깨진 것)는
덮어쓰지 않는다. 그 프로젝트는 열지 않는다(file_store의 공통 진입이 거절한다). 이해할 수 있는
manifest라도 모르는 필드와 모르는 기록 종류는 그대로 보존한다.

Deck.schema_version은 1로 둔다. 0.2.0은 필드 검증이 끝난 뒤에야 버전을 검사하므로, 버전을
올려도 새 보고 유형 덱에 대한 0.2.0의 표시는 나아지지 않는다(2026-10-08 실측).
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Callable, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from slidecaptain import __version__

MANIFEST_NAME = "manifest.json"
FORMAT_NAME = "slidecaptain-project"
MAX_SUPPORTED_FORMAT = 2
# 0.2.0(v0.2.0)의 ReportType. 이후 덱 계약의 차이는 보고 유형 6개 추가 하나뿐이다.
LEGACY_REPORT_TYPES = frozenset({"research", "approval", "strategy"})
# 덱 스키마에서 보고 유형 열거가 쓰이는 위치. 판정 함수는 이 두 곳을 모두 본다.
# test_project_format이 스키마를 훑어 이 목록과 실제 위치가 같은지 확인한다.
REPORT_TYPE_LOCATIONS = frozenset({("DeckMeta", "report_type"), ("ReportBrief", "report_type")})
# Deck.model_json_schema()의 SHA-256. 스키마가 바뀌면 test_project_format이 실패해 형식 판정을
# 다시 검토하게 한다 (모르는 필드를 버리는 이전 앱이 새 필드를 경고 없이 지우지 않게).
PINNED_DECK_SCHEMA_SHA256 = "48a623744b319353400654baf927df73e2458316c8b43bfd2fe24893e3ffbf3d"

ManifestState = Literal["missing", "ok", "newer", "unreadable"]


class MigrationRecord(BaseModel):
    # 모르는 필드와 모르는 값도 보존한다: 같은 형식의 이후 앱이 새 기록 종류를 쓸 수 있다
    model_config = ConfigDict(extra="allow")
    at: str
    # upgrade: 형식 1 덱을 형식 2로 처음 바꿈. downgrade: 이 앱의 저장이나 복원으로 형식 1이 됨.
    # external_downgrade: 이 앱의 쓰기 없이 디스크 덱이 형식 1로 돌아와 있었음(0.2.0의 저장이나 복원)
    kind: str
    from_format: int
    to_format: int
    snapshot_id: str | None = None
    # pending: 덱 교체 전 기록. done: 교체 확인. not_applied: 다음 쓰기 때 디스크 덱이 이전
    # 형식이었음(교체 전에 끊겼거나 그 사이 0.2.0이 되돌림. 어느 쪽인지는 알 수 없다)
    status: str = "done"


class ProjectManifest(BaseModel):
    model_config = ConfigDict(extra="allow")
    format: str = FORMAT_NAME
    format_version: int
    written_by: str = __version__  # 진단용. 판정에 쓰지 않는다
    migrations: list[MigrationRecord] = []


def _report_types_of_payload(payload: object) -> list[object] | None:
    """덱 JSON(사전)에서 보고 유형 값을 모은다. 덱 모양이 아니면 None."""
    if not isinstance(payload, dict):
        return None
    meta = payload.get("meta")
    if not isinstance(meta, dict):
        return None
    values = [meta.get("report_type", "research")]  # 없으면 0.2.0의 기본값과 같다
    structure = payload.get("structure")
    plan = structure.get("story_plan") if isinstance(structure, dict) else None
    brief = plan.get("brief") if isinstance(plan, dict) else None
    if isinstance(brief, dict):
        values.append(brief.get("report_type", "research"))
    return values


def _format_of_values(values: list[object]) -> int:
    return 1 if all(v in LEGACY_REPORT_TYPES for v in values) else 2


def deck_format(deck) -> int:
    """덱이 요구하는 형식. 0.2.0이 읽을 수 있으면 1, 아니면 2."""
    values: list[object] = [deck.meta.report_type]
    plan = deck.structure.story_plan
    if plan is not None:
        values.append(plan.brief.report_type)
    return _format_of_values(values)


def deck_format_of_bytes(data: bytes) -> int | None:
    """디스크 deck.json 바이트가 요구하는 형식. 덱으로 읽을 수 없으면 None.

    0.2.0이 쓴 덱도 판정해야 하므로 현재 모델로 검증하지 않고 보고 유형만 본다.
    """
    try:
        values = _report_types_of_payload(json.loads(data))
    except ValueError:
        return None
    return None if values is None else _format_of_values(values)


def legacy_readable(data: bytes) -> bool:
    """0.2.0이 이 바이트를 덱으로 열 수 있는가. 이전 전 복사본 표시의 조건이다.

    현재 모델의 검증을 통과하고 형식이 1이면 0.2.0도 연다(0.2.0 대비 차이는 보고 유형뿐이다).
    복구 필요 상태의 깨진 덱은 형식 판정이 1이어도 0.2.0이 열지 못하므로 제외한다.
    """
    from slidecaptain.models.deck import Deck  # 순환 import 회피: 모델 모듈은 저장소를 모른다

    try:
        deck = Deck.model_validate_json(data)
    except (ValueError, ValidationError):
        return False
    return deck_format(deck) == 1


def _read_manifest_payload(project_dir: Path) -> tuple[ManifestState, dict | None]:
    path = project_dir / MANIFEST_NAME
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return "missing", None
    except OSError:
        return "unreadable", None
    try:
        payload = json.loads(raw)
    except ValueError:
        return "unreadable", None
    if not isinstance(payload, dict):
        return "unreadable", None
    version = payload.get("format_version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        return "unreadable", None
    if version > MAX_SUPPORTED_FORMAT:
        return "newer", payload
    return "ok", payload


def manifest_state(project_dir: Path) -> ManifestState:
    """manifest를 이 앱이 다룰 수 있는가. newer와 unreadable이면 프로젝트를 열지 않는다."""
    state, payload = _read_manifest_payload(project_dir)
    if state == "ok":
        try:
            ProjectManifest.model_validate(payload)
        except ValidationError:
            return "unreadable"
    return state


def read_manifest(project_dir: Path) -> ProjectManifest | None:
    """다룰 수 있는 manifest만 돌려준다. 없거나 다룰 수 없으면 None."""
    state, payload = _read_manifest_payload(project_dir)
    if state != "ok":
        return None
    try:
        return ProjectManifest.model_validate(payload)
    except ValidationError:
        return None


def write_manifest(
    project_dir: Path, manifest: ProjectManifest, atomic_write: Callable[..., None]
) -> bool:
    """manifest를 원자적으로 쓴다. 디스크 내용과 같으면 쓰지 않고 False를 돌려준다."""
    data = manifest.model_dump_json(indent=2).encode("utf-8")
    path = project_dir / MANIFEST_NAME
    try:
        if path.read_bytes() == data:
            return False
    except OSError:
        pass
    atomic_write(project_dir, MANIFEST_NAME, data, prefix=".manifest-", suffix=".tmp")
    return True


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def reconcile(manifest: ProjectManifest | None, disk_format: int | None) -> ProjectManifest:
    """끊긴 이전 기록을 디스크의 덱 내용으로 마무리하고 형식 번호를 현재 덱에 맞춘다."""
    if manifest is None:
        manifest = ProjectManifest(format_version=disk_format or 1)
    pending = [r for r in manifest.migrations if r.status == "pending"]
    for record in pending:
        record.status = "done" if disk_format == record.to_format else "not_applied"
    if not pending and manifest.format_version == 2 and disk_format == 1:
        # 이 앱의 쓰기 없이 형식 1로 돌아왔다: 0.2.0의 저장이나 스냅샷 복원
        manifest.migrations.append(MigrationRecord(
            at=now_iso(), kind="external_downgrade", from_format=2, to_format=1,
        ))
    if disk_format is not None:
        manifest.format_version = disk_format
    manifest.written_by = __version__
    return manifest


def pre_migration_snapshot_ids(project_dir: Path) -> set[str]:
    """0.2.0으로 되돌릴 수 있는 이전 전 복사본. 완료된 upgrade 기록의 스냅샷만 해당한다."""
    manifest = read_manifest(project_dir)
    if manifest is None:
        return set()
    return {
        m.snapshot_id for m in manifest.migrations
        if m.kind == "upgrade" and m.status == "done" and m.snapshot_id
    }
