"""후보의 낡음 판정 (개정판 D3b-2, 계획 4.3).

구조안 후보는 덱 ETag가 아니라 (가) 구조안 지시문이 덱에서 읽는 값과 (나) 승인이 덮어쓰는 범위
(structure, slides)로 판정한다. 장 후보의 관련 입력은 장 지시문이 읽는 메타 값으로 좁힌다. 보고 목적
값은 함수 하나(purpose_prompt_values)가 정하고, 출력 지문 세 곳은 보고 목적 칸을 뺀다. 실제 AI 호출은 없다.
"""

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from slidecaptain.models.deck import Deck, DeckMeta
from slidecaptain.models.preset import Preset
from slidecaptain.models.render import RenderPlan
from slidecaptain.models.report_purpose import output_dump, purpose_prompt_values
from slidecaptain.pipeline.auth_status import LoginStatus
from slidecaptain.pipeline.numeric_review import assess_numeric_review
from slidecaptain.pipeline.prompts import build_structure_prompt
from slidecaptain.pipeline.quality import assess_quality
from slidecaptain.pipeline.relevance import chapter_relevance, structure_relevance
from slidecaptain.pipeline.semantic_review import assess_semantic_suspects
from slidecaptain.pipeline.story import story_fingerprint
from slidecaptain.server.app import create_app
from slidecaptain.storage.job_ledger import LEDGER_NAME
from test_jobs_api import HEADERS, GateProvider, _project, _register, _wait, manager  # noqa: F401 (픽스처)
from test_jobs_candidates import SLOTS, _two_chapters
from test_jobs_candidates import GateProvider as ChapterGate
from test_jobs_candidates import _wait as _wait_chapter

FIXTURES = Path(__file__).parent / "fixtures"


def _q3b():
    payload = json.loads((FIXTURES / "q3b-project.json").read_text(encoding="utf-8"))
    return (Deck.model_validate(payload["deck"]), payload["sources"],
            RenderPlan.model_validate(payload["render_plan"]), Preset.model_validate(payload["preset"]))


def _with_meta(deck: Deck, **update) -> Deck:
    return Deck.model_validate({**deck.model_dump(mode="json"), "meta": {**deck.meta.model_dump(mode="json"), **update}})


# -- 보고 목적 값 함수 (재리뷰 RR12) ----------------------------------------------------

def test_purpose_prompt_values_hold_only_what_the_prompts_read():
    meta = DeckMeta(title="보고", report_type="weekly", key_message="핵심", desired_outcome="facts",
                    desired_outcome_other="기타가 아니면 읽지 않음",
                    report_details={"weekly.period": "10월 둘째 주", "ir.investment_stage": "숨은 입력"})
    assert purpose_prompt_values(meta) == {
        "key_message": "핵심", "desired_outcome": "facts", "report_details": {"period": "10월 둘째 주"},
    }
    other = meta.model_copy(update={"desired_outcome": "other"})
    assert purpose_prompt_values(other)["desired_outcome_other"] == "기타가 아니면 읽지 않음"
    assert purpose_prompt_values(DeckMeta(title="보고", report_type_confirmed=True)) == {}


def test_story_fingerprint_follows_purpose_values_but_not_hidden_inputs():
    deck, sources, _, _ = _q3b()
    plan = deck.structure.story_plan
    base = story_fingerprint(plan, deck.meta, deck.structure.chapters, sources)
    assert base == plan.input_fingerprint  # 기본값이면 기존 계획의 지문 그대로
    hidden = _with_meta(deck, report_details={"ir.investment_stage": "시리즈 A"}, report_type_confirmed=True)
    assert story_fingerprint(plan, hidden.meta, deck.structure.chapters, sources) == base
    changed = _with_meta(deck, key_message="핵심을 바꿈")
    assert story_fingerprint(plan, changed.meta, deck.structure.chapters, sources) != base


def test_output_fingerprints_ignore_purpose_values_and_the_schema_version():
    """핵심 내용을 처음 넣거나 유형만 확인해도 검수 기록과 내보내기가 낡지 않는다 (재리뷰 RR4)."""
    deck, sources, plan, preset = _q3b()
    variants = [deck, _with_meta(deck, key_message="핵심"), _with_meta(deck, report_type_confirmed=True),
                _with_meta(deck, desired_outcome="persuasion", report_details={"ir.ask_and_use": "숨은 입력"})]
    assert variants[1].schema_version == 2
    for fingerprint in (
        lambda d: assess_quality(d, preset, plan, sources=sources).input_fingerprint,
        lambda d: assess_numeric_review(d, sources).input_fingerprint,
        lambda d: assess_semantic_suspects(d, sources).input_fingerprint,
    ):
        assert len({fingerprint(d) for d in variants}) == 1
    assert output_dump(deck) == deck.model_dump(mode="json")  # 기존 덱의 덤프는 그대로


# -- 해시 모양 ---------------------------------------------------------------------

def test_structure_hash_has_two_parts_and_ignores_presenter_and_hidden_inputs():
    deck, _, _, _ = _q3b()
    value = structure_relevance(deck)
    assert value.startswith("s1:") and value.count("|") == 1
    same = [_with_meta(deck, presenter="다른 보고자"), _with_meta(deck, report_type_confirmed=True),
            _with_meta(deck, preset_overrides={"accent": "#000000"}),
            _with_meta(deck, report_details={"ir.investment_stage": "숨은 입력"})]
    assert {structure_relevance(d) for d in same} == {value}
    a, b = value[3:].split("|")
    titled = structure_relevance(_with_meta(deck, title="다른 제목"))[3:].split("|")
    assert titled[0] != a and titled[1] == b
    moved = deck.model_copy(deep=True)
    moved.structure.chapters[0].conclusion = "바뀐 결론"
    assert structure_relevance(Deck.model_validate(moved.model_dump(mode="json")))[3:].split("|")[1] != b


def test_chapter_hash_keeps_three_parts_with_the_marker_in_the_first():
    """이전 빌드는 이 값을 정확히 세 조각으로 푼다. 앞에 표지를 더하면 작업 목록이 500이었다 (재리뷰 RR11)."""
    deck, _, _, _ = _q3b()
    chapter_id = deck.structure.chapters[0].id
    value = chapter_relevance(deck, chapter_id)
    template, _, _ = value.split("|")
    assert template.startswith("c1:")
    assert chapter_relevance(_with_meta(deck, presenter="다른 보고자"), chapter_id) == value
    assert chapter_relevance(_with_meta(deck, report_type_confirmed=True), chapter_id) == value


def test_structure_prompt_reads_exactly_the_hashed_meta_fields():
    """칸 하나씩 바꿔 지시문이 바뀌는 칸의 집합과 해시 (가)가 바뀌는 칸의 집합을 맞춘다 (가정 2의 검증 수단).
    보고 목적 칸의 표는 test_purpose_prompts.py에 있다(D3b-3이 지시문에 넣었다)."""
    base = DeckMeta(title="보고", report_type="approval", audience="임원")
    edits = {"title": "다른 제목", "report_type": "strategy", "audience": "팀장", "presenter": "보고자",
             "preset_overrides": {"accent": "#000000"}, "report_type_confirmed": True}
    deck_of = lambda meta: Deck(meta=meta)  # noqa: E731
    prompt_changes, hash_changes = set(), set()
    for name, value in edits.items():
        meta = base.model_copy(update={name: value})
        if build_structure_prompt(meta, {"a.md": "자료"}) != build_structure_prompt(base, {"a.md": "자료"}):
            prompt_changes.add(name)
        if structure_relevance(deck_of(meta))[3:].split("|")[0] != structure_relevance(deck_of(base))[3:].split("|")[0]:
            hash_changes.add(name)
    assert prompt_changes == hash_changes == {"title", "report_type", "audience"}


# -- 구조안 후보: 서버 판정 세 자리 -------------------------------------------------------

def _put_meta(client, **update):
    deck = client.get("/api/projects/p1/deck")
    body = deck.json()
    body["meta"].update(update)
    response = client.put("/api/projects/p1/deck", json=body, headers={"If-Match": deck.headers["etag"]})
    assert response.status_code == 200, response.text


def test_presenter_change_after_generation_keeps_the_structure_candidate_applicable(store):
    _project(store)
    provider = GateProvider()
    provider.release.set()
    with TestClient(create_app(store, provider=provider), headers=HEADERS) as client:
        job = _register(client).json()
        _wait(client, job["id"])
        _put_meta(client, presenter="김보고")
        view = client.get(f"/api/projects/p1/jobs/{job['id']}").json()
        settled = client.post(f"/api/projects/p1/jobs/{job['id']}/candidate", json={"action": "applied"})
    assert view["candidate_status"] == "held" and view["stale_reasons"] == ["deck_changed_elsewhere"]
    assert settled.status_code == 200


def test_presenter_change_during_generation_does_not_record_a_stale_candidate(store):
    """생성 직후 판정도 해시로 본다. 지금은 원장에 stale로 남아 승인할 수 없었다 (리뷰 V1)."""
    _project(store)
    provider = GateProvider()
    app = create_app(store, provider=provider, login_checker=lambda: LoginStatus(logged_in=False))
    with TestClient(app, headers=HEADERS) as client:
        job = _register(client).json()
        assert provider.entered.wait(5)
        _put_meta(client, presenter="박보고")
        provider.release.set()
        view = _wait(client, job["id"])
    assert view["state"] == "succeeded" and view["candidate_status"] == "held"
    assert view["stale_reasons"] == ["deck_changed_elsewhere"]


def test_presenter_change_before_start_does_not_fail_the_job(store, manager):
    _project(store)
    entered, resume = __import__("threading").Event(), __import__("threading").Event()
    real_status = manager.connections["claude"].status

    def slow_status():
        entered.set()
        assert resume.wait(5)
        return real_status()

    manager.connections["claude"].status = slow_status
    with TestClient(create_app(store, ai_connections=manager), headers=HEADERS) as client:
        job = _register(client, headers={"X-AI-Selection": manager.selection_id}).json()
        assert entered.wait(5)
        _put_meta(client, presenter="최보고")
        resume.set()
        view = _wait(client, job["id"])
    assert view["state"] == "succeeded", view


@pytest.mark.parametrize("update, code", [
    ({"title": "다른 제목"}, "structure_input_changed"),
    ({"key_message": "핵심을 새로 씀"}, "structure_input_changed"),
])
def test_input_change_before_start_fails_with_the_input_message(store, manager, update, code):
    _project(store)
    entered, resume = __import__("threading").Event(), __import__("threading").Event()
    real_status = manager.connections["claude"].status

    def slow_status():
        entered.set()
        assert resume.wait(5)
        return real_status()

    manager.connections["claude"].status = slow_status
    with TestClient(create_app(store, ai_connections=manager), headers=HEADERS) as client:
        job = _register(client, headers={"X-AI-Selection": manager.selection_id}).json()
        assert entered.wait(5)
        _put_meta(client, **update)
        resume.set()
        view = _wait(client, job["id"])
    assert view["state"] == "failed" and view["error"]["status"] == 412
    assert view["error"]["code"] == "base_changed" and "보고 정보가 바뀌었습니다" in view["error"]["detail"]
    assert manager.connections["claude"].calls == []


@pytest.mark.parametrize("update, reasons", [
    ({"title": "다른 제목"}, ["structure_input_changed"]),
    ({"key_message": "핵심"}, ["structure_input_changed"]),
    ({"report_details": {"ir.investment_stage": "숨은 입력"}}, ["deck_changed_elsewhere"]),
    ({"report_type_confirmed": True}, ["deck_changed_elsewhere"]),
])
def test_structure_candidate_reasons_follow_the_hashed_inputs(store, update, reasons):
    _project(store)
    provider = GateProvider()
    provider.release.set()
    with TestClient(create_app(store, provider=provider), headers=HEADERS) as client:
        job = _register(client).json()
        _wait(client, job["id"])
        _put_meta(client, **update)
        view = client.get(f"/api/projects/p1/jobs/{job['id']}").json()
    assert view["stale_reasons"] == reasons


def test_structure_candidate_is_stale_after_the_document_structure_changes(store):
    """승인이 덮어쓰는 범위가 바뀌면 옛 후보를 승인할 수 없다 (리뷰 V3, critical)."""
    _project(store)
    provider = GateProvider()
    provider.release.set()
    with TestClient(create_app(store, provider=provider), headers=HEADERS) as client:
        job = _register(client).json()
        _wait(client, job["id"])
        deck = client.get("/api/projects/p1/deck")
        body = deck.json()
        body["structure"]["chapters"] = [{"id": "c9", "topic": "재작성으로 바뀐 장", "conclusion": "",
                                          "template": "bullet_box", "source_refs": []}]
        client.put("/api/projects/p1/deck", json=body, headers={"If-Match": deck.headers["etag"]})
        view = client.get(f"/api/projects/p1/jobs/{job['id']}").json()
    assert view["stale_reasons"] == ["structure_applied_basis_changed"]


def test_rows_without_the_marker_are_judged_by_the_etag(store):
    """이전 빌드가 쓴 구조안 행(해시 없음)은 지금처럼 덱 ETag로 판정한다."""
    _project(store)
    provider = GateProvider()
    provider.release.set()
    with TestClient(create_app(store, provider=provider), headers=HEADERS) as client:
        job = _register(client).json()
        _wait(client, job["id"])
        with sqlite3.connect(store.root / LEDGER_NAME) as db:
            db.execute("UPDATE jobs SET relevance_hash = NULL WHERE id = ?", (job["id"],))
        _put_meta(client, presenter="김보고")
        view = client.get(f"/api/projects/p1/jobs/{job['id']}").json()
    assert view["stale_reasons"] == ["deck_changed"]


def test_structure_registration_rejects_a_brief_that_differs_from_the_report_info(store):
    _project(store)
    provider = GateProvider()
    provider.release.set()
    brief = {"decision_question": "확대할 것인가?", "audience": "", "report_type": "weekly"}
    with TestClient(create_app(store, provider=provider), headers=HEADERS) as client:
        response = _register(client, brief=brief)
    assert response.status_code == 422


# -- 장 후보 ---------------------------------------------------------------------

def _legacy_chapter_relevance(deck: Deck, chapter_id: str) -> str:
    """D3b 이전 빌드의 계산식 (메타 전체)."""
    chapter = next(c for c in deck.structure.chapters if c.id == chapter_id)
    plan = deck.structure.story_plan

    def digest(value) -> str:
        text = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    return "|".join([chapter.template, digest(chapter.model_dump(mode="json")),
                     digest({"plan": plan.model_dump(mode="json") if plan else None,
                             "meta": deck.meta.model_dump(mode="json")})])


def _chapter_job(client):
    return client.post("/api/projects/p1/jobs", json={"request_id": "chapter-0001", "kind": "chapter",
                                                       "params": {"chapter_id": "c1"}}).json()


def test_presenter_change_keeps_the_chapter_candidate(store):
    deck = _two_chapters(store)
    provider = ChapterGate(SLOTS)
    provider.release.set()
    with TestClient(create_app(store, provider=provider), headers=HEADERS) as client:
        job = _chapter_job(client)
        _wait_chapter(client, "p1", job["id"])
        store.save_deck("p1", _with_meta(deck, presenter="다른 보고자"), snapshot=False)
        view = client.get(f"/api/projects/p1/jobs/{job['id']}").json()
    assert view["candidate_status"] == "held" and view["stale_reasons"] == ["deck_changed_elsewhere"]


def test_old_chapter_rows_survive_the_first_type_confirmation(store):
    """업데이트 전 행은 옛 계산식에서 새 칸을 빼고 비교한다 (재리뷰 RR14)."""
    deck = _two_chapters(store)
    provider = ChapterGate(SLOTS)
    provider.release.set()
    with TestClient(create_app(store, provider=provider), headers=HEADERS) as client:
        job = _chapter_job(client)
        _wait_chapter(client, "p1", job["id"])
        with sqlite3.connect(store.root / LEDGER_NAME) as db:
            db.execute("UPDATE jobs SET relevance_hash = ? WHERE id = ?",
                       (_legacy_chapter_relevance(store.load_deck("p1"), "c1"), job["id"]))
        store.save_deck("p1", _with_meta(deck, report_type_confirmed=True, key_message="핵심"), snapshot=False)
        view = client.get(f"/api/projects/p1/jobs/{job['id']}").json()
    assert view["stale_reasons"] == ["deck_changed_elsewhere"]
