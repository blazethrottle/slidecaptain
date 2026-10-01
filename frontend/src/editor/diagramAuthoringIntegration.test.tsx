import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import fixture from "../../../backend/tests/fixtures/q3b-project.json";
import { api, ApiError, type Deck, type Preset, type RenderPlan } from "../api/client";
import { EditorScreen } from "../screens/EditorScreen";

vi.mock("../api/client", async (original) => {
  const mod = await original<typeof import("../api/client")>();
  return { ...mod, api: { ...mod.api, measure: vi.fn(), putDeck: vi.fn(), getDeck: vi.fn(), reconcileDiagramStory: vi.fn(), getPreset: vi.fn(), reviewNumbers: vi.fn() } };
});
const project = { name: "authoring", title: "합성 작성", updated_at: "", status: "ok" as const };
const fresh = () => structuredClone(fixture.deck) as Deck;

beforeEach(() => {
  vi.mocked(api.putDeck).mockReset().mockResolvedValue({ ok: true });
  vi.mocked(api.reconcileDiagramStory).mockReset().mockImplementation(async (_name, req) => req.deck);
  vi.mocked(api.getPreset).mockResolvedValue(fixture.preset as Preset);
  vi.mocked(api.measure).mockReset().mockImplementation(async deck => {
    const plan = structuredClone(fixture.render_plan) as RenderPlan;
    plan.slides = deck.structure.chapters.map(chapter => ({
      ...plan.slides[chapter.template === "diagram" ? 1 : 0], chapter_id: chapter.id,
    }));
    return plan;
  });
});
function setup(deck = fresh()) {
  const onDeckChange = vi.fn();
  const onDirtyChange = vi.fn();
  let flush: (() => Promise<boolean>) | null = null;
  render(<EditorScreen project={project} deck={deck} onDeckChange={onDeckChange}
    onDirtyChange={onDirtyChange} onEditorReady={fn => { flush = fn; }} timings={{ measureMs: 1, saveMs: 1 }} />);
  return { onDeckChange, onDirtyChange, flush: () => flush!() };
}

it("작성 중에는 이탈 플러시를 막고 취소하면 덱을 그대로 둔다", async () => {
  const { flush, onDirtyChange, onDeckChange } = setup();
  await userEvent.click(screen.getByRole("button", { name: "도식 추가" }));
  fireEvent.change(screen.getByLabelText("도식 제목"), { target: { value: "미완성" } });
  expect(onDirtyChange).toHaveBeenLastCalledWith(true);
  let ready = true;
  await act(async () => { ready = await flush(); });
  expect(ready).toBe(false);
  expect(api.putDeck).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "변경 버리고 닫기" }));
  await act(async () => { ready = await flush(); });
  expect(ready).toBe(true);
  expect(onDirtyChange).toHaveBeenLastCalledWith(false);
  expect(onDeckChange).not.toHaveBeenCalled();
});

it("빈 덱에서도 제안 도식을 작성하고 적용/저장/undo/redo한다", async () => {
  const deck = { ...fresh(), structure: { chapters: [], story_plan: null }, slides: [] } as Deck;
  const { onDeckChange } = setup(deck);
  await userEvent.click(screen.getByRole("button", { name: "도식 추가" }));
  const dialog = within(screen.getByRole("dialog"));
  expect(dialog.getAllByText("등록된 근거가 없습니다.")).toHaveLength(3);
  fireEvent.change(dialog.getByLabelText("도식 제목"), { target: { value: "새 제안 흐름" } });
  fireEvent.change(dialog.getByLabelText("항목 1 내용"), { target: { value: "접수" } });
  fireEvent.change(dialog.getByLabelText("항목 2 내용"), { target: { value: "검토" } });
  fireEvent.change(dialog.getByLabelText("관계 1 설명"), { target: { value: "검토 제안" } });
  await userEvent.click(dialog.getByRole("button", { name: "입력과 배치 확인" }));
  await waitFor(() => expect(dialog.getByRole("button", { name: "도식 적용" })).toBeEnabled());
  expect(api.putDeck).not.toHaveBeenCalled();
  await userEvent.click(dialog.getByRole("button", { name: "도식 적용" }));
  await waitFor(() => expect(onDeckChange).toHaveBeenCalled());
  const saved = vi.mocked(api.putDeck).mock.calls.at(-1)![1];
  expect(saved.structure.chapters[0].template).toBe("diagram");
  expect(saved.structure.story_plan).toBeNull();
  expect(saved.slides[0].slots.template).toBe("diagram");
  expect(vi.mocked(api.putDeck).mock.calls.at(-1)![2]).toBe(true);
  expect(screen.getByRole("button", { name: /새 제안 흐름/ })).toHaveAttribute("aria-pressed", "true");
  await userEvent.click(screen.getByRole("button", { name: /되돌리기/ }));
  await waitFor(() => expect(vi.mocked(api.putDeck).mock.calls.at(-1)![1].slides).toHaveLength(0));
  await userEvent.click(screen.getByRole("button", { name: "다시 실행" }));
  await waitFor(() => expect(vi.mocked(api.putDeck).mock.calls.at(-1)![1]).toEqual(saved));
});

it("기존 도식의 제목/조건을 수정하고 다른 장과 근거 장부를 보존한다", async () => {
  setup();
  await userEvent.click(screen.getByRole("button", { name: /요청 처리 흐름/ }));
  await userEvent.click(screen.getByRole("button", { name: "도식 내용 수정" }));
  fireEvent.change(screen.getByLabelText("도식 제목"), { target: { value: "수정 흐름" } });
  fireEvent.change(screen.getByLabelText("항목 3 조건"), { target: { value: "비용 검토 필요\n일정 미확인" } });
  await userEvent.click(screen.getByRole("button", { name: "입력과 배치 확인" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "도식 적용" })).toBeEnabled());
  await userEvent.click(screen.getByRole("button", { name: "도식 적용" }));
  await waitFor(() => expect(api.putDeck).toHaveBeenCalled());
  const saved = vi.mocked(api.putDeck).mock.calls.at(-1)![1];
  expect(saved.structure.chapters).toHaveLength(2);
  expect(saved.structure.story_plan).toEqual(fixture.deck.structure.story_plan);
  expect(saved.slides[1]).toEqual(fixture.deck.slides[1]);
  expect(saved.slides[0].slots.template === "diagram" && saved.slides[0].slots.diagram.nodes[2].caveats)
    .toEqual(["비용 검토 필요", "일정 미확인"]);
});

it("작성 창의 키보드 undo가 기존 덱 undo를 실행하지 않는다", async () => {
  setup();
  fireEvent.change(screen.getByLabelText("장 주제"), { target: { value: "다른 표지" } });
  fireEvent.blur(screen.getByLabelText("장 주제"));
  await waitFor(() => expect(api.putDeck).toHaveBeenCalled());
  const before = vi.mocked(api.putDeck).mock.calls.length;
  await userEvent.click(screen.getByRole("button", { name: "도식 추가" }));
  fireEvent.keyDown(screen.getByRole("dialog"), { key: "z", ctrlKey: true });
  await userEvent.click(screen.getByRole("button", { name: "변경 버리고 닫기" }));
  expect(screen.getByLabelText("장 주제")).toHaveValue("다른 표지");
  expect(vi.mocked(api.putDeck).mock.calls).toHaveLength(before);
});

it("저장 충돌 때 새 작성 진입을 막고 현재 도식 내용을 보존한다", async () => {
  vi.mocked(api.putDeck).mockRejectedValue(new ApiError(412, "다른 창에서 저장했습니다."));
  setup();
  fireEvent.change(screen.getByLabelText("장 주제"), { target: { value: "다른 표지" } });
  fireEvent.blur(screen.getByLabelText("장 주제"));
  await screen.findByText(/다른 창에서 저장했습니다/);
  expect(screen.getByRole("button", { name: "도식 추가" })).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: /요청 처리 흐름/ }));
  expect(screen.getByRole("button", { name: "도식 내용 수정" })).toBeDisabled();
});

it("연결 확인의 412도 작성 입력을 보존하고 닫은 뒤 서버본 복구를 제공한다", async () => {
  const serverDeck = fresh();
  serverDeck.meta.presenter = "다른 창의 수정";
  vi.mocked(api.getDeck).mockResolvedValue(serverDeck);
  vi.mocked(api.reconcileDiagramStory).mockRejectedValue(new ApiError(412, "다른 창에서 먼저 저장했습니다."));
  const { onDeckChange } = setup();
  await userEvent.click(screen.getByRole("button", { name: /요청 처리 흐름/ }));
  await userEvent.click(screen.getByRole("button", { name: "도식 내용 수정" }));
  fireEvent.change(screen.getByLabelText("항목 1 내용"), { target: { value: "보존할 작성 내용" } });
  await userEvent.click(screen.getByRole("button", { name: "입력과 배치 확인" }));
  await within(screen.getByRole("dialog")).findByText(/다른 창에서 먼저 저장했습니다/);
  expect(screen.getByLabelText("항목 1 내용")).toHaveValue("보존할 작성 내용");
  expect(screen.getByRole("button", { name: "도식 적용" })).toBeDisabled();
  expect(api.putDeck).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "변경 버리고 닫기" }));
  expect(screen.getByRole("button", { name: "도식 추가" })).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: "서버 내용으로 되돌리기" }));
  await waitFor(() => expect(onDeckChange).toHaveBeenLastCalledWith(serverDeck));
  expect(screen.getByRole("button", { name: "도식 추가" })).toBeEnabled();
  expect(api.putDeck).not.toHaveBeenCalled();
});
