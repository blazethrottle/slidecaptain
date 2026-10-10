// 원인별 실패 안내의 판정 시험 (개정판 D3a-4, 계획 4.3). 모의 본문을 지어내지 않고, 서버 시험이 실제 실행기와
// 라우트에서 모아 고정한 본문(backend/tests/fixtures/failure-bodies.json)을 판정에 넣는다. 서버 본문이 바뀌면
// 서버 시험이 먼저 깨지고, 고정 파일에 새 원인이 생기면 아래 표의 열쇠 대조가 깨진다
import { api, ApiError, type ChapterView, type JobView } from "../api/client";
import { JobCancelled, jobResult } from "../api/jobs";
import { describeFailure, describeJobFailure, type FailureAction, type FailureCause } from "./failure";
import fixture from "../../../backend/tests/fixtures/failure-bodies.json";

type ErrorBody = NonNullable<JobView["error"]>;
const bodies = fixture as unknown as {
  jobs: Record<string, ErrorBody>;
  chapters: Record<string, { chapter_id: string; state: ChapterView["state"]; candidate_status: ChapterView["candidate_status"]; error: ErrorBody }>;
  http: Record<string, { status: number; body: Record<string, unknown> }>;
};

function job(over: Partial<JobView> = {}): JobView {
  return {
    id: "job-9", project: "p1", kind: "structure", state: "failed", target: null, params: {}, candidate_status: "none",
    outcome: null, owner: "this_instance", created_at: "2026-10-10T10:00:00+09:00", started_at: null,
    finished_at: "2026-10-10T10:01:00+09:00", provider: null, model: null, base_etag: null, current_etag: null,
    relevance_hash: null, stale_reasons: [], cancel_requested: false, error: null, result: null, chapters: [], ...over,
  };
}

const JOBS: Record<string, [FailureCause, FailureAction]> = {
  internal: ["internal", "retry"],
  storage: ["storage", "open_recovery"],
  project_missing: ["project_missing", "back_to_list"],
  login_required: ["login_required", "open_connection"],
  model_unavailable: ["model_unavailable", "choose_model"],
  provider_call_failed: ["connection_other", "check_login_and_limit"],
  provider_cancelled: ["connection_retry", "retry_later"],
  provider_disconnected: ["connection_retry", "retry_later"],
  provider_limit: ["provider_limit", "check_limit"],
  provider_missing: ["provider_missing", "open_connection"],
  provider_timeout: ["connection_retry", "retry_later"],
  provider_unsupported: ["provider_unsupported", "switch_connection"],
};

const CHAPTERS: Record<string, [FailureCause, FailureAction]> = {
  ai_output: ["ai_output", "regenerate"],
  held_stale_plan: ["held", "recheck_structure"],
  internal: ["internal", "retry"],
  provider_failed: ["stopped", "follow_failed_chapter"],
  provider_timeout: ["connection_retry", "retry_later"],
  sources_changed: ["base_changed", "view_candidate_or_regenerate"],
  stale_story_plan: ["input_known", "go_to_structure"],
  stopped_after_error: ["stopped", "follow_failed_chapter"],
};

const HTTP: Record<string, [FailureCause, FailureAction]> = {
  deck_conflict: ["deck_conflict", "reload_server"],
  generation_active: ["generation_active", "cancel_active_job"],
  job_ledger_unavailable: ["ledger", "restart_app"],
  login_required: ["login_required", "open_connection"],
  selection_changed: ["target_changed", "check_target"],
  validation: ["input_unknown", "check_input"],
};

async function httpError(name: string): Promise<unknown> {
  const { status, body } = bodies.http[name];
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status })));
  return api.listJobs("p1").then(() => null, (e: unknown) => e);
}

afterEach(() => vi.unstubAllGlobals());

test("고정 파일의 원인과 판정 표의 열쇠가 같다", () => {
  expect(Object.keys(bodies.jobs).sort()).toEqual(Object.keys(JOBS).sort());
  expect(Object.keys(bodies.chapters).sort()).toEqual(Object.keys(CHAPTERS).sort());
  expect(Object.keys(bodies.http).sort()).toEqual(Object.keys(HTTP).sort());
});

test.each(Object.entries(JOBS))("작업 실패 %s", (name, [cause, action]) => {
  const view = job({ error: bodies.jobs[name] });
  const described = describeJobFailure(view);
  expect([described.cause, described.action]).toEqual([cause, action]);
  expect(described.diagnostics.jobId).toBe("job-9");
  // 화면은 작업 결과를 jobResult로 받는다. 그 오류를 넣어도 같은 판정이다
  let thrown: unknown;
  try { jobResult(view); } catch (e) { thrown = e; }
  expect(describeFailure(thrown).cause).toBe(cause);
});

test.each(Object.entries(CHAPTERS))("장 실패 %s", (name, [cause, action]) => {
  const row = bodies.chapters[name];
  const chapter: ChapterView = { ...row, position: 0, result: null, started_at: null, finished_at: null };
  const described = describeJobFailure(job({ kind: "chapters", chapters: [chapter] }), chapter);
  expect([described.cause, described.action]).toEqual([cause, action]);
});

test.each(Object.entries(HTTP))("등록 단계 HTTP 오류 %s", async (name, [cause, action]) => {
  const error = await httpError(name);
  expect(error).toBeInstanceOf(ApiError);
  const described = describeFailure(error);
  expect([described.cause, described.action]).toEqual([cause, action]);
});

test("다른 작업 진행 중이면 취소할 작업을 함께 싣는다", async () => {
  expect(describeFailure(await httpError("generation_active")).active?.id).toBe("job-1");
});

test("입력 검증 422는 고정 문구로 보이고 서버 문구는 진단 상세로 보낸다", async () => {
  const described = describeFailure(await httpError("validation"));
  expect(described.what).toBe("입력 형식이 맞지 않습니다.");
  expect(described.diagnostics.serverText).toBe(bodies.http.validation.body.detail);
});

test("구조안 후보의 기준 변경은 후보 보기가 아니라 다시 생성 또는 버리기다", () => {
  const error = bodies.chapters.sources_changed.error;
  expect(describeJobFailure(job({ error })).action).toBe("regenerate_or_discard");
});

test("작업 상태가 원인 분류보다 먼저다", () => {
  expect(describeJobFailure(job({ state: "interrupted" })).action).toBe("regenerate_chapter");
  expect(describeJobFailure(job({ state: "remote_completion_unknown" })).action).toBe("regenerate_with_confirm");
  expect(describeJobFailure(job({ state: "cancelled", error: bodies.jobs.internal })).cause).toBe("cancelled");
});

test("원인 분류가 없고 상태가 500이면 입력을 고치라고 안내하지 않는다", () => {
  const error = { error_class: null, status: 500, detail: "예기치 않음", code: null };
  expect(describeJobFailure(job({ error })).cause).toBe("internal");
});

test("서비스에 닿지 못함, 작업 없는 취소, 사전 조건 428", () => {
  expect(describeFailure(new TypeError("Failed to fetch")).action).toBe("restart_app");
  expect(describeFailure(new JobCancelled()).cause).toBe("cancelled");
  expect(describeFailure(new JobCancelled(job({ state: "cancelled" }))).cause).toBe("cancelled");
  expect(describeFailure(new ApiError(428, "프로젝트를 다시 열어 저장본을 확인해 주세요.")).action).toBe("retry");
});
