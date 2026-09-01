import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api, type Deck, type Preset } from "../api/client";
import { DesignPanel } from "./DesignPanel";

vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return { ...mod, api: { ...mod.api, getPreset: vi.fn() } };
});

const preset = {
  fonts: { korean: "Noto Sans KR", latin: "Noto Sans KR" },
  font_roles: { cover_title_pt: 28, section_title_pt: 24, title_pt: 20, subtitle_pt: 14,
    body_pt: 12, box_pt: 12, table_pt: 12, footnote_pt: 9, page_number_pt: 9 },
  colors: { text: "202020", accent: "1F4E79", box_fill: "EEF3F9",
    table_header_fill: "F2F2F2", border: "D0D7E2", background: "FFFFFF" },
  spacing: {}, bullet_marker: { char: "•", font: "Arial" },
  page_width_pt: 960, page_height_pt: 540, language: "ko-KR",
} as unknown as Preset;

const deck: Deck = {
  schema_version: 1,
  meta: { title: "t", report_type: "research", audience: "", presenter: "", preset_overrides: {} },
  structure: { chapters: [] }, slides: [],
};

it("본문 크기를 고치면 덮어쓰기로 기록된다", async () => {
  vi.mocked(api.getPreset).mockResolvedValue(preset);
  const onApply = vi.fn();
  render(<DesignPanel deck={deck} onApply={onApply} />);
  const input = await screen.findByLabelText("본문 크기(pt)");
  expect(input).toHaveValue(12);
  await userEvent.clear(input);
  await userEvent.type(input, "13");
  await userEvent.tab();
  const edit = onApply.mock.calls[0][0] as (d: Deck) => Deck;
  const next = edit(deck);
  expect((next.meta.preset_overrides as Record<string, Record<string, number>>).font_roles.body_pt).toBe(13);
});

it("덱 상태가 바뀌면(언두 등) 표시값이 따라간다", async () => {
  vi.mocked(api.getPreset).mockResolvedValue(preset);
  const onApply = vi.fn();
  const withOverride = {
    ...deck,
    meta: { ...deck.meta, preset_overrides: { font_roles: { body_pt: 13 } } },
  };
  const { rerender } = render(<DesignPanel deck={withOverride} onApply={onApply} />);
  expect(await screen.findByLabelText("본문 크기(pt)")).toHaveValue(13);
  rerender(<DesignPanel deck={deck} onApply={onApply} />);
  expect(await screen.findByLabelText("본문 크기(pt)")).toHaveValue(12);
});
