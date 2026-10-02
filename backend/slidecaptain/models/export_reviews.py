"""User-entered manual verdicts, separate from verified render or AI receipts."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


ReviewCategory = Literal["narrative", "evidence", "representation", "visual", "target_renderer"]
ReviewStatus = Literal["passed", "needs_revision"]
ReviewCurrentness = Literal["current", "stale", "unavailable"]
SHA256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
PageNumber = Annotated[int, Field(strict=True, ge=1)]
CATEGORIES: tuple[ReviewCategory, ...] = ("narrative", "evidence", "representation", "visual", "target_renderer")


class _Verdict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    category: ReviewCategory
    status: ReviewStatus
    reviewer: str = Field(min_length=1, max_length=200)
    note: str = Field(min_length=1, max_length=4000)
    pages: list[PageNumber] = Field(min_length=1, max_length=10000)

    @model_validator(mode="after")
    def unique_pages(self):
        if len(set(self.pages)) != len(self.pages):
            raise ValueError("확인한 페이지 번호는 중복 없이 입력해 주세요.")
        return self


class ExportReviewRequest(_Verdict):
    expected_input_fingerprint: SHA256
    expected_artifact_sha256: SHA256


class ExportReviewRecord(_Verdict):
    id: str = Field(pattern=r"^[0-9a-f]{32}$")
    sequence: int = Field(ge=1, le=99999999)
    rule_version: Literal["manual-review-v1"]
    export_id: str
    input_fingerprint: SHA256
    artifact_sha256: SHA256
    reviewed_at: str


class ExportReviewCategoryState(BaseModel):
    category: ReviewCategory
    status: Literal["not_run", "passed", "needs_revision", "stale", "unavailable"]
    latest_record_id: str | None


class ExportReviews(BaseModel):
    export_id: str
    checked_at: str
    base_etag: str | None
    input_fingerprint: str | None
    artifact_sha256: str | None
    current_input_fingerprint: str | None
    slide_count: int | None
    status: ReviewCurrentness
    storage_status: Literal["empty", "readable", "invalid", "unreadable"]
    can_record: bool
    reason: str | None
    categories: list[ExportReviewCategoryState]
    records: list[ExportReviewRecord]
    final_export_allowed: Literal[False]
