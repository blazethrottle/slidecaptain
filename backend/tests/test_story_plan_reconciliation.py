"""도식 장을 기존 StoryPlan에 연결하는 최소 왕복 계약."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from slidecaptain.models.deck import Deck
from slidecaptain.pipeline.story import (
    StaleStoryPlan,
    reconcile_diagram_story_plan,
    story_fingerprint,
)


@pytest.fixture
def project_input():
    sample = json.loads((Path(__file__).parent / "fixtures/q3b-project.json").read_text("utf-8"))
    deck = Deck.model_validate(sample["deck"])
    sources = sample["sources"]
    plan = deck.structure.story_plan
    plan.input_fingerprint = story_fingerprint(plan, deck.meta, deck.structure.chapters, sources)
    return deck, sources


def with_new_diagram(deck: Deck) -> Deck:
    candidate = deepcopy(deck)
    chapter = deepcopy(candidate.structure.chapters[1])
    chapter.id = "proposal-diagram"
    chapter.topic = "추가 제안 흐름"
    slide = deepcopy(candidate.slides[0])
    slide.chapter_id = chapter.id
    slide.slots.diagram.id = chapter.id
    candidate.structure.chapters.append(chapter)
    candidate.slides.append(slide)
    return candidate


def test_adds_diagram_assignment_and_recomputes_fingerprint(project_input):
    deck, sources = project_input
    candidate = with_new_diagram(deck)
    before = deepcopy(deck.structure.story_plan)

    updated = reconcile_diagram_story_plan(
        candidate,
        "proposal-diagram",
        "evidence",
        ["claim"],
        sources,
        base_deck=deck,
    )

    plan = updated.structure.story_plan
    assert [item.chapter_id for item in plan.chapters] == ["synthetic-flow", "proposal-diagram"]
    assert plan.chapters[-1].role == "evidence"
    assert plan.chapters[-1].claim_ids == ["claim"]
    assert plan.claims == before.claims
    assert plan.evidence == before.evidence
    assert plan.input_fingerprint == story_fingerprint(
        plan, updated.meta, updated.structure.chapters, sources,
    )
    assert plan.input_fingerprint != before.input_fingerprint
    assert deck.structure.story_plan == before


def test_rechecking_existing_diagram_replaces_its_assignment_without_duplicates(project_input):
    deck, sources = project_input

    updated = reconcile_diagram_story_plan(
        deck,
        "synthetic-flow",
        "answer",
        ["claim"],
        sources,
        base_deck=deck,
    )

    plan = updated.structure.story_plan
    assert len(plan.chapters) == 1
    assert plan.chapters[0].model_dump(mode="json") == {
        "chapter_id": "synthetic-flow", "role": "answer", "claim_ids": ["claim"],
    }


def test_rechecking_an_earlier_diagram_preserves_story_order_and_fingerprint(project_input):
    deck, sources = project_input
    linked = reconcile_diagram_story_plan(
        with_new_diagram(deck), "proposal-diagram", "evidence", ["claim"], sources, base_deck=deck,
    )
    previous = deepcopy(linked.structure.story_plan)
    first = previous.chapters[0]
    rechecked = reconcile_diagram_story_plan(
        linked, first.chapter_id, first.role, first.claim_ids, sources, base_deck=linked,
    )
    assert rechecked.structure.story_plan == previous


@pytest.mark.parametrize(
    ("chapter_id", "role", "claim_ids", "message"),
    [
        ("cover", "evidence", ["claim"], "도식 장"),
        ("synthetic-flow", "cover", ["claim"], "표지와 간지"),
        ("synthetic-flow", "evidence", ["missing"], "존재하지 않는 주장"),
        ("synthetic-flow", "evidence", ["claim", "claim"], "중복"),
    ],
)
def test_rejects_invalid_link(project_input, chapter_id, role, claim_ids, message):
    deck, sources = project_input
    with pytest.raises(ValueError, match=message):
        reconcile_diagram_story_plan(
            deck, chapter_id, role, claim_ids, sources, base_deck=deck,
        )


def test_source_change_cannot_be_approved_by_refreshing_fingerprint(project_input):
    deck, sources = project_input
    changed_sources = {**sources, next(iter(sources)): next(iter(sources.values())) + "\n변경"}

    with pytest.raises(StaleStoryPlan, match="자료"):
        reconcile_diagram_story_plan(
            deck, "synthetic-flow", "evidence", ["claim"], changed_sources, base_deck=deck,
        )


def test_candidate_cannot_refresh_an_unrelated_structure_change(project_input):
    deck, sources = project_input
    candidate = with_new_diagram(deck)
    candidate.structure.chapters[0].topic = "바뀐 표지"

    with pytest.raises(ValueError, match="도식 장 외부"):
        reconcile_diagram_story_plan(
            candidate,
            "proposal-diagram",
            "evidence",
            ["claim"],
            sources,
            base_deck=deck,
        )


def test_api_cannot_use_a_new_diagram_to_refresh_an_already_stale_saved_plan(project_input):
    deck, sources = project_input
    stale = deepcopy(deck)
    stale.structure.chapters[0].topic = "이미 바뀐 표지"
    candidate = with_new_diagram(stale)

    with pytest.raises(StaleStoryPlan, match="이미 낡았습니다"):
        reconcile_diagram_story_plan(
            candidate,
            "proposal-diagram",
            "evidence",
            ["claim"],
            sources,
            base_deck=stale,
        )


def test_api_returns_reconciled_candidate_without_saving(project_input, client, store):
    deck, sources = project_input
    candidate = with_new_diagram(deck)
    store.create_project("diagram-link")
    for filename, text in sources.items():
        store.write_source("diagram-link", filename, text)
    store.save_deck("diagram-link", deck)
    before_etag = store.deck_etag("diagram-link")
    before_snapshots = store.list_snapshots("diagram-link")

    response = client.post(
        "/api/projects/diagram-link/story-plan/diagram",
        json={
            "deck": candidate.model_dump(mode="json"),
            "chapter_id": "proposal-diagram",
            "role": "evidence",
            "claim_ids": ["claim"],
        },
    )

    assert response.status_code == 200
    assert response.headers["etag"] == f'"{before_etag}"'
    returned = Deck.model_validate(response.json())
    assert returned.structure.story_plan.chapters[-1].chapter_id == "proposal-diagram"
    assert store.deck_etag("diagram-link") == before_etag
    assert store.load_deck("diagram-link") == deck
    assert store.list_snapshots("diagram-link") == before_snapshots


def test_api_rejects_candidate_based_on_a_different_server_deck(project_input, client, store):
    deck, sources = project_input
    candidate = with_new_diagram(deck)
    candidate.structure.chapters[0].topic = "다른 표지"
    store.create_project("diagram-link")
    for filename, text in sources.items():
        store.write_source("diagram-link", filename, text)
    store.save_deck("diagram-link", deck)

    response = client.post(
        "/api/projects/diagram-link/story-plan/diagram",
        json={
            "deck": candidate.model_dump(mode="json"),
            "chapter_id": "proposal-diagram",
            "role": "evidence",
            "claim_ids": ["claim"],
        },
    )

    assert response.status_code == 422
    assert "도식 장 외부" in response.json()["detail"]


@pytest.mark.parametrize("failure", ["etag", "source"])
def test_api_rejection_preserves_deck_and_snapshots(project_input, client, store, monkeypatch, failure):
    deck, sources = project_input
    store.create_project("diagram-link")
    for filename, text in sources.items():
        store.write_source("diagram-link", filename, text)
    store.save_deck("diagram-link", deck)
    etag = store.deck_etag("diagram-link")
    snapshots = store.list_snapshots("diagram-link")
    if failure == "source":
        filename = next(iter(sources))
        store.write_source("diagram-link", filename, sources[filename] + "\n자료 변경")

    def unexpected_write(*args, **kwargs):
        pytest.fail("연결 확인에서 저장/스냅샷/사용량을 쓰면 안 된다")

    for method in ("save_deck", "snapshot_now", "append_usage"):
        monkeypatch.setattr(store, method, unexpected_write)
    response = client.post(
        "/api/projects/diagram-link/story-plan/diagram",
        headers={"If-Match": '"older"' if failure == "etag" else f'"{etag}"'},
        json={"deck": deck.model_dump(mode="json"), "chapter_id": "synthetic-flow",
              "role": "evidence", "claim_ids": ["claim"]},
    )
    assert response.status_code == (412 if failure == "etag" else 409)
    assert response.json().get("code") == (None if failure == "etag" else "stale_story_plan")
    assert store.deck_etag("diagram-link") == etag
    assert store.list_snapshots("diagram-link") == snapshots


def test_restoring_exact_source_allows_rechecking_without_changing_saved_deck(project_input, client, store):
    deck, sources = project_input
    store.create_project("restore-source")
    for filename, text in sources.items():
        store.write_source("restore-source", filename, text)
    store.save_deck("restore-source", deck)
    etag = store.deck_etag("restore-source")
    snapshots = store.list_snapshots("restore-source")
    filename = next(iter(sources))
    store.write_source("restore-source", filename, sources[filename] + "\n자료 변경")
    body = {"deck": deck.model_dump(mode="json"), "chapter_id": "synthetic-flow",
            "role": "answer", "claim_ids": ["claim"]}
    url = "/api/projects/restore-source/story-plan/diagram"
    rejected = client.post(url, json=body, headers={"If-Match": f'"{etag}"'})
    assert rejected.status_code == 409
    assert rejected.json().get("code") == "stale_story_plan"
    store.write_source("restore-source", filename, sources[filename])
    assert client.post(url, json=body, headers={"If-Match": f'"{etag}"'}).status_code == 200
    assert store.deck_etag("restore-source") == etag
    assert store.list_snapshots("restore-source") == snapshots


def test_api_story_validation_error_does_not_expose_model_input(project_input, client, store):
    deck, sources = project_input
    store.create_project("diagram-link")
    for filename, text in sources.items():
        store.write_source("diagram-link", filename, text)
    store.save_deck("diagram-link", deck)
    etag = store.deck_etag("diagram-link")
    snapshots = store.list_snapshots("diagram-link")
    response = client.post(
        "/api/projects/diagram-link/story-plan/diagram",
        json={"deck": deck.model_dump(mode="json"), "chapter_id": "synthetic-flow",
              "role": "evidence", "claim_ids": ["claim"]},
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "핵심 답변의 주장은 답변 역할의 장에 연결해야 합니다"
    assert store.deck_etag("diagram-link") == etag
    assert store.list_snapshots("diagram-link") == snapshots
