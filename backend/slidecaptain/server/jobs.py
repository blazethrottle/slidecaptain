"""AI 생성 작업 실행기 (개정판 D2b-2, 계획서 2.3, 5.4~5.6).

작업은 프로세스에 하나뿐인 전용 스레드의 이벤트 루프(작업 루프)에서 돈다. 요청 처리 루프는
결과만 기다린다. 그래서 요청 루프가 닫히거나 요청이 취소돼도 작업이 함께 취소되지 않고, 취소는
이 실행기의 `cancel`이 제공자 태스크에 한 번만 보낸다(SDK는 정리 중 두 번째 취소가 오면 CLI
프로세스를 남긴다. 계획서 사실 8).

작업 루프를 앱마다 만들지 않고 프로세스에 하나 두는 이유: 시험 스위트는 앱을 수백 번 만드는데,
앱마다 스레드와 이벤트 루프를 열면 파일 핸들이 쌓인다. 독립 앱과 웹 모드는 프로세스에 앱이 하나다.
루프는 멈추지 않는다. 앱의 종료 처리는 실행기의 `shutdown`이다.
"""

import asyncio
import logging
import threading
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from slidecaptain.storage.job_ledger import (
    BATCH_KIND,
    TRANSITIONS,
    FixedInputs,
    JobLedger,
    JobRow,
    LedgerError,
    LedgerUnavailable,
    TransitionRejected,
    reconcile_job,
)

_LOG = logging.getLogger("slidecaptain.server.jobs")

# 화면에 작업 취소 수단이 생기는 D2b-5a 전까지는 취소 안내를 넣지 않는다 (α 묶음 리뷰 A12)
GENERATION_ACTIVE_MESSAGE = "다른 AI 생성이 진행 중입니다. 끝난 뒤 다시 시도해 주세요."
SERVICE_STOPPING_MESSAGE = "앱이 종료되는 중이라 AI 생성을 시작하지 않았습니다."
JOB_CANCELLED_MESSAGE = "AI 생성이 취소되었습니다."
JOB_INTERRUPTED_MESSAGE = "AI 생성이 중단되었습니다. 완료 여부를 확인할 수 없으면 결과를 다시 생성해 주세요."
LEDGER_WRITE_MESSAGE = "작업 기록을 쓰지 못했습니다. 잠시 뒤 다시 시도해 주세요."
FORMAT_ERROR_MESSAGE = "AI 응답을 형식에 맞게 읽지 못했습니다. 입력은 그대로 두었습니다. 다시 생성해 주세요."
# 생성 뒤 판정의 이유 가운데 낡음으로 굳히지 않는 것. unknown*은 덱이나 자료를 읽지 못한 판정 불가(D2b-2
# 리뷰 R3), deck_changed_elsewhere는 장 재생성과 축약에서 다른 장이 바뀐 것을 알리기만 하는 이유(계획서 5.8)
NOTICE_REASONS = frozenset({"deck_changed_elsewhere"})
# 종료 처리가 실행 중 작업의 종료를 기다리는 시간. 서비스의 강제 종료 시간 10초(desktop_service의
# parent_lifeline)에서 uvicorn의 종료 대기 5초(timeout_graceful_shutdown)를 뺀 값이다 (계획서 5.5)
SHUTDOWN_WAIT_SECONDS = 5.0
# 취소 라우트가 작업 루프의 처리를 기다리는 시간. 루프의 콜백은 상태 쓰기와 task.cancel()뿐이라 짧다.
# 넘기면 기다리지 않고 지금 상태를 돌려준다(로그를 남긴다)
CANCEL_ACK_SECONDS = 5.0

_loop: asyncio.AbstractEventLoop | None = None
_loop_thread: threading.Thread | None = None
_loop_lock = threading.Lock()


def job_loop() -> asyncio.AbstractEventLoop:
    """프로세스에 하나뿐인 작업 루프. 처음 부를 때 데몬 스레드로 시작한다."""
    global _loop, _loop_thread
    with _loop_lock:
        if _loop is None or _loop.is_closed():
            loop = asyncio.new_event_loop()
            thread = threading.Thread(target=loop.run_forever, name="slidecaptain-jobs", daemon=True)
            thread.start()
            _loop, _loop_thread = loop, thread
        return _loop


def _on_job_loop() -> bool:
    return _loop_thread is not None and threading.current_thread() is _loop_thread


class JobFailed(Exception):
    """작업 안에서 난 실패를 지금 라우트와 같은 HTTP 응답으로 돌려준다 (계획서 5.4 오류 표현)."""

    def __init__(self, status: int, detail: str, code: str | None = None, error_class: str | None = None):
        super().__init__(detail)
        self.status, self.detail, self.code = status, detail, code
        # 응답 문구와 코드는 종전 라우트와 같게 두고 원장의 원인 분류만 따로 정할 때 쓴다
        self.error_class = error_class


class GenerationActive(Exception):
    def __init__(self, active: dict):
        super().__init__(GENERATION_ACTIVE_MESSAGE)
        self.active = active


class ServiceStopping(Exception):
    code = "service_stopping"


Classifier = Callable[[BaseException], tuple[str, int, str, str | None]]


@dataclass
class JobContext:
    """실행 중인 작업이 자기 취소 요청을 읽는 통로 (구성 수리의 cancelled 콜백, D2b-3)."""

    handle: "JobHandle"

    @property
    def cancel_requested(self) -> bool:
        return self.handle.cancel_requested


@dataclass
class JobSpec:
    """작업 하나의 실행 방법. 라우트가 등록 검사를 마친 뒤 만든다 (계획서 5.4)."""

    kind: str
    project: str
    request_id: str
    params: dict
    selection_id: str | None
    inputs: FixedInputs
    run: Callable[[Any, JobContext], Awaitable[Any]]  # 생성 서비스와 문맥을 받아 결과 모델을 돌려준다
    recheck: Callable[[], None] | None = None  # 임대 직후 고정 입력 재비교. 다르면 예외
    judge: Callable[[Any], list[str]] | None = None  # 결과 저장 뒤 판정. 비어 있으면 같다
    target: str | None = None  # 대상(장 ID, 도식 장). 진행 중 작업 요약에 쓴다
    chapter_ids: list[str] | None = None
    # 판정 뒤, 원장에 쓰기 전에 결과를 마무리한다(수리의 stopped). 원장과 응답의 결과가 같아진다 (D2b-3 리뷰 R8)
    finalize: Callable[[Any, list[str]], Any] | None = None


@dataclass
class Outcome:
    row: JobRow | None
    result: Any = None  # 메모리의 결과 모델. 없으면 None
    stale_reasons: list[str] = field(default_factory=list)


class JobHandle:
    """실행기 안의 작업 하나. 끝나면 Outcome을 모든 대기자에게 알린다."""

    def __init__(self, job_id: str, spec: JobSpec):
        self.job_id, self.spec = job_id, spec
        self.cancel_requested = False
        self.cancel_sent = False
        self.sent = False  # 제공자를 실제로 불렀는가. 원격 호출 시각은 이때 남긴다 (D2b-3 리뷰 R6)
        self.stage = "queued"  # 메모리의 단계. 진행 중 작업 요약에 쓴다 (α 묶음 리뷰 A7)
        self.created_at = _now()
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
            try:
                notify(outcome)
            except Exception:  # 한 대기자의 실패가 다른 대기자의 알림을 막지 않는다 (D2b-2 리뷰 R5)
                _LOG.exception("작업 대기자에게 결과를 알리지 못했습니다: %s", self.job_id)

    async def wait(self) -> Outcome:
        """어느 이벤트 루프에서든 끝나기를 기다린다. 이 대기가 취소돼도 작업은 취소되지 않는다."""
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()

        def notify(outcome: Outcome) -> None:
            try:
                loop.call_soon_threadsafe(lambda: future.done() or future.set_result(outcome))
            except RuntimeError:  # 대기자의 루프가 이미 닫혔다
                pass

        with self._lock:
            outcome = self.outcome
            if outcome is None:
                self._listeners.append(notify)
        if outcome is not None:
            return outcome
        try:
            return await future
        finally:
            with self._lock:
                if notify in self._listeners:
                    self._listeners.remove(notify)

    def wait_sync(self, timeout: float | None = None) -> Outcome | None:
        self._done.wait(timeout)
        return self.outcome


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def _encode(result: Any) -> Any:
    return result.model_dump(mode="json") if isinstance(result, BaseModel) else result


def _clean(reasons: list[str]) -> bool:
    """성공 시각을 기록해도 되는가: 알림 외의 판정 이유가 없다. 판정 불가도 종전 라우트처럼 기록하지 않는다."""
    return not [r for r in reasons if r not in NOTICE_REASONS]


def real_reasons(reasons: list[str]) -> list[str]:
    """판정 이유 가운데 관련 입력이 실제로 달라진 것만. 판정 불가는 조회 때 다시 본다 (계획서 5.8)."""
    return [r for r in reasons if not r.startswith("unknown") and r not in NOTICE_REASONS]


class JobRunner:
    """앱 하나의 작업 실행기. 실행 중 작업은 서비스 전체에서 하나다 (계획서 5.6)."""

    def __init__(self, *, ledger: JobLedger | None, ledger_error: LedgerUnavailable | None, instance_id: str,
                 acquire: Callable[[str | None, Callable[[], None]], tuple[Any, Callable[[], None]]],
                 classify: Classifier,
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
                raise GenerationActive(self._summary(self._active))
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

    def is_busy(self) -> bool:
        """실행 중 작업이 있는가. 원장을 읽지 않는다 (D2b-2 리뷰 R17)."""
        with self._lock:
            return self._active is not None

    def active_summary(self) -> dict | None:
        with self._lock:
            return None if self._active is None else self._summary(self._active)

    def _summary(self, handle: JobHandle) -> dict:
        """메모리의 정보로 만든다. 원장을 읽지 않으므로 원장 문제로 실패하지 않는다."""
        spec = handle.spec
        return {"id": handle.job_id, "project": spec.project, "kind": spec.kind, "target": spec.target,
                "stage": "cancel_requested" if handle.cancel_requested else handle.stage,
                "created_at": handle.created_at, "cancel_requested": handle.cancel_requested}

    def cancel_requested(self, job_id: str) -> bool:
        with self._lock:
            handle = self._handles.get(job_id)
        return handle is not None and handle.cancel_requested and not handle.done

    # 취소

    def cancel(self, job_id: str, *, wait_seconds: float = CANCEL_ACK_SECONDS) -> JobRow | None:
        """취소를 요청한다. 제공자 태스크에는 한 번만 보낸다. 이 실행기의 작업이 아니면 상태만 돌려준다."""
        with self._lock:
            handle = self._handles.get(job_id)
        if handle is not None and not handle.done:
            if _on_job_loop():
                self._request_cancel(handle)  # 작업 루프 안에서 기다리면 루프가 멈춘다 (D2b-2 리뷰 R7)
            else:
                acknowledged = threading.Event()

                def request() -> None:
                    try:
                        self._request_cancel(handle)
                    finally:
                        acknowledged.set()

                job_loop().call_soon_threadsafe(request)
                if not acknowledged.wait(wait_seconds):
                    _LOG.warning("작업 루프가 취소 요청을 %.1f초 안에 처리하지 못했습니다: %s", wait_seconds, job_id)
        return self.ledger.get_job(job_id) if self.ledger is not None else None

    def _request_cancel(self, handle: JobHandle) -> None:
        """작업 루프에서 실행된다."""
        handle.cancel_requested = True
        if handle.provider_task is None or handle.cancel_sent or handle.provider_task.done():
            return  # 임대 획득이나 재비교 중이면 실행 코루틴이 queued에서 cancelled로 끝낸다
        try:
            self.ledger.transition(handle.job_id, expected="running", new="cancel_requested")
        except (TransitionRejected, LedgerError):
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
                service, release = await asyncio.to_thread(self._acquire, spec.selection_id,
                                                           lambda: self._mark_sent(handle))
            except Exception as exc:
                outcome = Outcome(self._end(job_id, "queued", exc, cancelled=handle.cancel_requested))
                return
            if spec.recheck is not None and not handle.cancel_requested:
                try:
                    await asyncio.to_thread(spec.recheck)
                except Exception as exc:
                    outcome = Outcome(self._end(job_id, "queued", exc, cancelled=handle.cancel_requested))
                    return
            # 획득이나 재비교 중 들어온 취소는 원격 호출 전이다 (D2b-2 리뷰 R4)
            if handle.cancel_requested:
                outcome = Outcome(self._end(job_id, "queued", None, cancelled=True))
                return
            ledger.transition(job_id, expected="queued", new="running", attempts=1)
            handle.stage = "running"
            handle.provider_task = asyncio.get_running_loop().create_task(spec.run(service, JobContext(handle)))
            await asyncio.wait({handle.provider_task})
            outcome = await self._settle(handle)
        except TransitionRejected:
            # 종료 처리가 먼저 종결 상태를 썼다. 그 상태를 두되 메모리 결과는 대기자에게 넘긴다 (리뷰 R18)
            outcome = Outcome(self._read(job_id), self._memory_result(handle))
        except LedgerError:
            _LOG.exception("AI 생성 작업의 원장 쓰기가 실패했습니다: %s", job_id)
            outcome = self._ledger_failed(handle)
        except Exception:
            _LOG.exception("AI 생성 작업 실행 중 예기치 않은 오류: %s", job_id)
            outcome = Outcome(self._fail(job_id, "input", 500, "AI 생성 작업을 처리하지 못했습니다.", None))
        finally:
            if release is not None:
                try:
                    release()  # 작업 루프의 동기 호출이라 요청 취소의 영향을 받지 않는다 (계획서 5.5)
                except Exception:
                    _LOG.exception("생성 임대를 놓지 못했습니다: %s", job_id)
            with self._lock:
                if self._active is handle:
                    self._active = None
            if outcome is None:
                outcome = Outcome(self._read(job_id), self._memory_result(handle))
            handle._finish(outcome)

    def _mark_sent(self, handle: JobHandle) -> None:
        """제공자 호출 직전에 작업 루프에서 불린다. 첫 호출 때만 원격 호출 시각을 남긴다.

        시각을 남기지 못하면 호출하지 않는다. 남기지 못한 채 호출하고 프로세스가 죽으면 재시작 조정이 실제
        호출을 "중단"으로 잘못 분류한다 (α 묶음 리뷰 A13).
        """
        if handle.sent:
            return
        try:
            row = self.ledger.get_job(handle.job_id)
            if row is not None and row.remote_sent_at is None:
                self.ledger.update_job(handle.job_id, expected=row.state, remote_sent_at=_now())
        except TransitionRejected as exc:
            raise LedgerError("원격 호출 시각을 남기지 못했습니다.") from exc
        handle.sent = True

    @staticmethod
    def _memory_result(handle: JobHandle) -> Any:
        task = handle.provider_task
        if task is None or not task.done() or task.cancelled() or task.exception() is not None:
            return None
        return task.result()

    def _read(self, job_id: str) -> JobRow | None:
        try:
            return self.ledger.get_job(job_id)
        except LedgerError:
            return None

    def _ledger_failed(self, handle: JobHandle, result: Any = None, reasons: list[str] | None = None) -> Outcome:
        """원장 쓰기가 실패했다. failed(ledger)를 시도하고 메모리 결과와 판정은 대기자에게 넘긴다.

        판정을 넘겨야 래퍼가 기준 변경을 종전처럼 412/409로 돌려준다 (계획서 5.1, D2b-2 리뷰 R2, D2b-3 리뷰 R9).
        """
        row = self._fail(handle.job_id, "ledger", 503, LEDGER_WRITE_MESSAGE, "ledger_write_failed")
        if result is None:
            result = self._memory_result(handle)
        reasons = reasons or []
        if result is not None and getattr(result, "status", None) == "ok" and _clean(reasons):
            self._on_success(handle.spec, result)
        return Outcome(row, result, reasons)

    def _fail(self, job_id: str, error_class: str, status: int, detail: str, code: str | None) -> JobRow | None:
        row = self._read(job_id)
        if row is None or "failed" not in TRANSITIONS.get(row.state, ()):
            return row
        try:
            return self.ledger.transition(job_id, expected=row.state, new="failed", error_class=error_class,
                                          error_status=status, error_detail=detail, error_code=code)
        except (TransitionRejected, LedgerError):
            return self._read(job_id)

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
                                             error_class="cancelled"), task.result())
        if task.cancelled():  # 실행기가 보내지 않은 취소. 호출을 보냈으면 완료 여부를 모른다
            new = "remote_completion_unknown" if handle.sent else "interrupted"
            return Outcome(ledger.transition(job_id, expected="running", new=new))
        if isinstance(task.exception(), LedgerError):  # 원격 호출 시각을 남기지 못해 호출하지 않았다
            return self._ledger_failed(handle)
        if task.exception() is not None:
            return Outcome(self._end(job_id, "running", task.exception()))
        result = task.result()
        reasons = await asyncio.to_thread(spec.judge, result) if spec.judge is not None else []
        if spec.finalize is not None:
            result = spec.finalize(result, reasons)
        changed = real_reasons(reasons)
        format_error = getattr(result, "status", None) == "format_error"
        # 형식 오류 결과는 원문을 남기되 후보로 보이지 않는다 (리뷰 R11). 낡음은 실제로 달라졌을 때만 (리뷰 R3)
        candidate = "none" if format_error else ("stale" if changed else "held")
        try:
            ledger.transition(job_id, expected="running", new="validating", result=_encode(result),
                              candidate_status=candidate)
            if format_error:
                row = ledger.transition(job_id, expected="validating", new="failed", error_class="ai_output",
                                        error_detail=FORMAT_ERROR_MESSAGE,
                                        error_code=getattr(result, "format_issue", None) or "format_error")
            else:
                row = ledger.transition(job_id, expected="validating", new="succeeded")
        except LedgerError:
            _LOG.exception("생성 결과를 작업 원장에 쓰지 못했습니다: %s", job_id)
            return self._ledger_failed(handle, result, reasons)
        if not format_error and _clean(reasons):
            self._on_success(spec, result)
        return Outcome(row, result, reasons)

    def _end(self, job_id: str, expected: str, exc: BaseException | None, cancelled: bool = False) -> JobRow:
        if cancelled:
            return self.ledger.transition(job_id, expected=expected, new="cancelled", error_class="cancelled")
        error_class, status, detail, code = self._classify(exc)
        return self.ledger.transition(job_id, expected=expected, new="failed", error_class=error_class,
                                      error_status=status, error_detail=detail, error_code=code)

    def mark_delivered(self, job_id: str) -> None:
        """래퍼가 결과를 실제로 응답으로 돌려줄 때만 부른다. 화면은 이 결과를 "이전에 만든 결과"로 다시 보이지
        않는다. 낡은 결과를 200으로 돌려준 경우도 같다 (D2b-3 리뷰 R1, R11)."""
        for expected in ("held", "stale"):
            try:
                self.ledger.settle_candidate(job_id, expected=expected, new="delivered")
                return
            except TransitionRejected:
                continue
            except LedgerError:
                return  # 원장 문제는 응답을 막지 않는다

    # 재시작 조정과 종료 (계획서 5.5, 5.6)

    def reconcile_on_start(self, lock_state: str) -> int:
        """잠금을 쥔 서비스만 다른 인스턴스의 미종결 작업을 조정한다. 조정한 행 수를 돌려준다."""
        if self.ledger is None or lock_state != "held":
            return 0
        try:
            rows = self.ledger.unfinished_from_other_instances(self.instance_id)
        except LedgerError:
            _LOG.exception("재시작 조정에서 작업 원장을 읽지 못했습니다")
            return 0
        return sum(1 for row in rows if self._settle_left_over(row))

    def _settle_left_over(self, row: JobRow) -> bool:
        if row.kind == BATCH_KIND:
            return False  # 묶음은 하위 행 조정과 parent_outcome이 맡는다 (D2b-4)
        action = reconcile_job(row)
        try:
            if action in ("interrupted", "remote_completion_unknown"):
                self.ledger.transition(row.id, expected=row.state, new=action)
            elif action == "rejudge_candidate":
                # 결과가 원장에 있다. 다시 부르지 않고 종결한다. 낡음 판정은 조회 때 한다 (계획서 5.8)
                result = row.result or {}
                if result.get("status") == "format_error":
                    self.ledger.transition(row.id, expected="validating", new="failed", error_class="ai_output",
                                           error_detail=FORMAT_ERROR_MESSAGE,
                                           error_code=result.get("format_issue") or "format_error")
                else:
                    self.ledger.transition(row.id, expected="validating", new="succeeded")
            else:
                return False
        except (TransitionRejected, LedgerError):
            return False
        return True

    def close(self) -> None:
        """원장 파일을 닫는다. 종료 처리 뒤에 부른다. Windows는 열린 파일을 지우지 못한다(임시 폴더 정리)."""
        with self._lock:
            self._stopping = True
        if self.ledger is not None:
            self.ledger.close()

    def shutdown(self, wait_seconds: float = SHUTDOWN_WAIT_SECONDS) -> None:
        """① 새 등록 거절 ② 실행 중 작업에 취소 한 번 ③ 남은 예산만큼 기다림 ④ 남은 행 정리 (계획서 5.5).

        예산은 시작 시각부터 센다. 취소 요청의 처리 대기도 예산에 포함한다 (D2b-2 리뷰 R14).
        """
        deadline = time.monotonic() + wait_seconds
        with self._lock:
            self._stopping = True
            handle = self._active
        if handle is not None and not handle.done:
            self.cancel(handle.job_id, wait_seconds=max(0.0, deadline - time.monotonic()))
            handle.wait_sync(max(0.0, deadline - time.monotonic()))
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


def http_error_from(row: JobRow | None) -> JobFailed:
    """종결된 작업 행의 오류를 래퍼 응답으로 바꾼다."""
    if row is None:
        return JobFailed(503, LEDGER_WRITE_MESSAGE, "ledger_write_failed")
    if row.state == "cancelled":
        return JobFailed(409, JOB_CANCELLED_MESSAGE, "job_cancelled")
    if row.state in ("interrupted", "remote_completion_unknown"):
        return JobFailed(503, JOB_INTERRUPTED_MESSAGE, "job_interrupted")
    return JobFailed(row.error_status or 500, row.error_detail or "AI 생성 작업을 처리하지 못했습니다.", row.error_code)
