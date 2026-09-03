"""프리셋: 모든 시각 수치의 단일 진본.

좌표와 글자 크기는 덱 데이터에 존재하지 않고, 항상 이 프리셋의 수치에서
레이아웃 엔진이 수식으로 계산한다 (설계서 5.4).
"""

from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

BODY_MIN_PT = 12.0
FOOTNOTE_MIN_PT = 9.0
_MIN_CONTENT_PT = 100.0  # 표, 카드, 불릿 영역이 실제로 그려질 수 있는 내용 폭과 높이의 하한 (설계서 3.3)

HexColor = Annotated[str, Field(pattern=r"^[0-9A-Fa-f]{6}$")]


class Fonts(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    korean: str = "Noto Sans KR"
    latin: str = "Noto Sans KR"


class FontRoles(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True, allow_inf_nan=False)

    cover_title_pt: float = Field(default=28.0, gt=0)
    section_title_pt: float = Field(default=24.0, gt=0)
    title_pt: float = Field(default=20.0, gt=0)
    subtitle_pt: float = Field(default=14.0, gt=0)
    body_pt: float = Field(default=12.0, gt=0)
    box_pt: float = Field(default=12.0, gt=0)
    table_pt: float = Field(default=12.0, gt=0)
    footnote_pt: float = Field(default=9.0, gt=0)
    page_number_pt: float = Field(default=9.0, gt=0)

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
    model_config = ConfigDict(extra="forbid", validate_assignment=True, allow_inf_nan=False)

    margin_left: float = Field(default=50.0, ge=0)
    margin_right: float = Field(default=50.0, ge=0)
    margin_top: float = Field(default=36.0, ge=0)
    margin_bottom: float = Field(default=34.0, ge=0)
    title_height: float = Field(default=40.0, gt=0)
    title_gap: float = Field(default=16.0, ge=0)
    footnote_height: float = Field(default=24.0, gt=0)
    footnote_gap: float = Field(default=8.0, ge=0)
    box_height: float = Field(default=56.0, gt=0)
    box_gap: float = Field(default=8.0, ge=0)
    box_padding: float = Field(default=10.0, ge=0)
    summary_box_gap: float = Field(default=12.0, ge=0)
    line_spacing: float = Field(default=1.4, ge=0.5)
    bullet_gap: float = Field(default=6.0, ge=0)
    bullet_indent: float = Field(default=18.0, ge=0)
    card_gap: float = Field(default=20.0, ge=0)
    card_heading_height: float = Field(default=24.0, gt=0)
    card_heading_gap: float = Field(default=8.0, ge=0)
    cover_indent: float = Field(default=30.0, ge=0)
    table_min_col_width: float = Field(default=60.0, gt=0)
    table_cell_pad_x: float = Field(default=6.0, ge=0)
    table_cell_pad_y: float = Field(default=3.0, ge=0)
    page_number_width: float = Field(default=60.0, gt=0)
    page_number_height: float = Field(default=16.0, gt=0)
    page_number_bottom: float = Field(default=28.0, ge=0)
    safety_ratio: float = Field(default=0.97, gt=0, le=1)
    border_width_pt: float = Field(default=0.75, gt=0)


class Preset(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True, allow_inf_nan=False)

    fonts: Fonts = Fonts()
    font_roles: FontRoles = FontRoles()
    colors: Colors = Colors()
    spacing: Spacing = Spacing()
    bullet_marker: BulletMarker = BulletMarker()
    page_width_pt: float = Field(default=960.0, gt=0)
    page_height_pt: float = Field(default=540.0, gt=0)
    language: str = "ko-KR"

    @model_validator(mode="after")
    def enforce_content_box(self) -> "Preset":
        # 내용 영역이 무너지면(음수이거나 거의 0이면) 표와 카드와 불릿이 그려질 자리가 없다 (실측: title_height=1000 -> -578pt)
        box = content_box(self)
        if box["content_width"] < _MIN_CONTENT_PT:
            raise ValueError(
                f"내용 폭이 너무 좁습니다({box['content_width']:.1f}pt). "
                f"여백을 줄이거나 페이지 폭을 늘려 주세요(최소 {_MIN_CONTENT_PT:.0f}pt)"
            )
        content_height = box["content_bottom"] - box["content_top"]
        if content_height < _MIN_CONTENT_PT:
            raise ValueError(
                f"내용 높이가 너무 좁습니다({content_height:.1f}pt). "
                f"제목이나 각주 영역을 줄이거나 페이지 높이를 늘려 주세요(최소 {_MIN_CONTENT_PT:.0f}pt)"
            )
        return self


def content_box(preset: Preset) -> dict[str, float]:
    """내용 영역 기하의 진본 산식 (설계서 5.4). 레이아웃 엔진(`_content_geometry`)이 이 함수를 그대로 쓴다."""
    s = preset.spacing
    content_top = s.margin_top + s.title_height + s.title_gap
    footnote_top = preset.page_height_pt - s.margin_bottom - s.footnote_height
    content_bottom = footnote_top - s.footnote_gap
    content_width = preset.page_width_pt - s.margin_left - s.margin_right
    return {
        "content_top": content_top,
        "content_bottom": content_bottom,
        "content_width": content_width,
        "footnote_top": footnote_top,
    }


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
