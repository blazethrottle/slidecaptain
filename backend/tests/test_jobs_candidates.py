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



# D2b-3 리뷰 반영 (R1, R6, R8, R10, R11, R13)

def test_diagram_job_result_carries_its_basis(diagram_input, store):
    _, _, payload = diagram_input
    etag = store.deck_etag("diagram")
    with TestClient(create_app(store, provider=DiagramProvider(payload)), headers=HEADERS) as client:
        job = client.post("/api/projects/diagram/jobs", json={"request_id": "diagram-0002", "kind": "diagram",
                                                              "params": DIAGRAM_REQUEST},
                          headers={"If-Match": f'"{etag}"'}).json()
        view = _wait(client, "diagram", job["id"])
    assert view["result"]["base_etag"] == f'"{etag}"' and len(view["result"]["sources_fingerprint"]) == 64
    assert view["target"] == DIAGRAM_REQUEST["chapter_id"] and view["params"]["chapter_id"] == "new-diagram"


def test_unreadable_basis_after_drawing_is_not_delivered(diagram_input, store):
    _, _, payload = diagram_input
    provider = DiagramProvider(payload, effect=lambda: (store.root / "diagram" / "sources" / "unselected.md")
                               .write_bytes(b"\xff"))
    with diagram_client(store, provider) as client:
        response = client.post(DIAGRAM_ROUTE, json=DIAGRAM_REQUEST)
        [row] = _ledger_rows(client, "diagram")
    assert response.status_code == 409 and row.candidate_status == "held"  # 화면이 받지 못한 결과는 전달됨이 아니다


def test_stale_chapter_result_returned_by_the_wrapper_is_delivered(store):
    deck = _two_chapters(store)
    provider = GateProvider(SLOTS)

    def edit_then_release():
        assert provider.entered.wait(5)
        changed = deck.model_copy(deep=True)
        changed.structure.chapters[0].conclusion = "바뀐 결론"
        store.save_deck("p1", changed, snapshot=False)
        provider.release.set()

    with TestClient(create_app(store, provider=provider), headers=HEADERS) as client:
        threading.Thread(target=edit_then_release).start()
        response = client.post("/api/projects/p1/generate/chapter/c1", json={})
        [row] = _ledger_rows(client, "p1")
    assert response.status_code == 200 and row.candidate_status == "delivered"


@pytest.mark.parametrize("kind", ["rewrite", "chapter"])
def test_inputs_changed_between_registration_and_lease_make_no_call(rewrite_input, store, kind):
    # 정정 ⑤: 재작성과 장 재생성은 임대 직후 관련 입력을 다시 비교하고, 바뀌었으면 부르지 않는다
    deck, _, payload, brief = rewrite_input
    project = "rewrite"
    if kind == "chapter":
        _two_chapters(store)
        project = "p1"
    provider = GateProvider(payload if kind == "rewrite" else SLOTS)
    provider.release.set()
    app = create_app(store, provider=provider)
    entered, resume = threading.Event(), threading.Event()
    with TestClient(app, headers=HEADERS) as client:
        runner = client.app.state.job_runner
        real_acquire = runner._acquire

        def slow_acquire(*args):
            entered.set()
            assert resume.wait(5)
            return real_acquire(*args)

        runner._acquire = slow_acquire
        if kind == "rewrite":
            body = {"request_id": "rewrite-0002", "kind": "rewrite",
                    "params": {"brief": brief.model_dump(mode="json"), "instructions": "내용 보존"}}
            headers = {"If-Match": f'"{store.deck_etag(project)}"'}
        else:
            body = {"request_id": "chapter-0002", "kind": "chapter", "params": {"chapter_id": "c1"}}
            headers = {}
        job = client.post(f"/api/projects/{project}/jobs", json=body, headers=headers).json()
        assert entered.wait(5)
        current = store.load_deck(project)
        if kind == "rewrite":
            current.meta.presenter = "등록 뒤 편집"
        else:
            current.structure.chapters[0].conclusion = "등록 뒤 편집"
        store.save_deck(project, current, snapshot=False)
        resume.set()
        view = _wait(client, project, job["id"])
    assert view["state"] == "failed" and view["error"]["status"] == 412 and provider.calls == 0


def test_chapter_job_api_rejects_a_missing_chapter_without_a_row(store):
    _two_chapters(store)
    with TestClient(create_app(store, provider=GateProvider(SLOTS)), headers=HEADERS) as client:
        response = client.post("/api/projects/p1/jobs", json={"request_id": "chapter-0003", "kind": "chapter",
                                                              "params": {"chapter_id": "missing"}})
        assert response.status_code == 404 and _ledger_rows(client, "p1") == []


def test_remote_sent_time_is_recorded_only_when_the_provider_is_called(store):
    _two_chapters(store)
    with TestClient(create_app(store, provider=GateProvider(SLOTS)), headers=HEADERS) as client:
        # 래퍼는 종전처럼 없는 장 404를 임대 뒤에 낸다. 제공자를 부르지 않았으므로 원격 호출 시각이 없다
        assert client.post("/api/projects/p1/generate/chapter/missing", json={}).status_code == 404
        [row] = _ledger_rows(client, "p1")
    assert row.state == "failed" and row.remote_sent_at is None


def test_repair_stops_between_calls_when_its_cancel_flag_is_set(rewrite_input, store):
    # 수리의 cancelled 콜백이 작업의 취소 요청을 읽는다. 제공자가 취소를 무시하고 응답해도 다음 호출 전에 멈춘다
    deck, _, payload, brief = rewrite_input
    entered, release = threading.Event(), threading.Event()

    class Deaf(RepairProvider):
        async def complete(self, prompt, schema):  # 호출 기록은 부모 클래스가 한다
            entered.set()
            await asyncio.shield(asyncio.to_thread(release.wait, 5))
            return await super().complete(prompt, schema)

    provider = Deaf(payload)
    with TestClient(create_app(store, provider=provider), headers=HEADERS) as client:
        runner = client.app.state.job_runner
        job = client.post("/api/projects/rewrite/jobs", json={
            "request_id": "repair-0002", "kind": "repair", "params": repair_request(brief).model_dump(mode="json")},
            headers={"If-Match": f'"{store.deck_etag("rewrite")}"'}).json()
        assert entered.wait(5)
        runner._handles[job["id"]].cancel_requested = True  # 제공자 태스크에 취소를 보내지 않고 깃발만 세운다
        release.set()
        view = _wait(client, "rewrite", job["id"])
    assert len(provider.calls) == 1 and view["result"]["status"] == "stopped"
    assert view["result"]["reason"] == "작업이 취소됐습니다. 기존 초안을 보존합니다."


def test_repair_result_is_stopped_in_the_ledger_and_the_response_when_the_deck_changes(rewrite_input, store,
                                                                                        monkeypatch):
    # 수리 루프의 마지막 확인 뒤, 원장에 쓰기 전에 덱이 바뀌는 틈을 재현한다. 마무리가 stopped로 막는다 (리뷰 R8)
    import slidecaptain.server.app as app_module
    deck, _, payload, brief = rewrite_input
    changed = deck.model_copy(deep=True)
    changed.meta.presenter = "동시 편집"
    real_repair = app_module.repair_story

    async def repair_then_edit(*args, **kwargs):
        result = await real_repair(*args, **kwargs)
        store.save_deck("rewrite", changed, snapshot=False)
        return result

    monkeypatch.setattr(app_module, "repair_story", repair_then_edit)
    with TestClient(create_app(store, provider=RepairProvider(payload)), headers=HEADERS) as client:
        response = client.post("/api/projects/rewrite/story-plan/repair",
                               json=repair_request(brief).model_dump(mode="json"),
                               headers={"If-Match": f'"{store.deck_etag("rewrite")}"'})
        [row] = _ledger_rows(client, "rewrite")
    assert response.status_code == 200 and response.json()["status"] == "stopped"
    assert row.result["status"] == "stopped" and row.candidate_status == "delivered"


def test_chapter_recheck_reports_a_stale_story_plan(rewrite_input, store):
    # 구성 계획이 있는 덱에서 등록 뒤 자료가 바뀌면 종전처럼 stale_story_plan을 낸다 (리뷰 R10)
    deck, sources, _, _ = rewrite_input
    chapter_id = next(ch.id for ch in deck.structure.chapters if ch.template != "diagram")
    provider = GateProvider(SLOTS)
    provider.release.set()
    entered, resume = threading.Event(), threading.Event()
    with TestClient(create_app(store, provider=provider), headers=HEADERS) as client:
        runner = client.app.state.job_runner
        real_acquire = runner._acquire

        def slow_acquire(*args):
            entered.set()
            assert resume.wait(5)
            return real_acquire(*args)

        runner._acquire = slow_acquire
        job = client.post("/api/projects/rewrite/jobs", json={"request_id": "chapter-0004", "kind": "chapter",
                                                              "params": {"chapter_id": chapter_id}}).json()
        assert entered.wait(5)
        first = next(iter(sources))
        store.write_source("rewrite", first, sources[first] + " 바뀐 문장")
        resume.set()
        view = _wait(client, "rewrite", job["id"])
    assert view["state"] == "failed" and view["error"]["code"] == "stale_story_plan" and provider.calls == 0
