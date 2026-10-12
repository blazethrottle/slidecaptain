import type { ReactNode } from "react";
import { ActiveJobCancel, useActiveJobFate } from "./ActiveJobNotice";
import { Button } from "./Button";
import { Diagnostics } from "./Diagnostics";
import { actionLabel, type FailureAction, type FailureDescription } from "./failure";

// 원인별 실패 안내 (개정판 D3a-4, 계획 4.3, 제품 설계 5절 D). 무슨 일이 생겼는가, 무엇이 보존됐는가,
// 지금 할 수 있는 일을 차례로 보이고 진단 상세는 접어 둔다. 화면이 처리기를 준 행동만 버튼으로 그리고,
// 나머지는 누를 곳이 화면 어디인지 밝힌 문장으로 안내한다(리뷰 R10). 판정은 화면이 describeFailure로 해서
// 넘긴다(화면이 아는 문구로 "무슨 일"을 바꿀 수 있다)
// 기다리거나 사용자가 고른 결과는 오류가 아니다. 주의색과 상태 알림으로 보인다 (D3a 묶음 리뷰 A17)
const WAITING = new Set(["generation_active", "login_pending", "cancelled"]);

type Props = {
  failure: FailureDescription | null;
  lead?: string;  // 화면이 아는 앞 문장(묶음 요약 등)
  actions?: Partial<Record<FailureAction, () => void>>;
  role?: "alert" | "status";  // 같은 사실을 다른 경고가 이미 알리면 status로 낮춘다 (리뷰 R15)
  children?: ReactNode;  // 진단 상세에 더 넣을 것(응답 원문, 사용량)
};

export function FailureNotice(props: Props) {
  // 거절의 원인 작업이 바뀌면 그 작업의 상태를 처음부터 다시 본다
  return props.failure ? <Notice key={props.failure.active?.id ?? ""} {...props} failure={props.failure} /> : null;
}

function Notice({ failure: given, lead, actions = {}, role, children }: Props & { failure: FailureDescription }) {
  // 다른 작업 진행 중(409)은 머리의 진행 작업을 따른다. 그 작업이 끝났으면 끝났다고 바꾸고, 진행 중이면 머리의
  // 취소를 가리킨다. 같은 작업의 취소 버튼을 두 곳에 두지 않는다 (D3a-5, 묶음 리뷰 A10)
  const fate = useActiveJobFate(given.active);
  const failure: FailureDescription = fate === "ended"
    ? { ...given, what: `진행 중이던 다른 AI 작업(${given.active!.project})이 끝났습니다.`, guidance: "다시 시도할 수 있습니다." }
    : fate === "running"
      ? { ...given, guidance: "그 작업이 끝나기를 기다리거나, 화면 위쪽의 '그 작업 취소'로 그 작업을 취소해 주세요." }
      : given;
  const primary = actions[failure.action];
  const secondary = failure.secondary;
  const secondaryHandler = secondary ? actions[secondary.action] : undefined;
  const diagnostics = { ...failure.diagnostics };
  if (diagnostics.serverText === failure.what) delete diagnostics.serverText;  // 같은 문장을 두 번 보이지 않는다
  return (
    <div role={role ?? (WAITING.has(failure.cause) ? "status" : "alert")}
      className={WAITING.has(failure.cause) ? "failure-notice is-waiting" : "failure-notice"}>
      {lead && <p>{lead}</p>}
      <p className="failure-what">{failure.what}</p>
      <p>{failure.preserved}</p>
      <p>지금 할 수 있는 일:{" "}
        {primary ? <Button variant="secondary" onClick={primary}>{failure.actionText}</Button> : failure.guidance}
      </p>
      {secondary && <p>{secondaryHandler
        ? <>{secondary.text} <Button variant="text" onClick={secondaryHandler}>{actionLabel(secondary.action)}</Button></>
        : secondary.text}</p>}
      {failure.active && fate === "unknown" && <ActiveJobCancel key={failure.active.id} active={failure.active} />}
      {failure.active && fate === "running" && <p className="notice">진행 중인 작업: {failure.active.project}</p>}
      <Diagnostics fields={diagnostics}>
        {children}
        {/* 실패한 호출의 사용량은 작업 오류에 실리지 않는다. 어디서 보는지 알린다 (리뷰 R21) */}
        {diagnostics.jobId && failure.cause !== "ai_output" && failure.cause !== "cancelled"
          && <p>실패한 호출의 사용량은 프로젝트 폴더의 사용량 기록 파일에 있습니다.</p>}
      </Diagnostics>
    </div>
  );
}
