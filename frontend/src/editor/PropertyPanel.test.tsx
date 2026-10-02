import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Deck } from "../api/client";
import { PropertyPanel } from "./PropertyPanel";

const deck: Deck = {
  schema_version: 1,
  meta: { title: "t", report_type: "research", audience: "", presenter: "", preset_overrides: {} },
  structure: { chapters: [
    { id: "c1", topic: "주제", conclusion: "", template: "bullet_box", source_refs: [] }] },
  slides: [{ chapter_id: "c1", eyebrow: "", subtitle: "", slots: {
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

it("전환 드롭다운은 편집 가능한 신규 4종을 제공한다", () => {
  // DB-6 속성 편집을 제공한 신규 템플릿도 선택할 수 있다.
  render(<PropertyPanel deck={deck} chapterId="c1" onApply={() => {}} />);
  const select = screen.getByLabelText("템플릿") as HTMLSelectElement;
  const values = Array.from(select.options).map((o) => o.value);
  expect(values).toEqual(expect.arrayContaining(["callout", "cards", "process", "matrix"]));
  expect(values).toHaveLength(10);
});

it('공통 빈 아이브로우와 부제를 속성 패널에서 추가할 수 있다', async()=>{
 const onApply=vi.fn();render(<PropertyPanel deck={deck} chapterId='c1' onApply={onApply}/>);
 await userEvent.type(screen.getByLabelText('아이브로우'),'새');
 const next=onApply.mock.calls[0][0](deck);expect(next.slides[0].eyebrow).toBe('새');
});
it('손실 전환 취소는 적용도 전환 요청도 하지 않는다',async()=>{
 const confirm=vi.spyOn(window,'confirm').mockReturnValue(false),onApply=vi.fn(),onSwitchTemplate=vi.fn();
 render(<PropertyPanel deck={deck} chapterId='c1' onApply={onApply} onSwitchTemplate={onSwitchTemplate}/>);
 await userEvent.selectOptions(screen.getByLabelText('템플릿'),'cards');
 expect(confirm).toHaveBeenCalled();expect(onApply).not.toHaveBeenCalled();expect(onSwitchTemplate).not.toHaveBeenCalled();confirm.mockRestore();
});
it('카드의 빈 선택 필드와 강조, 불릿 추가를 편집할 수 있다',async()=>{
 const d:Deck={...deck,structure:{chapters:[{...deck.structure.chapters[0],template:'cards'}]},slides:[{...deck.slides[0],slots:{template:'cards',cards:[{heading:'A',badge:'',tail:'',emphasis:false,bullets:[]},{heading:'B',badge:'',tail:'',emphasis:false,bullets:[]}]}}]};
 const onApply=vi.fn();render(<PropertyPanel deck={d} chapterId='c1' onApply={onApply}/>);
 expect(screen.getByLabelText('카드 1 삭제')).toBeDisabled();
 await userEvent.type(screen.getByLabelText('1번 카드 배지'),'새');
 let s=onApply.mock.calls.at(-1)![0](d).slides[0].slots;expect(s.cards[0].badge).toBe('새');
 await userEvent.click(screen.getByLabelText('1번 카드 강조'));s=onApply.mock.calls.at(-1)![0](d).slides[0].slots;expect(s.cards[0].emphasis).toBe(true);
 await userEvent.click(screen.getByText('1번 카드 불릿 추가'));s=onApply.mock.calls.at(-1)![0](d).slides[0].slots;expect(s.cards[0].bullets).toHaveLength(1);
});
it('단계 보조 라벨 상한은 2개이며 빈 부제 입력을 제공한다',()=>{
 const d:Deck={...deck,structure:{chapters:[{...deck.structure.chapters[0],template:'process'}]},slides:[{...deck.slides[0],slots:{template:'process',steps:[{heading:'A',subtitle:'',notes:['x','y']},{heading:'B',subtitle:'',notes:[]},{heading:'C',subtitle:'',notes:[]}]}}]};
 render(<PropertyPanel deck={d} chapterId='c1' onApply={vi.fn()}/>);expect(screen.getByLabelText('1번 단계 부제')).toHaveValue('');expect(screen.getByText('1번 단계 보조 라벨 추가')).toBeDisabled();
});
