"""템플릿 6종: 슬롯 내용 → 프레임 목록. 좌표는 전부 프리셋 수치의 수식 결과다 (설계서 5.4).

같은 역할은 모든 장에서 같은 위치: 수식에 슬롯 내용이 들어가지 않는다
(내용은 프레임 안에 담길 뿐, 프레임을 움직이지 못한다).
"""

from slidecaptain.metrics.capacity import (
    _content_geometry,
    card_geometry,
    cover_geometry,
    divider_geometry,
    line_height_pt,
    max_lines,
    measure_bullets,
    measure_lines,
)
from slidecaptain.metrics.line_breaker import break_paragraph
from slidecaptain.models.deck import (
    Bullet,
    BulletBoxSlots,
    Chapter,
    CompareSlots,
    CoverSlots,
    DividerSlots,
    SummarySlots,
    TableSlots,
)
from slidecaptain.models.preset import Preset
from slidecaptain.models.render import CapacityWarning, Frame, Para, SlidePlan, TablePlan


def _para_lines(
    text: str, width_pt: float, font_pt: float, bold: bool, preset: Preset, metrics
) -> list[str]:
    """미리보기가 그대로 그릴 줄바꿈 결과. 분량 실측(measure_lines)과 같은 규칙이다."""
    return break_paragraph(text, width_pt, font_pt, metrics.face(bold), preset.spacing.safety_ratio)


def _bullet_paras(bullets: list[Bullet], area_width_pt: float, preset: Preset, metrics) -> list[Para]:
    s, r, c = preset.spacing, preset.font_roles, preset.colors
    return [
        Para(
            text=b.text, level=b.level, font_pt=r.body_pt, color=c.text, bullet=True,
            lines=_para_lines(
                b.text, area_width_pt - s.bullet_indent * (b.level + 1), r.body_pt, False, preset, metrics
            ),
        )
        for b in bullets
    ]


def _title_frame(chapter: Chapter, preset: Preset, metrics) -> Frame:
    s, r, c = preset.spacing, preset.font_roles, preset.colors
    g = _content_geometry(preset)
    return Frame(
        name=f"{chapter.id}:title",
        x=s.margin_left,
        y=s.margin_top,
        w=g["content_width"],
        h=s.title_height,
        paras=[Para(
            text=chapter.topic, font_pt=r.title_pt, bold=True, color=c.text,
            lines=_para_lines(chapter.topic, g["content_width"], r.title_pt, True, preset, metrics),
        )],
    )


def _footnote_frame(chapter: Chapter, text: str, preset: Preset, metrics) -> Frame:
    s, r, c = preset.spacing, preset.font_roles, preset.colors
    g = _content_geometry(preset)
    return Frame(
        name=f"{chapter.id}:footnote",
        x=s.margin_left,
        y=g["footnote_top"],
        w=g["content_width"],
        h=s.footnote_height,
        paras=[Para(
            text=text, font_pt=r.footnote_pt, color=c.text,
            lines=_para_lines(text, g["content_width"], r.footnote_pt, False, preset, metrics),
        )],
    )


def _page_number_frame(chapter: Chapter, page_no: int, preset: Preset) -> Frame:
    s, r, c = preset.spacing, preset.font_roles, preset.colors
    return Frame(
        name=f"{chapter.id}:page_number",
        x=preset.page_width_pt - s.margin_right - s.page_number_width,
        y=preset.page_height_pt - s.page_number_bottom,
        w=s.page_number_width,
        h=s.page_number_height,
        paras=[Para(
            text=str(page_no), font_pt=r.page_number_pt, color=c.text, align="right",
            lines=[str(page_no)],
        )],
    )


def _conclusion_box_frame(chapter: Chapter, text: str, y: float, preset: Preset, metrics) -> Frame:
    s, r, c = preset.spacing, preset.font_roles, preset.colors
    g = _content_geometry(preset)
    inner_w = g["content_width"] - 2 * s.box_padding
    return Frame(
        name=f"{chapter.id}:conclusion",
        x=s.margin_left,
        y=y,
        w=g["content_width"],
        h=s.box_height,
        fill=c.box_fill,
        border=c.border,
        paras=[Para(
            text=text, font_pt=r.box_pt, bold=True, color=c.accent,
            lines=_para_lines(text, inner_w, r.box_pt, True, preset, metrics),
        )],
    )


def _measure_warning(
    chapter: Chapter, slot: str, needed: float, available: float
) -> CapacityWarning:
    return CapacityWarning(
        chapter_id=chapter.id,
        slot=slot,
        message=f"{slot} 분량이 영역을 {needed - available:.0f}pt 넘습니다. 내용을 줄이거나 장을 나누세요",
        needed_pt=needed,
        available_pt=available,
    )


def _conclusion_warning(chapter: Chapter, text: str, preset: Preset, metrics) -> CapacityWarning | None:
    """결론 박스는 높이가 고정이므로, 굵은 글꼴 폭으로 실측해 초과를 잡는다."""
    s, r = preset.spacing, preset.font_roles
    g = _content_geometry(preset)
    inner_w = g["content_width"] - 2 * s.box_padding
    inner_h = s.box_height - 2 * s.box_padding
    capacity = max_lines(inner_h, r.box_pt, s.line_spacing)
    lines = measure_lines(text, inner_w, r.box_pt, metrics.face(True), s)
    if lines <= capacity:
        return None
    lh = line_height_pt(r.box_pt, s.line_spacing)
    return _measure_warning(chapter, "conclusion", lines * lh, inner_h)


def _fixed_height_warning(
    chapter: Chapter, slot: str, text: str,
    width_pt: float, height_pt: float, font_pt: float, bold: bool,
    preset: Preset, metrics,
) -> CapacityWarning | None:
    """높이가 고정된 한 줄성 영역(제목, 각주, 카드 소제목)의 초과를 실측으로 잡는다."""
    if not text:
        return None
    s = preset.spacing
    capacity = max_lines(height_pt, font_pt, s.line_spacing)
    lines = measure_lines(text, width_pt, font_pt, metrics.face(bold), s)
    if lines <= capacity:
        return None
    lh = line_height_pt(font_pt, s.line_spacing)
    return _measure_warning(chapter, slot, lines * lh, height_pt)


def _title_warning(chapter: Chapter, preset: Preset, metrics) -> CapacityWarning | None:
    s, r = preset.spacing, preset.font_roles
    g = _content_geometry(preset)
    return _fixed_height_warning(
        chapter, "title", chapter.topic, g["content_width"], s.title_height, r.title_pt, True,
        preset, metrics,
    )


def _footnote_warning(chapter: Chapter, text: str, preset: Preset, metrics) -> CapacityWarning | None:
    s, r = preset.spacing, preset.font_roles
    g = _content_geometry(preset)
    return _fixed_height_warning(
        chapter, "footnote", text, g["content_width"], s.footnote_height, r.footnote_pt, False,
        preset, metrics,
    )


def _build_cover(chapter: Chapter, slots: CoverSlots, preset: Preset, metrics, presenter: str) -> SlidePlan:
    r, c = preset.font_roles, preset.colors
    geo = cover_geometry(preset)
    x, w, f = geo["x"], geo["w"], geo["fields"]
    # 칸별 (텍스트, 폭, 글꼴 크기, 굵기). 높이가 고정된 한 줄성 영역이라 넘침을 실측으로 잡는다
    # (2026-09-02 Critical 묶음 태스크 C: 종전에는 표지에 경고 함수가 없어 4줄 제목도 경고 0건이었다)
    specs = {
        "cover_title": (slots.title, w, r.cover_title_pt, True, c.text),
        "subtitle": (slots.subtitle, w, r.subtitle_pt, False, c.accent),
        "date": (slots.date, w / 2, r.body_pt, False, c.text),
        # 보고자는 메타에서 온다 (장 제목을 chapter.topic에서 그리는 것과 같은 방식). 피보고자는 그리지 않는다
        "presenter": (presenter, w / 2, r.body_pt, False, c.text),
    }
    frames = []
    warnings = []
    for slot, (text, width, font_pt, bold, color) in specs.items():
        y, h = f[slot]
        frames.append(Frame(
            name=f"{chapter.id}:{slot}", x=x, y=y, w=width, h=h,
            paras=[Para(
                text=text, font_pt=font_pt, bold=bold, color=color,
                lines=_para_lines(text, width, font_pt, bold, preset, metrics),
            )],
        ))
        if (fw := _fixed_height_warning(chapter, slot, text, width, h, font_pt, bold, preset, metrics)) is not None:
            warnings.append(fw)
    return SlidePlan(chapter_id=chapter.id, template="cover", frames=frames, warnings=warnings)


def _build_divider(
    chapter: Chapter, slots: DividerSlots, page_no: int, preset: Preset, metrics
) -> SlidePlan:
    r, c = preset.font_roles, preset.colors
    geo = divider_geometry(preset)
    x, w, f = geo["x"], geo["w"], geo["fields"]
    specs = {
        "section_no": (slots.section_no, r.subtitle_pt, False, c.accent),
        "section_title": (slots.section_title, r.section_title_pt, True, c.text),
    }
    frames = []
    warnings = []
    for slot, (text, font_pt, bold, color) in specs.items():
        y, h = f[slot]
        frames.append(Frame(
            name=f"{chapter.id}:{slot}", x=x, y=y, w=w, h=h,
            paras=[Para(
                text=text, font_pt=font_pt, bold=bold, color=color,
                lines=_para_lines(text, w, font_pt, bold, preset, metrics),
            )],
        ))
        if (fw := _fixed_height_warning(chapter, slot, text, w, h, font_pt, bold, preset, metrics)) is not None:
            warnings.append(fw)
    return SlidePlan(chapter_id=chapter.id, template="divider", frames=frames, warnings=warnings)


def _build_bullet_box(
    chapter: Chapter, slots: BulletBoxSlots, page_no: int, preset: Preset, metrics
) -> SlidePlan:
    s = preset.spacing
    g = _content_geometry(preset)
    bullets_h = g["content_bottom"] - g["content_top"] - s.box_height - s.box_gap
    warnings = []
    if (tw := _title_warning(chapter, preset, metrics)) is not None:
        warnings.append(tw)
    measure = measure_bullets(
        slots.bullets, g["content_width"], preset.font_roles.body_pt, metrics.face(False), s
    )
    if measure.total_height_pt > bullets_h:
        warnings.append(_measure_warning(chapter, "bullets", measure.total_height_pt, bullets_h))
    if (cw := _conclusion_warning(chapter, slots.conclusion, preset, metrics)) is not None:
        warnings.append(cw)
    if (fw := _footnote_warning(chapter, slots.footnote, preset, metrics)) is not None:
        warnings.append(fw)
    frames = [
        _title_frame(chapter, preset, metrics),
        Frame(
            name=f"{chapter.id}:bullets",
            x=s.margin_left, y=g["content_top"], w=g["content_width"], h=bullets_h,
            paras=_bullet_paras(slots.bullets, g["content_width"], preset, metrics),
        ),
        _conclusion_box_frame(chapter, slots.conclusion, g["content_bottom"] - s.box_height, preset, metrics),
        _page_number_frame(chapter, page_no, preset),
    ]
    if slots.footnote:
        frames.insert(3, _footnote_frame(chapter, slots.footnote, preset, metrics))
    return SlidePlan(chapter_id=chapter.id, template="bullet_box", frames=frames, warnings=warnings)


def _build_summary(
    chapter: Chapter, slots: SummarySlots, page_no: int, preset: Preset, metrics
) -> SlidePlan:
    s = preset.spacing
    g = _content_geometry(preset)
    points_top = g["content_top"] + s.box_height + s.summary_box_gap
    points_h = g["content_bottom"] - points_top
    warnings = []
    if (tw := _title_warning(chapter, preset, metrics)) is not None:
        warnings.append(tw)
    measure = measure_bullets(
        slots.points, g["content_width"], preset.font_roles.body_pt, metrics.face(False), s
    )
    if measure.total_height_pt > points_h:
        warnings.append(_measure_warning(chapter, "points", measure.total_height_pt, points_h))
    if (cw := _conclusion_warning(chapter, slots.conclusion, preset, metrics)) is not None:
        warnings.append(cw)
    frames = [
        _title_frame(chapter, preset, metrics),
        _conclusion_box_frame(chapter, slots.conclusion, g["content_top"], preset, metrics),
        Frame(
            name=f"{chapter.id}:points",
            x=s.margin_left, y=points_top, w=g["content_width"], h=points_h,
            paras=_bullet_paras(slots.points, g["content_width"], preset, metrics),
        ),
        _page_number_frame(chapter, page_no, preset),
    ]
    return SlidePlan(chapter_id=chapter.id, template="summary", frames=frames, warnings=warnings)


def _table_col_widths(slots: TableSlots, frame_w: float, preset: Preset, metrics) -> list[float]:
    """열 폭은 열 내용의 최대 실측 폭에 비례 배분하되, 최소 폭을 보장하고 합을 프레임 폭에 맞춘다."""
    s, r = preset.spacing, preset.font_roles
    raw: list[float] = []
    for col_idx, col_name in enumerate(slots.columns):
        header_w = metrics.face(True).width_pt(col_name, r.table_pt)  # 머리글은 굵은 글꼴
        cell_w = max(
            (metrics.face(False).width_pt(row[col_idx], r.table_pt) for row in slots.rows),
            default=0.0,
        )
        raw.append(max(header_w, cell_w) + 2 * s.table_cell_pad_x)
    scale = frame_w / sum(raw)
    widths = [max(w * scale, s.table_min_col_width) for w in raw]
    # 최소 폭 보정으로 합이 넘치면 넘친 만큼 가장 넓은 열에서 회수한다
    excess = sum(widths) - frame_w
    if excess > 0:
        widest_idx = widths.index(max(widths))
        widths[widest_idx] -= excess
    return widths


def _build_table(
    chapter: Chapter, slots: TableSlots, page_no: int, preset: Preset, metrics
) -> SlidePlan:
    s, r, c = preset.spacing, preset.font_roles, preset.colors
    g = _content_geometry(preset)
    table_h = g["content_bottom"] - g["content_top"]
    col_widths = _table_col_widths(slots, g["content_width"], preset, metrics)
    lh = line_height_pt(r.table_pt, s.line_spacing)

    def row_lines(cells: list[str], bold: bool) -> list[list[str]]:
        face = metrics.face(bold)
        return [
            break_paragraph(cell, col_widths[i] - 2 * s.table_cell_pad_x, r.table_pt, face, s.safety_ratio)
            for i, cell in enumerate(cells)
        ]

    header_lines = row_lines(slots.columns, True)
    cell_lines = [row_lines(row, False) for row in slots.rows]

    def row_height(lines_by_cell: list[list[str]]) -> float:
        return max(len(lines) for lines in lines_by_cell) * lh + 2 * s.table_cell_pad_y

    row_heights = [row_height(header_lines)] + [row_height(c) for c in cell_lines]
    warnings = []
    if (tw := _title_warning(chapter, preset, metrics)) is not None:
        warnings.append(tw)
    total_h = sum(row_heights)
    if total_h > table_h:
        warnings.append(_measure_warning(chapter, "table", total_h, table_h))
    if (fw := _footnote_warning(chapter, slots.footnote, preset, metrics)) is not None:
        warnings.append(fw)
    frames = [
        _title_frame(chapter, preset, metrics),
        Frame(
            name=f"{chapter.id}:table",
            x=s.margin_left, y=g["content_top"], w=g["content_width"], h=table_h,
            table=TablePlan(
                col_widths_pt=col_widths,
                header=slots.columns,
                rows=slots.rows,
                font_pt=r.table_pt,
                header_fill=c.table_header_fill,
                row_heights_pt=row_heights,
                header_lines=header_lines,
                cell_lines=cell_lines,
            ),
        ),
        _page_number_frame(chapter, page_no, preset),
    ]
    if slots.footnote:
        frames.insert(2, _footnote_frame(chapter, slots.footnote, preset, metrics))
    return SlidePlan(chapter_id=chapter.id, template="table", frames=frames, warnings=warnings)


def _build_compare2(
    chapter: Chapter, slots: CompareSlots, page_no: int, preset: Preset, metrics
) -> SlidePlan:
    s, r, c = preset.spacing, preset.font_roles, preset.colors
    g = _content_geometry(preset)
    card = card_geometry(preset)  # 계약(capacity_contract)과 같은 기하 함수를 쓴다 (2026-09-02 태스크 A)
    card_h, card_w, inner_w = card["card_h"], card["card_w"], card["inner_w"]
    warnings = []
    if (tw := _title_warning(chapter, preset, metrics)) is not None:
        warnings.append(tw)
    if (cw := _conclusion_warning(chapter, slots.conclusion, preset, metrics)) is not None:
        warnings.append(cw)

    def card_frame(name: str, card_slots, x: float) -> Frame:
        paras = [Para(
            text=card_slots.heading, font_pt=r.body_pt, bold=True, color=c.accent,
            lines=_para_lines(card_slots.heading, inner_w, r.body_pt, True, preset, metrics),
        )]
        paras += _bullet_paras(card_slots.bullets, inner_w, preset, metrics)
        if (hw := _fixed_height_warning(
            chapter, f"{name}_heading", card_slots.heading,
            inner_w, s.card_heading_height, r.body_pt, True,
            preset, metrics,
        )) is not None:
            warnings.append(hw)
        bullets_h_available = card["bullets_h"]
        measure = measure_bullets(card_slots.bullets, inner_w, r.body_pt, metrics.face(False), s)
        if measure.total_height_pt > bullets_h_available:
            warnings.append(_measure_warning(chapter, name, measure.total_height_pt, bullets_h_available))
        return Frame(
            name=f"{chapter.id}:{name}",
            x=x, y=g["content_top"], w=card_w, h=card_h,
            border=c.border,
            paras=paras,
        )

    frames = [
        _title_frame(chapter, preset, metrics),
        card_frame("left_card", slots.left, s.margin_left),
        card_frame("right_card", slots.right, s.margin_left + card_w + s.card_gap),
        _conclusion_box_frame(chapter, slots.conclusion, g["content_bottom"] - s.box_height, preset, metrics),
        _page_number_frame(chapter, page_no, preset),
    ]
    return SlidePlan(chapter_id=chapter.id, template="compare2", frames=frames, warnings=warnings)


def build_slide(
    chapter: Chapter, slots, page_no: int, preset: Preset, metrics, presenter: str = ""
) -> SlidePlan:
    if isinstance(slots, CoverSlots):
        return _build_cover(chapter, slots, preset, metrics, presenter)
    if isinstance(slots, DividerSlots):
        return _build_divider(chapter, slots, page_no, preset, metrics)
    if isinstance(slots, SummarySlots):
        return _build_summary(chapter, slots, page_no, preset, metrics)
    if isinstance(slots, BulletBoxSlots):
        return _build_bullet_box(chapter, slots, page_no, preset, metrics)
    if isinstance(slots, TableSlots):
        return _build_table(chapter, slots, page_no, preset, metrics)
    if isinstance(slots, CompareSlots):
        return _build_compare2(chapter, slots, page_no, preset, metrics)
    raise ValueError(f"알 수 없는 슬롯 유형: {type(slots).__name__}")
