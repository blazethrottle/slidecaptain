"""도식 후보의 관련 입력 해시 (C1 계획 W2-a, 2026-10-16).

도식 작업 등록이 "d1:<프롬프트 입력>|<교체 대상>"을 남기고, 조회가 처분이 held인 후보를 이 해시로 판정한다. 프롬프트에 들어가는
덱 값이나 교체 대상이 바뀌면 막는 사유(story_plan_changed, chapter_changed, chapter_missing), 다른 곳만 바뀌면 알림
(deck_changed_elsewhere)이다. 생성 도중 덱이 바뀐 stale 후보와 해시가 없는 옛 행은 지금처럼 덱 전체 비교다. 실제 AI 호출 없음.
"""

import pytest
from fastapi.testclient import TestClient

from slidecaptain.pipeline.relevance import DIAGRAM_MARKER, diagram_parts, diagram_reasons, diagram_relevance
from slidecaptain.server.app import create_app
from test_diagram_generation import REQUEST
from test_diagram_generation import StubProvider as DiagramProvider
from test_diagram_generation import diagram_input  # noqa: F401 (픽스처)
from tests.test_jobs_batch import HEADERS

# 픽스처의 기존 도식 장. 교체 생성은 구성 계획의 연결(역할, 주장)을 그대로 보내야 서버가 받는다
REPLACE = {"mode": "replace", "chapter_id": "synthetic-flow", "topic": "요청 처리 흐름", "role": "answer",
           "claim_ids": ["claim", "unselected-claim"], "instructions": ""}


def _held(client, store, params, request_id="diagram-0001"):
    response = client.post("/api/projects/diagram/jobs", json={"request_id": request_id, "kind": "diagram", "params": params},
                           headers={"If-Match": f'"{store.deck_etag("diagram")}"'})
    assert response.status_code == 202, response.text
    assert client.app.state.job_runner._handles[response.json()["id"]].wait_sync(10) is not None
    return response.json()["id"]


def _view(client, job_id):
    return client.get(f"/api/projects/diagram/jobs/{job_id}").json()


def _edit(store, change):
    deck = store.load_deck("diagram")
    change(deck)
    store.save_deck("diagram", deck, snapshot=False)


def _claim(deck, claim_id="claim"):
    return next(c for c in deck.structure.story_plan.claims if c.id == claim_id)


def _evidence(deck, evidence_id):
    return next(e for e in deck.structure.story_plan.evidence if e.id == evidence_id)


def _cover(deck):
    return next(c for c in deck.structure.chapters if c.id == "cover")


# 회귀 RED: 지금 코드는 도식 행에 해시가 없어 주장 문장이 바뀌어도 사유가 deck_changed 하나다(계획 리뷰 E3)
def test_claim_statement_change_blocks_a_held_diagram_candidate(diagram_input, store):
    _, _, payload = diagram_input
    with TestClient(create_app(store, provider=DiagramProvider(payload)), headers=HEADERS) as client:
        job = _held(client, store, REQUEST)
        _edit(store, lambda d: setattr(_claim(d), "statement", "정반대의 주장으로 바뀐 문장"))
        view = _view(client, job)
    assert view["candidate_status"] == "held"
    assert view["relevance_hash"].startswith(DIAGRAM_MARKER)
    assert view["stale_reasons"] == ["story_plan_changed"]


@pytest.mark.parametrize("change, reasons", [
    # 프롬프트에 들어가지 않는 값만 바뀌면 알림 하나다
    (lambda d: setattr(_cover(d), "topic", "다른 장의 제목"), ["deck_changed_elsewhere"]),
    (lambda d: setattr(d.meta, "presenter", "보고자"), ["deck_changed_elsewhere"]),
    (lambda d: setattr(_claim(d, "unselected-claim"), "statement", "선택하지 않은 주장"), ["deck_changed_elsewhere"]),
    # 선택 주장이 가리키는 근거의 발췌가 바뀌면 막는다
    (lambda d: setattr(_evidence(d, _claim(d).evidence_ids[0]), "excerpt", "바뀐 발췌"), ["story_plan_changed"]),
    (lambda d: setattr(d.meta, "title", "바뀐 보고 제목"), ["story_plan_changed"]),
])
def test_held_create_candidate_reasons_follow_the_prompt_inputs(diagram_input, store, change, reasons):
    _, _, payload = diagram_input
    with TestClient(create_app(store, provider=DiagramProvider(payload)), headers=HEADERS) as client:
        job = _held(client, store, REQUEST)
        _edit(store, change)
        view = _view(client, job)
    assert view["stale_reasons"] == reasons


def test_replace_candidate_is_blocked_when_its_target_changes_or_disappears(diagram_input, store):
    _, _, payload = diagram_input

    def rename_node(deck):
        slide = next(s for s in deck.slides if s.chapter_id == "synthetic-flow")
        slide.slots.diagram.nodes[0].content = "사용자가 고친 항목"

    with TestClient(create_app(store, provider=DiagramProvider(payload)), headers=HEADERS) as client:
        job = _held(client, store, REPLACE)
        assert _view(client, job)["stale_reasons"] == []
        _edit(store, rename_node)
        changed = _view(client, job)
    assert changed["stale_reasons"] == ["chapter_changed"]


# 덱 검증은 구성 계획의 장 연결을 하나 이상 요구하므로 교체 대상 장이나 선택 주장이 사라진 덱은 저장할 수 없다. 그런 덱을
# 다른 빌드나 손 편집이 남길 수 있으므로 판정 함수에 검증 없는 사본으로 넣어 본다
def test_missing_target_or_claim_is_judged_without_saving(diagram_input):
    deck, _, _ = diagram_input
    value = diagram_relevance(deck, REPLACE)
    no_target = deck.model_copy(deep=True)
    no_target.structure.chapters = [c for c in no_target.structure.chapters if c.id != "synthetic-flow"]
    no_target.slides = [s for s in no_target.slides if s.chapter_id != "synthetic-flow"]
    no_claim = deck.model_copy(deep=True)
    no_claim.structure.story_plan.claims = [c for c in no_claim.structure.story_plan.claims if c.id != "claim"]
    no_plan = deck.model_copy(deep=True)
    no_plan.structure.story_plan = None
    assert diagram_reasons(no_target, REPLACE, value) == ["chapter_missing"]
    assert diagram_reasons(no_claim, REPLACE, value) == ["story_plan_changed"]
    assert diagram_reasons(no_plan, REQUEST, diagram_relevance(deck, REQUEST)) == ["story_plan_changed"]


def test_sources_change_and_legacy_rows_keep_the_old_reasons(diagram_input, store):
    _, _, payload = diagram_input
    with TestClient(create_app(store, provider=DiagramProvider(payload)), headers=HEADERS) as client:
        job = _held(client, store, REQUEST)
        legacy = _held(client, store, REQUEST, request_id="diagram-0002")
        client.app.state.job_runner.ledger._conn.execute(
            "UPDATE jobs SET relevance_hash = NULL WHERE id = ?", (legacy,))  # 이 빌드 전에 등록한 도식 행
        _edit(store, lambda d: setattr(d.meta, "presenter", "보고자"))
        legacy_view = _view(client, legacy)
        store.write_source("diagram", "unselected.md", "변경된 원문")
        sources_view = _view(client, job)
    assert legacy_view["stale_reasons"] == ["deck_changed"]
    assert sources_view["stale_reasons"] == ["sources_changed"]


# 고정: 생성 도중 덱이 바뀐 후보는 처분이 stale이고 조회 사유도 덱 전체 비교(deck_changed)다. 작성 창이 이 사유로 412를 낸다
def test_deck_change_while_drawing_keeps_the_stale_candidate_and_deck_changed(diagram_input, store):
    deck, _, payload = diagram_input

    def touch():
        changed = deck.model_copy(deep=True)
        changed.meta.presenter = "동시 편집"
        store.save_deck("diagram", changed, snapshot=False)

    with TestClient(create_app(store, provider=DiagramProvider(payload, effect=touch)), headers=HEADERS) as client:
        view = _view(client, _held(client, store, REQUEST))
    assert view["candidate_status"] == "stale"
    assert view["stale_reasons"] == ["deck_changed"]


# 해시가 프롬프트 입력을 모두 덮는다: diagram_prompt가 덱에서 읽는 값을 하나씩 바꾸면 첫 조각이 바뀐다
def test_diagram_relevance_covers_every_deck_value_the_prompt_reads(diagram_input):
    deck, _, _ = diagram_input
    # 픽스처는 도식의 근거 셋이 모두 선택 주장에도 연결되어 있다. 선택 주장의 근거를 하나로 줄여 교체 대상 도식만 가리키는
    # 근거를 만든다(그러지 않으면 그 근거를 해시에서 빼는 변형을 가르지 못한다)
    deck = deck.model_copy(deep=True)
    _claim(deck).evidence_ids = _claim(deck).evidence_ids[:1]
    base = diagram_parts(diagram_relevance(deck, REPLACE))
    existing_only = {eid for item in [*deck.slides[0].slots.diagram.nodes, *deck.slides[0].slots.diagram.edges]
                     for eid in item.evidence_ids} - set(_claim(deck).evidence_ids)
    assert existing_only
    changes = {
        "제목": lambda d: setattr(d.meta, "title", "바뀜"),
        "피보고자": lambda d: setattr(d.meta, "audience", "바뀜"),
        "보고 유형": lambda d: setattr(d.meta, "report_type", "proposal"),
        "핵심 메시지": lambda d: setattr(d.meta, "key_message", "바뀜"),
        "요약": lambda d: setattr(d.structure.story_plan.brief, "decision_question", "바뀜"),
        "선택 주장": lambda d: setattr(_claim(d), "statement", "바뀜"),
        "선택 근거": lambda d: setattr(_evidence(d, _claim(d).evidence_ids[0]), "excerpt", "바뀜"),
        "교체 대상 도식만 가리키는 근거": lambda d: setattr(_evidence(d, sorted(existing_only)[-1]), "excerpt", "바뀜"),
    }
    for name, change in changes.items():
        changed = deck.model_copy(deep=True)
        change(changed)
        assert diagram_parts(diagram_relevance(changed, REPLACE))[0] != base[0], name
    for name, change in {"보고자": lambda d: setattr(d.meta, "presenter", "바뀜"),
                         "다른 장 제목": lambda d: setattr(_cover(d), "topic", "바뀜")}.items():
        changed = deck.model_copy(deep=True)
        change(changed)
        assert diagram_parts(diagram_relevance(changed, REPLACE)) == base, name


def test_new_diagram_has_no_target_and_unknown_markers_are_not_parsed(diagram_input):
    deck, _, _ = diagram_input
    value = diagram_relevance(deck, REQUEST)
    assert value.startswith(DIAGRAM_MARKER) and value.endswith("|")
    assert diagram_parts("c1:x|y|z") is None and diagram_parts(None) is None
    assert diagram_reasons(deck, REQUEST, "c1:x|y|z") == []
