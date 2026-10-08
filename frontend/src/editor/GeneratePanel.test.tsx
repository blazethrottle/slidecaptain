import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AiConsentDeclined, api, ApiError, type ChapterResult, type Deck } from "../api/client";
import { jobView } from "../test/jobs";
import { emptyUsage } from "../test/usage";
import { GeneratePanel } from "./GeneratePanel";

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
    settleCandidate: vi.fn(), cancelJob: vi.fn() } };
});

// D2b-5b: 재생성과 축약은 작업 API로 등록하고 결과를 조회한다
beforeEach(() => {
  vi.mocked(api.prepareAi).mockResolvedValue({ "X-AI-Consent": "SlideCaptain" });
  vi.mocked(api.listJobs).mockResolvedValue([]);
  vi.mocked(api.settleCandidate).mockResolvedValue(jobView("chapter"));
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

it("재생성 결과를 보여주고 반영하면 onReplace에 새 슬롯이 담긴다", async () => {
  answer(okResult);
  const onReplace = vi.fn();
  render(<GeneratePanel project={project} deck={deck} chapterId="c1" onReplace={onReplace} />);
  await userEvent.click(screen.getByText("이 장 다시 생성"));
  expect(await screen.findByText(/8888/)).toBeInTheDocument();  // 수치 경고
  expect(screen.getByText(/축약했습니다/)).toBeInTheDocument();  // condensed 표시
  await userEvent.click(screen.getByText("반영"));
  const next = onReplace.mock.calls[0][0] as Deck;
  const slots = next.slides[0].slots;
  expect(slots.template === "bullet_box" && slots.bullets?.[0].text).toBe("새 내용");
  expect(api.settleCandidate).toHaveBeenCalledWith("p1", "job-1", "applied");  // 반영한 후보는 다시 보이지 않는다
});

// -- D2b-5b: 후보의 처분, 다시 열기, 낡음 -----------------------------------------------------------

it("버리면 후보를 버림으로 처분한다", async () => {
  answer(okResult);
  render(<GeneratePanel project={project} deck={deck} chapterId="c1" onReplace={() => {}} />);
  await userEvent.click(screen.getByText("이 장 다시 생성"));
  await userEvent.click(await screen.findByText("버리기"));
  expect(api.settleCandidate).toHaveBeenCalledWith("p1", "job-1", "dismissed");
  expect(screen.queryByText("반영")).toBeNull();
});

it("다시 열면 처분하지 않은 지난 결과를 보이고 반영할 수 있다", async () => {
  vi.mocked(api.listJobs).mockResolvedValue([jobView("chapter", { target: "c1",
    result: okResult as unknown as Record<string, unknown> })]);
  const onReplace = vi.fn();
  render(<GeneratePanel project={project} deck={deck} chapterId="c1" onReplace={onReplace} />);
  expect(await screen.findByText("이전에 만든 결과가 있습니다.")).toBeInTheDocument();
  await userEvent.click(screen.getByText("반영"));
  expect(onReplace).toHaveBeenCalled();
  expect(api.startJob).not.toHaveBeenCalled();
});

it("재생성 중 다른 장으로 옮겼다 돌아오면 끝난 결과가 보인다 (지금은 응답을 버린다)", async () => {
  const running = jobView("chapter", { target: "c1", state: "running", candidate_status: "none" });
  vi.mocked(api.startJob).mockResolvedValue(running);
  vi.mocked(api.getJob).mockImplementation(() => new Promise(() => {}));  // 첫 화면에서는 끝나지 않는다
  const { rerender } = render(<GeneratePanel project={project} deck={deck} chapterId="c1" onReplace={() => {}}
    pollIntervalMs={0} />);
  await userEvent.click(screen.getByText("이 장 다시 생성"));
  await waitFor(() => expect(api.getJob).toHaveBeenCalled());
  rerender(<GeneratePanel project={project} deck={deck} chapterId="c2" onReplace={() => {}} pollIntervalMs={0} />);
  // 돌아오면 목록에 진행 중 작업이 있고 조회하면 끝나 있다
  vi.mocked(api.listJobs).mockResolvedValue([running]);
  vi.mocked(api.getJob).mockResolvedValue(jobView("chapter", { target: "c1",
    result: okResult as unknown as Record<string, unknown> }));
  rerender(<GeneratePanel project={project} deck={deck} chapterId="c1" onReplace={() => {}} pollIntervalMs={0} />);
  expect(await screen.findByText("반영")).toBeInTheDocument();
  expect(api.startJob).toHaveBeenCalledTimes(1);  // 다시 생성하지 않았다
});

it("관련 입력이 바뀐 후보는 반영 대신 이전 입력 기준 후보와 다시 생성을 보인다", async () => {
  vi.mocked(api.listJobs).mockResolvedValue([jobView("chapter", { target: "c1", candidate_status: "held",
    stale_reasons: ["template_changed"], result: okResult as unknown as Record<string, unknown> })]);
  answer(okResult, "chapter", { id: "job-2" });
  render(<GeneratePanel project={project} deck={deck} chapterId="c1" onReplace={() => {}} />);
  expect(await screen.findByText(/이전 입력 기준 후보입니다\(이 장의 템플릿이 바뀌었습니다\)/)).toBeInTheDocument();
  expect(screen.queryByText("반영")).toBeNull();
  await userEvent.click(screen.getByText("후보 보기"));
  expect(screen.getByText(/새 내용/)).toBeInTheDocument();
  await userEvent.click(screen.getByText("현재 입력으로 다시 생성"));
  await waitFor(() => expect(api.startJob).toHaveBeenCalled());
  expect(vi.mocked(api.startJob).mock.calls[0][1].kind).toBe("chapter");
});

it("덱의 다른 부분만 바뀐 후보는 안내만 하고 반영할 수 있다", async () => {
  answer(okResult, "chapter", { stale_reasons: ["deck_changed_elsewhere"] });
  render(<GeneratePanel project={project} deck={deck} chapterId="c1" onReplace={() => {}} />);
  await userEvent.click(screen.getByText("이 장 다시 생성"));
  expect(await screen.findByText("덱의 다른 부분이 바뀌었지만 이 장의 입력은 그대로입니다.")).toBeInTheDocument();
  expect(screen.getByText("반영")).toBeInTheDocument();
});

it("축약 후보는 요청한 슬롯과 지금 슬롯이 다르면 반영하지 않는다", async () => {
  vi.mocked(api.listJobs).mockResolvedValue([jobView("condense", { target: "c1",
    params: { chapter_id: "c1", slots: { template: "bullet_box", bullets: [], conclusion: "다른 슬롯", footnote: "" } },
    result: okResult as unknown as Record<string, unknown> })]);
  render(<GeneratePanel project={project} deck={deck} chapterId="c1" onReplace={() => {}} />);
  expect(await screen.findByText(/이 장의 내용이 바뀌었습니다/)).toBeInTheDocument();
  expect(screen.queryByText("반영")).toBeNull();
});

it("다른 AI 생성이 진행 중이면 그 작업을 취소할 수 있다", async () => {
  vi.mocked(api.startJob).mockRejectedValue(new ApiError(409, "다른 AI 생성이 진행 중입니다. 끝난 뒤 다시 시도해 주세요.",
    "generation_active", { id: "job-9", project: "다른보고", kind: "diagram", target: null, stage: "running",
      created_at: "2026-10-08T10:00:00+09:00", cancel_requested: false }));
  vi.mocked(api.cancelJob).mockResolvedValue(jobView("diagram"));
  render(<GeneratePanel project={project} deck={deck} chapterId="c1" onReplace={() => {}} />);
  await userEvent.click(screen.getByText("이 장 다시 생성"));
  await userEvent.click(await screen.findByText("그 작업 취소"));
  expect(api.cancelJob).toHaveBeenCalledWith("다른보고", "job-9");
});

it("취소로 끝난 작업은 오류가 아니라 안내로 보인다", async () => {
  vi.mocked(api.startJob).mockResolvedValue(jobView("chapter", { state: "cancelled", candidate_status: "none" }));
  render(<GeneratePanel project={project} deck={deck} chapterId="c1" onReplace={() => {}} />);
  await userEvent.click(screen.getByText("이 장 다시 생성"));
  expect(await screen.findByText("생성이 취소되었습니다.")).toBeInTheDocument();
  expect(screen.queryByRole("alert")).toBeNull();
});

it("구성 계획 낡음 오류는 복구 안내로 보인다", async () => {
  vi.mocked(api.startJob).mockResolvedValue(jobView("chapter", { state: "failed", candidate_status: "none",
    error: { error_class: "input", status: 409, detail: "구조안을 다시 생성해 주세요.", code: "stale_story_plan" } }));
  render(<GeneratePanel project={project} deck={deck} chapterId="c1" onReplace={() => {}} />);
  await userEvent.click(screen.getByText("이 장 다시 생성"));
  expect(await screen.findByRole("region", { name: "보고 계획 복구 안내" })).toBeInTheDocument();
});

it("축약은 현재 슬롯을 동봉해 호출한다", async () => {
  answer(okResult, "condense");
  render(<GeneratePanel project={project} deck={deck} chapterId="c1" onReplace={() => {}} />);
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
  render(<GeneratePanel project={project} deck={deck} chapterId="c1" onReplace={() => {}} />);
  await userEvent.click(screen.getByText("이 장 다시 생성"));
  expect(await screen.findByText(/형식에 맞게 읽지 못했습니다/)).toBeInTheDocument();
  expect(screen.getByText("이상한 원문")).toBeInTheDocument();
  expect(screen.queryByText("반영")).not.toBeInTheDocument();
});

it("장을 전환하면 이전 장의 결과 패널이 사라진다", async () => {
  answer(okResult);
  const { rerender } = render(
    <GeneratePanel project={project} deck={deck} chapterId="c1" onReplace={() => {}} />);
  await userEvent.click(screen.getByText("이 장 다시 생성"));
  expect(await screen.findByText("반영")).toBeInTheDocument();
  rerender(<GeneratePanel project={project} deck={deck} chapterId="c2" onReplace={() => {}} />);
  expect(screen.queryByText("반영")).not.toBeInTheDocument();
});

// AI 전송 고지 취소 (계획서 B3): 취소는 실패가 아니므로 role=alert가 아닌 안내 문구로 보인다
it("재생성에서 AI 전송을 취소하면 알림이 아닌 안내 문구를 보인다", async () => {
  vi.mocked(api.prepareAi).mockRejectedValue(new AiConsentDeclined());
  render(<GeneratePanel project={project} deck={deck} chapterId="c1" onReplace={() => {}} />);
  await userEvent.click(screen.getByText("이 장 다시 생성"));
  const notice = await screen.findByText("전송을 취소했습니다. 필요하면 다시 시도해 주세요.");
  expect(notice.closest('[role="alert"]')).toBeNull();
  expect(screen.queryByRole("alert")).toBeNull();
});

it("축약에서 AI 전송을 취소해도 알림이 아닌 안내 문구를 보인다", async () => {
  vi.mocked(api.prepareAi).mockRejectedValue(new AiConsentDeclined());
  render(<GeneratePanel project={project} deck={deck} chapterId="c1" onReplace={() => {}} />);
  await userEvent.click(screen.getByText("이 장 축약"));
  const notice = await screen.findByText("전송을 취소했습니다. 필요하면 다시 시도해 주세요.");
  expect(notice.closest('[role="alert"]')).toBeNull();
});

// 태스크 C4: 결과 안내(축약, 재시도 문구) 옆에 사용량 한 줄을 보인다
it("재생성 결과 안내 옆에 사용량 한 줄을 보인다", async () => {
  // F8 리뷰 반영: 제목이 실제로 검증하지 않는 "값이 없으면 미확인" 주장을 포함하고 있었다.
  // 그 케이스는 바로 다음 테스트가 담당하므로 제목을 실제 검증 내용에 맞춘다.
  answer({ ...okResult, usage: measuredUsage() });
  render(<GeneratePanel project={project} deck={deck} chapterId="c1" onReplace={() => {}} />);
  await userEvent.click(screen.getByText("이 장 다시 생성"));
  expect(await screen.findByText(/AI 사용량: 호출 1회/)).toBeInTheDocument();
  expect(screen.getByText(/입력 100 토큰/)).toBeInTheDocument();
});

it("사용량 값이 없으면 미확인이 보인다", async () => {
  answer(okResult);  // okResult.usage는 emptyUsage()
  render(<GeneratePanel project={project} deck={deck} chapterId="c1" onReplace={() => {}} />);
  await userEvent.click(screen.getByText("이 장 다시 생성"));
  expect(await screen.findByText(/토큰 미확인/)).toBeInTheDocument();
  expect(screen.getByText(/비용 미확인/)).toBeInTheDocument();
});

// F5 리뷰 반영: usage는 상태와 무관하게 항상 채워지는 필수 필드다(C2/C3 가정 6). 형식 오류로
// 끝나도 최소 1회 호출은 있었으므로 그 사용량을 화면에서 감추면 안 된다.
it("형식 오류에도 사용량 한 줄이 보인다", async () => {
  answer({
    status: "format_error", slots: null, usage: measuredUsage(), raw_text: "이상한 원문",
    warnings: [], unverified_numbers: [], format_retried: true, condensed: false,
  });
  render(<GeneratePanel project={project} deck={deck} chapterId="c1" onReplace={() => {}} />);
  await userEvent.click(screen.getByText("이 장 다시 생성"));
  expect(await screen.findByText(/형식에 맞게 읽지 못했습니다/)).toBeInTheDocument();
  expect(screen.getByText(/AI 사용량: 호출 1회/)).toBeInTheDocument();
});

it("지시사항 입력이 .field 안에 있고 버튼은 .actions 행에 있다", () => {
  render(<GeneratePanel project={project} deck={deck} chapterId="c1" onReplace={() => {}} />);
  expect(screen.getByLabelText("재생성 지시사항").closest(".field")).not.toBeNull();
  expect(screen.getByText("이 장 다시 생성").closest(".actions")).not.toBeNull();
});

// -- D2b-5b 리뷰 반영 ------------------------------------------------------------------------

it("후보가 보이는 채로 다시 생성하면 등록 뒤 앞 후보를 버림으로 처분한다 (리뷰 R2)", async () => {
  vi.mocked(api.listJobs).mockResolvedValue([jobView("chapter", { id: "job-a", target: "c1",
    result: okResult as unknown as Record<string, unknown> })]);
  answer(okResult, "chapter", { id: "job-b" });
  render(<GeneratePanel project={project} deck={deck} chapterId="c1" onReplace={() => {}} />);
  await screen.findByText("이전에 만든 결과가 있습니다.");
  await userEvent.click(screen.getByText("이 장 다시 생성"));
  await waitFor(() => expect(api.settleCandidate).toHaveBeenCalledWith("p1", "job-a", "dismissed"));
});

it("동의를 거절하면 보이던 후보를 버리지 않는다 (리뷰 R2)", async () => {
  vi.mocked(api.listJobs).mockResolvedValue([jobView("chapter", { id: "job-a", target: "c1",
    result: okResult as unknown as Record<string, unknown> })]);
  vi.mocked(api.prepareAi).mockRejectedValue(new AiConsentDeclined());
  render(<GeneratePanel project={project} deck={deck} chapterId="c1" onReplace={() => {}} />);
  await screen.findByText("이전에 만든 결과가 있습니다.");
  await userEvent.click(screen.getByText("이 장 다시 생성"));
  await screen.findByText("전송을 취소했습니다. 필요하면 다시 시도해 주세요.");
  expect(api.settleCandidate).not.toHaveBeenCalled();
});

it("서버가 키 순서와 기본값을 바꿔 저장한 축약 요청도 지금 슬롯과 같으면 반영할 수 있다 (리뷰 R3)", async () => {
  const sent = deck.slides[0].slots as { bullets: unknown[]; conclusion: string };
  answer(okResult, "condense", { target: "c1", params: { chapter_id: "c1", instructions: "",
    slots: { footnote: "", conclusion: sent.conclusion, bullets: sent.bullets, template: "bullet_box" } } });
  render(<GeneratePanel project={project} deck={deck} chapterId="c1" onReplace={() => {}} />);
  await userEvent.click(screen.getByText("이 장 축약"));
  expect(await screen.findByText("반영")).toBeInTheDocument();
});

it("서버가 낡은 후보로 기록한 결과는 반영 대신 다시 생성을 보인다 (리뷰 R10)", async () => {
  vi.mocked(api.listJobs).mockResolvedValue([jobView("chapter", { target: "c1", candidate_status: "stale",
    result: okResult as unknown as Record<string, unknown> })]);
  render(<GeneratePanel project={project} deck={deck} chapterId="c1" onReplace={() => {}} />);
  expect(await screen.findByText(/만드는 동안 입력이 바뀌었던 후보입니다/)).toBeInTheDocument();
  expect(screen.queryByText("반영")).toBeNull();
});

it("조회가 실패하면 확인하지 못했다고 알리고 계속 조회한다", async () => {
  vi.mocked(api.startJob).mockResolvedValue(jobView("chapter", { target: "c1", state: "running", candidate_status: "none" }));
  vi.mocked(api.getJob).mockRejectedValueOnce(new ApiError(503, "연결 오류"))
    .mockResolvedValueOnce(jobView("chapter", { target: "c1", result: okResult as unknown as Record<string, unknown> }));
  render(<GeneratePanel project={project} deck={deck} chapterId="c1" onReplace={() => {}} pollIntervalMs={30} />);
  await userEvent.click(screen.getByText("이 장 다시 생성"));
  expect(await screen.findByText("작업 상태를 확인하지 못했습니다. 계속 확인합니다.")).toBeInTheDocument();
  expect(await screen.findByText("반영")).toBeInTheDocument();
  expect(screen.queryByText("작업 상태를 확인하지 못했습니다. 계속 확인합니다.")).toBeNull();
});

it("앞 작업의 취소 안내가 다음 작업의 취소 버튼을 가리지 않는다 (리뷰 R13)", async () => {
  const active = (id: string) => new ApiError(409, "다른 AI 생성이 진행 중입니다.", "generation_active",
    { id, project: "다른보고", kind: "diagram", target: null, stage: "running", created_at: "", cancel_requested: false });
  vi.mocked(api.startJob).mockRejectedValueOnce(active("job-9")).mockRejectedValueOnce(new ApiError(503, "다른 오류"))
    .mockRejectedValueOnce(active("job-10"));
  vi.mocked(api.cancelJob).mockResolvedValue(jobView("diagram"));
  render(<GeneratePanel project={project} deck={deck} chapterId="c1" onReplace={() => {}} />);
  await userEvent.click(screen.getByText("이 장 다시 생성"));
  await userEvent.click(await screen.findByText("그 작업 취소"));
  await userEvent.click(screen.getByText("이 장 다시 생성"));
  await screen.findByText("다른 오류");
  await userEvent.click(screen.getByText("이 장 다시 생성"));
  await userEvent.click(await screen.findByText("그 작업 취소"));
  expect(api.cancelJob).toHaveBeenLastCalledWith("다른보고", "job-10");
});
