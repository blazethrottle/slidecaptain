import { useEffect, useState } from "react";
import type { Deck, TemplateName } from "../api/client";
import { TEMPLATE_LABELS } from "./labels";
import {
  addBullet, applyTextEdit, deleteTableRow, mergeTableColumns, removeBullet,
} from "./slotOps";
import { applyTemplateSwitch } from "./templateSwitch";

export function PropertyPanel({ deck, chapterId, onApply }: {
  deck: Deck;
  chapterId: string;
  onApply: (edit: (d: Deck) => Deck) => void;
}) {
  const chapter = deck.structure.chapters.find((c) => c.id === chapterId);
  const slide = deck.slides.find((s) => s.chapter_id === chapterId);
  const [topic, setTopic] = useState(chapter?.topic ?? "");
  useEffect(() => setTopic(chapter?.topic ?? ""), [chapterId, chapter?.topic]);
  if (!chapter) return null;
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

  return (
    <div className="property-panel">
      <h3>{TEMPLATE_LABELS[chapter.template]}</h3>
      <label>장 주제
        <input aria-label="장 주제" value={topic}
          onChange={(e) => setTopic(e.target.value)} onBlur={commitTopic} />
      </label>
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
            onApply((d) => applyTemplateSwitch(d, chapterId, to).deck);
          }}>
          {Object.entries(TEMPLATE_LABELS).map(([v, label]) => (
            <option key={v} value={v}>{label}</option>
          ))}
        </select>
      </label>
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
