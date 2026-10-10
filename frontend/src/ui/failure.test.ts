// 원인별 실패 안내의 판정 시험 (개정판 D3a-4, 계획 4.3). 모의 본문을 지어내지 않고, 서버 시험이 실제 실행기와
// 라우트에서 모아 고정한 본문(backend/tests/fixtures/failure-bodies.json)을 판정에 넣는다. 서버 본문이 바뀌면
// 서버 시험이 먼저 깨지고, 고정 파일에 새 원인이 생기면 아래 표의 열쇠 대조가 깨진다
import { api, ApiError, type ChapterView, type JobView } from "../api/client";
import { JobCancelled, jobResult, staleError } from "../api/jobs";
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

// [원인, 주 행동, 처리기가 없을 때 보이는 안내 문장]. 문장까지 걸어 문구가 바뀌면 시험이 깨진다 (D3a-4 리뷰 R14)
type Row = [FailureCause, FailureAction, string];
const OPEN = "화면 위쪽의 'AI 연결 및 모델'에서 연결과 로그인 상태를 확인해 주세요.";
const LATER = "잠시 뒤 다시 생성해 주세요.";
const LOGIN_LIMIT = "로그인 상태와 사용 한도를 확인한 뒤 잠시 뒤 다시 생성해 주세요.";

const JOBS: Record<string, Row> = {
  internal: ["internal", "retry", "다시 시도해 주세요."],
  storage: ["storage", "retry", "다시 시도해 주세요."],  // 생성 전에 끝나 결과가 없다 (리뷰 R5)
  project_missing: ["project_missing", "back_to_list", "화면 위쪽의 '목록으로'를 눌러 프로젝트 목록으로 돌아가 주세요."],
  login_required: ["login_required", "open_connection", OPEN],
  model_unavailable: ["model_unavailable", "choose_model", "화면 위쪽의 'AI 연결 및 모델'에서 모델을 다시 골라 주세요."],
  provider_call_failed: ["connection_other", "check_login_and_limit", LOGIN_LIMIT],
  provider_cancelled: ["connection_retry", "retry_later", LATER],
  provider_disconnected: ["connection_retry", "retry_later", LATER],
  provider_limit: ["provider_limit", "check_limit", "사용 한도를 확인한 뒤 잠시 뒤 다시 생성해 주세요."],
  provider_missing: ["provider_missing", "open_connection", OPEN],
  provider_timeout: ["connection_retry", "retry_later", LATER],
  provider_unsupported: ["provider_unsupported", "switch_connection",
    "화면 위쪽의 'AI 연결 및 모델'에서 다른 AI 연결로 바꿔 주세요."],
};

const CHAPTERS: Record<string, Row> = {
  ai_output: ["ai_output", "regenerate", "같은 입력으로 다시 생성해 주세요."],
  held_stale_plan: ["held", "recheck_structure", "구성 단계에서 구성을 다시 확인해 주세요."],
  internal: ["internal", "retry", "다시 시도해 주세요."],
  provider_failed: ["stopped", "follow_failed_chapter", "먼저 실패한 장의 안내를 따라 주세요."],
  provider_timeout: ["connection_retry", "retry_later", LATER],
  sources_changed: ["base_changed", "view_candidate_or_regenerate", "후보를 보거나 현재 입력으로 다시 생성해 주세요."],
  stale_story_plan: ["input_known", "go_to_structure", "구성 단계에서 구성을 다시 확인해 주세요."],
  stopped_after_error: ["stopped", "follow_failed_chapter", "먼저 실패한 장의 안내를 따라 주세요."],
};

const HTTP: Record<string, Row> = {
  deck_conflict: ["deck_conflict", "reload_server", "위쪽 충돌 안내의 '서버 내용 다시 읽기'를 눌러 주세요."],
  generation_active: ["generation_active", "cancel_active_job",
    "그 작업이 끝나기를 기다리거나, 아래에서 그 작업을 취소해 주세요."],
  job_ledger_unavailable: ["ledger", "restart_app", "앱을 닫았다가 다시 열어 주세요."],
  login_required: ["login_required", "open_connection", OPEN],
  provider_missing: ["provider_missing", "open_connection", OPEN],
  project_missing: ["project_missing", "back_to_list", "화면 위쪽의 '목록으로'를 눌러 프로젝트 목록으로 돌아가 주세요."],
  consent_missing: ["precondition", "retry", "다시 시도해 주세요."],
  selection_changed: ["target_changed", "check_target",
    "화면 위쪽의 'AI 연결 및 모델'에서 지금 연결과 모델을 확인한 뒤 다시 생성해 주세요."],
  validation: ["input_unknown", "check_input", "입력을 확인한 뒤 다시 생성해 주세요."],
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

test.each(Object.entries(JOBS))("작업 실패 %s", (name, [cause, action, guidance]) => {
  const view = job({ error: bodies.jobs[name] });
  const described = describeJobFailure(view);
  expect([described.cause, described.action, described.guidance]).toEqual([cause, action, guidance]);
  expect(described.diagnostics.jobId).toBe("job-9");
  // 화면은 작업 결과를 jobResult로 받는다. 그 오류를 넣어도 같은 판정이다
  let thrown: unknown;
  try { jobResult(view); } catch (e) { thrown = e; }
  expect(describeFailure(thrown).cause).toBe(cause);
});

test.each(Object.entries(CHAPTERS))("장 실패 %s", (name, [cause, action, guidance]) => {
  const row = bodies.chapters[name];
  const chapter: ChapterView = { ...row, position: 0, result: null, started_at: null, finished_at: null };
  const described = describeJobFailure(job({ kind: "chapters", chapters: [chapter] }), chapter);
  expect([described.cause, described.action, described.guidance]).toEqual([cause, action, guidance]);
});

test.each(Object.entries(HTTP))("등록 단계 HTTP 오류 %s", async (name, [cause, action, guidance]) => {
  const error = await httpError(name);
  expect(error).toBeInstanceOf(ApiError);
  const described = describeFailure(error);
  expect([described.cause, described.action, described.guidance]).toEqual([cause, action, guidance]);
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
  expect(describeJobFailure(job({ error, candidate_status: "stale", result: {} })).action).toBe("regenerate_or_discard");
});

test("보존 문구는 남은 결과로 정한다. 결과가 없으면 후보가 남았다고 말하지 않는다 (리뷰 R5)", () => {
  const changed = bodies.chapters.sources_changed.error;
  expect(describeJobFailure(job({ kind: "chapter", error: changed })).preserved).toBe("입력은 그대로입니다.");
  expect(describeJobFailure(job({ kind: "chapter", error: changed })).action).toBe("regenerate_current");
  expect(describeJobFailure(job({ kind: "chapter", error: changed, candidate_status: "stale", result: {} })).preserved)
    .toBe("결과는 이전 입력 기준 후보로 남았습니다.");
  const stored = { ...bodies.jobs.storage, code: "apply_failed" };
  expect(describeJobFailure(job({ error: stored, candidate_status: "held" })).action).toBe("open_recovery");
  expect(describeJobFailure(job({ error: stored })).preserved).toBe("입력은 그대로입니다.");
});

test("묶음이 시작 전에 끝나 장에 작업의 원인 코드가 실리면 그 원인으로 안내한다 (리뷰 R12)", () => {
  const parent = job({ kind: "chapters", error: bodies.http.login_required.body as never });
  const chapter = (code: string): ChapterView => ({ chapter_id: "c1", position: 0, state: "interrupted",
    candidate_status: "none", error: { error_class: null, status: null, detail: null, code }, result: null,
    started_at: null, finished_at: null });
  expect(describeJobFailure({ ...parent, error: { error_class: "connection", status: 503, detail: "로그인 필요", code: "login_required" } },
    chapter("login_required")).action).toBe("open_connection");
  expect(describeJobFailure(parent, chapter("project_missing")).action).toBe("back_to_list");
  expect(describeJobFailure(parent, chapter("chain_broken")).action).toBe("follow_failed_chapter");
});

test("작업 상태가 원인 분류보다 먼저다", () => {
  expect(describeJobFailure(job({ kind: "chapter", state: "interrupted" })).action).toBe("regenerate_chapter");
  // 장이 없는 작업은 "그 장"이라 하지 않는다 (리뷰 R13)
  expect(describeJobFailure(job({ state: "interrupted" })).actionText).toBe("구조안 다시 생성");
  expect(describeJobFailure(job({ kind: "rewrite", state: "interrupted" })).actionText).toBe("다시 미리보기");
  expect(describeJobFailure(job({ state: "remote_completion_unknown" })).action).toBe("regenerate_with_confirm");
  expect(describeJobFailure(job({ state: "cancelled", error: bodies.jobs.internal })).cause).toBe("cancelled");
});

test("원인 분류가 없고 상태가 500이면 입력을 고치라고 안내하지 않는다", () => {
  const error = { error_class: null, status: 500, detail: "예기치 않음", code: null };
  expect(describeJobFailure(job({ error })).cause).toBe("internal");
});

test("서비스에 닿지 못함과 작업 없는 취소", () => {
  expect(describeFailure(new TypeError("Failed to fetch")).action).toBe("restart_app");
  expect(describeFailure(new JobCancelled()).cause).toBe("cancelled");
  expect(describeFailure(new JobCancelled(job({ state: "cancelled" }))).cause).toBe("cancelled");
});

// 화면이 스스로 만드는 오류는 서버 고정 파일에 없으므로 그 함수를 실제로 불러 판정한다 (리뷰 R1, R6)
test.each([
  [{ logged_in: false }, "selection-one", "login_required", "open_connection"],
  [{ logged_in: null, error: "Claude CLI를 찾지 못했습니다.", error_code: "provider_missing" }, "selection-one",
    "provider_missing", "open_connection"],
  [{ logged_in: null, error: "Claude CLI가 10초 안에 응답하지 않았습니다.", error_code: "provider_timeout" }, "selection-one",
    "connection_retry", "retry_later"],
  [{ logged_in: null, error: "응답을 해석하지 못했습니다" }, "selection-one", "connection_other", "check_login_and_limit"],
  [{ logged_in: true }, null, "service_unreachable", "restart_app"],
] as const)("생성 전 AI 상태 확인 실패 %#", async (login, selection, cause, action) => {
  vi.spyOn(api, "getStatus").mockResolvedValue({ provider: "claude", model: "sonnet", checked_at: "",
    selection_id: selection, login } as never);
  const error = await api.prepareAi().then(() => null, (e: unknown) => e);
  expect([describeFailure(error).cause, describeFailure(error).action]).toEqual([cause, action]);
});

test("도식 창이 만드는 기준 변경 오류: 자료 변경은 결과가 없어 현재 입력으로 다시 생성, 저장본 변경은 다시 읽기", () => {
  // 다시 씀(D3a 묶음 리뷰 A6): "같은 입력으로"가 아니라 "현재 입력으로"이고, 무슨 일 칸은 화면이 만든 사실 문구다
  const described = describeFailure(staleError(["sources_changed"]));
  expect([described.action, described.guidance]).toEqual(["regenerate_current", "현재 입력으로 다시 생성해 주세요."]);
  expect(described.what).toBe("도식 생성 중 자료가 바뀌었습니다. 현재 자료로 다시 작성해 주세요.");
  expect(describeFailure(staleError(["unknown_sources"])).cause).toBe("base_changed");
  expect(describeFailure(staleError(["deck_changed"])).action).toBe("reload_server");
});
