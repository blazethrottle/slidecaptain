import type { StoryPlan } from "../api/client";
import { DerivedValuesView } from "./DerivedValuesView";

const KIND_LABELS = { fact: "사실", inference: "추정", proposal: "제안", unknown: "미확인" };
const COMPARISON_LABELS = { compatible: "입력 조건 일치", incompatible: "비교 불가", insufficient_metadata: "정보 부족" };
const GRAIN_LABELS = { month: "월", quarter: "분기", year: "연", point: "시점", custom: "기타 기간" };
const AGGREGATION_LABELS = { sum: "합계", average: "평균", ratio: "비율", point: "시점 값", other: "기타 집계" };
const COVERAGE_LABELS = { complete: "전체 기간", partial: "부분 기간", unknown: "범위 미확인" };
type Evidence = StoryPlan["evidence"][number];

function sourceLabel(evidence: Evidence | undefined) {
  return evidence ? `${evidence.source_id} (${evidence.locator.line_start}~${evidence.locator.line_end}행)` : "원문 위치 미확인";
}

function basisRows(evidence: Evidence | undefined): string[] {
  const basis = evidence?.metric_basis;
  const period = basis?.period;
  const denominator = basis?.denominator;
  return [
    evidence?.value ?? "미확인", basis?.definition ?? "미확인", basis?.unit ?? "미확인", basis?.entity ?? "미확인",
    period ? `${period.start}~${period.end} / ${GRAIN_LABELS[period.grain]} / ${AGGREGATION_LABELS[period.aggregation]} / ${COVERAGE_LABELS[period.coverage]}` : "미확인",
    denominator?.kind === "none" ? "해당 없음" : denominator?.kind === "population" ? denominator.definition ?? "모집단 미확인" : "미확인",
  ];
}

function ComparisonsView({ plan }: { plan: StoryPlan }) {
  const comparisons = plan.comparisons ?? [];
  const results = new Map((plan.comparison_results ?? []).map((result) => [result.comparison_id, result]));
  const evidence = new Map(plan.evidence.map((item) => [item.id, item]));
  const claims = new Map(plan.claims.map((claim) => [claim.id, claim]));
  const checked = comparisons.filter((comparison) => results.has(comparison.id)).length;
  const blocked = comparisons.filter((comparison) => {
    const result = results.get(comparison.id);
    return result && result.status !== "compatible";
  }).length;
  return (
    <section aria-label="지표 비교">
      <h3>지표 비교</h3>
      <p>검사 대상 {comparisons.length}건 / 비교 불가 또는 정보 부족 {blocked}건 / 미검사 {comparisons.length - checked}건</p>
      {comparisons.length === 0 ? <p>등록된 비교가 없어 검사하지 않았습니다.</p> : <>
        <p className="notice">등록된 비교의 입력 조건만 대조했습니다. 원문 해석의 정확성, 계산과 등록되지 않은 비교 주장은 별도로 확인해야 합니다.</p>
        <ul>{comparisons.map((comparison) => {
          const result = results.get(comparison.id);
          const left = evidence.get(comparison.left_evidence_id);
          const right = evidence.get(comparison.right_evidence_id);
          const leftRows = basisRows(left);
          const rightRows = basisRows(right);
          return <li key={comparison.id}>
            <p><strong>{result ? COMPARISON_LABELS[result.status] : "미검사"}</strong>: {claims.get(comparison.claim_id)?.statement ?? "주장 미확인"}</p>
            <p>{comparison.axis === "entity" ? "주체 비교" : "기간 비교"}: {sourceLabel(left)} / {sourceLabel(right)}</p>
            {result && result.reasons.length > 0 && <ul>{result.reasons.map((reason, i) => <li key={i}>
              {reason.evidence_id && `${sourceLabel(evidence.get(reason.evidence_id))}: `}{reason.message}
            </li>)}</ul>}
            <details>
              <summary>비교 조건 보기</summary>
              <table>
                <thead><tr><th scope="col">조건</th><th scope="col">첫 번째 근거</th><th scope="col">두 번째 근거</th></tr></thead>
                <tbody>{["값", "지표 정의", "단위", "주체", "기간과 집계", "분모"].map((label, i) =>
                  <tr key={label}><th scope="row">{label}</th><td>{leftRows[i]}</td><td>{rightRows[i]}</td></tr>)}</tbody>
              </table>
            </details>
          </li>;
        })}</ul>
      </>}
    </section>
  );
}

export function StoryPlanView({ plan }: { plan: StoryPlan }) {
  const answers = plan.claims.filter((claim) => plan.answer_claim_ids.includes(claim.id));
  return (
    <section aria-label="보고 계획">
      <h2>보고 계획</h2>
      <p>{plan.brief.decision_question}</p>
      <p className="notice">근거 위치를 연결한 초안입니다. 주장과 자료의 의미가 맞는지는 별도로 확인해야 합니다.</p>
      {plan.rewrite_review && <p className="notice">기존 본문을 보존한 재작성입니다. 재작성 당시 {plan.rewrite_review.preserved_chapter_ids.length}개 장의 내용을 유지했습니다. 새 계획과 본문의 주장, 수치와 흐름은 별도 재검토가 필요하며 이후 편집의 검수 완료를 뜻하지 않습니다.</p>}
      <h3>핵심 판단</h3>
      <ul>{answers.map((claim) => <li key={claim.id}>
        [{KIND_LABELS[claim.kind]}] {claim.statement}
        {claim.caveats.length > 0 && <p>조건: {claim.caveats.join(" / ")}</p>}
      </li>)}</ul>
      <details>
        <summary>주장별 근거와 조건</summary>
        <ul>{plan.claims.map((claim) => <li key={claim.id}>
          [{KIND_LABELS[claim.kind]}] {claim.statement}
          {claim.caveats.length > 0 && <p>조건: {claim.caveats.join(" / ")}</p>}
          {claim.evidence_ids.length === 0 && <p>연결된 원문 근거가 없습니다.</p>}
          {plan.evidence.filter((e) => claim.evidence_ids.includes(e.id)).map((e) => <blockquote key={e.id}>
            <p>{e.source_id} ({e.locator.line_start}~{e.locator.line_end}행)</p>
            <p style={{ whiteSpace: "pre-wrap" }}>{e.excerpt}</p>
            {[e.entity, e.period, e.unit, e.denominator].some(Boolean) &&
              <p>{[e.entity, e.period, e.unit, e.denominator].filter(Boolean).join(" / ")}</p>}
          </blockquote>)}
        </li>)}</ul>
      </details>
      <ComparisonsView plan={plan} />
      <DerivedValuesView plan={plan} />
      {plan.unanswered_questions.length > 0 && <>
        <h3>확인할 질문</h3>
        <ul>{plan.unanswered_questions.map((question, i) => <li key={i}>{question}</li>)}</ul>
      </>}
      <p className="notice">보고 정보, 자료 또는 구조안을 바꾸면 장 내용을 생성하기 전에 보고 계획을 다시 확인해야 합니다. 구성 단계에서 기존 편집을 보존하는 계획 재작성을 사용할 수 있습니다.</p>
    </section>
  );
}
