import type { Deck, Slots } from '../api/client';
import { changeTemplateItems, editTemplateSlots, setSlideField } from './slotOps';
const base = (slots: Slots): Deck => ({schema_version:1, meta:{title:'t',report_type:'research',audience:'',presenter:'',preset_overrides:{}}, structure:{chapters:[{id:'c',topic:'t',template:slots.template,source_refs:[],conclusion:''}]}, slides:[{chapter_id:'c',eyebrow:'',subtitle:'',slots}]});
it.each(['cards','process','matrix'] as const)('항목 %s의 최소/최대 개수를 보존한다', template => {
 const n = template==='cards'?2:3;
 const slots: Slots = template==='cards'?{template,cards:Array.from({length:n},()=>({heading:'',badge:'',tail:'',emphasis:false,bullets:[]}))}:template==='process'?{template,steps:Array.from({length:n},()=>({heading:'',subtitle:'',notes:[]}))}:{template,rows:Array.from({length:n},()=>({category:'',primary:'',items:[]}))};
 let d=base(slots);
 const count=(d:Deck)=>{const s=d.slides[0].slots; return s.template==='cards'?s.cards.length:s.template==='process'?s.steps.length:s.template==='matrix'?s.rows.length:0};
 expect(count(changeTemplateItems(d,'c','remove',0))).toBe(n);
 for(let i=0;i<10;i++) d=changeTemplateItems(d,'c','add');
 expect(count(d)).toBe(template==='cards'?4:6);
 expect(count(changeTemplateItems(d,'c','remove',-1))).toBe(count(d));
});
it('빈 선택 필드와 강조를 추가하며 다른 데이터는 보존한다',()=>{
 const d=base({template:'cards',cards:[{heading:'A',badge:'',tail:'',emphasis:false,bullets:[]},{heading:'B',badge:'',tail:'',emphasis:false,bullets:[]}]});
 const next=editTemplateSlots(d,'c',s=>s.template==='cards'?{...s,cards:s.cards.map((c,i)=>i===0?{...c,badge:'새 배지',emphasis:true}:c)}:s);
 expect(next.slides[0].slots.template==='cards'&&next.slides[0].slots.cards[0].badge).toBe('새 배지');
 expect(setSlideField(d,'c','subtitle','부제').slides[0].subtitle).toBe('부제');
 expect(d.slides[0].subtitle).toBe('');
});

import { applyTemplateSwitch, switchTemplate } from './templateSwitch';
const allSlots: Slots[] = [
 {template:'cover',title:'표지',subtitle:'부제',date:'날짜'},
 {template:'summary',conclusion:'결론',points:[{text:'본문',level:0}]},
 {template:'bullet_box',conclusion:'결론',footnote:'각주',bullets:[{text:'본문',level:1}]},
 {template:'table',columns:['열'],rows:[['셀']],footnote:'각주'},
 {template:'compare2',conclusion:'결론',left:{heading:'왼쪽',bullets:[{text:'A',level:0}]},right:{heading:'오른쪽',bullets:[{text:'B',level:1}]}},
 {template:'divider',section_no:'번호',section_title:'제목'},
 {template:'callout',text:'밴드',tone:'danger'},
 {template:'cards',cards:[{heading:'A',badge:'배지',tail:'꼬리',emphasis:true,bullets:[{text:'본문',level:1}]},{heading:'B',badge:'',tail:'',emphasis:false,bullets:[]}]},
 {template:'process',steps:[{heading:'A',subtitle:'부제',notes:['라벨']},{heading:'B',subtitle:'',notes:[]},{heading:'C',subtitle:'',notes:[]}]},
 {template:'matrix',rows:[{category:'A',primary:'대표',items:['항목']},{category:'B',primary:'',items:[]},{category:'C',primary:'',items:[]}]},
];
it.each(allSlots)('$template에서 모든 템플릿으로 전환해 개수·공통 정보·원본을 보존한다', from=>{
 for(const to of allSlots){
  const d=base(from);d.slides[0].eyebrow='표제';d.slides[0].subtitle='페이지부제';
  const original=JSON.stringify(d);
  const result=applyTemplateSwitch(d,'c',to.template);const s=result.deck.slides[0].slots;
  expect(s.template).toBe(to.template);expect(result.deck.slides[0].eyebrow).toBe('표제');expect(result.deck.slides[0].subtitle).toBe('페이지부제');
  expect(JSON.stringify(d)).toBe(original);
  if(s.template==='cards')expect(s.cards.length).toBeGreaterThanOrEqual(2);
  if(s.template==='process')expect(s.steps.length).toBeGreaterThanOrEqual(3);
  if(s.template==='matrix')expect(s.rows.length).toBeGreaterThanOrEqual(3);
  if(from.template===to.template)expect(switchTemplate(from,to.template).slots).toBe(from);
 }
});
