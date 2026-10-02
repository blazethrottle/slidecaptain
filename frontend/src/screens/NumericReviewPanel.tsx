import { useEffect, useRef, useState } from "react";
import { api, messageOf, type Deck, type NumericReviewReport } from "../api/client";

type ReviewState = {
  deck: Deck;
  projectName: string;
  pending: boolean;
  report?: NumericReviewReport;
  error?: string;
};

const notRunMessages = {
  missing_plan: "보고 계획이 없어 대조하지 않았습니다. 보고 질문으로 구조안을 먼저 생성해 주세요.",
  stale_plan: "자료나 보고 계획이 바뀌어 대조하지 않았습니다. 수정 내용은 보존되어 있습니다. 구조안을 다시 생성해 주세요.",
  evidence_mismatch: "연결된 원문의 위치나 발췌가 현재 자료와 달라 대조하지 않았습니다. 보고 계획의 근거를 확인해 주세요.",
  no_numeric_fields: "대조할 숫자가 포함된 텍스트 칸이 없습니다. 검사 대상 0개는 통과를 뜻하지 않습니다.",
  no_computed_expressions: "연결할 계산 결과가 없어 대조하지 않았습니다. 구조안의 수치 계산과 계산 불가 사유를 확인해 주세요.",
};

export function NumericReviewPanel({ projectName, deck }: { projectName: string; deck: Deck }) {
  const [state, setState] = useState<ReviewState | null>(null);
  const requestId = useRef(0);
  useEffect(() => {
    // Edits, undo/redo, restore, project changes and unmount invalidate requests.
    requestId.current += 1;
    setState(null);
    return () => { requestId.current += 1; };
  }, [deck, projectName]);
  // The input guard also hides stale output before the effect has run.
  const current = state?.deck === deck && state.projectName === projectName ? state : null;
  const report = current?.report;

  const review = async () => {
    const id = ++requestId.current;
    setState({ deck, projectName, pending: true });
    try {
      const response = await api.reviewNumbers(projectName, deck);
      if (id === requestId.current) setState({ deck, projectName, pending: false, report: response });
    } catch (e) {
      if (id === requestId.current) setState({ deck, projectName, pending: false, error: messageOf(e) });
    }
  };

  return (
    <section aria-label="계산 문구 대조" className="numeric-review">
      <h3>계산 문구 대조</h3>
      <p>AI 호출 없이 전체 초안의 현재 편집본을 확인합니다.</p>
      <button onClick={() => void review()} disabled={current?.pending}>
        {current?.pending ? "대조 중..." : "계산 문구 대조"}
      </button>
      {current?.error && <p role="alert">{current.error}</p>}
      {report && (
        <div aria-live="polite">
          {report.status === "not_run" ? (
            <p>{report.reason ? notRunMessages[report.reason] : "계산 문구를 대조하지 않았습니다."}</p>
          ) : (
            <p>텍스트 칸 {report.evaluated}개 중 일치 {report.matched}개, 확인 필요 {report.unresolved}개.</p>
          )}
          <p className="numeric-review-notice">{report.notice}</p>
          {report.items.length > 0 && (
            <details open={report.unresolved > 0}>
              <summary>칸별 대조 결과</summary>
              <ul>
                {report.items.map((item) => (
                  <li key={`${item.chapter_id}:${item.path}`}>
                    <strong>{item.code === "matched" ? "일치" : "확인 필요"}</strong>
                    {" / "}{deck.structure.chapters.find((c) => c.id === item.chapter_id)?.topic ?? "장"}
                    <p className="numeric-review-text">{item.actual}</p>
                    <p>{item.message}</p>
                  </li>
                ))}
              </ul>
            </details>
          )}
          {report.expressions.length > 0 && (
            <details>
              <summary>연결 가능한 기준 문구와 자료</summary>
              <ul>
                {report.expressions.map((expression) => (
                  <li key={`${expression.chapter_id}:${expression.derivation_id}`}>
                    <p className="numeric-review-text">{expression.text}</p>
                    <p>산식: {expression.formula}</p>
                    <p>자료: {expression.source_ids.join(", ")}</p>
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}
    </section>
  );
}
