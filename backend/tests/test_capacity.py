import pytest

from slidecaptain.metrics.capacity import (
    BulletsMeasure,
    capacity_contract,
    line_height_pt,
    max_lines,
    measure_bullets,
    measure_lines,
)
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
    # 기본 프리셋에서 불릿 영역 높이는 318pt (Task 6의 프레임 수식과 같은 값)
    assert contract["bullets_max_lines"] == 18
    assert contract["conclusion_max_lines"] == 2
    assert contract["footnote_max_lines"] == 1


def test_capacity_contract_unknown_template():
    with pytest.raises(KeyError):
        capacity_contract("fancy_chart", PRESET)
