import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ExpressionPanel } from './ExpressionPanel';
import { deckWith, deferred } from '../test/fixtures';
import { comparisonDeck } from '../test/story';

it('읽기 전용 선택에서 이모지 강조를 만들고 원래 문구를 보존한다', async () => {
 const digest=vi.fn().mockResolvedValue(new Uint8Array(32).buffer);
 vi.stubGlobal('crypto',{subtle:{digest}});
 const deck=deckWith(['본문']);deck.slides[0].eyebrow='가😀나';const apply=vi.fn();
 render(<ExpressionPanel deck={deck} chapterId="c1" onApply={apply} />);
 const text=screen.getByLabelText('강조 문구 선택') as HTMLTextAreaElement;
 expect(text).toHaveAttribute('readonly');
 fireEvent.select(text,{target:{selectionStart:1,selectionEnd:3}});
 fireEvent.click(screen.getByRole('button',{name:'선택 부분 굵게'}));
 await waitFor(()=>expect(apply).toHaveBeenCalledTimes(1));
 const next=apply.mock.calls[0][0](deck);
 expect(next.slides[0].text_spans[0]).toMatchObject({slot:'eyebrow',start:1,end:2,role:'bold'});
 expect(next.slides[0].eyebrow).toBe('가😀나');vi.unstubAllGlobals();
});

it('늦은 해시가 도착해도 새 입력을 덮어쓰지 않는다', async () => {
 const pending=deferred<ArrayBuffer>();vi.stubGlobal('crypto',{subtle:{digest:vi.fn(()=>pending.promise)}});
 const deck=deckWith(['본문']);deck.slides[0].eyebrow='가나다';const apply=vi.fn();
 const {rerender}=render(<ExpressionPanel deck={deck} chapterId="c1" onApply={apply} />);
 fireEvent.select(screen.getByLabelText('강조 문구 선택'),{target:{selectionStart:0,selectionEnd:2}});
 fireEvent.click(screen.getByRole('button',{name:'선택 부분 강조색'}));
 rerender(<ExpressionPanel deck={{...deck,meta:{...deck.meta,presenter:'새 입력'}}} chapterId="c1" onApply={apply} />);
 await act(async()=>pending.resolve(new Uint8Array(32).buffer));
 expect(apply).not.toHaveBeenCalled();expect(screen.getByRole('alert')).toHaveTextContent('문서가 바뀌');vi.unstubAllGlobals();
});

it('차트 선택은 원래 표를 그대로 유지하고 비교가 없으면 막대 선택을 막는다', () => {
 const deck=comparisonDeck();deck.structure.chapters[0].template='table';deck.slides=[{chapter_id:'c1',eyebrow:'',subtitle:'',slots:{template:'table',columns:['팀','값'],rows:[['A','100']],footnote:''}}];
 const apply=vi.fn();const {rerender}=render(<ExpressionPanel deck={deck} chapterId="c1" onApply={apply} />);
 fireEvent.change(screen.getByLabelText('표시 방식'),{target:{value:'column'}});
 const next=apply.mock.calls[0][0](deck);expect(next.slides[0].chart.kind).toBe('column');expect(next.slides[0].slots).toBe(deck.slides[0].slots);
 rerender(<ExpressionPanel deck={{...deck,structure:{...deck.structure,story_plan:null}}} chapterId="c1" onApply={apply} />);
 expect(screen.getByRole('option',{name:'세로 막대 차트'})).toBeDisabled();
});

it('다른 편집 경로에서 문구가 바뀌면 이전 선택 범위로 강조하지 않는다', () => {
 const deck=deckWith(['본문']);deck.slides[0].eyebrow='이전 문구';const apply=vi.fn();
 const {rerender}=render(<ExpressionPanel deck={deck} chapterId="c1" onApply={apply} />);
 fireEvent.select(screen.getByLabelText('강조 문구 선택'),{target:{selectionStart:0,selectionEnd:2}});
 expect(screen.getByRole('button',{name:'선택 부분 굵게'})).not.toBeDisabled();
 rerender(<ExpressionPanel deck={{...deck,slides:[{...deck.slides[0],eyebrow:'새 문구'}]}} chapterId="c1" onApply={apply} />);
 expect(screen.getByRole('button',{name:'선택 부분 굵게'})).toBeDisabled();expect(apply).not.toHaveBeenCalled();
});

it('표시 중인 차트의 비교 선택은 같은 방식으로 새 비교를 바로 적용한다', () => {
 const deck=comparisonDeck();deck.structure.chapters[0].template='table';
 deck.structure.story_plan!.comparisons.push({...deck.structure.story_plan!.comparisons[0],id:'cmp2'});
 deck.slides=[{chapter_id:'c1',eyebrow:'',subtitle:'',slots:{template:'table',columns:['팀','값'],rows:[['A','100']],footnote:''},chart:{rule_version:'comparison-chart-v1',comparison_id:'cmp1',kind:'bar'}}];
 const apply=vi.fn();render(<ExpressionPanel deck={deck} chapterId="c1" onApply={apply} />);
 fireEvent.change(screen.getByLabelText('차트 비교'),{target:{value:'cmp2'}});
 const next=apply.mock.calls[0][0](deck);expect(next.slides[0].chart).toMatchObject({kind:'bar',comparison_id:'cmp2'});expect(next.slides[0].slots).toBe(deck.slides[0].slots);
});
