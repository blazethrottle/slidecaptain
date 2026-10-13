// 서버 적용의 ETag 흐름 (D3c-5 리뷰 F1, F6). API 함수를 흉내 내지 않고 fetch만 바꿔 실제 request()의 ETag 처리를 지난다.
// 적용 요청은 이 탭의 마지막 저장 ETag를 If-Match로 싣고, 받은 응답의 ETag가 다음 저장의 If-Match가 된다. 적용 중의 되돌리기
// 단축키는 덱을 바꾸지 않는다(바꾸면 응답을 받지 못하고, 다음 자동 저장이 서버의 반영 결과를 덮었다)
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api, resetEtags, type ChapterResult, type Deck, type RenderPlan } from "../api/client";
import { applyThroughCompare, previewOf } from "../test/compare";
import { jobView } from "../test/jobs";
import { emptyUsage } from "../test/usage";
import { EditorScreen } from "./EditorScreen";

vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return { ...mod, api: { ...mod.api, measure: vi.fn(), getPreset: vi.fn(), listDrafts: vi.fn(), listJobs: vi.fn() } };
});

const project = { name: "p1", title: "제목", updated_at: "", status: "ok" as const };
const deck: Deck = {
  schema_version: 1,
  meta: { title: "제목", report_type: "research", audience: "", presenter: "", preset_overrides: {} },
  structure: { chapters: [{ id: "c1", topic: "주제", conclusion: "", template: "bullet_box", source_refs: [] }] },
  slides: [{ chapter_id: "c1", eyebrow: "", subtitle: "", slots: {
    template: "bullet_box", bullets: [{ text: "옛불릿", level: 0 }], conclusion: "결론", footnote: "" } }],
};
const result: ChapterResult = {
  status: "ok", usage: emptyUsage(), raw_text: "", warnings: [], unverified_numbers: [], format_retried: false,
  condensed: false, slots: { template: "bullet_box", bullets: [{ text: "새불릿", level: 0 }], conclusion: "결론", footnote: "" },
};
const applied: Deck = { ...deck, slides: [{ ...deck.slides[0], slots: result.slots! }] };
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

afterEach(() => vi.unstubAllGlobals());

it("적용은 마지막 저장 ETag로 보내고, 응답 ETag로 다음 저장을 보내며, 적용 중 되돌리기는 덱을 바꾸지 않는다", async () => {
  resetEtags();
  const puts: { ifMatch: string | null; bullet: string }[] = [];
  const applies: (string | null)[] = [];
  let resolveApply: (r: Response) => void = () => {};
  vi.stubGlobal("fetch", vi.fn(async (path: string, init: RequestInit) => {
    const headers = new Headers(init?.headers);
    if (path.includes("/apply/preview")) {  // 비교 화면의 미리 보기: 이 탭이 마지막으로 저장한 저장본 기준
      return new Response(JSON.stringify(previewOf(deck.slides[0], result.slots!, { base_etag: `E${puts.length}` })),
        { status: 200 });
    }
    if (path.includes("/apply")) {
      applies.push(headers.get("If-Match"));
      return new Promise<Response>((res) => { resolveApply = res; });
    }
    if (init?.method === "PUT") {
      const body = JSON.parse(init.body as string);
      puts.push({ ifMatch: headers.get("If-Match"), bullet: body.slides[0].slots.bullets[0].text });
      return new Response(JSON.stringify({ ok: true }), { status: 200, headers: { ETag: `"E${puts.length}"` } });
    }
    return new Response(JSON.stringify(deck), { status: 200, headers: { ETag: '"E0"' } });
  }));
  await api.getDeck("p1");  // 이 탭이 본 저장본의 ETag
  vi.mocked(api.measure).mockImplementation(async (d: Deck) => plan(
    (d.slides[0].slots as { bullets: { text: string }[] }).bullets[0].text));
  vi.mocked(api.listDrafts).mockResolvedValue([]);
  vi.mocked(api.getPreset).mockReturnValue(new Promise(() => {}));
  vi.mocked(api.listJobs).mockResolvedValue([jobView("chapter", { target: "c1",
    result: result as unknown as Record<string, unknown> })]);
  render(<EditorScreen project={project} deck={deck} onDeckChange={() => {}} timings={{ measureMs: 0, saveMs: 0 }} />);
  const preview = () => within(document.querySelector(".editor-center") as HTMLElement);
  const edit = async (from: string, to: string) => {
    await userEvent.click(await preview().findByText(from));
    await userEvent.click(preview().getByText(from));
    const box = await screen.findByLabelText("내용 수정");
    await userEvent.clear(box);
    await userEvent.type(box, `${to}{Enter}`);
  };
  await edit("옛불릿", "고친불릿");
  await waitFor(() => expect(puts).toEqual([{ ifMatch: '"E0"', bullet: "고친불릿" }]));
  await applyThroughCompare();
  await waitFor(() => expect(applies).toEqual(['"E1"']));  // 반영 직전 저장의 ETag
  fireEvent.keyDown(document.body, { key: "z", ctrlKey: true });  // 실제 브라우저에서는 inert가 초점을 body로 옮긴다
  resolveApply(new Response(JSON.stringify(applied), { status: 200, headers: { ETag: '"EAPPLY"' } }));
  expect(await preview().findByText("새불릿")).toBeInTheDocument();
  await new Promise((r) => setTimeout(r, 30));
  expect(puts).toHaveLength(1);  // 서버의 반영 결과를 덮는 저장이 없다
  await edit("새불릿", "그다음");
  await waitFor(() => expect(puts[1]).toEqual({ ifMatch: '"EAPPLY"', bullet: "그다음" }));
});
