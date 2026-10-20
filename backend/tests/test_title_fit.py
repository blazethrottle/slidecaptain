"""제목 크기 맞춤 (2026-10-20 사용자 결정: 회사 PC 이월표 (22) A, (21) A).

장 제목 28pt, 표지 제목 36pt, 섹션 제목 32pt로 키우고, 칸에 들어가지 않는 제목만 1pt씩 줄여 종전 기본 크기(20, 28, 24pt)까지
맞춘다. 종전 크기에서 칸에 들어가던 제목은 반드시 들어가므로, 업데이트 뒤에 넘침 경고나 도식 장의 렌더 막힘이 새로 생기지 않는다.
"""

import json
from pathlib import Path

import pytest

from slidecaptain.layout.engine import build_render_plan
from slidecaptain.layout.templates import build_slide, slide_geometry
from slidecaptain.metrics.capacity import cover_geometry, divider_geometry, max_lines, measure_lines
from slidecaptain.metrics.font_metrics import FontMetrics
from slidecaptain.metrics.line_breaker import break_paragraph
from slidecaptain.models.deck import BulletBoxSlots, Chapter, CoverSlots, Deck, DividerSlots
from slidecaptain.models.preset import Preset

M = FontMetrics.load_default()


def _frame(plan, key):
    return next(f for f in plan.frames if f.name.endswith(":" + key))


def _warned(plan, key):
    return any(w.slot == key for w in plan.warnings)


def _content(topic, preset=None, scales=None):
    chapter = Chapter(id="c1", topic=topic, template="bullet_box")
    return build_slide(chapter, BulletBoxSlots(conclusion="결론"), 2, preset or Preset(), M, font_scales=scales)


def _cover(title, preset=None):
    return build_slide(Chapter(id="c0", topic="표지", template="cover"), CoverSlots(title=title), 1, preset or Preset(), M)


def _divider(title, preset=None):
    return build_slide(Chapter(id="c3", topic="간지", template="divider"), DividerSlots(section_no="02", section_title=title),
                       3, preset or Preset(), M)


def test_short_titles_use_the_new_sizes():
    assert _frame(_content("짧은 제목"), "title").paras[0].font_pt == 28
    assert _frame(_cover("합성 요청 처리 보고"), "cover_title").paras[0].font_pt == 36
    assert _frame(_divider("요청 처리 절차"), "section_title").paras[0].font_pt == 32


def test_cover_and_section_boxes_hold_one_line_at_the_new_sizes():
    # 종전 칸(표지 48pt, 섹션 44pt)은 36pt와 32pt 한 줄(행간 1.4배로 50.4pt, 44.8pt)이 들어가지 않았다
    s = Preset().spacing
    assert cover_geometry(Preset())["fields"]["cover_title"][1] >= 36 * s.line_spacing
    assert divider_geometry(Preset())["fields"]["section_title"][1] >= 32 * s.line_spacing


def test_long_chapter_title_shrinks_to_the_largest_size_that_fits_one_line():
    topic = "가" * 40
    frame = _frame(plan := _content(topic), "title")
    font = frame.paras[0].font_pt
    assert 20 <= font < 28 and len(frame.paras[0].lines) == 1 and not _warned(plan, "title")
    face = M.face(True)
    assert len(break_paragraph(topic, frame.w, font + 1, face, Preset().spacing.safety_ratio)) > 1


def _fit_before(text, key):
    """종전 동작: 맞춤 없이 종전 크기(20, 28, 24pt)와 종전 칸 높이(40, 48, 44pt)로 넘침 경고가 없었는가."""
    p = Preset()
    width = {"title": slide_geometry(p)["content_width"], "cover_title": cover_geometry(p)["w"],
             "section_title": divider_geometry(p)["w"]}[key]
    size, height = {"title": (20, 40), "cover_title": (28, 48), "section_title": (24, 44)}[key]
    return measure_lines(text, width, size, M.face(True), p.spacing) <= max_lines(height, size, p.spacing.line_spacing)


@pytest.mark.parametrize("build,key", [(_content, "title"), (_cover, "cover_title"), (_divider, "section_title")])
def test_titles_that_fit_at_the_old_size_still_fit(build, key):
    # 불변식: 종전 크기와 칸에서 경고가 없던 제목은 새 기본 크기에서도 경고가 없다. 길이를 늘려 가며 종전에 들어가던
    # 가장 긴 제목까지 본다
    base = "매출 증가 요인과 남은 위험을 정리한 결과 보고 "
    checked = 0
    for n in range(1, 70):
        text = (base * 4)[:n].strip() or "가"
        if _fit_before(text, key):
            checked += 1
            assert not _warned(build(text), key), text
    assert checked >= 20


@pytest.mark.parametrize("build,key,floor", [(_content, "title", 20), (_cover, "cover_title", 28),
                                             (_divider, "section_title", 24)])
def test_title_that_does_not_fit_even_at_the_floor_stays_there_and_warns(build, key, floor):
    plan = build("가" * 90)
    assert _frame(plan, key).paras[0].font_pt == floor and _warned(plan, key)


@pytest.mark.parametrize("topic", ["짧은 제목", "가" * 40])
def test_direct_edit_scale_multiplies_the_fitted_size(topic):
    # 직접 수정 배율은 칸에 맞춘 크기에 곱한다. 맞춤이 사용자가 키운 제목을 다시 줄이면 키운 효과가 사라지기 때문이다.
    # 키운 제목이 넘치면 경고로 알린다(리뷰 TCR-03: 종전 20pt에 1.2배를 둔 덱은 업데이트 뒤 더 커진다, D4 릴리스 안내)
    base = _frame(_content(topic), "title").paras[0].font_pt
    plan = _content(topic, scales={"title": 1.2})
    assert _frame(plan, "title").paras[0].font_pt == round(base * 1.2, 2)


def test_diagram_page_with_a_title_that_fit_at_20pt_still_renders():
    # 리뷰 TCR-01: 도식 장은 제목이 두 줄이 되면 경고가 아니라 렌더를 막는다. 28pt 고정에서는 33~45자 제목이 막혔다
    sample = json.loads((Path(__file__).parent / "fixtures/q3b-project.json").read_text("utf-8"))
    deck = Deck.model_validate(sample["deck"])
    chapter = next(c for c in deck.structure.chapters if c.template == "diagram")
    chapter.topic = "가나다라마바사아자차" * 4
    plan = build_render_plan(deck, Preset(), M)
    page = next(s for s in plan.slides if s.diagram is not None)
    title = next(h for h in page.diagram.headers if h.name.endswith(":title"))
    assert 20 <= title.paras[0].font_pt < 28 and len(title.paras[0].lines) == 1
