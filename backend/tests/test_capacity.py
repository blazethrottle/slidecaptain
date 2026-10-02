import pytest

from slidecaptain.metrics.capacity import (
    BulletsMeasure,
    capacity_contract,
    line_height_pt,
    max_lines,
    measure_bullets,
    measure_lines,
)
from slidecaptain.metrics.font_metrics import FontMetrics
from slidecaptain.models.deck import Bullet
from slidecaptain.models.preset import Preset


class FakeFace:
    def width_pt(self, text: str, font_pt: float) -> float:
        return len(text) * font_pt


FAKE = FakeFace()
PRESET = Preset()


def test_line_height():
    assert line_height_pt(12.0, 1.4) == pytest.approx(16.8)


def test_max_lines_floor():
    # 318pt 영역, 12pt 본문, 행간 1.4 → 16.8pt/줄 → 18줄
    assert max_lines(318.0, 12.0, 1.4) == 18


def test_measure_lines_single_paragraph():
    # 폭 120pt, 여유율 0.97 → 실효 116.4pt, 글자당 12pt → 9글자/줄
    assert measure_lines("가나다라마바사아자", 120.0, 12.0, FAKE, PRESET.spacing) == 1
    assert measure_lines("가나다라마바사아자차", 120.0, 12.0, FAKE, PRESET.spacing) == 2


def test_measure_bullets_heights_and_gaps():
    # 폭 120pt, 글자당 12pt, 들여쓰기 18pt → 실효 폭 102pt에 여유율 → 8글자/줄
    bullets = [Bullet(text="가나다라마바사아"), Bullet(text="하나 둘")]  # 1줄 + 1줄
    m = measure_bullets(bullets, 120.0, 12.0, FAKE, PRESET.spacing)
    assert isinstance(m, BulletsMeasure)
    assert m.lines_per_bullet == [1, 1]
    # 16.8*2 + 불릿 간격 6 = 39.6
    assert m.total_height_pt == pytest.approx(2 * 16.8 + 6.0)


def test_measure_bullets_wrapping_counts_lines():
    # 9글자 → 실효 폭 8글자 기준 2줄
    bullets = [Bullet(text="가나다라마바사아자")]
    m = measure_bullets(bullets, 120.0, 12.0, FAKE, PRESET.spacing)
    assert m.lines_per_bullet == [2]


def test_level1_bullet_gets_deeper_indent():
    # level 1은 들여쓰기 2배 → 실효 폭이 좁아져 같은 문장이 더 많은 줄을 차지한다
    text = "가나다라마바사아"
    flat = measure_bullets([Bullet(text=text, level=0)], 120.0, 12.0, FAKE, PRESET.spacing)
    deep = measure_bullets([Bullet(text=text, level=1)], 120.0, 12.0, FAKE, PRESET.spacing)
    assert deep.lines_per_bullet[0] >= flat.lines_per_bullet[0]


def test_capacity_contract_bullet_box():
    contract = capacity_contract("bullet_box", PRESET)
    # 기본 프리셋에서 불릿 영역 높이는 318pt. 한 줄짜리 불릿 사이마다 bullet_gap(6pt)이 들어가므로
    # floor((318 + 6) / (16.8 + 6)) = 14. 종전 기대값 18 은 간격을 빼지 않은 산식이라 실측과 어긋났다
    # (2026-09-02 Critical 묶음 태스크 A: 이 테스트는 산식만 검증해 결함을 잡지 못했다. 왕복 테스트는 아래)
    assert contract["bullets_max_lines"] == 14
    assert contract["conclusion_max_lines"] == 2
    assert contract["footnote_max_lines"] == 1


def test_capacity_contract_unknown_template():
    with pytest.raises(KeyError):
        capacity_contract("fancy_chart", PRESET)


def test_compare2_contract_includes_heading_limit():
    contract = capacity_contract("compare2", Preset())
    assert contract["card_heading_max_lines"] == 1


def test_hangul_chars_per_line_matches_bundle_metrics():
    # 불릿 폭 (860 - 들여쓰기 18)pt x safety 0.97 / (0.92em x 12pt) = 73.9... -> 73자 (번들 폭 실측 기준)
    # 종전 75 는 들여쓰기를 빼지 않아 안내대로 쓴 한 어절이 두 줄로 꺾였다 (2026-09-02 태스크 A)
    from slidecaptain.metrics.capacity import hangul_chars_per_line

    metrics = FontMetrics.load_default()
    assert hangul_chars_per_line(Preset(), metrics.face(False)) == 73


# ---- 계약 대 실측 왕복 (2026-09-02 Critical 묶음 태스크 A) ----
# 왜 기존 테스트가 잡지 못했나: 위의 계약 테스트는 capacity_contract 의 산식만, measure 테스트는 measure_bullets 만 검증했다.
# "계약대로 채우면 실측이 통과하는가" 를 잇는 테스트가 없어 계약이 불릿 간격(bullet_gap), 표 셀 여백(table_cell_pad_y),
# 카드 안쪽 여백(box_padding)을 빼지 않는 것을 놓쳤다. AI 가 계약을 지켜도 분량 게이트가 초과 경고를 내던 원인이다.
import math

from slidecaptain.layout.engine import build_render_plan
from slidecaptain.metrics.capacity import (
    callout_geometry,
    card_geometry,
    cards_geometry,
    char_hints,
    content_geometry,
    hangul_chars_per_line,
    matrix_geometry,
    process_geometry,
)
from slidecaptain.models.deck import (
    BulletBoxSlots,
    CalloutSlots,
    Card,
    CardItem,
    CardsSlots,
    Chapter,
    CompareSlots,
    Deck,
    DeckMeta,
    MatrixRow,
    MatrixSlots,
    ProcessSlots,
    ProcessStep,
    Slide,
    Structure,
    SummarySlots,
    TableSlots,
)
from slidecaptain.models.preset import apply_overrides

REAL = FontMetrics.load_default()
H = "가"


def _slide(template, slots, preset=PRESET):
    deck = Deck(
        meta=DeckMeta(title="t"),
        structure=Structure(chapters=[Chapter(id="c1", topic="주제", template=template)]),
        slides=[Slide(chapter_id="c1", slots=slots)],
    )
    return build_render_plan(deck, preset, REAL).slides[0]


def _slot_warnings(slide, slot):
    return [w for w in slide.warnings if w.slot == slot]


def test_contract_values_follow_measurement_rules():
    assert capacity_contract("bullet_box", PRESET)["bullets_max_lines"] == 14
    assert capacity_contract("summary", PRESET)["points_max_lines"] == 14
    assert capacity_contract("table", PRESET)["rows_max_single_line"] == 16
    assert capacity_contract("compare2", PRESET)["card_bullets_max_lines"] == 11


@pytest.mark.parametrize(
    ("template", "key", "slot", "make"),
    [
        ("bullet_box", "bullets_max_lines", "bullets",
         lambda n: BulletBoxSlots(bullets=[Bullet(text=f"항목{i}") for i in range(n)], conclusion="결론")),
        ("summary", "points_max_lines", "points",
         lambda n: SummarySlots(conclusion="결론", points=[Bullet(text=f"요점{i}") for i in range(n)])),
        ("compare2", "card_bullets_max_lines", "left_card",
         lambda n: CompareSlots(left=Card(heading="좌", bullets=[Bullet(text=f"항목{i}") for i in range(n)]),
                                right=Card(heading="우"), conclusion="결론")),
    ],
)
def test_contract_boundary_of_one_line_items_fits_and_plus_one_overflows(template, key, slot, make):
    n = capacity_contract(template, PRESET)[key]
    assert not _slot_warnings(_slide(template, make(n)), slot), "계약대로 채웠는데 넘침 경고가 났다"
    assert _slot_warnings(_slide(template, make(n + 1)), slot), "계약보다 하나 더 넣었는데 경고가 없다"


def test_table_contract_boundary_rows_fit_and_plus_one_overflows():
    n = capacity_contract("table", PRESET)["rows_max_single_line"]  # 머리글 포함 행 수

    def slots(k):
        return TableSlots(columns=["항목", "값"], rows=[[f"행{i}", "값"] for i in range(k - 1)])

    assert not _slot_warnings(_slide("table", slots(n)), "table")
    assert _slot_warnings(_slide("table", slots(n + 1)), "table")


def test_compare2_contract_and_template_share_card_geometry():
    # 계약과 레이아웃 엔진이 같은 카드 기하 함수를 쓴다: 종전에는 계약(286pt)이 카드 안쪽 여백을 빼지 않아 실측(266pt)과 달랐다
    geo = card_geometry(PRESET)
    assert geo["bullets_h"] == pytest.approx(266.0)
    lh = line_height_pt(PRESET.font_roles.body_pt, PRESET.spacing.line_spacing)
    gap = PRESET.spacing.bullet_gap
    expected = math.floor((geo["bullets_h"] + gap) / (lh + gap))
    assert capacity_contract("compare2", PRESET)["card_bullets_max_lines"] == expected


def test_contract_never_negative_with_large_padding():
    p2 = apply_overrides(PRESET, {"spacing": {"box_padding": 40.0}})
    for template in ("summary", "bullet_box", "table", "compare2", "cards"):
        assert min(capacity_contract(template, p2).values()) >= 0


def test_cover_and_divider_contracts_are_one_line_per_field():
    assert capacity_contract("cover", PRESET) == {
        "cover_title_max_lines": 1, "subtitle_max_lines": 1, "date_max_lines": 1,
    }
    assert capacity_contract("divider", PRESET) == {"section_no_max_lines": 1, "section_title_max_lines": 1}


def test_hinted_chars_fit_one_line_in_each_context():
    hints = char_hints("bullet_box", PRESET, REAL)
    assert hints == {"본문 한 줄": 73}
    s = _slide("bullet_box", BulletBoxSlots(bullets=[Bullet(text=H * 73)], conclusion="결론"))
    assert len(next(f for f in s.frames if f.name.endswith(":bullets")).paras[0].lines) == 1

    card = char_hints("compare2", PRESET, REAL)
    assert card == {"카드 안 한 줄": 33, "카드 소제목": 35}
    s = _slide("compare2", CompareSlots(left=Card(heading=H * 35, bullets=[Bullet(text=H * 33)]),
                                        right=Card(heading="우"), conclusion="결론"))
    left = next(f for f in s.frames if f.name.endswith(":left_card"))
    assert len(left.paras[0].lines) == 1 and len(left.paras[1].lines) == 1
    assert s.warnings == []

    assert char_hints("cover", PRESET, REAL) == {"표지 제목": 30, "부제": 60}
    assert char_hints("divider", PRESET, REAL) == {"섹션 제목": 35}
    assert char_hints("summary", PRESET, REAL) == {"본문 한 줄": 73}
    assert char_hints("table", PRESET, REAL) == {"본문 한 줄": 73}


# ---- 강조 밴드(callout) 용량 계약 (2026-09-07 DB-1) ----
# 밴드는 "문장 1~3줄"짜리 고정 높이라 계약 키는 하나뿐이다. 다른 템플릿처럼 계약과 실측 왕복을 붙인다.


def test_capacity_contract_callout():
    assert capacity_contract("callout", PRESET) == {"text_max_lines": 3}


def test_callout_geometry_is_full_width_and_vertically_centered_in_the_content_area():
    g = content_geometry(PRESET)
    band = callout_geometry(PRESET)
    assert band["band_h"] == PRESET.spacing.callout_height
    top_gap = band["band_y"] - g["content_top"]
    bottom_gap = g["content_bottom"] - (band["band_y"] + band["band_h"])
    assert top_gap == pytest.approx(bottom_gap)  # 세로 가운데: 위아래 남는 여백이 같다


def test_callout_char_hint_present_and_positive():
    hints = char_hints("callout", PRESET, REAL)
    assert set(hints) == {"밴드 안 한 줄"}
    assert hints["밴드 안 한 줄"] > 0


def test_callout_contract_boundary_of_lines_fits_and_plus_one_overflows():
    k = char_hints("callout", PRESET, REAL)["밴드 안 한 줄"]
    n = capacity_contract("callout", PRESET)["text_max_lines"]

    def slots(lines: int) -> CalloutSlots:
        return CalloutSlots(text=" ".join([H * k] * lines))

    assert not _slot_warnings(_slide("callout", slots(n)), "text"), "계약대로 채웠는데 넘침 경고가 났다"
    assert _slot_warnings(_slide("callout", slots(n + 1)), "text"), "계약보다 한 줄 더 넣었는데 경고가 없다"


# ---- 카드(cards) 용량 계약 (2026-09-07 DB-2) ----
# capacity_contract/char_hints에 card_count 인자가 늘었다: 카드 수에 따라 폭이 달라지고,
# 폭이 달라지면 카드 안 한 줄에 들어가는 글자 수(char_hints)가 달라진다. 높이 기반인
# card_bullets_max_lines 자체는 카드 수와 무관하다(한 행에 나란히 두므로 높이는 늘 본문
# 영역 전체다): 그래도 왕복 테스트는 2, 3, 4 각각에서 좌표 계산이 옳은지 검증한다.

def test_existing_seven_templates_contract_values_unchanged_by_cards_signature():
    """capacity_contract에 card_count 인자를 더해도 기존 7종(callout 포함) 계약은 그대로다."""
    assert capacity_contract("cover", PRESET) == {
        "cover_title_max_lines": 1, "subtitle_max_lines": 1, "date_max_lines": 1,
    }
    assert capacity_contract("divider", PRESET) == {
        "section_no_max_lines": 1, "section_title_max_lines": 1,
    }
    assert capacity_contract("summary", PRESET) == {"points_max_lines": 14, "conclusion_max_lines": 2}
    assert capacity_contract("bullet_box", PRESET) == {
        "bullets_max_lines": 14, "conclusion_max_lines": 2, "footnote_max_lines": 1,
    }
    assert capacity_contract("table", PRESET) == {"rows_max_single_line": 16, "footnote_max_lines": 1}
    assert capacity_contract("compare2", PRESET) == {
        "card_heading_max_lines": 1, "card_bullets_max_lines": 11, "conclusion_max_lines": 2,
    }
    assert capacity_contract("callout", PRESET) == {"text_max_lines": 3}


def test_cards_geometry_width_shrinks_as_card_count_grows_but_height_does_not():
    two = cards_geometry(PRESET, 2)
    three = cards_geometry(PRESET, 3)
    four = cards_geometry(PRESET, 4)
    assert two["card_w"] > three["card_w"] > four["card_w"]
    assert two["card_h"] == three["card_h"] == four["card_h"]
    # 컴페어2와 같은 산식이라 카드 2개일 때는 값도 같다 (compare2 카드폭 420.0, test_layout_engine.py 실측)
    assert two["card_w"] == pytest.approx(420.0)


def test_cards_geometry_widths_sum_to_content_width_for_every_valid_count():
    for n in (2, 3, 4):
        cg = cards_geometry(PRESET, n)
        assert n * cg["card_w"] + (n - 1) * PRESET.spacing.card_gap == pytest.approx(
            content_geometry(PRESET)["content_width"]
        )


def test_cards_char_hint_shrinks_as_card_count_grows():
    two = char_hints("cards", PRESET, REAL, card_count=2)
    four = char_hints("cards", PRESET, REAL, card_count=4)
    assert set(two) == {"카드 배지", "카드 소제목", "카드 안 한 줄", "카드 꼬리 라벨"}
    for key in two:
        assert two[key] > four[key], f"{key}: 카드가 늘어 폭이 좁아지면 한 줄 글자 수도 줄어야 한다"


def test_cards_contract_answers_without_card_count_argument():
    # capacity_contract("cards", PRESET) 처럼 card_count를 생략하는 기존 호출부(service.py)가
    # 죽지 않아야 한다: 기본값 2가 안전한 하한이다
    contract = capacity_contract("cards", PRESET)
    assert set(contract) == {
        "card_badge_max_lines", "card_heading_max_lines", "card_bullets_max_lines", "card_tail_max_lines",
    }
    assert all(v >= 0 for v in contract.values())


def _cards_slots(n: int, bullets_per_card: int, badge: str = "배지", tail: str = "꼬리") -> CardsSlots:
    return CardsSlots(cards=[
        CardItem(
            badge=badge, heading=f"카드{i}", tail=tail,
            bullets=[Bullet(text=f"항목{i}-{j}") for j in range(bullets_per_card)],
        )
        for i in range(n)
    ])


@pytest.mark.parametrize("card_count", [2, 3, 4])
def test_cards_contract_boundary_of_one_line_bullets_fits_and_plus_one_overflows(card_count):
    """카드 2, 3, 4개 각각에서 계약대로 채우면 실측이 통과하는지 (배지와 꼬리가 항상 있다고
    가정한 계약의 안전한 하한이므로, 실측도 배지와 꼬리를 채워야 경계가 정확히 맞는다)."""
    n = capacity_contract("cards", PRESET, card_count=card_count)["card_bullets_max_lines"]
    fits = _slide("cards", _cards_slots(card_count, n))
    assert not _slot_warnings(fits, "card0"), "계약대로 채웠는데 넘침 경고가 났다"
    overflows = _slide("cards", _cards_slots(card_count, n + 1))
    assert _slot_warnings(overflows, "card0"), "계약보다 하나 더 넣었는데 경고가 없다"


def test_cards_contract_never_negative_with_large_padding_across_counts():
    p2 = apply_overrides(PRESET, {"spacing": {"box_padding": 40.0}})
    for n in (2, 3, 4):
        assert min(capacity_contract("cards", p2, card_count=n).values()) >= 0


# ---- 번호 단계(process) 용량 계약 (2026-09-07 DB-3) ----
# cards는 카드 수가 늘면 폭이 좁아진다(가로 축). process는 단계가 전폭 행으로 세로로 쌓이므로
# 단계 수가 늘면 반대로 행 "높이"가 낮아진다(세로 축): capacity_contract/char_hints에 더한
# step_count 인자는 그래서 가로가 아니라 세로 용량에 영향을 준다. 배지/제목/라벨 칸의 가로
# 너비는 단계 수와 무관하므로 char_hints는 step_count가 바뀌어도 값이 그대로다: cards의
# char_hints가 card_count에 따라 줄어드는 것과 정확히 반대다.


def test_existing_eight_templates_contract_values_unchanged_by_process_signature():
    """capacity_contract에 step_count 인자를 더해도 기존 8종(cards 포함) 계약은 그대로다."""
    assert capacity_contract("cover", PRESET) == {
        "cover_title_max_lines": 1, "subtitle_max_lines": 1, "date_max_lines": 1,
    }
    assert capacity_contract("divider", PRESET) == {
        "section_no_max_lines": 1, "section_title_max_lines": 1,
    }
    assert capacity_contract("summary", PRESET) == {"points_max_lines": 14, "conclusion_max_lines": 2}
    assert capacity_contract("bullet_box", PRESET) == {
        "bullets_max_lines": 14, "conclusion_max_lines": 2, "footnote_max_lines": 1,
    }
    assert capacity_contract("table", PRESET) == {"rows_max_single_line": 16, "footnote_max_lines": 1}
    assert capacity_contract("compare2", PRESET) == {
        "card_heading_max_lines": 1, "card_bullets_max_lines": 11, "conclusion_max_lines": 2,
    }
    assert capacity_contract("callout", PRESET) == {"text_max_lines": 3}
    assert capacity_contract("cards", PRESET) == {
        "card_badge_max_lines": 1, "card_heading_max_lines": 1, "card_bullets_max_lines": 12,
        "card_tail_max_lines": 1,
    }


def test_process_geometry_row_height_shrinks_as_step_count_grows_but_x_fields_do_not():
    three = process_geometry(PRESET, 3)
    six = process_geometry(PRESET, 6)
    assert three["row_h"] > six["row_h"]
    assert three["badge_x"] == six["badge_x"]
    assert three["text_x"] == six["text_x"]
    assert three["text_w"] == six["text_w"]
    assert three["label_x"] == six["label_x"]
    assert three["label_w"] == six["label_w"]


def test_process_geometry_rows_span_the_content_height_for_every_valid_count():
    g = content_geometry(PRESET)
    content_h = g["content_bottom"] - g["content_top"]
    for n in (3, 4, 5, 6):
        pg = process_geometry(PRESET, n)
        assert n * pg["row_h"] + (n - 1) * pg["row_gap"] == pytest.approx(content_h)


def test_process_char_hint_is_independent_of_step_count():
    """가로 칸 너비는 단계 수와 무관하다: cards의 char_hints가 card_count로 줄어드는 것과 다르다."""
    three = char_hints("process", PRESET, REAL, step_count=3)
    six = char_hints("process", PRESET, REAL, step_count=6)
    assert set(three) == {"단계 제목", "단계 부제", "보조 라벨"}
    assert three == six


def test_process_contract_answers_without_step_count_argument():
    # capacity_contract("process", PRESET) 처럼 step_count를 생략하는 기존 호출부(service.py)가
    # 죽지 않아야 한다: 기본값 3이 안전하다
    contract = capacity_contract("process", PRESET)
    assert set(contract) == {"step_heading_max_lines", "step_subtitle_max_lines", "step_label_max_lines"}
    assert all(v >= 0 for v in contract.values())


def _process_slots(n: int, subtitle: str = "") -> ProcessSlots:
    return ProcessSlots(steps=[ProcessStep(heading=f"단계{i}", subtitle=subtitle) for i in range(n)])


@pytest.mark.parametrize("step_count", [3, 4, 5, 6])
def test_process_contract_boundary_of_subtitle_lines_fits_and_plus_one_overflows(step_count):
    """단계 3, 4, 5, 6개 각각에서 계약대로 부제를 채우면 실측이 통과하는지. 행이 낮아질수록
    (단계가 늘수록) 부제 상한도 함께 줄어야 한다(process_geometry의 row_h 축소가 그대로
    반영됨을 실측으로 확인)."""
    k = char_hints("process", PRESET, REAL, step_count=step_count)["단계 부제"]
    n = capacity_contract("process", PRESET, step_count=step_count)["step_subtitle_max_lines"]

    def slide(lines: int):
        subtitle = " ".join([H * k] * lines) if lines > 0 else ""
        return _slide("process", _process_slots(step_count, subtitle=subtitle))

    if n > 0:
        assert not _slot_warnings(slide(n), "step0_subtitle"), "계약대로 채웠는데 넘침 경고가 났다"
    assert _slot_warnings(slide(n + 1), "step0_subtitle"), "계약보다 한 줄 더 넣었는데 경고가 없다"


def test_process_contract_never_negative_with_large_row_gap_across_counts():
    p2 = apply_overrides(PRESET, {"spacing": {"process_row_gap": 100.0}})
    for n in (3, 4, 5, 6):
        assert min(capacity_contract("process", p2, step_count=n).values()) >= 0


# ---- 행렬(matrix) 용량 계약 (2026-09-07 DB-4) ----
# process와 같은 세로 원리(행이 늘수록 행 높이가 줄어든다)를 쓰되, 가로 3칸(분류/대표/나열)의
# 폭 배분이 다르다: 분류 셀과 나열은 고정 폭 좌우 블록이고 대표 항목이 그 사이 나머지 폭을
# 쓴다. capacity_contract/char_hints에 더한 row_count 인자는 그래서 process의 step_count와
# 정확히 같은 자리(세로 용량)에 영향을 준다: 가로 칸 폭은 행 수와 무관하므로 char_hints는
# process처럼 row_count가 바뀌어도 값이 그대로다.


def test_existing_nine_templates_contract_values_unchanged_by_matrix_signature():
    """capacity_contract에 row_count 인자를 더해도 기존 9종(process 포함) 계약은 그대로다."""
    assert capacity_contract("cover", PRESET) == {
        "cover_title_max_lines": 1, "subtitle_max_lines": 1, "date_max_lines": 1,
    }
    assert capacity_contract("divider", PRESET) == {
        "section_no_max_lines": 1, "section_title_max_lines": 1,
    }
    assert capacity_contract("summary", PRESET) == {"points_max_lines": 14, "conclusion_max_lines": 2}
    assert capacity_contract("bullet_box", PRESET) == {
        "bullets_max_lines": 14, "conclusion_max_lines": 2, "footnote_max_lines": 1,
    }
    assert capacity_contract("table", PRESET) == {"rows_max_single_line": 16, "footnote_max_lines": 1}
    assert capacity_contract("compare2", PRESET) == {
        "card_heading_max_lines": 1, "card_bullets_max_lines": 11, "conclusion_max_lines": 2,
    }
    assert capacity_contract("callout", PRESET) == {"text_max_lines": 3}
    assert capacity_contract("cards", PRESET) == {
        "card_badge_max_lines": 1, "card_heading_max_lines": 1, "card_bullets_max_lines": 12,
        "card_tail_max_lines": 1,
    }
    assert capacity_contract("process", PRESET) == {
        "step_heading_max_lines": 1, "step_subtitle_max_lines": 4, "step_label_max_lines": 1,
    }


def test_matrix_geometry_row_height_shrinks_as_row_count_grows_but_x_fields_do_not():
    three = matrix_geometry(PRESET, 3)
    six = matrix_geometry(PRESET, 6)
    assert three["row_h"] > six["row_h"]
    assert three["category_x"] == six["category_x"]
    assert three["primary_x"] == six["primary_x"]
    assert three["primary_w"] == six["primary_w"]
    assert three["items_x"] == six["items_x"]
    assert three["items_w"] == six["items_w"]


def test_matrix_geometry_rows_span_the_content_height_for_every_valid_count():
    g = content_geometry(PRESET)
    content_h = g["content_bottom"] - g["content_top"]
    for n in (3, 4, 5, 6):
        mg = matrix_geometry(PRESET, n)
        assert n * mg["row_h"] + (n - 1) * mg["row_gap"] == pytest.approx(content_h)


def test_matrix_char_hint_is_independent_of_row_count():
    """가로 칸 너비는 행 수와 무관하다: process의 char_hints가 step_count와 무관한 것과 같다."""
    three = char_hints("matrix", PRESET, REAL, row_count=3)
    six = char_hints("matrix", PRESET, REAL, row_count=6)
    assert set(three) == {"분류 셀 한 줄", "대표 항목 한 줄", "나열 항목 한 줄"}
    assert three == six


def test_matrix_contract_answers_without_row_count_argument():
    # capacity_contract("matrix", PRESET)처럼 row_count를 생략하는 기존 호출부(service.py)가
    # 죽지 않아야 한다: 기본값 3이 안전하다 (card_count/step_count와 같은 이유)
    contract = capacity_contract("matrix", PRESET)
    assert set(contract) == {"row_category_max_lines", "row_primary_max_lines", "row_items_max_lines"}
    assert all(v >= 0 for v in contract.values())


def _matrix_slots(n: int, category: str = "분류", primary: str = "", items: list[str] | None = None) -> MatrixSlots:
    return MatrixSlots(rows=[
        MatrixRow(category=category, primary=primary, items=list(items or [])) for _ in range(n)
    ])


@pytest.mark.parametrize("row_count", [3, 4, 5, 6])
def test_matrix_contract_boundary_of_category_lines_fits_and_plus_one_overflows(row_count):
    k = char_hints("matrix", PRESET, REAL, row_count=row_count)["분류 셀 한 줄"]
    n = capacity_contract("matrix", PRESET, row_count=row_count)["row_category_max_lines"]

    def slide(lines: int):
        category = " ".join([H * k] * lines) if lines > 0 else ""
        return _slide("matrix", _matrix_slots(row_count, category=category))

    if n > 0:
        assert not _slot_warnings(slide(n), "row0_category"), "계약대로 채웠는데 넘침 경고가 났다"
    assert _slot_warnings(slide(n + 1), "row0_category"), "계약보다 한 줄 더 넣었는데 경고가 없다"


@pytest.mark.parametrize("row_count", [3, 4, 5, 6])
def test_matrix_contract_boundary_of_primary_lines_fits_and_plus_one_overflows(row_count):
    """대표 항목 3, 4, 5, 6개 각각에서 계약대로 채우면 실측이 통과하는지. 행이 낮아질수록
    (행이 늘수록) 대표 항목 상한도 함께 줄어야 한다."""
    k = char_hints("matrix", PRESET, REAL, row_count=row_count)["대표 항목 한 줄"]
    n = capacity_contract("matrix", PRESET, row_count=row_count)["row_primary_max_lines"]

    def slide(lines: int):
        primary = " ".join([H * k] * lines) if lines > 0 else ""
        return _slide("matrix", _matrix_slots(row_count, primary=primary))

    if n > 0:
        assert not _slot_warnings(slide(n), "row0_primary"), "계약대로 채웠는데 넘침 경고가 났다"
    assert _slot_warnings(slide(n + 1), "row0_primary"), "계약보다 한 줄 더 넣었는데 경고가 없다"


@pytest.mark.parametrize("row_count", [3, 4, 5, 6])
def test_matrix_contract_boundary_of_one_line_items_fits_and_plus_one_overflows(row_count):
    n = capacity_contract("matrix", PRESET, row_count=row_count)["row_items_max_lines"]

    def slide(k):
        return _slide("matrix", _matrix_slots(row_count, items=[f"항목{j}" for j in range(k)]))

    assert not _slot_warnings(slide(n), "row0_items"), "계약대로 채웠는데 넘침 경고가 났다"
    assert _slot_warnings(slide(n + 1), "row0_items"), "계약보다 하나 더 넣었는데 경고가 없다"


def test_matrix_contract_never_negative_with_large_padding_across_counts():
    p2 = apply_overrides(PRESET, {"spacing": {"box_padding": 40.0}})
    for n in (3, 4, 5, 6):
        assert min(capacity_contract("matrix", p2, row_count=n).values()) >= 0


# 개수 의존 템플릿의 프롬프트 계약 (2026-09-07 DB-2, DB-3, DB-4 리뷰가 각각 같은 결함을 지적했다)


def test_count_range_comes_from_the_schema_not_a_hardcoded_number():
    """개수 범위는 deck.py 의 스키마 제약에서 읽는다.

    여기에 숫자를 적어 두면 스키마의 제약이 바뀔 때 조용히 어긋난다. 실제로 이 묶음은
    템플릿 이름을 네 곳에 하드코딩했다가 DA-5 에서 단일 출처로 묶은 이력이 있다.
    """
    from slidecaptain.metrics.capacity import count_range

    assert count_range("cards") == (2, 4)
    assert count_range("process") == (3, 6)
    assert count_range("matrix") == (3, 6)
    assert count_range("bullet_box") is None


def test_worst_case_counts_gives_the_largest_item_count():
    """프롬프트 계약은 개수가 정해지기 전에 만들어지므로 가장 빡빡한 개수로 잡는다."""
    from slidecaptain.metrics.capacity import worst_case_counts

    assert worst_case_counts("cards") == {"card_count": 4}
    assert worst_case_counts("process") == {"step_count": 6}
    assert worst_case_counts("matrix") == {"row_count": 6}
    assert worst_case_counts("bullet_box") == {}


def test_worst_case_contract_is_not_more_generous_than_any_actual_count():
    """최대 개수 기준 계약은 어느 실제 개수에서도 초과하지 않는다.

    이것이 보수적 계약의 정의다: AI 가 몇 개를 고르든 계약을 지키면 넘치지 않는다.
    """
    from slidecaptain.metrics.capacity import capacity_contract, count_range, worst_case_counts

    preset = Preset()
    for template in ("cards", "process", "matrix"):
        low, high = count_range(template)
        arg = next(iter(worst_case_counts(template)))
        worst = capacity_contract(template, preset, **{arg: high})
        for count in range(low, high + 1):
            actual = capacity_contract(template, preset, **{arg: count})
            for key, limit in worst.items():
                assert limit <= actual[key], f"{template} {count}개에서 {key} 계약이 실제보다 후하다"


def test_count_capacity_table_lists_only_the_values_that_change_with_count():
    """개수별 표에는 개수에 따라 실제로 달라지는 값만 담는다.

    변하지 않는 값까지 개수마다 반복하면 프롬프트만 길어지고 AI 가 읽을 것이 늘어난다.
    cards 는 가로로 나뉘어 줄당 글자 수가 달라지고, process 와 matrix 는 세로로 쌓여
    줄 수가 달라진다 (2026-09-07 실측).
    """
    from slidecaptain.metrics.capacity import count_capacity_table
    from slidecaptain.metrics.font_metrics import FontMetrics

    preset, metrics = Preset(), FontMetrics.load_default()

    cards = count_capacity_table("cards", preset, metrics)
    assert [count for count, _, _ in cards] == [2, 3, 4]
    assert all(not contract for _, contract, _ in cards), "cards 의 줄 수 계약은 카드 수와 무관하다"
    assert all("카드 안 한 줄" in hints for _, _, hints in cards)

    process = count_capacity_table("process", preset, metrics)
    assert [count for count, _, _ in process] == [3, 4, 5, 6]
    assert all("step_subtitle_max_lines" in contract for _, contract, _ in process)
    assert all(not hints for _, _, hints in process), "process 의 줄당 글자 수는 단계 수와 무관하다"

    assert count_capacity_table("bullet_box", preset, metrics) == []
