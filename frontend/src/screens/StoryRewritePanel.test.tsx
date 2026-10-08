import { useState } from "react";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api, ApiError, AiConsentDeclined, type Deck, type StoryRewriteResult } from "../api/client";
import { batchView, chapterView, jobView } from "../test/jobs";
import { storyDeck } from "../test/story";
import { emptyUsage } from "../test/usage";
import { StructureScreen } from "./StructureScreen";
vi.mock("../api/client", async (original) => {
  const mod = await original<typeof import("../api/client")>();
  return { ...mod, savedEtag: () => '"old"', api: { ...mod.api, applyStoryRewrite: vi.fn(), putDeck: vi.fn(), prepareAi: vi.fn(),
    startChapters: vi.fn(), getJob: vi.fn(), getDeck: vi.fn(), listJobs: vi.fn(), startJob: vi.fn(),
    settleCandidate: vi.fn(), cancelJob: vi.fn() } };
});

// D2b-5b: 재작성과 수리는 작업 API로 등록한다. 시험은 등록 기본 함수가 이 가짜 생성을 거쳐 끝난 작업을 돌려주게 한다
const rewriteStory = vi.fn<(name: string, params: unknown) => Promise<StoryRewriteResult>>();
function bridgeJobs() {
  vi.mocked(api.settleCandidate).mockResolvedValue(jobView("rewrite"));
  vi.mocked(api.startJob).mockImplementation(async (name, body) => {
    const result = await rewriteStory(name, body.params);
    return jobView(body.kind, { project: name, result: result as unknown as Record<string, unknown>,
      state: result.status === "ok" ? "succeeded" : "failed", candidate_status: result.status === "ok" ? "held" : "none" });
  });
}
const project = { name: "synthetic", title: "합성", updated_at: "", status: "ok" as const };
function candidate(): StoryRewriteResult {
  const deck = storyDeck();
  deck.structure.story_plan!.brief.decision_question = "새 질문";
  deck.structure.story_plan!.rewrite_review = { source_plan_fingerprint: "a".repeat(64), preserved_chapter_ids: ["c1"] };
  return { status: "ok", deck, base_etag: '"old"', sources_fingerprint: "b".repeat(64), raw_text: "", unverified_numbers: [], format_retried: false, usage: emptyUsage() };
}
function Harness({ onConflict = vi.fn(), onBusy = vi.fn(), onReady = vi.fn(), onDirty = vi.fn() } = {}) {
  const [deck, setDeck] = useState<Deck>(storyDeck());
  return <StructureScreen project={project} deck={deck} onDeckChange={setDeck} onDone={vi.fn()} onConflict={onConflict}
    onBusyChange={onBusy} onScreenReady={onReady} onDirtyChange={onDirty} />;
}
beforeEach(() => {
  bridgeJobs();
  rewriteStory.mockReset().mockResolvedValue(candidate());
  vi.mocked(api.applyStoryRewrite).mockResolvedValue(candidate().deck!);
  vi.mocked(api.prepareAi).mockResolvedValue({ "X-AI-Consent": "SlideCaptain" });
  vi.mocked(api.listJobs).mockResolvedValue([]);
});
async function showCandidate() {
  await userEvent.click(screen.getByRole("button", { name: "재작성 미리보기" }));
  return screen.findByRole("region", { name: "재작성 후보" });
}
async function applyCandidate() {
  await userEvent.click(screen.getByLabelText("본문 재검토가 필요함을 확인했습니다"));
  await userEvent.click(screen.getByRole("button", { name: "이 계획 적용" }));
}
it("명시적으로 적용할 때만 저장하며 기존 본문을 생성하지 않는다", async () => {
  render(<Harness />);
  expect(await showCandidate()).toHaveTextContent("새 질문");
  expect(api.applyStoryRewrite).not.toHaveBeenCalled();
  expect(api.putDeck).not.toHaveBeenCalled();
  await applyCandidate();
  await waitFor(() => expect(api.applyStoryRewrite).toHaveBeenCalledWith("synthetic", candidate()));
  expect(api.startChapters).not.toHaveBeenCalled();
  expect(screen.queryByRole("region", { name: "재작성 후보" })).not.toBeInTheDocument();
  expect(screen.getByLabelText("보고 질문")).toHaveValue("새 질문");
  expect(screen.getByText(/기존 본문을 보존한 재작성/)).toBeInTheDocument();
});
it("입력 변경은 후보를 무효화한다", async () => {
  render(<Harness />); await showCandidate();
  await userEvent.type(screen.getByLabelText("재작성 보고 질문"), " 수정");
  expect(screen.queryByRole("button", { name: "이 계획 적용" })).not.toBeInTheDocument();
});
it.each([409, 412, 503])("적용 실패 %s는 후보를 보존하고 충돌만 부모에 전달한다", async status => {
  vi.mocked(api.applyStoryRewrite).mockRejectedValue(new ApiError(status, "다시 확인"));
  const conflict = vi.fn(); render(<Harness onConflict={conflict} />);
  await showCandidate(); await applyCandidate();
  expect(await screen.findByRole("alert")).toHaveTextContent("다시 확인");
  expect(screen.getByRole("region", { name: "재작성 후보" })).toBeInTheDocument();
  expect(conflict).toHaveBeenCalledTimes(status === 412 ? 1 : 0);
  if (status !== 503) expect(screen.getByRole("button", { name: "이 계획 적용" })).toBeDisabled();
});
it("후보가 있으면 이탈 취소와 새로고침 경고를 연결한다", async () => {
  const ready=vi.fn(), dirty=vi.fn(); vi.spyOn(window,"confirm").mockReturnValue(false);
  render(<Harness onReady={ready} onDirty={dirty} />); await showCandidate();
  expect(dirty).toHaveBeenLastCalledWith(true);
  expect(await ready.mock.calls.at(-1)![0]()).toBe(false);
  expect(screen.getByRole("region", { name: "재작성 후보" })).toBeInTheDocument();
});
it("생성 중 기존 편집과 승인을 잠근다", async () => {
  let resolve!: (r: StoryRewriteResult)=>void;
  rewriteStory.mockReturnValue(new Promise(r=>{resolve=r;}));
  const busy=vi.fn(); render(<Harness onBusy={busy}/>);
  await userEvent.click(screen.getByRole("button",{name:"재작성 미리보기"}));
  expect(busy).toHaveBeenLastCalledWith(true);
  expect(screen.getByRole("button",{name:"승인하고 내용 생성"})).toBeDisabled();
  expect(screen.getByLabelText("1번 장 주제")).toBeDisabled();
  await act(async()=>resolve(candidate())); expect(busy).toHaveBeenLastCalledWith(false);
});
it("미승인 장 구성 변경은 재작성을 차단한다", async () => {
  render(<Harness/>); await userEvent.type(screen.getByLabelText("1번 장 주제")," 편집");
  expect(screen.getByRole("button",{name:"재작성 미리보기"})).toBeDisabled();
});
it("형식 오류의 원문을 표시하고 적용하지 않는다",async()=>{
  rewriteStory.mockResolvedValue({...candidate(),status:"format_error",deck:null,raw_text:"합성 오류"});
  render(<Harness/>); await userEvent.click(screen.getByRole("button",{name:"재작성 미리보기"}));
  expect(await screen.findByRole("alert")).toHaveTextContent("형식");
  expect(screen.getByText("합성 오류")).toBeInTheDocument();
  expect(screen.queryByRole("button",{name:"이 계획 적용"})).not.toBeInTheDocument();
});
it("동의 취소는 실패로 표시하지 않는다",async()=>{
  rewriteStory.mockRejectedValue(new AiConsentDeclined());
  render(<Harness/>); await userEvent.click(screen.getByRole("button",{name:"재작성 미리보기"}));
  expect(await screen.findByText(/재작성을 취소했습니다/)).toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

it("기존 장 생성 중 저장본이 바뀌어도 재작성 패널이 부모 잠금을 해제하지 않는다", async () => {
  // 장 생성 묶음이 끝나기 전까지 조회 응답을 붙잡아 둔다
  let finish!: (view: ReturnType<typeof batchView>) => void;
  vi.mocked(api.putDeck).mockResolvedValue({ok:true});
  vi.mocked(api.startChapters).mockResolvedValue(batchView([chapterView("c1", "running")],
    { project: project.name, state: "running", outcome: null }));
  vi.mocked(api.getJob).mockReturnValue(new Promise(r=>{finish=r;}));
  vi.mocked(api.getDeck).mockResolvedValue(storyDeck());
  const busy=vi.fn(); render(<Harness onBusy={busy}/>);
  await userEvent.click(screen.getByRole("button", {name:"승인하고 내용 생성"}));
  await waitFor(()=>expect(api.getJob).toHaveBeenCalled());
  expect(busy).toHaveBeenLastCalledWith(true);
  await act(async()=>finish(batchView([chapterView("c1", "failed")], { project: project.name, state: "failed", outcome: "partial" })));
  await waitFor(()=>expect(busy).toHaveBeenLastCalledWith(false));
});

// -- D2b-5b: 작업 연결과 후보 처분 ------------------------------------------------------------------

it("적용한 후보는 반영으로, 재작성 취소는 버림으로 처분한다", async () => {
  render(<Harness />);
  await showCandidate();
  await applyCandidate();
  await waitFor(() => expect(api.settleCandidate).toHaveBeenCalledWith("synthetic", "job-1", "applied"));
});

it("재작성 후보가 이전 입력 기준이면 적용 대신 다시 생성을 보이고 적용 라우트를 부르지 않는다", async () => {
  vi.mocked(api.startJob).mockResolvedValueOnce(jobView("rewrite", { project: "synthetic", candidate_status: "stale",
    stale_reasons: ["sources_changed"], result: candidate() as unknown as Record<string, unknown> }));
  render(<Harness />);
  const region = await showCandidate();
  expect(region).toHaveTextContent("이전 입력 기준 후보입니다(자료가 바뀌었습니다)");
  expect(screen.queryByRole("button", { name: "이 계획 적용" })).toBeNull();
  await userEvent.click(screen.getByRole("button", { name: "현재 입력으로 다시 생성" }));
  await waitFor(() => expect(api.startJob).toHaveBeenCalledTimes(2));
  expect(api.applyStoryRewrite).not.toHaveBeenCalled();
});

it("다시 열면 처분하지 않은 재작성 후보를 보인다", async () => {
  vi.mocked(api.listJobs).mockResolvedValue([jobView("rewrite", { project: "synthetic",
    params: { brief: { decision_question: "새 질문" }, instructions: "" },
    result: candidate() as unknown as Record<string, unknown> })]);
  render(<Harness />);
  const region = await screen.findByRole("region", { name: "재작성 후보" });
  expect(region).toHaveTextContent("이전에 만든 결과가 있습니다.");
  expect(screen.getByLabelText("재작성 보고 질문")).toHaveValue("새 질문");
  expect(api.startJob).not.toHaveBeenCalled();
});

async function startRepair() {
  await userEvent.click(screen.getByText("문제 목록으로 제한된 수정·재검수"));
  await userEvent.type(screen.getByLabelText("수정 문제 목록"), "근거가 약하다");
  await userEvent.click(screen.getByLabelText(/상한을 확인했습니다/));
  await userEvent.click(screen.getByRole("button", { name: "제한된 수정 미리보기" }));
}

it("수리 실행 중단은 취소를 요청하고, 작업이 취소로 끝난 뒤에만 취소 완료를 알린다 (지금은 즉시 알린다)", async () => {
  vi.mocked(api.startJob).mockResolvedValueOnce(jobView("repair", { id: "job-r", project: "synthetic",
    state: "running", candidate_status: "none" }));
  let finish!: (view: ReturnType<typeof jobView>) => void;
  vi.mocked(api.getJob).mockReturnValueOnce(new Promise((r) => { finish = r; }));
  vi.mocked(api.cancelJob).mockResolvedValue(jobView("repair", { state: "cancel_requested" }));
  render(<Harness />);
  await startRepair();
  await userEvent.click(await screen.findByRole("button", { name: "실행 중단" }));
  expect(api.cancelJob).toHaveBeenCalledWith("synthetic", "job-r");
  expect(await screen.findByText("취소를 요청했습니다. AI가 응답을 멈추면 취소됨으로 바뀝니다.")).toBeInTheDocument();
  expect(screen.queryByText(/수정 요청을 취소했습니다/)).toBeNull();
  await act(async () => finish(jobView("repair", { id: "job-r", state: "cancelled", candidate_status: "held" })));
  expect(await screen.findByText("수정 요청을 취소했습니다. 입력과 기존 저장본은 유지됩니다.")).toBeInTheDocument();
});

it("패널을 닫으면 조회만 멈추고 작업은 취소하지 않는다", async () => {
  vi.mocked(api.startJob).mockResolvedValueOnce(jobView("repair", { id: "job-r", project: "synthetic",
    state: "running", candidate_status: "none" }));
  vi.mocked(api.getJob).mockReturnValue(new Promise(() => {}));
  const view = render(<Harness />);
  await startRepair();
  await screen.findByRole("button", { name: "실행 중단" });
  view.unmount();
  expect(api.cancelJob).not.toHaveBeenCalled();
});

// -- D2b-5b 리뷰 반영 ------------------------------------------------------------------------

it("재작성 취소와 입력 변경은 보이던 후보를 버림으로 처분한다 (리뷰 R20)", async () => {
  vi.spyOn(window, "confirm").mockReturnValue(true);
  render(<Harness />);
  await showCandidate();
  await userEvent.click(screen.getByRole("button", { name: "재작성 취소" }));
  expect(api.settleCandidate).toHaveBeenCalledWith("synthetic", "job-1", "dismissed");
  vi.mocked(api.settleCandidate).mockClear();
  await showCandidate();
  await userEvent.type(screen.getByLabelText("재작성 지시사항"), "가");
  expect(api.settleCandidate).toHaveBeenCalledWith("synthetic", "job-1", "dismissed");
});

it("방금 적용한 후보는 처분 응답이 늦어도 다시 보이지 않고 충돌로 알리지 않는다 (리뷰 R4)", async () => {
  vi.mocked(api.settleCandidate).mockReturnValue(new Promise(() => {}));  // 처분 응답이 오지 않는다
  const conflict = vi.fn();
  render(<Harness onConflict={conflict} />);
  await showCandidate();
  vi.mocked(api.listJobs).mockResolvedValue([jobView("rewrite", { project: "synthetic", stale_reasons: ["deck_changed"],
    result: candidate() as unknown as Record<string, unknown> })]);
  const before = vi.mocked(api.listJobs).mock.calls.length;
  await applyCandidate();
  await waitFor(() => expect(vi.mocked(api.listJobs).mock.calls.length).toBeGreaterThan(before));  // 적용 뒤 다시 찾았다
  expect(screen.queryByRole("region", { name: "재작성 후보" })).toBeNull();
  expect(conflict).not.toHaveBeenCalled();
});

it("다시 연 낡은 후보는 충돌 배너 없이 안내만 하고, 수리 후보는 재작성으로 바꿔 보내지 않는다 (리뷰 R6, R7)", async () => {
  vi.mocked(api.listJobs).mockResolvedValue([jobView("repair", { project: "synthetic", candidate_status: "held",
    stale_reasons: ["deck_changed"], params: { brief: { decision_question: "새 질문" }, instructions: "원래 지시" },
    result: { ...candidate(), status: "reviewed_candidate", submission_approved: false, calls: 2, review_calls: 1, rounds: 1,
      findings: [], review_notes: [], notice: "수리 결과", reason: null } as unknown as Record<string, unknown> })]);
  const conflict = vi.fn();
  render(<Harness onConflict={conflict} />);
  expect(await screen.findByText(/문제 목록과 상한을 확인한 뒤 제한된 수정 미리보기를 다시 눌러 주세요/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "현재 입력으로 다시 생성" })).toBeNull();
  expect(screen.getByLabelText("재작성 지시사항")).toHaveValue("원래 지시");  // 리뷰 R19
  expect(conflict).not.toHaveBeenCalled();
});

it("취소 응답보다 결과가 먼저 끝났으면 취소 예고 문구를 붙이지 않는다 (리뷰 R18)", async () => {
  vi.mocked(api.startJob).mockResolvedValueOnce(jobView("repair", { id: "job-r", project: "synthetic",
    state: "running", candidate_status: "none" }));
  vi.mocked(api.getJob).mockReturnValue(new Promise(() => {}));
  vi.mocked(api.cancelJob).mockResolvedValue(jobView("repair", { state: "succeeded" }));
  render(<Harness />);
  await startRepair();
  await userEvent.click(await screen.findByRole("button", { name: "실행 중단" }));
  await waitFor(() => expect(api.cancelJob).toHaveBeenCalled());
  expect(screen.queryByText("취소를 요청했습니다. AI가 응답을 멈추면 취소됨으로 바뀝니다.")).toBeNull();
});
