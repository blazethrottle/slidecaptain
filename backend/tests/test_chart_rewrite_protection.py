"""Charts preserve their source graph when only the story plan is rewritten."""
import pytest

from slidecaptain.models.deck import Deck, Slide, TableSlots
from slidecaptain.models.expression import ChartSpec
from slidecaptain.pipeline.rewrite import (
    ProtectedEvidenceChanged, parse_story_rewrite, protected_story, validate_rewrite,
)
from slidecaptain.pipeline.story import parse_story_structure, story_fingerprint
from test_derived_values import BRIEF
from test_metric_comparison import META
from test_unit_conversion import normalized


def chart_case():
    data, sources = normalized()
    data['chapters'][0]['template'] = 'table'
    structure = parse_story_structure(data, META, BRIEF, sources)
    deck = Deck(meta=META, structure=structure, slides=[Slide(
        chapter_id='c1', slots=TableSlots(columns=['팀', '원값'], rows=[['A', '1.2천원'], ['B', '1000원']]),
        chart=ChartSpec(rule_version='comparison-chart-v1', comparison_id='cmp1', kind='column'),
    )])
    payload = {'chapter_order': ['c1'], 'chapters': [], 'claims': [], 'evidence': [],
               'comparisons': [], 'derivations': [], 'answer_claim_ids': ['k1'], 'unanswered_questions': []}
    return deck, sources, payload


def test_chart_source_graph_and_normalization_are_server_preserved():
    deck, sources, payload = chart_case()
    kept = protected_story(deck, sources)
    assert [item['id'] for item in kept['comparisons']] == ['cmp1']
    assert kept['comparisons'][0]['unit_normalization']['target_unit'] == '원'
    assert {item['id'] for item in kept['evidence']} == {'e1', 'e2'}
    assert kept['derivations'][0]['id'] == 'd1'
    candidate = parse_story_rewrite(payload, deck, BRIEF, sources)
    assert candidate.slides == deck.slides
    assert protected_story(candidate, sources) == kept
    assert candidate.structure.story_plan.derived_values[0].unit_conversions == deck.structure.story_plan.derived_values[0].unit_conversions


def test_chart_protected_claim_cannot_be_reprinted_or_changed():
    deck, sources, payload = chart_case()
    payload['claims'] = [deck.structure.story_plan.claims[0].model_dump()]
    with pytest.raises(ValueError, match='보호'):
        parse_story_rewrite(payload, deck, BRIEF, sources)
    payload['claims'] = []
    candidate = parse_story_rewrite(payload, deck, BRIEF, sources)
    candidate.structure.story_plan.claims[0].statement = '다른 새 의미'
    candidate.structure.story_plan.input_fingerprint = story_fingerprint(candidate.structure.story_plan, candidate.meta, candidate.structure.chapters, sources)
    with pytest.raises(ValueError, match='보존'):
        validate_rewrite(deck, candidate, sources)


def test_changed_chart_source_is_blocked_even_when_selected_lines_survive():
    deck, sources, _ = chart_case()
    with pytest.raises(ProtectedEvidenceChanged):
        protected_story(deck, {key: value+'\n추가 문맥' for key, value in sources.items()})
