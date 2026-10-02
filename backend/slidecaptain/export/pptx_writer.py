"""렌더 계획 → PPTX. 축적된 기법을 내장한다 (설계서 7.1, 방법론 히스토리 C절).

- 모든 run에 ko-KR 언어 속성 (어절 단위 줄바꿈)
- a:latin과 a:ea 폰트를 함께 지정 (한글 폰트 확실 적용)
- MSO_AUTO_SIZE.NONE (자동 맞춤이 글자를 줄이는 일을 기계적으로 차단)
- 도형 이름 = 역할 태그 (향후 양방향 재수입의 열쇠)
"""

from pathlib import Path
from typing import BinaryIO
import json
from contextlib import contextmanager

from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.chart.xlsx import CategoryWorkbookWriter
from xlsxwriter import Workbook
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION
from pptx.dml.color import RGBColor
from pptx.enum.lang import MSO_LANGUAGE_ID
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Pt

from slidecaptain.models.render import DiagramPagePlan, Frame, Para, RenderPlan, RenderStyle, TablePlan

EMU_PER_PT = 12700


class _LiteralCategoryWorkbookWriter(CategoryWorkbookWriter):
    """Source labels remain literal strings in the editable embedded workbook."""

    @contextmanager
    def _open_worksheet(self, xlsx_file):
        workbook = Workbook(xlsx_file, {"in_memory": True, "strings_to_formulas": False,
                                        "strings_to_urls": False})
        try:
            yield workbook, workbook.add_worksheet()
        finally:
            workbook.close()


class _LiteralCategoryChartData(CategoryChartData):
    @property
    def _workbook_writer(self):
        return _LiteralCategoryWorkbookWriter(self)

_ALIGN = {"left": PP_ALIGN.LEFT, "center": PP_ALIGN.CENTER, "right": PP_ALIGN.RIGHT}
# 세로 정렬은 렌더 계획 값을 항상 명시한다. 자동도형(add_shape)의 기본값은 ctr, 텍스트박스는 top 이라
# 명시하지 않으면 채움과 테두리 프레임만 PowerPoint 에서 중앙 정렬되어 미리보기와 어긋난다 (2026-09-02 태스크 B)
_ANCHOR = {"top": MSO_ANCHOR.TOP, "middle": MSO_ANCHOR.MIDDLE}


def _emu(pt: float) -> Emu:
    return Emu(round(pt * EMU_PER_PT))


def _style_run(run, para: Para, style: RenderStyle) -> None:
    run.font.size = Pt(para.font_pt)
    run.font.bold = para.bold
    run.font.color.rgb = RGBColor.from_string(para.color)
    run.font.name = style.latin_font  # a:latin만 기록된다 (실측 검증 2026-08-27)
    # 공식 API가 a:rPr에 lang="ko-KR"을 기록한다 (v0.1은 한국어 고정)
    run.font.language_id = MSO_LANGUAGE_ID.KOREAN
    # 한글 폰트는 a:ea 요소로 지정해야 실제 렌더에 적용된다. 스키마 순서상 a:latin 바로 뒤에 넣는다
    rPr = run._r.get_or_add_rPr()
    ea = rPr.find(qn("a:ea"))
    if ea is None:
        ea = rPr.makeelement(qn("a:ea"), {})
        latin = rPr.find(qn("a:latin"))
        if latin is not None:
            latin.addnext(ea)
        else:
            rPr.append(ea)
    ea.set("typeface", style.korean_font)


def _apply_bullet(paragraph, para: Para, style: RenderStyle) -> None:
    indent_emu = round(style.bullet_indent_pt * EMU_PER_PT)
    pPr = paragraph._p.get_or_add_pPr()
    pPr.set("marL", str(indent_emu * (para.level + 1)))
    pPr.set("indent", str(-indent_emu))
    bu_font = pPr.makeelement(qn("a:buFont"), {"typeface": style.bullet_font})
    bu_char = pPr.makeelement(qn("a:buChar"), {"char": style.bullet_char})
    pPr.append(bu_font)
    pPr.append(bu_char)


def _fill_text_frame(tf, frame: Frame, style: RenderStyle) -> None:
    tf.word_wrap = True
    tf.auto_size = MSO_AUTO_SIZE.NONE
    tf.vertical_anchor = _ANCHOR[frame.valign]
    pad = _emu(style.box_padding_pt) if (frame.fill or frame.border) else 0
    tf.margin_left = pad
    tf.margin_right = pad
    tf.margin_top = pad
    tf.margin_bottom = pad
    for i, para in enumerate(frame.paras):
        paragraph = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        paragraph.alignment = _ALIGN[para.align]
        # 고정 pt 행간: 용량 계산(line_height_pt)과 렌더를 일치시킨다
        paragraph.line_spacing = Pt(para.font_pt * style.line_spacing)
        paragraph.level = para.level
        if para.bullet:
            _apply_bullet(paragraph, para, style)
        if i > 0 and para.bullet:
            paragraph.space_before = Pt(style.bullet_gap_pt)
        if para.runs:
            for segment in para.runs:
                run=paragraph.add_run()
                run.text=segment.text
                _style_run(run,para.model_copy(update={'bold':segment.bold,'color':segment.color}),style)
        else:
            run = paragraph.add_run()
            run.text = para.text
            _style_run(run, para, style)


def _corner_adjustment(frame: Frame) -> float:
    """모서리 반경을 둥근 사각형의 조정값(짧은 변 대비 비율)으로 바꾼다.

    python-pptx 는 0.5 초과와 음수를 예외 없이 저장하므로(2026-09-07 실측) 여기서 자른다.
    0.5 는 짧은 변의 절반이며 알약과 정원이 나오는 상한이다.
    """

    short_side = min(frame.w, frame.h)
    if short_side <= 0:
        return 0.0
    return max(0.0, min(0.5, (frame.radius_pt or 0.0) / short_side))


def _add_text_shape(slide, frame: Frame, style: RenderStyle) -> None:
    if frame.fill or frame.border:
        rounded = frame.radius_pt is not None
        shape = slide.shapes.add_shape(
            MSO_SHAPE.ROUNDED_RECTANGLE if rounded else MSO_SHAPE.RECTANGLE,
            _emu(frame.x), _emu(frame.y), _emu(frame.w), _emu(frame.h),
        )
        if rounded:
            shape.adjustments[0] = _corner_adjustment(frame)
        shape.shadow.inherit = False
        if frame.fill:
            shape.fill.solid()
            shape.fill.fore_color.rgb = RGBColor.from_string(frame.fill)
        else:
            shape.fill.background()
        if frame.border:
            shape.line.color.rgb = RGBColor.from_string(frame.border)
            width = frame.border_width_pt if frame.border_width_pt is not None else style.border_width_pt
            shape.line.width = Pt(width)
        else:
            shape.line.fill.background()
    else:
        shape = slide.shapes.add_textbox(_emu(frame.x), _emu(frame.y), _emu(frame.w), _emu(frame.h))
    shape.name = frame.name
    _fill_text_frame(shape.text_frame, frame, style)


def _cell_fill(plan: TablePlan, row: int, col: int) -> str | None:
    """칸 채움색. 칸별 목록이 있으면 그것을 쓰고, 없으면 머리행만 단일 색으로 칠한다."""

    if row == 0:
        return plan.header_fills[col] if plan.header_fills else plan.header_fill
    return plan.body_fills[col] if plan.body_fills else None


def _add_table_shape(slide, frame: Frame, style: RenderStyle) -> None:
    plan: TablePlan = frame.table
    n_rows = len(plan.rows) + 1
    n_cols = len(plan.header)
    graphic_frame = slide.shapes.add_table(
        n_rows, n_cols, _emu(frame.x), _emu(frame.y), _emu(frame.w), _emu(frame.h)
    )
    graphic_frame.name = frame.name
    table = graphic_frame.table
    table.first_row = False  # 내장 스타일 밴딩을 쓰지 않고 직접 칠한다 (균일성)
    table.horz_banding = False
    for i, width in enumerate(plan.col_widths_pt):
        table.columns[i].width = _emu(width)
    for i, height in enumerate(plan.row_heights_pt):
        table.rows[i].height = _emu(height)
    all_rows = [plan.header] + plan.rows
    for r_idx, row in enumerate(all_rows):
        for c_idx, text in enumerate(row):
            cell = table.cell(r_idx, c_idx)
            cell.margin_left = _emu(style.table_cell_pad_x_pt)
            cell.margin_right = _emu(style.table_cell_pad_x_pt)
            cell.margin_top = _emu(style.table_cell_pad_y_pt)
            cell.margin_bottom = _emu(style.table_cell_pad_y_pt)
            fill_colour = _cell_fill(plan, r_idx, c_idx)
            if fill_colour is not None:
                cell.fill.solid()
                cell.fill.fore_color.rgb = RGBColor.from_string(fill_colour)
            tf = cell.text_frame
            tf.word_wrap = True
            paragraph = tf.paragraphs[0]
            paragraph.line_spacing = Pt(plan.font_pt * style.line_spacing)
            run = paragraph.add_run()
            run.text = text
            _style_run(
                run,
                Para(text=text, font_pt=plan.font_pt, bold=(r_idx == 0), color=style.text_color),
                style,
            )


def _diagram_tag(shape, name: str, page: DiagramPagePlan, **semantic) -> None:
    shape.name = name
    shape.shadow.inherit = False
    shape._element.xpath('.//p:cNvPr')[0].set('descr', json.dumps({
        'diagram_id': page.layout.diagram_id, 'input_fingerprint': page.input_fingerprint,
        **semantic,
    }, ensure_ascii=False, sort_keys=True))


def _add_fixed_text(slide, frame: Frame, style: RenderStyle, page: DiagramPagePlan,
                    *, line_height_pt: float | None = None, **semantic) -> None:
    """도식만 명시적 줄바꿈을 쓴다. 일반 템플릿의 자동 줄바꿈은 유지한다."""
    shape = slide.shapes.add_textbox(_emu(frame.x), _emu(frame.y), _emu(frame.w), _emu(frame.h))
    _diagram_tag(shape, frame.name, page, **semantic)
    tf = shape.text_frame
    tf.word_wrap = False
    tf.auto_size = MSO_AUTO_SIZE.NONE
    tf.vertical_anchor = MSO_ANCHOR.TOP
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    first = True
    for para in frame.paras:
        for line in para.lines:
            p = tf.paragraphs[0] if first else tf.add_paragraph()
            first = False
            p.alignment = _ALIGN[para.align]
            height = line_height_pt if line_height_pt is not None else para.font_pt * style.line_spacing
            # DrawingML 행간은 1/100pt다. float의 16.799999를 16.79로 잘라 쓰지 않는다.
            p.line_spacing = Emu(round(height * 100) * 127)
            p.space_before = p.space_after = Pt(0)
            # 빈 줄도 동일한 크기를 가지도록 문단과 run 모두 크기를 기록한다.
            p.font.size = Emu(round(para.font_pt * 100) * 127)
            run = p.add_run()
            run.text = line
            _style_run(run, para, style)
            run.font.size = Emu(round(para.font_pt * 100) * 127)


def _add_diagram(slide, page: DiagramPagePlan, style: RenderStyle) -> None:
    layout = page.layout
    prefix = layout.diagram_id
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = RGBColor.from_string(page.background)
    for node in layout.nodes:
        b = node.bounds
        shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, _emu(b.x), _emu(b.y), _emu(b.w), _emu(b.h))
        _diagram_tag(shape, f'{prefix}:node:{node.node.id}', page, node=node.node.model_dump(mode='json'))
        shape.fill.solid()
        shape.fill.fore_color.rgb = RGBColor.from_string(node.fill)
        shape.line.color.rgb = RGBColor.from_string(node.border)
        shape.line.width = _emu(layout.border_width_pt)
    for edge in layout.edges:
        a, b = edge.start.point, edge.end.point
        shape = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, _emu(a.x), _emu(a.y), _emu(b.x), _emu(b.y))
        semantic = {'edge': edge.edge.model_dump(mode='json')}
        _diagram_tag(shape, f'{prefix}:edge:{edge.edge.id}', page, **semantic)
        shape.line.color.rgb = RGBColor.from_string(edge.color)
        shape.line.width = _emu(layout.border_width_pt)
        ln = shape._element.spPr.get_or_add_ln()
        ln.set('cap', 'flat')  # SVG butt에 해당한다. 테마의 끝 모양을 상속하지 않는다.
        if edge.dash_pattern_pt:
            dash = ln.makeelement(qn('a:custDash'), {})
            for i in range(0, len(edge.dash_pattern_pt), 2):
                dash.append(dash.makeelement(qn('a:ds'), {
                    'd': str(round(edge.dash_pattern_pt[i] / layout.border_width_pt * 100000)),
                    'sp': str(round(edge.dash_pattern_pt[i + 1] / layout.border_width_pt * 100000)),
                }))
        else:
            dash = ln.makeelement(qn('a:prstDash'), {'val': 'solid'})
        ln.append(dash)
        for end in ('headEnd', 'tailEnd'):
            ln.append(ln.makeelement(qn('a:' + end), {'type': 'none'}))
        if edge.arrow_points:
            points = [(_emu(p.x), _emu(p.y)) for p in edge.arrow_points]
            builder = slide.shapes.build_freeform(*points[0])
            builder.add_line_segments(points[1:], close=True)
            arrow = builder.convert_to_shape()
            _diagram_tag(arrow, f'{prefix}:edge:{edge.edge.id}:arrow', page, **semantic)
            arrow.fill.solid()
            arrow.fill.fore_color.rgb = RGBColor.from_string(edge.color)
            arrow.line.fill.background()
    for node in layout.nodes:
        for i, text in enumerate(node.texts):
            _add_fixed_text(slide, Frame(
                name=f'{prefix}:node:{node.node.id}:text:{i}', **text.bounds.model_dump(),
                paras=[Para(text=text.text, lines=text.lines, font_pt=text.font_pt, bold=text.bold, color=text.color)],
            ), style, page, line_height_pt=text.line_height_pt, node=node.node.model_dump(mode='json'))
    for edge in layout.edges:
        text = edge.label
        _add_fixed_text(slide, Frame(
            name=f'{prefix}:edge:{edge.edge.id}:label', **text.bounds.model_dump(),
            paras=[Para(text=text.text, lines=text.lines, font_pt=text.font_pt, bold=text.bold, color=text.color)],
        ), style, page, line_height_pt=text.line_height_pt, edge=edge.edge.model_dump(mode='json'))
    for frame in page.headers:
        _add_fixed_text(slide, frame, style, page, role=frame.name.rsplit(':', 1)[-1])


def _chart_font(font,chart,style):
    font.size=Pt(chart.font_pt)
    font.name=style.latin_font
    font.color.rgb=RGBColor.from_string(chart.text_color)
    font.bold=False
    rpr=getattr(font,'_rPr',None)
    if rpr is not None:
        ea=rpr.find(qn('a:ea'))
        if ea is None:
            ea=rpr.makeelement(qn('a:ea'),{})
            rpr.append(ea)
        ea.set('typeface',style.korean_font)


def _add_chart_shape(slide,frame,style):
    spec=frame.chart
    data=_LiteralCategoryChartData(number_format='0.##############')
    data.categories=[point.label for point in spec.points]
    data.add_series(f'{spec.definition} ({spec.unit})',[float(point.value) for point in spec.points])
    shape=slide.shapes.add_chart(XL_CHART_TYPE.BAR_CLUSTERED if spec.kind=='bar' else XL_CHART_TYPE.COLUMN_CLUSTERED,
                                _emu(frame.x),_emu(frame.y),_emu(frame.w),_emu(frame.h),data)
    shape.name=frame.name
    shape._element.nvGraphicFramePr.cNvPr.set('descr',json.dumps(spec.model_dump(mode='json'),ensure_ascii=False,sort_keys=True))
    chart=shape.chart
    chart.has_legend=False
    chart.has_title=False
    plot=chart.plots[0]
    plot.gap_width=100
    plot.has_data_labels=True
    plot.data_labels.position=XL_LABEL_POSITION.OUTSIDE_END
    plot.data_labels.number_format='0.##############'
    _chart_font(plot.data_labels.font,spec,style)
    chart.value_axis.minimum_scale=float(spec.axis_minimum)
    chart.value_axis.maximum_scale=float(spec.axis_maximum)
    chart.value_axis.major_unit=float(spec.axis_maximum)/5
    chart.value_axis.tick_labels.number_format='0.##############'
    for axis in (chart.category_axis,chart.value_axis):
        _chart_font(axis.tick_labels.font,spec,style)
    for index,point in enumerate(spec.points):
        fill=chart.series[0].points[index].format.fill
        fill.solid()
        fill.fore_color.rgb=RGBColor.from_string(point.color)
    if spec.kind=='bar':
        scaling=chart.category_axis._element.find(qn('c:scaling'))
        orientation=scaling.find(qn('c:orientation'))
        if orientation is None:
            orientation=scaling.makeelement(qn('c:orientation'),{})
            scaling.append(orientation)
        orientation.set('val','maxMin')
    plot_area=chart._chartSpace.xpath('./c:chart/c:plotArea')[0]
    layout=plot_area.find(qn('c:layout'))
    if layout is None:
        layout=plot_area.makeelement(qn('c:layout'),{})
        plot_area.insert(0,layout)
    manual=layout.makeelement(qn('c:manualLayout'),{})
    for key,value in (('layoutTarget','inner'),('xMode','edge'),('yMode','edge'),('wMode','factor'),('hMode','factor'),
                      ('x',spec.plot_x/frame.w),('y',spec.plot_y/frame.h),('w',spec.plot_w/frame.w),('h',spec.plot_h/frame.h)):
        node=manual.makeelement(qn('c:'+key),{'val':str(value)})
        manual.append(node)
    layout.append(manual)


def write_pptx(plan: RenderPlan, out_path: str | Path | BinaryIO) -> None:
    style = plan.style
    prs = Presentation()
    prs.slide_width = _emu(plan.page_width_pt)
    prs.slide_height = _emu(plan.page_height_pt)
    blank_layout = prs.slide_layouts[6]
    for slide_plan in plan.slides:
        slide = prs.slides.add_slide(blank_layout)
        if slide_plan.diagram is not None:
            _add_diagram(slide, slide_plan.diagram, style)
            continue
        for frame in slide_plan.frames:
            if frame.chart is not None:
                _add_chart_shape(slide,frame,style)
            elif frame.table is not None:
                _add_table_shape(slide, frame, style)
            else:
                _add_text_shape(slide, frame, style)
    prs.save(out_path if hasattr(out_path, "write") else str(out_path))
