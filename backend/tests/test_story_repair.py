import asyncio
from copy import deepcopy

import pytest
from pydantic import ValidationError

from test_story_plan_rewrite import rewrite_input
from slidecaptain.metrics.font_metrics import FontMetrics
from slidecaptain.pipeline.provider import ProviderResponse
from slidecaptain.pipeline.story_repair import StoryRepairRequest, repair_story
from slidecaptain.server.app import create_app
from fastapi.testclient import TestClient


class Provider:
    def __init__(self, payload, critique=None, effect=None):
        self.payload, self.effect = payload, effect
        self.critique = critique if critique is not None else {"findings": [], "scope_note": "합성 원문과 후보의 계획 연결 확인; 본문 의미·native 렌더 미검수"}
        self.calls = []
    async def complete(self, prompt, schema):
        self.calls.append(prompt)
        if self.effect:
            self.effect()
        return ProviderResponse(deepcopy(self.critique if "scope_note" in schema.get("properties", {}) else self.payload), "synthetic")


def request(brief, **overrides):
    return StoryRepairRequest.model_validate({"brief": brief.model_dump(), "findings": [
        {"code": "flow", "target": "report", "message": "장 순서와 답변 연결 검토"}],
        "max_calls": 4, "max_rounds": 2, "max_seconds": 30, **overrides})


def execute(rewrite_input, provider, **kwargs):
    deck, sources, payload, brief = rewrite_input
    return asyncio.run(repair_story(deck, sources, request(brief, **kwargs.pop("limits", {})), provider,
        FontMetrics.load_default(), base_etag='"basis"', source_revision="a"*64,
        unchanged=kwargs.pop("unchanged", lambda: True), cancelled=kwargs.pop("cancelled", lambda: False)))


def test_candidate_has_distinct_critique_and_no_submission_approval(rewrite_input):
    deck, sources, payload, brief = rewrite_input
    original = deck.model_dump()
    provider = Provider(payload)
    result = execute(rewrite_input, provider)
    assert result.status == "reviewed_candidate"
    assert result.calls == 2 and result.review_calls == 1
    assert len(provider.calls) == 2 and "독립 검수 역할" in provider.calls[1]
    assert deck.model_dump() == original and result.deck.slides == deck.slides
    assert result.submission_approved is False and result.cost_usd is None
    assert result.unmeasured_calls == 2 and result.review_notes


def test_repeated_same_target_defect_stops_without_next_round(rewrite_input):
    provider = Provider(rewrite_input[2], {"findings": request(rewrite_input[3]).model_dump()["findings"], "scope_note": "순서 문제 유지"})
    result = execute(rewrite_input, provider)
    assert result.status == "stopped" and result.calls == 2
    assert result.deck and result.deck.slides == rewrite_input[0].slides
    assert result.findings[0].code == "flow"


@pytest.mark.parametrize("kind", ["stale", "cancel", "cost", "bad_critique", "retry"])
def test_failure_guards_and_retries_keep_last_saved_draft(rewrite_input, kind):
    original = rewrite_input[0].model_dump()
    provider = Provider({} if kind == "retry" else rewrite_input[2], {} if kind == "bad_critique" else None)
    kwargs = {"limits": {"max_calls": 2}} if kind in {"retry", "cost"} else {}
    if kind == "cost": kwargs["limits"]["max_cost_usd"] = "1"
    if kind == "cancel": kwargs["cancelled"] = lambda: True
    if kind == "stale": provider.effect = lambda: None; kwargs["unchanged"] = lambda: len(provider.calls) == 0
    result = execute(rewrite_input, provider, **kwargs)
    assert result.status == "stopped" and not result.submission_approved
    assert rewrite_input[0].model_dump() == original
    assert len(provider.calls) == (1 if kind in {"retry", "stale"} else 2 if kind == "bad_critique" else 0)


def test_inflight_cancel_counts_call_and_does_not_review(rewrite_input):
    async def scenario():
        entered = asyncio.Event()
        class Slow(Provider):
            async def complete(self, prompt, schema):
                self.calls.append(prompt); entered.set()
                await asyncio.Event().wait()
        provider = Slow(rewrite_input[2])
        deck, sources, payload, brief = rewrite_input
        task = asyncio.create_task(repair_story(deck, sources, request(brief), provider, FontMetrics.load_default(),
            base_etag='"basis"', source_revision="a"*64, unchanged=lambda: True, cancelled=lambda: False))
        await entered.wait(); task.cancel()
        result = await task
        assert result.status == "stopped" and result.calls == 1 and result.review_calls == 0
        assert result.unmeasured_calls == 1 and result.deck == deck
    asyncio.run(scenario())


def test_api_requires_consent_etag_and_never_saves_candidate(rewrite_input, store):
    provider = Provider(rewrite_input[2])
    client = TestClient(create_app(store, provider=provider), headers={"X-Requested-With": "SlideCaptain"})
    body = request(rewrite_input[3]).model_dump(mode="json")
    path = "/api/projects/rewrite/story-plan/repair"
    assert client.post(path, json=body).status_code == 428
    assert client.post(path, json=body, headers={"X-AI-Consent": "SlideCaptain"}).status_code == 428
    etag = store.deck_etag("rewrite")
    response = client.post(path, json=body, headers={"X-AI-Consent": "SlideCaptain", "If-Match": f'"{etag}"'})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "reviewed_candidate"
    assert store.deck_etag("rewrite") == etag and not store.list_snapshots("rewrite")


@pytest.mark.parametrize("bad", [{"max_calls": True}, {"max_rounds": 0}, {"findings": []}, {"max_seconds": 301}])
def test_budget_and_problem_list_are_explicit_bounded_inputs(rewrite_input, bad):
    with pytest.raises(ValidationError): request(rewrite_input[3], **bad)
