import type { Deck } from "../api/client";
import {
  addBullet, applyTextEdit, deleteTableRow, mergeTableColumns, removeBullet, reorderChapters,
} from "./slotOps";

function bulletDeck(): Deck {
  return {
    schema_version: 1,
    meta: { title: "t", report_type: "research", audience: "", preset_overrides: {} },
    structure: { chapters: [
      { id: "c1", topic: "주제", conclusion: "", template: "bullet_box", source_refs: [] }] },
    slides: [{ chapter_id: "c1", slots: {
      template: "bullet_box",
      bullets: [{ text: "하나", level: 0 }, { text: "둘", level: 1 }],
      conclusion: "결론", footnote: "" } }],
  };
}

it("title 수정은 구조안의 topic을 고친다", () => {
  const next = applyTextEdit(bulletDeck(), { chapterId: "c1", slot: "title", index: 0 }, "새 주제");
  expect(next.structure.chapters[0].topic).toBe("새 주제");
});

it("불릿 문단은 index로 고친다", () => {
  const next = applyTextEdit(bulletDeck(), { chapterId: "c1", slot: "bullets", index: 1 }, "고침");
  const slots = next.slides[0].slots;
  expect(slots.template === "bullet_box" && slots.bullets?.[1].text).toBe("고침");
  expect(slots.template === "bullet_box" && slots.bullets?.[0].text).toBe("하나");
});

it("표 칸은 row와 col로, 머리글은 row -1로 고친다", () => {
  const deck: Deck = {
    ...bulletDeck(),
    structure: { chapters: [
      { id: "c1", topic: "주제", conclusion: "", template: "table", source_refs: [] }] },
    slides: [{ chapter_id: "c1", slots: {
      template: "table", columns: ["구분", "내용"], rows: [["A", "값"]], footnote: "" } }],
  };
  let next = applyTextEdit(deck, { chapterId: "c1", slot: "table", row: 0, col: 1 }, "새 값");
  let slots = next.slides[0].slots;
  expect(slots.template === "table" && slots.rows[0][1]).toBe("새 값");
  next = applyTextEdit(deck, { chapterId: "c1", slot: "table", row: -1, col: 0 }, "새 머리글");
  slots = next.slides[0].slots;
  expect(slots.template === "table" && slots.columns[0]).toBe("새 머리글");
  // 붙여넣기로 섞인 개행은 공백으로 흡수한다 (표 칸 개행 금지 검증과 정합)
  next = applyTextEdit(deck, { chapterId: "c1", slot: "table", row: 0, col: 1 }, "줄1\n줄2");
  slots = next.slides[0].slots;
  expect(slots.template === "table" && slots.rows[0][1]).toBe("줄1 줄2");
});

it("카드의 index 0은 소제목, 이후는 불릿이다", () => {
  const deck: Deck = {
    ...bulletDeck(),
    structure: { chapters: [
      { id: "c1", topic: "주제", conclusion: "", template: "compare2", source_refs: [] }] },
    slides: [{ chapter_id: "c1", slots: {
      template: "compare2", conclusion: "결",
      left: { heading: "왼쪽", bullets: [{ text: "가", level: 0 }] },
      right: { heading: "오른쪽", bullets: [] } } }],
  };
  let next = applyTextEdit(deck, { chapterId: "c1", slot: "left_card", index: 0 }, "새 소제목");
  let slots = next.slides[0].slots;
  expect(slots.template === "compare2" && slots.left.heading).toBe("새 소제목");
  next = applyTextEdit(deck, { chapterId: "c1", slot: "left_card", index: 1 }, "새 불릿");
  slots = next.slides[0].slots;
  expect(slots.template === "compare2" && slots.left.bullets?.[0].text).toBe("새 불릿");
});

it("불릿 추가와 삭제", () => {
  let next = addBullet(bulletDeck(), "c1", "bullets");
  let slots = next.slides[0].slots;
  expect(slots.template === "bullet_box" && slots.bullets).toHaveLength(3);
  next = removeBullet(next, "c1", "bullets", 0);
  slots = next.slides[0].slots;
  expect(slots.template === "bullet_box" && slots.bullets?.[0].text).toBe("둘");
});

it("표 행 삭제와 열 병합", () => {
  const deck: Deck = {
    ...bulletDeck(),
    structure: { chapters: [
      { id: "c1", topic: "주제", conclusion: "", template: "table", source_refs: [] }] },
    slides: [{ chapter_id: "c1", slots: {
      template: "table", columns: ["구분", "내용", "비고"],
      rows: [["A", "값1", "메모1"], ["B", "값2", "메모2"]], footnote: "" } }],
  };
  let next = deleteTableRow(deck, "c1", 0);
  let slots = next.slides[0].slots;
  expect(slots.template === "table" && slots.rows).toEqual([["B", "값2", "메모2"]]);
  next = mergeTableColumns(deck, "c1", 1);  // "내용"과 "비고" 병합
  slots = next.slides[0].slots;
  expect(slots.template === "table" && slots.columns).toEqual(["구분", "내용 비고"]);
  expect(slots.template === "table" && slots.rows[0]).toEqual(["A", "값1 메모1"]);
});

it("장 순서 이동", () => {
  const deck = bulletDeck();
  deck.structure.chapters = [
    { id: "c1", topic: "가", conclusion: "", template: "bullet_box", source_refs: [] },
    { id: "c2", topic: "나", conclusion: "", template: "bullet_box", source_refs: [] },
    { id: "c3", topic: "다", conclusion: "", template: "bullet_box", source_refs: [] },
  ];
  const next = reorderChapters(deck, 0, 2);
  expect(next.structure.chapters.map((c) => c.topic)).toEqual(["나", "다", "가"]);
});
