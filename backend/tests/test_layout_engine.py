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
            ("cover", CoverSlots(title="보고 제목", subtitle="부제", date="2026-08-27", audience="보고 대상")),
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
