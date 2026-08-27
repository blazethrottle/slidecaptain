"""어절(공백) 단위 탐욕 줄바꿈. PowerPoint의 ko-KR 어절 줄바꿈과 같은 규칙을 코드로 재현한다.

여기서 계산한 줄수는 용량 검증에 쓰고, 실제 줄바꿈은 PowerPoint가 수행한다
(강제 개행을 심지 않으므로 내보낸 파일을 나중에 손으로 고치기 쉽다).
"""


def _split_long_word(word: str, budget_pt: float, font_pt: float, metrics) -> list[str]:
    parts: list[str] = []
    current = ""
    for ch in word:
        if current and metrics.width_pt(current + ch, font_pt) > budget_pt:
            parts.append(current)
            current = ch
        else:
            current += ch
    if current:
        parts.append(current)
    return parts


def break_paragraph(
    text: str,
    max_width_pt: float,
    font_pt: float,
    metrics,
    safety_ratio: float = 1.0,
) -> list[str]:
    budget = max_width_pt * safety_ratio
    lines: list[str] = []
    for raw_line in text.split("\n"):
        current = ""
        for word in [w for w in raw_line.split(" ") if w]:
            if metrics.width_pt(word, font_pt) > budget:
                # 한 어절이 한 줄을 넘으면 글자 단위로 쪼갠다
                if current:
                    lines.append(current)
                parts = _split_long_word(word, budget, font_pt, metrics)
                lines.extend(parts[:-1])
                current = parts[-1]
            elif not current:
                current = word
            elif metrics.width_pt(current + " " + word, font_pt) <= budget:
                current = current + " " + word
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines
