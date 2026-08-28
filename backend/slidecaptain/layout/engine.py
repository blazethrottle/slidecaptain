"""덱 + 프리셋 + 폰트 실측 → 렌더 계획. 같은 입력은 항상 같은 출력을 낸다."""

from slidecaptain.layout.templates import build_slide
from slidecaptain.models.deck import Deck
from slidecaptain.models.preset import Preset
from slidecaptain.models.render import RenderPlan, RenderStyle


def _style_from_preset(preset: Preset) -> RenderStyle:
    return RenderStyle(
        korean_font=preset.fonts.korean,
        latin_font=preset.fonts.latin,
        text_color=preset.colors.text,
        box_padding_pt=preset.spacing.box_padding,
        line_spacing=preset.spacing.line_spacing,
        bullet_indent_pt=preset.spacing.bullet_indent,
        bullet_gap_pt=preset.spacing.bullet_gap,
        table_cell_pad_x_pt=preset.spacing.table_cell_pad_x,
        table_cell_pad_y_pt=preset.spacing.table_cell_pad_y,
        border_width_pt=preset.spacing.border_width_pt,
        bullet_char=preset.bullet_marker.char,
        bullet_font=preset.bullet_marker.font,
    )


def build_render_plan(deck: Deck, preset: Preset, metrics) -> RenderPlan:
    chapters = {ch.id: ch for ch in deck.structure.chapters}
    slides = []
    for page_no, slide in enumerate(deck.slides, start=1):
        chapter = chapters.get(slide.chapter_id)
        if chapter is None:
            raise ValueError(f"구조안에 없는 장을 그릴 수 없습니다: {slide.chapter_id}")
        slides.append(build_slide(chapter, slide.slots, page_no, preset, metrics))
    return RenderPlan(
        page_width_pt=preset.page_width_pt,
        page_height_pt=preset.page_height_pt,
        style=_style_from_preset(preset),
        slides=slides,
    )
