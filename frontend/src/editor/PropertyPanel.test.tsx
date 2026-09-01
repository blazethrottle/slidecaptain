import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Deck } from "../api/client";
import { PropertyPanel } from "./PropertyPanel";

const deck: Deck = {
  schema_version: 1,
  meta: { title: "t", report_type: "research", audience: "", presenter: "", preset_overrides: {} },
  structure: { chapters: [
    { id: "c1", topic: "주제", conclusion: "", template: "bullet_box", source_refs: [] }] },
  slides: [{ chapter_id: "c1", slots: {
    template: "bullet_box", bullets: [{ text: "하나", level: 0 }], conclusion: "결론", footnote: "" } }],
};

it("장 주제를 고치면 onApply로 반영된다", async () => {
  const onApply = vi.fn();
  render(<PropertyPanel deck={deck} chapterId="c1" onApply={onApply} />);
  const input = screen.getByLabelText("장 주제");
  await userEvent.clear(input);
  await userEvent.type(input, "새 주제");
  await userEvent.tab();  // blur 확정
  expect(onApply).toHaveBeenCalled();
  const edit = onApply.mock.calls[0][0] as (d: Deck) => Deck;
  expect(edit(deck).structure.chapters[0].topic).toBe("새 주제");
});

it("불릿 추가 버튼이 동작한다", async () => {
  const onApply = vi.fn();
  render(<PropertyPanel deck={deck} chapterId="c1" onApply={onApply} />);
  await userEvent.click(screen.getByText("불릿 추가"));
  const edit = onApply.mock.calls[0][0] as (d: Deck) => Deck;
  const slots = edit(deck).slides[0].slots;
  expect(slots.template === "bullet_box" && slots.bullets).toHaveLength(2);
});

it("장 주제와 템플릿이 각각 한 줄을 차지한다", () => {
  render(<PropertyPanel deck={deck} chapterId="c1" onApply={() => {}} />);
  const topic = screen.getByLabelText("장 주제").closest(".field");
  const template = screen.getByLabelText("템플릿").closest(".field");
  expect(topic).not.toBeNull();
  expect(template).not.toBeNull();
  expect(topic).not.toBe(template);
});
