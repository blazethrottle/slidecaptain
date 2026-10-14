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
  // "분량 주의"는 분량 경고만 센다. 글자 크기 경고는 "글자 크기 확인"으로 따로 보인다 (α 리뷰 A3)
  const chaptersWith = (kind: string) => new Set((plan?.slides ?? [])
    .filter((s) => s.warnings.some((w) => (w.kind ?? "capacity") === kind)).map((s) => s.chapter_id));
  const warned = chaptersWith("capacity");
  const fontWarned = chaptersWith("font_size");
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
          onDragEnd={() => { dragFrom.current = null; }}
        >
          <button aria-pressed={selected === c.id} onClick={() => onSelect(c.id)}>
            <span className="chapter-topic">
              {i + 1}. {c.topic}
              {!generated.has(c.id) && <em> 내용 없음</em>}
              {warned.has(c.id) && <strong className="warn-badge"> 분량 주의</strong>}
              {fontWarned.has(c.id) && <strong className="warn-badge"> 글자 크기 확인</strong>}
            </span>{" "}
            <span className="chapter-template">템플릿: {TEMPLATE_LABELS[c.template]}</span>
          </button>
        </li>
      ))}
    </ul>
  );
}
