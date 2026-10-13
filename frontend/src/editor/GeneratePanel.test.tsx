import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AiConsentDeclined, api, ApiError, type ChapterResult, type Deck } from "../api/client";
import { applyThroughCompare, compareDialog, previewOf } from "../test/compare";
import { jobView } from "../test/jobs";
import { emptyUsage, expectUsageCollapsed } from "../test/usage";
import { STALE_BASE } from "./CandidateCompareDialog";
import { APPLY_UNCONFIRMED, GeneratePanel } from "./GeneratePanel";
import fixture from "../../../backend/tests/fixtures/failure-bodies.json";

// 적용 라우트의 실제 오류 본문 (D3c-5). 서버 시험이 모아 고정한다(backend/tests/test_failure_bodies.py)
const applyBodies = (fixture as unknown as { apply: Record<string, { status: number; body: { detail: string; code?: string } }> }).apply;
const applyError = (name: string) => {
  const { status, body } = applyBodies[name];
  return new ApiError(status, body.detail, body.code);
};
// 편집기가 주는 서버 적용 연결의 기본값: 저장은 성공하고 나머지는 아무것도 하지 않는다
const H = { onFlush: async () => true, onApplied: () => {}, onConflict: () => {} };

// 계측값이 채워진 사용량 (미확인이 아님을 확인하는 테스트용, 단계 5A 묶음 C4)
function measuredUsage(): ChapterResult["usage"] {
  return {
    ...emptyUsage(), calls: 1,
    input_tokens: 100, output_tokens: 50, cache_read_tokens: 0, cache_creation_tokens: 0,
    duration_ms: 1000, duration_api_ms: 900, cost_usd: 0.01,
    records: [{ purpose: "generate", ok: true, usage: {
      model: null, input_tokens: 100, output_tokens: 50, cache_read_tokens: 0, cache_creation_tokens: 0,
      duration_ms: 1000, duration_api_ms: 900, num_turns: 1, cost_usd: 0.01, stop_reason: null,
      terminal_reason: "completed", api_error_status: null, token_source: "model_usage",
    } }],
  };
}

vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return { ...mod, api: { ...mod.api, prepareAi: vi.fn(), startJob: vi.fn(), getJob: vi.fn(), listJobs: vi.fn(),
    settleCandidate: vi.fn(), cancelJob: vi.fn(), applyCandidate: vi.fn(), previewCandidate: vi.fn() } };
});

// D2b-5b: 재생성과 축약은 작업 API로 등록하고 결과를 조회한다
beforeEach(() => {
  vi.mocked(api.prepareAi).mockResolvedValue({ "X-AI-Consent": "SlideCaptain" });
  vi.mocked(api.listJobs).mockResolvedValue([]);
  vi.mocked(api.settleCandidate).mockResolvedValue(jobView("chapter"));
  // 비교 화면의 미리 보기: 기본 선택은 모두 새 문구다 (D3c-6)
  vi.mocked(api.previewCandidate).mockImplementation(async () => previewOf(deck.slides[0], okResult.slots!));
  // 반영 직전 재조회의 기본 응답: 입력이 바뀌지 않은 후보 (D2b-β 리뷰 R9)
  vi.mocked(api.getJob).mockImplementation(async (_name, id) => jobView("chapter", { id, target: "c1",
    result: okResult as unknown as Record<string, unknown> }));
});

// 등록 응답이 곧 끝난 작업인 경우(조회 없이 결과)
function answer(result: ChapterResult, kind = "chapter", extra: Parameters<typeof jobView>[1] = {}) {
  const failed = result.status === "format_error";
  vi.mocked(api.startJob).mockResolvedValue(jobView(kind, {
    target: "c1", result: result as unknown as Record<string, unknown>,
    state: failed ? "failed" : "succeeded", candidate_status: failed ? "none" : "held",
    error: failed ? { error_class: "ai_output", status: null, detail: "형식 오류", code: "format_error" } : null,
    ...extra,
  }));
}

const project = { name: "p1", title: "제목", updated_at: "", status: "ok" as const };
const deck: Deck = {
  schema_version: 1,
  meta: { title: "t", report_type: "research", audience: "", presenter: "", preset_overrides: {} },
  structure: { chapters: [
    { id: "c1", topic: "주제", conclusion: "", template: "bullet_box", source_refs: [] }] },
  slides: [{ chapter_id: "c1", eyebrow: "", subtitle: "", slots: {
    template: "bullet_box", bullets: [{ text: "옛 내용", level: 0 }], conclusion: "결", footnote: "" } }],
};

const okResult: ChapterResult = {
  status: "ok", usage: emptyUsage(), raw_text: "", warnings: [], unverified_numbers: ["8888"],
  format_retried: false, condensed: true,
  slots: { template: "bullet_box", bullets: [{ text: "새 내용", level: 0 }], conclusion: "결", footnote: "" },
};

it("반영은 남은 편집을 저장한 뒤 서버가 후보를 합치게 하고 응답 덱을 저장본으로 받는다 (D3c-5, 계획 4.7)", async () => {
  answer(okResult);
  const saved: Deck = { ...deck, slides: [{ ...deck.slides[0], slots: okResult.slots! }] };
  vi.mocked(api.applyCandidate).mockResolvedValue(saved);
  const order: string[] = [];
  const onFlush = vi.fn(async () => { order.push("flush"); return true; });
  vi.mocked(api.applyCandidate).mockImplementation(async () => { order.push("apply"); return saved; });
  const onApplied = vi.fn();
  const onApplyBusyChange = vi.fn();
  render(<GeneratePanel project={project} deck={deck} chapterId="c1" {...H} onFlush={onFlush} onApplied={onApplied}
    onApplyBusyChange={onApplyBusyChange} />);
  await userEvent.click(screen.getByText("이 장 다시 생성"));
  expect(await screen.findByText(/8888/)).toBeInTheDocument();  // 수치 경고
  expect(screen.getByText(/축약했습니다/)).toBeInTheDocument();  // condensed 표시
  await applyThroughCompare();
  await waitFor(() => expect(onApplied).toHaveBeenCalledWith(saved, deck));
  // 비교 화면을 열기 전과 반영 직전에 저장한다 (계획 4.7의 1)
  expect(order).toEqual(["flush", "flush", "apply"]);
  // 미리 보기가 돌려준 실제 선택과 그 기준 저장본으로 반영한다 (리뷰 G1)
  expect(api.applyCandidate).toHaveBeenCalledWith("p1", "job-1", { keep_current: [], drop_edits: [], unhide: [] }, "e0");
  expect(api.settleCandidate).not.toHaveBeenCalled();  // 처분은 서버가 덱 저장과 함께 바꾼다
  expect(onApplyBusyChange.mock.calls).toEqual([[true], [false]]);
  expect(screen.queryByRole("button", { name: "비교하고 반영" })).toBeNull();
  // 연 버튼이 사라졌으므로 초점은 패널 제목으로 간다(문서 맨 앞으로 빠지지 않는다. 다시 생성 중에도 비활성이 되지 않는다)
  await waitFor(() => expect(screen.getByRole("heading", { name: "AI 다시 쓰기" })).toHaveFocus());
});

it("비교 화면에서 고친 선택이 미리 보기와 반영 요청에 그대로 실린다 (D3c-6)", async () => {
  answer(okResult);
  vi.mocked(api.previewCandidate).mockImplementation(async (_n, _j, body) => previewOf(deck.slides[0], okResult.slots!,
    { edited_units: ["conclusion"], keep_current: body?.keep_current ?? ["conclusion"] }));
  vi.mocked(api.applyCandidate).mockResolvedValue(deck);
  render(<GeneratePanel project={project} deck={deck} chapterId="c1" {...H} />);
  await userEvent.click(screen.getByText("이 장 다시 생성"));
  await userEvent.click(await screen.findByRole("button", { name: "비교하고 반영" }));
  const dialog = await compareDialog();
  // 기본은 직접 고친 결론을 지금 문구로 둔다. 바꾸면 바뀌는 곳의 수를 반영 버튼 옆에 보인다
  const conclusion = within(dialog).getByRole("group", { name: /결론 상자/ });
  expect(within(conclusion).getByRole("radio", { name: "지금 문구 유지" })).toBeChecked();
  await userEvent.click(within(conclusion).getByRole("radio", { name: "새 문구 사용" }));
  await waitFor(() => expect(api.previewCandidate).toHaveBeenLastCalledWith("p1", "job-1", { keep_current: [] }));
  expect(await within(dialog).findByText("직접 고친 문구 1곳이 새 문구로 바뀝니다.")).toBeInTheDocument();
  const apply = within(dialog).getByRole("button", { name: "반영" });
  await waitFor(() => expect(apply).toBeEnabled());
  await userEvent.click(apply);
  await waitFor(() => expect(api.applyCandidate).toHaveBeenCalledWith("p1", "job-1",
    { keep_current: [], drop_edits: [], unhide: [] }, "e0"));
});

it("반영 직전 저장을 기다리는 동안 장을 옮기면 반영을 요청하지 않는다 (리뷰 F7)", async () => {
  answer(okResult);
  let calls = 0;
  let finish: (ok: boolean) => void = () => {};
  const onFlush = () => (++calls === 1 ? Promise.resolve(true) : new Promise<boolean>((res) => { finish = res; }));
  const { rerender } = render(<GeneratePanel project={project} deck={deck} chapterId="c1" {...H} onFlush={onFlush} />);
  await userEvent.click(screen.getByText("이 장 다시 생성"));
  await applyThroughCompare();
  rerender(<GeneratePanel project={project} deck={deck} chapterId="c2" {...H} onFlush={onFlush} />);
  finish(true);
  await new Promise((r) => setTimeout(r, 20));
  expect(api.applyCandidate).not.toHaveBeenCalled();
});

it("비교 화면을 열기 전 저장이 실패하면 열지 않고 반영도 요청하지 않는다 (계획 4.7의 1)", async () => {
  answer(okResult);
  render(<GeneratePanel project={project} deck={deck} chapterId="c1" {...H} onFlush={async () => false} />);
  await userEvent.click(screen.getByText("이 장 다시 생성"));
  await userEvent.click(await screen.findByRole("button", { name: "비교하고 반영" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "비교하고 반영" })).toBeEnabled());
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(api.previewCandidate).not.toHaveBeenCalled();
  expect(api.applyCandidate).not.toHaveBeenCalled();
});

it("이 탭이 모르는 저장본으로 계산한 비교는 보이지 않고 충돌 경로로 보낸다 (계획 4.7의 1)", async () => {
  answer(okResult);
  const { resetEtags } = await import("../api/client");
  resetEtags();
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(deck), { status: 200, headers: { ETag: '"mine"' } })));
  await api.getDeck("p1");
  vi.unstubAllGlobals();
  vi.mocked(api.previewCandidate).mockResolvedValue(previewOf(deck.slides[0], okResult.slots!, { base_etag: "other" }));
  const onConflict = vi.fn();
  render(<GeneratePanel project={project} deck={deck} chapterId="c1" {...H} onConflict={onConflict} />);
  await userEvent.click(screen.getByText("이 장 다시 생성"));
  await userEvent.click(await screen.findByRole("button", { name: "비교하고 반영" }));
  await waitFor(() => expect(onConflict).toHaveBeenCalledWith(STALE_BASE));
  expect(screen.queryByRole("dialog")).toBeNull();
  resetEtags();
});

it.each([
  ["deck_conflict", "다른 창이나 프로그램에서 먼저 저장되었습니다. 최신 덱을 다시 읽어 주세요."],
  ["deck_write_failed", APPLY_UNCONFIRMED],
  ["ledger_write_failed", APPLY_UNCONFIRMED],
])("적용 오류 %s는 편집기의 충돌 경로로 보내 자동 저장을 멈추고 다시 읽게 한다 (계획 4.7의 4, 6)", async (name, message) => {
  answer(okResult);
  vi.mocked(api.applyCandidate).mockRejectedValue(applyError(name));
  const onConflict = vi.fn();
  render(<GeneratePanel project={project} deck={deck} chapterId="c1" {...H} onConflict={onConflict} />);
  await userEvent.click(screen.getByText("이 장 다시 생성"));
  await applyThroughCompare();
  await waitFor(() => expect(onConflict).toHaveBeenCalledWith(message));
  expect(screen.queryByRole("alert")).toBeNull();  // 안내는 편집기의 충돌 배너 하나다
});

// 서버 판정이 반영을 막은 코드와 그 표시 (D3c-5, 리뷰 F5와 F7). 실제 본문이 고정 파일에 없는 코드는 같은 모양으로 만든다
const BLOCKED: [string, string][] = [
  ["sources_changed", "자료가 바뀌었습니다"], ["slots_changed", "이 장의 내용이 바뀌었습니다"],
  ["chapter_changed", "이 장의 주제나 결론이 바뀌었습니다"], ["story_plan_changed", "보고 계획이 바뀌었습니다"],
  ["template_changed", "이 장의 템플릿이 바뀌었습니다"], ["chapter_missing", "이 장이 구조안에서 빠졌습니다"],
  ["not_applicable", "이전 버전에서 만든 결과라 반영 여부를 판정할 수 없습니다"],
];
it.each(BLOCKED)("서버가 %s로 반영을 막으면 반영 대신 이전 입력 기준 후보와 다시 생성을 보인다", async (code, label) => {
  answer(okResult);
  vi.mocked(api.applyCandidate).mockRejectedValue(applyBodies[code] ? applyError(code)
    : new ApiError(409, "이 후보는 지금 반영할 수 없습니다.", code));
  vi.mocked(api.getJob).mockResolvedValue(jobView("chapter", { target: "c1", result: okResult as unknown as Record<string, unknown> }));
  const onConflict = vi.fn();
  render(<GeneratePanel project={project} deck={deck} chapterId="c1" {...H} onConflict={onConflict} />);
  await userEvent.click(screen.getByText("이 장 다시 생성"));
  await applyThroughCompare();
  expect(await screen.findByText(new RegExp(`이전 입력 기준 후보입니다\\(${label}\\)`))).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "비교하고 반영" })).toBeNull();
  expect(screen.getByText("현재 입력으로 다시 생성")).toBeInTheDocument();
  expect(api.getJob).toHaveBeenCalledWith("p1", "job-1");
  expect(onConflict).not.toHaveBeenCalled();
});

it("다른 탭이 먼저 처분한 후보는 결과를 닫고 그 사실을 알린다 (리뷰 F5)", async () => {
  answer(okResult);
  vi.mocked(api.applyCandidate).mockRejectedValue(applyError("candidate_settled"));
  render(<GeneratePanel project={project} deck={deck} chapterId="c1" {...H} />);
  await userEvent.click(screen.getByText("이 장 다시 생성"));
  await applyThroughCompare();
  expect(await screen.findByRole("alert")).toHaveTextContent(applyBodies.candidate_settled.body.detail);
  expect(screen.queryByRole("button", { name: "비교하고 반영" })).toBeNull();
});

it("묶음 실행 중이면 안내하고 반영 버튼은 남겨 묶음이 끝난 뒤 다시 누를 수 있다", async () => {
  answer(okResult);
  vi.mocked(api.applyCandidate).mockRejectedValue(applyError("batch_active"));
  render(<GeneratePanel project={project} deck={deck} chapterId="c1" {...H} />);
  await userEvent.click(screen.getByText("이 장 다시 생성"));
  await applyThroughCompare();
  expect(await screen.findByRole("alert")).toHaveTextContent(applyBodies.batch_active.body.detail);
  expect(screen.getByRole("button", { name: "비교하고 반영" })).toBeEnabled();
});

it("다시 열면 처분하지 않은 지난 결과를 보이고 반영할 수 있다", async () => {
  vi.mocked(api.listJobs).mockResolvedValue([jobView("chapter", { target: "c1",
    result: okResult as unknown as Record<string, unknown> })]);
  vi.mocked(api.applyCandidate).mockResolvedValue(deck);
  const onApplied = vi.fn();
  render(<GeneratePanel project={project} deck={deck} chapterId="c1" {...H} onApplied={onApplied} />);
  expect(await screen.findByText("이전에 만든 결과가 있습니다.")).toBeInTheDocument();
  await applyThroughCompare();
  await waitFor(() => expect(onApplied).toHaveBeenCalled());
  expect(api.startJob).not.toHaveBeenCalled();
});

it("재생성 중 다른 장으로 옮겼다 돌아오면 끝난 결과가 보인다 (지금은 응답을 버린다)", async () => {
  const running = jobView("chapter", { target: "c1", state: "running", candidate_status: "none" });
  vi.mocked(api.startJob).mockResolvedValue(running);
  vi.mocked(api.getJob).mockImplementation(() => new Promise(() => {}));  // 첫 화면에서는 끝나지 않는다
  const { rerender } = render(<GeneratePanel project={project} deck={deck} chapterId="c1" {...H}
    pollIntervalMs={0} />);
  await userEvent.click(screen.getByText("이 장 다시 생성"));
  await waitFor(() => expect(api.getJob).toHaveBeenCalled());
  rerender(<GeneratePanel project={project} deck={deck} chapterId="c2" {...H} pollIntervalMs={0} />);
  // 돌아오면 목록에 진행 중 작업이 있고 조회하면 끝나 있다
  vi.mocked(api.listJobs).mockResolvedValue([running]);
  vi.mocked(api.getJob).mockResolvedValue(jobView("chapter", { target: "c1",
    result: okResult as unknown as Record<string, unknown> }));
  rerender(<GeneratePanel project={project} deck={deck} chapterId="c1" {...H} pollIntervalMs={0} />);
  expect(await screen.findByRole("button", { name: "비교하고 반영" })).toBeInTheDocument();
  expect(api.startJob).toHaveBeenCalledTimes(1);  // 다시 생성하지 않았다
});

it("관련 입력이 바뀐 후보는 반영 대신 이전 입력 기준 후보와 다시 생성을 보인다", async () => {
  vi.mocked(api.listJobs).mockResolvedValue([jobView("chapter", { target: "c1", candidate_status: "held",
    stale_reasons: ["template_changed"], result: okResult as unknown as Record<string, unknown> })]);
  answer(okResult, "chapter", { id: "job-2" });
  render(<GeneratePanel project={project} deck={deck} chapterId="c1" {...H} />);
  expect(await screen.findByText(/이전 입력 기준 후보입니다\(이 장의 템플릿이 바뀌었습니다\)/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "비교하고 반영" })).toBeNull();
  // 막힌 후보도 비교는 보인다. 반영 버튼은 잠기고 다시 생성은 비교 화면을 닫은 뒤 부른다 (계획 4.8)
  vi.mocked(api.previewCandidate).mockResolvedValue(previewOf(deck.slides[0], okResult.slots!,
    { blocked_reasons: ["template_changed"] }));
  await userEvent.click(screen.getByRole("button", { name: "비교 보기" }));
  const dialog = await compareDialog();
  expect(within(dialog).getByRole("group", { name: /본문 불릿/ })).toHaveTextContent("새 내용");
  expect(within(dialog).getByRole("button", { name: "반영" })).toBeDisabled();
  await userEvent.click(within(dialog).getByRole("button", { name: "현재 입력으로 다시 생성" }));
  expect(screen.queryByRole("dialog")).toBeNull();
  await waitFor(() => expect(api.startJob).toHaveBeenCalled());
  expect(vi.mocked(api.startJob).mock.calls[0][1].kind).toBe("chapter");
});

it("덱의 다른 부분만 바뀐 후보는 안내만 하고 반영할 수 있다", async () => {
  answer(okResult, "chapter", { stale_reasons: ["deck_changed_elsewhere"] });
  render(<GeneratePanel project={project} deck={deck} chapterId="c1" {...H} />);
  await userEvent.click(screen.getByText("이 장 다시 생성"));
  expect(await screen.findByText("덱의 다른 부분이 바뀌었지만 이 장의 입력은 그대로입니다.")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "비교하고 반영" })).toBeInTheDocument();
});

it("축약 후보는 요청한 슬롯과 지금 슬롯이 다르면 반영하지 않는다", async () => {
  vi.mocked(api.listJobs).mockResolvedValue([jobView("condense", { target: "c1",
    params: { chapter_id: "c1", slots: { template: "bullet_box", bullets: [], conclusion: "다른 슬롯", footnote: "" } },
    result: okResult as unknown as Record<string, unknown> })]);
  render(<GeneratePanel project={project} deck={deck} chapterId="c1" {...H} />);
  expect(await screen.findByText(/이 장의 내용이 바뀌었습니다/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "비교하고 반영" })).toBeNull();
});

it("다른 AI 생성이 진행 중이면 그 작업을 취소할 수 있다", async () => {
  vi.mocked(api.startJob).mockRejectedValue(new ApiError(409, "다른 AI 생성이 진행 중입니다. 끝난 뒤 다시 시도해 주세요.",
    "generation_active", { id: "job-9", project: "다른보고", kind: "diagram", target: null, stage: "running",
      created_at: "2026-10-08T10:00:00+09:00", cancel_requested: false }));
  vi.mocked(api.cancelJob).mockResolvedValue(jobView("diagram"));
  render(<GeneratePanel project={project} deck={deck} chapterId="c1" {...H} />);
  await userEvent.click(screen.getByText("이 장 다시 생성"));
  await userEvent.click(await screen.findByText("그 작업 취소"));
  expect(api.cancelJob).toHaveBeenCalledWith("다른보고", "job-9");
});

it("취소로 끝난 작업은 오류가 아니라 안내로 보인다", async () => {
  vi.mocked(api.startJob).mockResolvedValue(jobView("chapter", { state: "cancelled", candidate_status: "none" }));
  render(<GeneratePanel project={project} deck={deck} chapterId="c1" {...H} />);
  await userEvent.click(screen.getByText("이 장 다시 생성"));
  expect(await screen.findByText("생성이 취소되었습니다.")).toBeInTheDocument();
  expect(screen.queryByRole("alert")).toBeNull();
});

it("구성 계획 낡음 오류는 복구 안내로 보인다", async () => {
  vi.mocked(api.startJob).mockResolvedValue(jobView("chapter", { state: "failed", candidate_status: "none",
    error: { error_class: "input", status: 409, detail: "구조안을 다시 생성해 주세요.", code: "stale_story_plan" } }));
  render(<GeneratePanel project={project} deck={deck} chapterId="c1" {...H} />);
  await userEvent.click(screen.getByText("이 장 다시 생성"));
  expect(await screen.findByRole("region", { name: "보고 계획 복구 안내" })).toBeInTheDocument();
});

it("축약은 현재 슬롯을 동봉해 호출한다", async () => {
  answer(okResult, "condense");
  render(<GeneratePanel project={project} deck={deck} chapterId="c1" {...H} />);
  await userEvent.click(screen.getByText("이 장 축약"));
  await waitFor(() => expect(api.startJob).toHaveBeenCalled());
  const [name, body, , ifMatch] = vi.mocked(api.startJob).mock.calls[0];
  expect(name).toBe("p1");
  expect(body.kind).toBe("condense");
  const sentSlots = (body.params as { chapter_id: string; slots: ChapterResult["slots"] }).slots!;
  expect((body.params as { chapter_id: string }).chapter_id).toBe("c1");
  expect(sentSlots.template === "bullet_box" && sentSlots.bullets?.[0].text).toBe("옛 내용");
  expect(ifMatch).toBeUndefined();  // 장 생성은 기준 저장본을 If-Match로 받지 않는다
});

it("형식 오류는 원문과 재시도 경로를 보여주고 버리기 전까지 반영 버튼이 없다", async () => {
  answer({
    status: "format_error", slots: null, usage: emptyUsage(), raw_text: "이상한 원문",
    warnings: [], unverified_numbers: [], format_retried: true, condensed: false,
  });
  render(<GeneratePanel project={project} deck={deck} chapterId="c1" {...H} />);
  await userEvent.click(screen.getByText("이 장 다시 생성"));
  expect(await screen.findByText(/형식에 맞게 읽지 못했습니다/)).toBeInTheDocument();
  expect(screen.getByText("이상한 원문")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "비교하고 반영" })).not.toBeInTheDocument();
});

it("장을 전환하면 이전 장의 결과 패널이 사라진다", async () => {
  answer(okResult);
  const { rerender } = render(
    <GeneratePanel project={project} deck={deck} chapterId="c1" {...H} />);
  await userEvent.click(screen.getByText("이 장 다시 생성"));
  expect(await screen.findByRole("button", { name: "비교하고 반영" })).toBeInTheDocument();
  rerender(<GeneratePanel project={project} deck={deck} chapterId="c2" {...H} />);
  expect(screen.queryByRole("button", { name: "비교하고 반영" })).not.toBeInTheDocument();
});

// AI 전송 고지 취소 (계획서 B3): 취소는 실패가 아니므로 role=alert가 아닌 안내 문구로 보인다
it("재생성에서 AI 전송을 취소하면 알림이 아닌 안내 문구를 보인다", async () => {
  vi.mocked(api.prepareAi).mockRejectedValue(new AiConsentDeclined());
  render(<GeneratePanel project={project} deck={deck} chapterId="c1" {...H} />);
  await userEvent.click(screen.getByText("이 장 다시 생성"));
  const notice = await screen.findByText("전송을 취소했습니다. 필요하면 다시 시도해 주세요.");
  expect(notice.closest('[role="alert"]')).toBeNull();
  expect(screen.queryByRole("alert")).toBeNull();
});

it("축약에서 AI 전송을 취소해도 알림이 아닌 안내 문구를 보인다", async () => {
  vi.mocked(api.prepareAi).mockRejectedValue(new AiConsentDeclined());
  render(<GeneratePanel project={project} deck={deck} chapterId="c1" {...H} />);
  await userEvent.click(screen.getByText("이 장 축약"));
  const notice = await screen.findByText("전송을 취소했습니다. 필요하면 다시 시도해 주세요.");
  expect(notice.closest('[role="alert"]')).toBeNull();
});

// 태스크 C4: 결과 안내(축약, 재시도 문구) 옆에 사용량 한 줄을 보인다
it("재생성 결과의 사용량 한 줄은 접힌 진단 상세에 있다 (D3a-4, R12)", async () => {
  // F8 리뷰 반영: 제목이 실제로 검증하지 않는 "값이 없으면 미확인" 주장을 포함하고 있었다.
  // 그 케이스는 바로 다음 테스트가 담당하므로 제목을 실제 검증 내용에 맞춘다.
  answer({ ...okResult, usage: measuredUsage() });
  render(<GeneratePanel project={project} deck={deck} chapterId="c1" {...H} />);
  await userEvent.click(screen.getByText("이 장 다시 생성"));
  expect(await screen.findByText(/AI 사용량: 호출 1회/)).toBeInTheDocument();
  expect(screen.getByText(/입력 100 토큰/)).toBeInTheDocument();
  expectUsageCollapsed();
  await userEvent.click(screen.getByText("진단 상세"));
  expect(screen.getByText(/입력 100 토큰/)).toBeVisible();
});

it("사용량 값이 없으면 미확인이 보인다", async () => {
  answer(okResult);  // okResult.usage는 emptyUsage()
  render(<GeneratePanel project={project} deck={deck} chapterId="c1" {...H} />);
  await userEvent.click(screen.getByText("이 장 다시 생성"));
  expect(await screen.findByText(/토큰 미확인/)).toBeInTheDocument();
  expect(screen.getByText(/비용 미확인/)).toBeInTheDocument();
});

// F5 리뷰 반영: usage는 상태와 무관하게 항상 채워지는 필수 필드다(C2/C3 가정 6). 형식 오류로
// 끝나도 최소 1회 호출은 있었으므로 그 사용량을 화면에서 감추면 안 된다.
it("형식 오류면 원인별 안내를 보이고 사용량과 응답 원문은 그 진단 상세에 둔다 (D3a-4)", async () => {
  answer({
    status: "format_error", slots: null, usage: measuredUsage(), raw_text: "이상한 원문",
    warnings: [], unverified_numbers: [], format_retried: true, condensed: false,
  });
  render(<GeneratePanel project={project} deck={deck} chapterId="c1" {...H} />);
  await userEvent.click(screen.getByText("이 장 다시 생성"));
  const alert = (await screen.findByText(/형식에 맞게 읽지 못했습니다/)).closest("[role=alert]")!;
  expect(alert).toHaveTextContent(/입력은 그대로입니다.*지금 할 수 있는 일: 위의 '이 장 다시 생성'/);
  expect(screen.getByText(/AI 사용량: 호출 1회/)).toBeInTheDocument();
  expectUsageCollapsed();
  expect(screen.getByText("이상한 원문")).not.toBeVisible();
  expect(within(alert as HTMLElement).getByText("이상한 원문")).toBeInTheDocument();
});

it("지시사항 입력이 .field 안에 있고 버튼은 .actions 행에 있다", () => {
  render(<GeneratePanel project={project} deck={deck} chapterId="c1" {...H} />);
  expect(screen.getByLabelText("재생성 지시사항").closest(".field")).not.toBeNull();
  expect(screen.getByText("이 장 다시 생성").closest(".actions")).not.toBeNull();
});

// -- D2b-5b 리뷰 반영 ------------------------------------------------------------------------

it("후보가 보이는 채로 다시 생성하면 등록 뒤 앞 후보를 버림으로 처분한다 (리뷰 R2)", async () => {
  vi.mocked(api.listJobs).mockResolvedValue([jobView("chapter", { id: "job-a", target: "c1",
    result: okResult as unknown as Record<string, unknown> })]);
  answer(okResult, "chapter", { id: "job-b" });
  render(<GeneratePanel project={project} deck={deck} chapterId="c1" {...H} />);
  await screen.findByText("이전에 만든 결과가 있습니다.");
  await userEvent.click(screen.getByText("이 장 다시 생성"));
  await waitFor(() => expect(api.settleCandidate).toHaveBeenCalledWith("p1", "job-a", "dismissed"));
});

it("동의를 거절하면 보이던 후보를 버리지 않는다 (리뷰 R2)", async () => {
  vi.mocked(api.listJobs).mockResolvedValue([jobView("chapter", { id: "job-a", target: "c1",
    result: okResult as unknown as Record<string, unknown> })]);
  vi.mocked(api.prepareAi).mockRejectedValue(new AiConsentDeclined());
  render(<GeneratePanel project={project} deck={deck} chapterId="c1" {...H} />);
  await screen.findByText("이전에 만든 결과가 있습니다.");
  await userEvent.click(screen.getByText("이 장 다시 생성"));
  await screen.findByText("전송을 취소했습니다. 필요하면 다시 시도해 주세요.");
  expect(api.settleCandidate).not.toHaveBeenCalled();
});

it("서버가 키 순서와 기본값을 바꿔 저장한 축약 요청도 지금 슬롯과 같으면 반영할 수 있다 (리뷰 R3)", async () => {
  const sent = deck.slides[0].slots as { bullets: unknown[]; conclusion: string };
  answer(okResult, "condense", { target: "c1", params: { chapter_id: "c1", instructions: "",
    slots: { footnote: "", conclusion: sent.conclusion, bullets: sent.bullets, template: "bullet_box" } } });
  render(<GeneratePanel project={project} deck={deck} chapterId="c1" {...H} />);
  await userEvent.click(screen.getByText("이 장 축약"));
  expect(await screen.findByRole("button", { name: "비교하고 반영" })).toBeInTheDocument();
});

it("서버가 낡은 후보로 기록한 결과는 반영 대신 다시 생성을 보인다 (리뷰 R10)", async () => {
  vi.mocked(api.listJobs).mockResolvedValue([jobView("chapter", { target: "c1", candidate_status: "stale",
    result: okResult as unknown as Record<string, unknown> })]);
  render(<GeneratePanel project={project} deck={deck} chapterId="c1" {...H} />);
  expect(await screen.findByText(/만드는 동안 입력이 바뀌었던 후보입니다/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "비교하고 반영" })).toBeNull();
});

it("조회가 실패하면 확인하지 못했다고 알리고 계속 조회한다", async () => {
  vi.mocked(api.startJob).mockResolvedValue(jobView("chapter", { target: "c1", state: "running", candidate_status: "none" }));
  vi.mocked(api.getJob).mockRejectedValueOnce(new ApiError(503, "연결 오류"))
    .mockResolvedValueOnce(jobView("chapter", { target: "c1", result: okResult as unknown as Record<string, unknown> }));
  render(<GeneratePanel project={project} deck={deck} chapterId="c1" {...H} pollIntervalMs={30} />);
  await userEvent.click(screen.getByText("이 장 다시 생성"));
  expect(await screen.findByText("작업 상태를 확인하지 못했습니다. 계속 확인합니다.")).toBeInTheDocument();
  expect(await screen.findByRole("button", { name: "비교하고 반영" })).toBeInTheDocument();
  expect(screen.queryByText("작업 상태를 확인하지 못했습니다. 계속 확인합니다.")).toBeNull();
});

it("앞 작업의 취소 안내가 다음 작업의 취소 버튼을 가리지 않는다 (리뷰 R13)", async () => {
  const active = (id: string) => new ApiError(409, "다른 AI 생성이 진행 중입니다.", "generation_active",
    { id, project: "다른보고", kind: "diagram", target: null, stage: "running", created_at: "", cancel_requested: false });
  vi.mocked(api.startJob).mockRejectedValueOnce(active("job-9")).mockRejectedValueOnce(new ApiError(503, "다른 오류"))
    .mockRejectedValueOnce(active("job-10"));
  vi.mocked(api.cancelJob).mockResolvedValue(jobView("diagram"));
  render(<GeneratePanel project={project} deck={deck} chapterId="c1" {...H} />);
  await userEvent.click(screen.getByText("이 장 다시 생성"));
  await userEvent.click(await screen.findByText("그 작업 취소"));
  await userEvent.click(screen.getByText("이 장 다시 생성"));
  await screen.findByText("다른 오류");
  await userEvent.click(screen.getByText("이 장 다시 생성"));
  await userEvent.click(await screen.findByText("그 작업 취소"));
  expect(api.cancelJob).toHaveBeenLastCalledWith("다른보고", "job-10");
});

// -- D2b-β 리뷰 R9의 반영 직전 판정은 D3c-5부터 서버가 저장 직전에 한다. 화면의 사전 조회와 그 실패 안내는 없앴다 ----------

it("반영 직전에 입력이 바뀐 후보는 서버가 막고 이전 입력 기준 후보로 보인다 (β 리뷰 R9, D3c-5)", async () => {
  vi.mocked(api.listJobs).mockResolvedValue([jobView("chapter", { id: "job-e", target: "c1",
    result: okResult as unknown as Record<string, unknown> })]);
  vi.mocked(api.applyCandidate).mockRejectedValue(applyError("sources_changed"));
  vi.mocked(api.getJob).mockResolvedValue(jobView("chapter", { id: "job-e", target: "c1", stale_reasons: ["sources_changed"],
    result: okResult as unknown as Record<string, unknown> }));
  const onApplied = vi.fn();
  render(<GeneratePanel project={project} deck={deck} chapterId="c1" {...H} onApplied={onApplied} />);
  await applyThroughCompare();
  expect(await screen.findByText(/이전 입력 기준 후보입니다\(자료가 바뀌었습니다\)/)).toBeInTheDocument();
  expect(api.getJob).toHaveBeenCalledWith("p1", "job-e");
  expect(onApplied).not.toHaveBeenCalled();
  expect(screen.queryByRole("button", { name: "비교하고 반영" })).toBeNull();
});

// D3a-4 리뷰 R25, R8과 묶음 리뷰 A8: 실패 안내는 같은 일을 하는 버튼을 하나 더 두지 않고 위쪽 버튼을 가리킨다
const formatError: ChapterResult = {
  status: "format_error", slots: null, usage: emptyUsage(), raw_text: "이상한 원문",
  warnings: [], unverified_numbers: [], format_retried: true, condensed: false,
};

it("실패 안내는 위쪽의 다시 생성과 축약 버튼을 가리키고 안내 안에 버튼을 두지 않는다 (묶음 리뷰 A8)", async () => {
  answer(formatError, "condense");
  render(<GeneratePanel project={project} deck={deck} chapterId="c1" {...H} />);
  await userEvent.click(screen.getByText("이 장 축약"));
  const alert = (await screen.findByText(/형식에 맞게 읽지 못했습니다/)).closest("[role=alert]") as HTMLElement;
  expect(alert).toHaveTextContent("지금 할 수 있는 일: 위의 '이 장 다시 생성'이나 '이 장 축약'을 다시 눌러 주세요.");
  expect(within(alert).queryAllByRole("button")).toHaveLength(0);
  expect(screen.getAllByRole("button", { name: "이 장 축약" })).toHaveLength(1);
});

it("비교를 열기 전 저장을 기다리는 사이 장을 옮기면 비교 화면을 열지 않는다 (D3c-6 리뷰 V11)", async () => {
  answer(okResult);
  let flushed: (ok: boolean) => void = () => {};
  const onFlush = vi.fn(() => new Promise<boolean>((res) => { flushed = res; }));
  const { rerender } = render(<GeneratePanel project={project} deck={deck} chapterId="c1" {...H} onFlush={onFlush} />);
  await userEvent.click(screen.getByText("이 장 다시 생성"));
  await userEvent.click(await screen.findByRole("button", { name: "비교하고 반영" }));
  await waitFor(() => expect(onFlush).toHaveBeenCalled());
  // 옮겨 간 장에도 처분하지 않은 후보가 있다. 검사가 없으면 그 장의 비교 화면이 사용자 조작 없이 열린다
  vi.mocked(api.listJobs).mockResolvedValue([jobView("chapter", { id: "job-2", target: "c2",
    result: okResult as unknown as Record<string, unknown>, state: "succeeded", candidate_status: "held" })]);
  rerender(<GeneratePanel project={project} deck={deck} chapterId="c2" {...H} onFlush={onFlush} />);
  expect(await screen.findByRole("button", { name: "비교하고 반영" })).toBeInTheDocument();
  flushed(true);
  await new Promise((r) => setTimeout(r, 0));
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(api.previewCandidate).not.toHaveBeenCalled();
});
