"""AI 생성 작업 원장 (개정판 D2b-1, 계획서 5.1~5.3과 5.6).

생성 작업의 실행 상태와 결과 후보를 자료 루트의 SQLite 파일에 남긴다. 문서의 정본은 프로젝트
파일이고, 원장은 생성 작업이 어디까지 갔는지와 결과를 기록한다. 재시작 뒤에도 결과와 실패가
남고, 원격 호출이 끝났는지 모르는 작업은 그 사실을 남긴다.

모든 상태 변경은 "기대한 현재 상태일 때만 갱신"(compare-and-set)이다. 종료 처리나 재시작 조정이
먼저 쓴 종결 상태를 늦게 깨어난 실행 코루틴이 덮지 못하게 하기 위해서다.
"""

import hashlib
import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, fields as dataclass_fields
from datetime import datetime
from pathlib import Path
from typing import Any

LEDGER_NAME = ".slidecaptain-jobs.sqlite3"  # 점으로 시작해 프로젝트 이름과 겹치지 않는다
LEDGER_FORMAT = 1  # PRAGMA user_version. 더 새 번호의 원장은 열지 않는다

# 계획서 5.3의 전이표. 기술 설계 6절 그림에 없는 전이는 계획서 「상위 문서와 다르게 정하는 것」 1항.
# 작업 행과 묶음 하위 행이 같은 표를 쓴다. 묶음 부모는 마지막 장이 끝나면 validating을 거쳐 종결한다
TRANSITIONS: dict[str, frozenset[str]] = {
    "queued": frozenset({"running", "failed", "cancelled", "interrupted"}),
    "running": frozenset({"validating", "failed", "cancel_requested", "interrupted", "remote_completion_unknown"}),
    "validating": frozenset({"succeeded", "failed"}),
    "cancel_requested": frozenset({"cancelled", "interrupted", "remote_completion_unknown"}),
    "succeeded": frozenset(),
    "failed": frozenset(),
    "cancelled": frozenset(),
    "interrupted": frozenset(),
    "remote_completion_unknown": frozenset(),
}
UNFINISHED = ("queued", "running", "validating", "cancel_requested")
CANDIDATE_STATUSES = ("none", "held", "applied", "stale", "dismissed")
ERROR_CLASSES = ("input", "ai_output", "connection", "base_changed", "cancelled", "ledger")


class LedgerUnavailable(Exception):
    """원장을 열 수 없다(손상, 더 새 형식, 권한). 서비스는 시작하고 생성 등록만 막는다."""

    code = "job_ledger_unavailable"


class TransitionRejected(Exception):
    """기대한 현재 상태가 아니거나 전이표 밖의 전이다."""


class RequestIdConflict(Exception):
    """같은 요청 ID로 다른 종류나 매개변수가 왔다."""

    code = "request_id_conflict"


@dataclass(frozen=True)
class FixedInputs:
    """등록 때 고정하는 입력 (계획서 5.4). D4의 계정 프로필, Effort, 동의 리비전은 빈 열로 둔다."""

    provider: str | None
    model: str | None
    selection_id: str | None
    base_etag: str | None
    sources_fingerprint: str | None
    relevance_hash: str | None


@dataclass(frozen=True)
class JobRow:
    id: str
    project: str
    kind: str
    request_id: str
    params_hash: str
    params: dict
    state: str
    attempts: int
    instance_id: str
    provider: str | None
    model: str | None
    selection_id: str | None
    base_etag: str | None
    sources_fingerprint: str | None
    relevance_hash: str | None
    remote_sent_at: str | None
    result: Any
    candidate_status: str
    error_class: str | None
    error_status: int | None
    error_detail: str | None
    error_code: str | None
    outcome: str | None
    account_profile: str | None
    effort: str | None
    consent_revision: str | None
    created_at: str
    started_at: str | None
    finished_at: str | None


@dataclass(frozen=True)
class ChapterRow:
    job_id: str
    chapter_id: str
    position: int
    state: str
    remote_sent_at: str | None
    result: Any
    candidate_status: str
    apply_target_etag: str | None
    applied_etag: str | None
    error_class: str | None
    error_status: int | None
    error_detail: str | None
    error_code: str | None


_JOB_COLUMNS = [f.name for f in dataclass_fields(JobRow)]
_CHAPTER_COLUMNS = [f.name for f in dataclass_fields(ChapterRow)]
# 상태 전이와 함께 바꿀 수 있는 열. 정체성과 고정 입력은 바꾸지 않는다
_JOB_MUTABLE = {"attempts", "remote_sent_at", "result", "candidate_status", "error_class", "error_status",
                "error_detail", "error_code", "outcome", "started_at", "finished_at"}
_CHAPTER_MUTABLE = {"remote_sent_at", "result", "candidate_status", "apply_target_etag", "applied_etag",
                    "error_class", "error_status", "error_detail", "error_code"}

_SCHEMA = """
CREATE TABLE jobs (
    id TEXT PRIMARY KEY,
    project TEXT NOT NULL,
    kind TEXT NOT NULL,
    request_id TEXT NOT NULL,
    params_hash TEXT NOT NULL,
    params TEXT NOT NULL,
    state TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    instance_id TEXT NOT NULL,
    provider TEXT, model TEXT, selection_id TEXT,
    base_etag TEXT, sources_fingerprint TEXT, relevance_hash TEXT,
    remote_sent_at TEXT,
    result TEXT,
    candidate_status TEXT NOT NULL DEFAULT 'none',
    error_class TEXT, error_status INTEGER, error_detail TEXT, error_code TEXT,
    outcome TEXT,
    account_profile TEXT, effort TEXT, consent_revision TEXT,
    created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT,
    UNIQUE (project, request_id)
);
CREATE TABLE job_chapters (
    job_id TEXT NOT NULL REFERENCES jobs(id),
    chapter_id TEXT NOT NULL,
    position INTEGER NOT NULL,
    state TEXT NOT NULL,
    remote_sent_at TEXT,
    result TEXT,
    candidate_status TEXT NOT NULL DEFAULT 'none',
    apply_target_etag TEXT, applied_etag TEXT,
    error_class TEXT, error_status INTEGER, error_detail TEXT, error_code TEXT,
    PRIMARY KEY (job_id, chapter_id)
);
CREATE INDEX jobs_by_project ON jobs(project, created_at);
"""


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def params_hash(kind: str, params: dict) -> str:
    canonical = json.dumps({"kind": kind, "params": params}, sort_keys=True, ensure_ascii=False,
                           separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class JobLedger:
    """연결 하나를 원장 전용 잠금으로 감싼다 (계획서 5.1). 잠금 순서는 프로젝트 잠금 다음 원장 잠금이다."""

    def __init__(self, conn: sqlite3.Connection, path: Path | None):
        conn.row_factory = sqlite3.Row
        self._conn = conn
        self._lock = threading.Lock()
        self.path = path

    @classmethod
    def open(cls, root: Path | str | None) -> "JobLedger":
        """자료 루트의 원장을 열거나 만든다. root가 None이면 메모리 원장이다."""
        path = None if root is None else Path(root) / LEDGER_NAME
        try:
            if path is not None:
                path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(":memory:" if path is None else str(path), check_same_thread=False,
                                   isolation_level=None)
        except (sqlite3.Error, OSError) as exc:
            raise LedgerUnavailable("작업 기록 파일을 열 수 없습니다.") from exc
        try:
            # 읽기만 하는 검사를 먼저 한다: 손상되었거나 더 새 형식이면 파일을 바꾸지 않고 멈춘다
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version > LEDGER_FORMAT:
                raise LedgerUnavailable("더 새 버전 앱이 만든 작업 기록입니다.")
            # 동기화 폴더에 있을 수 있어 WAL을 쓰지 않는다. 이 환경의 기본값과 같지만 명시한다
            conn.execute("PRAGMA journal_mode=DELETE")
            conn.execute("PRAGMA synchronous=FULL")
            if version == 0:
                tables = conn.execute("SELECT count(*) FROM sqlite_master").fetchone()[0]
                if tables:
                    raise LedgerUnavailable("형식 번호가 없는 작업 기록 파일입니다.")
                conn.executescript("BEGIN;" + _SCHEMA + f"PRAGMA user_version = {LEDGER_FORMAT};COMMIT;")
        except LedgerUnavailable:
            conn.close()
            raise
        except sqlite3.Error as exc:
            conn.close()
            raise LedgerUnavailable("작업 기록 파일을 읽을 수 없습니다.") from exc
        return cls(conn, path)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # 작업 행

    def create_job(self, *, project: str, kind: str, request_id: str, params: dict, instance_id: str,
                   inputs: FixedInputs, chapter_ids: list[str] | None = None) -> tuple[JobRow, bool]:
        """새 작업을 queued로 만든다. 같은 프로젝트와 요청 ID가 있으면 병합한다(종결 작업 포함).

        돌려주는 bool은 새로 만들었는지다. 같은 요청 ID에 종류나 매개변수가 다르면 RequestIdConflict.
        """
        digest = params_hash(kind, params)
        with self._lock, self._transaction():
            existing = self._conn.execute(
                "SELECT * FROM jobs WHERE project = ? AND request_id = ?", (project, request_id)).fetchone()
            if existing is not None:
                row = self._job_from(existing)
                if row.params_hash != digest:
                    raise RequestIdConflict("같은 요청 식별자로 다른 생성 요청이 왔습니다.")
                return row, False
            job_id = uuid.uuid4().hex
            self._conn.execute(
                "INSERT INTO jobs (id, project, kind, request_id, params_hash, params, state, instance_id,"
                " provider, model, selection_id, base_etag, sources_fingerprint, relevance_hash, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?, ?, ?, ?, ?, ?)",
                (job_id, project, kind, request_id, digest, json.dumps(params, ensure_ascii=False), instance_id,
                 inputs.provider, inputs.model, inputs.selection_id, inputs.base_etag,
                 inputs.sources_fingerprint, inputs.relevance_hash, _now()))
            for position, chapter_id in enumerate(chapter_ids or []):
                self._conn.execute(
                    "INSERT INTO job_chapters (job_id, chapter_id, position, state) VALUES (?, ?, ?, 'queued')",
                    (job_id, chapter_id, position))
            return self._get_job(job_id), True

    def get_job(self, job_id: str) -> JobRow | None:
        with self._lock:
            return self._get_job(job_id)

    def list_jobs(self, project: str) -> list[JobRow]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM jobs WHERE project = ? ORDER BY created_at DESC", (project,)).fetchall()
            return [self._job_from(r) for r in rows]

    def unfinished_from_other_instances(self, instance_id: str) -> list[JobRow]:
        with self._lock:
            marks = ",".join("?" for _ in UNFINISHED)
            rows = self._conn.execute(
                f"SELECT * FROM jobs WHERE instance_id != ? AND state IN ({marks}) ORDER BY created_at",
                (instance_id, *UNFINISHED)).fetchall()
            return [self._job_from(r) for r in rows]

    def transition(self, job_id: str, *, expected: str, new: str, **changes) -> JobRow:
        """expected 상태일 때만 new로 바꾸고 changes를 같은 변경에 쓴다."""
        self._check_edge(expected, new)
        values = self._encode(changes, _JOB_MUTABLE)
        if new not in UNFINISHED and "finished_at" not in values:
            values["finished_at"] = _now()
        if new == "running" and "started_at" not in values:
            values["started_at"] = _now()
        with self._lock, self._transaction():
            self._cas("jobs", "id = ?", (job_id,), expected, new, values)
            return self._get_job(job_id)

    def update_job(self, job_id: str, *, expected: str, **changes) -> JobRow:
        """상태는 그대로 두고 expected 상태일 때만 열을 바꾼다 (예: 후보 처분)."""
        values = self._encode(changes, _JOB_MUTABLE)
        with self._lock, self._transaction():
            self._cas("jobs", "id = ?", (job_id,), expected, expected, values)
            return self._get_job(job_id)

    # 묶음 하위 행

    def chapters(self, job_id: str) -> list[ChapterRow]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM job_chapters WHERE job_id = ? ORDER BY position", (job_id,)).fetchall()
            return [self._chapter_from(r) for r in rows]

    def transition_chapter(self, job_id: str, chapter_id: str, *, expected: str, new: str, **changes) -> ChapterRow:
        self._check_edge(expected, new)
        values = self._encode(changes, _CHAPTER_MUTABLE)
        with self._lock, self._transaction():
            self._cas("job_chapters", "job_id = ? AND chapter_id = ?", (job_id, chapter_id), expected, new, values)
            return self._get_chapter(job_id, chapter_id)

    def update_chapter(self, job_id: str, chapter_id: str, *, expected: str, **changes) -> ChapterRow:
        values = self._encode(changes, _CHAPTER_MUTABLE)
        with self._lock, self._transaction():
            self._cas("job_chapters", "job_id = ? AND chapter_id = ?", (job_id, chapter_id), expected, expected,
                      values)
            return self._get_chapter(job_id, chapter_id)

    # 내부

    @contextmanager
    def _transaction(self):
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self._conn.execute("ROLLBACK")
            raise
        self._conn.execute("COMMIT")

    @staticmethod
    def _check_edge(expected: str, new: str) -> None:
        if new not in TRANSITIONS.get(expected, ()):
            raise TransitionRejected(f"허용되지 않은 상태 전이입니다: {expected} -> {new}")

    @staticmethod
    def _encode(changes: dict, allowed: set[str]) -> dict:
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError(f"바꿀 수 없는 열입니다: {sorted(unknown)}")
        if changes.get("candidate_status", "none") not in CANDIDATE_STATUSES:
            raise ValueError(f"알 수 없는 후보 처분입니다: {changes['candidate_status']}")
        if changes.get("error_class") is not None and changes["error_class"] not in ERROR_CLASSES:
            raise ValueError(f"알 수 없는 원인 분류입니다: {changes['error_class']}")
        values = dict(changes)
        if "result" in values:
            values["result"] = None if values["result"] is None else json.dumps(values["result"], ensure_ascii=False)
        return values

    def _cas(self, table: str, where: str, key: tuple, expected: str, new: str, values: dict) -> None:
        sets = ["state = ?"] + [f"{name} = ?" for name in values]
        cursor = self._conn.execute(
            f"UPDATE {table} SET {', '.join(sets)} WHERE {where} AND state = ?",
            (new, *values.values(), *key, expected))
        if cursor.rowcount != 1:
            raise TransitionRejected(f"작업 상태가 {expected}가 아니어서 바꾸지 않았습니다.")

    def _get_job(self, job_id: str) -> JobRow | None:
        row = self._conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return None if row is None else self._job_from(row)

    def _get_chapter(self, job_id: str, chapter_id: str) -> ChapterRow:
        row = self._conn.execute(
            "SELECT * FROM job_chapters WHERE job_id = ? AND chapter_id = ?", (job_id, chapter_id)).fetchone()
        return self._chapter_from(row)

    @staticmethod
    def _job_from(row: sqlite3.Row) -> JobRow:
        data = dict(row)
        data["params"] = json.loads(data["params"])
        data["result"] = None if data["result"] is None else json.loads(data["result"])
        return JobRow(**{name: data[name] for name in _JOB_COLUMNS})

    @staticmethod
    def _chapter_from(row: sqlite3.Row) -> ChapterRow:
        data = dict(row)
        data["result"] = None if data["result"] is None else json.loads(data["result"])
        return ChapterRow(**{name: data[name] for name in _CHAPTER_COLUMNS})


# 재시작 판정 (계획서 5.6 표). 실행은 D2b-2(작업 행)와 D2b-4(묶음 적용 재개)가 한다

def reconcile_job(job: JobRow) -> str | None:
    """다른 인스턴스가 남긴 미종결 작업 행의 조정 결과. 종결 행은 None.

    "rejudge_candidate"는 원격 호출 없이 생성 뒤 판정을 다시 하라는 뜻이다. 묶음 부모는 하위 행을
    조정한 뒤 종결 상태를 계산하므로 이 함수를 쓰지 않는다.
    """
    if job.state == "queued":
        return "interrupted"
    if job.state in ("running", "cancel_requested"):
        return "remote_completion_unknown" if job.remote_sent_at else "interrupted"
    if job.state == "validating":
        return "rejudge_candidate"
    return None


def reconcile_chapter(chapter: ChapterRow, *, chain_etag: str | None, current_etag: str | None,
                      deck_slots: dict | None) -> str | None:
    """묶음 하위 행의 조정 결과.

    chain_etag는 사슬의 기대값(마지막으로 적용 결과 ETag가 기록된 하위 행, 없으면 부모의 기준 ETag),
    deck_slots는 지금 덱에서 그 장의 슬라이드 슬롯(없으면 None)이다.
    """
    if chapter.state == "queued":
        return "interrupted"
    if chapter.state in ("running", "cancel_requested"):
        return "remote_completion_unknown" if chapter.remote_sent_at else "interrupted"
    if chapter.state != "validating":
        return None
    if chapter.apply_target_etag is None:
        return "resume_apply"
    if current_etag == chapter.apply_target_etag:
        return "mark_applied"
    if current_etag == chain_etag:
        return "resume_apply"
    result_slots = (chapter.result or {}).get("slots")
    if deck_slots is not None and result_slots is not None and deck_slots == result_slots:
        return "mark_applied_changed"
    return "mark_stale"
