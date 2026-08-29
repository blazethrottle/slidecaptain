from slidecaptain.pipeline.numbers import extract_numbers, find_unverified_numbers


def test_extract_normalizes_commas_and_decimals():
    assert extract_numbers("매출 1,234억, 성장률 45.2%") == ["1234", "45.2"]


def test_extract_skips_single_digit_counts():
    assert extract_numbers("3가지 대안 중 2개 채택, 총 12건") == ["12"]


def test_extract_dedupes_keeping_order():
    assert extract_numbers("2026년 상반기, 2026년 하반기, 300억") == ["2026", "300"]


def test_verified_numbers_pass():
    sources = ["2026년 매출은 1,234억 원이며 성장률은 45.2%였다"]
    texts = ["매출 1234억 (45.2%)", "기준 연도 2026"]
    assert find_unverified_numbers(texts, sources) == []


def test_unverified_numbers_reported():
    sources = ["시장 규모는 500억 원"]
    texts = ["시장 규모 500억, 점유율 37%"]
    assert find_unverified_numbers(texts, sources) == ["37"]


def test_partial_digit_match_rejected():
    # 234는 1,234의 일부일 뿐, 자료에 있는 숫자가 아니다
    sources = ["매출 1,234억"]
    assert find_unverified_numbers(["순이익 234억"], sources) == ["234"]


def test_decimal_boundary_respected():
    # 45는 45.2의 일부일 뿐이다
    sources = ["성장률 45.2%"]
    assert find_unverified_numbers(["45명 대상"], sources) == ["45"]


def test_sentence_ending_period_is_a_boundary():
    # 문장 마침표와 한국식 날짜 표기는 소수점이 아니다 (2026-08-28 적대 리뷰 반영)
    sources = ["연간 매출은 1200. 기준일은 2026. 8. 28. 이다"]
    assert find_unverified_numbers(["매출 1200 (2026년 기준)"], sources) == []


def test_number_after_sentence_period_is_found():
    # 자료의 "이다.500억"처럼 문장 마침표 바로 뒤 숫자도 근거로 인정한다 (오탐 제거)
    assert find_unverified_numbers(["500억 규모"], ["시장이다.500억 규모다"]) == []


def test_decimal_fraction_still_guarded():
    # 3.14의 14는 여전히 소수부라 별개 숫자 14의 근거가 아니다
    assert find_unverified_numbers(["14개"], ["원주율은 3.14다"]) == ["14"]
