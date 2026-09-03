import type { Deck } from "../api/client";
import { editorReducer, type EditorState } from "./deckStore";

function deck(title: string): Deck {
  return {
    schema_version: 1,
    meta: { title, report_type: "research", audience: "", presenter: "", preset_overrides: {} },
    structure: { chapters: [] },
    slides: [],
  };
}

const init = (d: Deck): EditorState => ({ past: [], present: d, future: [] });

it("편집은 과거를 쌓고 미래를 비운다", () => {
  let s = init(deck("a"));
  s = editorReducer(s, { type: "edit", deck: deck("b") });
  s = editorReducer(s, { type: "undo" });
  expect(s.present.meta.title).toBe("a");
  s = editorReducer(s, { type: "edit", deck: deck("c") });
  expect(s.future).toHaveLength(0);
});

it("undo와 redo가 왕복한다", () => {
  let s = init(deck("a"));
  s = editorReducer(s, { type: "edit", deck: deck("b") });
  s = editorReducer(s, { type: "undo" });
  s = editorReducer(s, { type: "redo" });
  expect(s.present.meta.title).toBe("b");
});

it("과거는 100개로 제한된다", () => {
  let s = init(deck("0"));
  for (let i = 1; i <= 150; i += 1) s = editorReducer(s, { type: "edit", deck: deck(String(i)) });
  expect(s.past).toHaveLength(100);
});

it("reset은 과거와 미래를 비우고 present를 새 덱으로 교체한다 (충돌 복구용)", () => {
  let s = init(deck("a"));
  s = editorReducer(s, { type: "edit", deck: deck("b") });
  s = editorReducer(s, { type: "undo" });  // past: [a], present: a는 아님(되돌리기로 a), future: [b]
  s = editorReducer(s, { type: "reset", deck: deck("서버") });
  expect(s.present.meta.title).toBe("서버");
  expect(s.past).toHaveLength(0);
  expect(s.future).toHaveLength(0);
});
