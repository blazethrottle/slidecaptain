"""Q2d: exact expression/source linkage, never a general semantic verdict."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from slidecaptain.models.deck import Deck
from slidecaptain.pipeline.numeric_review import assess_numeric_review, chapter_numeric_expressions
from slidecaptain.pipeline.story import parse_story_structure, story_fingerprint
from slidecaptain.server.app import create_app
from test_derived_values import BRIEF, sample
from test_metric_comparison import META

FIXTURE = Path(__file__).parent / "fixtures" / "q2c-derived-deck.json"
EXPECTED = "A팀 순매출: B팀 대비 차이 +200원 (2026-01-01~2026-01-31)"


def inputs(text=EXPECTED, *, left="1,200원", right="1,000원", operation="difference", ratio=False):
    payload, sources = sample(left, right, operation, ratio=ratio)
    structure = parse_story_structure(payload, META, BRIEF, sources)
    deck = Deck.model_validate({
        "meta": META.model_dump(mode="json"), "structure": structure.model_dump(mode="json"),
        "slides": [{"chapter_id": "c1", "slots": {
            "template": "bullet_box", "bullets": [{"text": text}], "conclusion": "비교 조건 확인",
        }}],
    })
    return deck, sources


def test_exact_expression_links_both_operands_and_formula_without_mutation():
    deck, sources = inputs()
    before = deck.model_dump_json()
    report = assess_numeric_review(deck, sources)
    assert (report.status, report.evaluated, report.matched, report.unresolved) == ("matched", 1, 1, 0)
    item = report.items[0]
    assert (item.chapter_id, item.path, item.derivation_id) == ("c1", "/slots/bullets/0/text", "d1")
    expression = report.expressions[0]
    assert (expression.target_evidence_id, expression.baseline_evidence_id) == ("e1", "e2")
    assert expression.text == EXPECTED
    assert expression.source_ids == ["synthetic.md"]
    assert report.semantic_status == "not_run"
    assert before == deck.model_dump_json()


@pytest.mark.parametrize("wrong", [
    EXPECTED.replace("+200", "-200"), EXPECTED.replace("+200", "+20"),
    EXPECTED.replace("200원", "200천원"), EXPECTED.replace("200원", "200%"),
    EXPECTED.replace("A팀 순매출: B팀", "B팀 순매출: A팀"),
    EXPECTED.replace("차이", "증감률"), EXPECTED.replace("01-31", "02-28"),
    EXPECTED + "이므로 매출은 감소했다", "약 " + EXPECTED, "이전 초안: " + EXPECTED,
    "200원", "-200", "1", "１", "다른 조건의 20% 증가",
])
def test_partial_number_unit_sign_basis_and_unlinked_text_never_match(wrong):
    report = assess_numeric_review(*inputs(wrong))
    assert report.status == "needs_review"
    assert (report.matched, report.unresolved) == (0, 1)
    assert report.items[0].actual == wrong


def test_mutated_computed_result_is_not_trusted():
    deck, sources = inputs(EXPECTED.replace("+200", "+999"))
    deck.structure.story_plan.derived_values[0].value = "999"
    report = assess_numeric_review(deck, sources)
    assert report.status == "needs_review"
    assert report.expressions[0].text == EXPECTED
    assert deck.structure.story_plan.derived_values[0].value == "999"


def test_rounding_and_percentage_points_are_part_of_the_expression():
    deck, sources = inputs("확인", left="4", right="3", operation="percent_change")
    expected = chapter_numeric_expressions(deck.structure.story_plan, deck.structure.chapters[0])[0].text
    assert "+33.333333%" in expected
    assert "소수 최대 6자리 반올림" in expected
    deck.slides[0].slots.bullets[0].text = expected
    assert assess_numeric_review(deck, sources).status == "matched"
    deck.slides[0].slots.bullets[0].text = expected.replace(", 소수 최대 6자리 반올림", "")
    assert assess_numeric_review(deck, sources).status == "needs_review"
    deck, sources = inputs("확인", left="80%", right="70%", ratio=True)
    expected = chapter_numeric_expressions(deck.structure.story_plan, deck.structure.chapters[0])[0].text
    assert "+10퍼센트포인트" in expected and "분모:" in expected
    deck.slides[0].slots.bullets[0].text = expected.replace("퍼센트포인트", "%")
    assert assess_numeric_review(deck, sources).matched == 0


@pytest.mark.parametrize("change", ["sources", "plan", "chapter", "meta"])
def test_stale_inputs_never_reuse_a_match(change):
    deck, sources = inputs()
    if change == "sources": sources["synthetic.md"] += "\n추가 내용"
    elif change == "plan": deck.structure.story_plan.claims[0].statement = "다른 주장"
    elif change == "chapter": deck.structure.chapters[0].topic = "다른 제목"
    else: deck.meta.title = "다른 보고"
    report = assess_numeric_review(deck, sources)
    assert (report.status, report.evaluated, report.matched) == ("not_run", 0, 0)
    assert report.reason == "stale_plan"
    assert report.expressions == []


def test_missing_plan_empty_targets_and_blocked_calculations_are_not_passes():
    deck, sources = inputs("정성적인 설명")
    report = assess_numeric_review(deck, sources)
    assert (report.status, report.evaluated, report.reason) == ("not_run", 0, "no_numeric_fields")
    deck.structure.story_plan = None
    deck.slides[0].slots.bullets[0].text = "200원"
    assert assess_numeric_review(deck, sources).reason == "missing_plan"
    deck, sources = inputs("200%", right="0", operation="percent_change")
    report = assess_numeric_review(deck, sources)
    assert report.status == "not_run" and report.expressions == []
    assert report.matched == 0


def test_duplicate_derivations_do_not_choose_an_arbitrary_evidence_link():
    payload, sources = sample()
    payload["derivations"].append({**payload["derivations"][0], "id": "d2"})
    deck, _ = inputs()
    deck.structure = parse_story_structure(payload, META, BRIEF, sources)
    report = assess_numeric_review(deck, sources)
    assert report.status == "needs_review" and report.matched == 0
    assert report.items[0].code == "ambiguous_expression"


def test_changed_slot_and_restored_slot_have_distinct_review_fingerprints():
    deck, sources = inputs()
    first = assess_numeric_review(deck, sources)
    deck.slides[0].slots.bullets[0].text = "20%"
    edited = assess_numeric_review(deck, sources)
    assert edited.input_fingerprint != first.input_fingerprint
    deck.slides[0].slots.bullets[0].text = EXPECTED
    assert assess_numeric_review(deck, sources).input_fingerprint == first.input_fingerprint


def test_review_api_uses_unsaved_input_and_preserves_deck_snapshots_and_usage(client, store):
    deck, sources = inputs()
    store.create_project("synthetic", META.title)
    for name, text in sources.items(): store.write_source("synthetic", name, text)
    store.save_deck("synthetic", deck)
    saved = store.load_deck("synthetic").model_dump_json()
    files_before = {str(p.relative_to(store.root)): p.read_bytes() for p in store.root.rglob("*") if p.is_file()}
    unsaved = deck.model_dump(mode="json")
    unsaved["slides"][0]["slots"]["bullets"][0]["text"] = "-200원"
    response = client.post("/api/projects/synthetic/review/numbers", json=unsaved)
    assert response.status_code == 200
    assert response.json()["status"] == "needs_review"
    assert store.load_deck("synthetic").model_dump_json() == saved
    assert client.post("/api/projects/synthetic/review/numbers", json=deck.model_dump(mode="json")).json()["status"] == "matched"
    assert files_before == {str(p.relative_to(store.root)): p.read_bytes() for p in store.root.rglob("*") if p.is_file()}


def test_review_api_requires_app_header_but_no_ai_connection_or_consent(store):
    deck, sources = inputs()
    store.create_project("synthetic", META.title)
    for name, text in sources.items(): store.write_source("synthetic", name, text)
    bare = TestClient(create_app(store))
    assert bare.post("/api/projects/synthetic/review/numbers", json=deck.model_dump(mode="json")).status_code == 403


def test_q2c_saved_fixture_remains_compatible():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    deck = Deck.model_validate(data["deck"])
    before = deck.model_dump_json()
    assert assess_numeric_review(deck, data["sources"]).status == "not_run"
    assert deck.model_dump_json() == before


@pytest.mark.parametrize("defect", ["excerpt", "revision", "locator"])
def test_recomputed_fingerprint_cannot_hide_wrong_source_link(defect):
    deck, sources = inputs()
    plan = deck.structure.story_plan
    if defect == "excerpt": plan.evidence[0].excerpt += " 원문에 없는 추가 내용"
    elif defect == "revision": plan.evidence[0].source_revision = "f" * 64
    else: plan.evidence[0].locator.line_start = plan.evidence[0].locator.line_end = 1
    # A client can recompute an input hash. It cannot change the server's source.
    plan.input_fingerprint = story_fingerprint(plan, deck.meta, deck.structure.chapters, sources)
    report = assess_numeric_review(deck, sources)
    assert report.status == "not_run" and report.matched == 0
    assert report.reason == "evidence_mismatch"


def test_shared_fixture_roundtrips_through_real_backend(client, store):
    fixture = json.loads(FIXTURE.with_name("q2d-numeric-review.json").read_text(encoding="utf-8"))
    store.create_project("synthetic", "합성 자료")
    for name, text in fixture["sources"].items(): store.write_source("synthetic", name, text)
    for kind in ("matched", "mismatched"):
        deck = Deck.model_validate(fixture["deck"])
        if kind == "mismatched":
            deck.slides[0].slots.bullets[0].text = fixture["mismatched_report"]["items"][0]["actual"]
        response = client.post("/api/projects/synthetic/review/numbers", json=deck.model_dump(mode="json"))
        assert response.status_code == 200
        assert response.json() == fixture[f"{kind}_report"]


def test_reopen_and_snapshot_restore_are_reassessed(client, store):
    deck, sources = inputs()
    store.create_project("synthetic", META.title)
    for name, text in sources.items(): store.write_source("synthetic", name, text)
    store.save_deck("synthetic", deck)
    store.snapshot_now("synthetic")
    snapshot = store.list_snapshots("synthetic")[-1].id
    deck.slides[0].slots.bullets[0].text = "-200원"
    store.save_deck("synthetic", deck)
    reopened = client.get("/api/projects/synthetic/deck").json()
    assert client.post("/api/projects/synthetic/review/numbers", json=reopened).json()["status"] == "needs_review"
    restored = client.post(f"/api/projects/synthetic/snapshots/{snapshot}/restore").json()
    assert client.post("/api/projects/synthetic/review/numbers", json=restored).json()["status"] == "matched"


@pytest.mark.parametrize("operation", ["generate", "condense"])
def test_generation_and_condense_use_canonical_expressions_without_new_calls(store, operation):
    from test_story_plan import HEADERS, StubProvider
    deck, sources = inputs()
    slots = deck.slides[0].slots.model_dump(mode="json")
    provider = StubProvider([slots])
    client = TestClient(create_app(store, provider=provider), headers=HEADERS)
    store.create_project("synthetic", META.title)
    for name, text in sources.items(): store.write_source("synthetic", name, text)
    store.save_deck("synthetic", deck)
    saved = store.load_deck("synthetic").model_dump_json()
    suffix, body = ("", {}) if operation == "generate" else ("/condense", {"slots": slots})
    response = client.post(f"/api/projects/synthetic/generate/chapter/c1{suffix}", json=body)
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert len(provider.calls) == 1
    assert EXPECTED in provider.calls[0][0]
    assert "numeric_expressions" in provider.calls[0][0]
    generated = deck.model_dump(mode="json")
    generated["slides"][0]["slots"] = response.json()["slots"]
    assert client.post("/api/projects/synthetic/review/numbers", json=generated).json()["status"] == "matched"
    assert store.load_deck("synthetic").model_dump_json() == saved


def test_nested_table_cells_and_manual_titles_are_inspected():
    payload, sources = sample()
    payload["chapters"][0]["template"] = "table"
    deck, _ = inputs()
    saved = deck.model_dump(mode="json")
    saved["structure"] = parse_story_structure(payload, META, BRIEF, sources).model_dump(mode="json")
    saved["slides"][0]["slots"] = {"template": "table", "columns": ["비교"], "rows": [[EXPECTED], ["1"]]}
    saved["slides"][0]["subtitle"] = "미확인 5%"
    report = assess_numeric_review(Deck.model_validate(saved), sources)
    assert (report.evaluated, report.matched, report.unresolved) == (3, 1, 2)
    assert {item.path for item in report.items} == {"/slots/rows/0/0", "/slots/rows/1/0", "/subtitle"}


def test_other_chapters_computation_is_not_available_for_matching():
    payload, sources = sample()
    payload["claims"].append({"id": "k2", "statement": "다른 장의 주장", "kind": "proposal", "evidence_ids": ["e1", "e2"], "caveats": []})
    payload["chapters"].append({"topic": "상세 근거", "conclusion": "조건 확인", "template": "bullet_box", "role": "evidence", "claim_ids": ["k2"]})
    payload["comparisons"][0]["claim_id"] = "k2"
    deck, _ = inputs()
    deck.structure = parse_story_structure(payload, META, BRIEF, sources)
    report = assess_numeric_review(deck, sources)
    assert report.status == "needs_review" and report.matched == 0
    assert all(e.chapter_id == "c2" for e in report.expressions)


def test_not_run_notice_does_not_claim_a_completed_check():
    deck, sources = inputs()
    deck.structure.story_plan = None
    report = assess_numeric_review(deck, sources)
    assert "대조했습니다" not in report.notice


@pytest.mark.parametrize("left,right,operation,expected", [
    ("900원", "1,000원", "difference", "차이 -100원"),
    ("1,000원", "1,000원", "difference", "차이 0원"),
    ("999999999원", "1000000000원", "percent_change", "증감률 0%"),
])
def test_signed_zero_and_negative_display(left, right, operation, expected):
    deck, sources = inputs("확인", left=left, right=right, operation=operation)
    expression = chapter_numeric_expressions(deck.structure.story_plan, deck.structure.chapters[0])[0]
    assert expected in expression.text
    if operation == "percent_change": assert "반올림" in expression.text
    deck.slides[0].slots.bullets[0].text = expression.text
    assert assess_numeric_review(deck, sources).status == "matched"


def test_period_comparison_preserves_target_and_baseline_dates():
    payload, sources = sample(operation="percent_change")
    payload["comparisons"][0]["axis"] = "period"
    payload["evidence"][0]["metric_basis"]["period"].update(start="2026-02-01", end="2026-02-28")
    payload["evidence"][1]["metric_basis"]["entity"] = "A팀"
    sources["synthetic.md"] = sources["synthetic.md"].replace("A팀 2026년 1월", "A팀 2026년 2월").replace("B팀", "A팀")
    deck, _ = inputs()
    deck.structure = parse_story_structure(payload, META, BRIEF, sources)
    expected = "A팀 순매출: 2026-02-01~2026-02-28, 2026-01-01~2026-01-31 대비 증감률 +20%"
    deck.slides[0].slots.bullets[0].text = expected
    assert assess_numeric_review(deck, sources).status == "matched"
    deck.slides[0].slots.bullets[0].text = "A팀 순매출: 2026-01-01~2026-01-31, 2026-02-01~2026-02-28 대비 증감률 +20%"
    assert assess_numeric_review(deck, sources).matched == 0
