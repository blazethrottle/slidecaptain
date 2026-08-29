from slidecaptain.pipeline.normalize import collect_strings, normalize_payload, normalize_text


def test_newlines_become_single_spaces():
    assert normalize_text("첫 줄\r\n둘째 줄\r셋째\n넷째") == "첫 줄 둘째 줄 셋째 넷째"


def test_consecutive_spaces_and_tabs_collapse():
    assert normalize_text("앞  뒤\t끝   ") == "앞 뒤 끝"


def test_banned_characters_replaced():
    assert normalize_text("전략—핵심·요약") == "전략-핵심, 요약"


def test_payload_recurses_values_not_keys():
    payload = {"conclusion": "결론  문장\n계속", "bullets": [{"text": " 항목 ", "level": 1}]}
    result = normalize_payload(payload)
    assert result == {"conclusion": "결론 문장 계속", "bullets": [{"text": "항목", "level": 1}]}


def test_collect_strings_walks_nested():
    payload = {"a": "하나", "b": [{"c": "둘"}, "셋"], "d": 4}
    assert collect_strings(payload) == ["하나", "둘", "셋"]


def test_unicode_spaces_collapsed():
    assert normalize_text("가　나") == "가 나"
    assert normalize_text("가 나") == "가 나"
    assert normalize_text("가　  나") == "가 나"
