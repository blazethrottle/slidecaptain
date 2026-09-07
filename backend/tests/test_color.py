import pytest

from slidecaptain.metrics.color import readable_text_color, relative_luminance


def test_relative_luminance_of_white_and_black_are_the_extremes():
    assert relative_luminance("FFFFFF") == pytest.approx(1.0)
    assert relative_luminance("000000") == pytest.approx(0.0)


def test_readable_text_color_on_pure_white_and_black_fills():
    assert readable_text_color("FFFFFF") == "202020"  # 흰 바탕엔 어두운 글자
    assert readable_text_color("000000") == "FFFFFF"  # 검은 바탕엔 밝은 글자


def test_readable_text_color_flips_exactly_at_the_wcag_crossover():
    """light(FFFFFF)와 dark(202020) 각각과의 대비가 같아지는 상대 휘도는

    sqrt(1.05 * (luminance(202020) + 0.05)) - 0.05 = 0.21013이다 (전수 스캔으로 확인:
    0x7E7E7E와 0x7F7F7F 사이에서 갈린다). 회색조 한 단계 차이로 판단이 뒤집힌다는 것은
    밝기를 어림하는 매직 넘버가 아니라 대비 계산 자체로 결정한다는 증거다.
    """

    assert relative_luminance("7E7E7E") < 0.21013
    assert relative_luminance("7F7F7F") > 0.21013
    assert readable_text_color("7E7E7E") == "FFFFFF"
    assert readable_text_color("7F7F7F") == "202020"


def test_readable_text_color_respects_custom_light_and_dark_colors():
    assert readable_text_color("000000", light="EAF2F1", dark="1B2A3A") == "EAF2F1"


@pytest.mark.parametrize(
    ("fill_hex", "expected"),
    [
        ("1B2A3A", "FFFFFF"),  # ink: 아주 어둡다 (대비 14.6 대 1.1)
        ("24384A", "FFFFFF"),  # ink_soft
        ("EAF2F1", "202020"),  # surface1: 아주 밝다 (대비 14.3 대 1.1)
        ("C8860B", "202020"),  # accent2: 어두운 글자가 근소하게 대비가 더 크다 (5.33 대 3.06)
    ],
)
def test_readable_text_color_matches_hand_verified_role_colors(fill_hex, expected):
    assert readable_text_color(fill_hex) == expected


def test_readable_text_color_picks_the_higher_contrast_side_even_when_neither_hits_aa():
    # accent1(0E8C7F)은 두 후보 다 WCAG AA 4.5:1 미달이지만(4.14, 3.94) 그래도 더 나은 쪽을 고른다
    assert readable_text_color("0E8C7F") == "FFFFFF"
