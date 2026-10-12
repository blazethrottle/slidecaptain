"""프로젝트 형식 판정과 기록 (개정판 D2a-1, D3b-1).

형식 번호는 덱 내용 등급이다(models/report_purpose.py): 1은 0.2.0이 읽는 덱, 2는 개정판 중간
빌드(D2a~D3a)까지 읽는 덱, 3은 D3b 이후만 읽는 덱이다. 판정은 manifest가 아니라 덱 내용으로 한다. 배포된 0.2.0은 manifest를 모른 채 deck.json만 다시 쓰므로(저장, 스냅샷 복원)
manifest만 믿으면 두 파일이 어긋난다. manifest는 판정 결과의 기록이며, 쓰기 때마다 덱 내용으로
다시 계산해 바로잡는다. 앱 버전은 판정에 쓰지 않고 진단용으로만 남긴다.

이 앱이 이해할 수 없는 manifest(형식 번호가 더 크거나 정수가 아니거나 JSON이 깨진 것)는
덮어쓰지 않는다. 그 프로젝트는 열지 않는다(file_store의 공통 진입이 거절한다). 이해할 수 있는
manifest라도 모르는 필드와 모르는 기록 종류는 그대로 보존한다.

Deck.schema_version은 등급 3이면 2, 아니면 1이다(models/deck.py). 0.2.0은 필드 검증이 끝난 뒤에야
버전을 검사하므로 새 보고 유형 덱의 표시는 버전과 관계없다(2026-10-08 실측). 3종 유형에 새 항목만 더한
덱은 필드 검증을 통과하고 버전 검사에서 막힌다. 등급 3에서는 manifest 형식 번호 3이 중간 빌드를 막는
유일한 장치이므로, 등급이 3으로 오르는 저장은 manifest를 먼저 올린다(file_store, 재리뷰 RR6).
"""

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Callable, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from slidecaptain import __version__
from slidecaptain.models.report_purpose import LEGACY_REPORT_TYPES, level_of

MANIFEST_NAME = "manifest.json"
FORMAT_NAME = "slidecaptain-project"
MAX_SUPPORTED_FORMAT = 3
# 덱 스키마에서 보고 유형 열거가 쓰이는 위치. 판정 함수는 이 두 곳을 모두 본다.
# test_project_format이 스키마를 훑어 이 목록과 실제 위치가 같은지 확인한다.
REPORT_TYPE_LOCATIONS = frozenset({("DeckMeta", "report_type"), ("ReportBrief", "report_type")})
# 덱 스키마, 유형별 추가 입력 칸 표, 길이 상한을 함께 해시한 SHA-256 (D3b-1, 재리뷰 RR7). 바뀌면
# test_project_format이 실패해 형식 판정과 manifest 형식 번호를 다시 검토하게 한다 (모르는 필드를 버리는
# 이전 앱이 새 필드를 경고 없이 지우지 않게, 이전 빌드가 읽지 못하는 덱을 복원으로 덮지 않게).
PINNED_DECK_SCHEMA_SHA256 = "1fff1564f5ba9b2de8f822d2a13b9e01422ed71240c309a519f7ddca46347725"

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
    # 이 앱이 마지막으로 쓴 deck.json의 ETag (D3b-1). 디스크 덱이 이 값과 다르면 다른 앱이 바꾼 것이다:
    # 등급 1에서 오르는 저장의 강제 스냅샷 생략 판정(재리뷰 RR2)과 되돌림 표시(RR3)가 쓴다
    last_written_etag: str | None = None


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


def deck_format(deck) -> int:
    """덱 내용 등급(1, 2, 3)."""
    from slidecaptain.models.report_purpose import deck_level

    return deck_level(deck)


def deck_format_of_bytes(data: bytes) -> int | None:
    """디스크 deck.json 바이트의 등급. 덱으로 읽을 수 없으면 None.

    0.2.0이 쓴 덱도 판정해야 하므로 현재 모델로 검증하지 않는다. 이 앱은 등급 3 덱을 schema_version 2로
    쓰고 새 항목은 기본값이면 키가 없으므로, 버전 하나와 보고 유형으로 모델 판정과 같은 답을 낸다(리뷰 S6).
    """
    try:
        payload = json.loads(data)
    except ValueError:
        return None
    values = _report_types_of_payload(payload)
    if values is None:
        return None
    version = payload.get("schema_version", 1)
    return level_of(values, isinstance(version, int) and not isinstance(version, bool) and version >= 2)


def legacy_readable(data: bytes) -> bool:
    """0.2.0이 이 바이트를 덱으로 열 수 있는가. 이전 전 복사본 표시의 조건이다.

    현재 모델의 검증을 통과하고 등급이 1이면 0.2.0도 연다(등급 1에는 새 유형도 새 항목도 없다).
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


def reconcile(
    manifest: ProjectManifest | None, disk_format: int | None, revert_snapshot_id: str | None = None,
) -> ProjectManifest:
    """끊긴 이전 기록을 디스크의 덱 내용으로 마무리하고 형식 번호를 현재 덱에 맞춘다.

    revert_snapshot_id: 등급 3에서 다른 앱이 되돌렸을 때 되돌리기 직전 덱의 스냅샷(호출자가 찾는다).
    """
    if manifest is None:
        manifest = ProjectManifest(format_version=disk_format or 1)
    pending = [r for r in manifest.migrations if r.status == "pending"]
    for record in pending:
        record.status = "done" if disk_format == record.to_format else "not_applied"
    if not pending and disk_format is not None and manifest.format_version > disk_format:
        # 이 앱의 쓰기 없이 등급이 내려왔다: 0.2.0의 저장이나 스냅샷 복원 (D3b-1에서 등급 3까지 일반화)
        manifest.migrations.append(MigrationRecord(
            at=now_iso(), kind="external_downgrade", from_format=manifest.format_version, to_format=disk_format,
            snapshot_id=revert_snapshot_id if manifest.format_version == 3 else None,
        ))
    if disk_format is not None:
        manifest.format_version = disk_format
    manifest.written_by = __version__
    return manifest


def pre_migration_snapshot_ids(project_dir: Path) -> set[str]:
    """0.2.0으로 되돌릴 수 있는 이전 전 복사본. 등급 1에서 오른 완료 upgrade 기록의 스냅샷만 해당한다
    (2에서 3으로 오른 기록의 스냅샷은 0.2.0이 읽지 못한다, 재리뷰 RR8)."""
    manifest = read_manifest(project_dir)
    if manifest is None:
        return set()
    return {
        m.snapshot_id for m in manifest.migrations
        if m.kind == "upgrade" and m.status == "done" and m.snapshot_id and m.from_format == 1
    }


def find_revert_snapshot(project_dir: Path, manifest: ProjectManifest | None) -> str | None:
    """다른 앱이 등급 3 덱을 되돌렸을 때 되돌리기 직전 덱의 스냅샷 (재리뷰 RR3).

    0.2.0의 복원은 디스크 바이트를 그대로 복사해 스냅샷으로 남긴다. 그래서 이 앱이 마지막으로 쓴 덱과
    바이트가 같은 등급 3 스냅샷을 찾는다. 0.2.0이 복원 뒤 한 번 더 저장해 다른 스냅샷이 끼어도 찾고,
    등급 2 덱이 되돌려진 경우에는 오래된 등급 3 스냅샷을 고르지 않는다(바이트가 다르다).
    """
    if manifest is None or manifest.format_version != 3 or not manifest.last_written_etag:
        return None
    if any(r.status == "pending" for r in manifest.migrations):
        return None
    deck_path = project_dir / "deck.json"
    try:
        disk = deck_format_of_bytes(deck_path.read_bytes())
    except OSError:
        return None
    if disk is None or disk >= 3:
        return None
    for path in sorted((project_dir / "snapshots").glob("deck-*.json"), reverse=True):
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if hashlib.sha256(data).hexdigest() == manifest.last_written_etag and deck_format_of_bytes(data) == 3:
            return path.stem
    return None


def revert_snapshot_ids(project_dir: Path) -> set[str]:
    """"0.2.0에서 되돌리기 전"으로 표시할 스냅샷. 쓰기 때 남긴 기록과, 아직 쓰기가 없을 때의 읽기 전용 감지."""
    manifest = read_manifest(project_dir)
    if manifest is None:
        return set()
    ids = {
        m.snapshot_id for m in manifest.migrations
        if m.kind == "external_downgrade" and m.from_format == 3 and m.snapshot_id
    }
    found = find_revert_snapshot(project_dir, manifest)
    if found:
        ids.add(found)
    return ids
