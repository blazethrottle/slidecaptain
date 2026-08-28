"""AI 생성 텍스트의 상류 정규화 (설계 결정 9).

레이아웃의 줄바꿈 실측(line_breaker)은 "개행 없는 단일 문단, 연속 공백 없음"을
전제한다. AI 응답이 이 전제를 벗어나도 여기서 흡수한다. 프로젝트 금지 문자
(엠대시 U+2014, 중점 U+00B7)도 이 단계에서 기계 치환으로 보증한다.
"""

import re
from typing import Any

_MULTI_SPACE = re.compile(r" {2,}")


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", " ")
    text = text.replace("\t", " ")
    text = text.replace("—", "-").replace("·", ", ")
    return _MULTI_SPACE.sub(" ", text).strip()


def normalize_payload(data: Any) -> Any:
    """AI 응답(JSON 호환 구조) 안의 모든 문자열 값을 정규화한다. dict 키는 스키마 필드라 건드리지 않는다."""
    if isinstance(data, str):
        return normalize_text(data)
    if isinstance(data, list):
        return [normalize_payload(item) for item in data]
    if isinstance(data, dict):
        return {key: normalize_payload(value) for key, value in data.items()}
    return data


def collect_strings(data: Any) -> list[str]:
    """구조 안의 모든 문자열 값을 순서대로 모은다 (수치 대조 게이트의 입력)."""
    if isinstance(data, str):
        return [data]
    if isinstance(data, list):
        return [s for item in data for s in collect_strings(item)]
    if isinstance(data, dict):
        return [s for value in data.values() for s in collect_strings(value)]
    return []
