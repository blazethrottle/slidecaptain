"""덱 + 프리셋 + 폰트 실측 → 렌더 계획. 같은 입력은 항상 같은 출력을 낸다."""

from slidecaptain.layout.diagram_page import build_diagram_render_plan
from slidecaptain.layout.style import style_from_preset
from slidecaptain.layout.templates import build_slide
from slidecaptain.models.deck import Deck, DiagramSlots
from slidecaptain.models.diagram import _evidence_input
from slidecaptain.models.preset import Preset
from slidecaptain.models.render import RenderPlan
from slidecaptain.layout.expression import apply_text_spans, build_comparison_chart


def build_render_plan(deck: Deck, preset: Preset, metrics, *, sources: dict[str,str] | None = None) -> RenderPlan:
    # model_construct/후속 편집으로 우회한 도식 필드도 버리지 않고 검사한다.
    deck = Deck.model_validate(_evidence_input(deck))
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
        if isinstance(slide.slots, DiagramSlots):
            diagram = build_diagram_render_plan(
                slide.slots.diagram, preset, metrics,
                evidence=deck.structure.story_plan.evidence if deck.structure.story_plan else [],
                title=chapter.topic, eyebrow=slide.eyebrow, subtitle=slide.subtitle,
                footnote=slide.slots.footnote, page_no=page_no,
            )
            slides.extend(diagram.slides)
            continue
        page=build_slide(
            chapter, slide.slots, page_no, preset, metrics,
            presenter=deck.meta.presenter, eyebrow=slide.eyebrow, subtitle=slide.subtitle,
        )
        if slide.chart is not None:
            frame=next(item for item in page.frames if item.table is not None)
            chart,caption=build_comparison_chart(deck,slide,frame,preset,metrics,sources)
            page.frames=[item for item in page.frames if item is not frame]
            page.frames.extend([chart,caption])
            page.warnings=[warning for warning in page.warnings if warning.slot!='table']
        if slide.text_spans:
            apply_text_spans(slide,page,preset,metrics)
        slides.append(page)
    return RenderPlan(
        page_width_pt=preset.page_width_pt,
        page_height_pt=preset.page_height_pt,
        style=style_from_preset(preset),
        slides=slides,
    )
