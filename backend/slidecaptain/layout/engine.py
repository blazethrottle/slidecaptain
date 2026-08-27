"""덱 + 프리셋 + 폰트 실측 → 렌더 계획. 같은 입력은 항상 같은 출력을 낸다."""

from slidecaptain.layout.templates import build_slide
from slidecaptain.models.deck import Deck
from slidecaptain.models.preset import Preset
from slidecaptain.models.render import RenderPlan


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
        slides=slides,
    )
