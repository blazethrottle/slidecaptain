// 단계 상태 계산의 계약 시험 (개정판 D3a-3, 계획 4.2)
import type { ActiveJob, ProjectProgress } from "../api/client";
import { batchView, chapterView } from "../test/jobs";
import { REASON_TEXT, batchSummary, reasonText, stageLimitations, stageStatus, UNKNOWN_REASON_TEXT,
  type Stage, type StageProgress } from "./stageStatus";

const progress = (stages: Partial<StageProgress>[], jobs: ProjectProgress["jobs"] = null): ProjectProgress => ({
  project_status: "ok", jobs,
  stages: stages.map((s) => ({ stage: "purpose", state: "ready", reasons: [], ...s }) as StageProgress),
});
const base = { failed: false, current: false, dirty: false, activeJob: null as ActiveJob | null, projectName: "p1" };
const status = (stage: Stage, p: ProjectProgress | undefined, extra: Partial<typeof base> = {}) =>
  stageStatus(stage, { ...base, progress: p, ...extra });

it("서버 상태를 상태 종류로 옮기고, 확인 필요는 첫 사유를 사실 문구로 보인다", () => {
  const p = progress([
    { stage: "purpose", state: "needs_review", reasons: ["report_type_unconfirmed"] },
    { stage: "sources", state: "not_started", reasons: ["sources_missing"] },
    { stage: "structure", state: "needs_review", reasons: ["stale_story_plan"] },
    { stage: "editing", state: "ready" },
  ]);
  expect(status("purpose", p)).toEqual({ kind: "needs_review", detail: "보고 유형을 직접 골랐는지는 아직 기록하지 않습니다" });
  expect(status("sources", p)).toEqual({ kind: "not_started" });
  expect(status("structure", p)?.detail).toBe(
    "자료, 보고 정보, 장 구성(편집 단계의 장 순서와 템플릿 포함)이 바뀌어 구성을 다시 확인해야 합니다");
  expect(status("editor", p)).toEqual({ kind: "ready" });  // 서버 이름 editing을 편집 단계로 옮긴다
});

it("검토 단계의 준비됨은 초안 확인됨이고, 섞인 상태는 남은 부분을 말한다 (C20)", () => {
  expect(status("review", progress([{ stage: "review", state: "ready" }]))).toEqual({ kind: "draft_checked" });
  expect(status("review", progress([{ stage: "review", state: "needs_review", reasons: ["human_review_pending"] }])))
    .toEqual({ kind: "needs_review", detail: "사람 검토가 남았습니다" });
});

it("모르는 사유는 준비됨으로 두지 않고 상태를 확인해 달라고 보인다", () => {
  const p = progress([{ stage: "sources", state: "ready", reasons: ["future_reason" as never] }]);
  expect(status("sources", p)).toEqual({ kind: "needs_review", detail: UNKNOWN_REASON_TEXT });
  expect(reasonText("future_reason")).toBe(UNKNOWN_REASON_TEXT);
});

it("조회가 실패하면 확인하지 못함이고, 첫 조회 전에는 표시하지 않는다", () => {
  expect(status("sources", undefined, { failed: true })).toEqual({ kind: "unknown" });
  expect(status("sources", undefined)).toBeNull();
  expect(status("sources", progress([]))).toEqual({ kind: "unknown" });  // 그 단계가 응답에 없다
});

it("작성 중(현재 단계의 미저장)이 서버의 준비됨보다 앞서고, 그 단계의 작업이 진행 중이면 생성 중이다", () => {
  const p = progress([{ stage: "structure", state: "ready" }, { stage: "editing", state: "ready" }]);
  expect(status("structure", p, { current: true, dirty: true })).toEqual({ kind: "in_progress" });
  expect(status("structure", p, { current: false, dirty: true })).toEqual({ kind: "ready" });  // 다른 단계는 그대로
  const job = { id: "j", project: "p1", kind: "chapters", target: null, stage: "running", created_at: "", cancel_requested: false } as ActiveJob;
  expect(status("structure", p, { activeJob: job })).toEqual({ kind: "running" });
  expect(status("editor", p, { activeJob: job })).toEqual({ kind: "ready" });
  expect(status("structure", p, { activeJob: { ...job, project: "다른" } })).toEqual({ kind: "ready" });
  expect(status("editor", p, { activeJob: { ...job, kind: "diagram", cancel_requested: true } })).toEqual({ kind: "cancel_requested" });
});

it("준비됨에 붙는 사유는 단계 목록에 보이지 않고 그 단계 화면의 한계 안내로 간다", () => {
  const p = progress([
    { stage: "sources", state: "ready", reasons: ["extraction_review_unavailable"] },
    { stage: "review", state: "needs_review", reasons: ["human_review_pending"], parts: [
      { name: "auto_checks", state: "ready", reasons: ["draft_checks_only"] },
      { name: "human_review", state: "not_started", reasons: [] },
      { name: "file", state: "ready", reasons: [] }] },
  ]);
  expect(status("sources", p)).toEqual({ kind: "ready" });
  expect(stageLimitations(p, "sources")).toEqual([REASON_TEXT.extraction_review_unavailable]);
  expect(stageLimitations(p, "review")).toEqual([REASON_TEXT.draft_checks_only]);
});

it("가장 최근 장 생성 묶음의 장 요약은 실패, 중단, 보류, 이전 입력 기준 후보를 나눠 센다", () => {
  const latest = batchView([
    chapterView("c1", "succeeded"),
    chapterView("c2", "failed", { error: { error_class: "connection", status: 503, detail: "x", code: null } }),
    chapterView("c3", "interrupted", { error: { error_class: "input", status: 409, detail: "x", code: "held_stale_plan" } }),
    chapterView("c4", "interrupted"),
    chapterView("c5", "succeeded", { candidate_status: "stale" }),
    chapterView("c6", "succeeded"),
  ], { state: "failed", outcome: "partial" });
  const older = batchView([chapterView("c1", "failed")], { id: "old" });
  expect(batchSummary([latest, older])).toBe("6장 중 1장 실패, 1장 중단, 1장 보류, 1장은 이전 입력 기준 후보");
  expect(batchSummary([batchView([chapterView("c1", "succeeded")])])).toBeNull();  // 모두 반영
  expect(batchSummary([{ ...latest, state: "running" }])).toBeNull();  // 진행 중은 생성 중 표시가 맡는다
  expect(batchSummary(null)).toBeNull();
});

it("확인 필요 단계에 한계 사유가 함께 와도 단계 목록은 한계 사유가 아닌 첫 사유를 보인다", () => {
  const p = progress([{ stage: "sources", state: "needs_review", reasons: ["extraction_review_unavailable", "sources_over_limit"] }]);
  expect(status("sources", p)).toEqual({ kind: "needs_review", detail: REASON_TEXT.sources_over_limit });
});
