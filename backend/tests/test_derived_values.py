"""Q2c: 합성 수치의 계산, 거절 이유와 저장/생성 경계 왕복."""

import asyncio
from copy import deepcopy
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from slidecaptain.metrics.font_metrics import FontMetrics
from slidecaptain.models.deck import Deck
from slidecaptain.models.story import ReportBrief
from slidecaptain.pipeline.service import GenerationService
from slidecaptain.pipeline.story import parse_story_structure, require_current_story
from slidecaptain.server.app import create_app
from test_metric_comparison import META, SOURCE, payload as comparison_payload
from test_story_plan import HEADERS, SLOTS, StubProvider

BRIEF = ReportBrief(decision_question="같은 기간에 두 팀의 순매출은 얼마나 차이 나는가?")


def sample(left="1,200원", right="1,000원", operation="difference", *, ratio=False):
    data = comparison_payload()
    unit = "%" if ratio else "원"
    for e, value in zip(data["evidence"], (left, right)):
        e["value"] = value
        if not ratio:
            e["metric_basis"].update(definition="순매출", unit=unit, denominator={"kind": "none"})
            e["metric_basis"]["period"]["aggregation"] = "sum"
    data["derivations"] = [{"id": "d1", "comparison_id": "cmp1", "operation": operation}]
    metric = "응답 만족도" if ratio else "순매출"
    data["claims"][0].update(statement=f"같은 기간의 두 팀 {metric} 차이를 확인한다", caveats=["정의와 집계 범위의 원문 해석은 별도 검수"])
    data["chapters"][0].update(topic=f"두 팀 {metric} 비교", conclusion="비교 조건 확인")
    sources = {SOURCE: f"합성 자료\nA팀 2026년 1월 전체 기간 {metric}: {left}\nB팀 2026년 1월 전체 기간 {metric}: {right}"}
    return data, sources


def plan_for(data, sources):
    return parse_story_structure(data, META, BRIEF, sources).story_plan


def result_for(left="1,200원", right="1,000원", operation="difference", **kwargs):
    return plan_for(*sample(left, right, operation, **kwargs)).derived_values[0]


@pytest.mark.parametrize("left,right,operation,value,unit,rounded", [
    ("1,200원", "1,000원", "difference", "200", "원", False),
    ("1,200원", "1,000원", "percent_change", "20", "%", False),
    ("900", "1,000", "percent_change", "-10", "%", False),
    ("0.3", "0.1", "difference", "0.2", "원", False),
    ("-5원", "+2 원", "difference", "-7", "원", False),
    ("0", "0", "difference", "0", "원", False),
    ("0", "5", "percent_change", "-100", "%", False),
    ("4", "3", "percent_change", "33.333333", "%", True),
    ("0.000001", "0.000003", "percent_change", "-66.666667", "%", True),
    ("999999999", "1000000000", "percent_change", "0", "%", True),
    ("200000001", "200000000", "percent_change", "0.000001", "%", True),
    ("199999999", "200000000", "percent_change", "-0.000001", "%", True),
    ("999999999999999999999999", "1", "difference", "999999999999999999999998", "원", False),
])
def test_recomputes_bounded_decimal_arithmetic(left, right, operation, value, unit, rounded):
    result = result_for(left, right, operation)
    assert result.status == "computed"
    assert (result.value, result.unit, result.rounded) == (value, unit, rounded)
    assert result.reasons == []
    assert result.rule_version == "q2c-v1"


def test_percentage_difference_is_percentage_points_not_relative_percent():
    result = result_for("80%", "70%", ratio=True)
    assert (result.value, result.unit) == ("10", "퍼센트포인트")
    result = result_for("80%", "70%", "percent_change", ratio=True)
    assert result.status == "blocked"
    assert "unsupported_metric" in {r.code for r in result.reasons}


@pytest.mark.parametrize("value", ["약 120", "100~120", "1e3", "NaN", "Infinity", "(120)",
                                    "12,00", "1,2", "1.000,50", "1 200", "１２０", "−120",
                                    "1억 2천만원", "120천원", "120%", "1+2", "1.2.3"])
def test_ambiguous_or_different_unit_values_are_blocked(value):
    result = result_for(value)
    assert result.status == "blocked" and result.value is None and result.unit is None
    assert result.rounded is None
    assert "invalid_number" in {r.code for r in result.reasons}


@pytest.mark.parametrize("value", ["9" * 25, "0.0000001", "9" * 129])
def test_out_of_contract_precision_and_length_are_blocked(value):
    result = result_for(value)
    assert result.status == "blocked" and result.value is None
    assert "numeric_limit" in {r.code for r in result.reasons}


@pytest.mark.parametrize("original,selected", [("120", "20"), ("-120", "120"), ("1,200", "200"),
                                                ("0.25", "25"), ("1e3", "3"), ("120%", "120")])
def test_numeric_substring_cannot_become_an_operand(original, selected):
    data, sources = sample(original)
    data["evidence"][0]["value"] = selected
    result = plan_for(data, sources).derived_values[0]
    assert result.status == "blocked"
    assert "ambiguous_numeric_token" in {r.code for r in result.reasons}


@pytest.mark.parametrize("baseline,code", [("0", "zero_baseline"), ("-5", "negative_baseline")])
def test_rate_requires_positive_baseline(baseline, code):
    result = result_for("10", baseline, "percent_change")
    assert result.status == "blocked" and result.value is None
    assert code in {r.code for r in result.reasons}


@pytest.mark.parametrize("defect", ["unit", "denominator", "partial", "missing_basis", "missing_value"])
def test_comparison_failure_cannot_be_hidden_by_a_numeric_result(defect):
    data, sources = sample()
    e = data["evidence"][1]
    if defect == "unit": e["metric_basis"]["unit"] = "천원"
    elif defect == "denominator": e["metric_basis"]["denominator"] = {"kind": "population", "definition": "응답자"}
    elif defect == "partial": e["metric_basis"]["period"]["coverage"] = "partial"
    elif defect == "missing_basis": e["metric_basis"] = None
    else: e["value"] = None
    plan = plan_for(data, sources)
    assert plan.comparison_results[0].status != "compatible"
    assert plan.derived_values[0].value is None
    assert "comparison_blocked" in {r.code for r in plan.derived_values[0].reasons}


def test_period_rate_requires_target_after_baseline():
    data, sources = sample(operation="percent_change")
    data["comparisons"][0]["axis"] = "period"
    e = data["evidence"][1]
    e["metric_basis"]["entity"] = "A팀"
    e["metric_basis"]["period"].update(start="2026-02-01", end="2026-02-28")
    plan = plan_for(data, sources)
    assert plan.comparison_results[0].status == "compatible"
    assert "reversed_period" in {r.code for r in plan.derived_values[0].reasons}
    data["comparisons"][0].update(left_evidence_id="e2", right_evidence_id="e1")
    assert plan_for(data, sources).derived_values[0].status == "computed"


@pytest.mark.parametrize("defect", ["reference", "duplicate", "operation", "constant", "forged_result"])
def test_invalid_formula_contract_retries_at_most_once(defect):
    data, sources = sample()
    if defect == "reference": data["derivations"][0]["comparison_id"] = "absent"
    elif defect == "duplicate": data["derivations"] *= 2
    elif defect == "operation": data["derivations"][0]["operation"] = "eval(1+2)"
    elif defect == "constant": data["derivations"][0]["constant"] = 100
    else: data["derived_values"] = []
    provider = StubProvider([data, data])
    result = asyncio.run(GenerationService(provider, FontMetrics.load_default()).generate_structure(META, sources, brief=BRIEF))
    assert result.status == "format_error" and result.structure is None
    assert result.format_retried and len(provider.calls) == result.usage.calls == 2


def test_calculation_failure_is_normal_and_does_not_retry():
    data, sources = sample("約120", "0", "percent_change")
    provider = StubProvider([data])
    result = asyncio.run(GenerationService(provider, FontMetrics.load_default()).generate_structure(META, sources, brief=BRIEF))
    assert result.status == "ok" and not result.format_retried
    assert len(provider.calls) == 1
    assert result.structure.story_plan.derived_values[0].status == "blocked"
    assert "derived_values" not in provider.calls[0][1]["properties"]


def test_saved_success_and_operand_changes_are_recomputed():
    data, sources = sample()
    deck = Deck(meta=META, structure=parse_story_structure(data, META, BRIEF, sources))
    saved = deck.model_dump(mode="json")
    plan = saved["structure"]["story_plan"]
    plan["derived_values"][0].update(value="999", unit="천원", rounded=True)
    reloaded = Deck.model_validate(saved)
    assert reloaded.structure.story_plan.derived_values[0].value == "200"
    require_current_story(reloaded, sources)
    plan["evidence"][0]["value"] = "2,000원"
    reloaded = Deck.model_validate(saved)
    assert reloaded.structure.story_plan.derived_values[0].status == "blocked"
    with pytest.raises(ValueError, match="다시 생성"):
        require_current_story(reloaded, sources)


@pytest.mark.parametrize("version", ["q2a", "q2b"])
def test_actual_older_saved_plans_keep_fingerprint(version):
    saved = json.loads((Path(__file__).parent / f"fixtures/{version}-story-deck.json").read_text(encoding="utf-8"))
    deck = Deck.model_validate(saved["deck"])
    require_current_story(deck, saved["sources"])
    assert deck.structure.story_plan.derivations == []
    assert deck.structure.story_plan.derived_values == []


@pytest.mark.parametrize("version", ["q2a-v1", "q2b-v1"])
def test_older_version_cannot_hide_calculations(version):
    data, sources = sample()
    saved = plan_for(data, sources).model_dump(mode="json")
    saved["version"] = version
    from slidecaptain.models.story import StoryPlan
    with pytest.raises(ValueError):
        StoryPlan.model_validate(saved)


@pytest.mark.parametrize("operation", ["generate", "condense"])
def test_changed_formula_blocks_external_calls_but_preserves_edit(store, operation):
    client, provider, deck = saved_api(store)
    deck["structure"]["story_plan"]["derivations"][0]["operation"] = "percent_change"
    assert client.put("/api/projects/synthetic/deck", json=deck).status_code == 200
    suffix, body = ("", {}) if operation == "generate" else ("/condense", {"slots": SLOTS})
    assert client.post(f"/api/projects/synthetic/generate/chapter/c1{suffix}", json=body).status_code == 409
    assert len(provider.calls) == 1
    assert client.get("/api/projects/synthetic/deck").json()["structure"]["story_plan"]["derived_values"][0]["value"] == "20"


def saved_api(store, *, blocked=False, chapter_calls=False):
    data, sources = sample("약 1,200원" if blocked else "1,200원")
    provider = StubProvider([data, *([SLOTS, SLOTS] if chapter_calls else [])])
    client = TestClient(create_app(store, provider=provider), headers=HEADERS)
    assert client.post("/api/projects", json={"name": "synthetic", "title": META.title}).status_code == 201
    assert client.put(f"/api/projects/synthetic/sources/{SOURCE}", json={"text": sources[SOURCE]}).status_code == 200
    response = client.post("/api/projects/synthetic/generate/structure", json={"brief": BRIEF.model_dump(mode="json")})
    assert response.status_code == 200 and response.json()["status"] == "ok"
    deck = client.get("/api/projects/synthetic/deck").json()
    deck["structure"] = response.json()["structure"]
    assert client.put("/api/projects/synthetic/deck", json=deck).status_code == 200
    return client, provider, deck


@pytest.mark.parametrize("blocked", [False, True])
def test_api_save_restore_generate_and_condense_carry_calculation(store, blocked):
    client, provider, deck = saved_api(store, blocked=blocked, chapter_calls=True)
    assert client.get("/api/projects/synthetic/deck").json() == deck
    changed = deepcopy(deck)
    changed["structure"]["chapters"][0]["topic"] = "수동 제목"
    assert client.put("/api/projects/synthetic/deck", json=changed).status_code == 200
    snapshots = client.get("/api/projects/synthetic/snapshots").json()
    assert client.post(f"/api/projects/synthetic/snapshots/{snapshots[-1]['id']}/restore").json() == deck
    assert client.post("/api/projects/synthetic/generate/chapter/c1", json={}).json()["status"] == "ok"
    assert client.post("/api/projects/synthetic/generate/chapter/c1/condense", json={"slots": SLOTS}).json()["status"] == "ok"
    expected = deck["structure"]["story_plan"]["derived_values"][0]
    assert expected["status"] == ("blocked" if blocked else "computed")
    for prompt, _ in provider.calls[1:]:
        assert '"derivations"' in prompt and '"derived_values"' in prompt
        assert json.dumps(expected, ensure_ascii=False) in prompt
        assert "계산 불가" in prompt and "반올림" in prompt


def test_shared_ui_fixture_matches_actual_calculation_and_saved_contract():
    saved = json.loads((Path(__file__).parent / "fixtures/q2c-derived-deck.json").read_text(encoding="utf-8"))
    actual = Deck(meta=META, structure=parse_story_structure(saved["payload"], META, BRIEF, saved["sources"]))
    assert actual.model_dump(mode="json") == saved["deck"]
    require_current_story(actual, saved["sources"])


@pytest.mark.parametrize("blocked", [False, True])
def test_number_warning_uses_only_computed_values_in_generation_and_condense(store, blocked):
    client, provider, _ = saved_api(store, blocked=blocked)
    slots = {**SLOTS, "bullets": [{"text": "차이 200원, 미등록 7777원", "level": 0}], "conclusion": "계산 조건 확인"}
    provider.payloads.extend([slots, slots])
    for suffix, body in [("", {}), ("/condense", {"slots": slots})]:
        response = client.post(f"/api/projects/synthetic/generate/chapter/c1{suffix}", json=body)
        assert response.status_code == 200
        warnings = response.json()["unverified_numbers"]
        assert "7777" in warnings
        assert ("200" in warnings) == blocked
        assert "자료 원문 또는 코드가 계산한 computed 결과" in provider.calls[-1][0]
        assert "모든 숫자는 자료 원문에 있는 값만 쓴다" not in provider.calls[-1][0]


def test_derived_number_warning_does_not_accept_an_unrelated_chapter_calculation():
    from slidecaptain.pipeline.story import chapter_derived_numbers

    data, sources = sample()
    data["claims"].append({"id": "k2", "statement": "다른 장 판단", "kind": "proposal", "evidence_ids": [], "caveats": []})
    data["answer_claim_ids"] = ["k2"]
    data["chapters"][0]["role"] = "evidence"
    data["chapters"].append({"topic": "다른 장", "conclusion": "판단", "template": "bullet_box", "role": "answer", "claim_ids": ["k2"]})
    structure = parse_story_structure(data, META, BRIEF, sources)
    assert chapter_derived_numbers(structure.story_plan, structure.chapters[0]) == ["200"]
    assert chapter_derived_numbers(structure.story_plan, structure.chapters[1]) == []


@pytest.mark.parametrize("original,selected", [("120천원", "120"), ("120 천원", "120"), ("120 만원", "120"), ("약 120원", "120원"),
                                                ("120원 이상", "120원"), ("120 ~ 150원", "120"), ("(120)", "120")])
def test_qualified_values_cannot_be_clipped_into_exact_numbers(original, selected):
    data, sources = sample(original)
    data["evidence"][0]["value"] = selected
    assert plan_for(data, sources).derived_values[0].status == "blocked"


def test_number_token_accepts_sentence_punctuation_and_omitted_matching_unit():
    data, sources = sample("1,200원.", "1,000원, 확인 완료")
    data["evidence"][0]["value"] = "1,200"
    data["evidence"][1]["value"] = "1,000원"
    assert plan_for(data, sources).derived_values[0].value == "200"
