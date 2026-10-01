import asyncio
import time

import pytest

from slidecaptain.pipeline.repair_budget import BudgetStopped, RepairBudget, BudgetedProvider, RepairCoordinator
from slidecaptain.pipeline.provider import ProviderResponse, ProviderCallFailed


class Stub:
    def __init__(self, fail=False):
        self.calls = 0
        self.fail = fail

    async def complete(self, prompt, schema):
        self.calls += 1
        if self.fail:
            raise ProviderCallFailed("synthetic failure")
        return ProviderResponse({"ok": True}, "")


def test_retry_failures_consume_call_budget_and_keep_review_reserve():
    async def scenario():
        budget = RepairBudget(max_calls=3, max_rounds=1, reserved_review_calls=1)
        provider = Stub(fail=True)
        wrapped = BudgetedProvider(provider, budget, purpose="repair")
        for _ in range(2):
            with pytest.raises(ProviderCallFailed):
                await wrapped.complete("p", {})
        with pytest.raises(BudgetStopped):
            await wrapped.complete("p", {})
        assert provider.calls == 2
        assert budget.calls == 2
    asyncio.run(scenario())


def test_no_authorized_calls_is_zero_calls():
    async def scenario():
        provider = Stub()
        with pytest.raises(BudgetStopped):
            await BudgetedProvider(provider, RepairBudget(max_calls=0, max_rounds=0), purpose="repair").complete("", {})
        assert provider.calls == 0
    asyncio.run(scenario())


@pytest.mark.parametrize("guard", ["cancel", "stale", "deadline"])
def test_cancel_revision_and_deadline_checked_before_every_call(guard):
    async def scenario():
        b = RepairBudget(max_calls=3, max_rounds=1, reserved_review_calls=1,
            deadline_monotonic=time.monotonic() - 1 if guard == "deadline" else None)
        p = Stub()
        wrapped = BudgetedProvider(p, b, purpose="repair", cancelled=lambda: guard == "cancel",
                                  unchanged=lambda: guard != "stale")
        with pytest.raises(BudgetStopped):
            await wrapped.complete("", {})
        assert p.calls == 0
    asyncio.run(scenario())


def test_unknown_cost_never_bypasses_cost_limit():
    async def scenario():
        p = Stub()
        b = RepairBudget(max_calls=2, max_rounds=1, reserved_review_calls=1, max_cost_usd="1")
        with pytest.raises(BudgetStopped):
            await BudgetedProvider(p, b, purpose="repair").complete("", {})
        assert p.calls == 0
    asyncio.run(scenario())


def test_limited_coordinator_preserves_original_on_unresolved_review():
    async def scenario():
        original = {"body": "manual edit"}
        async def repair(value, findings, provider):
            await provider.complete("repair", {})
            return {"body": "candidate"}
        async def review(value, provider):
            await provider.complete("independent review", {})
            return [{"code": "unresolved", "severity": "major"}]
        b = RepairBudget(max_calls=2, max_rounds=1, reserved_review_calls=1)
        result = await RepairCoordinator(Stub(), Stub(), b).run(original, [{"code": "overflow"}], repair, review)
        assert original == {"body": "manual edit"}
        assert result.status == "needs_revision"
        assert result.original == original
        assert result.candidate == {"body": "candidate"}
        assert b.calls == 2
    asyncio.run(scenario())


def test_same_provider_instance_cannot_review_own_repair():
    p = Stub()
    with pytest.raises(ValueError):
        RepairCoordinator(p, p, RepairBudget(max_calls=2, max_rounds=1, reserved_review_calls=1))
