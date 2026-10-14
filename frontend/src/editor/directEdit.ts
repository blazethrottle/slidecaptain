// 직접 수정의 화면 쪽 계약 (개정판 D3c-3, 계획 4.2~4.5).
// 요소 열쇠와 정규화는 서버(models/direct_edit.py)와 같은 규칙이고 고정 파일 frame-keys.json으로 같은지 지킨다.
// 화면도 정규화하는 이유: PUT 응답이 정규화한 덱을 돌려주지 않아 화면 덱이 서버와 어긋나면, 지운 수정이 같은 화면
// 세션 안에서 되살아난다 (D3c 계획 재리뷰 RR5)
import type { Deck, Frame, SlidePlan } from "../api/client";
import type { components } from "../api/types";

export type ElementEdit = components["schemas"]["ElementEdit"];
type Slide = Deck["slides"][number];
export type EditKind = "move" | "font" | "text_color" | "fill" | "hide";
export type KeySpec = { kinds: EditKind[]; drag: "handle" | "body" };
export type TextColorRole = NonNullable<ElementEdit["text_color"]>;
export type FillRole = NonNullable<ElementEdit["fill"]>;

const TEXT: EditKind[] = ["font", "hide", "move", "text_color"];
const TEXT_FILLED: EditKind[] = ["fill", "font", "hide", "move", "text_color"];
const TABLE: EditKind[] = ["hide", "move"];
const BADGE: EditKind[] = ["fill", "hide", "move", "text_color"];

/** 글이 있는가. 공백만 있는 문구는 글이 없다(서버 _has_text와 같다). 문자열 아닌 칸(강조 여부 등)은 보지 않는다. */
function hasText(value: unknown): boolean {
  if (typeof value === "string") return value.trim() !== "";
  if (Array.isArray(value)) return value.some(hasText);
  if (value && typeof value === "object") return Object.values(value).some(hasText);
  return false;
}

// 글이 없는 요소는 글자 크기를 받지 않는다 (재리뷰 RR17, α 리뷰 A2)
function text(withText = true, filled = false): KeySpec {
  const kinds = (filled ? TEXT_FILLED : TEXT).filter((k) => withText || k !== "font");
  return { kinds, drag: "handle" };
}

/** 슬라이드의 요소 열쇠와 받는 수정 종류. 서버 frame_keys와 같다(쪽 번호는 넣지 않는다, 도식은 빈 사전). */
export function frameKeys(slide: Slide): Record<string, KeySpec> {
  const s = slide.slots;
  if (s.template === "diagram") return {};
  // 보고자는 메타에서 오므로 글 유무를 볼 수 없다(장 제목과 같다)
  if (s.template === "cover") return { cover_title: text(hasText(s.title)), subtitle: text(hasText(s.subtitle)),
    date: text(hasText(s.date)), presenter: text() };
  if (s.template === "divider") return { section_no: text(hasText(s.section_no)), section_title: text(hasText(s.section_title)) };
  const keys: Record<string, KeySpec> = { title: text() };
  if (slide.eyebrow) keys.eyebrow = text(hasText(slide.eyebrow));
  if (slide.subtitle) keys.subtitle = text(hasText(slide.subtitle));
  switch (s.template) {
    case "bullet_box":
      keys.bullets = text(hasText(s.bullets));
      keys.conclusion = text(hasText(s.conclusion), true);
      if (s.footnote) keys.footnote = text(hasText(s.footnote));
      break;
    case "summary":
      keys.conclusion = text(hasText(s.conclusion), true);
      keys.points = text(hasText(s.points));
      break;
    case "table":
      keys.table = { kinds: TABLE, drag: "body" };
      if (s.footnote) keys.footnote = text(hasText(s.footnote));
      break;
    case "compare2":
      keys.left_card = text(hasText(s.left));
      keys.right_card = text(hasText(s.right));
      keys.conclusion = text(hasText(s.conclusion), true);
      break;
    case "callout":
      keys.text = text(hasText(s.text));  // 채움은 슬롯의 tone이 정한다 (재리뷰 RR25)
      break;
    case "cards":
      s.cards.forEach((card, i) => { keys[`card${i}`] = text(hasText(card), !!card.emphasis); });
      break;
    case "process":
      s.steps.forEach((step, i) => {
        keys[`step${i}_badge`] = { kinds: BADGE, drag: "body" };
        keys[`step${i}`] = text(hasText([step.heading, step.subtitle]));
        if ((step.notes ?? []).length > 0) keys[`step${i}_labels`] = text(hasText(step.notes));
      });
      break;
    case "matrix":
      s.rows.forEach((row, i) => {
        keys[`row${i}_category`] = text(hasText(row.category), true);
        if (row.primary) keys[`row${i}_primary`] = text(hasText(row.primary));
        if ((row.items ?? []).length > 0) keys[`row${i}_items`] = text(hasText(row.items));
      });
      break;
  }
  return keys;
}

/** 정규화 다섯 규칙(서버 normalize_edits와 같다). 결과가 원래와 같으면 같은 객체를 돌려준다. */
export function normalizeEdits(
  edits: Record<string, ElementEdit> | undefined, keys: Record<string, KeySpec>,
): Record<string, ElementEdit> {
  const result: Record<string, ElementEdit> = {};
  for (const key of Object.keys(edits ?? {}).sort()) {
    const spec = keys[key];
    if (!spec) continue;
    const e = edits![key];
    const v: ElementEdit = {};
    if (spec.kinds.includes("move") && e.dx_pt != null && e.dy_pt != null && (e.dx_pt !== 0 || e.dy_pt !== 0)) {
      v.dx_pt = e.dx_pt; v.dy_pt = e.dy_pt;
    }
    if (spec.kinds.includes("font") && e.font_scale != null && e.font_scale !== 1) v.font_scale = e.font_scale;
    if (spec.kinds.includes("text_color") && e.text_color != null) v.text_color = e.text_color;
    if (spec.kinds.includes("fill") && e.fill != null) v.fill = e.fill;
    if (spec.kinds.includes("hide") && e.hidden) v.hidden = true;
    if (Object.keys(v).length > 0) result[key] = v;
  }
  return result;
}

function sameEdits(a: Record<string, ElementEdit> | undefined, b: Record<string, ElementEdit>): boolean {
  return JSON.stringify(a ?? {}) === JSON.stringify(b);
}

/** 덱 전체의 직접 수정을 정규화한다. 바뀐 슬라이드가 없으면 같은 덱을 돌려준다(되돌리기 이력을 늘리지 않게). */
export function normalizeDeckEdits(deck: Deck): Deck {
  let changed = false;
  const slides = deck.slides.map((slide) => {
    if (!slide.direct_edits || Object.keys(slide.direct_edits).length === 0) return slide;
    const next = normalizeEdits(slide.direct_edits, frameKeys(slide));
    if (sameEdits(slide.direct_edits, next)) return slide;
    changed = true;
    const { direct_edits: _drop, ...rest } = slide;
    return Object.keys(next).length > 0 ? { ...rest, direct_edits: next } : rest;
  });
  return changed ? { ...deck, slides } : deck;
}

/** 요소 하나의 수정을 바꾼다. 값이 undefined인 칸은 지운다("원래대로", 계획 4.5). */
export function editElement(deck: Deck, chapterId: string, key: string, patch: Partial<ElementEdit>): Deck {
  const next = normalizeDeckEdits({
    ...deck,
    slides: deck.slides.map((slide) => {
      if (slide.chapter_id !== chapterId) return slide;
      const current = { ...(slide.direct_edits?.[key] ?? {}) } as Record<string, unknown>;
      for (const [k, v] of Object.entries(patch)) {
        if (v === undefined) delete current[k]; else current[k] = v;
      }
      return { ...slide, direct_edits: { ...(slide.direct_edits ?? {}), [key]: current as ElementEdit } };
    }),
  });
  // 결과가 지금과 같으면(페이지 끝의 방향키, 지금 값과 같은 입력) 받은 덱을 돌려준다. 새 객체를 돌려주면 내용이 같은
  // 되돌리기 항목과 저장이 생긴다 (D3c-3 리뷰 F4)
  const before = deck.slides.find((s) => s.chapter_id === chapterId);
  const after = next.slides.find((s) => s.chapter_id === chapterId);
  return before && after && sameEdits(before.direct_edits, after.direct_edits ?? {}) ? deck : next;
}

/** 목록 항목 하나를 지운 뒤 순번 열쇠를 당긴다. 지운 항목의 수정은 버린다 (계획 4.2, 계획 리뷰 화면 S12). */
export function shiftListKeys(
  edits: Record<string, ElementEdit> | undefined, prefix: "card" | "step" | "row", removed: number,
): Record<string, ElementEdit> | undefined {
  if (!edits) return edits;
  const pattern = new RegExp(`^${prefix}(\\d+)(_.*)?$`);
  const result: Record<string, ElementEdit> = {};
  for (const [key, edit] of Object.entries(edits)) {
    const m = pattern.exec(key);
    if (!m) { result[key] = edit; continue; }
    const index = Number(m[1]);
    if (index === removed) continue;
    result[index > removed ? `${prefix}${index - 1}${m[2] ?? ""}` : key] = edit;
  }
  return result;
}

// 비교 차트의 두 프레임은 표의 열쇠로 묶는다
const GROUPED: Record<string, string> = { chart: "table", chart_conditions: "table" };

export function frameKey(frame: Pick<Frame, "name">): string {
  const name = frame.name.split(":").slice(1).join(":");
  return GROUPED[name] ?? name;
}

const WARNING_SUFFIXES = ["_heading", "_badge", "_tail", "_subtitle", "_span"];

/** 용량 경고의 slot이 가리키는 요소 열쇠(서버 warning_key와 같다, 고정 파일 warning-keys.json). */
export function warningKey(slot: string, keys: Iterable<string>): string | null {
  const set = new Set(keys);
  if (set.has(slot)) return slot;
  if (GROUPED[slot]) return GROUPED[slot];
  const label = /^(step\d+_labels)_\d+$/.exec(slot);
  if (label && set.has(label[1])) return label[1];
  for (const suffix of WARNING_SUFFIXES) {
    if (!slot.endsWith(suffix)) continue;
    const base = slot.slice(0, -suffix.length);
    if (set.has(base)) return base;
    if (GROUPED[base]) return GROUPED[base];
  }
  return null;
}

export type Box = { x: number; y: number; w: number; h: number; hidden: boolean };

/** 그리는 위치와 숨김. "프레임의 기본 자리 + 현재 덱의 거리"를 엔진과 같은 규칙으로 자른다 (계획 4.5, 재리뷰 RR3).
 * 상태를 따로 두지 않으므로 놓는 순간 새 자리에 그리고, 되돌리기 뒤에도 지울 것이 없다. */
export function displayBoxes(
  slide: SlidePlan, edits: Record<string, ElementEdit> | undefined, pageW: number, pageH: number,
): Map<string, Box> {
  const groups = new Map<string, Frame[]>();
  for (const f of slide.frames) {
    const k = frameKey(f);
    groups.set(k, [...(groups.get(k) ?? []), f]);
  }
  const boxes = new Map<string, Box>();
  for (const [key, frames] of groups) {
    const edit = edits?.[key];
    const base = frames.map((f) => ({ f, x: f.base_x ?? f.x, y: f.base_y ?? f.y }));
    let dx = 0;
    let dy = 0;
    if (edit?.dx_pt != null && edit.dy_pt != null) {
      const x0 = Math.min(...base.map((b) => b.x));
      const y0 = Math.min(...base.map((b) => b.y));
      const width = Math.max(...base.map((b) => b.x + b.f.w)) - x0;
      const height = Math.max(...base.map((b) => b.y + b.f.h)) - y0;
      dx = Math.min(Math.max(x0 + edit.dx_pt, 0), pageW - width) - x0;
      dy = Math.min(Math.max(y0 + edit.dy_pt, 0), pageH - height) - y0;
    }
    for (const b of base) {
      // 수정값을 넘기지 않으면 계획의 숨김 표시를 따른다(편집 화면 밖의 미리보기)
      boxes.set(b.f.name, { x: b.x + dx, y: b.y + dy, w: b.f.w, h: b.f.h, hidden: edits === undefined ? !!b.f.hidden : !!edit?.hidden });
    }
  }
  return boxes;
}

/** 엔진의 자리에서 그 거리로 옮겼을 때 페이지 안에 남는 거리. 저장하는 쪽에서 자른다 (재리뷰 RR3). */
export function clampOffset(
  slide: SlidePlan, key: string, dx: number, dy: number, pageW: number, pageH: number,
): { dx: number; dy: number } {
  const frames = slide.frames.filter((f) => frameKey(f) === key);
  if (frames.length === 0) return { dx, dy };
  const base = frames.map((f) => ({ x: f.base_x ?? f.x, y: f.base_y ?? f.y, w: f.w, h: f.h }));
  const x0 = Math.min(...base.map((b) => b.x));
  const y0 = Math.min(...base.map((b) => b.y));
  const width = Math.max(...base.map((b) => b.x + b.w)) - x0;
  const height = Math.max(...base.map((b) => b.y + b.h)) - y0;
  const round = (v: number) => Math.round(v * 100) / 100;
  return {
    dx: round(Math.min(Math.max(x0 + dx, 0), pageW - width) - x0),
    dy: round(Math.min(Math.max(y0 + dy, 0), pageH - height) - y0),
  };
}

// 요소의 우리말 역할 이름 (계획 4.3). 접근 이름, 속성 패널, 숨긴 요소 목록, 비교 화면이 같은 표를 쓴다
const FIXED_NAMES: Record<string, string> = {
  title: "장 제목", eyebrow: "제목 위 분류", subtitle: "제목 아래 한 문장", bullets: "본문 불릿", points: "요점 목록",
  conclusion: "결론 상자", footnote: "각주", table: "표", text: "강조 밴드 문구", left_card: "왼쪽 카드",
  right_card: "오른쪽 카드", cover_title: "표지 제목", date: "날짜", presenter: "보고자", section_no: "구분 번호",
  section_title: "구분 제목", page_number: "쪽 번호",
};

/** 목적격 조사를 이름의 끝 받침으로 고른다. 한글이 아니면 둘 다 적는다 (D3c-3 리뷰 F21). */
export function withObject(name: string): string {
  const code = name.charCodeAt(name.length - 1) - 0xac00;
  if (code < 0 || code > 11171) return `${name}을(를)`;
  return `${name}${code % 28 ? "을" : "를"}`;
}

export function roleName(key: string, template?: string): string {
  if (template === "cover" && key === "subtitle") return "표지 부제";
  if (FIXED_NAMES[key]) return FIXED_NAMES[key];
  let m = /^card(\d+)$/.exec(key);
  if (m) return `${Number(m[1]) + 1}번 카드`;
  m = /^step(\d+)(_badge|_labels)?$/.exec(key);
  if (m) return `${Number(m[1]) + 1}단계 ${m[2] === "_badge" ? "번호" : m[2] === "_labels" ? "라벨" : "본문"}`;
  m = /^row(\d+)_(category|primary|items)$/.exec(key);
  if (m) return `${Number(m[1]) + 1}번 행 ${{ category: "분류", primary: "대표 항목", items: "나열" }[m[2]]}`;
  return key;
}

// 색 역할의 우리말 이름 (계획 4.3, 계획 리뷰 화면 S22). 화면은 역할 식별자를 보이지 않는다
export const TEXT_COLOR_NAMES: Record<TextColorRole, string> = {
  text: "기본 글자색", accent: "결론 강조색", accent1: "강조색 1", accent2: "강조색 2", danger: "주의(빨강 계열)",
  ok: "정상(초록 계열)", ink: "진한 글자", ink_soft: "옅은 글자", background: "흰 글자",
};
export const FILL_NAMES: Record<FillRole, string> = {
  box_fill: "결론 상자 바탕", ink: "진한 바탕", ink_soft: "옅은 진한 바탕", accent1: "강조색 1", accent2: "강조색 2",
  danger: "주의(빨강 계열)", ok: "정상(초록 계열)", surface1: "옅은 바탕 1", surface2: "옅은 바탕 2",
  surface3: "옅은 바탕 3", surface_danger: "옅은 주의 바탕",
};

/** WCAG 2 상대 휘도 대비. 4.5 아래면 본문 글자로 읽기 어렵다(WCAG 2 AA 본문 기준). */
export function contrastRatio(hexA: string, hexB: string): number {
  const lum = (hex: string) => {
    const c = [0, 2, 4].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
      .map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
  };
  const [a, b] = [lum(hexA.replace("#", "")), lum(hexB.replace("#", ""))].sort((x, y) => y - x);
  return (a + 0.05) / (b + 0.05);
}
