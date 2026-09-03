"""용량 계약 (설계서 5.1): 프리셋이 확정한 규격에서 슬롯별 최대 분량을 역산한다.

이 한도는 AI 생성의 계약 조건으로 걸리고(단계 3), 편집 중 분량 검증에도 쓰인다.
`face` 인자는 `width_pt(text, font_pt)`를 가진 폭 데이터 한 벌이다 (FaceMetrics).

계약은 실측(5.2)과 같은 규칙으로 계산한다 (2026-09-02 Critical 묶음 태스크 A): 실측이 더하는 항목 간격과
셀 여백, 카드 안쪽 여백을 계약도 똑같이 뺀다. 종전에는 계약이 행간 높이로만 나눠 실측보다 22~35% 많이
약속했고, AI 가 계약을 지켜도 분량 게이트가 초과 경고를 냈다. 기하 수식의 진본은 이 모듈 한 곳이며,
레이아웃 엔진(layout/templates.py)도 같은 함수를 호출한다.
"""

import math

from pydantic import BaseModel

from slidecaptain.metrics.line_breaker import break_paragraph
from slidecaptain.models.deck import Bullet
from slidecaptain.models.preset import Preset, Spacing, content_box


def line_height_pt(font_pt: float, line_spacing: float) -> float:
    return font_pt * line_spacing


def max_lines(area_height_pt: float, font_pt: float, line_spacing: float) -> int:
    return max(0, math.floor(area_height_pt / line_height_pt(font_pt, line_spacing)))


def items_that_fit(area_height_pt: float, font_pt: float, line_spacing: float, gap_pt: float) -> int:
    """한 줄짜리 항목이 전부일 때 영역에 들어가는 최대 항목 수 (항목 사이 간격 포함).

    여러 줄짜리 항목이 섞이면 간격이 줄어 여유가 생기므로, 이 값은 계약의 안전한 하한이다.
    """
    lh = line_height_pt(font_pt, line_spacing)
    return max(0, math.floor((area_height_pt + gap_pt) / (lh + gap_pt)))


def rows_that_fit(area_height_pt: float, font_pt: float, line_spacing: float, pad_y_pt: float) -> int:
    """한 줄짜리 표 행이 전부일 때 들어가는 최대 행 수 (행마다 위아래 셀 여백 포함)."""
    lh = line_height_pt(font_pt, line_spacing)
    return max(0, math.floor(area_height_pt / (lh + 2 * pad_y_pt)))


def measure_lines(text: str, area_width_pt: float, font_pt: float, face, spacing: Spacing) -> int:
    return len(break_paragraph(text, area_width_pt, font_pt, face, spacing.safety_ratio))


class BulletsMeasure(BaseModel):
    total_height_pt: float
    lines_per_bullet: list[int]


def measure_bullets(
    bullets: list[Bullet],
    area_width_pt: float,
    font_pt: float,
    face,
    spacing: Spacing,
) -> BulletsMeasure:
    lh = line_height_pt(font_pt, spacing.line_spacing)
    total = 0.0
    lines_per_bullet: list[int] = []
    for i, bullet in enumerate(bullets):
        indent = spacing.bullet_indent * (bullet.level + 1)
        lines = break_paragraph(
            bullet.text, area_width_pt - indent, font_pt, face, spacing.safety_ratio
        )
        lines_per_bullet.append(len(lines))
        total += len(lines) * lh
        if i > 0:
            # 불릿 간격은 항목 사이에만 있다
            total += spacing.bullet_gap
    return BulletsMeasure(total_height_pt=total, lines_per_bullet=lines_per_bullet)


def _content_geometry(preset: Preset) -> dict[str, float]:
    """레이아웃 엔진(Task 6)과 공유하는 파생 좌표. 수식의 진본은 `models/preset.py`의 `content_box`다

    (2026-09-04 태스크 A3: Preset의 안전 검증이 같은 산식으로 내용 높이를 확인해야 둘이 어긋나지 않는다).
    """
    return content_box(preset)


def card_geometry(preset: Preset) -> dict[str, float]:
    """compare2 카드 기하. 계약과 레이아웃 엔진이 함께 쓴다 (2026-09-02: 종전에는 두 모듈이 다른 값을 계산했다).

    bullets_h 는 카드 소제목 영역과 그 아래 간격, 카드 안쪽 여백(위아래)을 뺀 불릿 가용 높이다.
    """
    s = preset.spacing
    g = _content_geometry(preset)
    card_h = g["content_bottom"] - g["content_top"] - s.box_height - s.box_gap
    card_w = (g["content_width"] - s.card_gap) / 2
    inner_w = card_w - 2 * s.box_padding
    bullets_h = card_h - s.card_heading_height - s.card_heading_gap - 2 * s.box_padding
    return {"card_w": card_w, "card_h": card_h, "inner_w": inner_w, "bullets_h": bullets_h}


def cover_geometry(preset: Preset) -> dict:
    """표지 프레임 기하 (x, w 와 칸별 (y, h)). y 리터럴의 프리셋 승격은 단계 5B 이월 항목이라 값은 그대로 둔다."""
    s = preset.spacing
    return {
        "x": s.margin_left + s.cover_indent,
        "w": preset.page_width_pt - 2 * (s.margin_left + s.cover_indent),
        "fields": {
            "cover_title": (200.0, 48.0),
            "subtitle": (260.0, 24.0),
            "date": (430.0, 18.0),
            "presenter": (452.0, 18.0),
        },
    }


def divider_geometry(preset: Preset) -> dict:
    """간지 프레임 기하 (표지와 같은 형식)."""
    s = preset.spacing
    return {
        "x": s.margin_left + s.cover_indent,
        "w": preset.page_width_pt - 2 * (s.margin_left + s.cover_indent),
        "fields": {
            "section_no": (218.0, 20.0),
            "section_title": (246.0, 44.0),
        },
    }


def capacity_contract(template: str, preset: Preset) -> dict[str, int]:
    s = preset.spacing
    r = preset.font_roles
    g = _content_geometry(preset)
    content_h = g["content_bottom"] - g["content_top"]
    box_inner_h = s.box_height - 2 * s.box_padding
    ls = s.line_spacing
    cover = cover_geometry(preset)["fields"]
    divider = divider_geometry(preset)["fields"]
    card = card_geometry(preset)

    contracts: dict[str, dict[str, int]] = {
        "cover": {
            "cover_title_max_lines": max_lines(cover["cover_title"][1], r.cover_title_pt, ls),
            "subtitle_max_lines": max_lines(cover["subtitle"][1], r.subtitle_pt, ls),
            "date_max_lines": max_lines(cover["date"][1], r.body_pt, ls),
        },
        "divider": {
            "section_no_max_lines": max_lines(divider["section_no"][1], r.subtitle_pt, ls),
            "section_title_max_lines": max_lines(divider["section_title"][1], r.section_title_pt, ls),
        },
        "summary": {
            "points_max_lines": items_that_fit(
                content_h - s.box_height - s.summary_box_gap, r.body_pt, ls, s.bullet_gap
            ),
            "conclusion_max_lines": max_lines(box_inner_h, r.box_pt, ls),
        },
        "bullet_box": {
            "bullets_max_lines": items_that_fit(
                content_h - s.box_height - s.box_gap, r.body_pt, ls, s.bullet_gap
            ),
            "conclusion_max_lines": max_lines(box_inner_h, r.box_pt, ls),
            "footnote_max_lines": max_lines(s.footnote_height, r.footnote_pt, ls),
        },
        "table": {
            # 한 줄짜리 행 기준 상한 (머리글 포함). 행 높이 = 행간 + 위아래 셀 여백
            "rows_max_single_line": rows_that_fit(content_h, r.table_pt, ls, s.table_cell_pad_y),
            "footnote_max_lines": max_lines(s.footnote_height, r.footnote_pt, ls),
        },
        "compare2": {
            "card_heading_max_lines": max_lines(s.card_heading_height, r.body_pt, ls),
            "card_bullets_max_lines": items_that_fit(card["bullets_h"], r.body_pt, ls, s.bullet_gap),
            "conclusion_max_lines": max_lines(box_inner_h, r.box_pt, ls),
        },
    }
    return contracts[template]


def hangul_chars_for_width(width_pt: float, font_pt: float, face, safety_ratio: float) -> int:
    """주어진 폭의 한 줄에 한글이 약 몇 자 들어가는지 어림한다."""
    return max(0, math.floor(width_pt * safety_ratio / face.width_pt("가", font_pt)))


def hangul_chars_per_line(preset: Preset, face) -> int:
    """본문 불릿 한 줄에 한글이 약 몇 자 들어가는지 어림한다 (AI 프롬프트의 분량 환산 안내용).

    불릿 들여쓰기(level 0)를 뺀 폭 기준이다 (2026-09-02: 종전에는 들여쓰기를 빼지 않아 안내대로 쓴 한 어절이 두 줄로 꺾였다).
    """
    g = _content_geometry(preset)
    width = g["content_width"] - preset.spacing.bullet_indent
    return hangul_chars_for_width(width, preset.font_roles.body_pt, face, preset.spacing.safety_ratio)


def char_hints(template: str, preset: Preset, metrics) -> dict[str, int]:
    """템플릿별 환산 안내 (칸 이름 → 한 줄 한글 글자 수). 프롬프트 계약 블록이 그대로 이어 붙인다."""
    s, r = preset.spacing, preset.font_roles
    regular, bold = metrics.face(False), metrics.face(True)
    if template in ("bullet_box", "summary", "table"):
        return {"본문 한 줄": hangul_chars_per_line(preset, regular)}
    if template == "compare2":
        card = card_geometry(preset)
        return {
            "카드 안 한 줄": hangul_chars_for_width(
                card["inner_w"] - s.bullet_indent, r.body_pt, regular, s.safety_ratio
            ),
            "카드 소제목": hangul_chars_for_width(card["inner_w"], r.body_pt, bold, s.safety_ratio),
        }
    if template == "cover":
        w = cover_geometry(preset)["w"]
        return {
            "표지 제목": hangul_chars_for_width(w, r.cover_title_pt, bold, s.safety_ratio),
            "부제": hangul_chars_for_width(w, r.subtitle_pt, regular, s.safety_ratio),
        }
    if template == "divider":
        w = divider_geometry(preset)["w"]
        return {"섹션 제목": hangul_chars_for_width(w, r.section_title_pt, bold, s.safety_ratio)}
    raise KeyError(template)
