"""렌더 계획: 레이아웃 엔진의 출력. PPTX 라이터와 (이후 단계의) 화면 미리보기가 함께 소비한다.

여기 담긴 좌표와 글자 크기는 프리셋에서 계산된 결과이지, 조정 대상이 아니다.
"""

from typing import Literal

from pydantic import BaseModel


class Para(BaseModel):
    text: str
    level: int = 0
    font_pt: float
    bold: bool = False
    color: str = "202020"
    align: Literal["left", "center", "right"] = "left"
    bullet: bool = False  # True면 라이터가 목록 표식(•)과 내어쓰기를 적용
    lines: list[str] = []  # 엔진의 어절 줄바꿈 결과. 미리보기 전용, 라이터는 읽지 않는다


class TablePlan(BaseModel):
    col_widths_pt: list[float]
    header: list[str]
    rows: list[list[str]]
    font_pt: float
    header_fill: str
    row_heights_pt: list[float]  # 머리글 포함, 위에서부터
    header_lines: list[list[str]] = []  # 머리글 칸별 줄바꿈 결과 (미리보기 전용)
    cell_lines: list[list[list[str]]] = []  # 행 x 열 x 줄 (미리보기 전용)


class Frame(BaseModel):
    name: str  # 역할 태깅: "장ID:슬롯" (설계서 7.1)
    x: float
    y: float
    w: float
    h: float
    fill: str | None = None
    border: str | None = None
    paras: list[Para] = []
    table: TablePlan | None = None
    # 세로 정렬. 미리보기가 그릴 수 있는 값만 허용하고, 라이터는 이 값을 모든 텍스트 도형에 항상 명시한다
    # (2026-09-02 Critical 묶음 태스크 B: 채움 프레임이 python-pptx 자동도형 기본값 ctr 을 상속해 미리보기와 어긋났다)
    valign: Literal["top", "middle"] = "top"


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
    text_color: str
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
