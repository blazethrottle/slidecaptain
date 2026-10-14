import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import fixture from "../../../backend/tests/fixtures/q3b-project.json";
import { api, ApiError, type Deck, type RenderPlan } from "../api/client";
import { DiagramAuthoringDialog } from "./DiagramAuthoringDialog";
import { createDiagramDraft, editDiagramDraft } from "./diagramDraft";

vi.mock("../api/client", async (original) => {
  const mod = await original<typeof import("../api/client")>();
  return { ...mod, api: { ...mod.api, measure: vi.fn(), putDeck: vi.fn(), reconcileDiagramStory: vi.fn() } };
});
const fresh = () => structuredClone(fixture.deck) as Deck;
const staleError = () => Object.assign(new ApiError(409, "자료를 확인한 뒤 구조안을 다시 생성해 주세요."),
  { code: "stale_story_plan" });
const reviewButton = () => screen.getByRole("button", { name: "입력과 배치 확인" });
const recovery = () => screen.queryByRole("region", { name: "보고 계획 복구 안내" });
function open(deck = fresh(), isNew = false) {
  const draft = isNew ? createDiagramDraft(deck) : editDiagramDraft(deck, "synthetic-flow");
  if (isNew) {
    draft.topic = "아직 적용하지 않은 도식";
    draft.storyRole = "evidence";
    draft.claimIds = ["claim"];
    draft.nodes.forEach((node, i) => { node.content = `제안 ${i + 1}`; });
    draft.edges[0].label = "확인 제안";
  }
  const onApply = vi.fn();
  const onCancel = vi.fn();
  const onConflict = vi.fn();
  render(<DiagramAuthoringDialog projectName="synthetic" deck={deck} initialDraft={draft}
    onApply={onApply} onCancel={onCancel} onConflict={onConflict} />);
  return { deck, draft, onApply, onCancel, onConflict };
}

it("낡은 계획의 도식 입력을 보존하고 지원되는 복구 방법을 안내한다", async () => {
  vi.mocked(api.reconcileDiagramStory).mockRejectedValue(staleError());
  const { deck, onApply, onCancel } = open();
  fireEvent.change(screen.getByLabelText("도식 제목"), { target: { value: "작성 중인 제목" } });
  fireEvent.change(screen.getByLabelText("항목 1 조건"), { target: { value: "확인할 조건\n보존할 조건" } });
  await userEvent.click(reviewButton());
  expect(await screen.findByRole("region", { name: "보고 계획 복구 안내" })).toHaveTextContent(/별도 프로젝트/);
  expect(recovery()).toHaveTextContent(/전체 구조안 다시 생성은 아직 지원하지 않습니다/);
  expect(recovery()).toHaveTextContent(/스냅샷.*자료/);
  expect(screen.queryByText("자료를 확인한 뒤 구조안을 다시 생성해 주세요.")).not.toBeInTheDocument();
  expect(screen.getByLabelText("도식 제목")).toHaveValue("작성 중인 제목");
  expect(screen.getByLabelText("항목 1 조건")).toHaveValue("확인할 조건\n보존할 조건");
  expect(screen.getByLabelText("보고 계획 주장 claim")).toBeChecked();
  expect(screen.getByLabelText("도식 장 보고 역할")).toHaveValue("answer");
  expect(screen.getByRole("button", { name: "도식 적용" })).toBeDisabled();
  expect(api.measure).not.toHaveBeenCalled();
  expect(api.putDeck).not.toHaveBeenCalled();
  expect(onApply).not.toHaveBeenCalled();
  expect(onCancel).not.toHaveBeenCalled();
  expect(deck).toEqual(fixture.deck);
  const title = screen.getByLabelText("도식 제목");
  await userEvent.type(title, " 이어서 수정");
  expect(title).toHaveValue("작성 중인 제목 이어서 수정");
  expect(title).toHaveFocus();
  expect(recovery()).toBeInTheDocument();
});

it.each([
  new ApiError(409, "AI 연결이 변경되었습니다."),
  new ApiError(412, "다른 창에서 저장했습니다."),
  Object.assign(new ApiError(422, "입력 오류"), { code: "stale_story_plan" }),
])("다른 충돌과 입력 오류를 낡은 계획으로 분류하지 않는다: %j", async (error) => {
  vi.mocked(api.reconcileDiagramStory).mockRejectedValue(error);
  const { onConflict } = open();
  await userEvent.click(reviewButton());
  const shownError = await screen.findByText(error.message);
  expect(shownError).toBeInTheDocument();
  expect(shownError.closest('[role="alert"]')).not.toBeNull();
  expect(recovery()).not.toBeInTheDocument();
  expect(onConflict).toHaveBeenCalledTimes(error.status === 412 ? 1 : 0);
});

it("원자료를 복원하고 같은 초안을 다시 확인하면 복구 안내를 해제하고 적용할 수 있다", async () => {
  vi.mocked(api.reconcileDiagramStory).mockRejectedValueOnce(staleError())
    .mockImplementationOnce(async (_name, req) => req.deck);
  vi.mocked(api.measure).mockResolvedValue(structuredClone(fixture.render_plan) as RenderPlan);
  const { onApply } = open();
  fireEvent.change(screen.getByLabelText("도식 제목"), { target: { value: "복구 뒤 적용할 제목" } });
  await userEvent.click(reviewButton());
  await screen.findByRole("region", { name: "보고 계획 복구 안내" });
  await userEvent.click(reviewButton());
  await waitFor(() => expect(screen.getByRole("button", { name: "도식 적용" })).toBeEnabled());
  expect(recovery()).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "도식 적용" }));
  expect(onApply.mock.calls[0][0].structure.chapters[1].topic).toBe("복구 뒤 적용할 제목");
  expect(api.measure).toHaveBeenCalledTimes(1);
});

it("아직 적용하지 않은 새 도식을 저장된 도식으로 세지 않는다", async () => {
  const deck = fresh();
  deck.structure.chapters = deck.structure.chapters.filter(ch => ch.template !== "diagram");
  deck.slides = deck.slides.filter(s => s.slots.template !== "diagram");
  vi.mocked(api.reconcileDiagramStory).mockRejectedValue(staleError());
  open(deck, true);
  await userEvent.click(reviewButton());
  expect(await screen.findByRole("region", { name: "보고 계획 복구 안내" })).toHaveTextContent(/구성 단계에서.*다시 생성/);
  expect(recovery()).not.toHaveTextContent(/전체 구조안 다시 생성은 아직 지원하지 않습니다/);
  expect(screen.getByLabelText("도식 제목")).toHaveValue("아직 적용하지 않은 도식");
});

it("입력 변경 뒤 늦게 도착한 과거 오류로 복구 안내를 다시 표시하지 않는다", async () => {
  let reject!: (reason: unknown) => void;
  vi.mocked(api.reconcileDiagramStory).mockReturnValue(new Promise((_resolve, r) => { reject = r; }));
  open();
  await userEvent.click(reviewButton());
  fireEvent.change(screen.getByLabelText("도식 제목"), { target: { value: "요청 뒤 수정" } });
  await act(async () => reject(staleError()));
  expect(recovery()).not.toBeInTheDocument();
  expect(screen.getByLabelText("도식 제목")).toHaveValue("요청 뒤 수정");
});

it.each([false, true])("보관용 텍스트를 제공하고 복사 실패를 성공으로 표시하지 않는다: 실패=%s", async (fails) => {
  const user = userEvent.setup();
  const copy = vi.spyOn(navigator.clipboard, "writeText");
  if (fails) copy.mockRejectedValue(new Error("clipboard denied"));
  else copy.mockResolvedValue(undefined);
  vi.mocked(api.reconcileDiagramStory).mockRejectedValue(staleError());
  open();
  fireEvent.change(screen.getByLabelText("도식 제목"), { target: { value: "보관할 제목" } });
  await user.click(reviewButton());
  await screen.findByRole("region", { name: "보고 계획 복구 안내" });
  await user.click(screen.getByText("작성 내용 보관"));
  const backup = screen.getByLabelText("보관용 작성 내용");
  expect(backup).toHaveAttribute("readonly");
  expect((backup as HTMLTextAreaElement).value).toContain("보관할 제목");
  expect((backup as HTMLTextAreaElement).value).toContain("요청 접수");
  expect((backup as HTMLTextAreaElement).value).toContain("합성 도식 자료.md");
  await user.click(screen.getByRole("button", { name: "작성 내용 복사" }));
  expect(copy).toHaveBeenCalledWith((backup as HTMLTextAreaElement).value);
  if (fails) {
    expect(await screen.findByText(/복사하지 못했습니다/)).toBeInTheDocument();
    expect(screen.queryByText("작성 내용을 복사했습니다.")).not.toBeInTheDocument();
  } else expect(await screen.findByText("작성 내용을 복사했습니다.")).toBeInTheDocument();
  expect(screen.getByLabelText("도식 제목")).toHaveValue("보관할 제목");
  expect(api.putDeck).not.toHaveBeenCalled();
});

it("복사 대기 중 입력을 바꾸면 현재 내용의 복사 성공으로 표시하지 않는다", async () => {
  const user = userEvent.setup();
  let resolve!: () => void;
  vi.spyOn(navigator.clipboard, "writeText").mockReturnValue(new Promise<void>(r => { resolve = r; }));
  vi.mocked(api.reconcileDiagramStory).mockRejectedValue(staleError());
  open();
  await user.click(reviewButton());
  await screen.findByRole("region", { name: "보고 계획 복구 안내" });
  await user.click(screen.getByText("작성 내용 보관"));
  await user.click(screen.getByRole("button", { name: "작성 내용 복사" }));
  fireEvent.change(screen.getByLabelText("도식 제목"), { target: { value: "복사 요청 뒤 수정" } });
  await act(async () => resolve());
  expect(screen.queryByText("작성 내용을 복사했습니다.")).not.toBeInTheDocument();
  expect(screen.getByLabelText("도식 제목")).toHaveValue("복사 요청 뒤 수정");
});
