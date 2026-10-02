"""Read-time observations are separate from immutable published checks."""

from typing import Literal

from pydantic import BaseModel

from slidecaptain.models.quality import QualityReport


class ExportHistoryItem(BaseModel):
    id: str
    file_modified_at: str | None
    record_status: Literal["readable", "missing", "invalid", "unsupported", "unreadable"]
    artifact_status: Literal["matched", "mismatch", "missing", "unreadable", "unverified"]
    input_status: Literal["current", "stale", "legacy", "unavailable"]
    quality_status: Literal["draft", "needs_revision"] | None
    slide_count: int | None
    gate_version: str | None


class ExportHistoryContext(BaseModel):
    checked_at: str
    current_input_fingerprint: str | None
    current_input_error: str | None


class ExportHistoryPage(ExportHistoryContext):
    items: list[ExportHistoryItem]
    total: int
    offset: int
    limit: int


class ExportHistoryDetail(ExportHistoryContext):
    item: ExportHistoryItem
    quality: QualityReport | None
    artifact_sha256: str | None
