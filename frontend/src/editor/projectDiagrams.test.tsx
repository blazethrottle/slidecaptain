import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import fixture from "../../../backend/tests/fixtures/q3b-project.json";
import { api, ApiError, type Deck, type Preset, type RenderPlan } from "../api/client";
import { PropertyPanel } from "./PropertyPanel";
import { GeneratePanel } from "./GeneratePanel";
import { applyTemplateSwitch, switchTemplate } from "./templateSwitch";
import { applyTextEdit, reorderChapters } from "./slotOps";
import { editorReducer } from "../state/deckStore";
import { StructureScreen } from "../screens/StructureScreen";
import { EditorScreen } from "../screens/EditorScreen";

vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return { ...mod, api: { ...mod.api, generateStructure: vi.fn(), generateChapter: vi.fn(),
    condenseChapter: vi.fn(), putDeck: vi.fn(), measure: vi.fn(), reviewNumbers: vi.fn(), getPreset: vi.fn() } };
});

const project = { name: "diagram", title: "합성 도식 보고", updated_at: "", status: "ok" as const };
const chapterId = "synthetic-flow";
const freshDeck = () => structuredClone(fixture.deck) as Deck;
beforeEach(() => { vi.mocked(api.getPreset).mockResolvedValue(fixture.preset as Preset); });

it("저장된 도식의 주제와 템플릿을 읽기 전용으로 보여 준다", () => {
  render(<PropertyPanel deck={freshDeck()} chapterId={chapterId} onApply={vi.fn()} />);
  expect(screen.getByText(/읽기 전용/)).toBeInTheDocument();
  expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  expect(screen.queryByText(/클릭해 직접 고칠/)).not.toBeInTheDocument();
});

it("도식에 AI 재생성이나 축약을 제공하지 않는다", () => {
  render(<GeneratePanel project={project} deck={freshDeck()} chapterId={chapterId} onReplace={vi.fn()} />);
  expect(screen.queryByRole("button", { name: "이 장 다시 생성" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "이 장 축약" })).not.toBeInTheDocument();
  expect(api.generateChapter).not.toHaveBeenCalled();
  expect(api.condenseChapter).not.toHaveBeenCalled();
});

it("일반 슬롯 편집이나 템플릿 전환으로 도식의 의미 입력을 버리지 않는다", () => {
  const deck = freshDeck();
  const slots = deck.slides[0].slots;
  expect(switchTemplate(slots, "bullet_box").slots).toBe(slots);
  expect(applyTemplateSwitch(deck, chapterId, "bullet_box").deck).toBe(deck);
  expect(applyTemplateSwitch(deck, "cover", "diagram").deck).toBe(deck);
  expect(applyTextEdit(deck, { chapterId, slot: "title", index: 0 }, "수정")).toBe(deck);
  expect(applyTextEdit(deck, { chapterId, slot: "subtitle", index: 0 }, "수정")).toBe(deck);
});

it("재정렬과 undo/redo에도 도식과 단일 근거 장부를 보존한다", () => {
  const deck = freshDeck();
  const next = reorderChapters(deck, 1, 0);
  const edited = editorReducer({ past: [], present: deck, future: [] }, { type: "edit", deck: next });
  const undone = editorReducer(edited, { type: "undo" });
  const redone = editorReducer(undone, { type: "redo" });
  expect(undone.present).toBe(deck);
  expect(redone.present).toBe(next);
  expect(next.slides).toEqual(deck.slides);
  expect(next.structure.story_plan).toEqual(deck.structure.story_plan);
});

it("구조안 재생성과 도식 수정은 막고 기존 도식을 유지해 승인 저장한다", async () => {
  vi.mocked(api.putDeck).mockResolvedValue({ ok: true });
  const onDone = vi.fn();
  const deck = freshDeck();
  render(<StructureScreen project={project} deck={deck} onDeckChange={vi.fn()} onDone={onDone} />);
  expect(screen.getByRole("button", { name: "다시 생성" })).toBeDisabled();
  expect(screen.getByLabelText("2번 장 템플릿")).toBeDisabled();
  expect(screen.getByLabelText("2번 장 템플릿")).toHaveValue("diagram");
  expect(screen.getByLabelText("2번 장 주제")).toHaveAttribute("readonly");
  expect(screen.getByRole("button", { name: "요청 처리 흐름 삭제" })).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: "승인하고 내용 생성" }));
  await waitFor(() => expect(onDone).toHaveBeenCalled());
  expect(api.putDeck).toHaveBeenCalledWith(project.name, deck, true);
  expect(api.generateStructure).not.toHaveBeenCalled();
  expect(api.generateChapter).not.toHaveBeenCalled();
});

it("구조안 화면은 도식 편집의 진입점과 재계획 제한의 복구 방법을 안내한다", async () => {
  render(<StructureScreen project={project} deck={freshDeck()} onDeckChange={vi.fn()} onDone={vi.fn()} />);
  expect(screen.getByText(/편집 탭에서.*도식 수정/)).toBeInTheDocument();
  expect(screen.queryByText(/도식은 읽기 전용이며/)).not.toBeInTheDocument();
  await userEvent.click(screen.getByText("자료나 보고 계획이 달라졌다면"));
  expect(screen.getByRole("region", { name: "보고 계획 복구 안내" })).toHaveTextContent(/별도 프로젝트/);
  expect(screen.getByRole("region", { name: "보고 계획 복구 안내" })).not.toHaveTextContent("현재 계획으로 작업을 계속할 수 없습니다");
  expect(screen.getByRole("button", { name: "다시 생성" })).toBeDisabled();
  expect(api.generateStructure).not.toHaveBeenCalled();
  expect(api.putDeck).not.toHaveBeenCalled();
});

it.each(["generate", "condense"])("일반 장의 %s도 낡은 계획을 도식 재계획으로 잘못 안내하지 않는다", async (operation) => {
  const stale = Object.assign(new ApiError(409, "구조안을 다시 생성해 주세요."), { code: "stale_story_plan" });
  vi.mocked(api.generateChapter).mockRejectedValue(stale);
  vi.mocked(api.condenseChapter).mockRejectedValue(stale);
  const deck = freshDeck();
  const onReplace = vi.fn();
  render(<GeneratePanel project={project} deck={deck} chapterId="cover" onReplace={onReplace} />);
  await userEvent.type(screen.getByLabelText("재생성 지시사항"), "유지할 지시");
  await userEvent.click(screen.getByRole("button", { name: operation === "generate" ? "이 장 다시 생성" : "이 장 축약" }));
  expect(await screen.findByRole("region", { name: "보고 계획 복구 안내" })).toHaveTextContent(/별도 프로젝트/);
  expect(screen.queryByText("구조안을 다시 생성해 주세요.")).not.toBeInTheDocument();
  expect(screen.getByLabelText("재생성 지시사항")).toHaveValue("유지할 지시");
  expect(onReplace).not.toHaveBeenCalled();
  expect(api.putDeck).not.toHaveBeenCalled();
  expect(deck).toEqual(fixture.deck);
});

it("구조안 승인 후 낡은 계획을 알게 되면 복구 안내를 하고 다음 장 호출을 멈춘다", async () => {
  const deck = freshDeck();
  deck.slides = deck.slides.filter(s => s.chapter_id !== "cover");
  deck.structure.chapters.push({ ...deck.structure.chapters[0], id: "another", topic: "다음 장" });
  vi.mocked(api.putDeck).mockResolvedValue({ ok: true });
  vi.mocked(api.generateChapter).mockRejectedValue(Object.assign(new ApiError(409, "구조안을 다시 생성해 주세요."),
    { code: "stale_story_plan" }));
  const onDone = vi.fn();
  render(<StructureScreen project={project} deck={deck} onDeckChange={vi.fn()} onDone={onDone} />);
  await userEvent.click(screen.getByRole("button", { name: "승인하고 내용 생성" }));
  expect(await screen.findByRole("region", { name: "보고 계획 복구 안내" })).toHaveTextContent(/별도 프로젝트/);
  expect(api.generateChapter).toHaveBeenCalledTimes(1);
  expect(onDone).not.toHaveBeenCalled();
});

it("프로젝트에서 도식 미리보기를 열고 다른 장을 저장해도 도식 입력을 보존한다", async () => {
  vi.mocked(api.putDeck).mockResolvedValue({ ok: true });
  vi.mocked(api.measure).mockResolvedValue(fixture.render_plan as RenderPlan);
  const onDeckChange = vi.fn();
  render(<EditorScreen project={project} deck={freshDeck()} onDeckChange={onDeckChange}
    timings={{ measureMs: 1, saveMs: 1 }} />);
  await screen.findByText("저장 상태: 저장됨");
  await waitFor(() => expect(api.measure).toHaveBeenCalled());
  // 장 목록은 주제 이름으로 접근할 수 있다.
  await userEvent.click(screen.getByRole("button", { name: /요청 처리 흐름/ }));
  expect(await screen.findByRole("group", { name: "도식 미리보기" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "이 장 다시 생성" })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /합성 보고/ }));
  const title = screen.getByLabelText("장 주제");
  await userEvent.clear(title);
  await userEvent.type(title, "수정 표지");
  await userEvent.tab();
  await waitFor(() => expect(api.putDeck).toHaveBeenCalled());
  const saved = vi.mocked(api.putDeck).mock.calls.at(-1)![1];
  expect(saved.slides[0]).toEqual(fixture.deck.slides[0]);
  expect(saved.structure.story_plan).toEqual(fixture.deck.structure.story_plan);
});

it("배치 실패를 내용 없음으로 오해하게 안내하지 않는다", async () => {
  vi.mocked(api.measure).mockRejectedValueOnce(new ApiError(422, "도식 페이지를 배치할 수 없습니다."));
  render(<EditorScreen project={project} deck={freshDeck()} onDeckChange={vi.fn()}
    timings={{ measureMs: 1, saveMs: 1 }} />);
  expect(await screen.findByRole("alert")).toHaveTextContent("도식 페이지를 배치할 수 없습니다.");
  expect(screen.queryByText(/이 장은 아직 내용이 없습니다/)).not.toBeInTheDocument();
  expect(screen.getByText(/미리보기를 만들지 못했습니다/)).toBeInTheDocument();
});
