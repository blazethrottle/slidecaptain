import type { ReactNode } from "react";
import type { FailureDescription } from "./failure";

// 진단 상세 (개정판 D3a-4, 계획 4.3, R12). 기본으로 접혀 있고, 오류 코드, 원래 원인 분류, 작업 ID와 시각,
// 사용량, 형식 오류의 응답 원문처럼 판단에는 쓰지 않지만 문제를 대조할 때 필요한 것을 담는다.
// 성공한 결과의 사용량도 여기에 둔다. 시험은 "사용량 표시가 모두 접힌 진단 상세 안에 있다"로 건다
// 내부 값은 개발자 대조에 그대로 필요하므로 두고, 사용자가 전달할 때 알아보도록 한국어 이름을 괄호로 붙인다 (리뷰 R16)
const CLASS_NAMES: Record<string, string> = {
  input: "입력", ai_output: "AI 응답 형식", connection: "AI 연결", base_changed: "기준 변경", cancelled: "취소",
  ledger: "작업 기록", storage: "저장", internal: "예기치 않은 오류",
};
const KIND_NAMES: Record<string, string> = {
  structure: "구조안", chapters: "장 생성 묶음", chapter: "장 다시 생성", condense: "장 축약", diagram: "도식",
  rewrite: "구성 재작성", repair: "제한된 수정",
};
const named = (value: string, names: Record<string, string>) => (names[value] ? `${value} (${names[value]})` : value);

export function Diagnostics({ fields, children }: { fields?: FailureDescription["diagnostics"]; children?: ReactNode }) {
  const rows: [string, string][] = [];
  if (fields?.code) rows.push(["오류 코드", fields.code]);
  if (fields?.errorClass) rows.push(["원인 분류", named(fields.errorClass, CLASS_NAMES)]);
  if (fields?.rawErrorClass) rows.push(["기록된 원래 분류", fields.rawErrorClass]);
  if (fields?.status) rows.push(["HTTP 상태", String(fields.status)]);
  if (fields?.jobKind) rows.push(["작업 종류", named(fields.jobKind, KIND_NAMES)]);
  if (fields?.jobId) rows.push(["작업 ID", fields.jobId]);
  if (fields?.at) rows.push(["시각", fields.at.slice(0, 19).replace("T", " ")]);  // 작업 기록과 대조하도록 초까지. 서버 로그의 실패 줄에는 작업 ID가 없다(묶음 리뷰 A16)
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
