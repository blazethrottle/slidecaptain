import type { Deck, Slide } from '../api/client';

export type TextSpan = NonNullable<Slide['text_spans']>[number];
export type SpanTarget = Pick<TextSpan, 'slot' | 'index'>;

export function spanText(slide: Slide, target: SpanTarget): string | null {
  if (target.slot === 'eyebrow' || target.slot === 'subtitle') return slide[target.slot] ?? '';
  if (target.slot === 'bullets') return slide.slots.template === 'bullet_box' && target.index != null
    ? slide.slots.bullets[target.index]?.text ?? null : null;
  if (target.slot === 'text') return slide.slots.template === 'callout' ? slide.slots.text : null;
  return 'conclusion' in slide.slots ? slide.slots.conclusion : null;
}

export function codePointRange(text: string, start: number, end: number): { start: number; end: number } | null {
  let offset = 0;
  const boundaries = new Map<number, number>([[0, 0]]);
  Array.from(text).forEach((char, index) => { offset += char.length; boundaries.set(offset, index + 1); });
  const a = boundaries.get(start), b = boundaries.get(end);
  return a !== undefined && b !== undefined && b > a ? { start: a, end: b } : null;
}

export async function sha256Text(text: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
  return Array.from(new Uint8Array(digest), value => value.toString(16).padStart(2, '0')).join('');
}

export async function prepareTextSpan(
  base: Deck, chapterId: string, target: SpanTarget, selection: { start: number; end: number },
  role: TextSpan['role'], current: () => Deck, hash: (text: string) => Promise<string> = sha256Text,
): Promise<TextSpan> {
  const slide = base.slides.find(s => s.chapter_id === chapterId);
  if ((slide?.text_spans?.length ?? 0) >= 100) throw new Error('한 장의 부분 강조는 최대 100개입니다. 기존 강조를 지운 뒤 다시 선택해 주세요.');
  const text = slide ? spanText(slide, target) : null;
  const range = text === null ? null : codePointRange(text, selection.start, selection.end);
  if (!range) throw new Error('강조할 문구를 정확히 선택해 주세요.');
  if ((slide?.text_spans ?? []).some(s => s.slot === target.slot && (s.index ?? null) === (target.index ?? null)
    && range.start < s.end && range.end > s.start)) throw new Error('기존 강조 범위와 겹칩니다. 강조를 지운 뒤 다시 선택해 주세요.');
  const text_sha256 = await hash(text!);
  if (current() !== base) throw new Error('선택하는 동안 문서가 바뀌었습니다. 현재 문구를 다시 선택해 주세요.');
  return { ...target, ...range, role, text_sha256 };
}

export function pruneChangedSpans(before: Deck, after: Deck): Deck {
  if (before === after) return after;
  let changed = false;
  const slides = after.slides.map(slide => {
    if (!slide.text_spans?.length) return slide;
    const old = before.slides.find(s => s.chapter_id === slide.chapter_id);
    if (!old) return slide;
    const kept = slide.text_spans.filter(span => spanText(old, span) === spanText(slide, span) && spanText(slide, span) !== null);
    if (kept.length === slide.text_spans.length) return slide;
    changed = true;
    return { ...slide, text_spans: kept };
  });
  return changed ? { ...after, slides } : after;
}

export function setChart(deck: Deck, chapterId: string, comparisonId: string, kind: 'bar' | 'column' | 'table'): Deck {
  const plan = deck.structure.story_plan;
  const assignment = plan?.chapters.find(ch => ch.chapter_id === chapterId);
  const comparison = plan?.comparisons.find(c => c.id === comparisonId && assignment?.claim_ids.includes(c.claim_id));
  if (kind !== 'table' && !comparison) return deck;
  return { ...deck, slides: deck.slides.map(slide => slide.chapter_id === chapterId && slide.slots.template === 'table'
    ? { ...slide, chart: kind === 'table' ? null : { rule_version: 'comparison-chart-v1', comparison_id: comparisonId, kind } } : slide) };
}
