"""Read-only numeric expression checks. No stored or model-authored verdicts."""

from typing import Literal

from pydantic import BaseModel, Field


class NumericExpression(BaseModel):
    chapter_id: str
    derivation_id: str
    claim_id: str
    target_evidence_id: str
    baseline_evidence_id: str
    source_ids: list[str]
    formula: str
    text: str


class NumericReviewItem(BaseModel):
    chapter_id: str
    path: str
    actual: str
    code: Literal["matched", "unlinked_expression", "ambiguous_expression"]
    message: str
    derivation_id: str | None = None


class NumericReviewReport(BaseModel):
    rule_version: Literal["q2d-v1"] = "q2d-v1"
    status: Literal["matched", "needs_review", "not_run"]
    reason: Literal["missing_plan", "stale_plan", "evidence_mismatch", "no_numeric_fields", "no_computed_expressions"] | None = None
    input_fingerprint: str
    numeric_fields: int = Field(ge=0)
    evaluated: int = Field(ge=0)
    matched: int = Field(ge=0)
    unresolved: int = Field(ge=0)
    expressions: list[NumericExpression]
    items: list[NumericReviewItem]
    semantic_status: Literal["not_run"] = "not_run"
    notice: str = (
        "이 기능은 계산 문구의 연결과 일치만 확인합니다. 원문 해석, 자유로운 문장의 의미와 보고서 품질은 미검수입니다. "
        "검사 시점의 자료를 사용하므로 다른 창이나 앱에서 원문을 바꾸면 다시 검사해 주세요."
    )
