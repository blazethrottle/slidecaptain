"""채움색 위 글자색 판단 (2026-09-07 DB-1): 밝은 글자와 어두운 글자 중 대비가 큰 쪽을 고른다.

라이터와 미리보기가 각자 판단하면 어긋난다(DA-1의 테두리 폴백 규칙과 같은 원칙). 그래서
레이아웃 엔진이 여기서 한 번 정해 프레임에 색을 항상 명시하고, 소비자는 값을 그대로 쓴다.

역할 이름 대 글자색의 고정 매핑표는 쓰지 않는다: 프리셋의 색 값 자체가 언제든 바뀔 수 있으므로
(사용자가 프리셋을 덮어쓰거나, 다음 회차에 벤치마크 값을 다시 뽑으면) 매번 실제 색값의 상대
휘도(WCAG 2.x)로 다시 판단해야 대비가 계속 맞는다.
"""


def _srgb_channel_to_linear(channel: float) -> float:
    """sRGB 채널(0.0~1.0)의 감마 보정. WCAG 2.x 상대 휘도 공식의 정의 그대로다."""
    return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4


def relative_luminance(hex_color: str) -> float:
    """WCAG 2.x 상대 휘도(0.0~1.0). hex_color는 여섯 자리 16진수(알파 없음)다."""
    r, g, b = (int(hex_color[i : i + 2], 16) / 255.0 for i in (0, 2, 4))
    r_lin, g_lin, b_lin = (_srgb_channel_to_linear(c) for c in (r, g, b))
    return 0.2126 * r_lin + 0.7152 * g_lin + 0.0722 * b_lin


def _contrast_ratio(luminance_a: float, luminance_b: float) -> float:
    lighter, darker = max(luminance_a, luminance_b), min(luminance_a, luminance_b)
    return (lighter + 0.05) / (darker + 0.05)


def readable_text_color(fill_hex: str, light: str = "FFFFFF", dark: str = "202020") -> str:
    """채움색(fill_hex) 위에서 light와 dark 중 대비가 더 큰 쪽을 고른다. 동률이면 light를 고른다."""
    bg = relative_luminance(fill_hex)
    light_contrast = _contrast_ratio(bg, relative_luminance(light))
    dark_contrast = _contrast_ratio(bg, relative_luminance(dark))
    return light if light_contrast >= dark_contrast else dark
