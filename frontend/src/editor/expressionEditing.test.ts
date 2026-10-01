import { deckWith, deferred } from '../test/fixtures';
import { comparisonDeck } from '../test/story';
import { applyTextEdit } from './slotOps';
import { applyTemplateSwitch } from './templateSwitch';
import { codePointRange, prepareTextSpan, pruneChangedSpans, setChart, spanText, type TextSpan } from './expressionEditing';

const span = (slot: TextSpan['slot'], index: number | null = null): TextSpan => ({ slot, index, start: 0, end: 1, role: 'bold', text_sha256: 'a'.repeat(64) });

it('UTF16 선택을 코드포인트로 바꾸며 이모지의 중간을 허용하지 않는다', () => {
 expect(codePointRange('가😀나',1,3)).toEqual({start:1,end:2});
 expect(codePointRange('가😀나',2,3)).toBeNull();
 expect(codePointRange('가😀나',1,2)).toBeNull();
 expect(codePointRange('가😀나',0,4)).toEqual({start:0,end:3});
});

it('해시를 기다리는 동안 변경된 문서에는 강조를 적용하지 않는다', async () => {
 const deck=deckWith(['가😀나']),pending=deferred<string>();let current=deck;
 const result=prepareTextSpan(deck,'c1',{slot:'bullets',index:0},{start:1,end:3},'accent',()=>current,()=>pending.promise);
 current={...deck,meta:{...deck.meta,presenter:'새 입력'}};
 const rejected=expect(result).rejects.toThrow('문서가 바뀌');pending.resolve('b'.repeat(64));await rejected;
 expect(deck.slides[0].text_spans).toBeUndefined();
});

it('범위 겹침을 거절하고 붙어있는 코드포인트 범위는 보존한다', async () => {
 const deck=deckWith(['가😀나']);deck.slides[0].text_spans=[{...span('bullets',0),start:1,end:2}];
 await expect(prepareTextSpan(deck,'c1',{slot:'bullets',index:0},{start:1,end:3},'bold',()=>deck,async()=> 'a'.repeat(64))).rejects.toThrow('겹칩니다');
 const next=await prepareTextSpan(deck,'c1',{slot:'bullets',index:0},{start:3,end:4},'bold',()=>deck,async()=> 'a'.repeat(64));
 expect(next.start).toBe(2);expect(next.end).toBe(3);
});

it('수정한 텍스트 칸의 강조만 지우고 다른 강조와 원본은 보존한다', () => {
 const deck=deckWith(['처음','다음']);deck.slides[0].eyebrow='표제';deck.slides[0].text_spans=[span('bullets',0),span('bullets',1),span('eyebrow')];
 const edited=applyTextEdit(deck,{chapterId:'c1',slot:'bullets',index:0},'수정');
 const next=pruneChangedSpans(deck,edited);
 expect(next.slides[0].text_spans).toEqual([span('bullets',1),span('eyebrow')]);
 expect(deck.slides[0].text_spans).toHaveLength(3);
 const style={...deck,slides:[{...deck.slides[0],subtitle:'다른 칸'}]};
 expect(pruneChangedSpans(deck,style)).toBe(style);
 expect(spanText(deck.slides[0],{slot:'bullets',index:2})).toBeNull();
});

it('차트는 해당 장에 연결된 비교를 명시적으로 고르며 표와 계획을 보존한다', () => {
 const deck=comparisonDeck();deck.structure.chapters[0].template='table';
 deck.slides=[{chapter_id:'c1',eyebrow:'',subtitle:'',slots:{template:'table',columns:['A','B'],rows:[['100','120']],footnote:'각주'}}];
 const table=deck.slides[0].slots,plan=deck.structure.story_plan;
 const next=setChart(deck,'c1','cmp1','bar');
 expect(next.slides[0].chart).toEqual({rule_version:'comparison-chart-v1',comparison_id:'cmp1',kind:'bar'});
 expect(next.slides[0].slots).toBe(table);expect(next.structure.story_plan).toBe(plan);
 expect(setChart(deck,'c1','unknown','column')).toBe(deck);
 expect(setChart(next,'c1','cmp1','table').slides[0].chart).toBeNull();
 const disconnected={...deck,structure:{...deck.structure,story_plan:{...plan!,chapters:[{chapter_id:'c1',role:'answer' as const,claim_ids:[]}]}}};
 expect(setChart(disconnected,'c1','cmp1','bar')).toBe(disconnected);
});

it('템플릿 변경은 차트와 강조의 소실을 정확히 알리며 같은 템플릿은 보존한다', () => {
 const deck=deckWith(['문구']);deck.slides[0].chart={rule_version:'comparison-chart-v1',comparison_id:'cmp1',kind:'bar'};deck.slides[0].text_spans=[span('bullets',0)];
 const unchanged=applyTemplateSwitch(deck,'c1','bullet_box');expect(unchanged.deck).toBe(deck);expect(unchanged.dropped).toEqual([]);
 const next=applyTemplateSwitch(deck,'c1','summary');
 expect(next.dropped).toContain('차트 표시 (가로 막대, 비교 cmp1)');expect(next.dropped).toContain('부분 강조 1개');
 expect(next.deck.slides[0].chart).toBeNull();expect(next.deck.slides[0].text_spans).toEqual([]);
 expect(deck.slides[0].text_spans).toHaveLength(1);
});


it('서버와 같은 장별 강조 100개 상한을 후보 생성 전에 확인한다',async()=>{
 const deck=deckWith(['가'.repeat(101)]);deck.slides[0].text_spans=Array.from({length:100},(_,i)=>({...span('bullets',0),start:i,end:i+1}));
 const hash=vi.fn().mockResolvedValue('a'.repeat(64));
 await expect(prepareTextSpan(deck,'c1',{slot:'bullets',index:0},{start:100,end:101},'bold',()=>deck,hash)).rejects.toThrow('최대 100개');
 expect(hash).not.toHaveBeenCalled();
});
