"""Export preflight contract, not a report-quality certificate."""

from typing import Literal

from pydantic import BaseModel, Field

from slidecaptain.models.numeric_review import NumericReviewReport


class QualityCheck(BaseModel):
    name: str
    status: Literal["passed", "failed", "not_run"]
    evaluated: int = Field(ge=0)
    failed: int = Field(ge=0)
    detail: str
    chapter_ids: list[str] = Field(default_factory=list)


class QualityReport(BaseModel):
    gate_version: Literal["preflight-v1", "preflight-v2"] = "preflight-v2"
    status: Literal["draft", "needs_revision"]
    input_fingerprint: str
    artifact_sha256: str | None = None
    slide_count: int = Field(ge=0)
    draft_export_allowed: bool
    final_export_allowed: Literal[False] = False
    checks: list[QualityCheck]
    numeric_review: NumericReviewReport | None = None
    notice: str = "사전 점검 결과입니다. 내용 정확성, 보고 흐름, 시각 품질과 PowerPoint 표시는 아직 검수하지 않았습니다."
