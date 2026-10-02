"""Q3a: 의미와 근거 참조의 계약만 검사하며 실제 배치/의미 품질을 승인하지 않는다."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from slidecaptain.models.diagram import DiagramNode, DiagramSpec, parse_diagram_spec
from slidecaptain.models.story import Evidence


FIXTURE = Path(__file__).parent / "fixtures/q3a-diagram.json"


@pytest.fixture
def sample():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def parse(sample):
    return parse_diagram_spec(
        sample["diagram"], evidence=[Evidence.model_validate(e) for e in sample["evidence"]],
    )


def test_synthetic_fixture_references_actual_source_lines_and_preserves_direction(sample):
    before = deepcopy(sample)
    for evidence in sample["evidence"]:
        source = sample["sources"][evidence["source_id"]]
        assert hashlib.sha256(source.encode()).hexdigest() == evidence["source_revision"]
        start = evidence["locator"]["line_start"]
        end = evidence["locator"]["line_end"]
        assert "\n".join(source.splitlines()[start - 1:end]) == evidence["excerpt"]
    spec = parse(sample)
    evidence = [Evidence.model_validate(e) for e in sample["evidence"]]
    reloaded = parse_diagram_spec(spec.model_dump_json(), evidence=evidence)
    assert reloaded.model_dump(mode="json") == sample["diagram"]
    assert [(e.from_node_id, e.to_node_id) for e in reloaded.edges] == [
        ("intake", "review"), ("review", "pilot"),
    ]
    assert sample == before


@pytest.mark.parametrize("location", ["nodes", "edges", "across", "evidence"])
def test_duplicate_identifiers_are_rejected(sample, location):
    if location in ("nodes", "edges"):
        sample["diagram"][location][1]["id"] = sample["diagram"][location][0]["id"]
    elif location == "across":
        sample["diagram"]["edges"][0]["id"] = sample["diagram"]["nodes"][0]["id"]
    else:
        sample["evidence"].append(deepcopy(sample["evidence"][0]))
    with pytest.raises(ValueError, match="중복"):
        parse(sample)


@pytest.mark.parametrize("location", ["nodes", "edges"])
@pytest.mark.parametrize("defect", ["missing", "duplicate"])
def test_evidence_references_must_exist_and_be_unique(sample, location, defect):
    sample["diagram"][location][0]["evidence_ids"] = (
        ["absent"] if defect == "missing" else ["e1", "e1"]
    )
    with pytest.raises(ValueError, match="근거"):
        parse(sample)


@pytest.mark.parametrize("field", ["from_node_id", "to_node_id"])
def test_dangling_endpoints_are_rejected(sample, field):
    sample["diagram"]["edges"][0][field] = "absent"
    with pytest.raises(ValueError, match="노드"):
        parse(sample)


@pytest.mark.parametrize("relation", ["flow", "reference"])
def test_relation_requires_its_own_support_not_just_supported_endpoints(sample, relation):
    sample["diagram"]["edges"][0].update(relation=relation, evidence_ids=[])
    with pytest.raises(ValueError, match="근거"):
        parse(sample)


def test_unbacked_fact_and_uncaveated_inference_are_rejected(sample):
    sample["diagram"]["nodes"][0]["evidence_ids"] = []
    with pytest.raises(ValueError, match="근거"):
        parse(sample)
    for kind in ("inference", "unknown"):
        sample["diagram"]["nodes"][0]["kind"] = kind
        with pytest.raises(ValueError, match="조건|확인"):
            parse(sample)
    sample["diagram"]["nodes"][0]["caveats"] = ["근거를 추가 확인해야 한다."]
    assert parse(sample).nodes[0].kind == "unknown"


def test_proposal_can_explicitly_have_no_evidence(sample):
    spec = parse(sample)
    assert spec.nodes[2].kind == "proposal"
    assert spec.nodes[2].evidence_ids == []
    assert spec.edges[1].relation == "proposal"
    assert spec.edges[1].evidence_ids == []
    assert "quality" not in spec.model_dump()


def test_reference_relation_retains_its_support_and_does_not_imply_order(sample):
    sample["diagram"]["edges"][1].update(
        from_node_id="review", to_node_id="intake", relation="reference", evidence_ids=["e3"],
    )
    assert parse(sample).edges[1].relation == "reference"


@pytest.mark.parametrize("defect", ["self", "duplicate", "cycle"])
def test_invalid_graph_structure_is_rejected(sample, defect):
    edge = sample["diagram"]["edges"][0]
    if defect == "self":
        edge["to_node_id"] = edge["from_node_id"]
    elif defect == "duplicate":
        sample["diagram"]["edges"].append({**edge, "id": "other"})
    else:
        sample["diagram"]["edges"].append({
            **edge, "id": "return", "from_node_id": "review", "to_node_id": "intake",
        })
    with pytest.raises(ValueError, match="자기|중복|순환"):
        parse(sample)


@pytest.mark.parametrize("relation", ["comparison", "causal", "causes", "unknown"])
def test_unsupported_relation_types_are_not_silently_reinterpreted(sample, relation):
    sample["diagram"]["edges"][0]["relation"] = relation
    with pytest.raises(ValidationError):
        parse(sample)


@pytest.mark.parametrize("location", ["root", "canvas", "node", "edge"])
@pytest.mark.parametrize("field,value", [
    ("x", -1), ("bounds", {"x": 10000, "width": 500}), ("anchor", "right"),
    ("style", {"font_size": 1}), ("html", "<div>synthetic</div>"),
    ("svg", "<svg/>"), ("script", "synthetic()"), ("quality", {"status": "pass"}),
])
def test_render_execution_and_quality_fields_are_forbidden(sample, location, field, value):
    targets = {"root": sample["diagram"], "canvas": sample["diagram"]["canvas"],
               "node": sample["diagram"]["nodes"][0], "edge": sample["diagram"]["edges"][0]}
    targets[location][field] = value
    with pytest.raises(ValidationError) as caught:
        parse(sample)
    assert any(e["type"] == "extra_forbidden" for e in caught.value.errors())


@pytest.mark.parametrize("field,value", [
    ("version", "q3a-v2"), ("version", None), ("id", "bad id"),
    ("layout_variant", "auto"), ("nodes", []), ("edges", []),
])
def test_required_version_identifiers_strategy_and_nonempty_graph(sample, field, value):
    sample["diagram"][field] = value
    with pytest.raises(ValidationError):
        parse(sample)


@pytest.mark.parametrize("value", [None, True, 12, "", "   ", "x" * 501])
def test_node_content_is_bounded_nonempty_text(sample, value):
    sample["diagram"]["nodes"][0]["content"] = value
    with pytest.raises(ValidationError):
        parse(sample)


@pytest.mark.parametrize("location", ["nodes", "edges"])
def test_graph_item_limits_are_enforced(sample, location):
    count = 13 if location == "nodes" else 25
    sample["diagram"][location] = [
        {**sample["diagram"][location][0], "id": f"item{i}"} for i in range(count)
    ]
    with pytest.raises(ValidationError) as caught:
        parse(sample)
    assert any(e["type"] == "too_long" for e in caught.value.errors())


@pytest.mark.parametrize("payload", [
    '{"id":"a","id":"b"}', '{"canvas":{"page_size":"preset","page_size":"preset"}}',
])
def test_duplicate_json_members_are_rejected(sample, payload):
    with pytest.raises(ValueError, match="중복"):
        parse_diagram_spec(payload, evidence=[Evidence.model_validate(e) for e in sample["evidence"]])


def test_validation_without_evidence_context_cannot_skip_reference_check(sample):
    with pytest.raises(ValueError, match="근거 장부"):
        DiagramSpec.model_validate(sample["diagram"])
    with pytest.raises(ValueError, match="근거 장부"):
        DiagramSpec.model_validate_json(json.dumps(sample["diagram"]))
    with pytest.raises(ValueError, match="근거"):
        parse_diagram_spec(sample["diagram"], evidence=[])


def test_reparse_revalidates_mutated_models_and_ledger(sample):
    spec = parse(sample)
    evidence = [Evidence.model_validate(e) for e in sample["evidence"]]
    spec.nodes[0].evidence_ids.append("absent")
    with pytest.raises(ValueError, match="근거"):
        parse_diagram_spec(spec, evidence=evidence)
    evidence[0].source_revision = "invalid"
    with pytest.raises(ValidationError):
        parse_diagram_spec(sample["diagram"], evidence=evidence)


def test_mutated_nested_source_locator_is_revalidated(sample):
    evidence = [Evidence.model_validate(e) for e in sample["evidence"]]
    evidence[1].locator.line_end = 1
    with pytest.raises(ValidationError, match="끝 행"):
        parse_diagram_spec(sample["diagram"], evidence=evidence)


@pytest.mark.parametrize("location", ["diagram", "node", "evidence", "locator"])
@pytest.mark.parametrize("field", ["quality", "_script"])
def test_reparse_rejects_extra_fields_on_copied_models_without_dropping_them(sample, location, field):
    evidence = [Evidence.model_validate(e) for e in sample["evidence"]]
    spec = parse(sample)
    if location == "diagram":
        spec = spec.model_copy(update={field: {"status": "pass"}})
    elif location == "node":
        spec.nodes[0] = spec.nodes[0].model_copy(update={field: {"font_size": 1}})
    elif location == "evidence":
        evidence[0] = evidence[0].model_copy(update={field: "pass"})
    else:
        evidence[0].locator = evidence[0].locator.model_copy(update={field: "pass"})
    with pytest.raises(ValidationError) as caught:
        parse_diagram_spec(spec, evidence=evidence)
    assert any(e["type"] == "extra_forbidden" for e in caught.value.errors())


def test_cyclic_python_evidence_object_is_rejected_without_recursing_forever(sample):
    evidence = [Evidence.model_validate(e) for e in sample["evidence"]]
    evidence[0].locator = evidence[0]
    with pytest.raises(ValueError, match="순환"):
        parse_diagram_spec(sample["diagram"], evidence=evidence)


@pytest.mark.parametrize("method", ["construct", "copy", "nested"])
def test_instances_created_without_validation_are_checked_by_supported_parser(sample, method):
    evidence = [Evidence.model_validate(e) for e in sample["evidence"]]
    if method == "construct":
        sample["diagram"]["version"] = "unsupported"
        payload = DiagramSpec.model_construct(**sample["diagram"])
    elif method == "copy":
        payload = parse(sample).model_copy(update={"version": "unsupported"})
    else:
        node = DiagramNode.model_construct(**sample["diagram"]["nodes"][0])
        node.content = 123
        sample["diagram"]["nodes"][0] = node
        payload = sample["diagram"]
    with pytest.raises(ValidationError):
        parse_diagram_spec(payload, evidence=evidence)


@pytest.mark.parametrize("field", ["page_size", "reading_profile"])
def test_canvas_only_accepts_named_supported_inputs(sample, field):
    sample["diagram"]["canvas"][field] = "custom"
    with pytest.raises(ValidationError):
        parse(sample)


@pytest.mark.parametrize("value", ["", "   ", "x" * 121, 12, None])
def test_edge_label_is_required_bounded_plain_text(sample, value):
    sample["diagram"]["edges"][0]["label"] = value
    with pytest.raises(ValidationError):
        parse(sample)


def test_a_longer_flow_cycle_is_rejected(sample):
    sample["diagram"]["edges"][1].update(relation="flow", evidence_ids=["e3"])
    sample["diagram"]["edges"].append({
        **sample["diagram"]["edges"][0], "id": "back", "from_node_id": "pilot", "to_node_id": "intake",
    })
    with pytest.raises(ValueError, match="순환"):
        parse(sample)


@pytest.mark.parametrize("payload", ["{", "[]", "null", "42"])
def test_json_parser_rejects_malformed_or_nonobject_input(sample, payload):
    with pytest.raises(ValueError):
        parse_diagram_spec(payload, evidence=[Evidence.model_validate(e) for e in sample["evidence"]])


def test_named_diagram_does_not_require_a_fixture_specific_identifier(sample):
    sample["diagram"]["id"] = "another-graph"
    sample["diagram"]["nodes"][0]["content"] = "새로운 합성 접수"
    assert parse(sample).id == "another-graph"


def test_contract_does_not_claim_to_verify_free_text_meaning(sample):
    # 의미 검수는 후속 단계다. 평문의 원인 표현과 마크업 모양을 실행하거나 품질 판정하지 않는다.
    sample["diagram"]["edges"][0]["label"] = "검토 완료 때문에 성과가 향상됐다"
    sample["diagram"]["nodes"][0]["content"] = "<b>합성 평문</b>"
    spec = parse(sample)
    assert spec.nodes[0].content == "<b>합성 평문</b>"
    assert spec.edges[0].label == sample["diagram"]["edges"][0]["label"]
