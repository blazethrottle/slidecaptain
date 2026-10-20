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


@pytest.mark.parametrize("scale", [0.8, 1.2])
def test_direct_edit_size_does_not_depend_on_the_title_text(scale):
    # 직접 정한 크기는 맞춤 전 크기(28pt)에 배율을 곱해 그대로 그린다. 화면은 입력한 pt를 맞춤 전 크기에 대한 배율로
    # 저장하므로, 맞춘 크기에 곱하면 제목 문구를 고칠 때 크기가 바뀌었다(확인 리뷰 TFR-01: 40자 제목에 26pt를 넣고
    # 짧게 고치면 33.09pt). 키운 제목이 넘치면 경고로 알린다
    sizes = {_frame(_content(topic, scales={"title": scale}), "title").paras[0].font_pt for topic in ("짧은 제목", "가" * 40)}
    assert sizes == {round(28 * scale, 2)}


def test_font_limit_reports_the_unfitted_base_and_the_rendered_size():
    # 화면은 base_pt로 입력값을 배율로 바꾸고 current_pt를 지금 크기로 보인다(DirectEditPanel). 긴 제목은 배율이 없을 때
    # 맞춘 크기로 그려지므로 current_pt가 그 크기다
    from slidecaptain.layout.direct_edits import font_limit
    from slidecaptain.models.deck import Slide

    topic = "가" * 40
    chapter = Chapter(id="c1", topic=topic, template="bullet_box")
    slide = Slide(chapter_id="c1", slots=BulletBoxSlots(conclusion="결론"))
    limit = font_limit(chapter, slide, Preset(), M, "", "title")
    fitted = _frame(_content(topic), "title").paras[0].font_pt
    assert limit["base_pt"] == 28 and limit["current_pt"] == fitted < 28


def test_cover_and_section_line_contract_uses_the_fit_floor():
    # 확인 리뷰 TFR-03: 행간을 넓힌 프리셋에서 새 크기(36, 32pt) 기준 줄 수가 0이 되어 프롬프트에 "최대 0줄"이 실렸다.
    # 렌더는 하한(28, 24pt)까지 줄여 그리므로 계약도 하한 크기로 센다
    from slidecaptain.metrics.capacity import capacity_contract
    from slidecaptain.models.preset import apply_overrides

    wide = apply_overrides(Preset(), {"spacing": {"line_spacing": 1.6}})
    assert capacity_contract("cover", wide)["cover_title_max_lines"] == 1
    assert capacity_contract("divider", wide)["section_title_max_lines"] == 1
    plan = _cover("합성 요청 처리 보고", wide)
    assert not _warned(plan, "cover_title")


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
