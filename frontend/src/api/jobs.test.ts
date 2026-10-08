// 작업 API 연결의 계약 (개정판 D2b-5b, 계획서 5.8, 5.9)
import { jobView } from "../test/jobs";
import { api, ApiError, resetEtags } from "./client";
import { jobResult, pendingCandidate, runningJob, startJob } from "./jobs";

afterEach(() => { vi.restoreAllMocks(); resetEtags(); });

it("중단과 완료 여부 불명은 서버 래퍼와 같이 503 job_interrupted다", () => {
  for (const state of ["interrupted", "remote_completion_unknown"] as const) {
    expect(() => jobResult(jobView("chapter", { state, result: null }))).toThrow(
      expect.objectContaining({ status: 503, code: "job_interrupted" }));
  }
});

it("기준 저장본을 받는 종류는 저장 ETag가 없으면 동의를 묻기 전에 428로 멈춘다", async () => {
  const prepare = vi.spyOn(api, "prepareAi");
  await expect(startJob("p1", "rewrite", {})).rejects.toMatchObject({ status: 428 });
  expect(prepare).not.toHaveBeenCalled();
});

it("기준 저장본은 동의를 기다리기 전에 고정한다", async () => {
  // 저장 ETag를 하나 만든다
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}", { status: 200, headers: { ETag: '"before"' } })));
  await api.getDeck("p1");
  vi.unstubAllGlobals();
  vi.spyOn(api, "prepareAi").mockImplementation(async () => {
    // 동의를 기다리는 동안 다른 저장이 ETag를 바꾼다
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}", { status: 200, headers: { ETag: '"after"' } })));
    await api.getDeck("p1");
    vi.unstubAllGlobals();
    return { "X-AI-Consent": "SlideCaptain" };
  });
  const start = vi.spyOn(api, "startJob").mockResolvedValue(jobView("rewrite"));
  await startJob("p1", "rewrite", { instructions: "" }, "req1");
  expect(start.mock.calls[0][3]).toBe('"before"');
  expect(start.mock.calls[0][1]).toEqual({ request_id: "req1", kind: "rewrite", params: { instructions: "" } });
});

it("지난 후보는 같은 종류와 대상의 가장 최근 작업이 처분되지 않은 결과일 때만이다", () => {
  const result = { status: "ok" };
  const mine = jobView("chapter", { target: "c1", result });
  expect(pendingCandidate([mine], ["chapter"], "c1")).toBe(mine);
  expect(pendingCandidate([mine], ["chapter"], "c2")).toBeNull();
  for (const candidate_status of ["delivered", "applied", "dismissed", "none"] as const) {
    expect(pendingCandidate([{ ...mine, candidate_status }], ["chapter"], "c1")).toBeNull();
  }
  expect(pendingCandidate([{ ...mine, candidate_status: "stale" }], ["chapter"], "c1")).not.toBeNull();
  // 더 새 작업이 처분됐으면 그보다 오래된 후보를 되살리지 않는다
  expect(pendingCandidate([{ ...mine, id: "new", candidate_status: "applied" }, mine], ["chapter"], "c1")).toBeNull();
});

it("이어서 조회하는 작업은 이 실행의 미종결 작업뿐이다", () => {
  const live = jobView("rewrite", { state: "running" });
  expect(runningJob([live], ["rewrite"])).toBe(live);
  expect(runningJob([{ ...live, owner: "other_instance" }], ["rewrite"])).toBeNull();
  expect(runningJob([{ ...live, state: "succeeded" }], ["rewrite"])).toBeNull();
  expect(runningJob([{ ...live, target: "c2" }], ["rewrite"], "c1")).toBeNull();
});

it("409 generation_active 응답의 진행 중 작업을 오류에 담는다", async () => {
  const active = { id: "job-9", project: "p2", kind: "diagram", target: null, stage: "running",
    created_at: "2026-10-08T10:00:00+09:00", cancel_requested: false };
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
    detail: "다른 AI 생성이 진행 중입니다.", code: "generation_active", active }), { status: 409 })));
  const error = await api.startJob("p1", { request_id: "r", kind: "chapter", params: {} }, {}).catch((e) => e);
  vi.unstubAllGlobals();
  expect(error).toBeInstanceOf(ApiError);
  expect(error.active).toEqual(active);
});
