"""Q2e uses explicit scale requests and preserves original evidence."""
from copy import deepcopy
import pytest
from slidecaptain.models.story import StoryPlan
from slidecaptain.pipeline.story import StoryDraft
from test_derived_values import sample,plan_for

def normalized(left='1.2천원',right='1000원',target='원',operation='difference'):
 data,sources=sample(left,right,operation)
 for e,u in zip(data['evidence'],('천원','원')):e['metric_basis']['unit']=u
 data['comparisons'][0]['unit_normalization']={'rule_version':'unit-scale-v1','target_unit':target}
 return data,sources

def test_explicit_normalization_preserves_raw_values_and_audits_exact_factors():
 data,sources=normalized();plan=plan_for(data,sources);result=plan.derived_values[0]
 assert plan.version=='q2e-v1';assert plan.comparison_results[0].status=='compatible'
 assert (result.value,result.unit,result.status)==('200','원','computed')
 assert [e.value for e in plan.evidence]==['1.2천원','1000원']
 assert [e.metric_basis.unit for e in plan.evidence]==['천원','원']
 assert result.unit_conversions[0].normalized_value=='1200'
 assert result.unit_conversions[0].factor_numerator=='1000';assert result.unit_conversions[0].factor_denominator=='1'
 assert result.unit_conversions[0].original_value=='1.2천원'

@pytest.mark.parametrize('target,value,unit',[('천원','0.2','천원'),('만원','0.02','만원'),('억원','0.000002','억원')])
def test_downscales_are_fraction_exact(target,value,unit):
 plan=plan_for(*normalized(target=target));assert(plan.derived_values[0].value,plan.derived_values[0].unit)==(value,unit)

@pytest.mark.parametrize('unit,target',[('명','원'),('%','원'),('달러','원'),('원','명')])
def test_different_dimension_percent_and_unknown_source_are_blocked(unit,target):
 data,sources=normalized(target=target);data['evidence'][0]['metric_basis']['unit']=unit
 plan=plan_for(data,sources);assert plan.comparison_results[0].status=='incompatible';assert plan.derived_values[0].status=='blocked'

@pytest.mark.parametrize('version',['q2a-v1','q2b-v1','q2c-v1'])
def test_old_version_cannot_hide_normalization(version):
 saved=plan_for(*normalized()).model_dump(mode='json');saved['version']=version
 with pytest.raises(ValueError):StoryPlan.model_validate(saved)

def test_model_cannot_supply_factor_or_conversion_results():
 data,sources=normalized();data['comparisons'][0]['unit_normalization']['factor']='999'
 with pytest.raises(ValueError):StoryDraft.model_validate(data)
 data,sources=normalized();data['unit_conversions']=[]
 with pytest.raises(ValueError):StoryDraft.model_validate(data)

def test_tampered_audit_is_recomputed_on_reload():
 saved=plan_for(*normalized()).model_dump(mode='json');saved['derived_values'][0]['unit_conversions'][0]['normalized_value']='999'
 result=StoryPlan.model_validate(saved).derived_values[0];assert result.unit_conversions[0].normalized_value=='1200'

def test_without_request_existing_unit_mismatch_is_preserved():
 data,sources=normalized();data['comparisons'][0].pop('unit_normalization');plan=plan_for(data,sources)
 assert plan.version=='q2c-v1';assert plan.derived_values[0].status=='blocked'
 assert 'unit_normalization' not in plan.comparisons[0].model_dump()
 assert 'unit_conversions' not in plan.derived_values[0].model_dump()

@pytest.mark.parametrize('unit_pair,target,left,right,value',[
 (('천명','명'),'명','1.2천명','1000명','200'),
 (('천건','건'),'건','1.2천건','1000건','200'),
 (('원','원'),'원','1200원','1000원','200'),
 (('억원','천원'),'백만원','1억원','50000천원','50'),
])
def test_registry_dimensions_and_identity_request(unit_pair,target,left,right,value):
 data,sources=sample(left,right)
 for evidence,unit in zip(data['evidence'],unit_pair):evidence['metric_basis']['unit']=unit
 data['comparisons'][0]['unit_normalization']={'rule_version':'unit-scale-v1','target_unit':target}
 plan=plan_for(data,sources);assert plan.version=='q2e-v1';assert plan.derived_values[0].value==value
 assert len(plan.derived_values[0].unit_conversions)==2
 assert plan.comparison_results[0].rule_version=='q2e-v1'

@pytest.mark.parametrize('left,right,operation,value,rounded',[
 ('1.2천원','1000원','percent_change','20',False),
 ('1.2천원','0원','difference','1200',False),
 ('0.000001천원','0원','difference','0.000001',False),
 ('0.000001천원','0원','difference','0',True),
])
def test_normalization_arithmetic_precision(left,right,operation,value,rounded):
 target='천원' if value=='0.000001' else '억원' if rounded else '원'
 result=plan_for(*normalized(left,right,target,operation)).derived_values[0]
 assert result.value==value;assert result.rounded is rounded

@pytest.mark.parametrize('change', ['ratio','denominator','definition','malformed','zero_baseline','partial'])
def test_conversion_keeps_old_metadata_and_raw_numeric_guards(change):
 data,sources=normalized(operation='percent_change' if change=='zero_baseline' else 'difference')
 if change=='ratio':data['evidence'][0]['metric_basis']['period']['aggregation']='ratio'
 elif change=='denominator':data['evidence'][0]['metric_basis']['denominator']={'kind':'population','definition':'all'}
 elif change=='definition':data['evidence'][0]['metric_basis']['definition']='other'
 elif change=='partial':data['evidence'][0]['metric_basis']['period']['coverage']='partial'
 elif change=='malformed':
  data,sources=normalized(left='약 1.2천원')
 else:data,sources=normalized(right='0원',operation='percent_change')
 result=plan_for(data,sources).derived_values[0];assert result.status=='blocked';assert result.value is None


def test_q2c_fixture_keeps_saved_plan_and_fingerprint():
 import json
 from pathlib import Path
 from slidecaptain.models.deck import Deck
 from slidecaptain.pipeline.story import require_current_story
 saved=json.loads((Path(__file__).parent/'fixtures/q2c-derived-deck.json').read_text())
 deck=Deck.model_validate(saved['deck']);require_current_story(deck,saved['sources'])
 assert deck.structure.story_plan.model_dump(mode='json')==saved['deck']['structure']['story_plan']


def test_protected_normalization_survives_rewrite():
 from scripts.quality_pilot import scenario
 from slidecaptain.models.deck import Deck
 from slidecaptain.models.story import ReportBrief
 from slidecaptain.pipeline.rewrite import parse_story_rewrite, protected_story
 from slidecaptain.pipeline.story import story_fingerprint,require_current_story
 case=scenario();raw=deepcopy(case['deck']);plan=raw['structure']['story_plan']
 plan['version']='q2e-v1';plan['comparisons']=[{'id':'kept','claim_id':'claim','left_evidence_id':'e1','right_evidence_id':'e2','axis':'entity','unit_normalization':{'rule_version':'unit-scale-v1','target_unit':'원'}}]
 plan['derivations']=[{'id':'d','comparison_id':'kept','operation':'difference'}]
 deck=Deck.model_validate(raw);deck.structure.story_plan.input_fingerprint=story_fingerprint(deck.structure.story_plan,deck.meta,deck.structure.chapters,case['sources'])
 payload={'chapter_order':['cover','pilot-action','synthetic-flow'],'chapters':[{'chapter_id':'cover','role':'cover','claim_ids':[]},{'chapter_id':'pilot-action','role':'action','claim_ids':['action']}], 'claims':[deck.structure.story_plan.claims[-1].model_dump()],'evidence':[], 'answer_claim_ids':['claim'],'unanswered_questions':[], 'comparisons':[], 'derivations':[]}
 candidate=parse_story_rewrite(payload,deck,ReportBrief.model_validate(case['rewrite_brief']),case['sources'])
 assert candidate.structure.story_plan.version=='q2e-v1';assert protected_story(candidate,case['sources'])==protected_story(deck,case['sources'])
 require_current_story(candidate,case['sources'])


def test_old_version_cannot_keep_new_audit_fields_without_input_request():
 saved=plan_for(*normalized()).model_dump(mode='json');saved['version']='q2c-v1'
 saved['comparisons'][0].pop('unit_normalization')
 with pytest.raises(ValueError,match='q2e-v1'):StoryPlan.model_validate(saved)


def test_large_original_number_is_not_truncated_by_normalization():
 data,sources=normalized(left='123456789012345678901234천원',right='0원')
 result=plan_for(data,sources).derived_values[0]
 assert result.value=='123456789012345678901234000'
 assert result.unit_conversions[0].normalized_value=='123456789012345678901234000'
 assert not result.rounded


def test_normalization_and_audit_bind_fingerprint():
 from slidecaptain.pipeline.story import story_fingerprint
 from test_metric_comparison import META
 from slidecaptain.pipeline.story import parse_story_structure
 from test_derived_values import BRIEF
 data,sources=normalized();structure=parse_story_structure(data,META,BRIEF,sources)
 original=structure.story_plan.input_fingerprint
 data['comparisons'][0]['unit_normalization']['target_unit']='천원'
 modified=parse_story_structure(data,META,BRIEF,sources)
 assert modified.story_plan.input_fingerprint!=original


@pytest.mark.parametrize('field,value',[('source_unit','원'),('source_units',['원','원']),('factor',1000),('normalized_value','100')])
def test_response_normalization_accepts_only_registry_rule_and_target(field,value):
 data,sources=normalized();data['comparisons'][0]['unit_normalization'][field]=value
 with pytest.raises(ValueError):StoryDraft.model_validate(data)


def test_empty_conversion_metadata_is_optional_in_serialization_schema():
 from slidecaptain.models.derivation import DerivedValue
 schema=DerivedValue.model_json_schema(mode='serialization')
 assert 'unit_conversions' not in schema.get('required',[])
 assert 'default' not in schema['properties']['unit_conversions']
 result=DerivedValue(derivation_id='d',status='blocked',formula='difference')
 assert 'unit_conversions' not in result.model_dump(mode='json')
