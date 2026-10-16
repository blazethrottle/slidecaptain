// 후보형 생성의 작업 API 연결 (개정판 D2b-5b, 계획서 5.8, 5.9).
// 등록, 조회, 결과 변환을 여기 둔다. client.ts의 api 객체를 가져와 쓰므로 시험의 모의가 그대로 닿는다
import { api, ApiError, followJob, newRequestId, notifyProject, savedEtag, TERMINAL_JOB_STATES, type JobView } from "./client";

export const JOB_CANCELLED_MESSAGE = "AI 생성이 취소되었습니다.";
export const JOB_INTERRUPTED_MESSAGE = "AI 생성이 중단되었습니다. 완료 여부를 확인할 수 없으면 결과를 다시 생성해 주세요.";
export const JOB_FOLLOW_ERROR = "작업 상태를 확인하지 못했습니다. 계속 확인합니다.";

export type JobKind = "structure" | "chapter" | "condense" | "diagram" | "rewrite" | "repair";

// 기준 저장본을 If-Match로 받는 종류. 나머지는 등록 때 서버가 지금 저장본을 기준으로 삼는다
const BASE_KINDS = new Set<JobKind>(["diagram", "rewrite", "repair"]);

// 취소로 끝난 작업. 화면은 실패가 아니라 취소 안내로 보인다
export class JobCancelled extends ApiError {
  // 취소로 끝난 작업. 취소 뒤 도착한 값을 화면이 처분할 수 있게 같이 싣는다 (D2b-β 리뷰 R3)
  constructor(readonly job: JobView | null = null) {
    super(409, JOB_CANCELLED_MESSAGE, "job_cancelled");
  }
}

// 등록. 기준 저장본은 동의를 기다리기 전에 고정한다(동의 중 다른 저장이 끼어도 요청의 기준은 그대로다)
export async function startJob(name: string, kind: JobKind, params: unknown, requestId = newRequestId()): Promise<JobView> {
  let expectedEtag: string | undefined;
  if (BASE_KINDS.has(kind)) {
    expectedEtag = savedEtag(name);
    if (!expectedEtag) throw new ApiError(428, "프로젝트를 다시 열어 저장본을 확인해 주세요.");
  }
  const headers = await api.prepareAi();
  return api.startJob(name, { request_id: requestId, kind, params }, headers, expectedEtag);
}

// 종결된 작업을 종전 동기 라우트의 응답처럼 바꾼다. 서버의 동기 생성 래퍼(D3c-7에서 지웠다)가 쓰던 규칙을 이어받는다:
// 결과가 있으면 돌려주고(형식 오류 결과 포함), 취소는 409, 중단과 완료 여부 불명은 503, 나머지는 기록된 오류다
export function jobResult<T>(view: JobView): T {
  if (view.state === "cancelled") throw new JobCancelled(view);
  if (view.result) return view.result as T;
  if (view.state === "interrupted" || view.state === "remote_completion_unknown") {
    throw new ApiError(503, JOB_INTERRUPTED_MESSAGE, "job_interrupted", undefined, view);
  }
  throw new ApiError(view.error?.status ?? 500, view.error?.detail ?? "AI 생성 작업을 처리하지 못했습니다.",
    view.error?.code ?? undefined, undefined, view);
}

// 진행 작업 확인이 이 작업을 진행 중으로 돌려주는가. 작업 조회가 실패할 때만 묻는다 (D3a-5, β R8)
export function stillActive(jobId: string): Promise<boolean> {
  return api.getActiveJob().then((status) => status.active?.id === jobId);
}

// 작업이 끝날 때까지 조회한다. signal은 조회만 멈추고 작업을 취소하지 않는다
export function waitJob(name: string, view: JobView, opts: {
  intervalMs?: number; signal?: AbortSignal; onUpdate?: (view: JobView) => void; onError?: (error: unknown) => void;
} = {}): Promise<JobView> {
  if (TERMINAL_JOB_STATES.has(view.state)) {
    // 등록 응답이 이미 종결이면 조회를 거치지 않으므로 여기서 종결을 알린다 (D3a-3 리뷰 R9)
    notifyProject({ kind: "job_ended", project: view.project, jobId: view.id, state: view.state, jobKind: view.kind,
      target: view.target });
    return Promise.resolve(view);
  }
  return followJob(() => api.getJob(name, view.id), (next) => opts.onUpdate?.(next),
    { intervalMs: opts.intervalMs, signal: opts.signal, onError: opts.onError, stillActive: () => stillActive(view.id) });
}

// 등록부터 결과까지. onStarted로 작업 ID를 알려 화면이 취소와 후보 처분에 쓰게 한다
export async function runJob<T>(name: string, kind: JobKind, params: unknown, opts: {
  intervalMs?: number; signal?: AbortSignal; onStarted?: (view: JobView) => void; onError?: (error: unknown) => void;
  onUpdate?: (view: JobView) => void;  // 조회할 때마다 받은 작업 응답 (실행 단계 표시, D3b-7)
} = {}): Promise<{ result: T; job: JobView }> {
  const started = await startJob(name, kind, params);
  opts.onStarted?.(started);
  const final = await waitJob(name, started, opts);
  return { result: jobResult<T>(final), job: final };
}

// 지난 후보: 이 종류와 대상의 가장 최근 작업이 성공으로 끝나 처분되지 않은 결과일 때만 돌려준다(목록은 최신 순).
// 취소로 끝나 값이 남은 작업은 고르지 않는다. 그런 값은 복구 화면에서만 다룬다 (D2b-5b 리뷰 R5)
export function pendingCandidate(jobs: JobView[], kinds: JobKind[], target: string | null = null): JobView | null {
  const latest = jobs.find((j) => (kinds as string[]).includes(j.kind) && (target === null || j.target === target));
  if (!latest || latest.state !== "succeeded" || !latest.result) return null;
  return latest.candidate_status === "held" || latest.candidate_status === "stale" ? latest : null;
}

// 결과 없이 끝난 실패 상태 (다시 연 화면이 지난 실패로 보인다, D3a-β 리뷰 B1)
export const FAILED_JOB_STATES: ReadonlySet<string> = new Set(["failed", "interrupted", "remote_completion_unknown"]);

// 작업이 이 시각(ms) 뒤에 끝났는가. 끝난 시각이 없으면 만든 시각으로 본다 (D3a-β 재리뷰 F2)
export function endedSince(view: JobView, since: number): boolean {
  const at = Date.parse(view.finished_at ?? view.created_at);
  return Number.isNaN(at) || at >= since;
}

// 진행 중인 같은 종류와 대상의 작업 (화면을 다시 열었을 때 이어서 조회한다)
export function runningJob(jobs: JobView[], kinds: JobKind[], target: string | null = null): JobView | null {
  return jobs.find((j) => (kinds as string[]).includes(j.kind) && (target === null || j.target === target)
    && !TERMINAL_JOB_STATES.has(j.state) && j.owner === "this_instance") ?? null;
}

// 반영을 막는 낡음 이유. deck_changed_elsewhere는 알리기만 한다 (계획서 5.8). 서버가 낡은 후보(stale)로
// 기록한 작업은 조회 때 이유가 비어도 반영할 수 없다. 서버가 그 처분을 거절한다 (D2b-5b 리뷰 R10)
export function blockingReasons(view: JobView): string[] {
  const reasons = view.stale_reasons.filter((r) => r !== "deck_changed_elsewhere");
  return view.candidate_status === "stale" && reasons.length === 0 ? ["candidate_stale"] : reasons;
}

// 슬롯 내용이 같은지. 서버는 기본값을 채우고 모델 순서로 키를 다시 놓으므로 키 순서와 빈 기본값을 무시한다
// (D2b-5b 리뷰 R3)
export function sameSlots(a: unknown, b: unknown): boolean {
  const canonical = (value: unknown): unknown => {
    if (Array.isArray(value)) return value.map(canonical);
    if (value && typeof value === "object") {
      return Object.fromEntries(Object.entries(value)
        .filter(([, v]) => !(v === null || v === "" || v === false || (Array.isArray(v) && v.length === 0)))
        .sort(([x], [y]) => (x < y ? -1 : x > y ? 1 : 0))
        .map(([k, v]) => [k, canonical(v)]));
    }
    return value;
  };
  return JSON.stringify(canonical(a)) === JSON.stringify(canonical(b));
}

// 처분은 화면 동작을 막지 않는다. 실패하면 다음에 열 때 후보가 한 번 더 보일 뿐이다
export async function settle(name: string, jobId: string, action: "applied" | "dismissed"): Promise<void> {
  try {
    await api.settleCandidate(name, jobId, action);
  } catch {
    /* 무시: 후보가 다시 보이는 것이 결과를 잃는 것보다 낫다 */
  }
}

// 낡음 이유의 화면 문구 (계획서 5.8). 서버의 고정 목록(StaleReason)과 화면이 만드는 둘을 모두 덮는지 타입 검사가
// 지킨다. 새 사유가 생겼는데 문구가 없으면 화면에 영문 코드가 나왔다 (D3b-2, 리뷰 V9)
type ServerStaleReason = JobView["stale_reasons"][number];
export const STALE_REASON_LABELS = {
  structure_input_changed: "보고 정보가 바뀌었습니다",
  structure_applied_basis_changed: "문서 구성이나 슬라이드가 바뀌었습니다",
  deck_changed_elsewhere: "다른 곳에서 저장본이 바뀌었습니다",
  chapter_missing: "이 장이 구조안에서 빠졌습니다",
  template_changed: "이 장의 템플릿이 바뀌었습니다",
  chapter_changed: "이 장의 주제나 결론이 바뀌었습니다",
  story_plan_changed: "보고 계획이 바뀌었습니다",
  sources_changed: "자료가 바뀌었습니다",
  unknown_sources: "자료를 확인하지 못했습니다",
  slots_changed: "이 장의 내용이 바뀌었습니다",
  deck_changed: "저장본이 바뀌었습니다",
  unknown_deck: "저장본을 확인하지 못했습니다",
  candidate_stale: "만드는 동안 입력이 바뀌었던 후보입니다",
  not_applicable: "이전 버전에서 만든 결과라 반영 여부를 판정할 수 없습니다",  // 적용 라우트의 409 (D3c-5)
} as const satisfies Record<ServerStaleReason | "slots_changed" | "candidate_stale" | "not_applicable", string>;

// 도식 후보에서 뜻이 다른 사유. 도식의 chapter_changed는 교체할 도식 장의 정의, 슬라이드, 구성 계획 연결(역할, 주장)이
// 바뀐 경우다(pipeline/relevance.py). 장 후보의 "주제나 결론"으로 부르지 않는다 (C1 W2 리뷰 W2R-09, C2 계획 4.3 (23))
const DIAGRAM_REASON_LABELS: Record<string, string> = {
  chapter_changed: "교체할 도식 장의 제목, 역할, 연결한 주장이나 도식 내용이 바뀌었습니다",
};

export function reasonText(reasons: string[], kind?: string): string {
  const labels: Record<string, string> = kind === "diagram" ? { ...STALE_REASON_LABELS, ...DIAGRAM_REASON_LABELS }
    : STALE_REASON_LABELS;
  return reasons.map((r) => labels[r] ?? r).join(", ");
}

// 후보 슬롯의 글자만 모아 보인다. 사용자가 반영 여부를 판단하는 데는 구조보다 내용이 필요하다
export function slotsText(slots: unknown): string {
  const texts: string[] = [];
  const walk = (value: unknown, key = "") => {
    if (typeof value === "string") { if (value && key !== "template" && key !== "tone") texts.push(value); }
    else if (Array.isArray(value)) value.forEach((v) => walk(v));
    else if (value && typeof value === "object") Object.entries(value).forEach(([k, v]) => walk(v, k));
  };
  walk(slots);
  return texts.join("\n");
}

// 도식의 낡은 결과는 종전 라우트처럼 오류로 알린다 (서버 _STALE_RESPONSES["diagram"]과 같은 표).
// 재작성의 낡은 후보는 오류가 아니라 이전 입력 기준 후보로 보인다 (계획서 D2b-5b 정정 ⑦, 리뷰 R14)
// 코드는 실패 안내의 판정에 쓴다 (D3a-4 리뷰 R6). 자료 변경은 결과가 없으므로 "다시 생성"이다
const STALE_RESPONSES: Record<string, [number, string, string]> = {
  unknown_deck: [412, "도식 생성 중 기준 저장본을 읽을 수 없게 되었습니다. 프로젝트를 다시 열어 주세요.", "base_changed"],
  deck_changed: [412, "다른 창이나 프로그램에서 먼저 저장되었습니다. 최신 덱을 다시 읽어 주세요.", "base_changed"],
  unknown_sources: [409, "도식 생성 중 자료를 읽을 수 없게 되었습니다. 자료를 확인한 뒤 다시 작성해 주세요.", "sources_changed"],
  sources_changed: [409, "도식 생성 중 자료가 바뀌었습니다. 현재 자료로 다시 작성해 주세요.", "sources_changed"],
};

export function staleError(reasons: string[]): ApiError | null {
  for (const reason of ["unknown_deck", "deck_changed", "unknown_sources", "sources_changed"]) {
    if (reasons.includes(reason)) {
      const [status, detail, code] = STALE_RESPONSES[reason];
      return new ApiError(status, detail, code);
    }
  }
  return null;
}
