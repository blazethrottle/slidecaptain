// 단계 상태 (개정판 D3a-3, 계획 4.2). 진행 API의 단계 상태와 사유를 단계 목록의 상태 표시로 옮긴다.
// 현재 보고 있는 단계(aria-current)와 단계 상태는 서로 다른 요소다. 이 모듈은 상태만 계산한다
import { TERMINAL_JOB_STATES, type ActiveJob, type JobView, type ProjectProgress } from "../api/client";
import type { components } from "../api/types";
import type { StatusKind } from "../ui/StatusIndicator";

export type Stage = "purpose" | "sources" | "structure" | "editor" | "review";
export type StageProgress = components["schemas"]["StageProgress"];
export type ReviewPart = components["schemas"]["ReviewPart"];
export type ProgressReason = NonNullable<StageProgress["reasons"]>[number];

// 사유 문구. 행동 지시가 아니라 사실 설명이다. 서버의 사유 목록(고정 목록)을 빠짐없이 덮는지 타입 검사가 확인한다
export const REASON_TEXT = {
  title_missing: "보고서 제목이 없습니다",
  report_type_unconfirmed: "보고 유형을 직접 골랐는지는 아직 기록하지 않습니다",
  sources_unreadable: "자료를 읽지 못했습니다",
  sources_missing: "자료가 없습니다",
  sources_over_limit: "자료 합계가 10만 자 한도를 넘습니다",
  extraction_review_unavailable: "자료의 부분 추출 경고는 아직 기록하지 않아, 엑셀 추출본의 빠진 부분을 이 화면이 알려 주지 못합니다",
  chapters_missing: "장 구성이 없습니다",
  plan_missing: "보고 계획이 없습니다",
  stale_story_plan: "자료, 보고 정보, 장 구성(편집 단계의 장 순서와 템플릿 포함)이 바뀌어 구성을 다시 확인해야 합니다",
  chapters_unwritten: "내용이 없는 장이 있습니다",
  no_export: "아직 내보낸 파일이 없습니다",
  artifact_mismatch: "내보낸 파일이 기록과 다릅니다",
  artifact_missing: "내보낸 파일을 찾지 못했습니다",
  artifact_unreadable: "내보낸 파일을 읽지 못했습니다",
  artifact_unverified: "내보낸 파일을 확인하지 못했습니다",
  input_stale: "내보낸 뒤 문서나 자료가 바뀌었습니다",
  input_legacy: "이전 버전에서 내보낸 파일이라 지금 입력과 대조할 수 없습니다",
  input_unavailable: "현재 문서와 자료를 읽지 못해 내보낸 파일과 대조하지 못했습니다",
  quality_needs_revision: "자동 검사에서 고칠 곳이 나왔습니다",
  draft_checks_only: "자동 검사는 내보낸 파일의 사전 점검이며 의미와 시각 품질의 통과가 아닙니다",
  review_records_unreadable: "검수 기록을 읽지 못했습니다",
  manual_pass_not_final: "사람 검토 통과는 독립 검수나 제출 승인이 아닙니다",
  review_not_run: "아직 검토하지 않은 항목이 있습니다",
  review_needs_revision: "검토에서 고칠 곳이 나왔습니다",
  review_stale: "검토 뒤 파일이나 입력이 바뀌었습니다",
  review_unavailable: "검토 기준을 확인하지 못했습니다",
  export_history_unreadable: "내보내기 이력을 읽지 못했습니다",
  auto_checks_pending: "자동 검사가 남았습니다",
  human_review_pending: "사람 검토가 남았습니다",
  file_pending: "파일 저장 확인이 남았습니다",
} as const satisfies Record<ProgressReason, string>;

// 화면이 모르는 사유(이후 버전의 서버가 더한 값). 준비됨으로 두지 않는다. 계획 4.2의 "상태를 확인해 주세요"는
// 지시문이라 사실 설명으로 바꿨다 (D3a-3 리뷰 R16)
export const UNKNOWN_REASON_TEXT = "이 화면이 알지 못하는 상태입니다";

// 준비됨에 붙는 사유. 단계 목록에는 보이지 않고 그 단계 화면의 한계 안내로 보인다 (계획 4.2)
export const READY_LIMITATIONS: ReadonlySet<string> = new Set<ProgressReason>(
  ["extraction_review_unavailable", "draft_checks_only", "manual_pass_not_final"]);

const SERVER_STAGE: Record<Stage, StageProgress["stage"]> = {
  purpose: "purpose", sources: "sources", structure: "structure", editor: "editing", review: "review",
};

// 작업 종류와 그 작업을 띄우는 단계. 구조안, 장 생성 묶음, 재작성, 수리는 구성 단계, 장 재생성, 축약, 도식은 편집 단계다
export const JOB_STAGE: Record<string, Stage> = {
  structure: "structure", chapters: "structure", rewrite: "structure", repair: "structure",
  chapter: "editor", condense: "editor", diagram: "editor",
};

export function isKnownReason(reason: string): reason is ProgressReason {
  return Object.prototype.hasOwnProperty.call(REASON_TEXT, reason);
}

export function reasonText(reason: string): string {
  return isKnownReason(reason) ? REASON_TEXT[reason] : UNKNOWN_REASON_TEXT;
}

export function stageProgress(progress: ProjectProgress | undefined, stage: Stage): StageProgress | undefined {
  return progress?.stages?.find((s) => s.stage === SERVER_STAGE[stage]);
}

export type StageStatus = { kind: StatusKind; detail?: string };

/**
 * 단계 목록의 상태. progress가 undefined면 아직 첫 조회 전이라 표시하지 않는다(null).
 * 화면이 보완하는 상태가 서버 상태보다 앞선다. 그 단계의 작업이 진행 중이면 "생성 중"이 먼저다(미저장 변경은 머리의
 * 저장 상태가 이미 보인다. 도식 작성 창이 열린 동안 편집 단계의 생성 중이 가려지지 않게 한다, D3a-3 리뷰 R8).
 * 그다음 현재 단계의 미저장 변경은 "작성 중"이다.
 * 진행 작업은 진행 작업 조회(activeJob)와 진행 API의 jobs 둘 다에서 찾는다. 같은 탭이 등록한 작업은 진행 작업
 * 조회가 다음 초점까지 모르지만 진행 API는 등록 알림 뒤 다시 읽혀 알기 때문이다 (D3a-3 리뷰 R1)
 */
export function stageStatus(stage: Stage, input: {
  progress: ProjectProgress | undefined; failed: boolean; current: boolean; dirty: boolean;
  activeJob: ActiveJob | null; projectName: string;
}): StageStatus | null {
  const job = input.activeJob;
  if (job && job.project === input.projectName && JOB_STAGE[job.kind] === stage) {
    return { kind: job.cancel_requested ? "cancel_requested" : "running" };
  }
  const running = (input.progress?.jobs ?? []).find((j) => JOB_STAGE[j.kind] === stage && !TERMINAL_JOB_STATES.has(j.state));
  if (running) return { kind: running.cancel_requested || running.state === "cancel_requested" ? "cancel_requested" : "running" };
  if (input.current && input.dirty) return { kind: "in_progress" };
  if (input.failed) return { kind: "unknown" };
  if (input.progress === undefined) return null;
  const sp = stageProgress(input.progress, stage);
  if (!sp) return { kind: "unknown" };
  const reasons = sp.reasons ?? [];
  if (reasons.some((r) => !isKnownReason(r))) return { kind: "needs_review", detail: UNKNOWN_REASON_TEXT };
  if (sp.state === "not_started") return { kind: "not_started" };
  if (sp.state === "ready") return { kind: stage === "review" ? "draft_checked" : "ready" };
  const shown = reasons.filter((r) => !READY_LIMITATIONS.has(r));
  return { kind: "needs_review", detail: shown.length > 0 ? reasonText(shown[0]) : undefined };
}

/** 준비됨에 붙은 사유의 문구. 그 단계 화면의 한계 안내로 보인다 */
export function stageLimitations(progress: ProjectProgress | undefined, stage: Stage): string[] {
  const sp = stageProgress(progress, stage);
  const reasons = [...(sp?.reasons ?? []), ...(sp?.parts ?? []).flatMap((p) => p.reasons ?? [])];
  return [...new Set(reasons.filter((r) => READY_LIMITATIONS.has(r)).map(reasonText))];
}

/**
 * 가장 최근 장 생성 묶음의 장 요약 (계획 4.2). 원장의 실제 행 모양으로 센다 (D3a-3 리뷰 R2):
 * - 이전 입력 기준 후보: 실패(failed)이고 후보 상태가 stale. 버린 후보(dismissed)는 세지 않는다
 * - 보류(구성 낡음): 구성 낡음으로 실패한 첫 장(stale_story_plan)과 그 뒤 멈춘 장(held_stale_plan)
 * - 실패: 그 밖의 실패. 중단(앞 장 때문에 멈춤): 그 밖의 interrupted. 취소: cancelled. 확인 필요: 완료 여부 불명
 * 진행 중이거나 모든 장이 반영됐으면 요약하지 않는다
 */
export function batchSummary(jobs: JobView[] | null | undefined): string | null {
  const batch = (jobs ?? []).find((j) => j.kind === "chapters");  // 진행 API의 작업은 최신 순이다
  if (!batch || !TERMINAL_JOB_STATES.has(batch.state)) return null;
  const total = batch.chapters.length;
  const counts = { failed: 0, stopped: 0, held: 0, stale: 0, cancelled: 0, unknown: 0 };
  for (const c of batch.chapters) {
    const code = c.error?.code;
    if (c.state === "succeeded") continue;
    if (c.candidate_status === "dismissed") continue;  // 사용자가 버린 후보는 남은 일이 아니다
    if (c.candidate_status === "stale") counts.stale += 1;
    else if (code === "stale_story_plan" || code === "held_stale_plan") counts.held += 1;
    else if (c.state === "failed") counts.failed += 1;
    else if (c.state === "cancelled") counts.cancelled += 1;
    else if (c.state === "remote_completion_unknown") counts.unknown += 1;
    else counts.stopped += 1;
  }
  const parts = [counts.failed && `${counts.failed}장 실패`, counts.stopped && `${counts.stopped}장 중단`,
    counts.held && `${counts.held}장 보류`, counts.stale && `${counts.stale}장은 이전 입력 기준 후보`,
    counts.cancelled && `${counts.cancelled}장 취소`, counts.unknown && `${counts.unknown}장 완료 여부 확인 필요`].filter(Boolean);
  return parts.length ? `${total}장 중 ${parts.join(", ")}` : null;
}
