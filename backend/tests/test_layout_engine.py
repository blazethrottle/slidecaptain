import pytest

from slidecaptain.layout.engine import build_render_plan
from slidecaptain.metrics.font_metrics import FontMetrics
from slidecaptain.models.deck import (
    Bullet,
    BulletBoxSlots,
    CalloutSlots,
    Card,
    CardItem,
    CardsSlots,
    Chapter,
    CompareSlots,
    CoverSlots,
    Deck,
    DeckMeta,
    DividerSlots,
    MatrixRow,
    MatrixSlots,
    ProcessSlots,
    ProcessStep,
    Slide,
    Structure,
    SummarySlots,
    TableSlots,
)
from slidecaptain.models.preset import Preset, apply_overrides

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


@pytest.mark.parametrize("n_cols", [5, 15, 20, 40])
def test_table_column_widths_stay_positive_with_many_columns(n_cols):
    # 열이 많아지면 최소 폭 보정의 초과분이 한 열에서만 빠져 음수가 났다 (실측 n=40 -> -1480pt)
    deck = _deck(
        [
            (
                "table",
                TableSlots(
                    columns=[f"열{i}" for i in range(n_cols)],
                    rows=[[f"값{i}" for i in range(n_cols)]],
                ),
            )
        ]
    )
    plan = build_render_plan(deck, PRESET, FAKE)
    widths = _frame(plan.slides[0], ":table").table.col_widths_pt
    assert len(widths) == n_cols
    assert all(w > 0 for w in widths)
    assert sum(widths) == pytest.approx(860.0, abs=1e-6)


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
    # 슬롯도 없고 템플릿도 하나인 최소 경우다. 전 템플릿과 공통 슬롯 조합에서 같은 규칙이
    # 지켜지는지는 test_common_slots.py 가 본다 (2026-09-07: 이 테스트만 있을 때 계획서가
    # 위험으로 예고한 "아이브로우와 부제가 함께 쓰이면 3단계" 가 실제로 검사되지 않았다)
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


# ---- 표지와 간지 넘침 경고 (2026-09-02 Critical 묶음 태스크 C) ----
# 다른 템플릿의 제목, 각주, 카드 소제목은 _fixed_height_warning 으로 잡는데 표지와 간지만 경고 함수가 없어
# 제목이 4줄이어도 경고 0건이었다. 자동 맞춤을 꺼 두었으므로 PowerPoint 에서 글자가 상자 밖으로 흘러넘쳤다.


def test_cover_multiline_title_and_subtitle_warn():
    deck = _deck([("cover", CoverSlots(
        title=" ".join(["가" * 25] * 4), subtitle=" ".join(["가" * 55] * 3), date="2026-09-02"))])
    slide = build_render_plan(deck, PRESET, METRICS).slides[0]
    assert {w.slot for w in slide.warnings} == {"cover_title", "subtitle"}


def test_cover_single_line_fields_do_not_warn():
    deck = _deck([("cover", CoverSlots(title="시장 진입 검토", subtitle="부제", date="2026-09-02"))])
    deck.meta.presenter = "사업개발팀"
    assert build_render_plan(deck, PRESET, METRICS).slides[0].warnings == []


def test_divider_multiline_title_warns():
    deck = _deck([("divider", DividerSlots(section_no="1", section_title=" ".join(["가" * 30] * 4)))])
    slide = build_render_plan(deck, PRESET, METRICS).slides[0]
    assert {w.slot for w in slide.warnings} == {"section_title"}


# ---- 강조 밴드(callout) 프레임 (2026-09-07 DB-1) ----
# 벤치마크 원형 2: 전폭 둥근 사각형에 문장 1~3줄. 좌표는 content_top=92, content_bottom=474
# (기본 프리셋)에서 84pt 밴드를 세로 가운데(241.0)에 둔 값이다 (capacity.callout_geometry와 공유).


def test_callout_frame_geometry_and_fill():
    deck = _deck([("callout", CalloutSlots(text="핵심 메시지", tone="accent1"))])
    plan = build_render_plan(deck, PRESET, FAKE)
    band = _frame(plan.slides[0], ":text")
    assert (band.x, band.y, band.w, band.h) == (50.0, 241.0, 860.0, 84.0)
    assert band.radius_pt == 12.0
    assert band.fill == "0E8C7F"
    assert band.valign == "middle"


def test_callout_frame_names_carry_role_tags():
    deck = _deck([("callout", CalloutSlots(text="핵심 메시지"))])
    plan = build_render_plan(deck, PRESET, FAKE)
    names = {f.name for f in plan.slides[0].frames}
    assert names == {"ch01:title", "ch01:text", "ch01:page_number"}


def test_callout_default_tone_is_surface1():
    assert CalloutSlots(text="기본값 확인").tone == "surface1"


@pytest.mark.parametrize(
    ("tone", "expected_color"),
    [
        ("ink", "FFFFFF"),  # 아주 어두운 채움: 밝은 글자
        ("surface1", "202020"),  # 아주 밝은 채움(기본값): 어두운 글자
        ("accent2", "202020"),  # 어두운 쪽이 근소하게 대비가 더 크다 (5.33 대 3.06)
        ("accent1", "FFFFFF"),  # 밝은 쪽이 근소하게 대비가 더 크다 (4.14 대 3.94), 둘 다 AA 미달
    ],
)
def test_callout_text_color_follows_fill_luminance_not_a_fixed_role_map(tone, expected_color):
    """역할 이름 대 글자색의 고정 매핑표를 쓰지 않는다: 실제 색값의 대비로 판단해야 한다."""

    deck = _deck([("callout", CalloutSlots(text="핵심 메시지", tone=tone))])
    plan = build_render_plan(deck, PRESET, FAKE)
    band = _frame(plan.slides[0], ":text")
    assert band.paras[0].color == expected_color


def test_callout_text_color_recomputes_when_preset_colors_change():
    """고정 매핑표라면 프리셋이 바뀌어도 이전 판정을 그대로 돌려준다: 그렇지 않은지 확인한다."""

    overridden = apply_overrides(PRESET, {"colors": {"ink": "F5F5F5"}})  # 원래 어두운 ink를 밝게 덮어쓴다
    deck = _deck([("callout", CalloutSlots(text="핵심 메시지", tone="ink"))])
    plan = build_render_plan(deck, overridden, FAKE)
    band = _frame(plan.slides[0], ":text")
    assert band.fill == "F5F5F5"
    assert band.paras[0].color == "202020"  # 원래 매핑(ink -> 밝은 글자)이었다면 FFFFFF가 나왔을 값


def test_callout_overflow_warns_on_the_text_slot():
    long_text = "밴드 문장이 지나치게 길어서 고정 높이를 넘는다 " * 20
    deck = _deck([("callout", CalloutSlots(text=long_text))])
    plan = build_render_plan(deck, PRESET, METRICS).slides[0]
    assert any(w.slot == "text" for w in plan.warnings)


def test_callout_short_text_has_no_warning_and_single_line():
    deck = _deck([("callout", CalloutSlots(text="짧은 강조 문장"))])
    plan = build_render_plan(deck, PRESET, METRICS).slides[0]
    assert plan.warnings == []
    band = _frame(plan, ":text")
    assert band.paras[0].lines == ["짧은 강조 문장"]


# ---- 카드(cards) 프레임 (2026-09-07 DB-2) ----
# 벤치마크 원형: 배지(선택)/제목/본문 불릿/꼬리 라벨(선택)을 담은 카드 2~4개를 가로로 나열.


def _cards_deck(n: int, **card_kwargs) -> Deck:
    cards = [CardItem(heading=f"카드{i}", bullets=[Bullet(text=f"항목{i}")], **card_kwargs) for i in range(n)]
    return _deck([("cards", CardsSlots(cards=cards))])


@pytest.mark.parametrize("n", [2, 3, 4])
def test_cards_frames_do_not_overlap_and_span_the_content_width(n):
    # 카드 사이에는 compare2의 두 카드처럼 card_gap(기본 20pt)만큼의 간격이 있다: 딱 붙지 않는다.
    plan = build_render_plan(_cards_deck(n), PRESET, FAKE)
    cards = [_frame(plan.slides[0], f":card{i}") for i in range(n)]
    for a, b in zip(cards, cards[1:]):
        assert a.x + a.w == pytest.approx(b.x - PRESET.spacing.card_gap), "카드 사이 간격이 card_gap이 아니다"
        assert a.x + a.w <= b.x, "카드가 겹친다"
    assert cards[0].x == 50.0  # margin_left
    assert cards[-1].x + cards[-1].w == pytest.approx(50.0 + 860.0)  # margin_left + content_width
    assert all(c.y == cards[0].y for c in cards), "카드 높이(y)는 카드 수와 무관하게 같아야 한다"
    assert all(c.h == cards[0].h for c in cards)


def test_cards_frame_names_carry_role_tags():
    plan = build_render_plan(_cards_deck(2), PRESET, FAKE)
    names = {f.name for f in plan.slides[0].frames}
    assert names == {"ch01:title", "ch01:card0", "ch01:card1", "ch01:page_number"}


def test_cards_emphasis_card_gets_dark_fill_and_accent_border_not_thicker_border():
    deck = _deck([(
        "cards",
        CardsSlots(cards=[
            CardItem(heading="강조", bullets=[Bullet(text="가")], emphasis=True),
            CardItem(heading="보통", bullets=[Bullet(text="나")], emphasis=False),
        ]),
    )])
    plan = build_render_plan(deck, PRESET, FAKE)
    emphasized = _frame(plan.slides[0], ":card0")
    plain = _frame(plan.slides[0], ":card1")
    assert emphasized.fill == PRESET.colors.ink
    assert emphasized.border == PRESET.colors.accent1
    assert plain.fill is None
    assert plain.border == PRESET.colors.rule
    # 계획서 명시: 강조는 굵기가 아니라 색으로 구분한다 (border_width_pt는 둘 다 명시하지 않는다)
    assert emphasized.border_width_pt is None
    assert plain.border_width_pt is None


def test_cards_emphasis_card_text_is_readable_on_the_dark_fill():
    deck = _deck([(
        "cards",
        CardsSlots(cards=[
            CardItem(badge="신규", heading="강조", tail="자세히", bullets=[Bullet(text="가")], emphasis=True),
            CardItem(heading="보통", bullets=[Bullet(text="나")]),
        ]),
    )])
    plan = build_render_plan(deck, PRESET, FAKE)
    emphasized = _frame(plan.slides[0], ":card0")
    plain = _frame(plan.slides[0], ":card1")
    assert emphasized.paras, "배지/제목/불릿/꼬리 문단이 있어야 한다"
    assert all(p.color != PRESET.colors.text for p in emphasized.paras)
    assert all(p.color == PRESET.colors.text for p in plain.paras)


def test_cards_badge_and_tail_are_optional_and_add_exactly_one_para_each():
    deck = _deck([(
        "cards",
        CardsSlots(cards=[
            CardItem(badge="신규", heading="A", tail="자세히", bullets=[Bullet(text="가")]),
            CardItem(heading="B", bullets=[Bullet(text="나")]),
        ]),
    )])
    plan = build_render_plan(deck, PRESET, FAKE)
    with_both = _frame(plan.slides[0], ":card0")
    without = _frame(plan.slides[0], ":card1")
    assert len(with_both.paras) == len(without.paras) + 2


def test_cards_badge_overflow_warns_only_that_cards_badge_slot():
    long_badge = "배지 문구가 지나치게 길어서 한 줄 높이를 넘긴다 " * 6
    deck = _deck([(
        "cards",
        CardsSlots(cards=[
            CardItem(badge=long_badge, heading="A", bullets=[Bullet(text="가")]),
            CardItem(heading="B", bullets=[Bullet(text="나")]),
        ]),
    )])
    plan = build_render_plan(deck, PRESET, METRICS).slides[0]
    assert "card0_badge" in _warned_slots(plan)
    assert "card1_badge" not in _warned_slots(plan)


# ---- 번호 단계(process) 프레임 (2026-09-07 DB-3) ----
# 벤치마크가 요구한 "플로우차트"의 실제 형태: 번호 배지 + 제목 + 부제(선택) + 오른쪽 보조
# 라벨(선택, 최대 2개)을 담은 행 3~6개를 세로로 쌓는다. 번호는 데이터가 아니라 렌더 순서에서
# 나온다.


def _process_deck(n: int, **step_kwargs) -> Deck:
    steps = [ProcessStep(heading=f"단계{i}", **step_kwargs) for i in range(n)]
    return _deck([("process", ProcessSlots(steps=steps))])


@pytest.mark.parametrize("n", [3, 4, 5, 6])
def test_process_rows_do_not_overlap_and_stay_within_the_content_area(n):
    from slidecaptain.metrics.capacity import content_geometry, process_geometry

    plan = build_render_plan(_process_deck(n), PRESET, FAKE)
    slide = plan.slides[0]
    g = content_geometry(PRESET)
    rows = [_frame(slide, f":step{i}") for i in range(n)]
    for row in rows:
        assert row.y >= g["content_top"] - 0.01
        assert row.y + row.h <= g["content_bottom"] + 0.01
    for a, b in zip(rows, rows[1:]):
        assert a.y + a.h <= b.y + 0.01, "행이 겹친다"
    # 배지는 그 행의 텍스트 블록보다 왼쪽에 있고, 세로로는 그 행의 범위 안에 있다
    for i in range(n):
        badge = _frame(slide, f":step{i}_badge")
        text = rows[i]
        assert badge.x + badge.w <= text.x + 0.01, "배지가 제목 블록과 겹친다"
        assert badge.y >= text.y - 0.01
        assert badge.y + badge.h <= text.y + text.h + 0.01
    # 기하 함수 자체도 배지/제목/라벨 세 칸이 겹치지 않고 본문 폭 전체에 걸친다
    pg = process_geometry(PRESET, n)
    assert pg["badge_x"] == pytest.approx(PRESET.spacing.margin_left)
    assert pg["badge_x"] + PRESET.spacing.process_badge_size <= pg["text_x"] + 0.01
    assert pg["text_x"] + pg["text_w"] <= pg["label_x"] + 0.01
    assert pg["label_x"] + pg["label_w"] == pytest.approx(PRESET.spacing.margin_left + g["content_width"])


def test_process_row_height_shrinks_as_step_count_grows():
    three = _frame(build_render_plan(_process_deck(3), PRESET, FAKE).slides[0], ":step0")
    six = _frame(build_render_plan(_process_deck(6), PRESET, FAKE).slides[0], ":step0")
    assert three.h > six.h


def test_process_badge_radius_gives_the_pill_adjustment_of_half():
    """번호 배지는 정사각형이고 반경이 짧은 변의 절반이라 라이터의 조정값이 정확히 0.5가
    되어야 정원으로 그려진다 (DA-1: 조정값 0.5가 알약과 정원이 나오는 상한)."""
    from slidecaptain.export.pptx_writer import _corner_adjustment

    plan = build_render_plan(_process_deck(4), PRESET, FAKE)
    for i in range(4):
        badge = _frame(plan.slides[0], f":step{i}_badge")
        assert badge.w == badge.h
        assert _corner_adjustment(badge) == pytest.approx(0.5)


def test_process_badge_numbers_come_from_render_order_not_from_data():
    plan = build_render_plan(_process_deck(4), PRESET, FAKE)
    slide = plan.slides[0]
    numbers = [_frame(slide, f":step{i}_badge").paras[0].text for i in range(4)]
    assert numbers == ["1", "2", "3", "4"]


def test_process_frame_names_carry_role_tags_and_omit_labels_when_no_notes():
    plan = build_render_plan(_process_deck(3), PRESET, FAKE)
    names = {f.name for f in plan.slides[0].frames}
    assert names == {
        "ch01:title",
        "ch01:step0_badge", "ch01:step0",
        "ch01:step1_badge", "ch01:step1",
        "ch01:step2_badge", "ch01:step2",
        "ch01:page_number",
    }


def test_process_subtitle_and_notes_are_optional():
    deck = _deck([(
        "process",
        ProcessSlots(steps=[
            ProcessStep(heading="A", subtitle="부제", notes=["라벨1", "라벨2"]),
            ProcessStep(heading="B"),
            ProcessStep(heading="C"),
        ]),
    )])
    plan = build_render_plan(deck, PRESET, FAKE)
    slide = plan.slides[0]
    with_subtitle = _frame(slide, ":step0")
    without_subtitle = _frame(slide, ":step1")
    assert len(with_subtitle.paras) == len(without_subtitle.paras) + 1  # 부제 문단 하나만 늘어난다
    names = {f.name for f in slide.frames}
    assert "ch01:step0_labels" in names
    assert "ch01:step1_labels" not in names
    assert "ch01:step2_labels" not in names
    labels = _frame(slide, ":step0_labels")
    assert [p.text for p in labels.paras] == ["라벨1", "라벨2"]


def test_process_heading_overflow_warns_only_that_step_heading_slot():
    long_heading = "단계 제목이 지나치게 길어서 한 줄 높이를 넘긴다 " * 6
    deck = _deck([(
        "process",
        ProcessSlots(steps=[
            ProcessStep(heading=long_heading),
            ProcessStep(heading="짧음"),
            ProcessStep(heading="셋째"),
        ]),
    )])
    plan = build_render_plan(deck, PRESET, METRICS).slides[0]
    assert "step0_heading" in _warned_slots(plan)
    assert "step1_heading" not in _warned_slots(plan)


def test_process_label_overflow_warns_only_that_steps_label_slot():
    long_label = "보조 라벨 문구가 지나치게 길어서 한 줄 높이를 넘긴다 " * 6
    deck = _deck([(
        "process",
        ProcessSlots(steps=[
            ProcessStep(heading="A", notes=[long_label]),
            ProcessStep(heading="B", notes=["짧음"]),
            ProcessStep(heading="C"),
        ]),
    )])
    plan = build_render_plan(deck, PRESET, METRICS).slides[0]
    # 라벨 프레임 slot은 복수형("step0_labels")이라, 경고 slot도 그 접두어를 따라야
    # Preview.tsx의 isWarned()가 프레임을 찾아낸다 (DB-3 리뷰 발견 1)
    assert "step0_labels_0" in _warned_slots(plan)
    assert "step1_labels_0" not in _warned_slots(plan)


def test_process_label_overflow_warning_slot_matches_its_frame_for_preview_highlighting():
    """Preview.tsx의 isWarned(slide, slot)은 `w.slot === slot || w.slot.startsWith(`${slot}_`)`로
    경고를 프레임에 매칭한다. 라벨 넘침 경고의 slot이 라벨 프레임 자신의 slot과 이 규약을
    지키지 않으면, 경고 메시지는 떠도 편집 화면에서 그 프레임에 빨간 강조가 뜨지 않는다
    (DB-3 리뷰 발견 1: frontend/src/editor/Preview.tsx:16, 이전에는 어떤 테스트도 이 접점을
    검증하지 않았다). 파이썬으로 그 매칭 규칙을 그대로 재현해 계약을 고정한다."""
    long_label = "보조 라벨 문구가 지나치게 길어서 한 줄 높이를 넘긴다 " * 6
    deck = _deck([(
        "process",
        ProcessSlots(steps=[
            ProcessStep(heading="A", notes=[long_label, "짧음"]),
            ProcessStep(heading="B"),
            ProcessStep(heading="C"),
        ]),
    )])
    slide = build_render_plan(deck, PRESET, METRICS).slides[0]
    labels_frame = _frame(slide, ":step0_labels")
    frame_slot = labels_frame.name.split(":", 1)[1]
    label_warnings = [w for w in slide.warnings if w.slot.startswith("step0_label")]
    assert label_warnings, "넘침 경고가 최소 1개는 있어야 이 계약을 검증할 수 있다"
    for w in label_warnings:
        assert w.slot == frame_slot or w.slot.startswith(f"{frame_slot}_"), (
            f"경고 slot {w.slot!r}이 프레임 slot {frame_slot!r}과 매칭되지 않아 "
            "Preview에서 강조가 뜨지 않는다"
        )


# ---- 행렬(matrix) 프레임 (2026-09-07 DB-4) ----
# 왼쪽 분류 셀(채움 블록, 항상 있음)/가운데 대표 항목(선택)/오른쪽 나열(선택)을 담은 행
# 3~6개를 세로로 쌓는다. process처럼 칸마다 가로 위치가 달라 프레임 셋으로 나뉜다. 표와
# 다른 점은 deck.py MatrixRow 주석 참고: 표는 열 이름이 있는 균일한 격자이고 matrix는
# 분류축이 왼쪽에 고정된 행 나열이다.


def _matrix_deck(n: int, **row_kwargs) -> Deck:
    rows = [MatrixRow(category=f"분류{i}", **row_kwargs) for i in range(n)]
    return _deck([("matrix", MatrixSlots(rows=rows))])


@pytest.mark.parametrize("n", [3, 4, 5, 6])
def test_matrix_rows_do_not_overlap_and_stay_within_the_content_area(n):
    from slidecaptain.metrics.capacity import content_geometry, matrix_geometry

    plan = build_render_plan(_matrix_deck(n), PRESET, FAKE)
    slide = plan.slides[0]
    g = content_geometry(PRESET)
    rows = [_frame(slide, f":row{i}_category") for i in range(n)]
    for row in rows:
        assert row.y >= g["content_top"] - 0.01
        assert row.y + row.h <= g["content_bottom"] + 0.01
    for a, b in zip(rows, rows[1:]):
        assert a.y + a.h <= b.y + 0.01, "행이 겹친다"
    # 기하 함수 자체도 분류/대표/나열 세 칸이 겹치지 않고 본문 폭 전체에 걸친다
    mg = matrix_geometry(PRESET, n)
    assert mg["category_x"] == pytest.approx(PRESET.spacing.margin_left)
    assert mg["category_x"] + PRESET.spacing.matrix_category_width <= mg["primary_x"] + 0.01
    assert mg["primary_x"] + mg["primary_w"] <= mg["items_x"] + 0.01
    assert mg["items_x"] + mg["items_w"] == pytest.approx(PRESET.spacing.margin_left + g["content_width"])


def test_matrix_row_height_shrinks_as_row_count_grows():
    three = _frame(build_render_plan(_matrix_deck(3), PRESET, FAKE).slides[0], ":row0_category")
    six = _frame(build_render_plan(_matrix_deck(6), PRESET, FAKE).slides[0], ":row0_category")
    assert three.h > six.h


def test_matrix_category_gets_a_filled_block_with_readable_text_color():
    """분류 셀은 색 역할로 채우고 글자색은 DB-1의 휘도 판단 함수로 다시 고른다 (계획서 명시)."""
    from slidecaptain.metrics.color import readable_text_color

    plan = build_render_plan(_matrix_deck(3), PRESET, FAKE)
    expected = readable_text_color(PRESET.colors.accent1, light=PRESET.colors.background, dark=PRESET.colors.text)
    for i in range(3):
        cell = _frame(plan.slides[0], f":row{i}_category")
        assert cell.fill == PRESET.colors.accent1
        assert cell.paras[0].color == expected


def test_matrix_frame_names_carry_role_tags_when_optional_columns_are_empty():
    plan = build_render_plan(_matrix_deck(3), PRESET, FAKE)
    names = {f.name for f in plan.slides[0].frames}
    assert names == {
        "ch01:title",
        "ch01:row0_category", "ch01:row1_category", "ch01:row2_category",
        "ch01:page_number",
    }


def test_matrix_primary_and_items_are_optional_and_add_their_own_frames_when_present():
    deck = _deck([(
        "matrix",
        MatrixSlots(rows=[
            MatrixRow(category="강점", primary="빠른 실행", items=["항목1", "항목2"]),
            MatrixRow(category="약점"),
            MatrixRow(category="기회"),
        ]),
    )])
    plan = build_render_plan(deck, PRESET, FAKE)
    names = {f.name for f in plan.slides[0].frames}
    assert "ch01:row0_primary" in names
    assert "ch01:row0_items" in names
    assert "ch01:row1_primary" not in names
    assert "ch01:row1_items" not in names
    assert "ch01:row2_primary" not in names
    assert "ch01:row2_items" not in names


def test_matrix_items_render_as_a_bulleted_list_in_render_order():
    deck = _deck([(
        "matrix",
        MatrixSlots(rows=[
            MatrixRow(category="강점", items=["항목A", "항목B", "항목C"]),
            MatrixRow(category="약점"),
            MatrixRow(category="기회"),
        ]),
    )])
    plan = build_render_plan(deck, PRESET, FAKE)
    items_frame = _frame(plan.slides[0], ":row0_items")
    assert [p.text for p in items_frame.paras] == ["항목A", "항목B", "항목C"]
    assert all(p.bullet for p in items_frame.paras)


def test_matrix_category_overflow_warns_only_that_rows_category_slot():
    long_category = "분류 이름이 지나치게 길어서 셀 높이를 넘긴다 " * 6
    deck = _deck([(
        "matrix",
        MatrixSlots(rows=[
            MatrixRow(category=long_category),
            MatrixRow(category="짧음"),
            MatrixRow(category="셋째"),
        ]),
    )])
    plan = build_render_plan(deck, PRESET, METRICS).slides[0]
    assert "row0_category" in _warned_slots(plan)
    assert "row1_category" not in _warned_slots(plan)


def test_matrix_items_overflow_warning_slot_matches_its_frame_for_preview_highlighting():
    """DB-3 리뷰 발견 1과 같은 계열의 위험: 나열 넘침 경고의 slot이 나열 프레임 자신의
    slot("row0_items")과 이 규약(`w.slot === slot || w.slot.startsWith(`${slot}_`)`)을
    지키지 않으면 경고 메시지는 떠도 편집 화면에서 그 프레임에 빨간 강조가 뜨지 않는다."""
    many_items = [f"항목{i}" for i in range(30)]
    deck = _deck([(
        "matrix",
        MatrixSlots(rows=[
            MatrixRow(category="강점", items=many_items),
            MatrixRow(category="약점"),
            MatrixRow(category="기회"),
        ]),
    )])
    slide = build_render_plan(deck, PRESET, METRICS).slides[0]
    items_frame = _frame(slide, ":row0_items")
    frame_slot = items_frame.name.split(":", 1)[1]
    item_warnings = [w for w in slide.warnings if w.slot.startswith("row0_items")]
    assert item_warnings, "넘침 경고가 최소 1개는 있어야 이 계약을 검증할 수 있다"
    for w in item_warnings:
        assert w.slot == frame_slot or w.slot.startswith(f"{frame_slot}_"), (
            f"경고 slot {w.slot!r}이 프레임 slot {frame_slot!r}과 매칭되지 않아 "
            "Preview에서 강조가 뜨지 않는다"
        )
