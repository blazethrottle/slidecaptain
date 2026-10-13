// 편집 화면이 도식 작성 창의 반영을 받는 판정 (D3c-6 리뷰 G11). 작성 창은 서버에 저장된 반영을 조건 없이 넘기고, 받을지는
// 편집 화면이 정한다. 기준 덱이 지금 덱과 다르면 저장된 반영은 충돌로 보내고(다음 자동 저장이 덮지 않게), 저장 전 후보는 버린다
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps } from "react";
import { api, type Deck, type RenderPlan } from "../api/client";
import type { DiagramAuthoringDialog } from "../editor/DiagramAuthoringDialog";
import { EditorScreen } from "./EditorScreen";

type DialogProps = ComponentProps<typeof DiagramAuthoringDialog>;
let dialog: DialogProps | null = null;
vi.mock("../editor/DiagramAuthoringDialog", () => ({
  DiagramAuthoringDialog: (props: DialogProps) => { dialog = props; return null; },
}));
vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return { ...mod, api: { ...mod.api, measure: vi.fn(), putDeck: vi.fn(), getPreset: vi.fn(), listDrafts: vi.fn(), listJobs: vi.fn() } };
});

const project = { name: "p1", title: "제목", updated_at: "", status: "ok" as const };
const deck: Deck = {
  schema_version: 1,
  meta: { title: "제목", report_type: "research", audience: "", presenter: "", preset_overrides: {} },
  structure: { chapters: [{ id: "c1", topic: "주제", conclusion: "", template: "bullet_box", source_refs: [] }] },
  slides: [{ chapter_id: "c1", eyebrow: "", subtitle: "", slots: {
    template: "bullet_box", bullets: [{ text: "옛 불릿", level: 0 }], conclusion: "결론", footnote: "" } }],
};
const plan: RenderPlan = { page_width_pt: 960, page_height_pt: 540, slides: [{ chapter_id: "c1", template: "bullet_box",
  warnings: [], frames: [] }], style: { korean_font: "Noto Sans KR", latin_font: "Noto Sans KR", text_color: "202020",
  box_padding_pt: 10, line_spacing: 1.4, bullet_indent_pt: 18, bullet_gap_pt: 6, table_cell_pad_x_pt: 6,
  table_cell_pad_y_pt: 3, border_width_pt: 0.75, bullet_char: "•", bullet_font: "Arial" } };

beforeEach(() => {
  dialog = null;
  vi.mocked(api.measure).mockResolvedValue(plan);
  vi.mocked(api.putDeck).mockResolvedValue({ ok: true });
  vi.mocked(api.listDrafts).mockResolvedValue([]);
  vi.mocked(api.getPreset).mockReturnValue(new Promise(() => {}));
  vi.mocked(api.listJobs).mockResolvedValue([]);
});

async function openDialog() {
  render(<EditorScreen project={project} deck={deck} onDeckChange={() => {}} timings={{ measureMs: 0, saveMs: 0 }} />);
  await userEvent.click(await screen.findByRole("button", { name: "도식 추가" }));
  expect(dialog).not.toBeNull();
  return dialog!;
}

it("기준이 지금 덱과 다른 저장된 도식 반영은 충돌로 보낸다", async () => {
  const props = await openDialog();
  const stale: Deck = { ...deck, meta: { ...deck.meta, title: "다른 기준" } };
  act(() => props.onApply(deck, stale, "c1", true));
  expect(await screen.findByText(/반영한 내용은 서버에 저장됐지만 그사이 이 화면이 바뀌어 받지 않았습니다/)).toBeInTheDocument();
});

it("기준이 다른 저장 전 후보는 조용히 버린다", async () => {
  const props = await openDialog();
  const stale: Deck = { ...deck, meta: { ...deck.meta, title: "다른 기준" } };
  act(() => props.onApply(deck, stale, "c1", false));
  await new Promise((r) => setTimeout(r, 0));
  expect(screen.queryByText(/반영한 내용은 서버에 저장됐지만/)).toBeNull();
});
