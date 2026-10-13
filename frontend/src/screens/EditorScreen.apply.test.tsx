// 편집 화면과 생성 패널의 서버 적용 연결 (D3c-5, 계획 4.7). 요청 중에는 화면을 잠그고, 성공하면 응답 덱을 저장본으로 받아
// 같은 내용을 다시 저장하지 않는다. 요청 중 덱이 바뀌면 응답을 받지 않는다(도식 경로와 같다)
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api, type ChapterResult, type Deck, type RenderPlan } from "../api/client";
import { deferred } from "../test/fixtures";
import { jobView } from "../test/jobs";
import { emptyUsage } from "../test/usage";
import { EditorScreen } from "./EditorScreen";

vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return {
    ...mod,
    api: { ...mod.api, measure: vi.fn(), putDeck: vi.fn(), getPreset: vi.fn(), listDrafts: vi.fn(), listJobs: vi.fn(),
      applyCandidate: vi.fn() },
  };
});

const project = { name: "p1", title: "제목", updated_at: "", status: "ok" as const };
const deck: Deck = {
  schema_version: 1,
  meta: { title: "제목", report_type: "research", audience: "", presenter: "", preset_overrides: {} },
  structure: { chapters: [{ id: "c1", topic: "주제", conclusion: "", template: "bullet_box", source_refs: [] }] },
  slides: [{ chapter_id: "c1", eyebrow: "", subtitle: "", slots: {
    template: "bullet_box", bullets: [{ text: "옛 불릿", level: 0 }], conclusion: "결론", footnote: "" } }],
};
const result: ChapterResult = {
  status: "ok", usage: emptyUsage(), raw_text: "", warnings: [], unverified_numbers: [], format_retried: false,
  condensed: false, slots: { template: "bullet_box", bullets: [{ text: "새 불릿", level: 0 }], conclusion: "결론", footnote: "" },
};
const saved: Deck = { ...deck, slides: [{ ...deck.slides[0], slots: result.slots! }] };
const plan = (text: string): RenderPlan => ({
  page_width_pt: 960, page_height_pt: 540,
  style: { korean_font: "Noto Sans KR", latin_font: "Noto Sans KR", text_color: "202020", box_padding_pt: 10,
    line_spacing: 1.4, bullet_indent_pt: 18, bullet_gap_pt: 6, table_cell_pad_x_pt: 6, table_cell_pad_y_pt: 3,
    border_width_pt: 0.75, bullet_char: "•", bullet_font: "Arial" },
  slides: [{ chapter_id: "c1", template: "bullet_box", warnings: [], frames: [
    { name: "c1:bullets", x: 50, y: 92, w: 860, h: 300, fill: null, border: null, valign: "top", table: null,
      paras: [{ text, level: 0, font_pt: 12, bold: false, color: "202020", align: "left", bullet: true, lines: [text] }] },
  ] }],
});

beforeEach(() => {
  vi.mocked(api.measure).mockImplementation(async (d: Deck) => plan(
    (d.slides[0].slots as { bullets: { text: string }[] }).bullets[0].text));
  vi.mocked(api.putDeck).mockResolvedValue({ ok: true });
  vi.mocked(api.listDrafts).mockResolvedValue([]);
  vi.mocked(api.getPreset).mockReturnValue(new Promise(() => {}));  // 디자인 패널의 프리셋은 이 시험과 무관하다
  vi.mocked(api.listJobs).mockResolvedValue([jobView("chapter", { target: "c1",
    result: result as unknown as Record<string, unknown> })]);
});

it("적용 중에는 편집 화면을 잠그고, 응답 덱을 저장본으로 받아 다시 저장하지 않는다", async () => {
  const pending = deferred<Deck>();
  vi.mocked(api.applyCandidate).mockReturnValue(pending.promise);
  const onDeckChange = vi.fn();
  render(<EditorScreen project={project} deck={deck} onDeckChange={onDeckChange} timings={{ measureMs: 0, saveMs: 0 }} />);
  await userEvent.click(await screen.findByText("반영"));
  await waitFor(() => expect(document.querySelector(".editor-screen")).toHaveAttribute("inert"));
  pending.resolve(saved);
  await waitFor(() => expect(document.querySelector(".editor-screen")).not.toHaveAttribute("inert"));
  const center = document.querySelector(".editor-center") as HTMLElement;
  expect(await within(center).findByText("새 불릿")).toBeInTheDocument();
  expect(onDeckChange).toHaveBeenCalledWith(saved);
  await new Promise((r) => setTimeout(r, 20));
  expect(api.putDeck).not.toHaveBeenCalled();  // 서버가 이미 저장했다
});

it("적용 결과를 확인하지 못하면 충돌 안내로 자동 저장을 멈추고 서버 내용으로 되돌리기를 연다", async () => {
  const { ApiError } = await import("../api/client");
  vi.mocked(api.applyCandidate).mockRejectedValue(new ApiError(503, "작업 기록을 읽거나 쓰지 못했습니다.", "ledger_write_failed"));
  render(<EditorScreen project={project} deck={deck} onDeckChange={() => {}} timings={{ measureMs: 0, saveMs: 0 }} />);
  await userEvent.click(await screen.findByText("반영"));
  expect(await screen.findByText(/반영 결과를 확인하지 못했습니다\. 서버 내용을 다시 읽어 주세요\./)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "서버 내용으로 되돌리기" })).toBeInTheDocument();
});

it("요청 중 충돌이 생기면 응답 덱을 받지 않아 충돌 안내와 화면 덱이 그대로다 (도식 경로와 같은 규칙)", async () => {
  const pending = deferred<Deck>();
  vi.mocked(api.applyCandidate).mockReturnValue(pending.promise);
  const onDeckChange = vi.fn();
  const view = (signal: number) => <EditorScreen project={project} deck={deck} onDeckChange={onDeckChange}
    conflictSignal={signal} timings={{ measureMs: 0, saveMs: 0 }} />;
  const { rerender } = render(view(0));
  await userEvent.click(await screen.findByText("반영"));
  await waitFor(() => expect(api.applyCandidate).toHaveBeenCalled());
  rerender(view(1));  // 그사이 다른 탭의 묶음이 끝나 저장본이 바뀌었다
  const notice = await screen.findByText(/서버 내용으로 되돌리기|다른 곳에서/, { selector: "[role=alert]" });
  pending.resolve(saved);
  await waitFor(() => expect(document.querySelector(".editor-screen")).not.toHaveAttribute("inert"));
  expect(notice).toBeInTheDocument();
  expect(onDeckChange).not.toHaveBeenCalledWith(saved);
  expect(within(document.querySelector(".editor-center") as HTMLElement).getByText("옛 불릿")).toBeInTheDocument();
});

it("적용 중에는 단계 이동 전 저장이 거절되고 부모에 떠날 수 없음을 알린다 (계획 4.7의 2, 리뷰 F7)", async () => {
  const pending = deferred<Deck>();
  vi.mocked(api.applyCandidate).mockReturnValue(pending.promise);
  let flush: (() => Promise<boolean | "declined">) | null = null;
  const onBusyChange = vi.fn();
  render(<EditorScreen project={project} deck={deck} onDeckChange={() => {}} timings={{ measureMs: 0, saveMs: 0 }}
    onEditorReady={(f) => { flush = f; }} onBusyChange={onBusyChange} />);
  await userEvent.click(await screen.findByText("반영"));
  await waitFor(() => expect(document.querySelector(".editor-screen")).toHaveAttribute("inert"));
  expect(onBusyChange).toHaveBeenLastCalledWith(true);
  expect(await flush!()).toBe(false);
  pending.resolve(saved);
  await waitFor(() => expect(onBusyChange).toHaveBeenLastCalledWith(false));
  expect(await flush!()).toBe(true);
});
