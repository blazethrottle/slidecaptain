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
    for slide in deck.slides:
        if slide.chapter_id not in chapters:
            raise ValueError(f"구조안에 없는 장을 그릴 수 없습니다: {slide.chapter_id}")
    slides_by_chapter = {slide.chapter_id: slide for slide in deck.slides}

    # 렌더 순서의 진본은 구조안이다 (단계 3 결정 1). slides 배열 순서는 의미가 없다.
    slides = []
    page_no = 0
    for chapter in deck.structure.chapters:
        slide = slides_by_chapter.get(chapter.id)
        if slide is None:
            continue  # 내용이 아직 생성되지 않은 장
        page_no += 1
        slides.append(build_slide(chapter, slide.slots, page_no, preset, metrics))
    return RenderPlan(
        page_width_pt=preset.page_width_pt,
        page_height_pt=preset.page_height_pt,
        style=_style_from_preset(preset),
        slides=slides,
    )
