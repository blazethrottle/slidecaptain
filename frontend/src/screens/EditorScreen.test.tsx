import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api, type Deck, type Preset, type RenderPlan } from "../api/client";
import { EditorScreen } from "./EditorScreen";

vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return { ...mod, api: { ...mod.api, measure: vi.fn(), putDeck: vi.fn(), getPreset: vi.fn() } };
});

// DesignPanel이 오른쪽 패널에 함께 그려지므로, 그 프리셋 조회 목이 필요하다 (Task 14 DesignPanel.test.tsx 픽스처 재사용)
const preset = {
  fonts: { korean: "Noto Sans KR", latin: "Noto Sans KR" },
  font_roles: { cover_title_pt: 28, section_title_pt: 24, title_pt: 20, subtitle_pt: 14,
    body_pt: 12, box_pt: 12, table_pt: 12, footnote_pt: 9, page_number_pt: 9 },
  colors: { text: "202020", accent: "1F4E79", box_fill: "EEF3F9",
    table_header_fill: "F2F2F2", border: "D0D7E2", background: "FFFFFF" },
  spacing: {}, bullet_marker: { char: "•", font: "Arial" },
  page_width_pt: 960, page_height_pt: 540, language: "ko-KR",
} as unknown as Preset;

const project = { name: "p1", title: "제목", updated_at: "", status: "ok" as const };

const deck: Deck = {
  schema_version: 1,
  meta: { title: "제목", report_type: "research", audience: "", presenter: "", preset_overrides: {} },
  structure: { chapters: [
    { id: "c1", topic: "주제", conclusion: "", template: "bullet_box", source_refs: [] }] },
  slides: [{ chapter_id: "c1", slots: {
    template: "bullet_box", bullets: [{ text: "하나", level: 0 }], conclusion: "결론", footnote: "" } }],
};

const plan: RenderPlan = {
  page_width_pt: 960, page_height_pt: 540,
  style: {
    korean_font: "Noto Sans KR", latin_font: "Noto Sans KR", text_color: "202020",
    box_padding_pt: 10, line_spacing: 1.4, bullet_indent_pt: 18, bullet_gap_pt: 6,
    table_cell_pad_x_pt: 6, table_cell_pad_y_pt: 3, border_width_pt: 0.75,
    bullet_char: "•", bullet_font: "Arial",
  },
  slides: [{ chapter_id: "c1", template: "bullet_box", warnings: [], frames: [
    { name: "c1:bullets", x: 50, y: 92, w: 860, h: 300, fill: null, border: null,
      valign: "top", table: null,
      paras: [{ text: "하나", level: 0, font_pt: 12, bold: false, color: "202020",
        align: "left", bullet: true, lines: ["하나"] }] },
  ] }],
};

it("실측을 불러 미리보기를 그리고, 편집을 자동 저장한다 (첫 저장은 스냅샷)", async () => {
  vi.mocked(api.measure).mockResolvedValue(plan);
  vi.mocked(api.putDeck).mockResolvedValue({ ok: true });
  vi.mocked(api.getPreset).mockResolvedValue(preset);
  render(<EditorScreen project={project} deck={deck} onDeckChange={() => {}}
    timings={{ measureMs: 0, saveMs: 0 }} />);
  // 속성 패널도 같은 불릿 텍스트를 보여주므로, 미리보기 영역으로 조회를 한정한다
  const preview = () => within(document.querySelector(".editor-center") as HTMLElement);
  expect(await preview().findByText("하나")).toBeInTheDocument();
  // 선택 후 같은 문단을 다시 클릭해 인라인 수정
  await userEvent.click(preview().getByText("하나"));
  await userEvent.click(preview().getByText("하나"));
  const box = await screen.findByLabelText("내용 수정");
  await userEvent.clear(box);
  await userEvent.type(box, "고침{Enter}");
  await waitFor(() => expect(api.putDeck).toHaveBeenCalled());
  const [, savedDeck, snapshot] = vi.mocked(api.putDeck).mock.calls[0];
  const slots = savedDeck.slides[0].slots;
  expect(slots.template === "bullet_box" && slots.bullets?.[0].text).toBe("고침");
  expect(snapshot).toBe(true);  // 편집 세션 첫 저장 (결정 1)
});

it("Ctrl+Z가 직전 편집을 되돌린다", async () => {
  vi.mocked(api.measure).mockResolvedValue(plan);
  vi.mocked(api.putDeck).mockResolvedValue({ ok: true });
  vi.mocked(api.getPreset).mockResolvedValue(preset);
  render(<EditorScreen project={project} deck={deck} onDeckChange={() => {}}
    timings={{ measureMs: 0, saveMs: 0 }} />);
  // 속성 패널도 같은 불릿 텍스트를 보여주므로, 미리보기 영역으로 조회를 한정한다
  const preview = () => within(document.querySelector(".editor-center") as HTMLElement);
  await preview().findByText("하나");
  await userEvent.click(preview().getByText("하나"));
  await userEvent.click(preview().getByText("하나"));
  const box = await screen.findByLabelText("내용 수정");
  await userEvent.clear(box);
  await userEvent.type(box, "고침{Enter}");
  await userEvent.keyboard("{Control>}z{/Control}");
  await waitFor(() => {
    const calls = vi.mocked(api.putDeck).mock.calls;
    const last = calls[calls.length - 1][1];
    const slots = last.slides[0].slots;
    expect(slots.template === "bullet_box" && slots.bullets?.[0].text).toBe("하나");
  });
});
