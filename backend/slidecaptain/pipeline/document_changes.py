"""No-I/O manual candidate confirmation; explicit source transfer is never semantic approval."""

import hashlib
import hmac
import json

from slidecaptain.models.change_review import DocumentChangeReview
from slidecaptain.models.deck import Deck
from slidecaptain.models.document_changes import DocumentChangePreview, EvidenceMigrationRequest, LossItem
from slidecaptain.models.story import Evidence
from slidecaptain.models.derivation import _parse_operand
from slidecaptain.pipeline.rewrite import protected_story, sources_fingerprint
from slidecaptain.pipeline.story import _require_current_evidence, require_current_story, story_fingerprint

_MAX_BYTES=1024*1024


def _canonical(value):
    raw=json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')
    if len(raw)>_MAX_BYTES:
        raise ValueError('문서 변경 후보/확인 목록은 1MiB 이내여야 합니다.')
    return raw


def _hash(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def evidence_fingerprint(evidence):
    return _hash(Evidence.model_validate(evidence).model_dump(mode='json'))


def _deck(deck):
    # Deck models do not revalidate mutated nested instances by themselves.
    return Deck.model_validate(deck.model_dump(mode='json') if isinstance(deck,Deck) else deck)


def _inventory(base,candidate):
    before=base.model_dump(mode='json');after=candidate.model_dump(mode='json')
    before.pop('document_review',None);after.pop('document_review',None)
    losses=[]
    def add(path,old,new,kind=None):
        if old==new:return
        kind=kind or ('added' if old is None else 'deleted' if new is None else 'replaced')
        item={'path':path,'kind':kind,'before':old,'after':new}
        losses.append(LossItem(id=_hash(item),**item))
    for key in ['schema_version','meta']:
        add(key,before[key],after[key])
    for container,idkey in [('chapters','id'),('slides','chapter_id')]:
        oldlist=before['structure']['chapters'] if container=='chapters' else before['slides']
        newlist=after['structure']['chapters'] if container=='chapters' else after['slides']
        old={i[idkey]:i for i in oldlist};new={i[idkey]:i for i in newlist}
        for ident in sorted(set(old)|set(new)):
            add(f'{container}/{ident}',old.get(ident),new.get(ident))
        add(f'{container}/order',[i[idkey] for i in oldlist],[i[idkey] for i in newlist],'reordered')
    # Server-computed derived/fingerprint fields are not independently acknowledged changes.
    def plan_payload(payload):
        plan=payload['structure'].get('story_plan')
        if plan is None:return None
        return {k:v for k,v in plan.items() if k not in ['input_fingerprint','comparison_results','derived_values']}
    add('story_plan',plan_payload(before),plan_payload(after))
    if not losses:raise ValueError('변경된 문서 내용이 없습니다.')
    if len(losses)>1000:raise ValueError('문서 변경 확인 항목은 최대 1000개입니다.')
    _canonical([item.model_dump(mode='json') for item in losses])
    return losses


def _validate_story(candidate,sources):
    plan=candidate.structure.story_plan
    if plan is None:return
    assignments={c.chapter_id:c for c in plan.chapters}
    chapters={c.id:c for c in candidate.structure.chapters}
    required={c.id for c in candidate.structure.chapters if c.template not in ('cover','divider')}
    if not required <= set(assignments) or not set(assignments)<=set(chapters):
        raise ValueError('모든 본문 장은 보고 계획에 연결하고 삭제한 장의 연결은 제거해야 합니다.')
    for ident,assignment in assignments.items():
        template=chapters[ident].template
        if (template in ('cover','divider') and assignment.role!=template) or (template not in ('cover','divider') and assignment.role in ('cover','divider')):
            raise ValueError('보고 계획의 장 역할과 실제 템플릿이 다릅니다.')
    plan.chapters=[assignments[c.id] for c in candidate.structure.chapters if c.id in assignments]
    if plan.brief.audience!=candidate.meta.audience or plan.brief.report_type!=candidate.meta.report_type:
        raise ValueError('보고 계획의 대상과 유형이 문서 정보와 다릅니다.')
    _require_current_evidence(plan,sources)
    for evidence in plan.evidence:
        if evidence.value is not None and evidence.value not in evidence.excerpt:
            raise ValueError('근거 값이 현재 발췌에 없습니다.')
        if evidence.value is not None and any(char.isdigit() for char in evidence.value):
            if _parse_operand(evidence,[]) is None:
                raise ValueError('문서 후보의 수치 근거는 원문의 명확한 전체 토큰이어야 합니다.')
    # Source refs are bindings, not client declarations of new evidence.
    by_claim={c.id:c for c in plan.claims};by_evidence={e.id:e for e in plan.evidence}
    by_chapter={c.chapter_id:c for c in plan.chapters}
    for chapter in candidate.structure.chapters:
        expected=list(dict.fromkeys(by_evidence[eid].source_id for cid in (by_chapter[chapter.id].claim_ids if chapter.id in by_chapter else [])
                                    for eid in by_claim[cid].evidence_ids))
        chapter.source_refs=expected
    plan.input_fingerprint=story_fingerprint(plan,candidate.meta,candidate.structure.chapters,sources)


def _protect(base,candidate,sources):
    if base.structure.story_plan is None:
        return
    protected=protected_story(base,sources)
    if candidate.structure.story_plan is None:
        raise ValueError('기존 보고 계획을 일반 문서 교체로 삭제할 수 없습니다.')
    plan=candidate.structure.story_plan
    for key,items in protected.items():
        idkey='chapter_id' if key=='chapters' else 'id'
        actual={item[idkey]:item for item in [v.model_dump(mode='json') for v in getattr(plan,key)]}
        for item in items:
            if actual.get(item[idkey])!=item:
                raise ValueError('보호 장 연결/주장/근거/비교/산식은 명시적 근거 이동 외에는 변경할 수 없습니다.')
    protected_claims={item['id'] for item in protected['claims']}
    protected_comparisons={item['id'] for item in protected['comparisons']}
    if {item.id for item in plan.comparisons if item.claim_id in protected_claims}!=protected_comparisons:
        raise ValueError('보호 주장에 비교를 추가하거나 제거할 수 없습니다.')
    if {item.id for item in plan.derivations if item.comparison_id in protected_comparisons}!={item['id'] for item in protected['derivations']}:
        raise ValueError('보호 비교에 산식을 추가하거나 제거할 수 없습니다.')
    current_chapters={c.id:c for c in candidate.structure.chapters}
    protected_chapters={item['chapter_id'] for item in protected['chapters']}
    protected_evidence={item['id'] for item in protected['evidence']}
    old_slides={slide.chapter_id:slide for slide in base.slides}
    new_slides={slide.chapter_id:slide for slide in candidate.slides}
    for ident in protected_chapters:
        old=old_slides.get(ident);new=new_slides.get(ident)
        if old is not None and old.slots.template=='diagram' and (new is None or new.slots.template!='diagram'):
            raise ValueError('보호 도식의 종류를 제거하여 보호 장부를 해제할 수 없습니다.')
        if old is not None and old.chart is not None and (new is None or new.chart is None or new.chart.comparison_id!=old.chart.comparison_id):
            raise ValueError('보호 차트 또는 등록 비교를 제거하여 보호 장부를 해제할 수 없습니다.')
    for slide in candidate.slides:
        if slide.chapter_id in protected_chapters and slide.slots.template=='diagram':
            refs={eid for item in [*slide.slots.diagram.nodes,*slide.slots.diagram.edges] for eid in item.evidence_ids}
            if not refs<=protected_evidence:
                raise ValueError('기존 도식 교체는 기존 보호 주장/근거 범위에서만 수행할 수 있습니다.')
            old=old_slides.get(slide.chapter_id)
            if old is not None and old.slots.template=='diagram':
                old_refs={eid for item in [*old.slots.diagram.nodes,*old.slots.diagram.edges] for eid in item.evidence_ids}
                if not old_refs<=refs:
                    raise ValueError('도식만 참조하는 보호 근거가 다음 변경에서 해제되지 않도록 기존 근거 참조를 보존해야 합니다.')
    for assignment in protected['chapters']:
        if assignment['chapter_id'] not in current_chapters:
            raise ValueError('보호 도식·차트 장을 일반 문서 교체로 삭제할 수 없습니다.')


def _preview(base,candidate,sources,key,reason):
    if not isinstance(key,bytes) or len(key)<32:
        raise ValueError('서버 문서 변경 확인 키가 설정되지 않았습니다.')
    losses=_inventory(base,candidate)
    base_hash=_hash(base.model_dump(mode='json'))
    review=DocumentChangeReview(reason=reason,base_fingerprint=base_hash,changed_paths=[i.path for i in losses])
    if candidate.document_review not in (None,base.document_review,review):
        raise ValueError('문서 변경 검수 안내는 서버가 기록합니다.')
    # Allow legacy imported candidate without the marker; it can never suppress the new marker.
    candidate.document_review=review
    candidate=_deck(candidate)
    payload={'rule_version':'document-change-v1','reason':reason,'base_fingerprint':base_hash,
             'sources_fingerprint':sources_fingerprint(sources),
             'candidate_fingerprint':_hash(candidate.model_dump(mode='json')),
             'losses':[i.model_dump(mode='json') for i in losses]}
    token=hmac.new(key,_canonical(payload),hashlib.sha256).hexdigest()
    return DocumentChangePreview(**{k:v for k,v in payload.items() if k!='losses'},candidate=candidate,
                                 losses=losses,confirmation_token=token)


def preview_document_change(base,candidate,sources,confirmation_key):
    base=_deck(base);candidate=_deck(candidate)
    require_current_story(base,sources)
    if base.structure.story_plan:
        _require_current_evidence(base.structure.story_plan,sources)
    _protect(base,candidate,sources)
    _validate_story(candidate,sources)
    return _preview(base,candidate,sources,confirmation_key,'document_replacement')


def _confirm(preview,token,ids):
    if not isinstance(token,str) or not hmac.compare_digest(token,preview.confirmation_token):
        raise ValueError('확인한 문서/자료/저장본이 바뀌었습니다. 후보를 다시 미리 보세요.')
    expected={i.id for i in preview.losses}
    if len(ids)!=len(set(ids)) or set(ids)!=expected:
        raise ValueError('모든 변경 항목을 정확히 한 번씩 확인해야 합니다.')
    return preview.candidate


def apply_document_change(base,candidate,sources,confirmation_key,confirmation_token,acknowledged_loss_ids):
    return _confirm(preview_document_change(base,candidate,sources,confirmation_key),confirmation_token,acknowledged_loss_ids)


def _materialize(selection,sources):
    source=sources.get(selection.source_id)
    if source is None:raise ValueError('이동할 원자료가 없습니다.')
    lines=source.splitlines()
    if selection.locator.line_end>len(lines):raise ValueError('이동할 근거의 행 범위가 원자료를 벗어납니다.')
    excerpt='\n'.join(lines[selection.locator.line_start-1:selection.locator.line_end])
    if not excerpt.strip():raise ValueError('이동할 근거의 발췌가 비어 있습니다.')
    evidence=Evidence(**selection.model_dump(),source_revision=hashlib.sha256(source.encode()).hexdigest(),excerpt=excerpt)
    if evidence.value is not None:
        if evidence.value not in excerpt:raise ValueError('이동할 값이 새 원문 발췌에 없습니다.')
        if any(char.isdigit() for char in evidence.value):
            reasons=[]
            if _parse_operand(evidence,reasons) is None:
                raise ValueError('이동할 수치 값은 새 원문의 명확한 전체 토큰이어야 합니다.')
    return evidence


def preview_evidence_migration(base,request,sources,confirmation_key):
    base=_deck(base);request=EvidenceMigrationRequest.model_validate(request)
    if request.expected_source_fingerprint!=sources_fingerprint(sources):
        raise ValueError('이동할 원자료가 미리보기 기준과 다릅니다.')
    plan=base.structure.story_plan
    if plan is None:raise ValueError('근거를 이동할 보고 계획이 없습니다.')
    old=next((e for e in plan.evidence if e.id==request.evidence_id),None)
    if old is None or evidence_fingerprint(old)!=request.old_evidence_fingerprint:
        raise ValueError('이동할 기존 근거가 저장본과 다릅니다.')
    # A source-wide edit invalidates other evidence in the same source, even identical excerpts.
    _require_current_evidence(plan.model_copy(update={'evidence':[e for e in plan.evidence if e.id!=old.id]}),sources)
    replacement=_materialize(request.new_selection,sources)
    payload=base.model_dump(mode='json')
    payload['structure']['story_plan']['evidence']=[replacement.model_dump(mode='json') if e.id==old.id else e.model_dump(mode='json') for e in plan.evidence]
    # StoryPlan recalculates comparisons/derived values; graph identity and references stay unchanged.
    candidate=_deck(payload)
    _validate_story(candidate,sources)
    return _preview(base,candidate,sources,confirmation_key,'evidence_migration')


def apply_evidence_migration(base,request,sources,confirmation_key,confirmation_token,acknowledged_loss_ids):
    return _confirm(preview_evidence_migration(base,request,sources,confirmation_key),confirmation_token,acknowledged_loss_ids)
