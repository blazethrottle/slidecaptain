import { fireEvent, render, screen } from "@testing-library/react";
import type { Deck } from "../api/client";
import { ChapterList } from "./ChapterList";

const deck: Deck = {
  schema_version: 1,
  meta: { title: "t", report_type: "research", audience: "", preset_overrides: {} },
  structure: { chapters: [
    { id: "c1", topic: "가", conclusion: "", template: "bullet_box", source_refs: [] },
    { id: "c2", topic: "나", conclusion: "", template: "bullet_box", source_refs: [] },
  ] },
  slides: [],
};

it("드래그로 순서를 바꾼다", () => {
  const onReorder = vi.fn();
  render(<ChapterList deck={deck} plan={null} selected={null}
    onSelect={() => {}} onReorder={onReorder} />);
  const items = screen.getAllByRole("listitem");
  fireEvent.dragStart(items[0]);
  fireEvent.dragOver(items[1]);
  fireEvent.drop(items[1]);
  expect(onReorder).toHaveBeenCalledWith(0, 1);
});

it("장 목록은 주제와 템플릿을 별도 줄로 보여준다", () => {
  render(<ChapterList deck={deck} plan={null} selected={null} onSelect={() => {}} />);
  const template = screen.getAllByText("템플릿: 불릿 + 강조박스")[0];
  expect(template).toHaveClass("chapter-template");
  expect(template.previousElementSibling).toHaveTextContent("1. 가");
});
