// 속성 패널의 직접 수정 (α 리뷰 반영): 한도 재요청 조건, 잠긴 패널, 덱별 색 견본
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api, type Deck, type Preset, type SlidePlan } from "../api/client";
import { DirectEditPanel } from "./DirectEditPanel";
import { frameKeys } from "./directEdit";

vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return { ...mod, api: { ...mod.api, getPreset: vi.fn(), fontLimit: vi.fn() } };
});

const preset = { font_roles: { body_pt: 12, box_pt: 12 }, colors: { text: "202020", danger: "B42318", background: "FFFFFF" } } as unknown as Preset;
const deck = {
  meta: { title: "t", preset_overrides: {} },
  structure: { chapters: [{ id: "c1", topic: "주제", template: "bullet_box" }] },
  slides: [{ chapter_id: "c1", eyebrow: "", subtitle: "", slots: { template: "bullet_box", bullets: [{ text: "하나", level: 0 }], conclusion: "결론", footnote: "" } }],
} as unknown as Deck;
const para = (text: string) => ({ text, level: 0, font_pt: 12, bold: false, color: "202020", align: "left" as const, bullet: false, lines: [text] });
const plan = { chapter_id: "c1", template: "bullet_box", warnings: [], frames: [
  { name: "c1:conclusion", x: 50, y: 400, w: 860, h: 60, fill: "EEF3F9", border: null, valign: "top", table: null, paras: [para("결론")] },
] } as unknown as SlidePlan;

function panel(d: Deck, extra: Partial<Parameters<typeof DirectEditPanel>[0]> = {}) {
  return <DirectEditPanel projectName="p" deck={d} chapterId="c1" plan={plan} pageW={960} pageH={540}
    keys={frameKeys(d.slides[0])} selectedKey="conclusion" onApply={() => {}} onShowFrame={() => {}} onHide={() => {}}
    onPendingChange={() => {}} {...extra} />;
}

beforeEach(() => {
  vi.mocked(api.getPreset).mockResolvedValue(preset);
  vi.mocked(api.fontLimit).mockResolvedValue({ base_pt: 12, current_pt: 12, fits_up_to_pt: 20, min_pt: 1, max_pt: 1131 });
});

it("부분 강조가 바뀌면 최대 크기를 다시 묻고, 위치만 바뀌면 묻지 않는다 (α 리뷰 A4)", async () => {
  const { rerender } = render(panel(deck));
  await waitFor(() => expect(api.fontLimit).toHaveBeenCalledTimes(1), { timeout: 2000 });
  const moved = { ...deck, slides: [{ ...deck.slides[0], direct_edits: { conclusion: { dx_pt: 5, dy_pt: 0 } } }] } as Deck;
  rerender(panel(moved));
  await new Promise((r) => setTimeout(r, 400));
  expect(api.fontLimit).toHaveBeenCalledTimes(1);
  const span = { slot: "conclusion", start: 0, end: 2, role: "bold", text_sha256: "0".repeat(64) };
  rerender(panel({ ...moved, slides: [{ ...moved.slides[0], text_spans: [span] }] } as unknown as Deck));
  await waitFor(() => expect(api.fontLimit).toHaveBeenCalledTimes(2), { timeout: 2000 });
});

it("잠긴 패널에서는 다시 보이기를 막는다 (α 리뷰 A11)", () => {
  const hidden = { ...deck, slides: [{ ...deck.slides[0], direct_edits: { conclusion: { hidden: true } } }] } as Deck;
  render(panel(hidden, { locked: true }));
  expect(screen.getByRole("button", { name: "다시 보이기" })).toBeDisabled();
});

it("색 견본은 덱별 색 덮어쓰기를 따른다 (α 리뷰 A8의 F16)", async () => {
  const designed = { ...deck, meta: { ...deck.meta, preset_overrides: { colors: { danger: "123456" } } } } as Deck;
  render(panel(designed));
  const summary = await screen.findByText("색 견본 보기");
  await userEvent.click(summary);
  const item = within(summary.closest("details")!).getByText(/주의\(빨강 계열\)/).closest("li")!;
  expect(item.querySelector<HTMLElement>(".swatch")!.style.background).toBe("rgb(18, 52, 86)");
});
