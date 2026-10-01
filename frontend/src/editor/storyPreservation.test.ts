import { comparisonDeck, derivedDeck, storyDeck } from "../test/story";
import { applyTextEdit, reorderChapters } from "./slotOps";
import { applyTemplateSwitch } from "./templateSwitch";
import { editorReducer } from "../state/deckStore";

it.each([storyDeck, comparisonDeck, derivedDeck])("제목, 순서, 템플릿 편집과 undo/redo가 보고 계획을 보존한다 (%#)", (makeDeck) => {
  const deck = makeDeck();
  deck.structure.chapters.push({ id: "c2", topic: "추가 장", conclusion: "", template: "bullet_box", source_refs: [] });
  const title = applyTextEdit(deck, { chapterId: "c1", slot: "title", index: 0 }, "수정 제목");
  const reordered = reorderChapters(title, 0, 1);
  const switched = applyTemplateSwitch(reordered, "c1", "bullet_box").deck;
  for (const changed of [title, reordered, switched]) {
    expect(changed.structure.story_plan).toEqual(deck.structure.story_plan);
  }
  expect(switched.structure.chapters[1]).toMatchObject({ id: "c1", topic: "수정 제목", template: "bullet_box" });
  const edited = editorReducer({ past: [], present: deck, future: [] }, { type: "edit", deck: switched });
  const undone = editorReducer(edited, { type: "undo" });
  expect(undone.present).toEqual(deck);
  expect(editorReducer(undone, { type: "redo" }).present).toEqual(switched);
});
