"""후보형 생성 6종의 원장 이전 (개정판 D2b-3, 계획서 5.4, 5.8, 6절 D2b-3).

지금 코드는 생성 도중 기준이 바뀐 결과를 버린다. 원장 이전 뒤에는 래퍼가 종전과 같은 412/409를
돌려주되 결과가 원장에 낡은 후보로 남는다. 실제 AI 호출은 없다.
"""

import asyncio
import threading
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from slidecaptain.pipeline.provider import ProviderResponse
from slidecaptain.server.app import create_app
from test_diagram_generation import REQUEST as DIAGRAM_REQUEST
from test_diagram_generation import ROUTE as DIAGRAM_ROUTE
from test_diagram_generation import StubProvider as DiagramProvider
from test_diagram_generation import app_client as diagram_client
from test_diagram_generation import diagram_input  # noqa: F401 (픽스처)
from test_story_plan_rewrite import StubProvider as RewriteProvider
from test_story_plan_rewrite import rewrite_input  # noqa: F401 (픽스처)
from test_story_repair import Provider as RepairProvider
from test_story_repair import request as repair_request

HEADERS = {"X-Requested-With": "SlideCaptain", "X-AI-Consent": "SlideCaptain"}
SLOTS = {"template": "bullet_box", "bullets": [{"text": "시장 규모 500억", "level": 0}],
         "conclusion": "성장 지속", "footnote": ""}


def _ledger_rows(client, project):
    return client.app.state.job_runner.ledger.list_jobs(project)


def _wait(client, project, job_id, timeout=10):
    handle = client.app.state.job_runner._handles[job_id]
    assert handle.wait_sync(timeout) is not None
    return client.get(f"/api/projects/{project}/jobs/{job_id}").json()


# 필수 RED 5와 6 (지금 코드의 틀린 동작: 생성 도중 기준이 바뀐 결과를 버린다)

def test_sources_changed_while_drawing_keep_the_candidate_as_stale(diagram_input, store):
    deck, _, payload = diagram_input
    provider = DiagramProvider(payload, effect=lambda: store.write_source("diagram", "unselected.md", "바뀐 원문"))
    with diagram_client(store, provider) as client:
        response = client.post(DIAGRAM_ROUTE, json=DIAGRAM_REQUEST)
        [row] = _ledger_rows(client, "diagram")
    assert response.status_code == 409  # 종전과 같은 응답
    assert row.state == "succeeded" and row.candidate_status == "stale" and row.result["status"] == "ok"
    assert store.load_deck("diagram") == deck


def test_deck_saved_before_the_rewrite_answer_keeps_a_stale_candidate_that_cannot_apply(rewrite_input, store):
    deck, _, payload, brief = rewrite_input
    changed = deck.model_copy(deep=True)
    changed.meta.presenter = "동시 편집"
    provider = RewriteProvider(payload, effect=lambda: store.save_deck("rewrite", changed, snapshot=False))
    etag = store.deck_etag("rewrite")
    with TestClient(create_app(store, provider=provider), headers=HEADERS) as client:
        job = client.post("/api/projects/rewrite/jobs", json={
            "request_id": "rewrite-0001", "kind": "rewrite",
            "params": {"brief": brief.model_dump(mode="json"), "instructions": "내용 보존"}},
            headers={"If-Match": f'"{etag}"'}).json()
        view = _wait(client, "rewrite", job["id"])
        applied = client.post("/api/projects/rewrite/story-plan/rewrite/apply", json={
            "deck": view["result"]["deck"], "sources_fingerprint": view["result"]["sources_fingerprint"]},
            headers={"If-Match": f'"{etag}"'})
    assert view["state"] == "succeeded" and view["candidate_status"] == "stale"
    assert view["stale_reasons"] == ["deck_changed"]
    assert applied.status_code == 412
    assert store.load_deck("rewrite").meta.presenter == "동시 편집"


# 장 재생성과 축약의 관련 입력 판정 (계획서 5.8)

class GateProvider:
    def __init__(self, payload):
        self.payload, self.entered, self.release = payload, threading.Event(), threading.Event()
        self.calls = 0

    async def complete(self, prompt, schema):
        self.calls += 1
        self.entered.set()
        while not self.release.is_set():
            await asyncio.sleep(0.01)
        return ProviderResponse(structured=deepcopy(self.payload), raw_text="r")


def _two_chapters(store):
    store.create_project("p1", "보고")
    store.write_source("p1", "리서치.md", "시장 규모는 500억 원이다")
    deck = store.load_deck("p1")
    deck = deck.model_validate({**deck.model_dump(mode="json"), "structure": {"chapters": [
        {"id": "c1", "topic": "시장 현황", "conclusion": "성장", "template": "bullet_box", "source_refs": ["리서치.md"]},
        {"id": "c2", "topic": "경쟁", "conclusion": "치열", "template": "bullet_box", "source_refs": ["리서치.md"]},
    ]}})
    store.save_deck("p1", deck, snapshot=False)
    return deck


@pytest.mark.parametrize("edit, candidate, reasons", [
    ("c2", "held", ["deck_changed_elsewhere"]),
    ("c1", "stale", ["chapter_changed"]),
])
def test_chapter_candidate_is_judged_by_its_own_inputs(store, edit, candidate, reasons):
    deck = _two_chapters(store)
    provider = GateProvider(SLOTS)
    with TestClient(create_app(store, provider=provider), headers=HEADERS) as client:
        job = client.post("/api/projects/p1/jobs", json={"request_id": "chapter-0001", "kind": "chapter",
                                                         "params": {"chapter_id": "c1"}}).json()
        assert provider.entered.wait(5)
        changed = deck.model_copy(deep=True)
        next(ch for ch in changed.structure.chapters if ch.id == edit).conclusion = "바뀐 결론"
        store.save_deck("p1", changed, snapshot=False)
        provider.release.set()
        view = _wait(client, "p1", job["id"])
        status = client.get("/api/status").json()
    assert view["state"] == "succeeded" and view["candidate_status"] == candidate
    assert view["stale_reasons"] == reasons
    # 다른 장의 편집은 알리기만 하므로 성공 시각을 기록한다. 그 장이 바뀐 결과는 기록하지 않는다
    assert (status["last_generation_at"] is not None) == (candidate == "held")


def test_condense_job_through_the_api(store):
    _two_chapters(store)
    provider = GateProvider(SLOTS)
    provider.release.set()
    with TestClient(create_app(store, provider=provider), headers=HEADERS) as client:
        job = client.post("/api/projects/p1/jobs", json={"request_id": "condense-0001", "kind": "condense",
                                                         "params": {"chapter_id": "c1", "slots": SLOTS}}).json()
        view = _wait(client, "p1", job["id"])
    assert view["kind"] == "condense" and view["state"] == "succeeded" and view["result"]["slots"]["template"] == "bullet_box"


def test_job_api_registration_checks_match_the_routes(store, diagram_input):
    # 도식 등록은 종전 라우트처럼 If-Match가 없으면 428, 낡으면 412이고 행을 만들지 않는다
    _, _, payload = diagram_input
    with TestClient(create_app(store, provider=DiagramProvider(payload)), headers=HEADERS) as client:
        body = {"request_id": "diagram-0001", "kind": "diagram", "params": DIAGRAM_REQUEST}
        assert client.post("/api/projects/diagram/jobs", json=body).status_code == 428
        assert client.post("/api/projects/diagram/jobs", json=body, headers={"If-Match": '"old"'}).status_code == 412
        assert _ledger_rows(client, "diagram") == []
        ok = client.post("/api/projects/diagram/jobs", json=body,
                         headers={"If-Match": f'"{store.deck_etag("diagram")}"'})
        assert ok.status_code == 202
        view = _wait(client, "diagram", ok.json()["id"])
    assert view["state"] == "succeeded" and view["candidate_status"] == "held"


def test_repair_job_reads_its_cancel_request_and_keeps_the_stopped_candidate(rewrite_input, store):
    deck, _, payload, brief = rewrite_input
    entered, release = threading.Event(), threading.Event()

    class Slow(RepairProvider):
        async def complete(self, prompt, schema):
            self.calls.append(prompt)
            entered.set()
            while not release.is_set():
                await asyncio.sleep(0.01)
            return await super().complete(prompt, schema)

    provider = Slow(payload)
    with TestClient(create_app(store, provider=provider), headers=HEADERS) as client:
        job = client.post("/api/projects/rewrite/jobs", json={
            "request_id": "repair-0001", "kind": "repair", "params": repair_request(brief).model_dump(mode="json")},
            headers={"If-Match": f'"{store.deck_etag("rewrite")}"'}).json()
        assert entered.wait(5)
        client.post(f"/api/projects/rewrite/jobs/{job['id']}/cancel")
        release.set()
        view = _wait(client, "rewrite", job["id"])
    assert view["state"] == "cancelled" and view["candidate_status"] == "held"
    assert view["result"]["status"] == "stopped"
    assert store.load_deck("rewrite") == deck
