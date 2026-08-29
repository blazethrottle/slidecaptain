import { useRef } from "react";
import type { Deck, RenderPlan } from "../api/client";
import { TEMPLATE_LABELS } from "./labels";

export function ChapterList({ deck, plan, selected, onSelect, onReorder }: {
  deck: Deck;
  plan: RenderPlan | null;
  selected: string | null;
  onSelect: (id: string) => void;
  onReorder?: (from: number, to: number) => void;
}) {
  const warned = new Set(
    (plan?.slides ?? []).filter((s) => s.warnings.length > 0).map((s) => s.chapter_id));
  const generated = new Set(deck.slides.map((s) => s.chapter_id));
  const dragFrom = useRef<number | null>(null);
  return (
    <ul className="chapter-list">
      {deck.structure.chapters.map((c, i) => (
        <li key={c.id} draggable={onReorder !== undefined}
          onDragStart={() => { dragFrom.current = i; }}
          onDragOver={(e) => e.preventDefault()}
          onDrop={() => {
            if (dragFrom.current !== null && dragFrom.current !== i) {
              onReorder?.(dragFrom.current, i);
            }
            dragFrom.current = null;
          }}
        >
          <button aria-pressed={selected === c.id} onClick={() => onSelect(c.id)}>
            {i + 1}. {c.topic} <small>{TEMPLATE_LABELS[c.template]}</small>
            {!generated.has(c.id) && <em> 내용 없음</em>}
            {warned.has(c.id) && <strong className="warn-badge"> 분량 주의</strong>}
          </button>
        </li>
      ))}
    </ul>
  );
}
