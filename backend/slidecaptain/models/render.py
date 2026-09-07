"""렌더 계획: 레이아웃 엔진의 출력. PPTX 라이터와 (이후 단계의) 화면 미리보기가 함께 소비한다.

여기 담긴 좌표와 글자 크기는 프리셋에서 계산된 결과이지, 조정 대상이 아니다.
"""

from typing import Annotated, Literal

from pydantic import ConfigDict

from pydantic import BaseModel, Field, model_validator

# 색값은 알파 없는 6자리 16진수. 프리셋과 같은 규격이다.
# 잘못된 값을 여기서 막지 않으면 python-pptx 가 예외를 던져 내보내기 전체가 멈추는데,
# 미리보기는 CSS 라 세 자리 축약을 정상으로 그려서 화면만 멀쩡해 보인다 (2026-09-07 최종 리뷰)
HexColor = Annotated[str, Field(pattern=r"^[0-9A-Fa-f]{6}$")]


class Para(BaseModel):
    text: str
    level: int = 0
    font_pt: float
    bold: bool = False
    color: HexColor = "202020"
    align: Literal["left", "center", "right"] = "left"
    bullet: bool = False  # True면 라이터가 목록 표식(•)과 내어쓰기를 적용
    lines: list[str] = []  # 엔진의 어절 줄바꿈 결과. 미리보기 전용, 라이터는 읽지 않는다


class TablePlan(BaseModel):
    # 생성 후 대입도 검증한다. 종전에는 길이 검증을 setattr 로 우회할 수 있었다 (2026-09-07 리뷰)
    model_config = ConfigDict(validate_assignment=True)

    col_widths_pt: list[float]
    header: list[str]
    rows: list[list[str]]
    font_pt: float
    header_fill: HexColor
    row_heights_pt: list[float]  # 머리글 포함, 위에서부터
    header_lines: list[list[str]] = []  # 머리글 칸별 줄바꿈 결과 (미리보기 전용)
    cell_lines: list[list[list[str]]] = []  # 행 x 열 x 줄 (미리보기 전용)
    # 칸별 채움. 비면 header_fill 로 머리행 전체를 칠하고 본문은 칠하지 않는다(기존 동작).
    # 벤치마크의 표는 행 교차가 아니라 열 단위 색상 코딩이고 머리행도 칸마다 색이 다르다
    # (2026-09-07 실측: 표 4개 전수 조사). header_fill 하나로는 표현할 수 없다
    header_fills: list[HexColor] = []  # 머리행 칸별
    body_fills: list[HexColor] = []  # 본문 열별 (모든 본문 행에 같은 열 색을 쓴다)

    @model_validator(mode="after")
    def _cell_fill_lengths_match_columns(self) -> "TablePlan":
        for name, values in (("header_fills", self.header_fills), ("body_fills", self.body_fills)):
            if values and len(values) != len(self.col_widths_pt):
                raise ValueError(
                    f"{name} 의 길이({len(values)})가 열 수({len(self.col_widths_pt)})와 다릅니다."
                )
        return self


class Frame(BaseModel):
    name: str  # 역할 태깅: "장ID:슬롯" (설계서 7.1)
    x: float
    y: float
    w: float
    h: float
    fill: HexColor | None = None
    border: HexColor | None = None
    paras: list[Para] = []
    table: TablePlan | None = None
    # 세로 정렬. 미리보기가 그릴 수 있는 값만 허용하고, 라이터는 이 값을 모든 텍스트 도형에 항상 명시한다
    # (2026-09-02 Critical 묶음 태스크 B: 채움 프레임이 python-pptx 자동도형 기본값 ctr 을 상속해 미리보기와 어긋났다)
    valign: Literal["top", "middle"] = "top"
    # 모서리 반경(pt). None 이면 직각 사각형이다. 짧은 변의 절반 이상이면 알약이나 정원이 된다.
    # 라이터는 사각형과 둥근 사각형 두 가지만 쓴다: OVAL 은 조정 핸들이 없어(python-pptx 1.0.2 실측)
    # 폭과 높이가 다르면 눌린 타원이 되고, 그 순간 CSS 로 그리는 미리보기와 어긋난다 (2026-09-07 DA-1)
    radius_pt: float | None = Field(default=None, ge=0)
    # 이 프레임만의 테두리 두께(pt). None 이면 RenderStyle.border_width_pt 를 쓴다.
    # 폴백 판단은 레이아웃 엔진이 하고 소비자는 값을 그대로 쓴다: 같은 기본값 규칙을 라이터와
    # 미리보기 두 곳에 따로 두면 세로 정렬 사고와 같은 계열의 어긋남이 생긴다
    border_width_pt: float | None = Field(default=None, ge=0)


class CapacityWarning(BaseModel):
    chapter_id: str
    slot: str
    message: str
    needed_pt: float
    available_pt: float


class SlidePlan(BaseModel):
    chapter_id: str
    template: str
    frames: list[Frame]
    warnings: list[CapacityWarning] = []


class RenderStyle(BaseModel):
    """라이터와 미리보기가 소비하는 시각 스타일. 프리셋에서 계산되어 렌더 계획에 내장된다.

    렌더 계획은 이 블록 덕에 자기완결적이다: 소비자는 프리셋을 다시 해석하지 않는다.
    """

    korean_font: str
    latin_font: str
    text_color: HexColor
    box_padding_pt: float
    line_spacing: float  # 행간 계수. 라이터가 font_pt에 곱해 고정 pt로 기록한다
    bullet_indent_pt: float
    bullet_gap_pt: float
    table_cell_pad_x_pt: float
    table_cell_pad_y_pt: float
    border_width_pt: float
    bullet_char: str
    bullet_font: str


class RenderPlan(BaseModel):
    page_width_pt: float
    page_height_pt: float
    style: RenderStyle
    slides: list[SlidePlan]
