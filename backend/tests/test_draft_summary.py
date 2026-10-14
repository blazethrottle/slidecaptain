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


def test_design_values_and_document_review_are_reported_and_only_a_whole_match_is_clean(store):
    """복원은 덱 전체를 쓰므로 디자인 값과 검토 기록만 다른 보존본도 "다른 점이 없다"가 아니다 (D3c-6 리뷰 G4)."""
    current = _deck(store)
    data = current.model_dump(mode="json")
    data["meta"]["preset_overrides"] = {"font_scale": 1.1}
    design = summarize_draft(current, data, "editor")
    assert design.design_changed and not design.report_info_changed and not design.review_changed
    data = current.model_dump(mode="json")
    data["document_review"] = {"reason": "document_replacement", "base_fingerprint": "a" * 64,
                               "changed_paths": ["slides/0"]}
    review = summarize_draft(current, data, "editor")
    assert review.review_changed and not review.design_changed
    same = summarize_draft(current, current.model_dump(mode="json"), "editor")
    assert not same.design_changed and not same.review_changed and same.current_readable


def test_chapter_order_ignores_added_chapters_and_a_changed_topic_is_a_changed_chapter(store):
    current = _deck(store)
    data = current.model_dump(mode="json")
    data["structure"]["chapters"].append({**data["structure"]["chapters"][2], "id": "c9", "topic": "더한 장"})
    added = summarize_draft(current, data, "editor")
    assert [c.label for c in added.added_chapters] == ["4장 더한 장"] and not added.order_changed  # 리뷰 V22
    data = current.model_dump(mode="json")
    del data["structure"]["chapters"][1]  # 가운데 장만 빠진 보존본도 순서 차이가 아니다(리뷰 V22)
    data["slides"] = [sl for sl in data["slides"] if sl["chapter_id"] != "c2"]
    assert summarize_draft(current, data, "editor").readable
    removed = summarize_draft(current, data, "editor")
    assert [c.label for c in removed.removed_chapters] == ["2장 주제 2"] and not removed.order_changed
    data = current.model_dump(mode="json")
    data["structure"]["chapters"][2]["topic"] = "바꾼 주제"  # 슬라이드가 없는 장: 장 정의만 다르다
    topic = summarize_draft(current, data, "editor")
    assert [c.label for c in topic.changed_chapters] == ["3장 바꾼 주제"]  # 리뷰 V23


def test_unreadable_saved_deck_summarizes_a_whole_restore_even_for_purpose_drafts(store):
    """저장본을 읽지 못하면 복원은 보존본 전체를 쓴다. 요약도 그렇게 말한다 (D3c-6 리뷰 G10)."""
    current = _deck(store)
    data = current.model_dump(mode="json")
    purpose = summarize_draft(None, data, "purpose")
    assert purpose.readable and not purpose.purpose_only and not purpose.current_readable
    assert [c.label for c in purpose.added_chapters] == ["1장 주제 1", "2장 주제 2", "3장 주제 3"]
    store.save_deck("p1", current, snapshot=False)
    info = store.save_draft("p1", deck=data, reason="conflict", source="purpose", base_etag=None)
    (store.root / "p1" / "deck.json").write_text("{", encoding="utf-8")  # 저장본을 읽지 못한다(리뷰 V24)
    with TestClient(create_app(store), headers=HEADERS) as client:
        response = client.get(f"/api/projects/p1/drafts/{info.id}/summary")
    assert response.status_code == 200, response.text
    assert response.json()["current_readable"] is False and response.json()["purpose_only"] is False
