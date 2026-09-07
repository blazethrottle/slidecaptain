"""템플릿 6종: 슬롯 내용 → 프레임 목록. 좌표는 전부 프리셋 수치의 수식 결과다 (설계서 5.4).

같은 역할은 모든 장에서 같은 위치: 수식에 슬롯 내용이 들어가지 않는다
(내용은 프레임 안에 담길 뿐, 프레임을 움직이지 못한다).
"""

from slidecaptain.metrics.capacity import (
    _content_geometry,
    content_geometry,
    callout_geometry,
    card_geometry,
    cards_geometry,
    cover_geometry,
    divider_geometry,
    line_height_pt,
    max_lines,
    measure_bullets,
    measure_lines,
    process_geometry,
)
from slidecaptain.metrics.color import readable_text_color
from slidecaptain.metrics.line_breaker import break_paragraph
from slidecaptain.models.deck import (
    Bullet,
    BulletBoxSlots,
    CalloutSlots,
    CardItem,
    CardsSlots,
    Chapter,
    CompareSlots,
    CoverSlots,
    DividerSlots,
    ProcessSlots,
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


def _bullet_paras(
    bullets: list[Bullet], area_width_pt: float, preset: Preset, metrics, color: str | None = None
) -> list[Para]:
    """color를 생략하면 기본 본문색(c.text)이다. cards 템플릿의 emphasis 카드처럼 어두운
    배경 위에서는 호출자가 휘도로 계산한 색을 넘긴다 (2026-09-07 DB-2)."""
    s, r, c = preset.spacing, preset.font_roles, preset.colors
    text_color = color if color is not None else c.text
    return [
        Para(
            text=b.text, level=b.level, font_pt=r.body_pt, color=text_color, bullet=True,
            lines=_para_lines(
                b.text, area_width_pt - s.bullet_indent * (b.level + 1), r.body_pt, False, preset, metrics
            ),
        )
        for b in bullets
    ]


def slide_geometry(preset: Preset, eyebrow: str = "", subtitle: str = "") -> dict[str, float]:
    """이 슬라이드의 세로 좌표. 공통 슬롯 유무에 따라 제목과 본문이 내려간다 (2026-09-07 DA-4).

    본문 상단을 빌더마다 따로 계산하면 새 슬롯이 어느 템플릿에서만 누락된다. 계산은 여기 하나뿐이고
    `_content_geometry` 를 직접 부르는 곳도 이 함수뿐이다(테스트가 강제한다).
    슬롯이 둘 다 비면 결과가 종전 값과 완전히 같아야 한다.
    """

    s, r = preset.spacing, preset.font_roles
    # 오프셋 산식의 진본은 capacity.common_slot_offset 이다. 레이아웃과 계약이 같은 값을 써야
    # 카드 높이와 계약 상한이 어긋나지 않는다 (2026-09-07 재작업)
    g = content_geometry(preset, eyebrow, subtitle)
    eyebrow_h = r.eyebrow_pt * s.line_spacing if eyebrow else 0.0
    subtitle_h = r.subtitle_pt * s.line_spacing if subtitle else 0.0
    g["eyebrow_y"] = s.margin_top
    g["eyebrow_h"] = eyebrow_h
    g["title_y"] = s.margin_top + (eyebrow_h + s.eyebrow_gap if eyebrow else 0.0)
    g["subtitle_y"] = g["title_y"] + s.title_height + s.subtitle_gap
    g["subtitle_h"] = subtitle_h
    return g


def common_slot_warnings(chapter: Chapter, g: dict, eyebrow: str, subtitle: str,
                         preset: Preset, metrics) -> list[CapacityWarning]:
    """제목과 각주에는 있던 넘침 경고를 이 두 슬롯에도 건다 (2026-09-07 최종 리뷰 major).

    프레임 높이는 한 줄로 고정인데 텍스트는 폭에 따라 여러 줄로 꺾이므로, 경고가 없으면
    긴 문구가 아래 요소를 소리 없이 침범한다.
    """

    r = preset.font_roles
    warnings: list[CapacityWarning] = []
    for slot, text, font_pt, bold, height in (
        ("eyebrow", eyebrow, r.eyebrow_pt, True, g["eyebrow_h"]),
        ("subtitle", subtitle, r.subtitle_pt, False, g["subtitle_h"]),
    ):
        warning = _fixed_height_warning(
            chapter, slot, text, g["content_width"], height, font_pt, bold, preset, metrics
        )
        if warning is not None:
            warnings.append(warning)
    return warnings


def _common_slot_frames(chapter: Chapter, g: dict, eyebrow: str, subtitle: str,
                        preset: Preset, metrics) -> list[Frame]:
    """값이 있을 때만 프레임을 만든다. 비어 있으면 편집 진입은 속성 패널이 맡는다 (DA-4 결정)."""

    r, c = preset.font_roles, preset.colors
    frames: list[Frame] = []
    if eyebrow:
        frames.append(Frame(
            name=f"{chapter.id}:eyebrow",
            x=preset.spacing.margin_left, y=g["eyebrow_y"], w=g["content_width"], h=g["eyebrow_h"],
            paras=[Para(
                text=eyebrow, font_pt=r.eyebrow_pt, bold=True, color=c.accent1,
                lines=_para_lines(eyebrow, g["content_width"], r.eyebrow_pt, True, preset, metrics),
            )],
        ))
    if subtitle:
        frames.append(Frame(
            name=f"{chapter.id}:subtitle",
            x=preset.spacing.margin_left, y=g["subtitle_y"], w=g["content_width"], h=g["subtitle_h"],
            paras=[Para(
                text=subtitle, font_pt=r.subtitle_pt, color=c.ink_soft,
                lines=_para_lines(subtitle, g["content_width"], r.subtitle_pt, False, preset, metrics),
            )],
        ))
    return frames


def _title_frame(chapter: Chapter, preset: Preset, metrics, g: dict | None = None) -> Frame:
    s, r, c = preset.spacing, preset.font_roles, preset.colors
    g = g if g is not None else slide_geometry(preset)
    return Frame(
        name=f"{chapter.id}:title",
        x=s.margin_left,
        y=g["title_y"],
        w=g["content_width"],
        h=s.title_height,
        paras=[Para(
            text=chapter.topic, font_pt=r.title_pt, bold=True, color=c.text,
            lines=_para_lines(chapter.topic, g["content_width"], r.title_pt, True, preset, metrics),
        )],
    )


def _footnote_frame(chapter: Chapter, text: str, preset: Preset, metrics) -> Frame:
    s, r, c = preset.spacing, preset.font_roles, preset.colors
    g = slide_geometry(preset)
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
    g = slide_geometry(preset)
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
    g = slide_geometry(preset)
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
    g = slide_geometry(preset)
    return _fixed_height_warning(
        chapter, "title", chapter.topic, g["content_width"], s.title_height, r.title_pt, True,
        preset, metrics,
    )


def _footnote_warning(chapter: Chapter, text: str, preset: Preset, metrics) -> CapacityWarning | None:
    s, r = preset.spacing, preset.font_roles
    g = slide_geometry(preset)
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
    chapter: Chapter, slots: BulletBoxSlots, page_no: int, preset: Preset, metrics,
    eyebrow: str = "", subtitle: str = "",
) -> SlidePlan:
    s = preset.spacing
    g = slide_geometry(preset, eyebrow, subtitle)
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
        _title_frame(chapter, preset, metrics, g),
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
    chapter: Chapter, slots: SummarySlots, page_no: int, preset: Preset, metrics,
    eyebrow: str = "", subtitle: str = "",
) -> SlidePlan:
    s = preset.spacing
    g = slide_geometry(preset, eyebrow, subtitle)
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
        _title_frame(chapter, preset, metrics, g),
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
    """열 폭은 열 내용의 최대 실측 폭에 비례 배분하되, 최소 폭을 보장하고 합을 프레임 폭에 맞춘다.

    열이 많으면 `table_min_col_width`(기본 60pt) 그대로는 열 수 * 최소 폭이 프레임 폭을 넘을 수 있다
    (실측 n=40 -> -1480pt). 그래서 최소 폭 자체를 `frame_w / n`으로도 낮춘다(그러면 열 수만큼 채워도
    프레임 폭을 넘지 않는다). 그래도 비례 배분 뒤 보정으로 합이 넘치면, 넘친 만큼을 한 열에서 몰아
    빼지 않고 최소 폭을 넘는 여유(slack)에 비례해 여러 열에서 나눠 회수한다: 최소 폭이 frame_w/n
    이하이므로 여유의 합은 항상 초과분 이상이라, 회수 뒤에도 모든 열이 최소 폭 이상으로 남는다.
    """
    s, r = preset.spacing, preset.font_roles
    n = len(slots.columns)
    min_w = min(s.table_min_col_width, frame_w / n)
    raw: list[float] = []
    for col_idx, col_name in enumerate(slots.columns):
        header_w = metrics.face(True).width_pt(col_name, r.table_pt)  # 머리글은 굵은 글꼴
        cell_w = max(
            (metrics.face(False).width_pt(row[col_idx], r.table_pt) for row in slots.rows),
            default=0.0,
        )
        raw.append(max(header_w, cell_w) + 2 * s.table_cell_pad_x)
    scale = frame_w / sum(raw)
    widths = [max(w * scale, min_w) for w in raw]
    excess = sum(widths) - frame_w
    if excess > 0:
        slack = [w - min_w for w in widths]
        total_slack = sum(slack)
        widths = [w - excess * (sl / total_slack) for w, sl in zip(widths, slack)]
    return widths


def _build_table(
    chapter: Chapter, slots: TableSlots, page_no: int, preset: Preset, metrics,
    eyebrow: str = "", subtitle: str = "",
) -> SlidePlan:
    s, r, c = preset.spacing, preset.font_roles, preset.colors
    g = slide_geometry(preset, eyebrow, subtitle)
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
        _title_frame(chapter, preset, metrics, g),
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
    chapter: Chapter, slots: CompareSlots, page_no: int, preset: Preset, metrics,
    eyebrow: str = "", subtitle: str = "",
) -> SlidePlan:
    s, r, c = preset.spacing, preset.font_roles, preset.colors
    g = slide_geometry(preset, eyebrow, subtitle)
    card = card_geometry(preset, eyebrow, subtitle)  # 계약(capacity_contract)과 같은 기하 함수를 쓴다 (2026-09-02 태스크 A)
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
        _title_frame(chapter, preset, metrics, g),
        card_frame("left_card", slots.left, s.margin_left),
        card_frame("right_card", slots.right, s.margin_left + card_w + s.card_gap),
        _conclusion_box_frame(chapter, slots.conclusion, g["content_bottom"] - s.box_height, preset, metrics),
        _page_number_frame(chapter, page_no, preset),
    ]
    return SlidePlan(chapter_id=chapter.id, template="compare2", frames=frames, warnings=warnings)


def _build_callout(
    chapter: Chapter, slots: CalloutSlots, page_no: int, preset: Preset, metrics,
    eyebrow: str = "", subtitle: str = "",
) -> SlidePlan:
    """전폭 강조 밴드 하나가 본문의 전부다 (2026-09-07 DB-1, 벤치마크 원형 2: 슬라이드 절반에서 관측).

    글자색은 채움색(tone 역할)의 상대 휘도로 정한다: 역할 이름 대 글자색의 고정 매핑표를 쓰지
    않는 이유는 DA-3처럼 프리셋 색값 자체가 나중에 바뀔 수 있어서다(metrics.color 참고).
    가운데 정렬(align, valign)은 작은 결론 상자와 달리 밴드가 슬라이드에서 가장 큰 시각 요소라
    내용 길이와 무관하게 균형 잡힌 배너로 보이게 하는 판단이다.
    """
    s, r, c = preset.spacing, preset.font_roles, preset.colors
    g = slide_geometry(preset, eyebrow, subtitle)
    band = callout_geometry(preset, eyebrow, subtitle)
    warnings = []
    if (tw := _title_warning(chapter, preset, metrics)) is not None:
        warnings.append(tw)
    lines = measure_lines(slots.text, band["inner_w"], r.box_pt, metrics.face(True), s)
    if lines > max_lines(band["inner_h"], r.box_pt, s.line_spacing):
        lh = line_height_pt(r.box_pt, s.line_spacing)
        warnings.append(_measure_warning(chapter, "text", lines * lh, band["inner_h"]))
    fill = getattr(c, slots.tone)
    text_color = readable_text_color(fill, light=c.background, dark=c.text)
    frames = [
        _title_frame(chapter, preset, metrics, g),
        Frame(
            name=f"{chapter.id}:text",
            x=s.margin_left, y=band["band_y"], w=g["content_width"], h=band["band_h"],
            fill=fill,
            radius_pt=s.callout_radius_pt,
            valign="middle",
            paras=[Para(
                text=slots.text, font_pt=r.box_pt, bold=True, color=text_color, align="center",
                lines=_para_lines(slots.text, band["inner_w"], r.box_pt, True, preset, metrics),
            )],
        ),
        _page_number_frame(chapter, page_no, preset),
    ]
    return SlidePlan(chapter_id=chapter.id, template="callout", frames=frames, warnings=warnings)


def _build_cards(
    chapter: Chapter, slots: CardsSlots, page_no: int, preset: Preset, metrics,
    eyebrow: str = "", subtitle: str = "",
) -> SlidePlan:
    """카드 2~4개를 가로로 나눈 프레임 (2026-09-07 DB-2). compare2와 달리 결론 상자가
    없어 카드 높이는 본문 영역 전체다. 배지와 꼬리 라벨은 선택이라, 카드마다 실제로 있는
    만큼만 본문 가용 높이에서 뺀다: 용량 계약(capacity.cards_geometry)은 둘 다 항상
    있다고 가정한 안전한 하한이라, 실제 렌더가 계약이 약속한 것보다 좁아지는 일은 없다.

    강조 카드는 어두운 채움(ink)과 강조 테두리 색(accent1)으로 구분한다. 테두리 굵기는
    다른 카드와 같다: border_width_pt를 명시하지 않아 공통 기본값을 그대로 쓴다(계획서가
    강조를 굵기가 아니라 색으로 하라고 명시했다). 글자색은 DB-1이 만든 휘도 판단 함수로
    카드 배경에 맞게 다시 고른다.
    """
    s, r, c = preset.spacing, preset.font_roles, preset.colors
    g = slide_geometry(preset, eyebrow, subtitle)
    n = len(slots.cards)
    cg = cards_geometry(preset, n, eyebrow, subtitle)  # 계약(capacity_contract)과 같은 기하 함수를 쓴다
    card_w, card_h, inner_w = cg["card_w"], cg["card_h"], cg["inner_w"]
    warnings: list[CapacityWarning] = []
    if (tw := _title_warning(chapter, preset, metrics)) is not None:
        warnings.append(tw)

    def card_frame(card: CardItem, name: str, x: float) -> Frame:
        fill = c.ink if card.emphasis else None
        border = c.accent1 if card.emphasis else c.rule
        text_color = readable_text_color(fill, light=c.background, dark=c.text) if fill else c.text
        paras: list[Para] = []
        reserved = s.card_heading_height + s.card_heading_gap
        if card.badge:
            paras.append(Para(
                text=card.badge, font_pt=r.footnote_pt, bold=True, color=text_color,
                lines=_para_lines(card.badge, inner_w, r.footnote_pt, True, preset, metrics),
            ))
            reserved += s.card_badge_height + s.card_badge_gap
            if (bw := _fixed_height_warning(
                chapter, f"{name}_badge", card.badge, inner_w, s.card_badge_height,
                r.footnote_pt, True, preset, metrics,
            )) is not None:
                warnings.append(bw)
        paras.append(Para(
            text=card.heading, font_pt=r.body_pt, bold=True, color=text_color,
            lines=_para_lines(card.heading, inner_w, r.body_pt, True, preset, metrics),
        ))
        if (hw := _fixed_height_warning(
            chapter, f"{name}_heading", card.heading, inner_w, s.card_heading_height,
            r.body_pt, True, preset, metrics,
        )) is not None:
            warnings.append(hw)
        if card.tail:
            reserved += s.card_tail_height + s.card_tail_gap
        bullets_h = card_h - 2 * s.box_padding - reserved
        paras.extend(_bullet_paras(card.bullets, inner_w, preset, metrics, color=text_color))
        measure = measure_bullets(card.bullets, inner_w, r.body_pt, metrics.face(False), s)
        if measure.total_height_pt > bullets_h:
            warnings.append(_measure_warning(chapter, name, measure.total_height_pt, bullets_h))
        if card.tail:
            paras.append(Para(
                text=card.tail, font_pt=r.footnote_pt, color=text_color,
                lines=_para_lines(card.tail, inner_w, r.footnote_pt, False, preset, metrics),
            ))
            if (twn := _fixed_height_warning(
                chapter, f"{name}_tail", card.tail, inner_w, s.card_tail_height,
                r.footnote_pt, False, preset, metrics,
            )) is not None:
                warnings.append(twn)
        return Frame(
            name=f"{chapter.id}:{name}", x=x, y=g["content_top"], w=card_w, h=card_h,
            fill=fill, border=border, paras=paras,
        )

    frames = [_title_frame(chapter, preset, metrics, g)]
    for i, card in enumerate(slots.cards):
        frames.append(card_frame(card, f"card{i}", s.margin_left + i * (card_w + s.card_gap)))
    frames.append(_page_number_frame(chapter, page_no, preset))
    return SlidePlan(chapter_id=chapter.id, template="cards", frames=frames, warnings=warnings)


def _build_process(
    chapter: Chapter, slots: ProcessSlots, page_no: int, preset: Preset, metrics,
    eyebrow: str = "", subtitle: str = "",
) -> SlidePlan:
    """번호 단계 3~6개를 전폭 행으로 쌓는다 (2026-09-07 DB-3). 사용자가 요구한 "플로우차트"의
    실제 형태다. 번호는 데이터가 아니라 렌더 순서(i+1)에서 나온다: 장 제목이 슬롯이 아니라
    구조안 순서(chapter.topic)에서 오는 것과 같은 원칙이다.

    행마다 배지(둥근 사각형, 조정값 0.5)/제목+부제(선택)/보조 라벨(선택, 최대 2개)이 서로 다른
    가로 칸에 있어 프레임 셋으로 나뉜다: 하나의 세로 텍스트 상자로는 "배지 왼쪽, 라벨 오른쪽"을
    표현할 수 없다(cards가 배지/제목/불릿/꼬리를 세로로 쌓아 한 프레임에 담는 것과 다른 점: cards는
    전부 같은 칸에서 위아래로 쌓이지만 process는 칸 자체가 가로로 나뉜다).
    """
    s, r, c = preset.spacing, preset.font_roles, preset.colors
    g = slide_geometry(preset, eyebrow, subtitle)
    n = len(slots.steps)
    pg = process_geometry(preset, n, eyebrow, subtitle)  # 계약(capacity_contract)과 같은 기하 함수를 쓴다
    row_h, row_gap = pg["row_h"], pg["row_gap"]
    warnings: list[CapacityWarning] = []
    if (tw := _title_warning(chapter, preset, metrics)) is not None:
        warnings.append(tw)

    badge_fill = c.accent1
    badge_text_color = readable_text_color(badge_fill, light=c.background, dark=c.text)

    frames = [_title_frame(chapter, preset, metrics, g)]
    for i, step in enumerate(slots.steps):
        name = f"step{i}"
        row_y = pg["content_top"] + i * (row_h + row_gap)
        frames.append(Frame(
            name=f"{chapter.id}:{name}_badge",
            x=pg["badge_x"], y=row_y, w=s.process_badge_size, h=s.process_badge_size,
            fill=badge_fill, radius_pt=s.process_badge_size / 2, valign="middle",
            paras=[Para(
                text=str(i + 1), font_pt=r.footnote_pt, bold=True, color=badge_text_color, align="center",
                lines=[str(i + 1)],
            )],
        ))
        text_paras = [Para(
            text=step.heading, font_pt=r.body_pt, bold=True, color=c.text,
            lines=_para_lines(step.heading, pg["text_w"], r.body_pt, True, preset, metrics),
        )]
        if (hw := _fixed_height_warning(
            chapter, f"{name}_heading", step.heading, pg["text_w"], s.process_heading_height,
            r.body_pt, True, preset, metrics,
        )) is not None:
            warnings.append(hw)
        if step.subtitle:
            text_paras.append(Para(
                text=step.subtitle, font_pt=r.subtitle_pt, color=c.ink_soft,
                lines=_para_lines(step.subtitle, pg["text_w"], r.subtitle_pt, False, preset, metrics),
            ))
            if (sw := _fixed_height_warning(
                chapter, f"{name}_subtitle", step.subtitle, pg["text_w"], pg["subtitle_h"],
                r.subtitle_pt, False, preset, metrics,
            )) is not None:
                warnings.append(sw)
        frames.append(Frame(
            name=f"{chapter.id}:{name}", x=pg["text_x"], y=row_y, w=pg["text_w"], h=row_h,
            paras=text_paras,
        ))
        if step.notes:
            label_paras = []
            for j, note in enumerate(step.notes):
                label_paras.append(Para(
                    text=note, font_pt=r.footnote_pt, color=c.text, align="right",
                    lines=_para_lines(note, pg["label_w"], r.footnote_pt, False, preset, metrics),
                ))
                if (lw := _fixed_height_warning(
                    chapter, f"{name}_label{j}", note, pg["label_w"], s.process_label_height,
                    r.footnote_pt, False, preset, metrics,
                )) is not None:
                    warnings.append(lw)
            frames.append(Frame(
                name=f"{chapter.id}:{name}_labels", x=pg["label_x"], y=row_y, w=pg["label_w"], h=row_h,
                paras=label_paras,
            ))
    frames.append(_page_number_frame(chapter, page_no, preset))
    return SlidePlan(chapter_id=chapter.id, template="process", frames=frames, warnings=warnings)


def build_slide(
    chapter: Chapter, slots, page_no: int, preset: Preset, metrics, presenter: str = "",
    eyebrow: str = "", subtitle: str = "",
) -> SlidePlan:
    plan = _dispatch(chapter, slots, page_no, preset, metrics, presenter, eyebrow, subtitle)
    # 표지와 간지는 그 자체가 제목 슬라이드라 공통 슬롯을 그리지 않는다
    if (eyebrow or subtitle) and not isinstance(slots, (CoverSlots, DividerSlots)):
        g = slide_geometry(preset, eyebrow, subtitle)
        plan.frames = _common_slot_frames(chapter, g, eyebrow, subtitle, preset, metrics) + plan.frames
        plan.warnings = plan.warnings + common_slot_warnings(
            chapter, g, eyebrow, subtitle, preset, metrics
        )
    return plan


def _dispatch(
    chapter: Chapter, slots, page_no: int, preset: Preset, metrics, presenter: str,
    eyebrow: str, subtitle: str,
) -> SlidePlan:
    if isinstance(slots, CoverSlots):
        return _build_cover(chapter, slots, preset, metrics, presenter)
    if isinstance(slots, DividerSlots):
        return _build_divider(chapter, slots, page_no, preset, metrics)
    if isinstance(slots, SummarySlots):
        return _build_summary(chapter, slots, page_no, preset, metrics, eyebrow, subtitle)
    if isinstance(slots, BulletBoxSlots):
        return _build_bullet_box(chapter, slots, page_no, preset, metrics, eyebrow, subtitle)
    if isinstance(slots, TableSlots):
        return _build_table(chapter, slots, page_no, preset, metrics, eyebrow, subtitle)
    if isinstance(slots, CompareSlots):
        return _build_compare2(chapter, slots, page_no, preset, metrics, eyebrow, subtitle)
    if isinstance(slots, CalloutSlots):
        return _build_callout(chapter, slots, page_no, preset, metrics, eyebrow, subtitle)
    if isinstance(slots, CardsSlots):
        return _build_cards(chapter, slots, page_no, preset, metrics, eyebrow, subtitle)
    if isinstance(slots, ProcessSlots):
        return _build_process(chapter, slots, page_no, preset, metrics, eyebrow, subtitle)
    raise ValueError(f"알 수 없는 슬롯 유형: {type(slots).__name__}")
