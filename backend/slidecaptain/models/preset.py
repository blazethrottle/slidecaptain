"""프리셋: 모든 시각 수치의 단일 진본.

좌표와 글자 크기는 덱 데이터에 존재하지 않고, 항상 이 프리셋의 수치에서
레이아웃 엔진이 수식으로 계산한다 (설계서 5.4).
"""

from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

BODY_MIN_PT = 12.0
FOOTNOTE_MIN_PT = 9.0

HexColor = Annotated[str, Field(pattern=r"^[0-9A-Fa-f]{6}$")]


class Fonts(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    korean: str = "맑은 고딕"
    latin: str = "맑은 고딕"


class FontRoles(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    cover_title_pt: float = 28.0
    section_title_pt: float = 24.0
    title_pt: float = 20.0
    subtitle_pt: float = 14.0
    body_pt: float = 12.0
    box_pt: float = 12.0
    table_pt: float = 12.0
    footnote_pt: float = 9.0
    page_number_pt: float = 9.0

    @model_validator(mode="after")
    def enforce_floors(self) -> "FontRoles":
        # 하한 규칙: 분량이 넘치면 글자가 아니라 내용을 줄인다 (설계서 1.2)
        for name in ("body_pt", "box_pt", "table_pt"):
            if getattr(self, name) < BODY_MIN_PT:
                raise ValueError(f"{name}은 본문 하한 {BODY_MIN_PT}pt 아래로 내릴 수 없습니다")
        for name in ("footnote_pt", "page_number_pt"):
            if getattr(self, name) < FOOTNOTE_MIN_PT:
                raise ValueError(f"{name}은 각주 하한 {FOOTNOTE_MIN_PT}pt 아래로 내릴 수 없습니다")
        return self


class Colors(BaseModel):
    """색상은 알파 없는 6자리 16진수 문자열."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    text: HexColor = "202020"
    accent: HexColor = "1F4E79"
    box_fill: HexColor = "EEF3F9"
    table_header_fill: HexColor = "F2F2F2"
    border: HexColor = "D0D7E2"
    background: HexColor = "FFFFFF"


class BulletMarker(BaseModel):
    """불릿 목록 표식. 문자와 표식 전용 폰트 (승격 전에는 라이터의 리터럴이었다)."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    char: str = "•"
    font: str = "Arial"


class Spacing(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    margin_left: float = 50.0
    margin_right: float = 50.0
    margin_top: float = 36.0
    margin_bottom: float = 34.0
    title_height: float = 40.0
    title_gap: float = 16.0
    footnote_height: float = 24.0
    footnote_gap: float = 8.0
    box_height: float = 56.0
    box_gap: float = 8.0
    box_padding: float = 10.0
    summary_box_gap: float = 12.0
    line_spacing: float = 1.4
    bullet_gap: float = 6.0
    bullet_indent: float = 18.0
    card_gap: float = 20.0
    card_heading_height: float = 24.0
    card_heading_gap: float = 8.0
    cover_indent: float = 30.0
    table_min_col_width: float = 60.0
    table_cell_pad_x: float = 6.0
    table_cell_pad_y: float = 3.0
    page_number_width: float = 60.0
    page_number_height: float = 16.0
    page_number_bottom: float = 28.0
    safety_ratio: float = 0.97
    border_width_pt: float = 0.75


class Preset(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    fonts: Fonts = Fonts()
    font_roles: FontRoles = FontRoles()
    colors: Colors = Colors()
    spacing: Spacing = Spacing()
    bullet_marker: BulletMarker = BulletMarker()
    page_width_pt: float = 960.0
    page_height_pt: float = 540.0
    language: str = "ko-KR"


def _deep_merge(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def apply_overrides(base: Preset, overrides: dict[str, Any]) -> Preset:
    """전역 프리셋 위에 덱별 덮어쓰기를 얹는다 (설계서 3.3). 하한 검증이 다시 걸린다."""
    return Preset.model_validate(_deep_merge(base.model_dump(), overrides))
