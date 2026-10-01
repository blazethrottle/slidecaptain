"""원문 값과 선언된 비교에서 계산한다. 등록된 단위 배율만 환산하며 자유 수식/의미 검수는 지원하지 않는다."""

from decimal import Decimal, ROUND_HALF_UP, localcontext
from fractions import Fraction
import re
from typing import TYPE_CHECKING, Literal

from pydantic import Field

from slidecaptain.models.comparison import ComparisonAssessment, ComparisonModel, EvidenceComparison, MetricId, ScaleUnit, unit_scale_factor

if TYPE_CHECKING:
    from slidecaptain.models.story import Evidence


class Derivation(ComparisonModel):
    id: MetricId
    comparison_id: MetricId
    operation: Literal["difference", "percent_change"]


class DerivationReason(ComparisonModel):
    code: Literal[
        "comparison_blocked", "missing_value", "invalid_number", "numeric_limit",
        "ambiguous_numeric_token", "value_not_in_excerpt", "zero_baseline",
        "negative_baseline", "unsupported_metric", "reversed_period",
    ]
    message: str
    evidence_id: MetricId | None = None


class UnitConversion(ComparisonModel):
    rule_version: Literal["unit-scale-v1"] = "unit-scale-v1"
    evidence_id: MetricId
    original_value: str
    original_unit: ScaleUnit
    target_unit: ScaleUnit
    factor_numerator: str
    factor_denominator: str
    normalized_value: str


class DerivedValue(ComparisonModel):
    derivation_id: MetricId
    rule_version: Literal["q2c-v1", "q2e-v1"] = "q2c-v1"
    status: Literal["computed", "blocked"]
    formula: str
    value: str | None = None
    unit: str | None = None
    rounded: bool | None = None
    reasons: list[DerivationReason] = []
    unit_conversions: list[UnitConversion] = Field(default_factory=list, exclude_if=lambda value: not value)


# 숫자 전체를 읽는다. ASCII 이외의 부호/숫자나 모호한 구분자를 보정하지 않는다.
_NUMBER = r"[+-]?(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?"


def _parse_operand(evidence: "Evidence", reasons: list[DerivationReason]) -> Decimal | None:
    def reject(code, message):
        reasons.append(DerivationReason(code=code, message=message, evidence_id=evidence.id))
        return None

    raw = evidence.value
    if raw is None:
        return reject("missing_value", "계산할 원문 값이 없습니다.")
    if len(raw) > 128:
        return reject("numeric_limit", "원문 값은 최대 128자까지 계산합니다.")
    unit = evidence.metric_basis.unit if evidence.metric_basis else None
    suffix = rf"(?:[ \t]*{re.escape(unit)})?" if unit else ""
    match = re.fullmatch(rf"(?P<number>{_NUMBER}){suffix}", raw)
    if match is None:
        return reject("invalid_number", "명확한 정수/소수와 일치하는 단위 표기만 계산합니다. 범위, '약'이 붙은 값, 지수와 복합 표기는 지원하지 않습니다.")
    token = match["number"].replace(",", "")
    if sum(c.isdigit() for c in token) > 24 or ("." in token and len(token.rsplit(".", 1)[1]) > 6):
        return reject("numeric_limit", "원문 숫자는 최대 24자리, 소수 최대 6자리까지 계산합니다.")
    occurrences = list(re.finditer(re.escape(raw), evidence.excerpt))
    if not occurrences:
        return reject("value_not_in_excerpt", "계산할 값이 연결된 원문 발췌에 없습니다.")
    # 120에서 20, -120에서 120, 1e3에서 3만 선택해도 문자열 포함 검사는 통과한다.
    # 원문 표기가 더 긴 숫자/단위 토큰이면 계산에 쓰지 않는다.
    def whole_value(occurrence):
        before = evidence.excerpt[:occurrence.start()]
        after = evidence.excerpt[occurrence.end():]
        prefix = before.rstrip()
        if prefix and (prefix[-1].isdigit() or prefix[-1] in "+-−~～" or prefix[-1].isascii() and prefix[-1].isalpha()):
            return False
        if re.search(r"[0-9][.,]$|(?:약|대략|최소|최대)\s*$", before):
            return False
        if before.endswith("(") and after.startswith(")"):
            return False
        # unit을 value에서 생략한 경우에는 정확히 같은 원문 단위만 허용한다.
        has_unit = match.end("number") != len(raw)
        if not has_unit and unit:
            unit_match = re.match(rf"[ \t]*{re.escape(unit)}", after)
            if unit_match:
                after = after[unit_match.end():]
                has_unit = True
        if not after:
            return True
        if after[0].isdigit() or after[0] in "%‰+-−~～" or re.match(r"[.,][0-9]", after):
            return False
        if after[0].isalpha() and not re.match(r"(?:은|는|이|가|을|를|와|과|의|으로|보다)", after):
            return False
        if not has_unit and after.lstrip() and after.lstrip()[0].isalpha():
            return False
        if re.match(r"\s*(?:[~～+−%‰-]|[0-9]|미만|이상|이하|초과)", after):
            return False
        return True

    if not any(whole_value(occurrence) for occurrence in occurrences):
        return reject("ambiguous_numeric_token", "원문 숫자의 일부이거나 다른 숫자/단위 표기가 이어져 계산할 값을 확정할 수 없습니다.")
    return Decimal(token)


def derive_value(
    derivation: Derivation, comparison: EvidenceComparison, assessment: ComparisonAssessment,
    left: "Evidence", right: "Evidence",
) -> DerivedValue:
    """왼쪽=대상값, 오른쪽=기준값. 실패는 결과 값 없이 이유를 반환한다."""
    formula = "대상값 - 기준값" if derivation.operation == "difference" else "(대상값 - 기준값) / 기준값 × 100"
    reasons: list[DerivationReason] = []

    def issue(code, message):
        reasons.append(DerivationReason(code=code, message=message))

    if assessment.status != "compatible":
        issue("comparison_blocked", "비교 조건이 일치하지 않거나 정보가 부족합니다. 연결된 지표 비교 사유를 확인해 주세요.")
    a, b = _parse_operand(left, reasons), _parse_operand(right, reasons)
    basis = left.metric_basis
    unit = basis.unit if basis else None
    if assessment.status == "compatible":
        # 비교 검사가 필수 메타데이터의 존재와 양쪽 일치를 이미 확인했다.
        assert basis is not None and basis.period is not None and basis.denominator is not None
        percentage = unit == "%" and basis.period.aggregation == "ratio" and basis.denominator.kind == "population"
        absolute = unit != "%" and basis.period.aggregation != "ratio" and basis.denominator.kind == "none"
        if percentage and derivation.operation == "difference":
            unit = "퍼센트포인트"
        elif not absolute:
            issue("unsupported_metric", "절대값의 차이/증감률과 모집단이 명시된 % 비율의 퍼센트포인트 차이만 지원합니다.")
        if derivation.operation == "percent_change" and comparison.axis == "period":
            assert right.metric_basis is not None and right.metric_basis.period is not None
            if basis.period.start <= right.metric_basis.period.end:
                issue("reversed_period", "증감률의 대상 기간은 기준 기간보다 뒤여야 합니다.")
    if derivation.operation == "percent_change" and b is not None:
        if b == 0:
            issue("zero_baseline", "기준값이 0이어서 증감률을 계산할 수 없습니다.")
        elif b < 0:
            issue("negative_baseline", "음수 기준값의 증감률은 지원하지 않습니다. 절대 차이를 확인해 주세요.")
    rule_version = "q2e-v1" if comparison.unit_normalization is not None else "q2c-v1"
    if reasons:
        return DerivedValue(derivation_id=derivation.id, rule_version=rule_version, status="blocked", formula=formula, reasons=reasons)

    assert a is not None and b is not None
    operands = [Fraction(a), Fraction(b)]
    conversions = []
    if comparison.unit_normalization is not None:
        target = comparison.unit_normalization.target_unit
        for index, evidence in enumerate((left, right)):
            original_unit = evidence.metric_basis.unit
            factor = unit_scale_factor(original_unit, target)
            # A compatible comparison already checked the registry dimension.
            assert factor is not None
            operands[index] *= factor
            with localcontext() as context:
                context.prec = 80  # raw <=24 digits and power-of-ten scale <=1e8
                normalized = Decimal(operands[index].numerator) / Decimal(operands[index].denominator)
            text = format(normalized, "f")
            text = text.rstrip("0").rstrip(".") if "." in text else text
            conversions.append(UnitConversion(
                evidence_id=evidence.id, original_value=evidence.value, original_unit=original_unit,
                target_unit=target, factor_numerator=str(factor.numerator),
                factor_denominator=str(factor.denominator), normalized_value=text if normalized else "0",
            ))
        unit = target
    exact = operands[0] - operands[1]
    if derivation.operation == "percent_change":
        exact = exact / operands[1] * 100
        unit = "%"
    # 입력 최대 24자리/소수 6자리에서 분자·분모를 충분히 표현한다.
    # Fraction과 다시 대조하여 끝나지 않는 나눗셈/표시 반올림을 숨기지 않는다.
    with localcontext() as context:
        context.prec = 80
        displayed = (Decimal(exact.numerator) / Decimal(exact.denominator)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
    value = format(displayed, "f").rstrip("0").rstrip(".") if displayed else "0"
    return DerivedValue(
        derivation_id=derivation.id, rule_version=rule_version, status="computed", formula=formula,
        unit_conversions=conversions,
        value=value, unit=unit, rounded=Fraction(displayed) != exact,
    )
