"""Pure candidate changes require exact server recomputation and explicit losses."""

import hashlib
import json
from pathlib import Path
import pytest

from slidecaptain.models.deck import Deck
from slidecaptain.models.document_changes import EvidenceMigrationRequest
from slidecaptain.pipeline.rewrite import sources_fingerprint
from slidecaptain.pipeline.story import story_fingerprint

KEY=b'local-test-server-secret-key-32bytes'


def sample():
    fixture=json.loads((Path(__file__).parent/'fixtures/q3b-project.json').read_text())
    deck=Deck.model_validate(fixture['deck'])
    sources=fixture['sources']
    deck.structure.story_plan.input_fingerprint=story_fingerprint(deck.structure.story_plan,deck.meta,deck.structure.chapters,sources)
    return deck,sources


def test_whole_document_preview_is_unsaved_and_confirmation_is_exact():
    from slidecaptain.pipeline.document_changes import preview_document_change,apply_document_change
    base,sources=sample()
    original=base.model_dump(mode='json')
    candidate=base.model_copy(deep=True)
    candidate.slides[0].slots.diagram.nodes[0].content+=' 변경'
    preview=preview_document_change(base,candidate,sources,KEY)
    assert base.model_dump(mode='json')==original
    assert preview.losses and preview.final_export_allowed is False
    assert preview.candidate.document_review.requires_independent_review is True
    applied=apply_document_change(base,preview.candidate,sources,KEY,preview.confirmation_token,[i.id for i in preview.losses])
    assert applied==preview.candidate
    for token,ids in [('0'*64,[i.id for i in preview.losses]),(preview.confirmation_token,[]),
                      (preview.confirmation_token,[preview.losses[0].id]*2)]:
        with pytest.raises(ValueError):
            apply_document_change(base,preview.candidate,sources,KEY,token,ids)


def test_explicit_evidence_migration_materializes_current_source_and_preserves_graph_ids():
    from slidecaptain.pipeline.document_changes import preview_evidence_migration,apply_evidence_migration,evidence_fingerprint
    base,sources=sample()
    old=base.structure.story_plan.evidence[0]
    new_sources={**sources,'moved.md':old.excerpt}
    selection=old.model_dump(exclude={'source_revision','excerpt'})
    selection.update(source_id='moved.md',locator={'line_start':1,'line_end':len(old.excerpt.splitlines())})
    req=EvidenceMigrationRequest(evidence_id=old.id,old_evidence_fingerprint=evidence_fingerprint(old),new_selection=selection,
                                 expected_source_fingerprint=sources_fingerprint(new_sources))
    preview=preview_evidence_migration(base,req,new_sources,KEY)
    applied=apply_evidence_migration(base,req,new_sources,KEY,preview.confirmation_token,[i.id for i in preview.losses])
    migrated=applied.structure.story_plan.evidence[0]
    assert migrated.id==old.id and migrated.source_id=='moved.md'
    assert migrated.source_revision==hashlib.sha256(old.excerpt.encode()).hexdigest()
    assert applied.structure.story_plan.claims==base.structure.story_plan.claims
    assert base.structure.story_plan.evidence[0]==old


def test_ordinary_replacement_cannot_modify_protected_evidence():
    from slidecaptain.pipeline.document_changes import preview_document_change
    base,sources=sample()
    candidate=base.model_copy(deep=True)
    candidate.structure.story_plan.claims[0].statement+=' 새로운 주장'
    with pytest.raises(ValueError):
        preview_document_change(base,candidate,sources,KEY)


@pytest.mark.parametrize('damage',['source','candidate','base','marker','secret','ack_extra'])
def test_confirmation_rejects_changed_inputs_and_client_marker(damage):
    from slidecaptain.pipeline.document_changes import preview_document_change,apply_document_change
    base,sources=sample()
    candidate=base.model_copy(deep=True)
    candidate.slides[0].subtitle='문서 변경'
    preview=preview_document_change(base,candidate,sources,KEY)
    candidate=preview.candidate.model_copy(deep=True)
    key=KEY;ids=[i.id for i in preview.losses]
    if damage=='source':sources={name:text+' 변경' for name,text in sources.items()}
    elif damage=='candidate':candidate.slides[0].subtitle+=' 더 변경'
    elif damage=='base':base.slides[0].subtitle='동시 변경'
    elif damage=='marker':candidate.document_review.base_fingerprint='0'*64
    elif damage=='secret':key=b'x'*32
    elif damage=='ack_extra':ids.append('unknown')
    with pytest.raises(ValueError):
        apply_document_change(base,candidate,sources,key,preview.confirmation_token,ids)


def test_migration_never_refreshes_other_stale_evidence_in_same_source():
    from slidecaptain.pipeline.document_changes import preview_evidence_migration,evidence_fingerprint
    base,sources=sample()
    old=base.structure.story_plan.evidence[0]
    sources={name:text+' outside excerpt changed' for name,text in sources.items()}
    selection=old.model_dump(exclude={'source_revision','excerpt'})
    req=EvidenceMigrationRequest(evidence_id=old.id,old_evidence_fingerprint=evidence_fingerprint(old),
        new_selection=selection,expected_source_fingerprint=sources_fingerprint(sources))
    with pytest.raises(ValueError):preview_evidence_migration(base,req,sources,KEY)


@pytest.mark.parametrize('damage',['old_hash','new_id','excerpt','source_hash','extra_approval'])
def test_migration_requests_cannot_forge_old_identity_or_new_excerpt(damage):
    from slidecaptain.pipeline.document_changes import preview_evidence_migration,evidence_fingerprint
    base,sources=sample();old=base.structure.story_plan.evidence[0]
    selection=old.model_dump(exclude={'source_revision','excerpt'})
    payload=dict(evidence_id=old.id,old_evidence_fingerprint=evidence_fingerprint(old),
                 new_selection=selection,expected_source_fingerprint=sources_fingerprint(sources))
    if damage=='old_hash':payload['old_evidence_fingerprint']='0'*64
    elif damage=='new_id':selection['id']='different'
    elif damage=='excerpt':selection['locator']={'line_start':100,'line_end':100}
    elif damage=='source_hash':payload['expected_source_fingerprint']='0'*64
    elif damage=='extra_approval':payload['approved']=True
    with pytest.raises(ValueError):preview_evidence_migration(base,EvidenceMigrationRequest.model_validate(payload),sources,KEY)


def test_existing_diagram_generation_requires_explicit_replace_and_same_claim_scope():
    from slidecaptain.pipeline.diagram_generation import GenerateDiagramRequest,diagram_prompt
    base,sources=sample()
    chapter=next(c for c in base.structure.chapters if c.template=='diagram')
    assignment=next(c for c in base.structure.story_plan.chapters if c.chapter_id==chapter.id)
    payload=dict(chapter_id=chapter.id,topic=chapter.topic,role=assignment.role,claim_ids=assignment.claim_ids)
    with pytest.raises(ValueError):diagram_prompt(base,GenerateDiagramRequest(**payload),sources)
    prompt,_=diagram_prompt(base,GenerateDiagramRequest(mode='replace',**payload),sources)
    assert 'existing_diagram' in prompt
    with pytest.raises(ValueError):diagram_prompt(base,GenerateDiagramRequest(mode='replace',**{**payload,'role':'risk'}),sources)


def test_legacy_deck_has_no_empty_document_review_and_large_candidate_rejects():
    from slidecaptain.pipeline.document_changes import preview_document_change
    base,sources=sample()
    assert 'document_review' not in base.model_dump(mode='json')
    candidate=base.model_copy(deep=True)
    candidate.meta.presenter='x'*(1024*1024)
    with pytest.raises(ValueError):preview_document_change(base,candidate,sources,KEY)


def test_manual_chapter_add_delete_and_body_replace_reports_original_loss():
    from slidecaptain.pipeline.document_changes import preview_document_change
    base,sources=sample()
    payload=base.model_dump(mode='json')
    payload['structure']['chapters']=[c for c in payload['structure']['chapters'] if c['id']!='cover']
    payload['slides']=[s for s in payload['slides'] if s['chapter_id']!='cover']
    payload['structure']['chapters'].append({'id':'new-cover','topic':'새 표지','template':'cover'})
    payload['slides'].append({'chapter_id':'new-cover','slots':{'template':'cover','title':'새 표지'}})
    preview=preview_document_change(base,Deck.model_validate(payload),sources,KEY)
    assert any(i.path=='chapters/cover' and i.kind=='deleted' and i.before['topic']=='합성 보고' for i in preview.losses)
    assert any(i.path=='chapters/new-cover' and i.kind=='added' for i in preview.losses)
    assert any(i.kind=='reordered' for i in preview.losses)


def test_migration_rejects_numeric_substring_even_when_it_exists_in_excerpt():
    from slidecaptain.pipeline.document_changes import preview_evidence_migration,evidence_fingerprint
    fixture=json.loads((Path(__file__).parent/'fixtures/q2d-numeric-review.json').read_text())
    base=Deck.model_validate(fixture['deck']);sources=fixture['sources'];old=base.structure.story_plan.evidence[0]
    selection=old.model_dump(exclude={'source_revision','excerpt'});selection['value']='200'
    assert '200' in old.excerpt
    req=EvidenceMigrationRequest(evidence_id=old.id,old_evidence_fingerprint=evidence_fingerprint(old),new_selection=selection,
                                 expected_source_fingerprint=sources_fingerprint(sources))
    with pytest.raises(ValueError):preview_evidence_migration(base,req,sources,KEY)


def test_ordinary_candidate_cannot_extend_protected_comparison_graph():
    from slidecaptain.pipeline.document_changes import preview_document_change
    from slidecaptain.models.expression import ChartSpec
    fixture=json.loads((Path(__file__).parent/'fixtures/q2d-numeric-review.json').read_text())
    payload=fixture['deck'];payload['structure']['chapters'][0]['template']='table'
    payload['slides'][0]['slots']={'template':'table','columns':['항목','값'],'rows':[['A','1200원'],['B','1000원']]}
    payload['slides'][0]['chart']=ChartSpec(rule_version='comparison-chart-v1',comparison_id='cmp1',kind='bar').model_dump()
    base=Deck.model_validate(payload);sources=fixture['sources']
    base.structure.story_plan.input_fingerprint=story_fingerprint(base.structure.story_plan,base.meta,base.structure.chapters,sources)
    candidate=base.model_dump(mode='json')
    extra={**candidate['structure']['story_plan']['comparisons'][0],'id':'new-comparison'}
    candidate['structure']['story_plan']['comparisons'].append(extra)
    with pytest.raises(ValueError):preview_document_change(base,Deck.model_validate(candidate),sources,KEY)


def test_ordinary_replacement_rejects_numeric_substring_in_unprotected_evidence():
    from slidecaptain.pipeline.document_changes import preview_document_change
    fixture=json.loads((Path(__file__).parent/'fixtures/q2d-numeric-review.json').read_text())
    base=Deck.model_validate(fixture['deck']);sources=fixture['sources']
    candidate=base.model_copy(deep=True)
    candidate.structure.story_plan.evidence[0].value='200'
    assert '200' in candidate.structure.story_plan.evidence[0].excerpt
    with pytest.raises(ValueError):preview_document_change(base,candidate,sources,KEY)


def test_protected_representation_cannot_be_removed_to_unprotect_graph_in_next_transaction():
    from slidecaptain.pipeline.document_changes import preview_document_change
    base,sources=sample()
    payload=base.model_dump(mode='json')
    chapter=next(ch for ch in payload['structure']['chapters'] if ch['template']=='diagram')
    chapter['template']='callout'
    slide=next(sl for sl in payload['slides'] if sl['chapter_id']==chapter['id'])
    slide['slots']={'template':'callout','text':'보호 도식 제거'}
    with pytest.raises(ValueError):preview_document_change(base,Deck.model_validate(payload),sources,KEY)


def test_node_only_protected_evidence_reference_cannot_be_removed_from_replacement():
    from slidecaptain.pipeline.document_changes import preview_document_change
    from slidecaptain.pipeline.diagram_generation import GenerateDiagramRequest,diagram_prompt
    base,sources=sample()
    payload=base.model_dump(mode='json')
    plan=payload['structure']['story_plan']
    plan['evidence'].append({**plan['evidence'][0],'id':'node-only'})
    slide=next(s for s in payload['slides'] if s['slots']['template']=='diagram')
    slide['slots']['diagram']['nodes'][0]['evidence_ids'].append('node-only')
    base=Deck.model_validate(payload)
    base.structure.story_plan.input_fingerprint=story_fingerprint(base.structure.story_plan,base.meta,base.structure.chapters,sources)
    assignment=base.structure.story_plan.chapters[0]
    chapter=next(ch for ch in base.structure.chapters if ch.template=='diagram')
    _,evidence=diagram_prompt(base,GenerateDiagramRequest(mode='replace',chapter_id=chapter.id,topic=chapter.topic,
                               role=assignment.role,claim_ids=assignment.claim_ids),sources)
    assert 'node-only' in {e.id for e in evidence}
    candidate=base.model_copy(deep=True)
    candidate.slides[0].slots.diagram.nodes[0].evidence_ids.remove('node-only')
    with pytest.raises(ValueError):preview_document_change(base,candidate,sources,KEY)
