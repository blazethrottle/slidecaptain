"""Q2b: 비교 조건의 실패 경계와 저장/생성 계약 왕복. 실제 AI 호출 없음."""

import asyncio
from copy import deepcopy
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from slidecaptain.metrics.font_metrics import FontMetrics
from slidecaptain.models.deck import Deck, DeckMeta
from slidecaptain.models.story import ReportBrief
from slidecaptain.pipeline.service import GenerationService
from slidecaptain.pipeline.story import parse_story_structure, require_current_story
from slidecaptain.server.app import create_app
from test_story_plan import HEADERS, SLOTS, StubProvider


SOURCE = "synthetic.md"
SOURCES = {SOURCE: "합성 자료\nA팀 응답 만족도 80%, 2026년 1월 전체 응답자 기준.\nB팀 응답 만족도 70%, 2026년 1월 전체 응답자 기준."}
META = DeckMeta(title="합성 비교")
BRIEF = ReportBrief(decision_question="두 팀 만족도를 비교할 수 있는가?")
BASIS = {
    "definition": "긍정 응답 수 / 전체 응답 수", "unit": "%", "entity": "A팀",
    "period": {"start": "2026-01-01", "end": "2026-01-31", "grain": "month",
               "aggregation": "ratio", "coverage": "complete"},
    "denominator": {"kind": "population", "definition": "전체 설문 응답 수"},
}


def payload():
    return {
        "evidence": [
            {"id": "e1", "source_id": SOURCE, "locator": {"line_start": 2, "line_end": 2},
             "value": "80%", "metric_basis": deepcopy(BASIS)},
            {"id": "e2", "source_id": SOURCE, "locator": {"line_start": 3, "line_end": 3},
             "value": "70%", "metric_basis": {**deepcopy(BASIS), "entity": "B팀"}},
        ],
        "claims": [{"id": "k1", "statement": "동일 설문 기준으로 두 팀을 비교한다", "kind": "proposal",
                    "evidence_ids": ["e1", "e2"], "caveats": ["설문 방식의 동일성은 별도 확인"]}],
        "answer_claim_ids": ["k1"], "unanswered_questions": [],
        "chapters": [{"topic": "두 팀 비교", "conclusion": "조건 확인", "template": "bullet_box",
                      "role": "answer", "claim_ids": ["k1"]}],
        "comparisons": [{"id": "cmp1", "claim_id": "k1", "left_evidence_id": "e1",
                         "right_evidence_id": "e2", "axis": "entity"}],
    }


def structure(data=None):
    return parse_story_structure(payload() if data is None else data, META, BRIEF, SOURCES)


def assessment(data=None):
    return structure(data).story_plan.comparison_results[0]


def test_same_period_entity_comparison_is_bound_to_plan():
    plan = structure().story_plan
    assert plan.version == "q2c-v1"
    check = plan.comparison_results[0]
    assert check.comparison_id == "cmp1"
    assert check.status == "compatible"
    assert check.reasons == []
    assert plan.evidence[0].excerpt == SOURCES[SOURCE].splitlines()[1]


@pytest.mark.parametrize("field,value,code", [
    ("definition", "전체 등록자 대비 긍정 응답", "definition_mismatch"),
    ("unit", "퍼센트포인트", "unit_mismatch"),
    ("unit", "천원", "unit_mismatch"),
    ("denominator", {"kind": "population", "definition": "전체 등록자 수"}, "denominator_mismatch"),
    ("denominator", {"kind": "none", "definition": None}, "denominator_mismatch"),
    ("entity", "A팀", "same_axis_value"),
])
def test_incompatible_basis_returns_reason_without_format_failure(field, value, code):
    data = payload()
    data["evidence"][1]["metric_basis"][field] = value
    check = assessment(data)
    assert check.status == "incompatible"
    assert code in [r.code for r in check.reasons]


@pytest.mark.parametrize("field", ["definition", "unit", "entity", "period", "denominator"])
def test_matching_missing_values_do_not_pass(field):
    data = payload()
    for e in data["evidence"]:
        e["metric_basis"][field] = None
    check = assessment(data)
    assert check.status == "insufficient_metadata"
    assert all(r.code == "missing_metadata" for r in check.reasons)
    assert {r.evidence_id for r in check.reasons} == {"e1", "e2"}


@pytest.mark.parametrize("defect", ["basis", "value", "unknown_denominator", "missing_population", "unknown_coverage"])
def test_unknown_metadata_is_not_inferred_from_legacy_labels(defect):
    data = payload()
    e = data["evidence"][1]
    e.update(unit="%", period="2026년 1월", entity="B팀", denominator="전체 응답자")
    if defect == "basis":
        e["metric_basis"] = None
    elif defect == "value":
        e["value"] = None
    elif defect == "unknown_denominator":
        e["metric_basis"]["denominator"] = {"kind": "unknown", "definition": None}
    elif defect == "missing_population":
        e["metric_basis"]["denominator"]["definition"] = None
    else:
        e["metric_basis"]["period"]["coverage"] = "unknown"
    check = assessment(data)
    assert check.status == "insufficient_metadata"
    assert check.reasons


def time_comparison(grain="month", left=("2026-01-01", "2026-01-31"), right=("2026-02-01", "2026-02-28")):
    data = payload()
    data["comparisons"][0]["axis"] = "period"
    for e, dates in zip(data["evidence"], [left, right]):
        e["metric_basis"]["entity"] = "A팀"
        e["metric_basis"]["period"].update(grain=grain, start=dates[0], end=dates[1])
    return data


@pytest.mark.parametrize("grain,left,right", [
    ("month", ("2026-01-01", "2026-01-31"), ("2026-02-01", "2026-02-28")),
    ("quarter", ("2026-01-01", "2026-03-31"), ("2026-04-01", "2026-06-30")),
    ("year", ("2024-01-01", "2024-12-31"), ("2025-01-01", "2025-12-31")),
])
def test_completed_calendar_periods_allow_different_day_counts(grain, left, right):
    assert assessment(time_comparison(grain, left, right)).status == "compatible"


@pytest.mark.parametrize("defect,code", [
    ("entity", "entity_mismatch"), ("overlap", "overlapping_periods"),
    ("partial", "incomplete_period"), ("bad_boundary", "unsupported_period"),
    ("custom", "unsupported_period"), ("aggregation", "period_basis_mismatch"),
    ("grain", "period_basis_mismatch"), ("entity_period", "period_mismatch"),
])
def test_period_comparison_failure_boundaries(defect, code):
    data = time_comparison()
    basis = data["evidence"][1]["metric_basis"]
    if defect == "entity": basis["entity"] = "B팀"
    elif defect == "overlap": basis["period"].update(start="2026-01-01", end="2026-01-31")
    elif defect == "partial": basis["period"]["coverage"] = "partial"
    elif defect == "bad_boundary": basis["period"]["start"] = "2026-02-02"
    elif defect == "custom": basis["period"]["grain"] = "custom"
    elif defect == "aggregation": basis["period"]["aggregation"] = "sum"
    elif defect == "grain": basis["period"].update(grain="year", start="2026-01-01", end="2026-12-31")
    else: data["comparisons"][0]["axis"] = "entity"
    check = assessment(data)
    assert check.status != "compatible"
    assert code in [r.code for r in check.reasons]


def test_absolute_values_without_denominator_and_point_values():
    data = payload()
    for e in data["evidence"]:
        basis = e["metric_basis"]
        basis.update(definition="잔액", unit="원", denominator={"kind": "none"})
        basis["period"].update(start="2026-01-31", end="2026-01-31", grain="point", aggregation="point")
    assert assessment(data).status == "compatible"
    data["comparisons"][0]["axis"] = "period"
    data["evidence"][1]["metric_basis"]["entity"] = "A팀"
    data["evidence"][1]["metric_basis"]["period"].update(start="2026-02-28", end="2026-02-28")
    assert assessment(data).status == "compatible"


def test_ratio_cannot_pass_with_denominator_marked_not_applicable():
    data = payload()
    for e in data["evidence"]:
        e["metric_basis"]["denominator"] = {"kind": "none"}
    assert assessment(data).status == "insufficient_metadata"


def test_known_conflict_and_unknown_metadata_are_both_reported():
    data = payload()
    data["evidence"][1]["metric_basis"].update(unit="원", entity=None)
    check = assessment(data)
    assert check.status == "incompatible"
    assert {r.code for r in check.reasons} == {"missing_metadata", "unit_mismatch"}


def test_valid_comparison_survives_one_format_retry_but_incompatibility_does_not_retry():
    data = payload()
    data["evidence"][1]["metric_basis"]["unit"] = "원"
    invalid = deepcopy(data)
    invalid["comparisons"][0]["claim_id"] = "absent"
    provider = StubProvider([invalid, data])
    result = asyncio.run(GenerationService(provider, FontMetrics.load_default()).generate_structure(META, SOURCES, brief=BRIEF))
    assert result.status == "ok" and result.format_retried
    assert len(provider.calls) == 2
    assert result.structure.story_plan.comparison_results[0].status == "incompatible"


@pytest.mark.parametrize("defect", ["missing_evidence", "same_evidence", "missing_claim", "unlinked", "duplicate", "axis", "date", "reversed", "forged_result"])
def test_bad_comparison_contract_retries_once(defect):
    data = payload()
    comparison = data["comparisons"][0]
    if defect == "missing_evidence": comparison["right_evidence_id"] = "absent"
    elif defect == "same_evidence": comparison["right_evidence_id"] = "e1"
    elif defect == "missing_claim": comparison["claim_id"] = "absent"
    elif defect == "unlinked": data["claims"][0]["evidence_ids"] = ["e1"]
    elif defect == "duplicate": data["comparisons"] *= 2
    elif defect == "axis": comparison["axis"] = "anything"
    elif defect == "date": data["evidence"][0]["metric_basis"]["period"]["end"] = "2026-02-30"
    elif defect == "reversed": data["evidence"][0]["metric_basis"]["period"]["end"] = "2025-12-31"
    else: data["comparison_results"] = [{"comparison_id": "cmp1", "status": "compatible", "reasons": []}]
    provider = StubProvider([data, data])
    service = GenerationService(provider, FontMetrics.load_default())
    result = asyncio.run(service.generate_structure(META, SOURCES, brief=BRIEF))
    assert result.status == "format_error"
    assert result.structure is None
    assert result.format_retried
    assert len(provider.calls) == result.usage.calls == 2


def test_saved_comparison_result_is_recomputed_and_changed_basis_invalidates_plan():
    deck = Deck(meta=META, structure=structure()).model_dump(mode="json")
    saved = deck["structure"]["story_plan"]
    saved["evidence"][1]["metric_basis"]["unit"] = "원"
    # 저장된 성공 표시를 신뢰하지 않는다. 수동 입력 변경은 보존한다.
    assert saved["comparison_results"][0]["status"] == "compatible"
    reloaded = Deck.model_validate(deck)
    assert reloaded.structure.story_plan.comparison_results[0].status == "incompatible"
    with pytest.raises(ValueError, match="다시 생성"):
        require_current_story(reloaded, SOURCES)


def test_actual_q2a_saved_fixture_keeps_original_fingerprint():
    saved = json.loads((Path(__file__).parent / "fixtures/q2a-story-deck.json").read_text(encoding="utf-8"))
    deck = Deck.model_validate(saved["deck"])
    require_current_story(deck, saved["sources"])
    assert deck.structure.story_plan.version == "q2a-v1"
    assert deck.structure.story_plan.comparisons == []
    assert deck.structure.story_plan.comparison_results == []


def test_old_version_cannot_hide_new_comparison_fields_from_fingerprint():
    deck = Deck(meta=META, structure=structure()).model_dump(mode="json")
    deck["structure"]["story_plan"]["version"] = "q2a-v1"
    with pytest.raises(ValueError, match="q2b-v1"):
        Deck.model_validate(deck)


def test_legacy_plan_without_comparisons_is_explicitly_unchecked():
    data = payload()
    data.pop("comparisons")
    for e in data["evidence"]:
        e.pop("metric_basis")
    plan = structure(data).story_plan
    assert plan.comparisons == [] and plan.comparison_results == []


def test_comparison_api_save_reload_and_generation_context(store):
    data = payload()
    data["evidence"][1]["metric_basis"]["unit"] = "원"
    provider = StubProvider([data, SLOTS, SLOTS])
    client = TestClient(create_app(store, provider=provider), headers=HEADERS)
    assert client.post("/api/projects", json={"name": "synthetic", "title": META.title}).status_code == 201
    assert client.put(f"/api/projects/synthetic/sources/{SOURCE}", json={"text": SOURCES[SOURCE]}).status_code == 200
    response = client.post("/api/projects/synthetic/generate/structure", json={"brief": BRIEF.model_dump(mode="json")})
    assert response.status_code == 200 and response.json()["status"] == "ok"
    deck = client.get("/api/projects/synthetic/deck").json()
    deck["structure"] = response.json()["structure"]
    assert client.put("/api/projects/synthetic/deck", json=deck).status_code == 200
    assert client.get("/api/projects/synthetic/deck").json() == deck
    assert deck["structure"]["story_plan"]["comparison_results"][0]["status"] == "incompatible"
    for suffix, body in [("", {}), ("/condense", {"slots": SLOTS})]:
        generated = client.post(f"/api/projects/synthetic/generate/chapter/c1{suffix}", json=body)
        assert generated.status_code == 200
        prompt = provider.calls[-1][0]
        assert '"comparison_id": "cmp1"' in prompt and "unit_mismatch" in prompt
        assert "직접적인 우열" in prompt and "비교 불가" in prompt
    schema = provider.calls[0][1]
    assert "comparisons" in schema["properties"]
    assert "comparison_results" not in schema["properties"]
    assert "metric_basis" in provider.calls[0][0]
    assert len(provider.calls) == 3  # 비교 불가 자체는 형식 재시도나 추가 검수 호출을 만들지 않는다.

    # 같은 계획을 스냅샷에서 복원한 뒤 자료를 바꾸면 두 생성 경로 모두 호출 전에 막는다.
    changed = deepcopy(deck)
    changed["structure"]["chapters"][0]["topic"] = "수동 제목"
    assert client.put("/api/projects/synthetic/deck", json=changed).status_code == 200
    snapshots = client.get("/api/projects/synthetic/snapshots").json()
    assert client.post(f"/api/projects/synthetic/snapshots/{snapshots[-1]['id']}/restore").json() == deck
    assert client.put(f"/api/projects/synthetic/sources/{SOURCE}", json={"text": SOURCES[SOURCE] + "\n조건 변경"}).status_code == 200
    for suffix, body in [("", {}), ("/condense", {"slots": SLOTS})]:
        assert client.post(f"/api/projects/synthetic/generate/chapter/c1{suffix}", json=body).status_code == 409
    assert len(provider.calls) == 3
