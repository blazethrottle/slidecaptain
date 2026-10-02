"""Server-recorded change notice, never a review approval."""

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class DocumentChangeReview(BaseModel):
    model_config = ConfigDict(extra='forbid', revalidate_instances='always')
    rule_version: Literal['document-change-v1'] = 'document-change-v1'
    reason: Literal['document_replacement','evidence_migration']
    base_fingerprint: str = Field(pattern=r'^[a-f0-9]{64}$')
    changed_paths: list[str] = Field(min_length=1,max_length=1000)
    requires_independent_review: Literal[True] = True
