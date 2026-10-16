// 편집 화면이 복구 화면에서 넘겨받은 도식 후보 작업을 여는 막힘 조건 (C1 계획 W2-b 4.3, W2 리뷰 W2R-08의 F5). 읽기 전용이면
// 행을 읽지 않고 안내하며, 넘겨받은 작업 ID는 어느 경우에도 한 번 쓰고 부모에게 지우게 한다
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { api, type Deck, type JobView, type RenderPlan } from "../api/client";
import { deferred } from "../test/fixtures";
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

// C1 묶음 리뷰 BR-07 ①: 행을 읽는 동안 다른 탭의 묶음이 시작되어 읽기 전용이 되면 작성 창을 열지 않는다
it("행 읽기 응답 전에 읽기 전용이 되면 작성 창을 열지 않는다", async () => {
  let resolve!: (job: ReturnType<typeof jobView>) => void;
  vi.mocked(api.getJob).mockReturnValue(new Promise((r) => { resolve = r; }));
  const props = { project, deck, onDeckChange: () => {}, timings: { measureMs: 0, saveMs: 0 }, reopenDiagramJob: "job-d1",
    onReopenConsumed: () => {} };
  const { rerender } = render(<EditorScreen {...props} />);
  await waitFor(() => expect(api.getJob).toHaveBeenCalledOnce());
  rerender(<EditorScreen {...props} readOnly />);
  resolve(jobView("diagram", { id: "job-d1", relevance_hash: "d1:a|", params: { mode: "create", chapter_id: "new-diagram",
    topic: "t", role: "evidence", claim_ids: [] }, result: { status: "ok", diagram: { nodes: [], edges: [] } } }));
  expect(await screen.findByText(FAILED)).toBeInTheDocument();
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});


// C1 W2 리뷰 W2R-10: 지금 코드는 행을 읽기 전에 작업 ID를 지우게 한다. 읽는 사이 다시 마운트되면(묶음 종결, 덱 다시 읽기)
// 앞 화면의 응답은 버려지고 새 화면은 지워진 ID를 받아, 작성 창도 안내도 없이 끝난다 (C2 계획 4.3 (23))
it("행을 읽는 동안 다시 마운트되어도 새 화면이 그 작업을 이어 받아 처리한다", async () => {
  const first = deferred<JobView>();
  vi.mocked(api.getJob).mockReturnValueOnce(first.promise).mockResolvedValue(jobView("diagram"));
  const consumed = vi.fn();
  function Harness() {
    const [id, setId] = useState<string | null>("job-d1");
    const [mount, setMount] = useState(0);
    return <>
      <button onClick={() => setMount((n) => n + 1)}>다시 마운트</button>
      <EditorScreen key={mount} project={project} deck={deck} onDeckChange={() => {}} timings={{ measureMs: 0, saveMs: 0 }}
        reopenDiagramJob={id} onReopenConsumed={() => { consumed(); setId(null); }} />
    </>;
  }
  render(<Harness />);
  await waitFor(() => expect(api.getJob).toHaveBeenCalledTimes(1));
  await userEvent.click(screen.getByRole("button", { name: "다시 마운트" }));
  expect(await screen.findByText(FAILED)).toBeInTheDocument();  // 이 작업은 열 수 없는 행이라 안내로 끝난다
  expect(api.getJob).toHaveBeenCalledTimes(2);
  first.resolve(jobView("diagram"));
  await new Promise((r) => setTimeout(r, 20));
  expect(consumed).toHaveBeenCalledOnce();
});
