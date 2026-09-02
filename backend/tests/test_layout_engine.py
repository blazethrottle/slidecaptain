import pytest

from slidecaptain.layout.engine import build_render_plan
from slidecaptain.metrics.font_metrics import FontMetrics
from slidecaptain.models.deck import (
    Bullet,
    BulletBoxSlots,
    Card,
    Chapter,
    CompareSlots,
    CoverSlots,
    Deck,
    DeckMeta,
    DividerSlots,
    Slide,
    Structure,
    SummarySlots,
    TableSlots,
)
from slidecaptain.models.preset import Preset

METRICS = FontMetrics.load_default()


class FakeFace:
    def width_pt(self, text: str, font_pt: float) -> float:
        return len(text) * font_pt * 0.5


class FakeMetrics:
    """FontMetrics와 같은 모양의 가짜: 볼드 구분 없이 같은 폭을 돌려준다."""

    def face(self, bold: bool) -> FakeFace:
        return FakeFace()


PRESET = Preset()
FAKE = FakeMetrics()


def _deck(chapters_and_slots) -> Deck:
    chapters = []
    slides = []
    for i, (template, slots) in enumerate(chapters_and_slots, start=1):
        cid = f"ch{i:02d}"
        chapters.append(Chapter(id=cid, topic=f"{i}장 주제", template=template))
        slides.append(Slide(chapter_id=cid, slots=slots))
    return Deck(
        meta=DeckMeta(title="테스트 덱"),
        structure=Structure(chapters=chapters),
        slides=slides,
    )


def _bullet_box_deck() -> Deck:
    return _deck(
        [
            (
                "bullet_box",
                BulletBoxSlots(
                    bullets=[Bullet(text="첫 불릿"), Bullet(text="둘째 불릿", level=1)],
                    conclusion="결론 한 줄",
                    footnote="주: 출처는 내부 자료",
                ),
            )
        ]
    )


def _frame(plan_slide, name_suffix):
    matches = [f for f in plan_slide.frames if f.name.endswith(name_suffix)]
    assert len(matches) == 1, f"{name_suffix} 프레임이 정확히 1개 있어야 합니다"
    return matches[0]


def test_bullet_box_frame_positions():
    plan = build_render_plan(_bullet_box_deck(), PRESET, FAKE)
    slide = plan.slides[0]
    title = _frame(slide, ":title")
    assert (title.x, title.y, title.w, title.h) == (50.0, 36.0, 860.0, 40.0)
    bullets = _frame(slide, ":bullets")
    assert (bullets.x, bullets.y, bullets.w, bullets.h) == (50.0, 92.0, 860.0, 318.0)
    box = _frame(slide, ":conclusion")
    assert (box.x, box.y, box.w, box.h) == (50.0, 418.0, 860.0, 56.0)
    footnote = _frame(slide, ":footnote")
    assert (footnote.x, footnote.y, footnote.w, footnote.h) == (50.0, 482.0, 860.0, 24.0)


def test_title_comes_from_structure_topic():
    plan = build_render_plan(_bullet_box_deck(), PRESET, FAKE)
    title = _frame(plan.slides[0], ":title")
    assert title.paras[0].text == "1장 주제"


def test_frame_names_carry_role_tags():
    plan = build_render_plan(_bullet_box_deck(), PRESET, FAKE)
    names = {f.name for f in plan.slides[0].frames}
    assert names == {"ch01:title", "ch01:bullets", "ch01:conclusion", "ch01:footnote", "ch01:page_number"}


def test_same_role_same_position_across_slides():
    deck = _deck(
        [
            ("bullet_box", BulletBoxSlots(bullets=[Bullet(text="가")], conclusion="결론 A")),
            ("bullet_box", BulletBoxSlots(bullets=[Bullet(text="나")], conclusion="결론 B")),
        ]
    )
    plan = build_render_plan(deck, PRESET, FAKE)
    f1 = _frame(plan.slides[0], ":title")
    f2 = _frame(plan.slides[1], ":title")
    assert (f1.x, f1.y, f1.w, f1.h) == (f2.x, f2.y, f2.w, f2.h)


def test_deterministic_output():
    deck = _bullet_box_deck()
    plan_a = build_render_plan(deck, PRESET, FAKE)
    plan_b = build_render_plan(deck, PRESET, FAKE)
    assert plan_a == plan_b


def test_cover_and_divider_have_no_page_number_or_title_frame():
    deck = _deck(
        [
            ("cover", CoverSlots(title="보고 제목", subtitle="부제", date="2026-08-27")),
            ("divider", DividerSlots(section_no="1", section_title="첫 섹션")),
            ("bullet_box", BulletBoxSlots(bullets=[Bullet(text="가")], conclusion="결론")),
        ]
    )
    plan = build_render_plan(deck, PRESET, FAKE)
    cover_names = {f.name for f in plan.slides[0].frames}
    assert not any(n.endswith(":page_number") for n in cover_names)
    divider_names = {f.name for f in plan.slides[1].frames}
    assert any(n.endswith(":section_title") for n in divider_names)
    # 본문 장에는 쪽번호가 있고, 번호는 표지 포함 실제 순번이다
    content_pn = _frame(plan.slides[2], ":page_number")
    assert content_pn.paras[0].text == "3"


def test_summary_box_on_top():
    deck = _deck([("summary", SummarySlots(conclusion="핵심 결론", points=[Bullet(text="요점")]))])
    plan = build_render_plan(deck, PRESET, FAKE)
    box = _frame(plan.slides[0], ":conclusion")
    assert (box.y, box.h) == (92.0, 56.0)
    points = _frame(plan.slides[0], ":points")
    assert (points.y, points.h) == (160.0, 314.0)


def test_compare2_cards_symmetric():
    deck = _deck(
        [
            (
                "compare2",
                CompareSlots(
                    left=Card(heading="옵션 A", bullets=[Bullet(text="장점")]),
                    right=Card(heading="옵션 B", bullets=[Bullet(text="단점")]),
                    conclusion="A를 권장",
                ),
            )
        ]
    )
    plan = build_render_plan(deck, PRESET, FAKE)
    left = _frame(plan.slides[0], ":left_card")
    right = _frame(plan.slides[0], ":right_card")
    assert (left.x, left.y, left.w, left.h) == (50.0, 92.0, 420.0, 318.0)
    assert (right.x, right.y, right.w, right.h) == (490.0, 92.0, 420.0, 318.0)


def test_table_column_widths_sum_to_frame_width():
    deck = _deck(
        [
            (
                "table",
                TableSlots(
                    columns=["항목", "상세 내용 설명"],
                    rows=[["가", "이 칸은 내용이 훨씬 길어서 넓은 열이 필요하다"]],
                ),
            )
        ]
    )
    plan = build_render_plan(deck, PRESET, FAKE)
    table = _frame(plan.slides[0], ":table")
    assert table.table is not None
    widths = table.table.col_widths_pt
    assert sum(widths) == pytest.approx(860.0)
    assert widths[1] > widths[0]  # 내용이 긴 열이 더 넓다
    assert min(widths) >= PRESET.spacing.table_min_col_width


def test_conclusion_overflow_warns():
    # 결론 박스는 높이 고정(56pt)이라 2줄을 넘으면 경고가 남는다
    long_conclusion = "결론 문장이 지나치게 길어서 박스 용량을 넘는다 " * 20
    deck = _deck([("bullet_box", BulletBoxSlots(bullets=[Bullet(text="가")], conclusion=long_conclusion))])
    plan = build_render_plan(deck, PRESET, FAKE)
    assert any(w.slot == "conclusion" for w in plan.slides[0].warnings)


def test_overflow_produces_warning_not_resize():
    # 본문 영역을 넘치는 불릿 더미: 경고가 남고 글자 크기는 그대로다
    many = [Bullet(text=f"불릿 항목 {i}: 내용이 제법 길어서 여러 줄로 나뉘게 되는 문장이다") for i in range(30)]
    deck = _deck([("bullet_box", BulletBoxSlots(bullets=many, conclusion="결론"))])
    plan = build_render_plan(deck, PRESET, FAKE)
    slide = plan.slides[0]
    assert len(slide.warnings) >= 1
    warning = slide.warnings[0]
    assert warning.slot == "bullets"
    assert warning.needed_pt > warning.available_pt
    bullets = _frame(slide, ":bullets")
    assert all(p.font_pt == PRESET.font_roles.body_pt for p in bullets.paras)


def test_body_font_sizes_at_most_two_steps_on_content_slides():
    deck = _bullet_box_deck()
    plan = build_render_plan(deck, PRESET, FAKE)
    slide = plan.slides[0]
    body_sizes = {
        p.font_pt
        for f in slide.frames
        if not (f.name.endswith(":title") or f.name.endswith(":page_number"))
        for p in f.paras
    }
    assert len(body_sizes) <= 2


def _two_chapter_deck() -> Deck:
    return Deck(
        meta=DeckMeta(title="순서 테스트"),
        structure=Structure(chapters=[
            Chapter(id="c2", topic="둘째 주제", template="bullet_box"),
            Chapter(id="c1", topic="첫째 주제", template="bullet_box"),
        ]),
        slides=[
            Slide(chapter_id="c1", slots=BulletBoxSlots(conclusion="결론1")),
            Slide(chapter_id="c2", slots=BulletBoxSlots(conclusion="결론2")),
        ],
    )


def test_render_order_follows_structure_not_slides_array():
    plan = build_render_plan(_two_chapter_deck(), Preset(), METRICS)
    assert [s.chapter_id for s in plan.slides] == ["c2", "c1"]


def test_chapter_without_slide_is_skipped_and_pages_renumber():
    # c1 슬라이드만 남긴다: 구조안에서 c1은 두 번째 장이므로, 장 위치를 그대로 쪽번호로 쓰는
    # 버그 구현은 2를 내고 올바른 구현(렌더 순번)은 1을 낸다 (2026-08-28 적대 리뷰 반영)
    deck = _two_chapter_deck()
    deck = deck.model_copy(update={"slides": [deck.slides[0]]})
    plan = build_render_plan(deck, Preset(), METRICS)
    assert [s.chapter_id for s in plan.slides] == ["c1"]
    page_para = next(
        p for f in plan.slides[0].frames if f.name.endswith(":page_number") for p in f.paras
    )
    assert page_para.text == "1"


def _plan_for(chapter: Chapter, slots) -> "SlidePlan":
    deck = Deck(
        meta=DeckMeta(title="경고 테스트"),
        structure=Structure(chapters=[chapter]),
        slides=[Slide(chapter_id=chapter.id, slots=slots)],
    )
    return build_render_plan(deck, Preset(), METRICS).slides[0]


def _warned_slots(plan_slide) -> set[str]:
    return {w.slot for w in plan_slide.warnings}


# 제목 경고는 4종 빌더 전부에 배선되므로 전부 검증한다 (2026-08-28 적대 리뷰 반영)
@pytest.mark.parametrize(
    "template,slots",
    [
        ("bullet_box", BulletBoxSlots(conclusion="결론")),
        ("summary", SummarySlots(conclusion="결론")),
        ("table", TableSlots(columns=["a"], rows=[["b"]])),
        ("compare2", CompareSlots(left=Card(heading="좌"), right=Card(heading="우"), conclusion="결론")),
    ],
)
def test_long_topic_warns_title_overflow(template, slots):
    long_topic = "제목 영역 한 줄을 확실히 넘기기 위한 매우 길고 긴 장 제목 문장이며 계속 이어진다" * 2
    chapter = Chapter(id="c1", topic=long_topic, template=template)
    slide = _plan_for(chapter, slots)
    assert "title" in _warned_slots(slide)


def test_short_topic_no_title_warning():
    chapter = Chapter(id="c1", topic="짧은 제목", template="bullet_box")
    slide = _plan_for(chapter, BulletBoxSlots(conclusion="결론"))
    assert "title" not in _warned_slots(slide)


def test_long_footnote_warns_on_bullet_box_and_table():
    long_footnote = "출처와 기준 시점을 장황하게 설명하는 각주 문장 " * 12
    chapter_b = Chapter(id="c1", topic="주제", template="bullet_box")
    slide_b = _plan_for(chapter_b, BulletBoxSlots(conclusion="결론", footnote=long_footnote))
    assert "footnote" in _warned_slots(slide_b)

    chapter_t = Chapter(id="c2", topic="주제", template="table")
    slide_t = _plan_for(chapter_t, TableSlots(columns=["a"], rows=[["b"]], footnote=long_footnote))
    assert "footnote" in _warned_slots(slide_t)


def _deck_with(template: str, slots: dict) -> Deck:
    return Deck(
        meta=DeckMeta(title="줄바꿈 테스트"),
        structure=Structure(chapters=[Chapter(id="c1", topic="주제", template=template)]),
        slides=[Slide(chapter_id="c1", slots={"template": template, **slots})],
    )


def _plan_frame(plan, suffix: str):
    return next(f for f in plan.slides[0].frames if f.name.endswith(suffix))


def test_para_lines_match_engine_breaks():
    long_text = ("가나다라마 " * 30).strip()
    plan = build_render_plan(
        _deck_with("bullet_box", {"bullets": [{"text": long_text}], "conclusion": "결론"}),
        Preset(), METRICS,
    )
    para = _plan_frame(plan, ":bullets").paras[0]
    assert len(para.lines) >= 2  # 긴 문장은 여러 줄로 갈라진다
    assert " ".join(para.lines) == para.text  # 줄 결합이 원문을 보존한다

def test_short_para_has_single_line():
    plan = build_render_plan(
        _deck_with("bullet_box", {"bullets": [{"text": "짧다"}], "conclusion": "결론"}),
        Preset(), METRICS,
    )
    assert _plan_frame(plan, ":bullets").paras[0].lines == ["짧다"]
    assert _plan_frame(plan, ":title").paras[0].lines == ["주제"]
    assert _plan_frame(plan, ":conclusion").paras[0].lines == ["결론"]

def test_cover_and_divider_paras_have_lines():
    cover = build_render_plan(
        _deck_with("cover", {"title": "표지 제목", "subtitle": "부제"}), Preset(), METRICS
    )
    assert _plan_frame(cover, ":cover_title").paras[0].lines == ["표지 제목"]
    divider = build_render_plan(
        _deck_with("divider", {"section_no": "1", "section_title": "간지 제목"}), Preset(), METRICS
    )
    assert _plan_frame(divider, ":section_title").paras[0].lines == ["간지 제목"]

def test_table_plan_carries_cell_lines():
    long_cell = ("항목 설명 " * 30).strip()
    plan = build_render_plan(
        _deck_with("table", {"columns": ["구분", "내용"], "rows": [["A", long_cell]]}),
        Preset(), METRICS,
    )
    tp = _plan_frame(plan, ":table").table
    assert len(tp.header_lines) == 2 and tp.header_lines[0] == ["구분"]
    assert len(tp.cell_lines) == 1 and len(tp.cell_lines[0]) == 2
    assert len(tp.cell_lines[0][1]) >= 2  # 긴 칸은 여러 줄
    # 행 높이는 줄수에서 계산된 기존 값과 정합해야 한다
    from slidecaptain.metrics.capacity import line_height_pt
    lh = line_height_pt(tp.font_pt, Preset().spacing.line_spacing)
    expected = max(len(c) for c in tp.cell_lines[0]) * lh + 2 * Preset().spacing.table_cell_pad_y
    assert abs(tp.row_heights_pt[1] - expected) < 0.01


def test_long_card_heading_warns_on_compare2():
    # 실측 근거(2026-08-28): 카드 소제목 예산은 388.0pt(카드 내부 폭 400pt x safety 0.97)이고
    # 아래 문자열은 볼드 12pt로 약 728pt(1회 364pt의 2배)라 확실히 2줄이 된다.
    # 1회만 쓰면 364pt로 1줄에 들어가 경고가 나지 않는다 (적대 리뷰가 실측으로 확인한 함정)
    long_heading = "카드 소제목 영역 한 줄을 넘기기 위한 매우 긴 소제목 문구가 계속 이어진다 " * 2
    chapter = Chapter(id="c1", topic="주제", template="compare2")
    slide = _plan_for(chapter, CompareSlots(
        left=Card(heading=long_heading), right=Card(heading="짧음"), conclusion="결론",
    ))
    assert "left_card_heading" in _warned_slots(slide)
    assert "right_card_heading" not in _warned_slots(slide)


def test_cover_presenter_is_rendered_from_meta():
    # 표지의 보고자는 슬롯이 아니라 메타에서 그린다 (장 제목을 chapter.topic에서 그리는 것과 같은 선례). 파일럿 관찰 6, 2026-09-01
    from slidecaptain.models.deck import Deck as _Deck, DeckMeta as _Meta, Slide as _Slide, Structure as _Structure

    deck = _Deck(
        meta=_Meta(title="보고 제목", presenter="사업개발팀", audience="경영진"),
        structure=_Structure(chapters=[Chapter(id="c0", topic="표지", template="cover")]),
        slides=[_Slide(chapter_id="c0", slots=CoverSlots(title="보고 제목", date="2026-09-01"))],
    )
    plan = build_render_plan(deck, PRESET, FAKE)
    frames = {f.name: f for f in plan.slides[0].frames}
    assert frames["c0:presenter"].paras[0].text == "사업개발팀"
    assert not any(n.endswith(":audience") for n in frames)
    assert "경영진" not in {p.text for f in plan.slides[0].frames for p in f.paras}


def test_frame_valign_accepts_only_top_and_middle():
    # 미리보기가 그릴 수 있는 값만 허용한다 (bottom 을 넣으면 라이터만 그리는 불일치가 생긴다. 2026-09-02 태스크 B)
    from pydantic import ValidationError

    from slidecaptain.models.render import Frame

    Frame(name="x:y", x=0, y=0, w=10, h=10, valign="middle")
    with pytest.raises(ValidationError):
        Frame(name="x:y", x=0, y=0, w=10, h=10, valign="bottom")
    with pytest.raises(ValidationError):
        Frame(name="x:y", x=0, y=0, w=10, h=10, valign="center")
