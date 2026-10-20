"""Deterministic sourced charts and measured exact-text emphasis."""

from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal, localcontext
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


_MAX_SIGNIFICANT_DIGITS=15


class ChartUnavailable(ValueError):
    """비교 차트를 그릴 수 없는 이유. 렌더 계획 라우트가 500 대신 422와 이 문구로 답해 화면이 안내를 보인다
    (C3 리뷰 C3R-01: 15자리 안내가 "요청이 실패했습니다"로만 보였다)."""


def _significant_digits(value):
    return len(value.normalize().as_tuple().digits)


_DISPLAY_PLACES=Decimal('0.01')


def chart_display_text(value):
    """차트 값의 표시 글자. 소수 2자리 이하는 원문 그대로, 3자리 이상은 소수 셋째 자리에서 사사오입해 2자리로 보인다
    (2026-10-20 회사 PC 이월표 (18) 사용자 결정 A). PowerPoint도 원문 값에 '0.00' 서식을 주면 같은 글자를 보인다
    (2026-10-20 회사 PC 실측: 1.005, 2.675가 1.01, 2.68). 원문 값은 ChartPoint.value와 PPTX 내장 데이터에 남는다."""
    text=format(value,'f')
    if '.' in text:
        text=text.rstrip('0').rstrip('.')
    if len(text.partition('.')[2])<=2:
        return text
    return format(value.quantize(_DISPLAY_PLACES,rounding=ROUND_HALF_UP),'f')


def axis_maximum_text(maximum):
    """축 최댓값의 표시 글자. 눈금은 0과 최댓값 둘뿐이므로(2026-10-20 회사 PC 이월표 (16)) 최댓값 자체의 소수 자릿수만
    남긴다. 미리보기는 이 글자를 그대로 그리고, PPTX의 축 서식은 이 글자의 자릿수를 따른다. 종전의 format(maximum,'f')는
    '1320.0'을 남겨 미리보기 축에 그대로 보였다 (2026-10-16 회사 PC 실측)."""
    places=max(-maximum.normalize().as_tuple().exponent,0)
    return format(maximum,f'.{places}f')


def build_comparison_chart(deck,slide,frame,preset,metrics,sources):
    from slidecaptain.pipeline.story import require_current_story,_require_current_evidence
    if sources is None:
        raise ChartUnavailable('비교 차트는 프로젝트의 실제 원문 자료와 함께 확인해야 합니다.')
    require_current_story(deck,sources)
    story=deck.structure.story_plan
    _require_current_evidence(story,sources)
    comparison=next(item for item in story.comparisons if item.id==slide.chart.comparison_id)
    evidence={item.id:item for item in story.evidence}
    left,right=evidence[comparison.left_evidence_id],evidence[comparison.right_evidence_id]
    assessment=assess_comparison(comparison,left.metric_basis,right.metric_basis,left.value,right.value)
    if assessment.status!='compatible':
        raise ChartUnavailable('비교 조건이 일치하지 않거나 정보가 부족하여 차트를 그릴 수 없습니다.')
    reasons=[]
    operands=[_parse_operand(item,reasons) for item in (left,right)]
    if reasons or any(value is None for value in operands):
        raise ChartUnavailable('차트의 원문 숫자와 전체 단위를 확정하지 못했습니다.')
    basis=left.metric_basis
    unit=comparison.unit_normalization.target_unit if comparison.unit_normalization else basis.unit
    values=[]
    for item,value in zip((left,right),operands):
        if comparison.unit_normalization:
            factor=unit_scale_factor(item.metric_basis.unit,unit)
            if factor is None:
                raise ChartUnavailable('등록된 단위 배율을 확인하지 못했습니다.')
            exact=Fraction(value)*factor
            with localcontext() as context:
                context.prec=80
                value=Decimal(exact.numerator)/Decimal(exact.denominator)
        if value<0 or value>Decimal('1000000000000'):
            raise ChartUnavailable('차트는 0~1조 범위에서 native 숫자로 정확히 표현할 수 있는 값만 지원합니다.')
        if _significant_digits(value)>_MAX_SIGNIFICANT_DIGITS:
            # PowerPoint는 15자리까지만 보이고 미리보기는 원문 자릿수를 보여 두 화면의 숫자가 달라진다 (회사 PC 이월표 (7)).
            # float 왕복 검사보다 먼저 두어, float로 왕복하지 않는 17자리 이상 값도 같은 안내를 받게 한다 (C3 리뷰 C3R-04)
            raise ChartUnavailable('차트 값은 유효숫자 15자리까지 지원합니다. 원문 수치의 자릿수를 줄여 주세요.')
        if Decimal(str(float(value)))!=value:
            raise ChartUnavailable('차트는 0~1조 범위에서 native 숫자로 정확히 표현할 수 있는 값만 지원합니다.')
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
        raise ChartUnavailable('차트의 단위/기간/분모 조건을 세 줄 안에 보존하지 못했습니다. 내용 영역을 확인해 주세요.')
    caption_h=len(condition_lines)*font*preset.spacing.line_spacing+preset.spacing.subtitle_gap
    height=frame.h-caption_h
    # 세로 막대는 그림 영역이 높이에서 글자 크기의 4.5배를 빼고, 아래의 그림 영역 하한이 4배라 8.5배가 하한이다.
    # 하한을 8배로 두면 8~8.5배 구간이 둘째 문구로 실패했다 (회사 PC 이월표 (13))
    if height<font*(8.5 if slide.chart.kind=='column' else 8) or frame.w<font*20:
        raise ChartUnavailable('차트와 필수 조건을 배치할 공간이 부족합니다.')
    text_values=[format(v,'f').rstrip('0').rstrip('.') if '.' in format(v,'f') else format(v,'f') for v in values]
    display_values=[chart_display_text(v) for v in values]
    label_width=max(metrics.face(False).width_pt(label,font) for label in labels)
    value_width=max(metrics.face(False).width_pt(text,font) for text in display_values)
    # 축 최댓값은 앱이 정하는 여유값이라 원문과 무관하다. 반올림해 보이지 않고 값 자체를 소수 2자리로 올려 정한다
    # (회사 PC 이월표 (18)). 값이 1조 이하라 최댓값은 정수 13자리와 소수 2자리, 15자리 안이다. 눈금은 0과 최댓값뿐이라
    # 종전처럼 다섯 눈금의 자릿수를 볼 필요가 없다(C3 리뷰 C3R-03은 눈금 k/5가 16자리가 되는 문제였다)
    maximum=(max(values)*Decimal('1.1')).quantize(_DISPLAY_PLACES,rounding=ROUND_CEILING) if max(values)>0 else Decimal(1)
    axis_text=axis_maximum_text(maximum)
    if slide.chart.kind=='bar':
        plot_x=label_width+font*1.5
        plot_y=font
        plot_w=frame.w-plot_x-value_width-font*2
        # 그림 영역 아래에 값 축 글자 자리로 글자 크기의 2.5배를 둔다. PowerPoint는 12pt 값 축 글자 칸으로 약 28pt를 쓰고,
        # 종전의 2배(24pt)에서는 그 칸을 차트 틀 안에 넣으려고 그림 영역을 계획보다 4.2pt 위에 그렸다 (2026-10-20 회사 PC,
        # build 20430 실측. 30pt에서 계획과 일치)
        plot_h=height-font*3.5
    else:
        # 세로 축 글자는 그림 영역 왼쪽에 끝 맞춤된다. 가장 넓은 눈금 글자는 최댓값이다(소수 자릿수가 모두 같다).
        # 값 글자 폭만 잡으면 '1357.40'처럼 더 넓은 축 글자의 앞자리가 미리보기 왼쪽 밖으로 나간다 (2026-10-16 리뷰)
        plot_x=max(value_width,metrics.face(False).width_pt(axis_text,font))+font*1.5
        plot_y=font*2
        plot_w=frame.w-plot_x-font
        # 축 아래에 범주 이름 자리로 글자 크기의 2.5배를 둔다. PowerPoint는 12pt 범주 이름을 축 아래 15.5~25.5pt에
        # 그려, 종전의 2배(24pt)로는 글자 아랫부분이 차트 틀에서 잘렸다 (2026-10-16 회사 PC, build 20430 실측)
        plot_h=height-font*4.5
        if label_width>plot_w/2-font:
            raise ChartUnavailable('차트 범주 라벨을 한 줄로 보존할 폭이 부족합니다.')
    if plot_w<font*4 or plot_h<font*4:
        raise ChartUnavailable('차트 축과 값을 배치할 공간이 부족합니다.')
    points=[]
    for index,(item,value,label) in enumerate(zip((left,right),values,labels)):
        ratio=float(value/maximum)
        if slide.chart.kind=='bar':
            band=plot_h/2
            x,y,w,h=plot_x,plot_y+band*(index+.25),plot_w*ratio,band*.5
        else:
            band=plot_w/2
            x,y,w,h=plot_x+band*(index+.25),plot_y+plot_h*(1-ratio),band*.5,plot_h*ratio
        points.append(ChartPoint(evidence_id=item.id,label=label,value=text_values[index],display=display_values[index],
                                 color=preset.colors.accent1 if index==0 else preset.colors.accent2,x=x,y=y,w=w,h=h))
    chart=ChartPlan(kind=slide.chart.kind,comparison_id=comparison.id,claim_id=comparison.claim_id,
                    definition=basis.definition,unit=unit,conditions=conditions,axis_minimum='0',axis_maximum=axis_text,
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
