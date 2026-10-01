"""Signals are review candidates and never semantic approval."""
from copy import deepcopy
import pytest
from slidecaptain.models.deck import Deck,Slide,SummarySlots,BulletBoxSlots,Bullet,Chapter
from slidecaptain.pipeline.semantic_review import assess_semantic_suspects
from slidecaptain.pipeline.story import parse_story_structure,story_fingerprint
from test_derived_values import sample,BRIEF
from test_metric_comparison import META

def case(text='순매출은 20% 증가했다',registered=False):
 data,sources=sample()
 data['chapters'][0]['template']='summary'
 if not registered:data['comparisons']=[];data['derivations']=[]
 structure=parse_story_structure(data,META,BRIEF,sources)
 deck=Deck(meta=META,structure=structure,slides=[Slide(chapter_id=structure.chapters[0].id,slots=SummarySlots(conclusion=text))])
 return deck,sources

def codes(report):return {f.code for f in report.findings}

def test_unregistered_comparison_and_growth_formula_are_candidates_only():
 deck,sources=case('순매출은 기준 대비 20% 증가율이다')
 before=deck.model_dump_json();report=assess_semantic_suspects(deck,sources)
 assert {'unregistered_comparison','unregistered_formula'}<=codes(report)
 assert report.status=='needs_review';assert report.semantic_status=='not_run';assert deck.model_dump_json()==before


def test_declared_same_scope_comparison_and_derivation_suppress_unregistered_signal():
 report=assess_semantic_suspects(*case('순매출은 기준 대비 20% 증가율이다',True))
 assert 'unregistered_comparison' not in codes(report);assert 'unregistered_formula' not in codes(report)
 assert report.semantic_status=='not_run'


def test_arithmetic_expression_is_detected_without_eval():
 report=assess_semantic_suspects(*case('합계 = 100 + 20'))
 assert 'unregistered_formula' in codes(report)


@pytest.mark.parametrize('date',['2026-09-30','2026-09','2026/09','2026.09.30'])
def test_dates_numbers_and_qualitative_text_are_not_formula_or_comparison(date):
 report=assess_semantic_suspects(*case(date+' 자료를 보다. 원문 번호 10'))
 assert not report.findings;assert report.status=='no_signals_detected';assert report.semantic_status=='not_run'


def test_calculated_direction_is_review_candidate_when_same_metric_named():
 report=assess_semantic_suspects(*case('순매출은 200원 감소했다',True))
 assert 'calculated_direction_mismatch' in codes(report)


def test_other_metric_direction_does_not_create_mismatch():
 assert 'calculated_direction_mismatch' not in codes(assess_semantic_suspects(*case('비용은 200원 감소했다',True)))


def test_stale_source_is_not_run_and_does_not_modify_input():
 deck,sources=case();sources={k:v+'changed' for k,v in sources.items()};report=assess_semantic_suspects(deck,sources)
 assert report.status=='not_run';assert report.reason=='stale_plan';assert report.evaluated_fields==0


def summary_body(*, shared=True, same_metric=True):
 data,sources=sample()
 data['chapters'][0]['template']='summary'
 if not shared:data['claims'].append({**deepcopy(data['claims'][0]),'id':'k2'})
 data['chapters'].append({'topic':'본문 검토','conclusion':'방향 확인','template':'bullet_box','role':'evidence','claim_ids':['k1' if shared else 'k2']})
 structure=parse_story_structure(data,META,BRIEF,sources)
 slides=[Slide(chapter_id='c1',slots=SummarySlots(conclusion='순매출은 증가했다')),
         Slide(chapter_id='c2',slots=BulletBoxSlots(conclusion='본문 확인',bullets=[Bullet(text=('순매출' if same_metric else '비용')+'은 감소했다')]))]
 return Deck(meta=META,structure=structure,slides=slides),sources


def test_summary_direction_uses_shared_claim_and_returns_original_body():
 deck,sources=summary_body();before=deck.model_dump_json()
 report=assess_semantic_suspects(deck,sources)
 findings=[f for f in report.findings if f.code=='summary_direction_conflict']
 assert len(findings)==1
 assert findings[0].claim_ids==['k1'];assert findings[0].comparison_ids==['cmp1']
 assert findings[0].related_texts[0].text=='순매출은 감소했다'
 assert deck.model_dump_json()==before


def test_unshared_claim_or_other_metric_cannot_create_summary_conflict():
 for kwargs in ({'shared':False},{'same_metric':False}):
  assert 'summary_direction_conflict' not in codes(assess_semantic_suspects(*summary_body(**kwargs)))


def test_other_nonanswer_claim_formula_cannot_suppress_current_claim_signal():
 data,sources=sample()
 data['claims'].append({**deepcopy(data['claims'][0]),'id':'k2','statement':'순매출은 대비 200원 차이가 있다'})
 data['chapters'].append({'topic':'추가 검토','conclusion':'산식 확인','template':'bullet_box','role':'evidence','claim_ids':['k2']})
 structure=parse_story_structure(data,META,BRIEF,sources)
 deck=Deck(meta=META,structure=structure)
 report=assess_semantic_suspects(deck,sources)
 assert any(f.code=='unregistered_comparison' and f.claim_ids==['k2'] for f in report.findings)


def test_fingerprint_changes_with_body_and_current_source():
 deck,sources=case();first=assess_semantic_suspects(deck,sources)
 deck.slides[0].slots.conclusion='동일 자료를 직접 확인한다'
 second=assess_semantic_suspects(deck,sources)
 assert first.input_fingerprint!=second.input_fingerprint
 assert second.status=='no_signals_detected';assert second.semantic_status=='not_run'
 assert '미수행' in second.scope_notice


def test_missing_plan_and_empty_target_are_not_run(monkeypatch):
 import slidecaptain.pipeline.semantic_review as module
 deck,sources=case();deck.structure.story_plan=None
 assert assess_semantic_suspects(deck,sources).reason=='missing_plan'
 deck,sources=case();monkeypatch.setattr(module,'_fields',lambda deck:iter(()))
 assert assess_semantic_suspects(deck,sources).reason=='no_reviewable_fields'


def test_limits_return_unexecuted_instead_of_partial_findings(monkeypatch):
 import slidecaptain.pipeline.semantic_review as module
 deck,sources=case('기준 대비 20% 증가율')
 for name in ('_MAX_FIELDS','_MAX_CHARS','_MAX_FINDINGS'):
  with monkeypatch.context() as context:
   context.setattr(module,name,0)
   report=assess_semantic_suspects(deck,sources)
   assert report.status=='not_run';assert report.reason=='review_limit';assert report.evaluated_fields==0;assert report.findings==[]


def test_forged_excerpt_cannot_be_reapproved_by_new_fingerprint():
 deck,sources=case(registered=True);plan=deck.structure.story_plan
 plan.evidence[0].excerpt='다른 내용 1200원'
 plan.input_fingerprint=story_fingerprint(plan,deck.meta,deck.structure.chapters,sources)
 assert assess_semantic_suspects(deck,sources).reason in ('stale_plan','invalid_plan')


def test_document_viewing_idiom_with_a_number_is_not_a_comparison():
 report=assess_semantic_suspects(*case('자료를 보다 보니 원문 번호 10을 발견했다'))
 assert 'unregistered_comparison' not in codes(report)
 assert report.semantic_status=='not_run'
