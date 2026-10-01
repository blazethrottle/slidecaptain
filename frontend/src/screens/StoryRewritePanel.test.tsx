import { useState } from "react";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api, ApiError, AiConsentDeclined, type Deck, type StoryRewriteResult } from "../api/client";
import { storyDeck } from "../test/story";
import { emptyUsage } from "../test/usage";
import { StructureScreen } from "./StructureScreen";
vi.mock("../api/client", async (original) => {
  const mod = await original<typeof import("../api/client")>();
  return { ...mod, api: { ...mod.api, rewriteStory: vi.fn(), applyStoryRewrite: vi.fn(), putDeck: vi.fn(), generateChapter: vi.fn() } };
});
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
  vi.mocked(api.rewriteStory).mockResolvedValue(candidate());
  vi.mocked(api.applyStoryRewrite).mockResolvedValue(candidate().deck!);
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
  expect(api.generateChapter).not.toHaveBeenCalled();
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
  vi.mocked(api.rewriteStory).mockReturnValue(new Promise(r=>{resolve=r;}));
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
  vi.mocked(api.rewriteStory).mockResolvedValue({...candidate(),status:"format_error",deck:null,raw_text:"합성 오류"});
  render(<Harness/>); await userEvent.click(screen.getByRole("button",{name:"재작성 미리보기"}));
  expect(await screen.findByRole("alert")).toHaveTextContent("형식");
  expect(screen.getByText("합성 오류")).toBeInTheDocument();
  expect(screen.queryByRole("button",{name:"이 계획 적용"})).not.toBeInTheDocument();
});
it("동의 취소는 실패로 표시하지 않는다",async()=>{
  vi.mocked(api.rewriteStory).mockRejectedValue(new AiConsentDeclined());
  render(<Harness/>); await userEvent.click(screen.getByRole("button",{name:"재작성 미리보기"}));
  expect(await screen.findByText(/재작성을 취소했습니다/)).toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

it("기존 장 생성 중 저장본이 바뀌어도 재작성 패널이 부모 잠금을 해제하지 않는다", async () => {
  let finish!: (result: Awaited<ReturnType<typeof api.generateChapter>>) => void;
  vi.mocked(api.putDeck).mockResolvedValue({ok:true});
  vi.mocked(api.generateChapter).mockReturnValue(new Promise(r=>{finish=r;}));
  const busy=vi.fn(); render(<Harness onBusy={busy}/>);
  await userEvent.click(screen.getByRole("button", {name:"승인하고 내용 생성"}));
  await waitFor(()=>expect(api.generateChapter).toHaveBeenCalled());
  expect(busy).toHaveBeenLastCalledWith(true);
  await act(async()=>finish({status:"format_error",raw_text:"",usage:emptyUsage(),warnings:[],unverified_numbers:[],format_retried:false,condensed:false}));
});
