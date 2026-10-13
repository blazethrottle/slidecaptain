"""보존본 복원 전 차이 요약 (개정판 D3c-6, 계획 4.8의 E7)."""

from fastapi.testclient import TestClient

from slidecaptain.models.deck import Deck
from slidecaptain.pipeline.draft_summary import summarize_draft
from slidecaptain.server.app import create_app
from tests.test_jobs_batch import HEADERS, _project, slots


def _with(deck: Deck, **changes) -> Deck:
    return Deck.model_validate({**deck.model_dump(mode="json"), **changes})


def _deck(store):
    deck = _project(store)
    data = deck.model_dump(mode="json")
    data["slides"] = [{"chapter_id": "c1", "slots": slots("하나")}, {"chapter_id": "c2", "slots": slots("둘")}]
    return Deck.model_validate(data)


def test_summary_lists_changed_added_removed_and_edited_chapters(store):
    current = _deck(store)
    data = current.model_dump(mode="json")
    data["slides"][0]["slots"]["conclusion"] = "고친 하나"  # 내용이 다른 장
    data["slides"][1]["direct_edits"] = {"conclusion": {"dx_pt": 5, "dy_pt": 0}}  # 수정만 다른 장
    chapters = data["structure"]["chapters"]
    data["structure"]["chapters"] = [chapters[1], chapters[0], {**chapters[2], "id": "c9", "topic": "새 장"}]
    summary = summarize_draft(current, data, "editor")
    assert summary.readable and not summary.purpose_only
    assert [c.label for c in summary.changed_chapters] == ["2장 주제 1"]
    assert [c.label for c in summary.direct_edit_chapters] == ["1장 주제 2"]
    assert [c.label for c in summary.added_chapters] == ["3장 새 장"]
    assert [c.label for c in summary.removed_chapters] == ["3장 주제 3"]
    assert summary.order_changed and not summary.report_info_changed and not summary.story_plan_changed


def test_purpose_drafts_only_compare_report_info_and_unreadable_drafts_are_not_summarized(store):
    current = _deck(store)
    data = current.model_dump(mode="json")
    data["meta"]["key_message"] = "핵심 내용"
    data["slides"] = []
    purpose = summarize_draft(current, data, "purpose")
    assert purpose.readable and purpose.purpose_only and purpose.report_info_changed
    assert purpose.removed_chapters == [] and purpose.changed_chapters == []  # 복원은 보고 정보만 바꾼다
    broken = summarize_draft(current, {"meta": {}}, "editor")
    assert not broken.readable and broken.changed_chapters == []
    same = summarize_draft(current, current.model_dump(mode="json"), "editor")
    assert same.readable and not any([same.changed_chapters, same.added_chapters, same.removed_chapters,
                                      same.direct_edit_chapters, same.report_info_changed, same.order_changed])


def test_summary_route_reads_the_draft_without_restoring_it(store):
    current = _deck(store)
    store.save_deck("p1", current, snapshot=False)
    data = current.model_dump(mode="json")
    data["slides"][0]["slots"]["conclusion"] = "보존한 결론"
    info = store.save_draft("p1", deck=data, reason="conflict", source="editor", base_etag=None)
    before = (store.root / "p1" / "deck.json").read_bytes()
    with TestClient(create_app(store), headers=HEADERS) as client:
        response = client.get(f"/api/projects/p1/drafts/{info.id}/summary")
        missing = client.get("/api/projects/p1/drafts/draft-20990101-000000-000000/summary")
    assert response.status_code == 200 and [c["label"] for c in response.json()["changed_chapters"]] == ["1장 주제 1"]
    assert missing.status_code == 404
    assert (store.root / "p1" / "deck.json").read_bytes() == before
