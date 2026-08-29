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
  return updateSlide(deck, chapterId, (slots) => {
    switch (slots.template) {
      case "cover":
        if (slot === "cover_title") return { ...slots, title: text };
        if (slot === "subtitle") return { ...slots, subtitle: text };
        if (slot === "date") return { ...slots, date: text };
        if (slot === "audience") return { ...slots, audience: text };
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
