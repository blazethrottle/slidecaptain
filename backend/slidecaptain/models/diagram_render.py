"""Q3b의 독립 계산 출력. 저장된 후보는 검수 승인이나 신뢰할 입력이 아니다."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from slidecaptain.models.diagram import DiagramEdge, DiagramNode
from slidecaptain.models.preset import HexColor


class LayoutModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class DiagramPoint(LayoutModel):
    x: float = Field(ge=0)
    y: float = Field(ge=0)


class DiagramBounds(DiagramPoint):
    w: float = Field(gt=0)
    h: float = Field(gt=0)


class DiagramTextPlan(LayoutModel):
    text: str
    lines: list[str]
    bounds: DiagramBounds
    font_pt: float = Field(ge=12)
    line_height_pt: float = Field(gt=0)
    bold: bool
    color: HexColor


class DiagramNodePlan(LayoutModel):
    node: DiagramNode
    display_name: str
    bounds: DiagramBounds
    texts: list[DiagramTextPlan]
    fill: HexColor
    border: HexColor


class DiagramAnchor(LayoutModel):
    side: Literal["left", "right"]
    point: DiagramPoint


class DiagramEdgePlan(LayoutModel):
    edge: DiagramEdge
    start: DiagramAnchor
    end: DiagramAnchor
    label: DiagramTextPlan
    stroke: Literal["solid", "dotted", "dashed"]
    # 선 길이/간격을 pt로 확정한다. 소비자는 스타일 이름에서 수치를 다시 만들지 않는다.
    dash_pattern_pt: list[float]
    line_cap: Literal["butt"]
    color: HexColor
    # 선은 start.point부터 end.point까지다. flow 화살표는 끝점부터 시계 방향 3점이다.
    arrow_points: list[DiagramPoint]


class DiagramRenderPlan(LayoutModel):
    diagram_id: str
    page_width_pt: float = Field(gt=0)
    page_height_pt: float = Field(gt=0)
    content_bounds: DiagramBounds
    reading_profile: Literal["report"] = "report"
    layout_variant: Literal["flow_horizontal"] = "flow_horizontal"
    korean_font: str
    latin_font: str
    border_width_pt: float = Field(gt=0)
    nodes: list[DiagramNodePlan] = Field(min_length=2, max_length=12)
    edges: list[DiagramEdgePlan] = Field(min_length=1, max_length=24)


class DiagramLayoutIssue(LayoutModel):
    code: Literal[
        "unsupported_topology", "unsupported_font", "unsupported_spacing",
        "unsupported_text", "width_overflow", "height_overflow", "invalid_geometry",
    ]
    target_id: str
    message: str
    needed_pt: float | None = None
    available_pt: float | None = None


class DiagramReviewStatus(LayoutModel):
    semantic: Literal["not_run"] = "not_run"
    browser: Literal["not_run"] = "not_run"
    powerpoint: Literal["not_run"] = "not_run"
    reader: Literal["not_run"] = "not_run"


class DiagramLayoutResult(LayoutModel):
    rule_version: Literal["q3b-v1"] = "q3b-v1"
    diagram_id: str
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["computed", "blocked"]
    plan: DiagramRenderPlan | None
    issues: list[DiagramLayoutIssue]
    review: DiagramReviewStatus = Field(default_factory=DiagramReviewStatus)

    @model_validator(mode="after")
    def _complete_or_blocked(self) -> "DiagramLayoutResult":
        if self.status == "computed":
            if self.plan is None or self.issues or self.plan.diagram_id != self.diagram_id:
                raise ValueError("계산 완료에는 같은 도식의 전체 후보와 빈 문제 목록이 필요합니다")
        elif self.plan is not None or not self.issues:
            raise ValueError("배치 불가에는 사유가 필요하고 부분 후보를 포함할 수 없습니다")
        return self
