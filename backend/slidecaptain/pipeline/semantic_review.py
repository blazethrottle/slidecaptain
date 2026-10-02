"""Read-only textual signals; never replace source, claims or signed reviews."""
import hashlib
import json
import re
from dataclasses import dataclass
from decimal import Decimal

from slidecaptain.models.deck import Deck
from slidecaptain.models.semantic_review import SemanticSuspect, SemanticSuspectReport, SemanticRelatedText
from slidecaptain.pipeline.story import StaleStoryPlan, require_current_story, _require_current_evidence

_MAX_FIELDS = 5000
_MAX_CHARS = 200000
_MAX_FINDINGS = 1000
_COMPARISON = re.compile(r'대비|보다|격차|차이|증감률|증가율|감소율')
_RATE = re.compile(r'증감률|증가율|감소율')
# An ISO date or period is not an arithmetic expression.
_DATE = re.compile(r'\b(?:\d{4}[-/]\d{1,2}(?:[-/]\d{1,2})?|\d{4}\.\d{1,2}\.\d{1,2})\b')
_ARITHMETIC = re.compile(r'\d[\d,.]*\s*(?:[+×÷*/=]|-(?!\d{2}-))\s*[+-]?\d')
_UP = re.compile(r'증가|상승|성장|확대|개선|상회')
_DOWN = re.compile(r'감소|하락|축소|악화|하회')


@dataclass
class _Text:
    chapter_id: str
    path: str
    text: str
    claim_ids: set[str]
    template: str
    slide_field: bool


def _strings(value, path):
    if isinstance(value,str) and value.strip():
        yield path,value
    elif isinstance(value,dict):
        for key,child in value.items():yield from _strings(child,f'{path}/{key}')
    elif isinstance(value,list):
        for i,child in enumerate(value):yield from _strings(child,f'{path}/{i}')


def _fields(deck):
    plan=deck.structure.story_plan
    assignments={a.chapter_id:set(a.claim_ids) for a in plan.chapters}
    chapters={c.id:c for c in deck.structure.chapters}
    for i,claim in enumerate(plan.claims):
        chapter=next((a.chapter_id for a in plan.chapters if claim.id in a.claim_ids),'')
        yield _Text(chapter,f'/structure/story_plan/claims/{i}/statement',claim.statement,{claim.id},'claim',False)
    for i,slide in enumerate(deck.slides):
        chapter=chapters[slide.chapter_id]
        if chapter.template in ('cover','divider'):continue
        ids=assignments.get(chapter.id,set())
        visible={'topic':chapter.topic,'eyebrow':slide.eyebrow,'subtitle':slide.subtitle}
        if slide.slots.template=='diagram':
            d=slide.slots.diagram
            visible['slots']={'footnote':slide.slots.footnote,
              'nodes':[{'content':n.content,'caveats':n.caveats} for n in d.nodes],
              'edges':[{'label':e.label} for e in d.edges]}
        else:visible['slots']=slide.slots.model_dump(exclude={'template','tone'})
        for path,text in _strings(visible,f'/slides/{i}'):
            yield _Text(chapter.id,path,text,ids,chapter.template,True)


def _direction(text):
    up,down=bool(_UP.search(text)),bool(_DOWN.search(text))
    return 1 if up and not down else -1 if down and not up else 0


def assess_semantic_suspects(deck: Deck, sources: dict[str,str]) -> SemanticSuspectReport:
    raw=deck.model_dump(mode='json')
    fingerprint=hashlib.sha256(json.dumps({'rule':'semantic-suspect-v1','deck':raw,
      'sources':{name:hashlib.sha256(text.encode()).hexdigest() for name,text in sources.items()}},
      ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
    def not_run(reason):return SemanticSuspectReport(input_fingerprint=fingerprint,status='not_run',reason=reason,evaluated_fields=0,findings=[])
    if deck.structure.story_plan is None:return not_run('missing_plan')
    try:
        # Recompute cached comparison/calculation metadata without editing caller.
        deck=Deck.model_validate(raw)
    except ValueError:return not_run('invalid_plan')
    try:
        require_current_story(deck,sources);_require_current_evidence(deck.structure.story_plan,sources)
    except StaleStoryPlan:return not_run('stale_plan')
    fields=list(_fields(deck))
    if not fields:return not_run('no_reviewable_fields')
    if len(fields)>_MAX_FIELDS or sum(len(f.text) for f in fields)>_MAX_CHARS:return not_run('review_limit')
    plan=deck.structure.story_plan
    comparisons={c.id:c for c in plan.comparisons}
    evidence={e.id:e for e in plan.evidence}
    values={v.derivation_id:v for v in plan.derived_values if v.status=='computed'}
    findings=[]
    def add(field,code,signal,message,cmps,ders,related=None):
        findings.append(SemanticSuspect(code=code,chapter_id=field.chapter_id,path=field.path,text=field.text,signal=signal,message=message,
          claim_ids=sorted(field.claim_ids),comparison_ids=[c.id for c in cmps],derivation_ids=[d.id for d in ders],related_texts=related or []))
    for field in fields:
        eligible=field.claim_ids | (set(plan.answer_claim_ids) if field.slide_field else set())
        cmps=[c for c in plan.comparisons if c.claim_id in eligible]
        ders=[d for d in plan.derivations if d.comparison_id in {c.id for c in cmps}]
        cleaned=_DATE.sub('',field.text)
        cleaned=re.sub(r'(?:자료|원문|문서|파일|화면)(?:를|을)\s*보다', '', cleaned)
        clauses=re.split(r'(?<!\d)\.(?!\d)|[。!?;\n]',cleaned)
        numeric_clauses=[part for part in clauses if re.search(r'\d',part)]
        marker=next((match for part in numeric_clauses if (match:=_COMPARISON.search(part))),None)
        if marker and not cmps:
            add(field,'unregistered_comparison',marker.group(),'수치 비교 표지가 있으나 이 문구 범위에 등록된 비교가 없습니다. 원문과 비교 조건을 확인해 주세요.',cmps,ders)
        formula=_ARITHMETIC.search(cleaned) or next((match for part in numeric_clauses if (match:=_RATE.search(part))),None)
        if formula and not ders:
            add(field,'unregistered_formula',formula.group(),'산식 또는 증감률 표지가 있으나 연결된 계산이 없습니다. 계산할 의미인지 직접 확인해 주세요.',cmps,ders)
        direction=_direction(field.text)
        if direction:
            for derivation in ders:
                c=comparisons[derivation.comparison_id];v=values.get(derivation.id)
                e=evidence[c.left_evidence_id]
                definition=e.metric_basis.definition if e.metric_basis else None
                if v is None or not definition or definition not in field.text:continue
                expected=1 if Decimal(v.value)>0 else -1 if Decimal(v.value)<0 else 0
                if expected and direction!=expected:
                    add(field,'calculated_direction_mismatch',definition,'계산 부호와 문구 방향 표지가 다릅니다. 지표·주체·기간·부정·조건 문맥을 확인해 주세요.',[c],[derivation])
        if len(findings)>_MAX_FINDINGS:return not_run('review_limit')
    # Summary candidates require an actually shared assigned claim and named metric.
    summaries=[f for f in fields if f.slide_field and f.template=='summary' and _direction(f.text)]
    body=[f for f in fields if f.slide_field and f.template not in ('summary','cover','divider') and _direction(f.text)]
    for summary in summaries:
        for other in body:
            shared=summary.claim_ids & other.claim_ids
            if not shared or _direction(summary.text)==_direction(other.text):continue
            cmps=[c for c in plan.comparisons if c.claim_id in shared]
            for c in cmps:
                e=evidence[c.left_evidence_id];definition=e.metric_basis.definition if e.metric_basis else None
                if not definition or definition not in summary.text or definition not in other.text:continue
                add(summary,'summary_direction_conflict',definition,'같은 주장·지표에 연결된 요약과 본문의 방향 표지가 다릅니다. 조건과 원문을 대조해 주세요.',[c],[],
                  [SemanticRelatedText(chapter_id=other.chapter_id,path=other.path,text=other.text)])
                if len(findings)>_MAX_FINDINGS:return not_run('review_limit')
    return SemanticSuspectReport(input_fingerprint=fingerprint,status='needs_review' if findings else 'no_signals_detected',evaluated_fields=len(fields),findings=findings)
