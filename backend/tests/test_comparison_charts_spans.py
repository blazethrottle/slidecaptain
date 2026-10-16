"""Sourced chart opt-in and exact-text spans preserve original editable data."""

import hashlib
import json
import io
import zipfile
from xml.etree import ElementTree
from pathlib import Path

import pytest
from pptx import Presentation

from slidecaptain.models.deck import Deck
from slidecaptain.models.preset import Preset
from slidecaptain.metrics.font_metrics import FontMetrics
from slidecaptain.layout.engine import build_render_plan
from slidecaptain.export.pptx_writer import write_pptx
from slidecaptain.pipeline.story import _text_hash, story_fingerprint


def chart_sample(a_value='1,200'):
    # a_value는 원문과 근거의 A팀 값을 함께 바꾼다. 원문이 바뀌므로 근거의 원문 해시도 다시 계산한다
    raw=(Path(__file__).parent/'fixtures/q2d-numeric-review.json').read_text(encoding='utf-8')
    fixture=json.loads(raw.replace('1,200',a_value))
    for evidence in fixture['deck']['structure']['story_plan']['evidence']:
        evidence['source_revision']=_text_hash(fixture['sources'][evidence['source_id']])
    deck=Deck.model_validate(fixture['deck'])
    payload=deck.model_dump(mode='json')
    payload['structure']['chapters'][0]['template']='table'
    payload['slides'][0]['slots']={'template':'table','columns':['팀','순매출'],
                                  'rows':[['A',a_value.replace(',','')+'원'],['B','1000원']],'footnote':'같은 기간과 분모'}
    deck=Deck.model_validate(payload)
    deck.structure.story_plan.input_fingerprint=story_fingerprint(deck.structure.story_plan,deck.meta,deck.structure.chapters,fixture['sources'])
    return deck,fixture['sources']


def test_chart_preserves_source_table_and_writes_native_editable_chart(tmp_path):
    from slidecaptain.models.expression import ChartSpec
    deck,sources=chart_sample()
    original=deck.slides[0].slots.model_dump()
    comparison=deck.structure.story_plan.comparisons[0]
    deck.slides[0].chart=ChartSpec(rule_version='comparison-chart-v1',comparison_id=comparison.id,kind='column')
    plan=build_render_plan(deck,Preset(),FontMetrics.load_default(),sources=sources)
    chart=next(frame.chart for frame in plan.slides[0].frames if frame.chart is not None)
    assert {point.evidence_id for point in chart.points}=={comparison.left_evidence_id,comparison.right_evidence_id}
    assert deck.slides[0].slots.model_dump()==original
    output=tmp_path/'chart.pptx'
    write_pptx(plan,output)
    reopened=Presentation(output)
    charts=[shape.chart for shape in reopened.slides[0].shapes if shape.has_chart]
    assert len(charts)==1 and charts[0].series[0].values==(1200.0,1000.0)


def test_partial_bold_span_preserves_exact_text_in_plan_and_pptx(tmp_path):
    from slidecaptain.models.expression import TextSpan
    fixture=json.loads((Path(__file__).parent/'fixtures/q2d-numeric-review.json').read_text())
    deck=Deck.model_validate(fixture['deck'])
    text=deck.slides[0].slots.bullets[0].text
    deck.slides[0].text_spans=[TextSpan(slot='bullets',index=0,start=0,end=2,role='bold',text_sha256=hashlib.sha256(text.encode()).hexdigest())]
    plan=build_render_plan(deck,Preset(),FontMetrics.load_default())
    para=next(frame for frame in plan.slides[0].frames if frame.name.endswith(':bullets')).paras[0]
    assert ''.join(run.text for run in para.runs)==text
    assert para.runs[0].bold is True and para.runs[-1].bold is False
    output=tmp_path/'span.pptx'
    write_pptx(plan,output)
    prs=Presentation(output)
    shape=next(shape for shape in prs.slides[0].shapes if shape.name.endswith(':bullets'))
    assert shape.text==text
    assert shape.text_frame.paragraphs[0].runs[0].font.bold is True


def test_editable_chart_workbook_preserves_formula_and_url_labels_as_plain_text(tmp_path):
    from slidecaptain.models.expression import ChartSpec
    deck,sources=chart_sample()
    deck.slides[0].chart=ChartSpec(rule_version='comparison-chart-v1',comparison_id=deck.structure.story_plan.comparisons[0].id,kind='bar')
    plan=build_render_plan(deck,Preset(),FontMetrics.load_default(),sources=sources)
    chart=next(f.chart for f in plan.slides[0].frames if f.chart)
    chart.points[0].label='=1+1'
    chart.points[1].label='https://example.com/'
    chart.definition='=1+2'
    output=tmp_path/'literal.pptx'
    write_pptx(plan,output)
    with zipfile.ZipFile(output) as package:
        embedded=next(n for n in package.namelist() if n.startswith('ppt/embeddings/'))
        with zipfile.ZipFile(io.BytesIO(package.read(embedded))) as workbook:
            sheet=ElementTree.fromstring(workbook.read('xl/worksheets/sheet1.xml'))
            ns={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
            assert not sheet.findall('.//s:f',ns)
            assert not sheet.findall('.//s:hyperlink',ns)
            strings=ElementTree.fromstring(workbook.read('xl/sharedStrings.xml'))
            texts=[node.text for node in strings.findall('.//s:t',ns)]
            assert '=1+1' in texts and 'https://example.com/' in texts
            assert any(text.startswith('=1+2') for text in texts)


@pytest.mark.parametrize('kind',['bar','column'])
def test_chart_values_are_source_bound_and_geometries_stay_in_frame(kind):
    from slidecaptain.models.expression import ChartSpec
    deck,sources=chart_sample()
    deck.slides[0].chart=ChartSpec(rule_version='comparison-chart-v1',comparison_id=deck.structure.story_plan.comparisons[0].id,kind=kind)
    frame=next(frame for frame in build_render_plan(deck,Preset(),FontMetrics.load_default(),sources=sources).slides[0].frames if frame.chart)
    chart=frame.chart
    assert [p.value for p in chart.points]==['1200','1000']
    assert chart.axis_minimum=='0'
    assert chart.axis_maximum=='1320'  # 종전 '1320.0'이 미리보기 축에 그대로 보였다 (2026-10-16)
    assert '단위 원' in chart.conditions and '분모 해당 없음' in chart.conditions
    for point in chart.points:
        assert 0<=point.x<=point.x+point.w<=frame.w
        assert 0<=point.y<=point.y+point.h<=frame.h


@pytest.mark.parametrize('maximum,expected',[('1320.0','1320'),('13.2','13.20'),('1.1','1.10'),('1','1.0'),('5','5'),
                                             ('1100000000000.0','1100000000000')])
def test_axis_maximum_text_keeps_only_the_decimals_its_ticks_need(maximum,expected):
    # 2026-10-16 회사 PC 실측: 축 최댓값 문자열 '1320.0'이 미리보기 축에 그대로 보였다. 눈금은 최댓값의 1/5
    # 간격이므로 다섯 눈금을 모두 정확히 보일 자릿수만 남긴다(13.2의 눈금 2.64는 두 자리가 필요하다)
    from decimal import Decimal
    from slidecaptain.layout.expression import axis_maximum_text
    assert axis_maximum_text(Decimal(maximum))==expected


def _shown(format_code,value):
    """PowerPoint가 이 서식 기호로 값을 보일 글자. '0', '0.00' 꼴과, 0만 '0'으로 보이는 '0.00;-0.00;0' 꼴만 받는다."""
    import re
    match=re.fullmatch(r'(0(?:\.(0+))?)(?:;-\1;(0))?',format_code)
    assert match, f'미리보기와 같은 글자를 보장하지 못하는 서식: {format_code}'
    if match.group(3) and float(value)==0:
        return match.group(3)
    return f'{float(value):.{len(match.group(2) or "")}f}'


def _in_schema_order(element,order):
    tags=[child.tag.split('}')[1] for child in element]
    known=[tag for tag in tags if tag in order]
    return known==sorted(known,key=order.index)


_DLBL_ORDER=['idx','delete','layout','tx','numFmt','spPr','txPr','dLblPos','showLegendKey','showVal','showCatName',
             'showSerName','showPercent','showBubbleSize','separator','extLst']
_DLBLS_ORDER=['dLbl','delete','numFmt','spPr','txPr','dLblPos','showLegendKey','showVal','showCatName','showSerName',
              'showPercent','showBubbleSize','separator','showLeaderLines','leaderLines','extLst']


def _chart_labels(path,count):
    """점마다 실제로 적용될 라벨 설정. 점별(c:dLbl), 계열(c:ser/c:dLbls), 차트(c:barChart/c:dLbls) 순으로 앞선 값이 이긴다."""
    ns={'c':'http://schemas.openxmlformats.org/drawingml/2006/chart',
        'a':'http://schemas.openxmlformats.org/drawingml/2006/main'}
    with zipfile.ZipFile(path) as package:
        root=ElementTree.fromstring(package.read(next(n for n in package.namelist() if n.startswith('ppt/charts/chart'))))
    plot=root.find('.//c:plotArea/c:barChart/c:dLbls',ns)
    series=root.find('.//c:ser/c:dLbls',ns)
    points={int(d.find('c:idx',ns).get('val')):d for d in (series.findall('c:dLbl',ns) if series is not None else [])}

    def effective(index,path,attr):
        for level in (points.get(index),series,plot):
            node=level.find(path,ns) if level is not None else None
            if node is not None:
                return node.get(attr)
        return None

    labels=[{'format':effective(i,'c:numFmt','formatCode'),'show':effective(i,'c:showVal','val'),
             'position':effective(i,'c:dLblPos','val'),'size':effective(i,'c:txPr/a:p/a:pPr/a:defRPr','sz')}
            for i in range(count)]
    # ElementTree의 find는 순서를 보지 않으므로, PowerPoint가 복구 오류를 내는 스키마 순서 위반을 따로 본다
    for container in (plot,series):
        if container is not None:
            assert _in_schema_order(container,_DLBLS_ORDER)
    for dlbl in points.values():
        assert _in_schema_order(dlbl,_DLBL_ORDER)
    axis=root.find('.//c:valAx/c:numFmt',ns).get('formatCode')
    return labels,axis


@pytest.mark.parametrize('kind',['bar','column'])
@pytest.mark.parametrize('a_value,values,axis_text',[('1,200',None,'1320'),('1,200',('1200','1000.5'),'1320'),
                                                     ('1,234',None,'1357.40')])
def test_pptx_chart_labels_and_axis_show_the_same_text_as_the_preview(tmp_path,kind,a_value,values,axis_text):
    # 2026-10-16 회사 PC 실측(PowerPoint 16.0 build 20430): '0.##############' 서식 때문에 값과 눈금이 '1200.',
    # '1320.'처럼 끝에 마침표가 붙었다. 미리보기는 '1200'을 그리고 배치도 그 글자 폭으로 계산한다.
    # 1234와 1000은 눈금(271.48 간격)에 소수 두 자리가 필요한 축이다(리뷰 발견: 정수 축만 시험했다)
    from slidecaptain.models.expression import ChartSpec
    deck,sources=chart_sample(a_value)
    deck.slides[0].chart=ChartSpec(rule_version='comparison-chart-v1',comparison_id=deck.structure.story_plan.comparisons[0].id,kind=kind)
    plan=build_render_plan(deck,Preset(),FontMetrics.load_default(),sources=sources)
    chart=next(f.chart for f in plan.slides[0].frames if f.chart)
    assert chart.axis_maximum==axis_text
    for point,value in zip(chart.points,values or ()):
        point.value=value
    output=tmp_path/'chart.pptx'
    write_pptx(plan,output)
    labels,axis=_chart_labels(output,len(chart.points))
    for point,label in zip(chart.points,labels):
        # 계열이나 점에 라벨 설정을 새로 만들면 값 표시, 위치, 글꼴이 차트 단위 설정을 덮으므로 함께 본다
        assert label['show']=='1'
        assert label['position']=='outEnd'
        assert label['size']==str(int(chart.font_pt*100))
        assert _shown(label['format'],point.value)==point.value
    assert _shown(axis,chart.axis_maximum)==chart.axis_maximum
    assert _shown(axis,chart.axis_minimum)=='0'  # 미리보기는 0 눈금을 '0'으로 그린다


def test_column_chart_leaves_room_for_the_axis_maximum_the_preview_draws():
    # 리뷰 발견(2026-10-16): 1234와 1000의 축 최댓값 '1357.40'이 값 글자보다 넓어, 미리보기가 축 글자를
    # 프레임 왼쪽 밖(-4.7pt)에서 그리기 시작해 앞자리가 잘렸다. 미리보기는 축 최댓값을 plot_x-font/2에 끝 맞춤한다
    from slidecaptain.models.expression import ChartSpec
    deck,sources=chart_sample('1,234')
    deck.slides[0].chart=ChartSpec(rule_version='comparison-chart-v1',comparison_id=deck.structure.story_plan.comparisons[0].id,kind='column')
    metrics=FontMetrics.load_default()
    chart=next(f.chart for f in build_render_plan(deck,Preset(),metrics,sources=sources).slides[0].frames if f.chart)
    assert chart.axis_maximum=='1357.40'
    assert chart.plot_x-chart.font_pt/2-metrics.face(False).width_pt(chart.axis_maximum,chart.font_pt)>=0


@pytest.mark.parametrize('damage',['missing_sources','stale_source','incompatible','forged_comparison','value_token'])
def test_chart_never_falls_back_to_original_table_for_unverifiable_values(damage):
    from slidecaptain.models.expression import ChartSpec
    deck,sources=chart_sample()
    deck.slides[0].chart=ChartSpec(rule_version='comparison-chart-v1',comparison_id=deck.structure.story_plan.comparisons[0].id,kind='bar')
    if damage=='missing_sources':
        sources=None
    elif damage=='stale_source':
        sources={name:text+'\nchanged' for name,text in sources.items()}
    elif damage=='incompatible':
        deck.structure.story_plan.evidence[1].metric_basis.definition='다른 지표'
    elif damage=='forged_comparison':
        deck.slides[0].chart.comparison_id='unknown'
    else:
        deck.structure.story_plan.evidence[0].value='200'  # substring of 1200 is not a fact
    with pytest.raises(ValueError):
        build_render_plan(deck,Preset(),FontMetrics.load_default(),sources=sources)


@pytest.mark.parametrize('changes',[{'kind':'pie'},{'values':[1,2]},{'x':0},{'approved':True}])
def test_chart_does_not_accept_client_values_geometry_or_approval(changes):
    from slidecaptain.models.expression import ChartSpec
    with pytest.raises(ValueError):
        ChartSpec.model_validate({'rule_version':'comparison-chart-v1','comparison_id':'cp1','kind':'bar',**changes})


@pytest.mark.parametrize('changes',[{'start':True},{'end':0},{'end':100000},{'index':1},
                                   {'text_sha256':'0'*64},{'role':'arbitrary'},{'slot':'rows'},
                                   {'index':None},{'start':2,'end':2}])
def test_spans_reject_invalid_offsets_stale_text_or_wrong_scope(changes):
    fixture=json.loads((Path(__file__).parent/'fixtures/q2d-numeric-review.json').read_text())
    payload=fixture['deck']
    text=payload['slides'][0]['slots']['bullets'][0]['text']
    payload['slides'][0]['text_spans']=[{'slot':'bullets','index':0,'start':0,'end':2,'role':'bold',
                                       'text_sha256':hashlib.sha256(text.encode()).hexdigest(),**changes}]
    with pytest.raises(ValueError):
        Deck.model_validate(payload)


def test_overlapping_spans_and_edits_cannot_rebind_old_offsets():
    from slidecaptain.models.expression import TextSpan
    fixture=json.loads((Path(__file__).parent/'fixtures/q2d-numeric-review.json').read_text())
    deck=Deck.model_validate(fixture['deck'])
    text=deck.slides[0].slots.bullets[0].text
    span={'slot':'bullets','index':0,'start':0,'end':3,'role':'bold','text_sha256':hashlib.sha256(text.encode()).hexdigest()}
    deck.slides[0].text_spans=[TextSpan(**span),TextSpan(**{**span,'start':2,'end':4,'role':'accent'})]
    with pytest.raises(ValueError,match='겹칠'):
        build_render_plan(deck,Preset(),FontMetrics.load_default())
    deck.slides[0].text_spans=deck.slides[0].text_spans[:1]
    deck.slides[0].slots.bullets[0].text='다른 문장'
    with pytest.raises(ValueError,match='기준 문장'):
        build_render_plan(deck,Preset(),FontMetrics.load_default())


def test_legacy_deck_and_numeric_fingerprint_are_identical_without_opt_in():
    from slidecaptain.pipeline.numeric_review import assess_numeric_review
    fixture=json.loads((Path(__file__).parent/'fixtures/q2d-numeric-review.json').read_text())
    deck=Deck.model_validate(fixture['deck'])
    assert deck.model_dump(mode='json')==fixture['deck']
    assert assess_numeric_review(deck,fixture['sources']).model_dump(mode='json')==fixture['matched_report']
    plan=build_render_plan(deck,Preset(),FontMetrics.load_default())
    for frame in plan.model_dump(mode='json')['slides'][0]['frames']:
        assert 'chart' not in frame
        assert all('runs' not in para and 'line_runs' not in para for para in frame['paras'])


def test_bold_face_width_changes_wrapping_and_is_not_replaced_by_regular_width():
    from slidecaptain.layout.expression import _styled_lines
    from slidecaptain.models.expression import TextRun
    class Face:
        def __init__(self,width):self.width=width
        def width_pt(self,text,font):return len(text)*self.width
    class Metrics:
        def face(self,bold):return Face(10 if bold else 1)
    plain=_styled_lines([TextRun(text='AAAA BBBB',bold=False,color='202020')],8,12,Metrics(),1)
    styled=_styled_lines([TextRun(text='AAAA',bold=True,color='202020'),TextRun(text=' BBBB',bold=False,color='202020')],8,12,Metrics(),1)
    assert len(styled)>len(plain)
    assert ''.join(run.text for line in styled for run in line)=='AAAA BBBB'
