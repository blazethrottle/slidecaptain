import { act, renderHook } from '@testing-library/react';
import { api } from '../api/client';
import { useDeckEditor } from './useDeckEditor';
import { deckWith, planWith } from '../test/fixtures';
import { applyTextEdit } from '../editor/slotOps';

vi.mock('../api/client',async(importOriginal)=>{
 const mod=await importOriginal<typeof import('../api/client')>();
 return {...mod,api:{...mod.api,measure:vi.fn(),putDeck:vi.fn()}};
});

it('apply만 변경 칸의 강조를 지우며 undo와 redo는 문구·강조의 해당 상태를 복원한다', async()=>{
 vi.mocked(api.measure).mockResolvedValue(planWith(['문구']));vi.mocked(api.putDeck).mockResolvedValue({ok:true});
 const initial=deckWith(['문구']);initial.slides[0].eyebrow='표제';
 initial.slides[0].text_spans=[{slot:'bullets',index:0,start:0,end:1,role:'bold',text_sha256:'a'.repeat(64)},{slot:'eyebrow',index:null,start:0,end:1,role:'accent',text_sha256:'b'.repeat(64)}];
 const {result}=renderHook(()=>useDeckEditor('p',initial,()=>{}, {measureMs:100000,saveMs:100000}));
 await act(async()=>result.current.apply(d=>applyTextEdit(d,{chapterId:'c1',slot:'bullets',index:0},'수정')));
 const changed=result.current.deck;expect(changed.slides[0].text_spans).toHaveLength(1);expect(changed.slides[0].text_spans![0].slot).toBe('eyebrow');
 await act(async()=>result.current.undo());expect(result.current.deck).toBe(initial);expect(result.current.deck.slides[0].text_spans).toHaveLength(2);
 await act(async()=>result.current.redo());expect(result.current.deck).toBe(changed);expect(result.current.deck.slides[0].text_spans).toHaveLength(1);
});
