import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api } from "../api/client";
import { emptyUsage } from "../test/usage";
import { comparisonDeck, derivedDeck, storyDeck } from "../test/story";
import { StructureScreen } from "./StructureScreen";

vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return { ...mod, api: { ...mod.api, generateStructure: vi.fn(), generateChapter: vi.fn(), putDeck: vi.fn() } };
});

const project = { name: "synthetic", title: "합성 보고", updated_at: "", status: "ok" as const };

function generated(structure = storyDeck().structure) {
  return { status: "ok" as const, structure, raw_text: "", unverified_numbers: [], format_retried: false, usage: emptyUsage() };
}

it.each([storyDeck, comparisonDeck, derivedDeck])("질문을 계획 요청으로 보내고 근거와 비교 계약을 승인 저장에 보존한다 (%#)", async (makeDeck) => {
  const deck = makeDeck();
  const empty = { ...deck, structure: { chapters: [] } };
  vi.mocked(api.generateStructure).mockResolvedValue(generated(deck.structure));
  vi.mocked(api.putDeck).mockResolvedValue({ ok: true });
  vi.mocked(api.generateChapter).mockResolvedValue({ status: "ok", usage: emptyUsage(), raw_text: "", warnings: [], unverified_numbers: [], format_retried: false, condensed: false,
    slots: { template: "summary", conclusion: "비용 확인 후 판단", points: [] } });
  const onDone = vi.fn();
  render(<StructureScreen project={project} deck={empty} onDeckChange={() => {}} onDone={onDone} />);
  await userEvent.type(screen.getByLabelText("보고 질문"), "운영을 확대할 것인가?");
  await userEvent.click(screen.getByRole("button", { name: "구조안 생성" }));
  expect(await screen.findByRole("region", { name: "보고 계획" })).toHaveTextContent("확대 비용은 얼마인가?");
  expect(screen.getByRole("region", { name: "보고 계획" })).toHaveTextContent("비용 확인 후 확대 여부를 판단한다");
  expect(screen.getByRole("region", { name: "보고 계획" })).toHaveTextContent("합성.md");
  if (deck.structure.story_plan!.comparisons.length > 0) {
    expect(screen.getByRole("region", { name: "지표 비교" })).toHaveTextContent("두 근거의 단위가 다릅니다.");
  }
  if (deck.structure.story_plan!.derivations.length > 0) {
    expect(screen.getByRole("region", { name: "수치 계산" })).toHaveTextContent("계산 불가");
  }
  expect(api.generateStructure).toHaveBeenCalledWith("synthetic", expect.objectContaining({ brief: deck.structure.story_plan!.brief }));
  await userEvent.click(screen.getByRole("button", { name: "승인하고 내용 생성" }));
  await waitFor(() => expect(onDone).toHaveBeenCalled());
  for (const [, saved] of vi.mocked(api.putDeck).mock.calls) {
    expect(saved.structure.story_plan).toEqual(deck.structure.story_plan);
  }
  expect(vi.mocked(api.putDeck).mock.calls.at(-1)![1].slides).toHaveLength(1);
});

it("다시 연 계획의 질문을 복원하고 수동 구조안 수정에도 계획을 보존한다", async () => {
  const deck = storyDeck();
  deck.slides = [{ chapter_id: "c1", eyebrow: "", subtitle: "", slots: { template: "summary", conclusion: "수동 내용", points: [] } }];
  vi.mocked(api.putDeck).mockResolvedValue({ ok: true });
  const onDone = vi.fn();
  render(<StructureScreen project={project} deck={deck} onDeckChange={() => {}} onDone={onDone} />);
  expect(screen.getByLabelText("보고 질문")).toHaveValue("운영을 확대할 것인가?");
  await userEvent.clear(screen.getByLabelText("1번 장 주제"));
  await userEvent.type(screen.getByLabelText("1번 장 주제"), "수동 수정");
  await userEvent.click(screen.getByRole("button", { name: "승인하고 내용 생성" }));
  await waitFor(() => expect(onDone).toHaveBeenCalled());
  const saved = vi.mocked(api.putDeck).mock.calls[0][1];
  expect(saved.structure.chapters[0].topic).toBe("수동 수정");
  expect(saved.structure.story_plan).toEqual(deck.structure.story_plan);
  expect(saved.slides).toEqual(deck.slides);
});

it("질문이 바뀌면 옛 계획을 승인하기 전에 재생성을 요구한다", async () => {
  render(<StructureScreen project={project} deck={storyDeck()} onDeckChange={() => {}} onDone={() => {}} />);
  await userEvent.type(screen.getByLabelText("보고 질문"), " 변경");
  expect(screen.getByRole("button", { name: "승인하고 내용 생성" })).toBeDisabled();
  expect(screen.getByText(/보고 질문이 바뀌었습니다/)).toBeInTheDocument();
});

it("질문을 비워 기존 방식으로 재생성하면 옛 계획을 새 구조안에 붙이지 않는다", async () => {
  const deck = storyDeck();
  vi.mocked(api.generateStructure).mockResolvedValue(generated({ chapters: deck.structure.chapters }));
  vi.mocked(api.putDeck).mockResolvedValue({ ok: true });
  vi.mocked(api.generateChapter).mockResolvedValue({ status: "format_error", usage: emptyUsage(), raw_text: "실패", warnings: [], unverified_numbers: [], format_retried: true, condensed: false });
  render(<StructureScreen project={project} deck={deck} onDeckChange={() => {}} onDone={() => {}} />);
  await userEvent.clear(screen.getByLabelText("보고 질문"));
  await userEvent.click(screen.getByRole("button", { name: "다시 생성" }));
  await waitFor(() => expect(screen.queryByRole("region", { name: "보고 계획" })).not.toBeInTheDocument());
  await userEvent.click(screen.getByRole("button", { name: "승인하고 내용 생성" }));
  await waitFor(() => expect(api.putDeck).toHaveBeenCalled());
  expect(vi.mocked(api.putDeck).mock.calls[0][1].structure.story_plan).toBeNull();
});
