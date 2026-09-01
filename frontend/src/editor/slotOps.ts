import type { Deck, Slots } from "../api/client";
import type { TextRef } from "./Preview";

function updateSlide(deck: Deck, chapterId: string, f: (s: Slots) => Slots): Deck {
  return {
    ...deck,
    slides: deck.slides.map((s) => (s.chapter_id === chapterId ? { ...s, slots: f(s.slots) } : s)),
  };
}

export function applyTextEdit(deck: Deck, ref: TextRef, text: string): Deck {
  const { chapterId, slot } = ref;
  if (slot === "title") {
    return {
      ...deck,
      structure: {
        chapters: deck.structure.chapters.map((c) =>
          c.id === chapterId ? { ...c, topic: text } : c),
      },
    };
  }
  if (slot === "presenter") {
    // 표지의 보고자는 슬롯이 아니라 메타에 있다 (장 제목이 구조안에 있는 것과 같다). 2026-09-01
    return { ...deck, meta: { ...deck.meta, presenter: text } };
  }
  return updateSlide(deck, chapterId, (slots) => {
    switch (slots.template) {
      case "cover":
        if (slot === "cover_title") return { ...slots, title: text };
        if (slot === "subtitle") return { ...slots, subtitle: text };
        if (slot === "date") return { ...slots, date: text };
        return slots;
      case "divider":
        if (slot === "section_no") return { ...slots, section_no: text };
        if (slot === "section_title") return { ...slots, section_title: text };
        return slots;
      case "summary":
        if (slot === "conclusion") return { ...slots, conclusion: text };
        if (slot === "points") {
          return { ...slots, points: (slots.points ?? []).map((b, i) =>
            i === ref.index ? { ...b, text } : b) };
        }
        return slots;
      case "bullet_box":
        if (slot === "conclusion") return { ...slots, conclusion: text };
        if (slot === "footnote") return { ...slots, footnote: text };
        if (slot === "bullets") {
          return { ...slots, bullets: (slots.bullets ?? []).map((b, i) =>
            i === ref.index ? { ...b, text } : b) };
        }
        return slots;
      case "table": {
        if (slot === "footnote") return { ...slots, footnote: text };
        if (slot === "table") {
          // 표 칸 개행은 덱 검증이 거부한다: 붙여넣기로 섞인 개행을 공백으로 흡수한다 (단계 3 결정 8과 정합)
          const cell = text.replace(/[\r\n]+/g, " ");
          if (ref.row === -1) {
            return { ...slots, columns: slots.columns.map((c, j) => (j === ref.col ? cell : c)) };
          }
          return { ...slots, rows: slots.rows.map((r, i) =>
            i === ref.row ? r.map((c, j) => (j === ref.col ? cell : c)) : r) };
        }
        return slots;
      }
      case "compare2": {
        if (slot === "conclusion") return { ...slots, conclusion: text };
        const editCard = (card: (typeof slots)["left"]) =>
          (ref.index ?? 0) === 0
            ? { ...card, heading: text }
            : { ...card, bullets: (card.bullets ?? []).map((b, i) =>
                i === (ref.index ?? 0) - 1 ? { ...b, text } : b) };
        if (slot === "left_card") return { ...slots, left: editCard(slots.left) };
        if (slot === "right_card") return { ...slots, right: editCard(slots.right) };
        return slots;
      }
    }
    return slots;
  });
}

type BulletSlot = "bullets" | "points" | "left_card" | "right_card";

export function addBullet(deck: Deck, chapterId: string, slot: BulletSlot): Deck {
  return updateSlide(deck, chapterId, (slots) => {
    const item = { text: "새 항목", level: 0 as const };
    if (slots.template === "bullet_box" && slot === "bullets") {
      return { ...slots, bullets: [...(slots.bullets ?? []), item] };
    }
    if (slots.template === "summary" && slot === "points") {
      return { ...slots, points: [...(slots.points ?? []), item] };
    }
    if (slots.template === "compare2" && (slot === "left_card" || slot === "right_card")) {
      const key = slot === "left_card" ? "left" : "right";
      const card = slots[key];
      return { ...slots, [key]: { ...card, bullets: [...(card.bullets ?? []), item] } };
    }
    return slots;
  });
}

export function removeBullet(deck: Deck, chapterId: string, slot: BulletSlot, index: number): Deck {
  return updateSlide(deck, chapterId, (slots) => {
    if (slots.template === "bullet_box" && slot === "bullets") {
      return { ...slots, bullets: (slots.bullets ?? []).filter((_, i) => i !== index) };
    }
    if (slots.template === "summary" && slot === "points") {
      return { ...slots, points: (slots.points ?? []).filter((_, i) => i !== index) };
    }
    if (slots.template === "compare2" && (slot === "left_card" || slot === "right_card")) {
      const key = slot === "left_card" ? "left" : "right";
      const card = slots[key];
      return { ...slots, [key]: { ...card, bullets: (card.bullets ?? []).filter((_, i) => i !== index) } };
    }
    return slots;
  });
}

export function deleteTableRow(deck: Deck, chapterId: string, rowIndex: number): Deck {
  return updateSlide(deck, chapterId, (slots) =>
    slots.template === "table"
      ? { ...slots, rows: slots.rows.filter((_, i) => i !== rowIndex) }
      : slots);
}

export function mergeTableColumns(deck: Deck, chapterId: string, colIndex: number): Deck {
  return updateSlide(deck, chapterId, (slots) => {
    if (slots.template !== "table" || colIndex < 0 || colIndex >= slots.columns.length - 1) {
      return slots;
    }
    const join = (a: string, b: string) => [a, b].filter(Boolean).join(" ");
    return {
      ...slots,
      columns: slots.columns.flatMap((c, j) =>
        j === colIndex ? [join(c, slots.columns[j + 1])] : j === colIndex + 1 ? [] : [c]),
      rows: slots.rows.map((r) => r.flatMap((c, j) =>
        j === colIndex ? [join(c, r[j + 1])] : j === colIndex + 1 ? [] : [c])),
    };
  });
}

export function reorderChapters(deck: Deck, from: number, to: number): Deck {
  const chapters = [...deck.structure.chapters];
  const [moved] = chapters.splice(from, 1);
  chapters.splice(to, 0, moved);
  return { ...deck, structure: { chapters } };
}

export function setPresetOverride(
  deck: Deck, group: string, key: string, value: number | string,
): Deck {
  const overrides = { ...(deck.meta.preset_overrides ?? {}) } as Record<string, unknown>;
  const groupValues = { ...((overrides[group] as Record<string, unknown>) ?? {}) };
  groupValues[key] = value;
  overrides[group] = groupValues;
  return { ...deck, meta: { ...deck.meta, preset_overrides: overrides } };
}
