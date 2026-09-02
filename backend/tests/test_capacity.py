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
    card_geometry,
    char_hints,
    hangul_chars_per_line,
)
from slidecaptain.models.deck import (
    BulletBoxSlots,
    Card,
    Chapter,
    CompareSlots,
    Deck,
    DeckMeta,
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
    for template in ("summary", "bullet_box", "table", "compare2"):
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
