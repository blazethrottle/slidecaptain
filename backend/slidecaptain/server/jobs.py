"""AI 생성 작업 실행기 (개정판 D2b-2, 계획서 2.3, 5.4~5.6).

작업은 프로세스에 하나뿐인 전용 스레드의 이벤트 루프(작업 루프)에서 돈다. 요청 처리 루프는
결과만 기다린다. 그래서 요청 루프가 닫히거나 요청이 취소돼도 작업이 함께 취소되지 않고, 취소는
이 실행기의 `cancel`이 제공자 태스크에 한 번만 보낸다(SDK는 정리 중 두 번째 취소가 오면 CLI
프로세스를 남긴다. 계획서 사실 8).

작업 루프를 앱마다 만들지 않고 프로세스에 하나 두는 이유: 시험 스위트는 앱을 수백 번 만드는데,
앱마다 스레드와 이벤트 루프를 열면 파일 핸들이 쌓인다. 독립 앱과 웹 모드는 프로세스에 앱이 하나다.
"""

import asyncio
import logging
import threading
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel

from slidecaptain.storage.job_ledger import (
    BATCH_KIND,
    FixedInputs,
    JobLedger,
    LedgerError,
    JobRow,
    LedgerUnavailable,
    TRANSITIONS,
    RequestIdConflict,
    TransitionRejected,
    reconcile_job,
)

_LOG = logging.getLogger("slidecaptain.server.jobs")

GENERATION_ACTIVE_MESSAGE = "다른 AI 생성이 진행 중입니다. 끝난 뒤 다시 시도하거나 그 작업을 취소해 주세요."
SERVICE_STOPPING_MESSAGE = "앱이 종료되는 중이라 AI 생성을 시작하지 않았습니다."
JOB_CANCELLED_MESSAGE = "AI 생성이 취소되었습니다."
# 종료 처리가 실행 중 작업의 종료를 기다리는 시간. 서비스의 강제 종료 시간 10초(desktop_service의
# parent_lifeline)에서 uvicorn의 종료 대기 5초(timeout_graceful_shutdown)를 뺀 값이다 (계획서 5.5)
SHUTDOWN_WAIT_SECONDS = 5.0

_loop: asyncio.AbstractEventLoop | None = None
_loop_lock = threading.Lock()


def job_loop() -> asyncio.AbstractEventLoop:
    """프로세스에 하나뿐인 작업 루프. 처음 부를 때 데몬 스레드로 시작한다."""
    global _loop
    with _loop_lock:
        if _loop is None or _loop.is_closed():
            loop = asyncio.new_event_loop()
            threading.Thread(target=loop.run_forever, name="slidecaptain-jobs", daemon=True).start()
            _loop = loop
        return _loop


class JobFailed(Exception):
    """작업 안에서 난 실패를 지금 라우트와 같은 HTTP 응답으로 돌려준다 (계획서 5.4 오류 표현)."""

    def __init__(self, status: int, detail: str, code: str | None = None):
        super().__init__(detail)
        self.status, self.detail, self.code = status, detail, code


class GenerationActive(Exception):
    def __init__(self, active: dict):
        super().__init__(GENERATION_ACTIVE_MESSAGE)
        self.active = active


class ServiceStopping(Exception):
    code = "service_stopping"


Classifier = Callable[[BaseException], tuple[str, int, str, str | None]]


@dataclass
class JobSpec:
    """작업 하나의 실행 방법. 라우트가 등록 검사를 마친 뒤 만든다 (계획서 5.4)."""

    kind: str
    project: str
    request_id: str
    params: dict
    selection_id: str | None
    inputs: FixedInputs
    run: Callable[[Any], Awaitable[Any]]  # 생성 서비스를 받아 결과 모델을 돌려준다
    recheck: Callable[[], None] | None = None  # 임대 직후 고정 입력 재비교. 다르면 예외
    judge: Callable[[Any], list[str]] | None = None  # 결과 저장 뒤 판정. 비어 있으면 같다
    chapter_ids: list[str] | None = None


@dataclass
class Outcome:
    row: JobRow
    result: Any = None  # 메모리의 결과 모델. 없으면 None
    stale_reasons: list[str] = field(default_factory=list)


class JobHandle:
    """실행기 안의 작업 하나. 끝나면 Outcome을 모든 대기자에게 알린다."""

    def __init__(self, job_id: str, spec: JobSpec):
        self.job_id, self.spec = job_id, spec
        self.cancel_requested = False
        self.cancel_sent = False
        self.provider_task: asyncio.Task | None = None
        self.outcome: Outcome | None = None
        self._done = threading.Event()
        self._listeners: list[Callable[[Outcome], None]] = []
        self._lock = threading.Lock()

    @property
    def done(self) -> bool:
        return self._done.is_set()

    def _finish(self, outcome: Outcome) -> None:
        with self._lock:
            self.outcome = outcome
            self._done.set()
            listeners, self._listeners = self._listeners, []
        for notify in listeners:
            notify(outcome)

    async def wait(self) -> Outcome:
        """어느 이벤트 루프에서든 끝나기를 기다린다. 이 대기가 취소돼도 작업은 취소되지 않는다."""
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()

        def notify(outcome: Outcome) -> None:
            loop.call_soon_threadsafe(lambda: future.done() or future.set_result(outcome))

        with self._lock:
            if self.outcome is None:
                self._listeners.append(notify)
                outcome = None
            else:
                outcome = self.outcome
        if outcome is not None:
            return outcome
        return await future

    def wait_sync(self, timeout: float | None = None) -> Outcome | None:
        self._done.wait(timeout)
        return self.outcome


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def _encode(result: Any) -> Any:
    return result.model_dump(mode="json") if isinstance(result, BaseModel) else result


class JobRunner:
    """앱 하나의 작업 실행기. 실행 중 작업은 서비스 전체에서 하나다 (계획서 5.6)."""

    def __init__(self, *, ledger: JobLedger | None, ledger_error: LedgerUnavailable | None, instance_id: str,
                 acquire: Callable[[str | None], tuple[Any, Callable[[], None]]], classify: Classifier,
                 on_success: Callable[[JobSpec, Any], None]):
        self.ledger, self.ledger_error = ledger, ledger_error
        self.instance_id = instance_id
        self._acquire, self._classify, self._on_success = acquire, classify, on_success
        self._lock = threading.Lock()
        self._active: JobHandle | None = None
        self._handles: dict[str, JobHandle] = {}
        self._stopping = False

    # 등록과 조회

    def require_ledger(self) -> JobLedger:
        if self.ledger is None:
            raise self.ledger_error or LedgerUnavailable("작업 기록을 열 수 없습니다.")
        return self.ledger

    def start(self, spec: JobSpec) -> tuple[JobRow, JobHandle | None, bool]:
        """작업을 등록하고 실행을 시작한다. 같은 요청 ID는 병합한다(새로 만들지 않으면 created=False).

        실행 중 작업이 있으면 GenerationActive. 돌려주는 handle은 이 실행기에서 도는 작업일 때만 있다.
        """
        ledger = self.require_ledger()
        with self._lock:
            if self._stopping:
                raise ServiceStopping(SERVICE_STOPPING_MESSAGE)
            existing = ledger.find_job(spec.project, spec.request_id)
            if existing is None and self._active is not None:
                raise GenerationActive(self.active_summary_locked())
            row, created = ledger.create_job(
                project=spec.project, kind=spec.kind, request_id=spec.request_id, params=spec.params,
                instance_id=self.instance_id, inputs=spec.inputs, chapter_ids=spec.chapter_ids)
            if not created:
                return row, self._handles.get(row.id), False
            handle = JobHandle(row.id, spec)
            self._active = handle
            self._handles = {k: h for k, h in self._handles.items() if not h.done}
            self._handles[row.id] = handle
        asyncio.run_coroutine_threadsafe(self._execute(handle), job_loop())
        return row, handle, True

    def active_summary(self) -> dict | None:
        with self._lock:
            return self.active_summary_locked()

    def active_summary_locked(self) -> dict | None:
        if self._active is None or self.ledger is None:
            return None
        row = self.ledger.get_job(self._active.job_id)
        if row is None:
            return None
        return {"id": row.id, "project": row.project, "kind": row.kind, "state": row.state,
                "created_at": row.created_at, "started_at": row.started_at}

    def is_running(self, job_id: str) -> bool:
        with self._lock:
            return self._active is not None and self._active.job_id == job_id

    # 취소

    def cancel(self, job_id: str) -> JobRow | None:
        """취소를 요청한다. 제공자 태스크에는 한 번만 보낸다. 이 실행기의 작업이 아니면 상태만 돌려준다."""
        with self._lock:
            handle = self._handles.get(job_id)
        if handle is not None and not handle.done:
            done = threading.Event()

            def request() -> None:
                try:
                    self._request_cancel(handle)
                finally:
                    done.set()

            job_loop().call_soon_threadsafe(request)
            done.wait(5)
        return self.ledger.get_job(job_id) if self.ledger is not None else None

    def _request_cancel(self, handle: JobHandle) -> None:
        """작업 루프에서 실행된다."""
        handle.cancel_requested = True
        if handle.provider_task is None or handle.cancel_sent or handle.provider_task.done():
            return  # 임대 획득 중이면 획득이 끝난 뒤 실행 코루틴이 cancelled로 끝낸다
        try:
            self.ledger.transition(handle.job_id, expected="running", new="cancel_requested")
        except TransitionRejected:
            return
        handle.cancel_sent = True
        handle.provider_task.cancel()

    # 실행 (작업 루프)

    async def _execute(self, handle: JobHandle) -> None:
        ledger, spec, job_id = self.ledger, handle.spec, handle.job_id
        release: Callable[[], None] | None = None
        outcome: Outcome | None = None
        try:
            try:
                service, release = await asyncio.to_thread(self._acquire, spec.selection_id)
            except Exception as exc:
                outcome = Outcome(self._end(job_id, "queued", exc, cancelled=handle.cancel_requested))
                return
            if handle.cancel_requested:
                outcome = Outcome(self._end(job_id, "queued", None, cancelled=True))
                return
            if spec.recheck is not None:
                try:
                    await asyncio.to_thread(spec.recheck)
                except Exception as exc:
                    outcome = Outcome(self._end(job_id, "queued", exc))
                    return
            ledger.transition(job_id, expected="queued", new="running", remote_sent_at=_now(), attempts=1)
            handle.provider_task = asyncio.get_running_loop().create_task(spec.run(service))
            if handle.cancel_requested:
                self._request_cancel(handle)
            await asyncio.wait({handle.provider_task})
            outcome = await self._settle(handle)
        except TransitionRejected:
            # 종료 처리가 먼저 종결 상태를 썼다. 그 상태를 그대로 둔다
            outcome = Outcome(ledger.get_job(job_id))
        except Exception:
            _LOG.exception("AI 생성 작업 실행 중 예기치 않은 오류: %s", job_id)
            outcome = Outcome(self._fail_unexpected(job_id))
        finally:
            if release is not None:
                try:
                    release()  # 작업 루프의 동기 호출이라 요청 취소의 영향을 받지 않는다 (계획서 5.5)
                except Exception:
                    _LOG.exception("생성 임대를 놓지 못했습니다: %s", job_id)
            with self._lock:
                if self._active is handle:
                    self._active = None
            if outcome is None or outcome.row is None:
                try:
                    outcome = Outcome(ledger.get_job(job_id), outcome.result if outcome else None)
                except LedgerError:
                    outcome = Outcome(None, outcome.result if outcome else None)
            handle._finish(outcome)

    async def _settle(self, handle: JobHandle) -> Outcome:
        ledger, spec, task, job_id = self.ledger, handle.spec, handle.provider_task, handle.job_id
        if handle.cancel_sent:
            if task.cancelled():
                return Outcome(ledger.transition(job_id, expected="cancel_requested", new="cancelled",
                                                 error_class="cancelled"))
            if task.exception() is not None:
                error_class, status, detail, code = self._classify(task.exception())
                return Outcome(ledger.transition(job_id, expected="cancel_requested", new="cancelled",
                                                 error_class="cancelled", error_status=status,
                                                 error_detail=detail, error_code=code))
            # 취소 요청 뒤 값이 왔다(수리의 stopped, 늦은 응답). 남기되 적용하지 않는다
            return Outcome(ledger.transition(job_id, expected="cancel_requested", new="cancelled",
                                             result=_encode(task.result()), candidate_status="held",
                                             error_class="cancelled"))
        if task.cancelled():  # 실행기가 보내지 않은 취소. 원격 호출을 보냈으므로 완료 여부를 모른다
            return Outcome(ledger.transition(job_id, expected="running", new="remote_completion_unknown"))
        if task.exception() is not None:
            return Outcome(self._end(job_id, "running", task.exception()))
        result = task.result()
        reasons = await asyncio.to_thread(spec.judge, result) if spec.judge is not None else []
        try:
            ledger.transition(job_id, expected="running", new="validating", result=_encode(result),
                              candidate_status="stale" if reasons else "held")
        except LedgerError:
            # 결과를 원장에 쓰지 못했다. 래퍼는 메모리의 결과를 돌려준다 (계획서 5.1)
            _LOG.exception("생성 결과를 작업 원장에 쓰지 못했습니다: %s", job_id)
            if not reasons:
                self._on_success(spec, result)
            return Outcome(ledger.get_job(job_id), result, reasons)
        if getattr(result, "status", None) == "format_error":
            row = ledger.transition(job_id, expected="validating", new="failed", error_class="ai_output",
                                    error_code=getattr(result, "format_issue", None) or "format_error")
        else:
            row = ledger.transition(job_id, expected="validating", new="succeeded")
            if not reasons:
                self._on_success(spec, result)
        return Outcome(row, result, reasons)

    def _fail_unexpected(self, job_id: str) -> JobRow | None:
        try:
            row = self.ledger.get_job(job_id)
            if row is not None and "failed" in TRANSITIONS.get(row.state, ()):
                row = self.ledger.transition(job_id, expected=row.state, new="failed", error_class="input",
                                             error_status=500, error_detail="AI 생성 작업을 처리하지 못했습니다.")
            return row
        except (TransitionRejected, LedgerError):
            return None

    def _end(self, job_id: str, expected: str, exc: BaseException | None, cancelled: bool = False) -> JobRow:
        if cancelled:
            return self.ledger.transition(job_id, expected=expected, new="cancelled", error_class="cancelled")
        error_class, status, detail, code = self._classify(exc)
        return self.ledger.transition(job_id, expected=expected, new="failed", error_class=error_class,
                                      error_status=status, error_detail=detail, error_code=code)

    # 재시작 조정과 종료 (계획서 5.5, 5.6)

    def reconcile_on_start(self, lock_state: str) -> int:
        """잠금을 쥔 서비스만 다른 인스턴스의 미종결 작업을 조정한다. 조정한 행 수를 돌려준다."""
        if self.ledger is None or lock_state != "held":
            return 0
        count = 0
        for row in self.ledger.unfinished_from_other_instances(self.instance_id):
            if self._settle_left_over(row):
                count += 1
        return count

    def _settle_left_over(self, row: JobRow) -> bool:
        if row.kind == BATCH_KIND:
            return False  # 묶음은 하위 행 조정과 parent_outcome이 맡는다 (D2b-4)
        action = reconcile_job(row)
        try:
            if action in ("interrupted", "remote_completion_unknown"):
                self.ledger.transition(row.id, expected=row.state, new=action)
            elif action == "rejudge_candidate":
                # 결과가 원장에 있다. 다시 부르지 않고 종결한다. 낡음 판정은 조회 때 한다 (계획서 5.8)
                status = (row.result or {}).get("status")
                if status == "format_error":
                    self.ledger.transition(row.id, expected="validating", new="failed", error_class="ai_output",
                                           error_code=(row.result or {}).get("format_issue") or "format_error")
                else:
                    self.ledger.transition(row.id, expected="validating", new="succeeded")
            else:
                return False
        except (TransitionRejected, LedgerError):
            return False
        return True

    def shutdown(self, wait_seconds: float = SHUTDOWN_WAIT_SECONDS) -> None:
        """① 새 등록 거절 ② 실행 중 작업에 취소 한 번 ③ 기다림 ④ 남은 행 정리 (계획서 5.5)."""
        with self._lock:
            self._stopping = True
            handle = self._active
        if handle is not None and not handle.done:
            self.cancel(handle.job_id)
            handle.wait_sync(wait_seconds)
        if self.ledger is None:
            return
        try:
            rows = self.ledger.unfinished_of_instance(self.instance_id)
        except LedgerError:
            _LOG.exception("종료 처리에서 작업 원장을 읽지 못했습니다")
            return
        for row in rows:
            self._settle_left_over(row)


def new_request_id() -> str:
    return uuid.uuid4().hex


def http_error_from(row: JobRow) -> HTTPException | JobFailed:
    """종결된 작업 행의 오류를 래퍼 응답으로 바꾼다."""
    if row.state == "cancelled":
        return JobFailed(409, JOB_CANCELLED_MESSAGE, "job_cancelled")
    return JobFailed(row.error_status or 500, row.error_detail or "AI 생성 작업을 처리하지 못했습니다.", row.error_code)
