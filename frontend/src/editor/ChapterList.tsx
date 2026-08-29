import type { Deck, RenderPlan } from "../api/client";
import { TEMPLATE_LABELS } from "./labels";

export function ChapterList({ deck, plan, selected, onSelect }: {
  deck: Deck;
  plan: RenderPlan | null;
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  const warned = new Set(
    (plan?.slides ?? []).filter((s) => s.warnings.length > 0).map((s) => s.chapter_id));
  const generated = new Set(deck.slides.map((s) => s.chapter_id));
  return (
    <ul className="chapter-list">
      {deck.structure.chapters.map((c, i) => (
        <li key={c.id}>
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
