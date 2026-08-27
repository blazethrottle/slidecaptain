from pathlib import Path

import pytest

from slidecaptain.metrics.font_metrics import FontMetrics

MALGUN = Path("C:/Windows/Fonts/malgun.ttf")
MALGUN_BOLD = Path("C:/Windows/Fonts/malgunbd.ttf")


def test_bundled_metrics_load_both_faces():
    m = FontMetrics.from_bundled()
    assert m.face(False).width_pt("가", 12.0) > 0
    assert m.face(True).width_pt("가", 12.0) > 0


def test_hangul_is_exactly_one_em_in_both_faces():
    # 실측 검증(2026-08-27): 한글 음절은 레귤러와 볼드 모두 2048/2048 = 1em
    m = FontMetrics.from_bundled()
    assert m.face(False).width_pt("가", 12.0) == pytest.approx(12.0)
    assert m.face(True).width_pt("가", 12.0) == pytest.approx(12.0)
    assert m.face(False).width_pt("늬", 12.0) == pytest.approx(12.0)


def test_width_scales_linearly_with_font_size():
    face = FontMetrics.from_bundled().face(False)
    assert face.width_pt("가나다", 24.0) == pytest.approx(2 * face.width_pt("가나다", 12.0))


def test_width_additive_over_chars():
    face = FontMetrics.from_bundled().face(False)
    assert face.width_pt("가가", 12.0) == pytest.approx(2 * face.width_pt("가", 12.0))


def test_latin_is_proportional_and_narrower_than_hangul():
    face = FontMetrics.from_bundled().face(False)
    assert face.width_pt("iiii", 12.0) < face.width_pt("WWWW", 12.0)
    assert face.width_pt("a", 12.0) < face.width_pt("가", 12.0)


def test_bold_latin_wider_than_regular():
    # 실측 검증(2026-08-27): W는 레귤러 1953, 볼드 2068 유닛
    m = FontMetrics.from_bundled()
    assert m.face(True).width_pt("W", 12.0) > m.face(False).width_pt("W", 12.0)


def test_unknown_char_falls_back_to_safe_width():
    face = FontMetrics.from_bundled().face(False)
    # 수집 범위 밖의 글자도 1em 폭으로 계산된다 (과소 측정 방지)
    assert face.width_pt("\u2603", 12.0) == pytest.approx(12.0)  # SNOWMAN: 번들에 없는 글자


@pytest.mark.skipif(not (MALGUN.exists() and MALGUN_BOLD.exists()), reason="맑은 고딕이 없는 환경")
def test_bundled_matches_live_ttf():
    live = FontMetrics.from_ttf(MALGUN, MALGUN_BOLD)
    bundled = FontMetrics.from_bundled()
    for bold in (False, True):
        for text in ("가나다", "Market 12,300", "요약: 결론 우선"):
            assert bundled.face(bold).width_pt(text, 12.0) == pytest.approx(
                live.face(bold).width_pt(text, 12.0)
            )
