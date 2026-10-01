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
from slidecaptain.pipeline.story import story_fingerprint


def chart_sample():
    fixture=json.loads((Path(__file__).parent/'fixtures/q2d-numeric-review.json').read_text())
    deck=Deck.model_validate(fixture['deck'])
    payload=deck.model_dump(mode='json')
    payload['structure']['chapters'][0]['template']='table'
    payload['slides'][0]['slots']={'template':'table','columns':['팀','순매출'],
                                  'rows':[['A','1200원'],['B','1000원']],'footnote':'같은 기간과 분모'}
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
    assert '단위 원' in chart.conditions and '분모 해당 없음' in chart.conditions
    for point in chart.points:
        assert 0<=point.x<=point.x+point.w<=frame.w
        assert 0<=point.y<=point.y+point.h<=frame.h


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
