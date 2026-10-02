"""Explicit manual changes and evidence transfers. No client approval verdicts."""

from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from slidecaptain.models.deck import Deck
from slidecaptain.models.story import EvidenceSelection, Identifier

Hash = str


class ChangeModel(BaseModel):
    model_config = ConfigDict(extra='forbid',revalidate_instances='always')


class LossItem(ChangeModel):
    id: str = Field(pattern=r'^[a-f0-9]{64}$')
    path: str
    kind: Literal['added','deleted','replaced','reordered']
    before: Any
    after: Any


class DocumentChangeRequest(ChangeModel):
    candidate: Deck
    expected_source_fingerprint: str = Field(pattern=r'^[a-f0-9]{64}$')


class EvidenceMigrationRequest(ChangeModel):
    evidence_id: Identifier
    old_evidence_fingerprint: str = Field(pattern=r'^[a-f0-9]{64}$')
    new_selection: EvidenceSelection
    expected_source_fingerprint: str = Field(pattern=r'^[a-f0-9]{64}$')

    @model_validator(mode='after')
    def same_identity(self):
        if self.evidence_id != self.new_selection.id:
            raise ValueError('근거 이동은 기존 근거 ID를 보존해야 합니다.')
        return self


class ChangeConfirmation(ChangeModel):
    confirmation_token: str = Field(pattern=r'^[a-f0-9]{64}$')
    acknowledged_loss_ids: list[str] = Field(max_length=1000)


class DocumentChangeApplyRequest(DocumentChangeRequest,ChangeConfirmation):
    pass


class EvidenceMigrationApplyRequest(EvidenceMigrationRequest,ChangeConfirmation):
    pass


class DocumentChangePreview(ChangeModel):
    rule_version: Literal['document-change-v1'] = 'document-change-v1'
    reason: Literal['document_replacement','evidence_migration']
    base_fingerprint: str = Field(pattern=r'^[a-f0-9]{64}$')
    sources_fingerprint: str = Field(pattern=r'^[a-f0-9]{64}$')
    candidate_fingerprint: str = Field(pattern=r'^[a-f0-9]{64}$')
    candidate: Deck
    losses: list[LossItem] = Field(min_length=1,max_length=1000)
    confirmation_token: str = Field(pattern=r'^[a-f0-9]{64}$')
    final_export_allowed: Literal[False] = False
    notice: str = '변경 후보입니다. 근거 이동의 의미, 문서 내용과 실제 표시를 검수하지 않았습니다. 적용 후 현재 PPTX의 독립 검수가 필요합니다.'
