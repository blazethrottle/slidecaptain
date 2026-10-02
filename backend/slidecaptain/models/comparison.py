"""지표 비교 입력과 결정론 판정. 입력 의미의 진실성이나 산식을 검증하지 않는다."""

import calendar
from datetime import date
from fractions import Fraction
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator, model_serializer

MetricText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
MetricId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]+$", max_length=64)]


class ComparisonModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MetricPeriod(ComparisonModel):
    start: date
    end: date
    grain: Literal["month", "quarter", "year", "point", "custom"]
    aggregation: Literal["sum", "average", "ratio", "point", "other"]
    coverage: Literal["complete", "partial", "unknown"]

    @model_validator(mode="after")
    def _ordered(self) -> "MetricPeriod":
        if self.end < self.start:
            raise ValueError("비교 기간의 끝은 시작보다 앞설 수 없습니다")
        return self


class MetricDenominator(ComparisonModel):
    kind: Literal["none", "population", "unknown"]
    definition: MetricText | None = None

    @model_validator(mode="after")
    def _not_applicable(self) -> "MetricDenominator":
        if self.kind == "none" and self.definition is not None:
            raise ValueError("분모가 해당 없음이면 분모 정의를 함께 지정할 수 없습니다")
        return self


class MetricBasis(ComparisonModel):
    definition: MetricText | None = None
    unit: MetricText | None = None
    entity: MetricText | None = None
    period: MetricPeriod | None = None
    denominator: MetricDenominator | None = None


ScaleUnit = Literal["원", "천원", "만원", "백만원", "억원", "명", "천명", "건", "천건"]
UNIT_SCALES = {
    "원": ("KRW", 1), "천원": ("KRW", 1000), "만원": ("KRW", 10000),
    "백만원": ("KRW", 1000000), "억원": ("KRW", 100000000),
    "명": ("people", 1), "천명": ("people", 1000),
    "건": ("events", 1), "천건": ("events", 1000),
}


class UnitNormalization(ComparisonModel):
    rule_version: Literal["unit-scale-v1"]
    target_unit: ScaleUnit


def unit_scale_factor(source_unit: str | None, target_unit: str) -> Fraction | None:
    source, target = UNIT_SCALES.get(source_unit), UNIT_SCALES.get(target_unit)
    if source is None or target is None or source[0] != target[0]:
        return None
    return Fraction(source[1], target[1])


class EvidenceComparison(ComparisonModel):
    id: MetricId
    claim_id: MetricId
    left_evidence_id: MetricId
    right_evidence_id: MetricId
    axis: Literal["entity", "period"]
    unit_normalization: UnitNormalization | None = None

    @model_serializer(mode="wrap")
    def _legacy_serialization(self, handler):
        payload = handler(self)
        if self.unit_normalization is None:
            payload.pop("unit_normalization", None)
        return payload

    @model_validator(mode="after")
    def _distinct(self) -> "EvidenceComparison":
        if self.left_evidence_id == self.right_evidence_id:
            raise ValueError("비교에는 서로 다른 두 근거가 필요합니다")
        return self


class ComparisonReason(ComparisonModel):
    code: Literal[
        "missing_metadata", "definition_mismatch", "unit_mismatch", "denominator_mismatch",
        "entity_mismatch", "period_mismatch", "period_basis_mismatch", "incomplete_period",
        "overlapping_periods", "unsupported_period", "same_axis_value", "unsupported_normalization",
    ]
    field: str
    message: str
    evidence_id: MetricId | None = None


class ComparisonAssessment(ComparisonModel):
    comparison_id: MetricId
    rule_version: Literal["q2b-v1", "q2e-v1"] = "q2b-v1"
    status: Literal["compatible", "incompatible", "insufficient_metadata"]
    reasons: list[ComparisonReason]


def _supported_period(period: MetricPeriod) -> bool:
    """정확한 달력 경계만 지원한다. 월/연을 고정 일수로 환산하지 않는다."""
    start, end = period.start, period.end
    if period.grain == "point" or period.aggregation == "point":
        return period.grain == "point" and period.aggregation == "point" and start == end
    if period.aggregation == "other" or start.year != end.year or start.day != 1:
        return False
    if end.day != calendar.monthrange(end.year, end.month)[1]:
        return False
    if period.grain == "month":
        return start.month == end.month
    if period.grain == "quarter":
        return start.month in (1, 4, 7, 10) and end.month == start.month + 2
    if period.grain == "year":
        return start.month == 1 and end.month == 12
    return False


def assess_comparison(
    comparison: EvidenceComparison,
    left: MetricBasis | None, right: MetricBasis | None,
    left_value: str | None, right_value: str | None,
) -> ComparisonAssessment:
    """결측을 일치로 취급하지 않고, 두 입력에 선언된 조건만 대조한다."""
    reasons: list[ComparisonReason] = []
    incompatible = False

    def issue(code, field, message, evidence_id=None, *, conflict=False):
        nonlocal incompatible
        incompatible |= conflict
        reasons.append(ComparisonReason(code=code, field=field, message=message, evidence_id=evidence_id))

    fields = {"definition": "지표 정의", "unit": "단위", "entity": "주체", "period": "기간", "denominator": "분모"}
    for eid, basis, value in (
        (comparison.left_evidence_id, left, left_value),
        (comparison.right_evidence_id, right, right_value),
    ):
        if value is None:
            issue("missing_metadata", "value", "원문에서 비교할 값을 지정하지 않았습니다.", eid)
        if basis is None:
            issue("missing_metadata", "metric_basis", "지표의 비교 조건이 없습니다.", eid)
            continue
        for field, label in fields.items():
            if getattr(basis, field) is None:
                issue("missing_metadata", field, f"{label} 정보가 없습니다.", eid)
        denominator = basis.denominator
        if denominator is not None and (
            denominator.kind == "unknown"
            or (denominator.kind == "population" and denominator.definition is None)
        ):
            issue("missing_metadata", "denominator", "분모의 모집단 정의가 확인되지 않았습니다.", eid)
        period = basis.period
        if period is not None:
            if period.coverage == "unknown":
                issue("missing_metadata", "period.coverage", "전체 기간을 포함하는지 확인되지 않았습니다.", eid)
            elif period.coverage == "partial":
                issue("incomplete_period", "period.coverage", "부분 기간은 직접 비교하지 않습니다.", eid, conflict=True)
            if not _supported_period(period):
                issue("unsupported_period", "period", "지원하는 완결 월/분기/연 또는 시점 기준이 아닙니다.", eid)
            if period.aggregation == "ratio" and denominator is not None and denominator.kind == "none":
                issue("missing_metadata", "denominator", "비율 지표에는 분모의 모집단 정의가 필요합니다.", eid)

    if left is not None and right is not None:
        if comparison.unit_normalization is not None:
            target = comparison.unit_normalization.target_unit
            for basis in (left, right):
                if basis.unit is not None and unit_scale_factor(basis.unit, target) is None:
                    issue("unsupported_normalization", "unit_normalization", "지원하는 같은 차원의 단위 배율만 환산할 수 있습니다.", conflict=True)
                if (basis.period is not None and basis.period.aggregation == "ratio"
                        or basis.denominator is not None and basis.denominator.kind == "population"):
                    issue("unsupported_normalization", "unit_normalization", "비율과 분모가 있는 지표는 단위 배율로 환산하지 않습니다.", conflict=True)
        for field in ("definition", "unit"):
            if field == "unit" and comparison.unit_normalization is not None:
                continue
            a, b = getattr(left, field), getattr(right, field)
            if a is not None and b is not None and a != b:
                issue(f"{field}_mismatch", field, f"두 근거의 {fields[field]}가 다릅니다.", conflict=True)
        a, b = left.denominator, right.denominator
        if a is not None and b is not None and a.kind != "unknown" and b.kind != "unknown":
            if a.kind != b.kind or (a.definition is not None and b.definition is not None and a.definition != b.definition):
                issue("denominator_mismatch", "denominator", "분모의 종류 또는 모집단 정의가 다릅니다.", conflict=True)
        if left.entity is not None and right.entity is not None:
            if comparison.axis == "period" and left.entity != right.entity:
                issue("entity_mismatch", "entity", "기간 비교에는 같은 주체가 필요합니다.", conflict=True)
            elif comparison.axis == "entity" and left.entity == right.entity:
                issue("same_axis_value", "entity", "주체 비교에 같은 주체를 지정했습니다.", conflict=True)
        p, q = left.period, right.period
        if p is not None and q is not None:
            if p.grain != q.grain or p.aggregation != q.aggregation:
                issue("period_basis_mismatch", "period", "기간 단위 또는 집계 방식이 다릅니다.", conflict=True)
            if comparison.axis == "entity" and (p.start != q.start or p.end != q.end):
                issue("period_mismatch", "period", "주체 비교에는 같은 시작일과 종료일이 필요합니다.", conflict=True)
            elif comparison.axis == "period" and max(p.start, q.start) <= min(p.end, q.end):
                issue("overlapping_periods", "period", "비교 기간이 중복되거나 겹칩니다.", conflict=True)

    status = "incompatible" if incompatible else "insufficient_metadata" if reasons else "compatible"
    return ComparisonAssessment(comparison_id=comparison.id, rule_version="q2e-v1" if comparison.unit_normalization else "q2b-v1", status=status, reasons=reasons)
