"""수치 대조 게이트 (설계서 4.2 게이트 3).

생성 문장에서 숫자를 추출해 입력 자료 원문에 존재하는지 대조한다.
"근거 없는 수치 금지"를 프롬프트 당부가 아니라 기계 검증으로 강제하며,
결과는 차단이 아니라 화면 경고 표지로 쓰인다 (단계 3 결정 6).
"""

import re

# 콤마 자릿수 구분과 소수점을 포함한 숫자 토큰
_NUMBER_RE = re.compile(r"\d+(?:,\d{3})*(?:\.\d+)?")


def _normalize(token: str) -> str:
    return token.replace(",", "")


def extract_numbers(text: str) -> list[str]:
    """대조 대상 숫자를 정규화 형태(콤마 제거)로 추출한다. 등장 순서 유지, 중복 제거.

    한 자리 정수는 제외한다: "3가지" 같은 개수 표현이 대부분이라 경고 소음이 되고,
    놓쳤을 때의 위험도 작다.
    """
    seen: list[str] = []
    for m in _NUMBER_RE.finditer(text):
        value = _normalize(m.group())
        if len(value) < 2:
            continue
        if value not in seen:
            seen.append(value)
    return seen


def find_unverified_numbers(texts: list[str], sources: list[str]) -> list[str]:
    """자료 원문 어디에도 없는 숫자 목록.

    대조는 콤마를 제거한 정규화 텍스트에서 숫자 경계를 지켜 수행한다
    (234가 1,234의 일부에 걸려 통과하는 것을 막는다). 앞 경계는 "숫자" 또는
    "숫자."만 막는다: 문장 마침표 바로 뒤 숫자("이다.500억")는 근거로 인정하고,
    1234 안의 234와 3.14 안의 14는 여전히 막는다.
    """
    haystack = "\n".join(_normalize(s) for s in sources)
    unverified: list[str] = []
    for text in texts:
        for number in extract_numbers(text):
            pattern = re.compile(r"(?<!\d)(?<!\d\.)" + re.escape(number) + r"(?!\.?\d)")
            if pattern.search(haystack) is None and number not in unverified:
                unverified.append(number)
    return unverified
