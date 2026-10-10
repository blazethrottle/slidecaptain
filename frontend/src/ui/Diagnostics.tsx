import type { ReactNode } from "react";
import { formatSavedAt } from "../api/time";
import type { FailureDescription } from "./failure";

// 진단 상세 (개정판 D3a-4, 계획 4.3, R12). 기본으로 접혀 있고, 오류 코드, 원래 원인 분류, 작업 ID와 시각,
// 사용량, 형식 오류의 응답 원문처럼 판단에는 쓰지 않지만 문제를 대조할 때 필요한 것을 담는다.
// 성공한 결과의 사용량도 여기에 둔다. 시험은 "사용량 표시가 모두 접힌 진단 상세 안에 있다"로 건다
export function Diagnostics({ fields, children }: { fields?: FailureDescription["diagnostics"]; children?: ReactNode }) {
  const rows: [string, string][] = [];
  if (fields?.code) rows.push(["오류 코드", fields.code]);
  if (fields?.errorClass) rows.push(["원인 분류", fields.errorClass]);
  if (fields?.rawErrorClass) rows.push(["기록된 원래 분류", fields.rawErrorClass]);
  if (fields?.status) rows.push(["HTTP 상태", String(fields.status)]);
  if (fields?.jobKind) rows.push(["작업 종류", fields.jobKind]);
  if (fields?.jobId) rows.push(["작업 ID", fields.jobId]);
  if (fields?.at) rows.push(["시각", formatSavedAt(fields.at)]);
  if (fields?.serverText) rows.push(["서버 문구", fields.serverText]);
  if (rows.length === 0 && !children) return null;
  return (
    <details className="diagnostics">
      <summary>진단 상세</summary>
      {rows.length > 0 && <dl>{rows.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}</dl>}
      {children}
    </details>
  );
}
