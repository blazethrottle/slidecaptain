"""Server render proofs and independently signed, artifact-bound judgments."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from slidecaptain.models.export_reviews import CATEGORIES, ReviewCategory, SHA256

RunID = Annotated[str, Field(pattern=r'^[0-9a-f]{32}$')]
Page = Annotated[int, Field(strict=True, ge=1, le=10000)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, allow_inf_nan=False)


class QualificationRequest(StrictModel):
    expected_input_fingerprint: SHA256
    expected_artifact_sha256: SHA256


class ReviewVerdict(StrictModel):
    category: ReviewCategory
    status: Literal['passed', 'needs_revision']
    note: str = Field(min_length=1, max_length=4000)

    @field_validator('note')
    @classmethod
    def substantive_note(cls, value):
        if not value.strip():
            raise ValueError('검수 근거가 필요합니다.')
        return value  # Signed text is preserved exactly, never normalized.


class ReviewFinding(StrictModel):
    code: str = Field(min_length=1, max_length=100)
    severity: Literal['critical', 'major', 'minor']
    pages: list[Page] = Field(min_length=1, max_length=10000)
    note: str = Field(min_length=1, max_length=4000)
    resolved: bool

    @field_validator('note', 'code')
    @classmethod
    def substantive_text(cls, value):
        if not value.strip():
            raise ValueError('문제 코드와 근거가 필요합니다.')
        return value

    @model_validator(mode='after')
    def unique(self):
        if len(set(self.pages)) != len(self.pages):
            raise ValueError('문제 페이지가 중복되었습니다.')
        return self


class IndependentReceipt(StrictModel):
    receipt_type: Literal['independent-review']
    rule_version: Literal['independent-review-v1']
    reviewer_id: str = Field(min_length=1, max_length=200)
    run_id: RunID
    producer_run_id: RunID
    input_fingerprint: SHA256
    artifact_sha256: SHA256
    render_id: RunID
    render_fingerprint: SHA256
    environment_fingerprint: SHA256
    pages: list[Page] = Field(min_length=1, max_length=10000)
    verdicts: list[ReviewVerdict] = Field(min_length=5, max_length=5)
    findings: list[ReviewFinding] = Field(max_length=1000)

    @model_validator(mode='after')
    def coverage(self):
        if len(set(self.pages)) != len(self.pages):
            raise ValueError('검수 페이지가 중복되었습니다.')
        if set(v.category for v in self.verdicts) != set(CATEGORIES):
            raise ValueError('다섯 필수 검수 항목이 각각 필요합니다.')
        if any(not set(f.pages).issubset(self.pages) for f in self.findings):
            raise ValueError('문제 페이지가 검수 범위 밖입니다.')
        return self


class IndependentReviewRequest(QualificationRequest):
    receipt: IndependentReceipt
    signature: SHA256


class ExportProvenance(StrictModel):
    rule_version: Literal['export-provenance-v1']
    producer_id: Literal['slidecaptain']
    producer_run_id: RunID
    input_fingerprint: SHA256
    artifact_sha256: SHA256


class RenderPage(StrictModel):
    page: Page
    filename: str = Field(min_length=1, max_length=500)
    sha256: SHA256
    width: int = Field(strict=True, ge=1, le=10000)
    height: int = Field(strict=True, ge=1, le=10000)


class NativeRenderRecord(StrictModel):
    kind: Literal['render'] = 'render'
    rule_version: Literal['native-powerpoint-v1'] = 'native-powerpoint-v1'
    id: RunID
    sequence: int = Field(strict=True, ge=1, le=99999999)
    recorded_at: str
    input_fingerprint: SHA256
    artifact_sha256: SHA256
    status: Literal['rendered', 'not_run', 'failed']
    reason: str | None
    environment_fingerprint: SHA256 | None
    render_fingerprint: SHA256 | None
    environment: dict[str, str]
    pages: list[RenderPage]


class IndependentReviewRecord(StrictModel):
    kind: Literal['independent-review'] = 'independent-review'
    id: RunID
    sequence: int = Field(strict=True, ge=1, le=99999999)
    recorded_at: str
    receipt: IndependentReceipt
    signature: SHA256


class ExportQualification(BaseModel):
    export_id: str
    checked_at: str
    base_etag: str | None
    input_fingerprint: str | None
    artifact_sha256: str | None
    slide_count: int | None
    status: Literal['current', 'stale', 'unavailable']
    storage_status: Literal['empty', 'readable', 'invalid']
    provenance: ExportProvenance | None
    render_status: Literal['not_run', 'rendered', 'failed', 'stale', 'unavailable']
    render: NativeRenderRecord | None
    independent_review_status: Literal['not_run', 'passed', 'needs_revision', 'stale', 'unavailable']
    independent_review: IndependentReviewRecord | None
    final_export_allowed: bool
    can_render: bool
    can_import_review: bool
    blockers: list[str]


class FinalPublication(StrictModel):
    rule_version: Literal['qualified-final-v1'] = 'qualified-final-v1'
    id: RunID
    export_id: str
    published_at: str
    input_fingerprint: SHA256
    artifact_sha256: SHA256
    producer_run_id: RunID
    render_id: RunID
    review_record_id: RunID
    environment_fingerprint: SHA256
    pptx_path: str
    receipt_path: str
    render: NativeRenderRecord
    independent_review: IndependentReviewRecord
