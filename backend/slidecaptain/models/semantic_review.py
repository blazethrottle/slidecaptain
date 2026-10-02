"""Deterministic review signals. Absence of signals is not semantic approval."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class SemanticRelatedText(BaseModel):
    chapter_id: str
    path: str
    text: str


class SemanticSuspect(BaseModel):
    model_config = ConfigDict(extra='forbid')
    code: Literal['unregistered_comparison','unregistered_formula','calculated_direction_mismatch','summary_direction_conflict']
    chapter_id: str
    path: str
    text: str
    signal: str
    message: str
    claim_ids: list[str]
    comparison_ids: list[str]
    derivation_ids: list[str]
    related_texts: list[SemanticRelatedText] = Field(default_factory=list)


class SemanticSuspectReport(BaseModel):
    rule_version: Literal['semantic-suspect-v1'] = 'semantic-suspect-v1'
    input_fingerprint: str
    status: Literal['not_run','needs_review','no_signals_detected']
    semantic_status: Literal['not_run'] = 'not_run'
    reason: Literal['missing_plan','stale_plan','invalid_plan','no_reviewable_fields','review_limit'] | None = None
    evaluated_fields: int
    findings: list[SemanticSuspect]
    scope_notice: str = '정의한 문구 탐지에서 검토 후보를 찾습니다. 후보가 없어도 원문 의미와 요약 정합성 검수는 미수행입니다.'
