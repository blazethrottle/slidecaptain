from slidecaptain.metrics.line_breaker import break_paragraph


class FakeMetrics:
    """글자 하나 = font_pt 만큼의 폭. 폭 10pt 글자 10개 = 100pt 식으로 셈이 쉬운 가짜."""

    def width_pt(self, text: str, font_pt: float) -> float:
        return len(text) * font_pt


FAKE = FakeMetrics()


def test_greedy_word_wrap():
    # 폭 한도 100pt, 글자당 10pt: 한 줄에 10글자 (공백 포함)
    lines = break_paragraph("가나다 라마바 사아자차카타", 100.0, 10.0, FAKE)
    assert lines == ["가나다 라마바", "사아자차카타"]


def test_single_short_line_unchanged():
    assert break_paragraph("짧은 문장", 100.0, 10.0, FAKE) == ["짧은 문장"]


def test_long_word_splits_by_char():
    # 14글자 한 어절: 10글자에서 쪼개진다
    lines = break_paragraph("가나다라마바사아자차카타파하", 100.0, 10.0, FAKE)
    assert lines == ["가나다라마바사아자차", "카타파하"]


def test_newline_forces_break():
    lines = break_paragraph("첫 줄\n둘째 줄", 100.0, 10.0, FAKE)
    assert lines == ["첫 줄", "둘째 줄"]


def test_empty_text_is_one_line():
    assert break_paragraph("", 100.0, 10.0, FAKE) == [""]


def test_safety_ratio_shrinks_budget():
    # 여유율 0.5 → 실효 한도 50pt = 5글자
    lines = break_paragraph("가나다 라마바", 100.0, 10.0, FAKE, safety_ratio=0.5)
    assert lines == ["가나다", "라마바"]


def test_multiple_spaces_collapse_into_word_split():
    lines = break_paragraph("하나  둘", 100.0, 10.0, FAKE)
    assert lines == ["하나 둘"]
