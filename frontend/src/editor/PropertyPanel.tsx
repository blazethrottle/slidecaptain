import { useEffect, useState } from "react";
import type { Deck, Slots, TemplateName } from "../api/client";
import { SELECTABLE_TEMPLATES, TEMPLATE_LABELS } from "./labels";
import {
  addBullet, applyTextEdit, deleteTableRow, mergeTableColumns, removeBullet,
  editTemplateSlots, changeTemplateItems, setSlideField,
} from "./slotOps";
import { applyTemplateSwitch } from "./templateSwitch";
import { ExpressionPanel } from "./ExpressionPanel";

export function PropertyPanel({ deck, chapterId, onApply, onEditDiagram, diagramDisabled, onSwitchTemplate }: {
  deck: Deck;
  chapterId: string;
  onApply: (edit: (d: Deck) => Deck) => void;
  onEditDiagram?: () => void;
  diagramDisabled?: boolean;
  onSwitchTemplate?: (chapterId: string, to: TemplateName, base: Deck) => void;
}) {
  const chapter = deck.structure.chapters.find((c) => c.id === chapterId);
  const slide = deck.slides.find((s) => s.chapter_id === chapterId);
  const [topic, setTopic] = useState(chapter?.topic ?? "");
  useEffect(() => setTopic(chapter?.topic ?? ""), [chapterId, chapter?.topic]);
  if (!chapter) return null;
  if (chapter.template === "diagram") {
    return <section className="property-panel">
      <h3>{TEMPLATE_LABELS.diagram}</h3>
      <p>{chapter.topic}</p>
      <p>도식 미리보기는 읽기 전용입니다. 내용과 관계는 작성 창에서 수정할 수 있습니다.</p>
      {onEditDiagram && <button disabled={diagramDisabled} onClick={onEditDiagram}>도식 내용 수정</button>}
      <p className="hint">아직 검수하지 않은 초안입니다.</p>
    </section>;
  }
  const slots = slide?.slots;

  const commitTopic = () => {
    if (topic !== chapter.topic) {
      onApply((d) => applyTextEdit(d, { chapterId, slot: "title", index: 0 }, topic));
    }
  };

  const bulletSection = (label: string, slot: "bullets" | "points" | "left_card" | "right_card",
    items: { text: string }[]) => (
    <section key={slot}>
      <h4>{label}</h4>
      <ul>
        {items.map((b, i) => (
          <li key={i}>
            <span>{b.text}</span>
            <button aria-label={`${label} ${i + 1} 삭제`}
              onClick={() => onApply((d) => removeBullet(d, chapterId, slot, i))}>삭제</button>
          </li>
        ))}
      </ul>
      <button onClick={() => onApply((d) => addBullet(d, chapterId, slot))}>
        {slot === "bullets" || slot === "points" ? "불릿 추가" : `${label} 불릿 추가`}
      </button>
    </section>
  );

  const editSlots = (edit: (s: Slots) => Slots) => onApply(d => editTemplateSlots(d, chapterId, edit));
  const textField = (label: string, value: string, change: (text: string) => void) => <label className="field">{label}
    <input aria-label={label} value={value} onChange={e => change(e.target.value)} />
  </label>;
  const textList = (label: string, items: string[], change: (items: string[]) => void, max = Infinity) => <section>
    <h4>{label}</h4>{items.map((value, i) => <div key={i}>
      {textField(`${label} ${i + 1}`, value, text => change(items.map((v,j) => j === i ? text : v)))}
      <button aria-label={`${label} ${i + 1} 삭제`} onClick={() => change(items.filter((_,j) => j !== i))}>삭제</button>
    </div>)}
    <button disabled={items.length >= max} onClick={() => change([...items, ""])}>{label} 추가</button>
  </section>;
  const itemControls = (label: string, count: number, min: number, index: number) => <button
    disabled={count <= min} aria-label={`${label} ${index + 1} 삭제`}
    onClick={() => onApply(d => changeTemplateItems(d, chapterId, 'remove', index))}>삭제</button>;

  return (
    <div className="property-panel">
      <h3>{TEMPLATE_LABELS[chapter.template]}</h3>
      <div className="field">
        <label>장 주제
          <input aria-label="장 주제" value={topic}
            onChange={(e) => setTopic(e.target.value)} onBlur={commitTopic} />
        </label>
      </div>
      <div className="field">
        <label>템플릿
        <select aria-label="템플릿" value={chapter.template}
          onChange={(e) => {
            const to = e.target.value as TemplateName;
            const result = applyTemplateSwitch(deck, chapterId, to);
            if (result.dropped.length > 0) {
              const ok = window.confirm(
                `다음 내용은 새 템플릿에 자리가 없어 사라집니다:\n- ${result.dropped.join("\n- ")}\n계속할까요?`,
              );
              if (!ok) return;
            }
            if (onSwitchTemplate) onSwitchTemplate(chapterId, to, deck);
            else onApply((d) => applyTemplateSwitch(d, chapterId, to).deck);
          }}>
          {SELECTABLE_TEMPLATES.map((v) => (
            <option key={v} value={v}>{TEMPLATE_LABELS[v]}</option>
          ))}
        </select>
        </label>
      </div>
      {slide && <>
        {textField("아이브로우", slide.eyebrow ?? "", text => onApply(d => setSlideField(d, chapterId, "eyebrow", text)))}
        {textField("페이지 부제", slide.subtitle ?? "", text => onApply(d => setSlideField(d, chapterId, "subtitle", text)))}
      </>}
      {slide && <ExpressionPanel deck={deck} chapterId={chapterId} onApply={onApply} />}
      {slots?.template === "callout" && <section>
        {textField("강조 문장", slots.text, text => editSlots(s => s.template === 'callout' ? {...s, text} : s))}
        <label>강조 색 역할<select aria-label="강조 색 역할" value={slots.tone} onChange={e => {
          const tone = e.target.value as typeof slots.tone;
          editSlots(s => s.template === 'callout' ? {...s, tone} : s);
        }}>{['ink','ink_soft','accent1','accent2','danger','ok','surface1','surface2','surface3','surface_danger'].map(t => <option key={t} value={t}>{t}</option>)}</select></label>
      </section>}
      {slots?.template === "cards" && <section><h4>카드</h4>
        {slots.cards.map((card, i) => {
          const update = (change: (item: typeof card) => typeof card) => editSlots(s => s.template === 'cards' ? {...s, cards:s.cards.map((v,j) => j === i ? change(v) : v)} : s);
          return <section key={i}><h4>{i + 1}번 카드</h4>
            {textField(`${i + 1}번 카드 배지`, card.badge ?? '', text => update(v => ({...v,badge:text})))}
            {textField(`${i + 1}번 카드 제목`, card.heading, text => update(v => ({...v,heading:text})))}
            {textField(`${i + 1}번 카드 꼬리`, card.tail ?? '', text => update(v => ({...v,tail:text})))}
            <label><input type="checkbox" aria-label={`${i + 1}번 카드 강조`} checked={card.emphasis} onChange={e => {const emphasis=e.target.checked;update(v => ({...v,emphasis}));}} />강조</label>
            {card.bullets.map((b,j) => <div key={j}>
              {textField(`${i + 1}번 카드 불릿 ${j + 1}`, b.text, text => update(v => ({...v,bullets:v.bullets.map((x,k) => k===j?{...x,text}:x)})))}
              <label>들여쓰기<select aria-label={`${i + 1}번 카드 불릿 ${j + 1} 들여쓰기`} value={b.level} onChange={e => {const level=Number(e.target.value) as 0|1;update(v=>({...v,bullets:v.bullets.map((x,k)=>k===j?{...x,level}:x)}));}}><option value={0}>없음</option><option value={1}>1단계</option></select></label>
              <button aria-label={`${i + 1}번 카드 불릿 ${j + 1} 삭제`} onClick={() => update(v => ({...v,bullets:v.bullets.filter((_,k) => k!==j)}))}>삭제</button>
            </div>)}
            <button onClick={() => update(v => ({...v,bullets:[...v.bullets,{text:'',level:0}]}))}>{i + 1}번 카드 불릿 추가</button>
            {itemControls('카드',slots.cards.length,2,i)}
          </section>;
        })}
        <button disabled={slots.cards.length >= 4} onClick={() => onApply(d => changeTemplateItems(d,chapterId,'add'))}>카드 추가</button>
      </section>}
      {slots?.template === "process" && <section><h4>번호 단계</h4>
        {slots.steps.map((step,i) => {
          const update = (change:(item: typeof step) => typeof step) => editSlots(s=>s.template==='process'?{...s,steps:s.steps.map((v,j)=>j===i?change(v):v)}:s);
          return <section key={i}><h4>{i + 1}번 단계</h4>
            {textField(`${i + 1}번 단계 제목`,step.heading,text=>update(v=>({...v,heading:text})))}
            {textField(`${i + 1}번 단계 부제`,step.subtitle ?? '',text=>update(v=>({...v,subtitle:text})))}
            {textList(`${i + 1}번 단계 보조 라벨`,step.notes,notes=>update(v=>({...v,notes})),2)}
            {itemControls('단계',slots.steps.length,3,i)}
          </section>;
        })}
        <button disabled={slots.steps.length >= 6} onClick={() => onApply(d=>changeTemplateItems(d,chapterId,'add'))}>단계 추가</button>
      </section>}
      {slots?.template === "matrix" && <section><h4>분류 행</h4>
        {slots.rows.map((row,i)=>{
          const update=(change:(item:typeof row)=>typeof row)=>editSlots(s=>s.template==='matrix'?{...s,rows:s.rows.map((v,j)=>j===i?change(v):v)}:s);
          return <section key={i}><h4>{i + 1}번 행</h4>
            {textField(`${i + 1}번 행 분류`,row.category,text=>update(v=>({...v,category:text})))}
            {textField(`${i + 1}번 행 대표 항목`,row.primary ?? '',text=>update(v=>({...v,primary:text})))}
            {textList(`${i + 1}번 행 항목`,row.items,items=>update(v=>({...v,items})))}
            {itemControls('분류 행',slots.rows.length,3,i)}
          </section>;
        })}
        <button disabled={slots.rows.length >= 6} onClick={() => onApply(d=>changeTemplateItems(d,chapterId,'add'))}>분류 행 추가</button>
      </section>}
      {slots?.template === "bullet_box" && bulletSection("본문 불릿", "bullets", slots.bullets ?? [])}
      {slots?.template === "summary" && bulletSection("요점", "points", slots.points ?? [])}
      {slots?.template === "compare2" && (
        <>
          {bulletSection("왼쪽 카드", "left_card", slots.left.bullets ?? [])}
          {bulletSection("오른쪽 카드", "right_card", slots.right.bullets ?? [])}
        </>
      )}
      {slots?.template === "table" && (
        <section>
          <h4>표 조작</h4>
          <ul>
            {slots.rows.map((r, i) => (
              <li key={i}>
                <span>{r.join(" | ")}</span>
                <button aria-label={`${i + 1}번 행 삭제`}
                  onClick={() => onApply((d) => deleteTableRow(d, chapterId, i))}>행 삭제</button>
              </li>
            ))}
          </ul>
          {slots.columns.slice(0, -1).map((c, i) => (
            <button key={i}
              onClick={() => onApply((d) => mergeTableColumns(d, chapterId, i))}>
              {c} + {slots.columns[i + 1]} 열 병합
            </button>
          ))}
        </section>
      )}
      <p className="hint">텍스트 내용은 가운데 미리보기에서 클릭해 직접 고칠 수 있습니다.</p>
    </div>
  );
}
