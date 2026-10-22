"""요청 강도의 원장과 사용량 기록 (개정판 D4 실제 생성 확인 계획 3.2, 로드맵 D4a 이월표 둘째 행).

원장의 effort 열과 ai-usage.jsonl의 requested_effort는 사용자가 요청한 강도다. 실제 적용값이 아니다.
실제 AI 호출은 없다.
"""

import json

import pytest
from fastapi.testclient import TestClient

from slidecaptain.pipeline.connections import AIConnections, AISelection, ModelOption
from slidecaptain.pipeline.provider import ProviderResponse
from slidecaptain.server.app import create_app
from slidecaptain.storage.job_ledger import JobLedger
from tests.job_runs import run_job
from tests.test_ai_connections import FakeConnection

STRUCTURE = {"chapters": [{"topic": "표지", "conclusion": "", "template": "cover", "source_refs": []}]}
HEADERS = {"X-Requested-With": "SlideCaptain", "X-AI-Consent": "SlideCaptain"}


class _EffortProvider:
    def __init__(self, model, effort=None):
        self.model, self.effort = model, effort

    async def complete(self, prompt, schema):
        return ProviderResponse(structured=STRUCTURE, raw_text="r")


class _EffortConnection(FakeConnection):
    def models(self):
        return [ModelOption(id=self.model, label=self.model, supported_efforts=["low", "high"])]

    def provider(self, model, *, effort=None):
        return _EffortProvider(model, effort)


@pytest.fixture
def manager(tmp_path):
    value = AIConnections(tmp_path / "settings.json", connections={
        "claude": _EffortConnection("sonnet"), "chatgpt": FakeConnection("gpt-test")})
    yield value
    value.close()


def _project(store):
    store.create_project("p1", "보고")
    store.write_source("p1", "자료.md", "시장 규모는 500억 원이다")


def _usage_lines(store):
    return [json.loads(line) for line in
            (store.root / "p1" / "ai-usage.jsonl").read_text(encoding="utf-8").splitlines()]


@pytest.mark.parametrize("effort", ["low", None])
def test_selected_effort_is_kept_as_requested_in_ledger_and_usage(store, manager, effort):
    _project(store)
    manager.select(AISelection(provider="claude", model="sonnet", effort=effort))
    with TestClient(create_app(store, ai_connections=manager), headers=HEADERS) as client:
        run = run_job(client, "p1", "structure", {}, headers={"X-AI-Selection": manager.selection_id})
        assert run.state == "succeeded"
        job_id = run.view["id"]
    ledger = JobLedger.open(store.root)
    try:
        row = ledger.get_job(job_id)
    finally:
        ledger.close()
    assert (row.provider, row.model, row.effort) == ("claude", "sonnet", effort)
    [record] = _usage_lines(store)
    assert record["requested_model"] == "sonnet"
    assert record["requested_effort"] == effort


def test_single_provider_app_records_the_provider_effort(store):
    _project(store)
    with TestClient(create_app(store, provider=_EffortProvider("opus", "high")), headers=HEADERS) as client:
        run = run_job(client, "p1", "structure", {})
        assert run.state == "succeeded"
        job_id = run.view["id"]
    ledger = JobLedger.open(store.root)
    try:
        assert ledger.get_job(job_id).effort == "high"
    finally:
        ledger.close()
    [record] = _usage_lines(store)
    assert (record["requested_model"], record["requested_effort"]) == ("opus", "high")


def test_current_selection_is_read_together_with_its_id(manager):
    """등록 입력은 선택과 선택 식별자를 잠금 안에서 함께 읽는다. 그 사이에 선택이 바뀌면 행을 만들지 않고 409다 (코드 리뷰 LCC-08)."""
    from slidecaptain.pipeline.connections import ConnectionConflict

    token = manager.selection_id
    assert manager.current_selection(token) == manager.selection
    manager.select(AISelection(provider="claude", model="sonnet", effort="low"))
    with pytest.raises(ConnectionConflict) as error:
        manager.current_selection(token)
    assert error.value.code == "selection_changed"
