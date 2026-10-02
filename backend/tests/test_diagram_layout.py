"""Q3b 계산 계약. 실제 브라우저/PPTX/독자 품질의 대리 검사가 아니다."""

from copy import deepcopy
import json
import math
from pathlib import Path

import pytest

from slidecaptain.layout.diagram import build_diagram_layout
from slidecaptain.metrics.font_metrics import FontMetrics
from slidecaptain.models.diagram import parse_diagram_spec
from slidecaptain.models.diagram_render import DiagramLayoutResult
from slidecaptain.models.preset import Preset, content_box
from slidecaptain.models.story import Evidence


@pytest.fixture
def sample():
    return json.loads((Path(__file__).parent / 'fixtures/q3a-diagram.json').read_text('utf-8'))


def build(sample, preset=None, metrics=None):
    return build_diagram_layout(
        sample['diagram'], preset or Preset(), metrics or FontMetrics.load_default(),
        evidence=[Evidence.model_validate(e) for e in sample['evidence']],
    )


def test_determinism_roundtrip_and_no_input_mutation(sample):
    before = deepcopy(sample)
    preset, metrics = Preset(), FontMetrics.load_default()
    preset_before, metrics_before = preset.model_dump(), metrics.to_json()
    result = build(sample, preset, metrics)
    assert result.status == 'computed'
    assert result == build(sample, preset, metrics)
    assert DiagramLayoutResult.model_validate_json(result.model_dump_json()) == result
    assert result.review.model_dump() == dict.fromkeys(
        ['semantic', 'browser', 'powerpoint', 'reader'], 'not_run',
    )
    assert sample == before
    assert preset.model_dump() == preset_before
    assert metrics.to_json() == metrics_before
    assert result.plan is not None and not result.issues


def test_all_semantics_support_and_caveats_survive(sample):
    plan = build(sample).plan
    assert [n.node.model_dump() for n in plan.nodes] == sample['diagram']['nodes']
    assert [e.edge.model_dump() for e in plan.edges] == sample['diagram']['edges']
    assert [t.text for t in plan.nodes[2].texts] == [
        '제안 / 결과', '자동 알림 도입 제안', '조건: 효과와 비용은 확인하지 않았다.',
    ]
    assert plan.edges[1].label.text == '제안: 알림 도입 제안\n주체: 요청 검토\n대상: 자동 알림 도입 제안'


def test_flow_order_and_arrow_direction_are_from_relationship(sample):
    sample['diagram']['nodes'][:2] = reversed(sample['diagram']['nodes'][:2])
    plan = build(sample).plan
    assert [n.node.id for n in plan.nodes] == ['intake', 'review', 'pilot']
    flow = plan.edges[0]
    assert flow.start.side == 'right' and flow.end.side == 'left'
    assert flow.start.point.x < flow.end.point.x
    assert flow.arrow_points[0] == flow.end.point
    assert all(p.x < flow.end.point.x for p in flow.arrow_points[1:])
    assert flow.stroke == 'solid'


@pytest.mark.parametrize('relation,stroke', [('reference', 'dotted'), ('proposal', 'dashed')])
def test_non_flow_keeps_input_direction_without_an_arrow(sample, relation, stroke):
    sample['diagram']['edges'][0].update(
        relation=relation, from_node_id='review', to_node_id='intake',
    )
    plan = build(sample).plan
    assert [n.node.id for n in plan.nodes] == ['intake', 'review', 'pilot']
    edge = plan.edges[0]
    assert edge.start.side == 'left' and edge.end.side == 'right'
    assert edge.start.point.x > edge.end.point.x
    assert edge.arrow_points == [] and edge.stroke == stroke


def test_parallel_relations_use_distinct_lanes_and_keep_all_edges(sample):
    edge = sample['diagram']['edges'][0]
    sample['diagram']['edges'].extend([
        {**edge, 'id': 'reference', 'relation': 'reference'},
        {**edge, 'id': 'proposal', 'relation': 'proposal'},
    ])
    plan = build(sample).plan
    group = [e for e in plan.edges if e.edge.to_node_id == 'review']
    assert len(group) == 3
    ordered = sorted(group, key=lambda e: e.label.bounds.y)
    for a, b in zip(ordered, ordered[1:]):
        assert a.label.bounds.y + a.label.bounds.h < a.start.point.y
        assert a.start.point.y < b.label.bounds.y
    assert len(plan.edges) == 4


def test_every_box_line_and_arrow_is_finite_and_within_content(sample):
    preset = Preset()
    plan = build(sample, preset).plan
    g = content_box(preset)
    left, right = preset.spacing.margin_left, preset.page_width_pt - preset.spacing.margin_right
    top, bottom = g['content_top'], g['content_bottom']
    for bounds in [*(n.bounds for n in plan.nodes),
                   *(t.bounds for n in plan.nodes for t in n.texts),
                   *(e.label.bounds for e in plan.edges)]:
        assert all(math.isfinite(v) for v in bounds.model_dump().values())
        assert left <= bounds.x <= bounds.x + bounds.w <= right + 1e-8
        assert top <= bounds.y <= bounds.y + bounds.h <= bottom + 1e-8
    for edge in plan.edges:
        for point in [edge.start.point, edge.end.point, *edge.arrow_points]:
            assert left <= point.x <= right and top <= point.y <= bottom
    nodes = {n.node.id: n for n in plan.nodes}
    for edge in plan.edges:
        for endpoint, node_id in [(edge.start, edge.edge.from_node_id), (edge.end, edge.edge.to_node_id)]:
            b = nodes[node_id].bounds
            assert endpoint.point.x == (b.x if endpoint.side == 'left' else b.x + b.w)
            assert b.y < endpoint.point.y < b.y + b.h


def test_wraps_korean_english_newlines_and_conditions_without_losing_text(sample):
    sample['diagram']['nodes'][0]['content'] = '요청 검토 담당자가 자료를 확인한다.\nLongUnbrokenEnglishWordForWrapping'
    sample['diagram']['nodes'][0]['kind'] = 'inference'
    sample['diagram']['nodes'][0]['caveats'] = ['자료 범위를 확인해야 한다.', '효과는 아직 미확인이다.']
    metrics, preset = FontMetrics.load_default(), Preset()
    result = build(sample, preset, metrics)
    assert result.status == 'computed'
    for text in [*(t for n in result.plan.nodes for t in n.texts), *(e.label for e in result.plan.edges)]:
        assert ''.join(''.join(text.lines).split()) == ''.join(text.text.split())
        assert text.font_pt >= 12
        assert text.line_height_pt >= text.font_pt
        assert text.bounds.h == pytest.approx(len(text.lines) * text.line_height_pt)
        assert all(metrics.face(text.bold).width_pt(line, text.font_pt) <= text.bounds.w * preset.spacing.safety_ratio + 1e-8 for line in text.lines)
    assert len(result.plan.nodes[0].texts) == 4


@pytest.mark.parametrize('location', ['node', 'label', 'caveat'])
def test_insufficient_height_returns_reason_and_no_partial_plan(sample, location):
    if location == 'node':
        sample['diagram']['nodes'][0]['content'] = '문' * 500
    elif location == 'label':
        sample['diagram']['edges'][0]['label'] = '문' * 120
    else:
        sample['diagram']['nodes'][0]['caveats'] = ['조건' * 250]
    preset = Preset(page_height_pt=270)
    result = build(sample, preset)
    assert result.status == 'blocked' and result.plan is None
    assert any(i.code == 'height_overflow' and i.needed_pt > i.available_pt for i in result.issues)


def test_one_glyph_too_wide_is_not_accepted_after_wrapping(sample):
    preset = Preset(page_width_pt=210)
    result = build(sample, preset)
    assert result.status == 'blocked' and result.plan is None
    assert any(i.code == 'width_overflow' for i in result.issues)


def test_valid_but_nonadjacent_graph_is_explicitly_blocked(sample):
    sample['diagram']['edges'][1]['from_node_id'] = 'intake'
    result = build(sample)
    assert result.status == 'blocked' and result.plan is None
    assert [(i.code, i.target_id) for i in result.issues] == [('unsupported_topology', 'suggestion')]


@pytest.mark.parametrize('field', ['korean', 'latin'])
def test_font_name_mismatch_is_not_measured_as_noto(sample, field):
    preset = Preset()
    setattr(preset.fonts, field, 'Other Font')
    result = build(sample, preset)
    assert result.status == 'blocked'
    assert result.issues[0].code == 'unsupported_font'


def test_tight_line_height_is_not_called_computed(sample):
    preset = Preset()
    preset.spacing.line_spacing = 0.5
    result = build(sample, preset)
    assert result.status == 'blocked'
    assert result.issues[0].code == 'unsupported_spacing'


@pytest.mark.parametrize('change', ['text', 'caveat', 'edge', 'evidence', 'preset', 'metrics'])
def test_input_fingerprint_binds_all_calculation_inputs(sample, change):
    preset, metrics = Preset(), FontMetrics.load_default()
    first = build(sample, preset, metrics)
    if change == 'text':
        sample['diagram']['nodes'][0]['content'] += ' 확인'
    elif change == 'caveat':
        sample['diagram']['nodes'][0]['caveats'] = ['합성 자료']
    elif change == 'edge':
        sample['diagram']['edges'][0]['label'] += ' 확인'
    elif change == 'evidence':
        sample['evidence'][0]['excerpt'] += ' 다른 근거'
    elif change == 'preset':
        preset.font_roles.body_pt = 13
    else:
        metrics.regular.widths[ord('a')] += 1
    assert first.input_fingerprint != build(sample, preset, metrics).input_fingerprint


def test_revalidates_mutated_diagram_and_preset(sample):
    evidence = [Evidence.model_validate(e) for e in sample['evidence']]
    spec = parse_diagram_spec(sample['diagram'], evidence=evidence)
    spec.edges[0].to_node_id = 'absent'
    with pytest.raises(ValueError):
        build_diagram_layout(spec, Preset(), FontMetrics.load_default(), evidence=evidence)
    preset = Preset()
    object.__setattr__(preset.font_roles, 'box_pt', 1)
    with pytest.raises(ValueError):
        build(sample, preset)


@pytest.mark.parametrize('bad', [0, -1, float('inf'), float('nan')])
def test_invalid_metrics_are_rejected_before_layout(sample, bad):
    metrics = FontMetrics.load_default()
    metrics.regular.upem = bad
    with pytest.raises(ValueError):
        build(sample, metrics=metrics)


def test_blocked_result_cannot_contain_a_plan(sample):
    value = build(sample).model_dump(mode='json')
    value['status'] = 'blocked'
    with pytest.raises(ValueError):
        DiagramLayoutResult.model_validate(value)


@pytest.mark.parametrize('text', ['가' + ' ' * 450 + '나', '가\t나', '가\r나',
                                  '가\n 나', '가 \n나', '가🙂나', '漢字'])
def test_unsupported_text_is_not_silently_changed_or_measured_with_fallback(sample, text):
    sample['diagram']['nodes'][0]['content'] = text
    result = build(sample)
    assert result.status == 'blocked' and result.plan is None
    assert any(i.code == 'unsupported_text' and i.target_id == 'intake' for i in result.issues)


@pytest.mark.parametrize('location', ['label', 'caveat'])
def test_text_support_applies_to_conditions_and_labels(sample, location):
    if location == 'label':
        sample['diagram']['edges'][0]['label'] = '관계  확인'
    else:
        sample['diagram']['nodes'][0]['caveats'] = ['조건  확인']
    assert build(sample).status == 'blocked'


def test_duplicate_content_is_disambiguated_in_nodes_and_nonflow_labels(sample):
    sample['diagram']['nodes'][0]['content'] = '같은 내용'
    sample['diagram']['nodes'][1]['content'] = '같은 내용'
    sample['diagram']['edges'][0]['relation'] = 'reference'
    plan = build(sample).plan
    assert plan.nodes[0].display_name != plan.nodes[1].display_name
    for node in plan.nodes[:2]:
        assert node.display_name in plan.edges[0].label.text
        assert node.display_name in [t.text for t in node.texts]
        assert node.node.content == '같은 내용'


def test_generated_display_name_cannot_collide_with_another_original_content(sample):
    for node in sample['diagram']['nodes'][:2]:
        node['content'] = '같은 내용'
    sample['diagram']['nodes'][2]['content'] = '같은 내용 (intake)'
    plan = build(sample).plan
    assert len({node.display_name for node in plan.nodes}) == 3
    assert all(node.node.id in node.display_name for node in plan.nodes)


@pytest.mark.parametrize('width', [0.1, 12, 48, 180, 1000])
def test_border_and_arrow_footprints_are_accounted_for(sample, width):
    preset = Preset()
    preset.spacing.border_width_pt = width
    result = build(sample, preset)
    if result.status == 'blocked':
        assert result.issues and result.plan is None
        return
    bounds = result.plan.content_bounds
    for node in result.plan.nodes:
        box = node.bounds
        assert bounds.x <= box.x - width / 2
        assert box.x + box.w + width / 2 <= bounds.x + bounds.w + 1e-8
        assert bounds.y <= box.y - width / 2
        assert box.y + box.h + width / 2 <= bounds.y + bounds.h + 1e-8
    for edge in result.plan.edges:
        for point in edge.arrow_points:
            assert bounds.y <= point.y - width / 2
            assert point.y + width / 2 <= bounds.y + bounds.h


@pytest.mark.parametrize('part', ['root', 'spacing', 'fonts', 'font_roles'])
def test_preset_extra_fields_are_not_lost_before_validation(sample, part):
    preset = Preset()
    target = preset if part == 'root' else getattr(preset, part)
    object.__setattr__(target, 'unexpected', 'synthetic')
    with pytest.raises(ValueError):
        build(sample, preset)


@pytest.mark.parametrize('face', ['regular', 'bold'])
@pytest.mark.parametrize('part', ['fallback_width', 'hangul_uniform_width', 'widths'])
def test_invalid_metric_values_are_checked_in_both_faces(sample, face, part):
    metrics = FontMetrics.load_default()
    target = getattr(metrics, face)
    if part == 'widths':
        target.widths[ord('A')] = float('nan')
    else:
        setattr(target, part, float('inf'))
    with pytest.raises(ValueError):
        build(sample, metrics=metrics)


def test_overflow_in_valid_preset_is_not_published_as_a_plan(sample):
    preset = Preset()
    preset.spacing.line_spacing = 1e308
    result = build(sample, preset)
    assert result.status == 'blocked'
    assert all(i.code == 'invalid_geometry' for i in result.issues)


def test_unchanged_graph_is_not_given_order_by_reference_edges(sample):
    sample['diagram']['edges'][0].update(relation='reference', from_node_id='review', to_node_id='intake')
    a = build(sample)
    sample['diagram']['edges'][0].update(from_node_id='intake', to_node_id='review')
    b = build(sample)
    assert [n.node.id for n in a.plan.nodes] == [n.node.id for n in b.plan.nodes]
    assert a.plan.edges[0].label.text != b.plan.edges[0].label.text


def test_font_unit_underflow_cannot_make_visible_text_zero_width(sample):
    sample['diagram']['nodes'][0]['content'] = '가' * 500
    metrics = FontMetrics.load_default()
    metrics.regular.upem = metrics.bold.upem = 10 ** 400
    with pytest.raises(ValueError):
        build(sample, metrics=metrics)


@pytest.mark.parametrize('part', ['regular', 'bold', 'regular.upem', 'regular.widths',
                                  'regular.hangul_uniform_width', 'regular.fallback_width'])
def test_missing_metric_structure_returns_the_input_error_contract(sample, part):
    metrics = FontMetrics.load_default()
    names = part.split('.')
    target = metrics if len(names) == 1 else getattr(metrics, names[0])
    delattr(target, names[-1])
    with pytest.raises(ValueError):
        build(sample, metrics=metrics)


@pytest.mark.parametrize('field', ['nodes', 'edges'])
def test_computed_json_cannot_claim_an_empty_diagram(sample, field):
    value = build(sample).model_dump(mode='json')
    value['plan'][field] = []
    with pytest.raises(ValueError):
        DiagramLayoutResult.model_validate(value)
