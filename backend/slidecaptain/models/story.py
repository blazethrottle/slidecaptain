"""Q2a 보고 계획 계약. 근거의 존재와 연결을 검사하며 의미의 진실성을 보증하지 않는다."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_serializer, model_validator
from pydantic_core import PydanticCustomError

from slidecaptain.models.comparison import (
    ComparisonAssessment, EvidenceComparison, MetricBasis, assess_comparison,
)
from slidecaptain.models.derivation import Derivation, DerivedValue, derive_value

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Identifier = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]+$", max_length=64)]
ReportType = Literal[
    "research", "approval", "strategy", "weekly", "business", "monthly", "data", "project", "results",
]
ChapterRole = Literal["answer", "context", "evidence", "risk", "action", "cover", "divider"]


class StoryModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReportBrief(StoryModel):
    decision_question: Text
    audience: str = ""
    report_type: ReportType = "research"
    reading_profile: Text = "미지정"
    constraints: list[Text] = []


class SourceLocator(StoryModel):
    """sources/에 저장된 추출 텍스트의 1부터 시작하는 행 범위 (양끝 포함)."""

    line_start: int = Field(ge=1, strict=True)
    line_end: int = Field(ge=1, strict=True)

    @model_validator(mode="after")
    def _ordered(self) -> "SourceLocator":
        if self.line_end < self.line_start:
            raise ValueError("근거의 끝 행은 시작 행보다 앞설 수 없습니다")
        return self


class EvidenceSelection(StoryModel):
    id: Identifier
    source_id: str = Field(min_length=1)  # 파일명과 원문 문자는 정규화하지 않는다
    locator: SourceLocator
    value: Text | None = None
    unit: Text | None = None
    period: Text | None = None
    entity: Text | None = None
    denominator: Text | None = None
    metric_basis: MetricBasis | None = None


class Evidence(EvidenceSelection):
    source_revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    excerpt: str = Field(min_length=1)


class Claim(StoryModel):
    id: Identifier
    statement: Text
    kind: Literal["fact", "inference", "proposal", "unknown"]
    evidence_ids: list[Identifier]
    caveats: list[Text]

    @model_validator(mode="after")
    def _support_and_uncertainty(self) -> "Claim":
        if self.kind == "fact" and not self.evidence_ids:
            raise ValueError("사실 주장은 원문 근거가 필요합니다")
        if self.kind in ("inference", "unknown") and not self.caveats:
            raise ValueError("추정과 미확인 주장은 조건이나 확인할 사항이 필요합니다")
        unique_ids(self.evidence_ids, "주장의 근거")
        return self


class StoryChapter(StoryModel):
    chapter_id: Identifier
    role: ChapterRole
    claim_ids: list[Identifier]


def unique_ids(ids: list[str], label: str) -> set[str]:
    if len(ids) != len(set(ids)):
        raise ValueError(f"{label} ID가 중복되었습니다")
    return set(ids)


class RewriteReview(StoryModel):
    """재작성 당시 보존한 본문 기록. 후속 편집의 검수 승인 원장이 아니다."""

    source_plan_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    preserved_chapter_ids: list[str]


class StoryPlan(StoryModel):
    version: Literal["q2a-v1", "q2b-v1", "q2c-v1", "q2e-v1"] = "q2a-v1"
    brief: ReportBrief
    evidence: list[Evidence]
    claims: list[Claim] = Field(min_length=1)
    answer_claim_ids: list[Identifier] = Field(min_length=1)
    # 목록 순서가 장 순서다. 별도 자유 문자열 요약 대신 답변의 주장 ID를 사용한다.
    chapters: list[StoryChapter] = Field(min_length=1)
    unanswered_questions: list[Text]
    comparisons: list[EvidenceComparison] = []
    comparison_results: list[ComparisonAssessment] = []
    derivations: list[Derivation] = []
    derived_values: list[DerivedValue] = []
    input_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    rewrite_review: RewriteReview | None = None

    @model_serializer(mode="wrap")
    def _legacy_serialization(self, handler):
        payload = handler(self)
        # 기존 저장 JSON 및 모든 fingerprint 소비자의 바이트 계약을 유지한다.
        if self.rewrite_review is None:
            payload.pop("rewrite_review", None)
        return payload

    @model_validator(mode="after")
    def _references(self) -> "StoryPlan":
        evidence_ids = unique_ids([e.id for e in self.evidence], "근거")
        claim_ids = unique_ids([c.id for c in self.claims], "주장")
        unique_ids([ch.chapter_id for ch in self.chapters], "계획의 장")
        answer_ids = unique_ids(self.answer_claim_ids, "핵심 답변")
        if not answer_ids <= claim_ids:
            raise ValueError("핵심 답변이 존재하지 않는 주장을 가리킵니다")
        for claim in self.claims:
            if not set(claim.evidence_ids) <= evidence_ids:
                raise ValueError(f"주장 {claim.id}이 존재하지 않는 근거를 가리킵니다")
        assigned: set[str] = set()
        answers: set[str] = set()
        for chapter in self.chapters:
            refs = unique_ids(chapter.claim_ids, "장별 주장")
            if not refs <= claim_ids:
                raise ValueError(f"장 {chapter.chapter_id}이 존재하지 않는 주장을 가리킵니다")
            if chapter.role in ("cover", "divider") and refs:
                raise ValueError("표지와 간지 대신 본문 장에 주장을 연결해야 합니다")
            if chapter.role not in ("cover", "divider") and not refs:
                raise ValueError("본문 장에는 뒷받침할 주장이 필요합니다")
            assigned |= refs
            if chapter.role == "answer":
                answers |= refs
        if assigned != claim_ids:
            raise ValueError("보고 계획에 어느 장에도 연결되지 않은 주장이 있습니다")
        if not answer_ids <= answers:
            raise PydanticCustomError("answer_not_in_summary", "핵심 답변의 주장은 답변 역할의 장에 연결해야 합니다")
        if any(c.kind == "unknown" for c in self.claims) and not self.unanswered_questions:
            raise ValueError("미확인 주장이 있으면 확인할 질문을 남겨야 합니다")
        if self.version == "q2a-v1" and (
            self.comparisons or self.comparison_results or any(e.metric_basis is not None for e in self.evidence)
        ):
            raise ValueError("지표 비교 계약은 q2b-v1 계획에만 사용할 수 있습니다")
        if self.version != "q2e-v1" and (any(c.unit_normalization is not None for c in self.comparisons)
                or any(v.unit_conversions for v in self.derived_values)):
            raise ValueError("명시적 단위 환산은 q2e-v1 계획에만 사용할 수 있습니다")
        unique_ids([c.id for c in self.comparisons], "비교")
        by_evidence = {e.id: e for e in self.evidence}
        by_claim = {c.id: c for c in self.claims}
        results = []
        for comparison in self.comparisons:
            pair = {comparison.left_evidence_id, comparison.right_evidence_id}
            if comparison.claim_id not in by_claim or not pair <= evidence_ids:
                raise ValueError("비교가 존재하지 않는 주장 또는 근거를 가리킵니다")
            if not pair <= set(by_claim[comparison.claim_id].evidence_ids):
                raise ValueError("비교의 두 근거를 해당 주장에 연결해야 합니다")
            left = by_evidence[comparison.left_evidence_id]
            right = by_evidence[comparison.right_evidence_id]
            results.append(assess_comparison(comparison, left.metric_basis, right.metric_basis, left.value, right.value))
        # API와 저장 파일의 결과를 신뢰하지 않는다. 편집한 입력에서 매번 재계산한다.
        self.comparison_results = results
        if self.version not in ("q2c-v1", "q2e-v1") and (self.derivations or self.derived_values):
            raise ValueError("수치 계산 계약은 q2c-v1 계획에만 사용할 수 있습니다")
        unique_ids([d.id for d in self.derivations], "계산")
        by_comparison = {c.id: c for c in self.comparisons}
        by_result = {r.comparison_id: r for r in results}
        derived = []
        for derivation in self.derivations:
            if derivation.comparison_id not in by_comparison:
                raise ValueError("계산이 존재하지 않는 비교를 가리킵니다")
            comparison = by_comparison[derivation.comparison_id]
            derived.append(derive_value(
                derivation, comparison, by_result[comparison.id],
                by_evidence[comparison.left_evidence_id], by_evidence[comparison.right_evidence_id],
            ))
        self.derived_values = derived
        return self
