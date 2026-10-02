"""Budgeted, candidate-only repair and independent re-review orchestration.

This does not grant AI consent, save a Deck, or approve submission. Entrypoints
must supply the user's current authorization and revision checks.
"""

import asyncio
import copy
import math
import time
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Literal

from slidecaptain.pipeline.provider import AIProvider, ProviderError


class BudgetStopped(ProviderError):
    pass


def _decimal(value):
    if isinstance(value, bool):
        raise ValueError("비용 상한은 0 이상의 실제 수치여야 합니다.")
    try:
        amount = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("잘못된 비용입니다.") from exc
    if not amount.is_finite() or amount < 0:
        raise ValueError("비용은 0 이상의 유한한 수치여야 합니다.")
    return amount


@dataclass
class RepairBudget:
    max_calls: int
    max_rounds: int
    reserved_review_calls: int = 0
    deadline_monotonic: float | None = None
    max_cost_usd: str | None = None
    calls: int = field(default=0, init=False)
    review_calls: int = field(default=0, init=False)
    rounds: int = field(default=0, init=False)
    known_cost: Decimal = field(default=Decimal(0), init=False)
    unmeasured_calls: int = field(default=0, init=False)
    pending_cost: Decimal = field(default=Decimal(0), init=False)
    pending_calls: int = field(default=0, init=False)
    completed_review_calls: int = field(default=0, init=False)

    def __post_init__(self):
        for n in (self.max_calls, self.max_rounds, self.reserved_review_calls):
            if type(n) is not int or n < 0:
                raise ValueError("호출/회차/검수 예약 한도는 0 이상의 정수여야 합니다.")
        if self.reserved_review_calls > self.max_calls:
            raise ValueError("검수 예약 호출은 전체 호출 상한을 넘을 수 없습니다.")
        if self.deadline_monotonic is not None and (isinstance(self.deadline_monotonic, bool) or
                not math.isfinite(self.deadline_monotonic)):
            raise ValueError("실행 마감은 유한한 시간이어야 합니다.")
        if self.max_cost_usd is not None:
            _decimal(self.max_cost_usd)

    def reserve(self, purpose, upper_cost):
        if self.calls >= self.max_calls:
            raise BudgetStopped("승인된 호출 상한에 도달했습니다. 초안을 보존합니다.")
        if purpose == "repair" and self.max_calls - self.calls <= max(0, self.reserved_review_calls - self.review_calls):
            raise BudgetStopped("독립 검수에 예약한 호출을 수정에 사용할 수 없습니다.")
        if self.max_cost_usd is not None:
            if self.unmeasured_calls or upper_cost is None:
                raise BudgetStopped("비용이 미계측이어서 비용 상한 이내의 다음 호출을 확인할 수 없습니다.")
            if self.known_cost + self.pending_cost + _decimal(upper_cost) > _decimal(self.max_cost_usd):
                raise BudgetStopped("다음 호출의 비용 예약이 승인된 비용 상한을 넘습니다.")
            self.pending_cost += _decimal(upper_cost)
        self.calls += 1  # Failed calls and schema retries consume the same ceiling.
        self.pending_calls += 1
        if purpose == "review":
            self.review_calls += 1

    def record(self, usage, upper_cost=None):
        self.pending_calls -= 1
        if self.max_cost_usd is not None and upper_cost is not None:
            self.pending_cost -= _decimal(upper_cost)
        if usage is None or usage.cost_usd is None:
            self.unmeasured_calls += 1
        else:
            try:
                self.known_cost += _decimal(usage.cost_usd)
            except ValueError:
                self.unmeasured_calls += 1

    def summary(self):
        return {"calls": self.calls, "review_calls": self.review_calls, "rounds": self.rounds,
                "cost_usd": None if self.unmeasured_calls or self.pending_calls else str(self.known_cost),
                "unmeasured_calls": self.unmeasured_calls, "pending_calls": self.pending_calls,
                "completed_review_calls": self.completed_review_calls}


class BudgetedProvider:
    def __init__(self, provider: AIProvider, budget: RepairBudget, *, purpose: Literal["repair", "review"],
                 cancelled: Callable[[], bool] = lambda: False,
                 unchanged: Callable[[], bool] = lambda: True,
                 upper_call_cost_usd: str | None = None):
        if purpose not in ("repair", "review"):
            raise ValueError("수정 또는 검수 호출만 지원합니다.")
        self.provider, self.budget, self.purpose = provider, budget, purpose
        self.cancelled, self.unchanged, self.upper_cost = cancelled, unchanged, upper_call_cost_usd
        self.closed = False
        self.active_tasks = set()

    def guard(self):
        if self.closed:
            raise BudgetStopped("이 수정 작업은 종료됐습니다. 늦은 추가 호출을 실행하지 않습니다.")
        if self.cancelled():
            raise BudgetStopped("작업이 취소됐습니다. 기존 초안을 보존합니다.")
        if not self.unchanged():
            raise BudgetStopped("기준 자료나 저장본이 바뀌었습니다. 후보를 적용하지 않습니다.")
        if self.budget.deadline_monotonic is not None and time.monotonic() >= self.budget.deadline_monotonic:
            raise BudgetStopped("승인된 실행 시간이 끝났습니다. 초안을 보존합니다.")

    async def complete(self, prompt, schema):
        self.guard()
        self.budget.reserve(self.purpose, self.upper_cost)
        current_task = asyncio.current_task()
        self.active_tasks.add(current_task)
        try:
            call = self.provider.complete(prompt, schema)
            if self.budget.deadline_monotonic is None:
                response = await call
            else:
                response = await asyncio.wait_for(call, max(0, self.budget.deadline_monotonic - time.monotonic()))
        except BaseException as exc:
            self.budget.record(getattr(exc, "usage", None), self.upper_cost)
            self.active_tasks.discard(current_task)
            if isinstance(exc, TimeoutError):
                raise BudgetStopped("승인된 실행 시간이 끝났습니다. 초안을 보존합니다.") from exc
            raise
        self.budget.record(response.usage, self.upper_cost)
        self.active_tasks.discard(current_task)
        if self.budget.max_cost_usd is not None:
            cost = getattr(response.usage, "cost_usd", None)
            if cost is None or self.budget.unmeasured_calls:
                raise BudgetStopped("실제 비용이 미계측입니다. 비용 상한을 확인할 때까지 후보를 승인하지 않습니다.")
            if _decimal(cost) > _decimal(self.upper_cost) or self.budget.known_cost > _decimal(self.budget.max_cost_usd):
                raise BudgetStopped("제공자의 실제 비용이 예약 상한을 넘었습니다. 사용량은 기록하고 추가 호출을 중단합니다.")
        self.guard()
        if self.purpose == "review":
            self.budget.completed_review_calls += 1
        return response


@dataclass
class RepairResult:
    status: Literal["needs_revision", "reviewed_candidate", "stopped"]
    original: Any
    candidate: Any
    findings: list[dict]
    budget: dict
    reason: str | None = None
    submission_approved: Literal[False] = False


class RepairCoordinator:
    def __init__(self, repair_provider: AIProvider, review_provider: AIProvider, budget: RepairBudget, **guards):
        if repair_provider is review_provider:
            raise ValueError("수정 제공자와 독립 검수 호출 컨텍스트는 분리해야 합니다.")
        self.budget = budget
        self.repair_provider = BudgetedProvider(repair_provider, budget, purpose="repair", **guards)
        self.review_provider = BudgetedProvider(review_provider, budget, purpose="review", **guards)

    async def run(self, original, findings: list[dict], repair, review) -> RepairResult:
        baseline, candidate = copy.deepcopy(original), copy.deepcopy(original)
        current = copy.deepcopy(findings)
        try:
            for _ in range(self.budget.max_rounds):
                if self.budget.rounds >= self.budget.max_rounds:
                    raise BudgetStopped("수정 회차 상한에 도달했습니다. 기존 초안을 보존합니다.")
                self.repair_provider.guard()
                if not current:
                    break
                # Every candidate round leaves at least one call for its own review.
                if self.budget.max_calls - self.budget.calls < 2:
                    raise BudgetStopped("수정과 독립 재검수에 필요한 호출이 남지 않았습니다.")
                self.budget.rounds += 1
                candidate = await repair(copy.deepcopy(candidate), copy.deepcopy(current), self.repair_provider)
                before = self.budget.completed_review_calls
                current = await review(copy.deepcopy(candidate), self.review_provider)
                if self.budget.completed_review_calls == before or self.budget.pending_calls:
                    raise BudgetStopped("독립 검수 호출이 성공적으로 완료되지 않았습니다. 후보를 승인하지 않습니다.")
                if not isinstance(current, list) or any(not isinstance(x, dict) for x in current):
                    raise BudgetStopped("독립 검수 결과 형식이 잘못되었습니다.")
                self.review_provider.guard()
                if not current:
                    return RepairResult("reviewed_candidate", baseline, candidate, [], self.budget.summary())
            return RepairResult("needs_revision", baseline, candidate, current, self.budget.summary())
        except ProviderError as exc:
            return RepairResult("stopped", baseline, candidate, current, self.budget.summary(), str(exc))
        except asyncio.CancelledError:
            return RepairResult("stopped", baseline, candidate, current, self.budget.summary(),
                                "작업이 취소됐습니다. 마지막 후보와 기존 저장본을 보존합니다.")
        except Exception as exc:
            # Invalid candidate/reviewer callbacks never erase the saved draft.
            return RepairResult("stopped", baseline, candidate, current, self.budget.summary(),
                                f"후보 수정 또는 검수 처리에 실패했습니다: {type(exc).__name__}")
        finally:
            for provider in (self.repair_provider, self.review_provider):
                provider.closed = True
                for task in list(provider.active_tasks):
                    if task is not asyncio.current_task():
                        task.cancel()
