import pytest
from pptx import Presentation
from pptx.oxml.ns import qn
from pptx.util import Emu, Pt

from slidecaptain.export.pptx_writer import write_pptx
from slidecaptain.models.render import Frame, Para, RenderPlan, RenderStyle, SlidePlan


def _style() -> RenderStyle:
    return RenderStyle(
        korean_font="Noto Sans KR",
        latin_font="Noto Sans KR",
        text_color="202020",
        box_padding_pt=10.0,
        line_spacing=1.4,
        bullet_indent_pt=18.0,
        bullet_gap_pt=6.0,
        table_cell_pad_x_pt=6.0,
        table_cell_pad_y_pt=3.0,
        border_width_pt=0.75,
        bullet_char="•",
        bullet_font="Arial",
    )


def _simple_plan() -> RenderPlan:
    return RenderPlan(
        page_width_pt=960.0,
        page_height_pt=540.0,
        style=_style(),
        slides=[
            SlidePlan(
                chapter_id="ch01",
                template="bullet_box",
                frames=[
                    Frame(
                        name="ch01:title", x=50.0, y=36.0, w=860.0, h=40.0,
                        paras=[Para(text="장 제목", font_pt=20.0, bold=True)],
                    ),
                    Frame(
                        name="ch01:bullets", x=50.0, y=92.0, w=860.0, h=318.0,
                        paras=[
                            Para(text="첫 불릿", font_pt=12.0, bullet=True),
                            Para(text="하위 불릿", font_pt=12.0, level=1, bullet=True),
                        ],
                    ),
                    Frame(
                        name="ch01:conclusion", x=50.0, y=418.0, w=860.0, h=56.0,
                        fill="EEF3F9", border="D0D7E2",
                        paras=[Para(text="결론 문장", font_pt=12.0, bold=True, color="1F4E79")],
                    ),
                ],
            )
        ],
    )


@pytest.fixture()
def saved(tmp_path) -> Presentation:
    out = tmp_path / "out.pptx"
    write_pptx(_simple_plan(), out)
    return Presentation(str(out))


def test_page_size_16_9(saved):
    assert saved.slide_width == Emu(12192000)
    assert saved.slide_height == Emu(6858000)


def test_shape_names_and_positions(saved):
    shapes = {s.name: s for s in saved.slides[0].shapes}
    assert set(shapes) == {"ch01:title", "ch01:bullets", "ch01:conclusion"}
    title = shapes["ch01:title"]
    # 1pt = 12700 EMU
    assert title.left == Emu(round(50.0 * 12700))
    assert title.top == Emu(round(36.0 * 12700))
    assert title.width == Emu(round(860.0 * 12700))
    assert title.height == Emu(round(40.0 * 12700))


def test_every_run_has_korean_lang_and_fonts(saved):
    for shape in saved.slides[0].shapes:
        if not shape.has_text_frame:
            continue
        for para in shape.text_frame.paragraphs:
            for run in para.runs:
                rPr = run._r.find(qn("a:rPr"))
                assert rPr is not None
                assert rPr.get("lang") == "ko-KR"
                latin = rPr.find(qn("a:latin"))
                ea = rPr.find(qn("a:ea"))
                assert latin is not None and latin.get("typeface") == "Noto Sans KR"
                assert ea is not None and ea.get("typeface") == "Noto Sans KR"


def test_autofit_disabled_everywhere(saved):
    from pptx.enum.text import MSO_AUTO_SIZE

    for shape in saved.slides[0].shapes:
        if shape.has_text_frame:
            assert shape.text_frame.auto_size == MSO_AUTO_SIZE.NONE
            assert shape.text_frame.word_wrap is True


def test_font_sizes_written_exactly(saved):
    shapes = {s.name: s for s in saved.slides[0].shapes}
    title_run = shapes["ch01:title"].text_frame.paragraphs[0].runs[0]
    assert title_run.font.size.pt == 20.0
    assert title_run.font.bold is True
    bullet_run = shapes["ch01:bullets"].text_frame.paragraphs[0].runs[0]
    assert bullet_run.font.size.pt == 12.0


def test_bullet_paragraphs_have_marker_and_level(saved):
    shapes = {s.name: s for s in saved.slides[0].shapes}
    paras = shapes["ch01:bullets"].text_frame.paragraphs
    p0 = paras[0]._p.find(qn("a:pPr"))
    assert p0 is not None
    assert p0.find(qn("a:buChar")) is not None
    assert paras[1].level == 1


def test_box_fill_and_border(saved):
    shapes = {s.name: s for s in saved.slides[0].shapes}
    box = shapes["ch01:conclusion"]
    assert box.fill.fore_color.rgb == 0xEEF3F9 or str(box.fill.fore_color.rgb) == "EEF3F9"
    assert str(box.line.color.rgb) == "D0D7E2"


def _border_only_plan() -> RenderPlan:
    return RenderPlan(
        page_width_pt=960.0,
        page_height_pt=540.0,
        style=_style(),
        slides=[
            SlidePlan(
                chapter_id="ch01",
                template="compare2",
                frames=[
                    Frame(
                        name="ch01:left_card", x=50.0, y=92.0, w=420.0, h=318.0,
                        border="D0D7E2",
                        paras=[Para(text="카드 내용", font_pt=12.0)],
                    ),
                ],
            )
        ],
    )


def test_border_only_frame_gets_padding(tmp_path):
    out = tmp_path / "border.pptx"
    write_pptx(_border_only_plan(), out)
    prs = Presentation(str(out))
    shape = prs.slides[0].shapes[0]
    assert shape.text_frame.margin_left == Emu(round(10.0 * 12700))


def test_style_comes_from_plan_not_literal(tmp_path):
    style = _style()
    style.border_width_pt = 2.0
    plan = _simple_plan()
    plan.style = style
    bordered_frame = next(
        f for slide in plan.slides for f in slide.frames if f.border and f.table is None
    )
    out = tmp_path / "t.pptx"
    write_pptx(plan, out)
    prs = Presentation(str(out))
    shapes = {s.name: s for slide in prs.slides for s in slide.shapes}
    assert shapes[bordered_frame.name].line.width.pt == pytest.approx(2.0)


# ---- 세로 정렬: 라이터는 렌더 계획의 valign 을 항상 bodyPr anchor 로 기록한다 (2026-09-02 Critical 묶음 태스크 B) ----
# 배경: python-pptx 자동도형(add_shape)의 기본 bodyPr 은 anchor="ctr" 이고 텍스트박스(add_textbox)는 속성이 없어 top 이다.
# 라이터가 anchor 를 명시하지 않으면 채움과 테두리 프레임만 PowerPoint 에서 세로 중앙이 되어 미리보기(top)와 어긋난다.

_ANCHOR_BY_VALIGN = {"top": "t", "middle": "ctr"}


def _anchor_of(shape) -> str:
    bodyPr = shape.text_frame._txBody.find(qn("a:bodyPr"))
    return bodyPr.get("anchor") or "t"  # 속성 부재 = PowerPoint 기본값 top


def test_every_text_shape_anchor_matches_frame_valign(saved):
    plan = _simple_plan()
    for plan_slide, slide in zip(plan.slides, saved.slides):
        shapes = {s.name: s for s in slide.shapes}
        for frame in plan_slide.frames:
            if frame.table is not None:
                continue
            assert _anchor_of(shapes[frame.name]) == _ANCHOR_BY_VALIGN[frame.valign], frame.name


def test_boxed_frame_is_top_anchored_not_autoshape_default(saved):
    # 채움과 테두리가 있는 결론 박스는 자동도형이라 기본값이 ctr 인데, 렌더 계획(top)이 이겨야 한다
    conclusion = next(s for s in saved.slides[0].shapes if s.name == "ch01:conclusion")
    assert _anchor_of(conclusion) == "t"


def test_middle_valign_is_written_explicitly_for_boxed_and_plain_frames(tmp_path):
    plan = _simple_plan()
    plan.slides[0].frames[2].valign = "middle"  # 채움 있는 결론 박스
    plan.slides[0].frames[0].valign = "middle"  # 채움 없는 제목 텍스트박스 (기본값에 기대지 않는다)
    out = tmp_path / "middle.pptx"
    write_pptx(plan, out)
    prs = Presentation(str(out))
    shapes = {s.name: s for s in prs.slides[0].shapes}
    assert _anchor_of(shapes["ch01:conclusion"]) == "ctr"
    assert _anchor_of(shapes["ch01:title"]) == "ctr"


def _radius_plan(*frames: Frame) -> RenderPlan:
    return RenderPlan(
        page_width_pt=960.0,
        page_height_pt=540.0,
        style=_style(),
        slides=[SlidePlan(chapter_id="ch01", template="cards", frames=list(frames))],
    )


def _shapes_of(tmp_path, plan: RenderPlan):
    out = tmp_path / "radius.pptx"
    write_pptx(plan, out)
    return list(Presentation(str(out)).slides[0].shapes)


def _prst_of(shape) -> str:
    node = shape._element.find(".//" + qn("a:prstGeom"))
    return node.get("prst") if node is not None else ""


def _adjust_of(shape) -> float | None:
    return shape.adjustments[0] if len(shape.adjustments) else None


def test_frame_without_radius_stays_a_plain_rectangle(tmp_path):
    """기존 동작 불변: 반경을 지정하지 않으면 직각 사각형이다."""

    frame = Frame(name="ch01:box", x=50, y=50, w=300, h=100, fill="EEF3F9")
    shape = _shapes_of(tmp_path, _radius_plan(frame))[0]

    assert _prst_of(shape) == "rect"


def test_radius_makes_a_rounded_rectangle_with_proportional_adjustment(tmp_path):
    frame = Frame(name="ch01:card", x=50, y=50, w=300, h=100, fill="EEF3F9", radius_pt=10.0)
    shape = _shapes_of(tmp_path, _radius_plan(frame))[0]

    assert _prst_of(shape) == "roundRect"
    assert _adjust_of(shape) == pytest.approx(10.0 / 100.0)


@pytest.mark.parametrize(
    ("w", "h", "radius"),
    [(200.0, 40.0, 20.0), (40.0, 40.0, 20.0), (300.0, 24.0, 12.0)],
)
def test_half_of_short_side_gives_a_pill_or_circle(tmp_path, w, h, radius):
    """알약과 정원은 둥근 사각형의 조정값 0.5 로 만든다. OVAL 은 조정 핸들이 없어 눌린 타원이 된다."""

    frame = Frame(name="ch01:badge", x=50, y=50, w=w, h=h, fill="0E8C7F", radius_pt=radius)
    shape = _shapes_of(tmp_path, _radius_plan(frame))[0]

    assert _prst_of(shape) == "roundRect"
    assert _adjust_of(shape) == pytest.approx(0.5)


@pytest.mark.parametrize("radius", [80.0, 1000.0])
def test_radius_over_half_is_clamped(tmp_path, radius):
    """python-pptx 는 0.5 초과를 예외 없이 저장한다. 클램프는 라이터가 한다."""

    frame = Frame(name="ch01:badge", x=50, y=50, w=200, h=40, fill="0E8C7F", radius_pt=radius)
    shape = _shapes_of(tmp_path, _radius_plan(frame))[0]

    assert _adjust_of(shape) == pytest.approx(0.5)


def test_zero_radius_is_a_rounded_rectangle_with_square_corners(tmp_path):
    frame = Frame(name="ch01:card", x=50, y=50, w=300, h=100, fill="EEF3F9", radius_pt=0.0)
    shape = _shapes_of(tmp_path, _radius_plan(frame))[0]

    assert _prst_of(shape) == "roundRect"
    assert _adjust_of(shape) == pytest.approx(0.0)


def test_per_frame_border_width_overrides_the_plan_style(tmp_path):
    thin = Frame(name="ch01:a", x=50, y=50, w=300, h=100, border="DCE3E5")
    thick = Frame(name="ch01:b", x=50, y=200, w=300, h=100, border="0E8C7F", border_width_pt=2.5)
    shapes = _shapes_of(tmp_path, _radius_plan(thin, thick))

    assert shapes[0].line.width == Pt(0.75)
    assert shapes[1].line.width == Pt(2.5)
