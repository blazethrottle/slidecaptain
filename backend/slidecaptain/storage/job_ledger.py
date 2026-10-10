"""AI 생성 작업 원장 (개정판 D2b-1, 계획서 5.1~5.3과 5.6).

생성 작업의 실행 상태와 결과 후보를 자료 루트의 SQLite 파일에 남긴다. 문서의 정본은 프로젝트
파일이고, 원장은 생성 작업이 어디까지 갔는지와 결과를 기록한다. 재시작 뒤에도 결과와 실패가
남고, 원격 호출이 끝났는지 모르는 작업은 그 사실을 남긴다.

모든 상태 변경은 "기대한 현재 상태일 때만 갱신"(compare-and-set)이다. 종료 처리나 재시작 조정이
먼저 쓴 종결 상태를 늦게 깨어난 실행 코루틴이 덮지 못하게 하기 위해서다. 종결 행은 후보 처분
(candidate_status)만 처분 전이표에 따라 바꿀 수 있다.
"""

import hashlib
import json
import sqlite3
import threading
import unicodedata
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, fields as dataclass_fields
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from slidecaptain.models.deck import Slots

LEDGER_NAME = ".slidecaptain-jobs.sqlite3"  # 점으로 시작해 프로젝트 이름과 겹치지 않는다
LEDGER_FORMAT = 1  # PRAGMA user_version. 더 새 번호의 원장은 열지 않는다
BATCH_KIND = "chapters"  # 장 생성 묶음 (D2b-4). 부모 행은 하위 행으로 종결 상태를 계산한다
KINDS = ("structure", "chapter", "condense", "diagram", "rewrite", "repair", BATCH_KIND)

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
STATES = tuple(TRANSITIONS)
# 묶음 부모의 종결 전이 (계획서 5.3의 α 묶음 리뷰 A3 정정). 부모는 미종결 어디서든 parent_outcome의 결과로 한 번에
# 종결한다. 장 적용 중 취소가 와도 모든 장이 적용됐으면 succeeded로 끝낼 수 있어야 하기 때문이다
PARENT_FINISH = {state: frozenset({"succeeded", "failed", "cancelled"})
                 for state in ("running", "validating", "cancel_requested")}
UNFINISHED = ("queued", "running", "validating", "cancel_requested")
# 후보 처분의 전이표 (계획서 5.8). 버린 후보와 반영한 후보는 되살리지 않는다. delivered는 래퍼가 응답으로
# 이미 화면에 돌려준 결과다. 화면은 delivered를 "이전에 만든 결과"로 다시 보이지 않는다 (D2b-2 리뷰 R8)
CANDIDATE_TRANSITIONS: dict[str, frozenset[str]] = {
    "none": frozenset({"held", "stale"}),
    "held": frozenset({"delivered", "applied", "dismissed", "stale"}),
    "delivered": frozenset({"applied", "dismissed"}),
    "stale": frozenset({"delivered", "dismissed"}),  # 래퍼가 낡은 결과를 200으로 돌려준 경우 (D2b-3 리뷰 R11)
    "applied": frozenset(),
    "dismissed": frozenset(),
}
CANDIDATE_STATUSES = tuple(CANDIDATE_TRANSITIONS)
# 원인 분류. 응답 모델 models/jobs.py의 ErrorClass와 같은 집합이어야 한다(시험이 확인한다). storage와 internal은
# D3a-4가 더했다. 읽기 관대화(9cdcd1c) 이후 빌드는 모르는 값을 internal로 읽는다. 그보다 앞선 빌드(D2b 빌드)가
# 같은 자료 폴더에서 이 값을 읽으면 작업 목록이 500이다(계획 9절 가정 1)
ERROR_CLASSES = ("input", "ai_output", "connection", "base_changed", "cancelled", "ledger", "storage", "internal")
OUTCOMES = ("all_applied", "partial", "chain_broken", "held_stale_plan", "cancelled")
# 묶음 하위 행의 중단 사유는 error_code에 둔다 (계획서 5.2)
HELD_STALE_PLAN = "held_stale_plan"
STALE_STORY_PLAN = "stale_story_plan"  # 구성 계획 낡음으로 실패한 장 자신의 오류 코드
CHAIN_BROKEN = "chain_broken"  # 장과 장 사이에 다른 저장이 덱을 바꿔 시작하지 않은 장의 사유 (D2b-4 리뷰 R11)

_SLOTS = TypeAdapter(Slots)


class LedgerUnavailable(Exception):
    """원장을 열 수 없다(손상, 더 새 형식, 권한). 서비스는 시작하고 생성 등록만 막는다."""

    code = "job_ledger_unavailable"


class LedgerError(Exception):
    """연 뒤의 원장 읽기나 쓰기가 실패했다(잠금 대기 초과, 디스크, 손상). 원인은 __cause__에 남는다."""

    code = "ledger_write_failed"


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
    attempts: int
    remote_sent_at: str | None
    result: Any
    candidate_status: str
    apply_target_etag: str | None
    applied_etag: str | None
    error_class: str | None
    error_status: int | None
    error_detail: str | None
    error_code: str | None
    started_at: str | None
    finished_at: str | None


_JOB_COLUMNS = [f.name for f in dataclass_fields(JobRow)]
_CHAPTER_COLUMNS = [f.name for f in dataclass_fields(ChapterRow)]
# 상태 전이와 함께 바꿀 수 있는 열. 정체성과 고정 입력은 바꾸지 않는다
_JOB_MUTABLE = {"attempts", "remote_sent_at", "result", "candidate_status", "error_class", "error_status",
                "error_detail", "error_code", "outcome", "started_at", "finished_at"}
_CHAPTER_MUTABLE = {"attempts", "remote_sent_at", "result", "candidate_status", "apply_target_etag", "applied_etag",
                    "error_class", "error_status", "error_detail", "error_code", "started_at", "finished_at"}

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
    attempts INTEGER NOT NULL DEFAULT 0,
    remote_sent_at TEXT,
    result TEXT,
    candidate_status TEXT NOT NULL DEFAULT 'none',
    apply_target_etag TEXT, applied_etag TEXT,
    error_class TEXT, error_status INTEGER, error_detail TEXT, error_code TEXT,
    started_at TEXT, finished_at TEXT,
    PRIMARY KEY (job_id, chapter_id)
);
CREATE INDEX jobs_by_project ON jobs(project);
"""
_REQUIRED_COLUMNS = {"jobs": set(_JOB_COLUMNS) | {"params_hash"}, "job_chapters": set(_CHAPTER_COLUMNS)}


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def _nfc(name: str) -> str:
    # 저장소가 폴더 이름을 NFC로 맞추므로 원장의 프로젝트 키도 NFC로 둔다 (D2b-1 리뷰 R19)
    return unicodedata.normalize("NFC", name)


def params_hash(kind: str, params: dict) -> str:
    canonical = json.dumps({"kind": kind, "params": params}, sort_keys=True, ensure_ascii=False,
                           separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class JobLedger:
    """연결 하나를 원장 전용 잠금으로 감싼다 (계획서 5.1). 잠금 순서는 프로젝트 잠금 다음 원장 잠금이다."""

    def __init__(self, conn: sqlite3.Connection, path: Path | None):
        conn.row_factory = sqlite3.Row
        self._conn = conn
        self._lock = threading.RLock()  # batch() 안에서 같은 스레드의 메서드가 다시 잡는다
        self.path = path

    @classmethod
    def open(cls, root: Path | str | None) -> "JobLedger":
        """자료 루트의 원장을 열거나 만든다. root가 None이면 메모리 원장이다.

        손상, 더 새 형식, 다른 구조, 쓰기 불가는 파일을 바꾸기 전에 LedgerUnavailable로 거절한다.
        """
        path = None if root is None else Path(root) / LEDGER_NAME
        try:
            if path is not None:
                path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(":memory:" if path is None else str(path), check_same_thread=False,
                                   isolation_level=None)
        except (sqlite3.Error, OSError) as exc:
            raise LedgerUnavailable("작업 기록 파일을 열 수 없습니다.") from exc
        try:
            # 읽기만 하는 검사를 먼저 한다 (리뷰 R4: journal_mode 변경은 WAL 파일의 머리를 바꾼다)
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version > LEDGER_FORMAT:
                raise LedgerUnavailable("더 새 버전 앱이 만든 작업 기록입니다.")
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            if version == 0 and tables:
                raise LedgerUnavailable("형식 번호가 없는 작업 기록 파일입니다.")
            if version == LEDGER_FORMAT:
                for table, required in _REQUIRED_COLUMNS.items():
                    columns = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
                    if not required <= columns:
                        raise LedgerUnavailable("작업 기록 파일의 구조가 이 앱과 다릅니다.")
                if conn.execute("PRAGMA quick_check").fetchone()[0] != "ok":  # 리뷰 R3: 중간 페이지 손상
                    raise LedgerUnavailable("작업 기록 파일이 손상되었습니다.")
            # 쓰기 가능 여부를 확인한다 (리뷰 R2: 읽기 전용 파일과 폴더). BEGIN IMMEDIATE만으로는 읽기 전용
            # 파일에서도 성공하므로 같은 형식 번호를 실제로 쓴 뒤 되돌린다. 파일 내용은 바뀌지 않는다
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute(f"PRAGMA user_version = {version}")
            finally:
                conn.execute("ROLLBACK")
            # 동기화 폴더에 있을 수 있어 WAL을 쓰지 않는다. 이 환경의 기본값과 같지만 명시한다
            conn.execute("PRAGMA journal_mode=DELETE")
            conn.execute("PRAGMA synchronous=FULL")
            if version == 0:
                conn.executescript("BEGIN;" + _SCHEMA + f"PRAGMA user_version = {LEDGER_FORMAT};COMMIT;")
        except LedgerUnavailable:
            conn.close()
            raise
        except sqlite3.Error as exc:
            conn.close()
            raise LedgerUnavailable("작업 기록 파일을 읽거나 쓸 수 없습니다.") from exc
        return cls(conn, path)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @contextmanager
    def batch(self):
        """여러 compare-and-set을 한 트랜잭션으로 묶는다. 하나라도 거절되면 모두 되돌린다 (리뷰 R15)."""
        with self._lock, self._transaction():
            yield self

    # 작업 행

    def create_job(self, *, project: str, kind: str, request_id: str, params: dict, instance_id: str,
                   inputs: FixedInputs, chapter_ids: list[str] | None = None) -> tuple[JobRow, bool]:
        """새 작업을 queued로 만든다. 같은 프로젝트와 요청 ID가 있으면 병합한다(종결 작업 포함).

        돌려주는 bool은 새로 만들었는지다. 같은 요청 ID에 종류나 매개변수가 다르면 RequestIdConflict.
        묶음의 하위 행은 params["chapter_ids"]와 같은 chapter_ids로만 만든다 (리뷰 R22).
        """
        if kind not in KINDS:
            raise ValueError(f"알 수 없는 작업 종류입니다: {kind}")
        if (kind == BATCH_KIND) != (chapter_ids is not None):
            raise ValueError("장 목록은 묶음 작업에만 둔다")
        if chapter_ids is not None:
            if list(params.get("chapter_ids", [])) != list(chapter_ids) or len(set(chapter_ids)) != len(chapter_ids):
                raise ValueError("묶음의 장 목록이 매개변수와 다르거나 중복이 있습니다")
            if not inputs.base_etag:
                raise ValueError("묶음 작업에는 기준 ETag가 필요합니다")  # 리뷰 R8: 사슬 기대값 None 금지
        project = _nfc(project)
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
        with self._lock, self._reading():
            return self._get_job(job_id)

    def find_job(self, project: str, request_id: str) -> JobRow | None:
        with self._lock, self._reading():
            row = self._conn.execute("SELECT * FROM jobs WHERE project = ? AND request_id = ?",
                                     (_nfc(project), request_id)).fetchone()
            return None if row is None else self._job_from(row)

    def list_jobs(self, project: str) -> list[JobRow]:
        """최근 등록 순. 순서는 시각 문자열이 아니라 등록 순번(rowid)이다 (리뷰 R13)."""
        with self._lock, self._reading():
            rows = self._conn.execute(
                "SELECT * FROM jobs WHERE project = ? ORDER BY rowid DESC", (_nfc(project),)).fetchall()
            return [self._job_from(r) for r in rows]

    def unfinished_from_other_instances(self, instance_id: str) -> list[JobRow]:
        """다른 인스턴스의 작업 가운데 자신이나 하위 행이 미종결인 것 (리뷰 R15)."""
        return self._unfinished("instance_id != ?", instance_id)

    def unfinished_of_instance(self, instance_id: str) -> list[JobRow]:
        return self._unfinished("instance_id = ?", instance_id)

    def _unfinished(self, where: str, instance_id: str) -> list[JobRow]:
        marks = ",".join("?" for _ in UNFINISHED)
        with self._lock, self._reading():
            rows = self._conn.execute(
                f"SELECT * FROM jobs WHERE {where} AND (state IN ({marks}) OR EXISTS ("
                f"SELECT 1 FROM job_chapters c WHERE c.job_id = jobs.id AND c.state IN ({marks})))"
                " ORDER BY rowid", (instance_id, *UNFINISHED, *UNFINISHED)).fetchall()
            return [self._job_from(r) for r in rows]

    def transition(self, job_id: str, *, expected: str, new: str, **changes) -> JobRow:
        """expected 상태일 때만 new로 바꾸고 changes를 같은 변경에 쓴다."""
        values = self._prepare(expected, new, changes, _JOB_MUTABLE)
        with self._lock, self._transaction():
            self._cas("jobs", "id = ?", (job_id,), expected, new, values)
            return self._get_job(job_id)

    def finish_parent(self, job_id: str, *, expected: str, new: str, outcome: str) -> JobRow:
        """묶음 부모를 parent_outcome의 결과로 종결한다. 부모 전용 전이표를 쓴다 (계획서 5.3, A3)."""
        if new not in PARENT_FINISH.get(expected, ()):
            raise TransitionRejected(f"묶음 부모를 {expected}에서 {new}로 끝낼 수 없습니다")
        values = self._encode({"outcome": outcome, "finished_at": _now()}, _JOB_MUTABLE)
        with self._lock, self._transaction():
            row = self._get_job(job_id)
            if row is None or row.kind != BATCH_KIND:
                raise TransitionRejected("묶음 작업이 아닙니다")
            if self._conn.execute("SELECT count(*) FROM job_chapters WHERE job_id = ? AND state IN (?, ?, ?, ?)",
                                  (job_id, *UNFINISHED)).fetchone()[0]:
                raise TransitionRejected("미종결 장이 남아 있어 묶음을 끝낼 수 없습니다")
            sets = ", ".join(f"{name} = ?" for name in values)
            cursor = self._conn.execute(f"UPDATE jobs SET state = ?, {sets} WHERE id = ? AND state = ?",
                                        (new, *values.values(), job_id, expected))
            if cursor.rowcount != 1:
                raise TransitionRejected(f"작업 상태가 {expected}가 아니어서 바꾸지 않았습니다.")
            return self._get_job(job_id)

    def update_job(self, job_id: str, *, expected: str, **changes) -> JobRow:
        """미종결 행의 열만 바꾼다(상태 유지). 종결 행은 settle_candidate만 쓴다 (리뷰 R10)."""
        values = self._prepare_update(expected, changes, _JOB_MUTABLE)
        with self._lock, self._transaction():
            self._cas("jobs", "id = ?", (job_id,), expected, expected, values)
            return self._get_job(job_id)

    def settle_candidate(self, job_id: str, *, expected: str, new: str) -> JobRow:
        """후보 처분을 처분 전이표에 따라 compare-and-set으로 바꾼다 (계획서 5.8, 리뷰 R10)."""
        self._check_candidate(expected, new)
        with self._lock, self._transaction():
            self._cas_candidate("jobs", "id = ?", (job_id,), expected, new)
            return self._get_job(job_id)

    # 묶음 하위 행

    def chapters(self, job_id: str) -> list[ChapterRow]:
        with self._lock, self._reading():
            rows = self._conn.execute(
                "SELECT * FROM job_chapters WHERE job_id = ? ORDER BY position", (job_id,)).fetchall()
            return [self._chapter_from(r) for r in rows]

    def transition_chapter(self, job_id: str, chapter_id: str, *, expected: str, new: str, **changes) -> ChapterRow:
        values = self._prepare(expected, new, changes, _CHAPTER_MUTABLE)
        with self._lock, self._transaction():
            self._cas("job_chapters", "job_id = ? AND chapter_id = ?", (job_id, chapter_id), expected, new, values)
            return self._get_chapter(job_id, chapter_id)

    def update_chapter(self, job_id: str, chapter_id: str, *, expected: str, **changes) -> ChapterRow:
        values = self._prepare_update(expected, changes, _CHAPTER_MUTABLE)
        with self._lock, self._transaction():
            self._cas("job_chapters", "job_id = ? AND chapter_id = ?", (job_id, chapter_id), expected, expected,
                      values)
            return self._get_chapter(job_id, chapter_id)

    def settle_chapter_candidate(self, job_id: str, chapter_id: str, *, expected: str, new: str) -> ChapterRow:
        self._check_candidate(expected, new)
        with self._lock, self._transaction():
            self._cas_candidate("job_chapters", "job_id = ? AND chapter_id = ?", (job_id, chapter_id), expected, new)
            return self._get_chapter(job_id, chapter_id)

    # 내부

    @contextmanager
    def _transaction(self):
        """BEGIN IMMEDIATE에서 COMMIT까지. COMMIT 실패도 되돌린다 (리뷰 R1). batch() 안에서는 중첩하지 않는다."""
        if self._conn.in_transaction:
            yield
            return
        try:
            self._conn.execute("BEGIN IMMEDIATE")
        except sqlite3.Error as exc:
            raise LedgerError("작업 기록을 쓰지 못했습니다.") from exc
        try:
            yield
            self._conn.execute("COMMIT")
        except BaseException as exc:
            if self._conn.in_transaction:  # SQLite가 이미 되돌린 경우 ROLLBACK이 원인을 가린다 (리뷰 R12)
                try:
                    self._conn.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
            if isinstance(exc, sqlite3.Error):
                raise LedgerError("작업 기록을 쓰지 못했습니다.") from exc
            raise

    @contextmanager
    def _reading(self):
        try:
            yield
        except sqlite3.Error as exc:
            raise LedgerError("작업 기록을 읽지 못했습니다.") from exc

    @staticmethod
    def _check_candidate(expected: str, new: str) -> None:
        if new not in CANDIDATE_TRANSITIONS.get(expected, ()):
            raise TransitionRejected(f"허용되지 않은 후보 처분입니다: {expected} -> {new}")

    @classmethod
    def _prepare(cls, expected: str, new: str, changes: dict, allowed: set[str]) -> dict:
        if new not in TRANSITIONS.get(expected, ()):
            raise TransitionRejected(f"허용되지 않은 상태 전이입니다: {expected} -> {new}")
        values = cls._encode(changes, allowed)
        if new not in UNFINISHED and values.get("finished_at") is None:
            values["finished_at"] = _now()  # 리뷰 R20: None을 넘겨도 종결 시각을 채운다
        if new == "running" and values.get("started_at") is None:
            values["started_at"] = _now()
        return values

    @classmethod
    def _prepare_update(cls, expected: str, changes: dict, allowed: set[str]) -> dict:
        if expected not in UNFINISHED:
            raise TransitionRejected("종결된 작업의 기록은 바꾸지 않습니다. 후보 처분은 settle_candidate를 씁니다.")
        if "candidate_status" in changes:
            raise ValueError("후보 처분은 settle_candidate로 바꾼다")
        return cls._encode(changes, allowed)

    @staticmethod
    def _encode(changes: dict, allowed: set[str]) -> dict:
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError(f"바꿀 수 없는 열입니다: {sorted(unknown)}")
        if changes.get("candidate_status", "none") not in CANDIDATE_STATUSES:
            raise ValueError(f"알 수 없는 후보 처분입니다: {changes['candidate_status']}")
        if changes.get("error_class") is not None and changes["error_class"] not in ERROR_CLASSES:
            raise ValueError(f"알 수 없는 원인 분류입니다: {changes['error_class']}")
        if changes.get("outcome") is not None and changes["outcome"] not in OUTCOMES:
            raise ValueError(f"알 수 없는 묶음 결과입니다: {changes['outcome']}")
        values = dict(changes)
        if "result" in values:
            values["result"] = None if values["result"] is None else json.dumps(values["result"], ensure_ascii=False)
        return values

    def _cas(self, table: str, where: str, key: tuple, expected: str, new: str, values: dict) -> None:
        sets = ["state = ?"] + [f"{name} = ?" for name in values]
        # 리뷰 R11: 같은 출발 상태에서 원격 호출 시각으로 도착 상태를 가르는 조건을 원장이 강제한다
        condition = ""
        if new == "interrupted" and expected in ("running", "cancel_requested"):
            condition = " AND remote_sent_at IS NULL"
        elif new == "remote_completion_unknown":
            condition = " AND remote_sent_at IS NOT NULL"
        cursor = self._conn.execute(
            f"UPDATE {table} SET {', '.join(sets)} WHERE {where} AND state = ?{condition}",
            (new, *values.values(), *key, expected))
        if cursor.rowcount != 1:
            raise TransitionRejected(f"작업 상태가 {expected}가 아니거나 조건이 맞지 않아 바꾸지 않았습니다.")

    def _cas_candidate(self, table: str, where: str, key: tuple, expected: str, new: str) -> None:
        cursor = self._conn.execute(
            f"UPDATE {table} SET candidate_status = ? WHERE {where} AND candidate_status = ?", (new, *key, expected))
        if cursor.rowcount != 1:
            raise TransitionRejected(f"후보 처분이 {expected}가 아니어서 바꾸지 않았습니다.")

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
    """다른 인스턴스가 남긴 작업 행의 조정 결과. 종결 행은 None.

    "rejudge_candidate"는 원격 호출 없이 생성 뒤 판정을 다시 하라는 뜻이다. 묶음 부모는
    "reconcile_children"이다: 하위 행을 reconcile_chapter로 조정한 뒤 parent_outcome으로 종결한다 (리뷰 R6).
    """
    if job.kind == BATCH_KIND:
        return "reconcile_children" if job.state in UNFINISHED else None
    if job.state == "queued":
        return "interrupted"
    if job.state in ("running", "cancel_requested"):
        return "remote_completion_unknown" if job.remote_sent_at else "interrupted"
    if job.state == "validating":
        return "rejudge_candidate"
    return None


def _normalized_slots(value: Any) -> dict:
    return _SLOTS.dump_python(_SLOTS.validate_python(value), mode="json")


def reconcile_chapter(chapter: ChapterRow, *, chain_etag: str, current_etag: str | None,
                      deck_slots: Any) -> str | None:
    """묶음 하위 행의 조정 결과.

    chain_etag는 사슬의 기대값(마지막으로 적용 결과 ETag가 기록된 하위 행, 없으면 부모의 기준 ETag),
    current_etag는 지금 덱 ETag(읽을 수 없으면 None), deck_slots는 지금 덱에서 그 장의 슬롯(없으면 None,
    dict나 슬롯 모델)이다.
    """
    if not chain_etag:
        raise ValueError("사슬 기대값이 없습니다")  # 리뷰 R8: None == None으로 적용 재개가 되지 않게 한다
    if chapter.state == "queued":
        return "interrupted"
    if chapter.state in ("running", "cancel_requested"):
        return "remote_completion_unknown" if chapter.remote_sent_at else "interrupted"
    if chapter.state != "validating":
        return None
    result = chapter.result
    if not isinstance(result, dict):
        raise TypeError("하위 행의 결과는 dict여야 한다")
    if result.get("status") != "ok" or not result.get("slots"):
        return "mark_format_failed"  # 리뷰 R7: 형식 판정 전에 끊긴 형식 오류 결과
    if current_etag is None:
        return "defer_unknown"  # 리뷰 R8: 덱을 읽을 수 없으면 판정을 미루고 다음 시작에서 다시 본다
    if chapter.apply_target_etag is None:
        return "resume_apply"
    if current_etag == chapter.apply_target_etag:
        return "mark_applied"
    if current_etag == chain_etag:
        return "resume_apply"
    if deck_slots is not None and _normalized_slots(deck_slots) == _normalized_slots(result["slots"]):
        return "mark_applied_changed"
    return "mark_stale"


def parent_outcome(chapters: list[ChapterRow], parent_state: str | None = None) -> tuple[str, str]:
    """묶음 부모의 종결 상태와 outcome을 하위 행에서 계산한다 (계획서 5.3, D2b-1 리뷰 R9, α 묶음 리뷰 A3).

    정상 종결과 재시작 조정이 같은 함수를 쓴다. 하위 행은 모두 종결되어 있어야 한다. 부모가 취소 요청을
    받았으면 모든 장이 적용된 경우만 succeeded이고 그 밖에는 cancelled다("취소 후 닫기" 뒤 재시작도 같다).
    """
    if any(c.state in UNFINISHED for c in chapters):
        raise ValueError("미종결 하위 행이 있어 묶음 결과를 계산할 수 없습니다")
    if chapters and all(c.state == "succeeded" for c in chapters):
        return "succeeded", "all_applied"
    if parent_state == "cancel_requested":
        return "cancelled", "cancelled"
    if any(c.state == "cancelled" for c in chapters):
        return "cancelled", "cancelled"
    # 낡음이 마지막 장에서 나면 남은 장이 없어 보류 사유가 없다. 그 장 자신의 코드도 본다 (D2b-4 리뷰 R7)
    if any(c.error_code in (HELD_STALE_PLAN, STALE_STORY_PLAN) for c in chapters):
        return "failed", "held_stale_plan"
    if any(c.candidate_status == "stale" or c.error_code == CHAIN_BROKEN for c in chapters):
        return "failed", "chain_broken"
    return "failed", "partial"  # 형식 오류, 제공자 오류, 완료 여부 불명, 사유 없는 중단
