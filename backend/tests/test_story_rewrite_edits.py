"""AI는 변경 가능한 계획만 반환하고 보호 문맥은 서버가 보존한다."""
from copy import deepcopy
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from scripts.quality_pilot import scenario
from slidecaptain.models.deck import Deck
from slidecaptain.models.story import ReportBrief
from slidecaptain.pipeline.provider import ProviderResponse
from slidecaptain.pipeline.rewrite import (
    RewriteDraft, parse_story_rewrite, protected_story, validate_rewrite,
)
from slidecaptain.pipeline.story import require_current_story, story_fingerprint
from slidecaptain.server.app import create_app


@pytest.fixture
def edit_case():
    data = scenario()
    deck = Deck.model_validate(data["deck"])
    payload = {
        "chapter_order": ["cover", "pilot-action", "synthetic-flow"],
        "chapters": [
            {"chapter_id": "cover", "role": "cover", "claim_ids": []},
            {"chapter_id": "pilot-action", "role": "action", "claim_ids": ["action"]},
        ],
        "evidence": [],
        "claims": [deck.structure.story_plan.claims[-1].model_dump()],
        "answer_claim_ids": ["claim"], "unanswered_questions": [],
        "comparisons": [], "derivations": [],
    }
    return deck, data["sources"], ReportBrief.model_validate(data["rewrite_brief"]), payload


def test_edits_restore_protected_graph_without_echoing_it(edit_case):
    deck, sources, brief, payload = edit_case
    before, response_before = deck.model_dump_json(), deepcopy(payload)
    candidate = parse_story_rewrite(payload, deck, brief, sources)
    assert [c.id for c in candidate.structure.chapters] == payload["chapter_order"]
    assert protected_story(candidate, sources) == protected_story(deck, sources)
    assert candidate.slides == deck.slides
    assert candidate.structure.chapters[1].source_refs == list(sources)
    assert candidate.structure.story_plan.brief == brief
    require_current_story(candidate, sources)
    assert deck.model_dump_json() == before
    assert payload == response_before


def test_only_diagram_needs_no_editable_claims_or_assignments(edit_case):
    deck, sources, brief, payload = edit_case
    raw = deck.model_dump(mode="json")
    raw["structure"]["chapters"] = [c for c in raw["structure"]["chapters"] if c["template"] == "diagram"]
    raw["slides"] = [s for s in raw["slides"] if s["slots"]["template"] == "diagram"]
    raw["structure"]["story_plan"]["chapters"] = [raw["structure"]["story_plan"]["chapters"][0]]
    raw["structure"]["story_plan"]["claims"] = [raw["structure"]["story_plan"]["claims"][0]]
    deck = Deck.model_validate(raw)
    payload.update(chapter_order=["synthetic-flow"], chapters=[], claims=[])
    candidate = parse_story_rewrite(payload, deck, brief, sources)
    assert candidate.structure.story_plan.claims == deck.structure.story_plan.claims
    assert candidate.slides == deck.slides
    assert RewriteDraft.model_validate(payload).claims == []


@pytest.mark.parametrize("defect", [
    "order_missing", "order_duplicate", "order_unknown", "chapter_missing", "chapter_duplicate",
    "chapter_unknown", "orphan_claim", "unknown_evidence", "unknown_answer", "duplicate_claim",
])
def test_edits_reject_incomplete_or_ambiguous_graph(edit_case, defect):
    deck, sources, brief, payload = edit_case
    if defect == "order_missing": payload["chapter_order"].pop()
    if defect == "order_duplicate": payload["chapter_order"].append("cover")
    if defect == "order_unknown": payload["chapter_order"][0] = "absent"
    if defect == "chapter_missing": payload["chapters"].pop()
    if defect == "chapter_duplicate": payload["chapters"].append(payload["chapters"][0])
    if defect == "chapter_unknown": payload["chapters"][0]["chapter_id"] = "absent"
    if defect == "orphan_claim": payload["claims"].append({**payload["claims"][0], "id": "orphan"})
    if defect == "unknown_evidence": payload["claims"][0]["evidence_ids"] = ["absent"]
    if defect == "unknown_answer": payload["answer_claim_ids"] = ["absent"]
    if defect == "duplicate_claim": payload["claims"].append(payload["claims"][0])
    before = deck.model_dump_json()
    with pytest.raises(ValueError):
        parse_story_rewrite(payload, deck, brief, sources)
    assert deck.model_dump_json() == before


@pytest.mark.parametrize("field,changed", [(k, c) for k in ["evidence", "claims", "chapters"] for c in [False, True]])
def test_protected_ids_are_rejected_even_when_echo_is_identical(edit_case, field, changed):
    deck, sources, brief, payload = edit_case
    item = deepcopy(protected_story(deck, sources)[field][0])
    if field == "evidence":
        item.pop("source_revision")
        excerpt = item.pop("excerpt")
        if changed: item["value"] = excerpt  # First actual LUNA failure: null became source text.
    if field == "claims" and changed: item["statement"] = "변경된 주장"
    if field == "chapters" and changed: item["claim_ids"].append("action")
    payload[field].append(item)
    with pytest.raises(ValueError, match="보호"):
        parse_story_rewrite(payload, deck, brief, sources)


def _with_protected_calculation(deck, sources):
    raw = deck.model_dump(mode="json")
    plan = raw["structure"]["story_plan"]
    plan["version"] = "q2c-v1"
    plan["comparisons"] = [{"id": "kept-comparison", "claim_id": "claim", "left_evidence_id": "e1", "right_evidence_id": "e2", "axis": "entity"}]
    plan["derivations"] = [{"id": "kept-calculation", "comparison_id": "kept-comparison", "operation": "difference"}]
    deck = Deck.model_validate(raw)
    deck.structure.story_plan.input_fingerprint = story_fingerprint(deck.structure.story_plan, deck.meta, deck.structure.chapters, sources)
    return deck


def test_protected_comparison_and_derivation_are_copied_with_blocked_results(edit_case):
    deck, sources, brief, payload = edit_case
    deck = _with_protected_calculation(deck, sources)
    candidate = parse_story_rewrite(payload, deck, brief, sources)
    assert protected_story(candidate, sources) == protected_story(deck, sources)
    assert candidate.structure.story_plan.derived_values == deck.structure.story_plan.derived_values
    assert candidate.structure.story_plan.derived_values[0].status == "blocked"


def test_general_claim_can_compare_protected_evidence_without_changing_protected_graph(edit_case):
    deck, sources, brief, payload = edit_case
    payload["claims"][0]["evidence_ids"] = ["e1", "e2"]
    payload["comparisons"] = [{"id": "new-comparison", "claim_id": "action", "left_evidence_id": "e1", "right_evidence_id": "e2", "axis": "entity"}]
    payload["derivations"] = [{"id": "new-calculation", "comparison_id": "new-comparison", "operation": "difference"}]
    candidate = parse_story_rewrite(payload, deck, brief, sources)
    assert protected_story(candidate, sources) == protected_story(deck, sources)
    assert candidate.structure.story_plan.comparisons[0].id == "new-comparison"
    assert candidate.structure.story_plan.derivations[0].id == "new-calculation"


@pytest.mark.parametrize("evidence_id", ["e1", "e3"])
def test_node_or_edge_only_evidence_is_preserved_and_source_changes_are_rejected(edit_case, evidence_id):
    from slidecaptain.pipeline.rewrite import ProtectedEvidenceChanged, rewrite_prompt
    deck, sources, brief, payload = edit_case
    # e1 is referenced by a node and e3 by an edge, even without a diagram claim.
    deck.structure.story_plan.claims[0].evidence_ids.remove(evidence_id)
    candidate = parse_story_rewrite(payload, deck, brief, sources)
    assert protected_story(candidate, sources) == protected_story(deck, sources)
    assert evidence_id in {e.id for e in candidate.structure.story_plan.evidence}
    changed = {name: text + "\n변경된 문맥" for name, text in sources.items()}
    with pytest.raises(ProtectedEvidenceChanged):
        rewrite_prompt(deck, brief, changed, "")


def test_computed_protected_calculations_survive_edits(edit_case):
    deck, sources, brief, payload = edit_case
    numeric = json.loads((Path(__file__).parent / "fixtures/q2c-derived-deck.json").read_text("utf-8"))
    other = numeric["deck"]["structure"]["story_plan"]
    # Keep the numeric fixture's metadata and replace only colliding IDs.
    for item in other["evidence"]: item["id"] = "numeric-" + item["id"]
    for claim in other["claims"]: claim["evidence_ids"] = ["numeric-" + key for key in claim["evidence_ids"]]
    for comparison in other["comparisons"]:
        for field in ("left_evidence_id", "right_evidence_id"): comparison[field] = "numeric-" + comparison[field]
    raw = deck.model_dump(mode="json")
    plan = raw["structure"]["story_plan"]
    plan["version"] = "q2c-v1"
    for key in ("evidence", "claims", "comparisons", "derivations"): plan[key].extend(other[key])
    plan["chapters"][0]["claim_ids"].append("k1")
    deck = Deck.model_validate(raw)
    sources = {**sources, **numeric["sources"]}
    candidate = parse_story_rewrite(payload, deck, brief, sources)
    assert protected_story(candidate, sources) == protected_story(deck, sources)
    assert candidate.structure.story_plan.derived_values == deck.structure.story_plan.derived_values
    assert [v.status for v in candidate.structure.story_plan.derived_values] == ["computed", "computed"]
    assert [v.value for v in candidate.structure.story_plan.derived_values] == ["200", "20"]


@pytest.mark.parametrize("field,new_id", [(k, n) for k in ["comparisons", "derivations"] for n in [False, True]])
def test_cannot_extend_protected_calculations_using_new_ids(edit_case, field, new_id):
    deck, sources, brief, payload = edit_case
    deck = _with_protected_calculation(deck, sources)
    item = deepcopy(protected_story(deck, sources)[field][0])
    if new_id: item["id"] = "new-id"
    payload[field].append(item)
    with pytest.raises(ValueError, match="보호"):
        parse_story_rewrite(payload, deck, brief, sources)


@pytest.mark.parametrize("defect", ["value", "diagram_claims"])
def test_apply_still_rejects_original_luna_protection_failures(edit_case, defect):
    deck, sources, brief, payload = edit_case
    candidate = parse_story_rewrite(payload, deck, brief, sources)
    plan = candidate.structure.story_plan
    if defect == "value": plan.evidence[0].value = plan.evidence[0].excerpt
    else: next(c for c in plan.chapters if c.chapter_id == "synthetic-flow").claim_ids.append("action")
    plan.input_fingerprint = story_fingerprint(plan, candidate.meta, candidate.structure.chapters, sources)
    with pytest.raises(ValueError, match="보존"):
        validate_rewrite(deck, candidate, sources)


@pytest.mark.parametrize("defect", ["protected_echo", "answer_role"])
def test_api_retries_invalid_edits_then_applies_without_saving_preview(edit_case, store, defect):
    deck, sources, brief, payload = edit_case
    store.create_project("rewrite-edits")
    for name, content in sources.items(): store.write_source("rewrite-edits", name, content)
    store.save_deck("rewrite-edits", deck, snapshot=False)
    bad = deepcopy(payload)
    if defect == "protected_echo":
        bad["chapters"].append({"chapter_id": "synthetic-flow", "role": "answer", "claim_ids": ["claim", "action"]})
    else:
        # LUNA's 2026-09-29 first response linked an action-only claim to the answer.
        bad["answer_claim_ids"].append("action")

    class Provider:
        def __init__(self): self.calls = []
        async def complete(self, prompt, schema):
            self.calls.append((prompt, schema))
            return ProviderResponse(structured=deepcopy(bad if len(self.calls) == 1 else payload), raw_text="synthetic")

    provider = Provider()
    etag = store.deck_etag("rewrite-edits")
    with TestClient(create_app(store, provider=provider), headers={
        "X-Requested-With": "SlideCaptain", "X-AI-Consent": "SlideCaptain", "If-Match": f'"{etag}"',
    }) as client:
        response = client.post("/api/projects/rewrite-edits/story-plan/rewrite", json={"brief": brief.model_dump(), "instructions": "내용 보존"})
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["status"] == "ok", result
        assert result["format_retried"] and result["usage"]["calls"] == 2
        assert store.deck_etag("rewrite-edits") == etag
        assert store.list_snapshots("rewrite-edits") == []
        schema = provider.calls[0][1]
        assert "chapter_order" in schema["required"]
        assert "minItems" not in schema["properties"]["claims"]
        assert "기존 모든 장 ID를 정확히 한 번씩 chapters에 포함" not in provider.calls[0][0]
        response = client.post("/api/projects/rewrite-edits/story-plan/rewrite/apply", json={
            "deck": result["deck"], "sources_fingerprint": result["sources_fingerprint"],
        }, headers={"If-Match": result["base_etag"]})
        assert response.status_code == 200, response.text
    assert store.load_deck("rewrite-edits").slides == deck.slides
    assert len(store.list_snapshots("rewrite-edits")) == 1
