// 편집 화면이 복구 화면에서 넘겨받은 도식 후보 작업을 여는 막힘 조건 (C1 계획 W2-b 4.3, W2 리뷰 W2R-08의 F5). 읽기 전용이면
// 행을 읽지 않고 안내하며, 넘겨받은 작업 ID는 어느 경우에도 한 번 쓰고 부모에게 지우게 한다
import { render, screen, waitFor } from "@testing-library/react";
import { api, type Deck, type RenderPlan } from "../api/client";
import { jobView } from "../test/jobs";
import { EditorScreen } from "./EditorScreen";

vi.mock("../editor/DiagramAuthoringDialog", () => ({ DiagramAuthoringDialog: () => <div role="dialog">작성 창</div> }));
vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return { ...mod, api: { ...mod.api, measure: vi.fn(), putDeck: vi.fn(), getPreset: vi.fn(), listDrafts: vi.fn(),
    listJobs: vi.fn(), getJob: vi.fn() } };
});

const project = { name: "p1", title: "제목", updated_at: "", status: "ok" as const };
const deck: Deck = {
  schema_version: 1,
  meta: { title: "제목", report_type: "research", audience: "", presenter: "", preset_overrides: {} },
  structure: { chapters: [{ id: "c1", topic: "주제", conclusion: "", template: "bullet_box", source_refs: [] }] },
  slides: [{ chapter_id: "c1", eyebrow: "", subtitle: "", slots: {
    template: "bullet_box", bullets: [{ text: "불릿", level: 0 }], conclusion: "결론", footnote: "" } }],
};
const plan: RenderPlan = { page_width_pt: 960, page_height_pt: 540, slides: [{ chapter_id: "c1", template: "bullet_box",
  warnings: [], frames: [] }], style: { korean_font: "Noto Sans KR", latin_font: "Noto Sans KR", text_color: "202020",
  box_padding_pt: 10, line_spacing: 1.4, bullet_indent_pt: 18, bullet_gap_pt: 6, table_cell_pad_x_pt: 6,
  table_cell_pad_y_pt: 3, border_width_pt: 0.75, bullet_char: "•", bullet_font: "Arial" } };
const FAILED = "이 도식 후보를 열지 못했습니다. 복구 화면에서 다시 확인해 주세요.";

beforeEach(() => {
  vi.mocked(api.measure).mockResolvedValue(plan);
  vi.mocked(api.getPreset).mockReturnValue(new Promise(() => {}));
  vi.mocked(api.listDrafts).mockResolvedValue([]);
  vi.mocked(api.listJobs).mockResolvedValue([]);
  vi.mocked(api.getJob).mockReset();
});

it("읽기 전용이면 행을 읽지 않고 작성 창을 열지 않으며 안내한다", async () => {
  const consumed = vi.fn();
  render(<EditorScreen project={project} deck={deck} onDeckChange={() => {}} timings={{ measureMs: 0, saveMs: 0 }}
    readOnly reopenDiagramJob="job-d1" onReopenConsumed={consumed} />);
  expect(await screen.findByText(FAILED)).toBeInTheDocument();
  expect(consumed).toHaveBeenCalledOnce();
  expect(api.getJob).not.toHaveBeenCalled();
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

it("행을 읽지 못하면 작성 창을 열지 않고 안내한다", async () => {
  vi.mocked(api.getJob).mockRejectedValue(new Error("읽기 실패"));
  const consumed = vi.fn();
  render(<EditorScreen project={project} deck={deck} onDeckChange={() => {}} timings={{ measureMs: 0, saveMs: 0 }}
    reopenDiagramJob="job-d1" onReopenConsumed={consumed} />);
  expect(await screen.findByText(FAILED)).toBeInTheDocument();
  expect(consumed).toHaveBeenCalledOnce();
});

it("넘겨받은 작업이 없으면 행을 읽지 않는다", async () => {
  vi.mocked(api.getJob).mockResolvedValue(jobView("diagram"));
  render(<EditorScreen project={project} deck={deck} onDeckChange={() => {}} timings={{ measureMs: 0, saveMs: 0 }} />);
  await waitFor(() => expect(api.measure).toHaveBeenCalled());
  expect(api.getJob).not.toHaveBeenCalled();
  expect(screen.queryByText(FAILED)).not.toBeInTheDocument();
});
