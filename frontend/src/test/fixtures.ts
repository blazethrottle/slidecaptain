// 저장 안전성 테스트 공용 픽스처 (2026-09-03 묶음). EditorScreen.test.tsx 와 ProjectView.test.tsx 의 픽스처 형태를 따른다
import type { Deck, Preset, RenderPlan } from "../api/client";

export const project = { name: "p1", title: "제목", updated_at: "", status: "ok" as const };

export const preset = {
  fonts: { korean: "Noto Sans KR", latin: "Noto Sans KR" },
  font_roles: { cover_title_pt: 28, section_title_pt: 24, title_pt: 20, subtitle_pt: 14,
    body_pt: 12, box_pt: 12, table_pt: 12, footnote_pt: 9, page_number_pt: 9 },
  colors: { text: "202020", accent: "1F4E79", box_fill: "EEF3F9",
    table_header_fill: "F2F2F2", border: "D0D7E2", background: "FFFFFF" },
  spacing: {}, bullet_marker: { char: "•", font: "Arial" },
  page_width_pt: 960, page_height_pt: 540, language: "ko-KR",
} as unknown as Preset;

export function deckWith(bullets: string[], presenter = ""): Deck {
  return {
    schema_version: 1,
    meta: { title: "제목", report_type: "research", audience: "", presenter, preset_overrides: {} },
    structure: { chapters: [
      { id: "c1", topic: "주제", conclusion: "", template: "bullet_box", source_refs: [] }] },
    slides: [{ chapter_id: "c1", slots: {
      template: "bullet_box", bullets: bullets.map((t) => ({ text: t, level: 0 as const })),
      conclusion: "결론", footnote: "" } }],
  };
}

export function planWith(bullets: string[]): RenderPlan {
  return {
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
        paras: bullets.map((t) => ({ text: t, level: 0, font_pt: 12, bold: false, color: "202020",
          align: "left" as const, bullet: true, lines: [t] })) },
    ] }],
  };
}

export function bulletsOf(d: Deck): string[] {
  const s = d.slides[0].slots;
  return s.template === "bullet_box" ? (s.bullets ?? []).map((b) => b.text) : [];
}

export function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

export const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
