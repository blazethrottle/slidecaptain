// 원인별 실패 안내 (개정판 D3a-4, 계획 4.3, 제품 설계 5절 D). 실패 하나를 세 요소(무슨 일이 생겼는가,
// 무엇이 보존됐는가, 지금 할 수 있는 일)로 바꾼다. 판정은 "작업 상태, 원인 분류, 코드" 순서다.
// 서버 문구를 그대로 보이는 것은 "무슨 일" 칸뿐이고, 422 입력 검증 문구는 그 칸에서도 고정 문구로 바꾼다.
// 동의 대화 상자 취소처럼 실패가 아닌 결과는 이 판정을 쓰지 않는다
import { AiConsentDeclined, ApiError, type ActiveJob, type ChapterView, type JobView } from "../api/client";
import { JobCancelled } from "../api/jobs";

export type FailureAction =
  | "go_to_structure" | "check_input" | "regenerate" | "open_connection" | "retry_later" | "switch_connection"
  | "check_login_and_limit" | "check_limit" | "choose_model" | "check_target" | "finish_login"
  | "view_candidate_or_regenerate" | "regenerate_or_discard" | "open_recovery" | "back_to_list" | "restart_app"
  | "retry" | "none" | "regenerate_chapter" | "regenerate_with_confirm" | "recheck_structure"
  | "follow_failed_chapter" | "cancel_active_job" | "reload_server";

export type FailureCause =
  | "input_known" | "input_unknown" | "ai_output" | "provider_missing" | "login_required" | "connection_retry"
  | "provider_unsupported" | "connection_other" | "provider_limit" | "model_unavailable" | "target_changed"
  | "login_pending" | "base_changed" | "storage" | "project_missing" | "ledger" | "internal" | "cancelled"
  | "interrupted" | "completion_unknown" | "held" | "stopped" | "service_unreachable" | "generation_active"
  | "deck_conflict" | "precondition";

export type FailureDescription = {
  cause: FailureCause;
  what: string;          // 무슨 일이 생겼는가
  preserved: string;     // 무엇이 보존됐는가
  action: FailureAction; // 지금 할 수 있는 일(주 행동)
  actionText: string;
  secondary?: { action: FailureAction; text: string };  // 보조 행동
  active?: ActiveJob;    // 다른 작업 진행 중(409)일 때 취소할 작업
  diagnostics: { code?: string | null; errorClass?: string | null; rawErrorClass?: string | null; status?: number;
    serverText?: string; jobId?: string; jobKind?: string; at?: string | null };
};

// 화면이 아는 입력 코드와 이동할 곳. 모르는 코드는 이동할 단계를 추측하지 않는다
const KNOWN_INPUT: Record<string, { action: FailureAction; text: string }> = {
  stale_story_plan: { action: "go_to_structure", text: "구성 단계에서 구성 다시 확인" },
  rewrite_protected_evidence: { action: "go_to_structure", text: "구성 단계에서 보호된 근거 확인" },
};

const ACTION_TEXT: Record<Exclude<FailureAction, "go_to_structure">, string> = {
  check_input: "입력을 확인한 뒤 다시 생성",
  regenerate: "같은 입력으로 다시 생성",
  open_connection: "AI 연결 열기",
  retry_later: "잠시 뒤 다시 생성",
  switch_connection: "AI 설정에서 다른 AI 연결로 바꾸기",
  check_login_and_limit: "로그인 상태와 사용 한도를 확인한 뒤 잠시 뒤 다시 생성",
  check_limit: "사용 한도를 확인한 뒤 잠시 뒤 다시 생성",
  choose_model: "AI 설정에서 모델 다시 선택",
  check_target: "AI 설정에서 전송 대상을 확인한 뒤 다시 생성",
  finish_login: "로그인을 마친 뒤 다시 생성",
  view_candidate_or_regenerate: "후보 보기 또는 현재 입력으로 다시 생성",
  regenerate_or_discard: "다시 생성 또는 후보 버리기",
  open_recovery: "복구 화면에서 후보 보기",
  back_to_list: "프로젝트 목록으로",
  restart_app: "앱 다시 시작",
  retry: "다시 시도",
  none: "필요하면 다시 생성",
  regenerate_chapter: "그 장 다시 생성",
  regenerate_with_confirm: "다시 생성(AI 사용량이 한 번 더 기록될 수 있습니다)",
  recheck_structure: "구성 단계에서 구성 다시 확인",
  follow_failed_chapter: "실패한 장의 안내를 따르기",
  cancel_active_job: "그 작업 취소",
  reload_server: "서버 내용 다시 읽기",
};

const PRESERVED = {
  input: "입력은 그대로입니다.",
  aiOutput: "입력은 그대로입니다. AI 응답 원문은 진단 상세에 있습니다.",
  candidate: "결과는 이전 입력 기준 후보로 남았습니다.",
  stored: "결과는 작업 기록에 후보로 남았습니다.",
  nothing: "보존한 것이 없습니다.",
  editing: "편집과 내보내기는 계속할 수 있습니다.",
  applied: "이미 반영한 장과 보관된 후보는 그대로입니다.",
  unknown: "결과를 받았는지 알 수 없습니다.",
  deck: "이 화면의 입력은 그대로입니다. 저장본은 다른 곳에서 바뀌었습니다.",
} as const;

function make(cause: FailureCause, what: string, preserved: string, action: FailureAction,
  extra: Partial<FailureDescription> & { actionText?: string } = {}): FailureDescription {
  return {
    cause, what, preserved, action, actionText: extra.actionText ?? ACTION_TEXT[action as keyof typeof ACTION_TEXT],
    secondary: extra.secondary, active: extra.active, diagnostics: extra.diagnostics ?? {},
  };
}

// 연결 원인. 코드는 서버가 던지는 자리마다 붙인다 (계획 4.3)
function connection(code: string | null | undefined, what: string, diagnostics: FailureDescription["diagnostics"]) {
  const d = { diagnostics };
  switch (code) {
    case "provider_missing": return make("provider_missing", what, PRESERVED.input, "open_connection", d);
    case "login_required": return make("login_required", what, PRESERVED.input, "open_connection", d);
    case "provider_timeout":
    case "provider_disconnected":
    case "provider_cancelled":  // 제공자 쪽이 생성을 취소로 끝냄(codex.py). 로그인이나 한도 문제가 아니다
    case "settings_busy":       // AI 설정을 바꾸는 중이었다
      return make("connection_retry", what, PRESERVED.input, "retry_later",
        { ...d, secondary: { action: "open_connection", text: "반복되면 AI 연결 확인" } });
    case "provider_unsupported": return make("provider_unsupported", what, PRESERVED.input, "switch_connection", d);
    case "provider_limit": return make("provider_limit", what, PRESERVED.input, "check_limit", d);
    case "model_unavailable": return make("model_unavailable", what, PRESERVED.input, "choose_model", d);
    case "selection_changed":
    case "identity_changed":
      return make("target_changed", what, PRESERVED.input, "check_target", d);
    case "login_pending": return make("login_pending", what, PRESERVED.input, "finish_login", d);
    default:
      // 로그인 문제와 한도 초과가 한 자리로 와서 서버가 가르지 못한 경우를 포함한다
      return make("connection_other", what, PRESERVED.input, "check_login_and_limit",
        { ...d, secondary: { action: "open_connection", text: "AI 연결 열기" } });
  }
}

function fromClass(errorClass: string | null | undefined, code: string | null | undefined, what: string,
  status: number | undefined, jobKind: string | undefined, diagnostics: FailureDescription["diagnostics"]): FailureDescription {
  const d = { diagnostics };
  switch (errorClass) {
    case "ai_output": return make("ai_output", "AI 응답이 형식에 맞지 않았습니다.", PRESERVED.aiOutput, "regenerate", d);
    case "connection": return connection(code, what, diagnostics);
    case "base_changed":
      return make("base_changed", "만드는 동안 입력이 바뀌었습니다.", PRESERVED.candidate,
        jobKind === "structure" ? "regenerate_or_discard" : "view_candidate_or_regenerate", d);
    case "storage":
      if (code === "project_missing") return make("project_missing", what, PRESERVED.nothing, "back_to_list", d);
      return make("storage", what, PRESERVED.stored, "open_recovery",
        { ...d, secondary: { action: "none", text: "저장 공간과 폴더 권한을 확인해 주세요" } });
    case "ledger": return make("ledger", what, PRESERVED.editing, "restart_app", d);
    case "internal":
      return make("internal", what, PRESERVED.input, "retry", { ...d,
        secondary: { action: "none", text: "반복되면 진단 상세의 작업 ID와 시각을 개발자에게 전달해 주세요" } });
    case "cancelled": return make("cancelled", "생성을 취소했습니다.", PRESERVED.applied, "none", d);
    case "input":
    default: {
      if (code && KNOWN_INPUT[code]) {
        return make("input_known", what, PRESERVED.input, KNOWN_INPUT[code].action, { ...d, actionText: KNOWN_INPUT[code].text });
      }
      if (errorClass == null && status !== undefined && status >= 500) {
        return make("internal", what, PRESERVED.input, "retry", d);
      }
      return make("input_unknown", what, PRESERVED.input, "check_input", d);
    }
  }
}

/** 원장의 작업(또는 묶음의 장 하나)을 안내로 바꾼다. */
export function describeJobFailure(job: JobView, chapter?: ChapterView): FailureDescription {
  const row = chapter ?? job;
  const error = row.error;
  const diagnostics = { code: error?.code, errorClass: error?.error_class, rawErrorClass: error?.raw_error_class,
    status: error?.status ?? undefined, serverText: error?.detail ?? undefined, jobId: job.id, jobKind: job.kind,
    at: (chapter?.finished_at ?? job.finished_at) ?? job.created_at };
  if (row.state === "cancelled") return make("cancelled", "생성을 취소했습니다.", PRESERVED.applied, "none", { diagnostics });
  if (row.state === "remote_completion_unknown") {
    return make("completion_unknown", "AI 생성이 끝났는지 확인하지 못했습니다.", PRESERVED.unknown, "regenerate_with_confirm",
      { diagnostics });
  }
  if (row.state === "interrupted") {
    if (chapter && error?.code === "held_stale_plan") {
      return make("held", "구성이 바뀌어 이 장을 만들지 않았습니다.", PRESERVED.applied, "recheck_structure", { diagnostics });
    }
    if (chapter) {
      return make("stopped", "앞 장이 실패해 이 장을 만들지 않았습니다.", PRESERVED.applied, "follow_failed_chapter", { diagnostics });
    }
    return make("interrupted", "AI 생성이 중단되었습니다.", PRESERVED.applied, "regenerate_chapter",
      { diagnostics, secondary: { action: "open_recovery", text: "복구 화면의 결과 없이 끝난 작업에서 확인" } });
  }
  const what = error?.detail ?? "AI 생성 작업을 처리하지 못했습니다.";
  return fromClass(error?.error_class, error?.code, what, error?.status ?? undefined, job.kind, diagnostics);
}

/** 화면이 받은 오류(작업 실패, 등록 단계의 HTTP 오류, 연결 실패)를 안내로 바꾼다. */
export function describeFailure(error: unknown): FailureDescription {
  if (error instanceof ApiError && error.job) return describeJobFailure(error.job);
  if (error instanceof JobCancelled) return make("cancelled", "생성을 취소했습니다.", PRESERVED.applied, "none");
  if (!(error instanceof ApiError)) {
    return make("service_unreachable", "로컬 서비스에 닿지 못했습니다.", PRESERVED.input, "restart_app");
  }
  const diagnostics = { code: error.code, status: error.status, serverText: error.message };
  if (error instanceof AiConsentDeclined) {
    // 실패가 아니다. 부르는 쪽이 따로 안내하지만, 잘못 들어와도 실패로 말하지 않는다
    return make("cancelled", error.message, PRESERVED.input, "none", { diagnostics });
  }
  if (error.status === 409 && error.code === "generation_active") {
    return make("generation_active", error.message, PRESERVED.input, "cancel_active_job", { diagnostics, active: error.active });
  }
  if (error.status === 428) {
    // 전송 동의 헤더 누락과 기준 저장본 누락이 같은 상태로 온다. 서버 문구가 할 일을 담고 있고,
    // 다시 시도하면 생성 전 확인(prepareAi)이 동의 대화 상자를 다시 연다
    return make("precondition", error.message, PRESERVED.input, "retry", { diagnostics });
  }
  if (error.status === 412) return make("deck_conflict", error.message, PRESERVED.deck, "reload_server", { diagnostics });
  if (error.status === 503 && error.code === "job_ledger_unavailable") {
    return make("ledger", error.message, PRESERVED.editing, "restart_app", { diagnostics });
  }
  if (error.status === 422) {
    // 입력 검증 문구는 서버 구현의 말이라 고정 문구로 바꾸고 원문은 진단 상세로 보낸다 (계획 4.3)
    return make("input_unknown", "입력 형식이 맞지 않습니다.", PRESERVED.input, "check_input", { diagnostics });
  }
  const connectionCodes = ["provider_missing", "login_required", "provider_timeout", "provider_disconnected",
    "provider_unsupported", "provider_limit", "provider_cancelled", "model_unavailable", "provider_call_failed",
    "selection_changed", "identity_changed", "login_pending", "settings_busy"];
  if (error.code && connectionCodes.includes(error.code)) return connection(error.code, error.message, diagnostics);
  return fromClass(undefined, error.code, error.message, error.status, undefined, diagnostics);
}

/** 결과는 받았지만 형식 검사를 통과하지 못한 생성(결과 상태 format_error). 원문은 화면이 진단 상세에 넣는다. */
export function describeAiOutput(job?: JobView | null, what = "AI 응답을 형식에 맞게 읽지 못했습니다."): FailureDescription {
  return make("ai_output", what, PRESERVED.aiOutput, "regenerate",
    { diagnostics: job ? { jobId: job.id, jobKind: job.kind, at: job.finished_at ?? job.created_at } : {} });
}
