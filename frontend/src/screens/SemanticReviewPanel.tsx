import { useEffect, useRef, useState } from "react";
import { api, messageOf, type Deck, type SemanticSuspectReport } from "../api/client";

export function SemanticReviewPanel({projectName, deck}: {projectName: string; deck: Deck}) {
  const [state, setState] = useState<{deck: Deck; project: string; report?: SemanticSuspectReport; error?: string; busy: boolean} | null>(null);
  const sequence = useRef(0);
  useEffect(() => {sequence.current++; setState(null); return () => {sequence.current++;};}, [deck, projectName]);
  const current = state?.deck === deck && state.project === projectName ? state : null;
  const check = async () => {
    if (current?.busy) return;
    const id = ++sequence.current;
    setState({deck, project:projectName, busy:true});
    try {
      const report = await api.reviewSemantics(projectName, deck);
      if (id === sequence.current) setState({deck,project:projectName,busy:false,report});
    } catch(e) {if(id === sequence.current) setState({deck,project:projectName,busy:false,error:messageOf(e)});}
  };
  const report = current?.report;
  return <section aria-label="비교·요약 검토 후보">
    <h3>비교·요약 검토 후보</h3><p>AI 호출 없이 미등록 수치 비교·산식과 요약 방향의 검토 후보를 찾습니다.</p>
    <button disabled={current?.busy} onClick={() => void check()}>{current?.busy ? "확인 중..." : "비교·요약 후보 찾기"}</button>
    {current?.error && <p role="alert">{current.error}</p>}
    {report && <div aria-live="polite">
      <p>{report.status === "not_run" ? "현재 계획·자료 또는 대상 한도 때문에 탐지를 완료하지 못했습니다." :
        `문구 ${report.evaluated_fields}개 중 검토 후보 ${report.findings.length}개.`}</p>
      <p>{report.scope_notice}</p><p>원문 의미와 요약 정합성 검수: 미수행</p>
      {report.findings.map((finding,i) => <article key={i}>
        <h4>{deck.structure.chapters.find(c=>c.id === finding.chapter_id)?.topic ?? "보고 주장"}</h4>
        <p>{finding.text}</p><p>{finding.message}</p>
        {(finding.related_texts??[]).map((related,j)=><blockquote key={j}>{related.text}</blockquote>)}
        {!!finding.claim_ids.length && <p>관련 주장: {finding.claim_ids.join(", ")}</p>}
      </article>)}
    </div>}
  </section>;
}
