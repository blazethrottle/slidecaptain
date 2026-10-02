import type { StoryPlan } from "../api/client";

const OPERATION_LABELS = { difference: "차이", percent_change: "기준 대비 증감률" };

export function DerivedValuesView({ plan }: { plan: StoryPlan }) {
  const derivations = plan.derivations ?? [];
  const results = new Map((plan.derived_values ?? []).map((result) => [result.derivation_id, result]));
  const comparisons = new Map((plan.comparisons ?? []).map((comparison) => [comparison.id, comparison]));
  const comparisonsChecked = new Map((plan.comparison_results ?? []).map((result) => [result.comparison_id, result]));
  const evidence = new Map(plan.evidence.map((item) => [item.id, item]));
  const claims = new Map(plan.claims.map((claim) => [claim.id, claim]));
  const checked = derivations.filter((derivation) => results.has(derivation.id)).length;
  const blocked = derivations.filter((derivation) => results.get(derivation.id)?.status === "blocked").length;

  function sourceLabel(id: string | undefined) {
    const item = id ? evidence.get(id) : undefined;
    return item ? `${item.source_id} (${item.locator.line_start}~${item.locator.line_end}행)` : "원문 위치 미확인";
  }

  return <section aria-label="수치 계산">
    <h3>수치 계산</h3>
    <p>계산 대상 {derivations.length}건 / 계산 불가 {blocked}건 / 미계산 {derivations.length - checked}건</p>
    {derivations.length === 0 ? <p>등록된 산식이 없어 계산하지 않았습니다.</p> : <>
      <p className="notice">계산에는 연결된 원문 값과 산식을 사용합니다. 원문 해석과 산식 선택이 타당한지, 보고 문장이 결과를 올바르게 설명하는지는 별도로 확인해야 합니다.</p>
      <ul>{derivations.map((derivation) => {
        const result = results.get(derivation.id);
        const comparison = comparisons.get(derivation.comparison_id);
        const left = comparison ? evidence.get(comparison.left_evidence_id) : undefined;
        const right = comparison ? evidence.get(comparison.right_evidence_id) : undefined;
        return <li key={derivation.id}>
          <p><strong>{OPERATION_LABELS[derivation.operation]}</strong>: {comparison ? claims.get(comparison.claim_id)?.statement ?? "주장 미확인" : "비교 미확인"}</p>
          <p>대상값: {left?.value ?? "미확인"} / {sourceLabel(left?.id)}</p>
          <p>기준값: {right?.value ?? "미확인"} / {sourceLabel(right?.id)}</p>
          {comparison?.unit_normalization && <p>비교할 단위: {comparison.unit_normalization.target_unit}. 등록된 배율로 환산하며 원문 값은 보존합니다.</p>}
          {!!result?.unit_conversions?.length && <ul aria-label="단위 환산 근거">
            {result.unit_conversions.map((conversion) => <li key={conversion.evidence_id}>
              {sourceLabel(conversion.evidence_id)}: {conversion.original_value} ({conversion.original_unit}) → {conversion.normalized_value} {conversion.target_unit}.
              적용 배율: {conversion.factor_numerator}/{conversion.factor_denominator}.
            </li>)}
          </ul>}
          {result && <p>산식: {result.formula}</p>}
          {result?.status === "computed" ? <>
            <p><strong>계산 결과: {result.value} {result.unit}</strong></p>
            {result.rounded && <p>소수 최대 6자리로 반올림했습니다.</p>}
          </> : <p><strong>{result ? "계산 불가" : "미계산"}</strong></p>}
          {result && result.reasons.length > 0 && <ul>{result.reasons.map((reason, index) => <li key={index}>
            {reason.evidence_id && `${sourceLabel(reason.evidence_id)}: `}{reason.message}
          </li>)}</ul>}
          {result?.reasons.some((reason) => reason.code === "comparison_blocked") && <ul>
            {comparisonsChecked.get(derivation.comparison_id)?.reasons.map((reason, index) => <li key={index}>
              {reason.evidence_id && `${sourceLabel(reason.evidence_id)}: `}{reason.message}
            </li>)}
          </ul>}
        </li>;
      })}</ul>
    </>}
  </section>;
}
