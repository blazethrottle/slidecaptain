"""Deterministic sourced charts and measured exact-text emphasis."""

from decimal import Decimal, localcontext
from fractions import Fraction
import re

from slidecaptain.metrics.font_metrics import HANGUL_START, HANGUL_END
from slidecaptain.metrics.line_breaker import break_paragraph
from slidecaptain.models.comparison import assess_comparison, unit_scale_factor
from slidecaptain.models.derivation import _parse_operand
from slidecaptain.models.expression import ChartPlan, ChartPoint, TextRun, span_text
from slidecaptain.models.render import CapacityWarning, Frame, Para


def _supported_text(text,preset,metrics):
    if preset.fonts.korean!='Noto Sans KR' or preset.fonts.latin!='Noto Sans KR':
        raise ValueError('차트와 부분 강조는 번들 Noto Sans KR 폭이 확인된 폰트만 지원합니다.')
    face=metrics.face(False)
    for char in text:
        cp=ord(char)
        if char=='\n':
            continue
        if cp not in face.widths and not (HANGUL_START<=cp<=HANGUL_END and face.hangul_uniform_width is not None):
            raise ValueError('차트나 강조 문장에 글자 폭이 확인되지 않은 문자가 있습니다.')


def build_comparison_chart(deck,slide,frame,preset,metrics,sources):
    from slidecaptain.pipeline.story import require_current_story,_require_current_evidence
    if sources is None:
        raise ValueError('비교 차트는 프로젝트의 실제 원문 자료와 함께 확인해야 합니다.')
    require_current_story(deck,sources)
    story=deck.structure.story_plan
    _require_current_evidence(story,sources)
    comparison=next(item for item in story.comparisons if item.id==slide.chart.comparison_id)
    evidence={item.id:item for item in story.evidence}
    left,right=evidence[comparison.left_evidence_id],evidence[comparison.right_evidence_id]
    assessment=assess_comparison(comparison,left.metric_basis,right.metric_basis,left.value,right.value)
    if assessment.status!='compatible':
        raise ValueError('비교 조건이 일치하지 않거나 정보가 부족하여 차트를 그릴 수 없습니다.')
    reasons=[]
    operands=[_parse_operand(item,reasons) for item in (left,right)]
    if reasons or any(value is None for value in operands):
        raise ValueError('차트의 원문 숫자와 전체 단위를 확정하지 못했습니다.')
    basis=left.metric_basis
    unit=comparison.unit_normalization.target_unit if comparison.unit_normalization else basis.unit
    values=[]
    for item,value in zip((left,right),operands):
        if comparison.unit_normalization:
            factor=unit_scale_factor(item.metric_basis.unit,unit)
            if factor is None:
                raise ValueError('등록된 단위 배율을 확인하지 못했습니다.')
            exact=Fraction(value)*factor
            with localcontext() as context:
                context.prec=80
                value=Decimal(exact.numerator)/Decimal(exact.denominator)
        if value<0 or value>Decimal('1000000000000') or Decimal(str(float(value)))!=value:
            raise ValueError('차트는 0~1조 범위에서 native 숫자로 정확히 표현할 수 있는 값만 지원합니다.')
        values.append(value)
    labels=[]
    for item in (left,right):
        metric=item.metric_basis
        labels.append(metric.entity if comparison.axis=='entity' else f'{metric.period.start.isoformat()}~{metric.period.end.isoformat()}')
    denominator=basis.denominator.definition if basis.denominator.kind=='population' else '해당 없음'
    periods=' / '.join(f'{item.metric_basis.period.start.isoformat()}~{item.metric_basis.period.end.isoformat()}' for item in (left,right))
    conditions=f'{basis.definition}, 단위 {unit}, 기간 {periods}, 분모 {denominator}'
    if comparison.unit_normalization:
        conditions+=f', 원문 단위 {left.metric_basis.unit}/{right.metric_basis.unit}에서 등록 배율로 환산'
    for text in [*labels,conditions]:
        _supported_text(text,preset,metrics)
    font=preset.font_roles.body_pt
    condition_lines=break_paragraph(conditions,frame.w,font,metrics.face(False),preset.spacing.safety_ratio)
    if len(condition_lines)>3:
        raise ValueError('차트의 단위/기간/분모 조건을 세 줄 안에 보존하지 못했습니다. 내용 영역을 확인해 주세요.')
    caption_h=len(condition_lines)*font*preset.spacing.line_spacing+preset.spacing.subtitle_gap
    height=frame.h-caption_h
    if height<font*8 or frame.w<font*20:
        raise ValueError('차트와 필수 조건을 배치할 공간이 부족합니다.')
    text_values=[format(v,'f').rstrip('0').rstrip('.') if '.' in format(v,'f') else format(v,'f') for v in values]
    label_width=max(metrics.face(False).width_pt(label,font) for label in labels)
    value_width=max(metrics.face(False).width_pt(text,font) for text in text_values)
    if slide.chart.kind=='bar':
        plot_x=label_width+font*1.5
        plot_y=font
        plot_w=frame.w-plot_x-value_width-font*2
        plot_h=height-font*3
    else:
        plot_x=value_width+font*1.5
        plot_y=font*2
        plot_w=frame.w-plot_x-font
        plot_h=height-font*4
        if label_width>plot_w/2-font:
            raise ValueError('차트 범주 라벨을 한 줄로 보존할 폭이 부족합니다.')
    if plot_w<font*4 or plot_h<font*4:
        raise ValueError('차트 축과 값을 배치할 공간이 부족합니다.')
    maximum=max(values)*Decimal('1.1') if max(values)>0 else Decimal(1)
    points=[]
    for index,(item,value,label) in enumerate(zip((left,right),values,labels)):
        ratio=float(value/maximum)
        if slide.chart.kind=='bar':
            band=plot_h/2
            x,y,w,h=plot_x,plot_y+band*(index+.25),plot_w*ratio,band*.5
        else:
            band=plot_w/2
            x,y,w,h=plot_x+band*(index+.25),plot_y+plot_h*(1-ratio),band*.5,plot_h*ratio
        points.append(ChartPoint(evidence_id=item.id,label=label,value=text_values[index],
                                 color=preset.colors.accent1 if index==0 else preset.colors.accent2,x=x,y=y,w=w,h=h))
    chart=ChartPlan(kind=slide.chart.kind,comparison_id=comparison.id,claim_id=comparison.claim_id,
                    definition=basis.definition,unit=unit,conditions=conditions,axis_minimum='0',axis_maximum=format(maximum,'f'),
                    plot_x=plot_x,plot_y=plot_y,plot_w=plot_w,plot_h=plot_h,font_pt=font,
                    text_color=preset.colors.text,points=points)
    chart_frame=Frame(name=f'{slide.chapter_id}:chart',x=frame.x,y=frame.y,w=frame.w,h=height,chart=chart)
    caption=Frame(name=f'{slide.chapter_id}:chart_conditions',x=frame.x,y=frame.y+height,w=frame.w,h=caption_h,
                  paras=[Para(text=conditions,font_pt=font,color=preset.colors.text,lines=condition_lines)])
    return chart_frame,caption


def _merge(chars):
    result=[]
    for char,bold,color in chars:
        if result and result[-1].bold==bold and result[-1].color==color:
            result[-1].text+=char
        else:
            result.append(TextRun(text=char,bold=bold,color=color))
    return result


def _styled_lines(runs,width,font,metrics,safety):
    chars=[(char,run.bold,run.color) for run in runs for char in run.text]
    text=''.join(item[0] for item in chars)
    budget=width*safety
    current=[]
    lines=[]
    def measured(items):
        return sum(metrics.face(bold).width_pt(char,font) for char,bold,_ in items)
    for match in re.finditer(r'[^ \n]+| +|\n',text):
        part=chars[match.start():match.end()]
        if match.group()=='\n':
            lines.append(_merge(current));current=[];continue
        if measured(part)>budget:
            if current:
                lines.append(_merge(current));current=[]
            for char in part:
                if current and measured([*current,char])>budget:
                    lines.append(_merge(current));current=[]
                current.append(char)
        elif current and measured([*current,*part])>budget:
            lines.append(_merge(current));current=part
        else:
            current.extend(part)
    lines.append(_merge(current))
    return lines


def apply_text_spans(slide,plan,preset,metrics):
    grouped={}
    for span in slide.text_spans:
        grouped.setdefault((span.slot,span.index or 0),[]).append(span)
    changed=set()
    for (slot,index),spans in grouped.items():
        frame=next((item for item in plan.frames if item.name==f'{slide.chapter_id}:{slot}'),None)
        if frame is None or index>=len(frame.paras):
            raise ValueError('선택한 텍스트의 강조 렌더를 지원하지 않습니다.')
        para=frame.paras[index]
        if para.text!=span_text(slide,spans[0]):
            raise ValueError('강조 대상 원문과 렌더 문장이 일치하지 않습니다.')
        _supported_text(para.text,preset,metrics)
        boundaries={0,len(para.text),*(s.start for s in spans),*(s.end for s in spans)}
        runs=[]
        offsets=sorted(boundaries)
        for start,end in zip(offsets,offsets[1:]):
            span=next((s for s in spans if s.start<=start and end<=s.end),None)
            runs.append(TextRun(text=para.text[start:end],bold=para.bold or bool(span and span.role=='bold'),
                                color=preset.colors.accent1 if span and span.role=='accent' else para.color))
        padding=preset.spacing.box_padding if frame.fill or frame.border else 0
        width=frame.w-2*padding-(preset.spacing.bullet_indent*(para.level+1) if para.bullet else 0)
        para.runs=runs
        para.line_runs=_styled_lines(runs,width,para.font_pt,metrics,preset.spacing.safety_ratio)
        para.lines=[''.join(run.text for run in line) for line in para.line_runs]
        changed.add(frame.name)
    for frame in plan.frames:
        if frame.name not in changed:
            continue
        padding=preset.spacing.box_padding if frame.fill or frame.border else 0
        needed=sum(len(p.lines)*p.font_pt*preset.spacing.line_spacing+
                   (preset.spacing.bullet_gap if p.bullet and i>0 else 0) for i,p in enumerate(frame.paras))
        available=frame.h-2*padding
        if needed>available:
            plan.warnings.append(CapacityWarning(chapter_id=slide.chapter_id,slot=frame.name.split(':',1)[1]+'_span',
                                                 message='부분 강조의 실제 bold 폭을 반영하면 기존 영역을 초과합니다.',
                                                 needed_pt=needed,available_pt=available))
    return plan
