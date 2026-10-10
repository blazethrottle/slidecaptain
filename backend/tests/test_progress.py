"""단계 준비 모델 (개정판 D2a-6).

현재 저장 계약으로 판정할 수 있는 것만 판정하고, 판정할 수 없는 것은 사유 코드로 남긴다.
기본값을 사용자가 확정한 값으로 표시하지 않는다. 화면 연결은 D3다.
"""

import json
from pathlib import Path

import pytest

from slidecaptain.models.deck import Deck
from slidecaptain.pipeline.progress import project_progress

FIXTURES = Path(__file__).parent / "fixtures"


def _fixture(name):
    data = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return Deck.model_validate(data["deck"]), data["sources"]


def _stage(progress, name):
    return next(s for s in progress.stages if s.stage == name)


def test_purpose_is_never_ready_from_defaults():
    deck, sources = _fixture("q3b-project.json")
    purpose = _stage(project_progress(deck, sources=sources), "purpose")
    assert purpose.state == "needs_review"
    assert "report_type_unconfirmed" in purpose.reasons
    deck.meta.title = ""
    assert _stage(project_progress(deck, sources=sources), "purpose").state == "not_started"


def test_sources_states_and_unavailable_review_reason():
    deck, sources = _fixture("q3b-project.json")
    ready = _stage(project_progress(deck, sources=sources), "sources")
    assert ready.state == "ready"
    # 다시 씀(D3a 묶음 리뷰 A15): 부분 추출 경고가 저장되지 않는다는 한계(D5)는 엑셀 추출본이 있을 때만 붙는다
    assert "extraction_review_unavailable" not in ready.reasons
    with_xlsx = _stage(project_progress(deck, sources={**sources, "매출.xlsx.md": "표"}), "sources")
    assert (with_xlsx.state, with_xlsx.reasons) == ("ready", ["extraction_review_unavailable"])
    assert _stage(project_progress(deck, sources={}), "sources").state == "not_started"
    big = {"a.md": "가" * 100_001}
    over = _stage(project_progress(deck, sources=big), "sources")
    assert (over.state, over.reasons[0]) == ("needs_review", "sources_over_limit")
    unreadable = _stage(project_progress(deck, sources=None, sources_error="읽기 실패"), "sources")
    assert (unreadable.state, unreadable.reasons[0]) == ("needs_review", "sources_unreadable")


def test_structure_current_stale_missing_and_empty():
    deck, sources = _fixture("q3b-project.json")
    assert _stage(project_progress(deck, sources=sources), "structure").state == "ready"
    changed = {**sources, "새 자료.md": "추가"}
    stale = _stage(project_progress(deck, sources=changed), "structure")
    assert (stale.state, stale.reasons) == ("needs_review", ["stale_story_plan"])
    deck.structure.story_plan = None
    missing = _stage(project_progress(deck, sources=sources), "structure")
    # 다시 씀(D3a 묶음 리뷰 A3): 보고 질문은 선택 입력이라 보고 계획 없음은 준비됨에 붙는 한계다
    assert (missing.state, missing.reasons) == ("ready", ["plan_missing"])
    deck.structure.chapters = []
    assert _stage(project_progress(deck, sources=sources), "structure").state == "not_started"


def test_title_and_chapter_topic_edits_make_structure_need_review():
    """구성 낡음 판정은 제목, 피보고자, 보고 유형, 장 제목과 결론도 본다(생성 관문과 같은 계약)."""
    deck, sources = _fixture("q3b-project.json")
    deck.meta.title = deck.meta.title + " 수정"
    assert _stage(project_progress(deck, sources=sources), "structure").reasons == ["stale_story_plan"]
    deck, sources = _fixture("q3b-project.json")
    deck.structure.chapters[0].topic = deck.structure.chapters[0].topic + " 수정"
    assert _stage(project_progress(deck, sources=sources), "structure").reasons == ["stale_story_plan"]


def test_report_type_change_affects_structure_but_not_sources():
    deck, sources = _fixture("q3b-project.json")
    deck.meta.report_type = "weekly"
    progress = project_progress(deck, sources=sources)
    assert _stage(progress, "structure").reasons == ["stale_story_plan"]
    assert _stage(progress, "sources").state == "ready"


def test_editing_counts_written_chapters():
    deck, sources = _fixture("q2a-story-deck.json")
    editing = _stage(project_progress(deck, sources=sources), "editing")
    assert (editing.state, editing.written_chapters, editing.total_chapters) == ("not_started", 0, 3)
    deck, sources = _fixture("q3b-project.json")
    full = _stage(project_progress(deck, sources=sources), "editing")
    assert (full.state, full.written_chapters, full.total_chapters) == ("ready", 2, 2)
    deck.slides = deck.slides[:1]
    partial = _stage(project_progress(deck, sources=sources), "editing")
    assert (partial.state, partial.reasons) == ("needs_review", ["chapters_unwritten"])


def test_review_reports_three_parts_separately():
    from slidecaptain.models.export_history import ExportHistoryItem

    deck, sources = _fixture("q3b-project.json")
    review = _stage(project_progress(deck, sources=sources), "review")
    assert review.state == "not_started"
    assert {p.name: p.state for p in review.parts} == {
        "auto_checks": "not_started", "human_review": "not_started", "file": "not_started"}
    item = ExportHistoryItem(id="x", file_modified_at=None, record_status="readable", artifact_status="matched",
                             input_status="stale", quality_status="needs_revision", slide_count=2, gate_version=None)
    review = _stage(project_progress(deck, sources=sources, latest_export=item), "review")
    parts = {p.name: (p.state, p.reasons) for p in review.parts}
    assert parts["file"] == ("needs_review", ["input_stale"])
    assert parts["auto_checks"] == ("needs_review", ["quality_needs_revision"])
    assert review.state == "needs_review"


def test_jobs_slot_is_reserved_for_the_job_ledger():
    deck, sources = _fixture("q3b-project.json")
    assert project_progress(deck, sources=sources).jobs is None


# -- API --------------------------------------------------------------------------------


def test_progress_route_is_200_for_ok_recovery_and_newer_projects(client, store):
    client.post("/api/projects", json={"name": "p1"})
    body = client.get("/api/projects/p1/progress").json()
    assert body["project_status"] == "ok"
    assert [s["stage"] for s in body["stages"]] == ["purpose", "sources", "structure", "editing", "review"]
    (store.root / "p1" / "deck.json").write_text("{깨진", encoding="utf-8")
    broken = client.get("/api/projects/p1/progress")
    assert broken.status_code == 200
    assert broken.json() == {"project_status": "needs_recovery", "stages": None, "jobs": None}
    client.post("/api/projects", json={"name": "p2"})
    manifest = store.root / "p2" / "manifest.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["format_version"] = 99
    manifest.write_text(json.dumps(data), encoding="utf-8")
    newer = client.get("/api/projects/p2/progress").json()
    assert newer == {"project_status": "newer_format", "stages": None, "jobs": None}
    assert client.get("/api/projects/없음/progress").status_code == 404


def test_progress_reads_only_the_latest_export_record(client, monkeypatch):
    import slidecaptain.server.app as app_module

    seen = []
    original = app_module.read_export_history

    def spy(directory, **kwargs):
        seen.append(kwargs.get("limit"))
        return original(directory, **kwargs)

    monkeypatch.setattr(app_module, "read_export_history", spy)
    client.post("/api/projects", json={"name": "p1"})
    assert client.get("/api/projects/p1/progress").status_code == 200
    assert seen == [1]


def test_unreadable_export_history_is_not_reported_as_no_export():
    deck, sources = _fixture("q3b-project.json")
    review = _stage(project_progress(deck, sources=sources, export_error="읽기 실패"), "review")
    assert review.state == "needs_review"
    assert {p.name: p.reasons for p in review.parts} == {
        "auto_checks": ["export_history_unreadable"], "human_review": ["export_history_unreadable"],
        "file": ["export_history_unreadable"]}


# -- D2a 묶음 최종 리뷰 반영 (F1, F4, F5, F6) ---------------------------------------------


def _exported_project(client, store, count=3):
    from slidecaptain.models.deck import BulletBoxSlots, Chapter, Slide

    store.create_project("px", "합성")
    deck = store.load_deck("px")
    deck.structure.chapters = [Chapter(id="c1", topic="합성", template="bullet_box")]
    deck.slides = [Slide(chapter_id="c1", slots=BulletBoxSlots(bullets=[], conclusion="합성 초안"))]
    store.save_deck("px", deck)
    store.write_source("px", "자료.md", "합성 자료")
    for _ in range(count):
        assert client.post("/api/projects/px/export").status_code == 200


def test_invalid_project_name_is_an_error_not_a_recovery_state(client):
    assert client.get("/api/projects/.hidden/progress").status_code == 422
    assert client.get("/api/projects/.hidden/deck").status_code == 422


def test_unreadable_manifest_and_snapshot_only_projects(client, store):
    client.post("/api/projects", json={"name": "p1"})
    (store.root / "p1" / "manifest.json").write_text("{깨진", encoding="utf-8")
    assert client.get("/api/projects/p1/progress").json()["project_status"] == "unreadable_manifest"
    client.post("/api/projects", json={"name": "p2"})
    deck = client.get("/api/projects/p2/deck").json()
    deck["meta"]["title"] = "두 번째"
    assert client.put("/api/projects/p2/deck?snapshot=true", json=deck).status_code == 200
    (store.root / "p2" / "deck.json").unlink()
    assert client.get("/api/projects/p2/progress").json()["project_status"] == "needs_recovery"
    (store.root / "p3" / "snapshots").mkdir(parents=True)
    assert client.get("/api/projects/p3/progress").status_code == 404


def test_progress_inspects_only_the_latest_of_many_exports_and_measures_once(client, store, monkeypatch):
    import slidecaptain.export.history as history
    import slidecaptain.server.app as app_module

    _exported_project(client, store, count=3)
    inspected, measured = [], []
    real_inspect, real_plan = history._inspect, app_module.build_render_plan
    monkeypatch.setattr(history, "_inspect", lambda *a, **k: inspected.append(a[1]) or real_inspect(*a, **k))
    monkeypatch.setattr(app_module, "build_render_plan", lambda *a, **k: measured.append(1) or real_plan(*a, **k))
    body = client.get("/api/projects/px/progress").json()
    # 최신 기록만 본다(이력 조회와 검수 기록 조회가 같은 최신 기록을 본다). 이전 기록 2건은 보지 않는다
    assert set(inspected) == {"합성_v003"}
    assert len(measured) == 1
    review = next(s for s in body["stages"] if s["stage"] == "review")
    assert {p["name"]: p["state"] for p in review["parts"]}["file"] == "ready"


def test_source_change_marks_the_latest_export_input_stale(client, store):
    _exported_project(client, store, count=1)
    store.write_source("px", "자료.md", "바뀐 자료")
    body = client.get("/api/projects/px/progress").json()
    review = next(s for s in body["stages"] if s["stage"] == "review")
    assert {p["name"]: p["reasons"] for p in review["parts"]}["file"] == ["input_stale"]


@pytest.mark.parametrize("statuses, state, reasons", [
    (["not_run"] * 5, "not_started", []),
    (["passed"] * 5, "ready", ["manual_pass_not_final"]),
    (["passed", "needs_revision", "stale", "passed", "passed"], "needs_review", ["review_needs_revision", "review_stale"]),
])
def test_human_review_part_states(statuses, state, reasons):
    from types import SimpleNamespace

    deck, sources = _fixture("q3b-project.json")
    reviews = SimpleNamespace(categories=[SimpleNamespace(status=s) for s in statuses])
    review = _stage(project_progress(deck, sources=sources, reviews=reviews), "review")
    human = next(p for p in review.parts if p.name == "human_review")
    assert (human.state, human.reasons) == (state, reasons)
    errored = _stage(project_progress(deck, sources=sources, reviews_error="읽기 실패"), "review")
    assert next(p for p in errored.parts if p.name == "human_review").reasons == ["review_records_unreadable"]


# -- D3a-3: 사유 고정 목록과 검토 단계 수준 사유 ----------------------------------------------------------

def _every_reason_produced():
    """모듈의 모든 분기를 지나 낼 수 있는 사유를 실제로 만든다. 조합 사유는 원천 상태 목록을 모두 돈다."""
    from typing import get_args
    from types import SimpleNamespace

    from slidecaptain.models.export_history import ExportHistoryItem
    from slidecaptain.models.export_reviews import ExportReviewCategoryState

    produced = set()

    def take(progress):
        for stage in progress.stages:
            produced.update(stage.reasons)
            for part in stage.parts or []:
                produced.update(part.reasons)

    deck, sources = _fixture("q3b-project.json")
    take(project_progress(deck, sources=sources))
    take(project_progress(deck, sources={}))
    take(project_progress(deck, sources={"a.md": "가" * 100_001}))
    take(project_progress(deck, sources=None, sources_error="읽기 실패"))
    take(project_progress(deck, sources={**sources, "새 자료.md": "추가"}))
    take(project_progress(deck, sources={**sources, "매출.xlsx.md": "표"}))  # 엑셀 추출본의 한계 (A15)
    take(project_progress(deck, sources=sources, export_error="이력 읽기 실패"))
    take(project_progress(deck, sources=sources, reviews_error="읽기 실패",
                          latest_export=ExportHistoryItem(id="x", file_modified_at=None, record_status="readable",
                                                          artifact_status="matched", input_status="current",
                                                          quality_status="draft", slide_count=2, gate_version=None)))
    status_values = get_args(ExportReviewCategoryState.model_fields["status"].annotation)
    for status in status_values:
        reviews = SimpleNamespace(categories=[SimpleNamespace(status="passed"), SimpleNamespace(status=status)])
        take(project_progress(deck, sources=sources, reviews=reviews))
    take(project_progress(deck, sources=sources, reviews=SimpleNamespace(categories=[SimpleNamespace(status="passed")])))
    artifact_values = get_args(ExportHistoryItem.model_fields["artifact_status"].annotation)
    input_values = get_args(ExportHistoryItem.model_fields["input_status"].annotation)
    for artifact in artifact_values:
        for inp in input_values:
            for quality in ("draft", "needs_revision", None):
                item = ExportHistoryItem(id="x", file_modified_at=None, record_status="readable", artifact_status=artifact,
                                         input_status=inp, quality_status=quality, slide_count=2, gate_version=None)
                take(project_progress(deck, sources=sources, latest_export=item))
    deck.slides = deck.slides[:1]
    take(project_progress(deck, sources=sources))
    deck.structure.story_plan = None
    take(project_progress(deck, sources=sources))
    deck.structure.chapters = []
    deck.meta.title = ""
    take(project_progress(deck, sources=sources))
    return produced


def test_progress_reasons_are_a_closed_list_that_every_branch_covers():
    """사유는 고정 목록이고(OpenAPI와 화면 타입에 나온다), 목록의 값은 모두 실제로 나올 수 있다 (D3a-3, 계획 4.2)."""
    from typing import get_args

    from slidecaptain.pipeline.progress import ProgressReason

    assert _every_reason_produced() == set(get_args(ProgressReason))


def test_review_stage_names_what_remains_when_parts_are_mixed():
    """검토 단계가 확인 필요이면 준비되지 않은 부분을 단계 수준 사유로 돌려준다 (C20)."""
    from types import SimpleNamespace

    from slidecaptain.models.export_history import ExportHistoryItem

    deck, sources = _fixture("q3b-project.json")
    item = ExportHistoryItem(id="x", file_modified_at=None, record_status="readable", artifact_status="matched",
                             input_status="current", quality_status="draft", slide_count=2, gate_version=None)
    review = _stage(project_progress(deck, sources=sources, latest_export=item), "review")
    assert (review.state, review.reasons) == ("needs_review", ["human_review_pending"])  # 자동 검사와 파일은 준비됨
    # 확인이 필요한 부분은 남은 일이 아니라 그 부분의 사유를 올린다. 파일, 자동 검사, 사람 검토 순서다 (D3a-3 리뷰 R3)
    found = ExportHistoryItem(id="x", file_modified_at=None, record_status="readable", artifact_status="matched",
                              input_status="stale", quality_status="needs_revision", slide_count=2, gate_version=None)
    stale_review = SimpleNamespace(categories=[SimpleNamespace(status="passed"), SimpleNamespace(status="stale")])
    mixed = _stage(project_progress(deck, sources=sources, latest_export=found, reviews=stale_review), "review")
    assert mixed.reasons == ["input_stale", "quality_needs_revision", "review_stale"]
    done = SimpleNamespace(categories=[SimpleNamespace(status="passed")] * 5)
    ready = _stage(project_progress(deck, sources=sources, latest_export=item, reviews=done), "review")
    assert (ready.state, ready.reasons) == ("ready", [])
    assert _stage(project_progress(deck, sources=sources), "review").reasons == []  # 시작 전에는 사유가 없다
    unreadable = _stage(project_progress(deck, sources=sources, export_error="읽기 실패"), "review")
    assert unreadable.reasons == ["export_history_unreadable"]
