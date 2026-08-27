"""용량 계약 (설계서 5.1): 프리셋이 확정한 규격에서 슬롯별 최대 분량을 역산한다.

이 한도는 AI 생성의 계약 조건으로 걸리고(단계 3), 편집 중 분량 검증에도 쓰인다.
`face` 인자는 `width_pt(text, font_pt)`를 가진 폭 데이터 한 벌이다 (FaceMetrics).
"""

import math

from pydantic import BaseModel

from slidecaptain.metrics.line_breaker import break_paragraph
from slidecaptain.models.deck import Bullet
from slidecaptain.models.preset import Preset, Spacing


def line_height_pt(font_pt: float, line_spacing: float) -> float:
    return font_pt * line_spacing


def max_lines(area_height_pt: float, font_pt: float, line_spacing: float) -> int:
    return math.floor(area_height_pt / line_height_pt(font_pt, line_spacing))


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
    """레이아웃 엔진(Task 6)과 공유하는 파생 좌표. 수식의 진본은 여기 한 곳이다."""
    s = preset.spacing
    content_top = s.margin_top + s.title_height + s.title_gap
    footnote_top = preset.page_height_pt - s.margin_bottom - s.footnote_height
    content_bottom = footnote_top - s.footnote_gap
    content_width = preset.page_width_pt - s.margin_left - s.margin_right
    return {
        "content_top": content_top,
        "content_bottom": content_bottom,
        "content_width": content_width,
        "footnote_top": footnote_top,
    }


def capacity_contract(template: str, preset: Preset) -> dict[str, int]:
    s = preset.spacing
    r = preset.font_roles
    g = _content_geometry(preset)
    content_h = g["content_bottom"] - g["content_top"]
    box_inner_h = s.box_height - 2 * s.box_padding

    contracts: dict[str, dict[str, int]] = {
        "cover": {},
        "divider": {},
        "summary": {
            "points_max_lines": max_lines(
                content_h - s.box_height - s.summary_box_gap, r.body_pt, s.line_spacing
            ),
            "conclusion_max_lines": max_lines(box_inner_h, r.box_pt, s.line_spacing),
        },
        "bullet_box": {
            "bullets_max_lines": max_lines(
                content_h - s.box_height - s.box_gap, r.body_pt, s.line_spacing
            ),
            "conclusion_max_lines": max_lines(box_inner_h, r.box_pt, s.line_spacing),
            "footnote_max_lines": max_lines(s.footnote_height, r.footnote_pt, s.line_spacing),
        },
        "table": {
            "rows_max_single_line": max_lines(
                content_h, r.table_pt, s.line_spacing
            ),  # 한 줄짜리 행 기준 상한 (머리글 포함)
            "footnote_max_lines": max_lines(s.footnote_height, r.footnote_pt, s.line_spacing),
        },
        "compare2": {
            "card_bullets_max_lines": max_lines(
                content_h - s.box_height - s.box_gap - s.card_heading_height - s.card_heading_gap,
                r.body_pt,
                s.line_spacing,
            ),
            "conclusion_max_lines": max_lines(box_inner_h, r.box_pt, s.line_spacing),
        },
    }
    return contracts[template]
