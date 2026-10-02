import { useEffect, useRef, useState } from 'react';
import type { Deck } from '../api/client';
import { prepareTextSpan, setChart, spanText, type SpanTarget } from './expressionEditing';

export function ExpressionPanel({ deck, chapterId, onApply }: {
  deck: Deck; chapterId: string; onApply: (edit: (deck: Deck) => Deck) => void;
}) {
  const latest = useRef(deck); latest.current = deck;
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const slide = deck.slides.find(s => s.chapter_id === chapterId);
  const [targetKey, setTargetKey] = useState('eyebrow');
  const [selection, setSelection] = useState({ start: 0, end: 0 });
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const [error, setError] = useState('');
  const [comparisonId, setComparisonId] = useState('');
  const chapterRef = useRef(chapterId); chapterRef.current = chapterId;

  const targets: { key: string; label: string; target: SpanTarget }[] = [
    { key: 'eyebrow', label: '아이브로우', target: { slot: 'eyebrow', index: null } },
    { key: 'subtitle', label: '페이지 부제', target: { slot: 'subtitle', index: null } },
  ];
  if (slide && 'conclusion' in slide.slots) targets.push({ key: 'conclusion', label: '결론', target: { slot: 'conclusion', index: null } });
  if (slide?.slots.template === 'callout') targets.push({ key: 'text', label: '강조 문장', target: { slot: 'text', index: null } });
  if (slide?.slots.template === 'bullet_box') slide.slots.bullets.forEach((_, index) => targets.push({ key: `bullets-${index}`, label: `불릿 ${index + 1}`, target: { slot: 'bullets', index } }));
  const chosen = targets.find(item => item.key === targetKey) ?? targets[0];
  const text = slide ? spanText(slide, chosen.target) ?? '' : '';
  useEffect(() => { setSelection({ start: 0, end: 0 }); setError(''); }, [chapterId, chosen.key, text]);
  const plan = deck.structure.story_plan;
  const assignment = plan?.chapters.find(ch => ch.chapter_id === chapterId);
  const comparisons = plan?.comparisons.filter(c => assignment?.claim_ids.includes(c.claim_id)) ?? [];
  const selectedComparison = comparisons.some(c => c.id === comparisonId) ? comparisonId : slide?.chart?.comparison_id ?? comparisons[0]?.id ?? '';
  if (!slide) return null;
  const add = async (role: 'bold' | 'accent') => {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true); setError('');
    const base = deck, chapter = chapterId;
    try {
      const span = await prepareTextSpan(base, chapter, chosen.target, selection, role, () => latest.current);
      if (!mounted.current || chapterRef.current !== chapter) return;
      onApply(current => current !== base ? current : { ...current, slides: current.slides.map(s => s.chapter_id === chapter
        ? { ...s, text_spans: [...(s.text_spans ?? []), span] } : s) });
    } catch (err) { if (mounted.current) setError(err instanceof Error ? err.message : '강조를 적용하지 못했습니다.'); }
    finally { busyRef.current = false; if (mounted.current) setBusy(false); }
  };
  return <section aria-label="차트와 부분 강조">
    {slide.slots.template === 'table' && <section>
      <h4>표와 차트</h4>
      <p className="hint">원래 표 내용은 보존됩니다. 현재 근거의 비교 조건과 값이 확인되는 경우 차트를 표시합니다.</p>
      <label>차트 비교<select aria-label="차트 비교" value={selectedComparison} onChange={event => {
        const id = event.target.value;
        setComparisonId(id);
        if (slide.chart) onApply(current => setChart(current, chapterId, id, slide.chart!.kind));
      }}>
        {!comparisons.length && <option value="">연결된 비교 없음</option>}
        {comparisons.map(c => <option key={c.id} value={c.id}>{c.id}: {plan?.claims.find(claim => claim.id === c.claim_id)?.statement}</option>)}
      </select></label>
      <label>표시 방식<select aria-label="표시 방식" value={slide.chart?.kind ?? 'table'} onChange={event => {
        const kind = event.target.value as 'bar' | 'column' | 'table';
        onApply(current => setChart(current, chapterId, selectedComparison, kind));
      }}>
        <option value="table">원래 표</option><option value="bar" disabled={!selectedComparison}>가로 막대 차트</option><option value="column" disabled={!selectedComparison}>세로 막대 차트</option>
      </select></label>
    </section>}
    <h4>문구 부분 강조</h4>
    <label>강조할 칸<select aria-label="강조할 칸" disabled={busy} value={chosen.key} onChange={event => setTargetKey(event.target.value)}>
      {targets.map(item => <option key={item.key} value={item.key}>{item.label}</option>)}
    </select></label>
    <textarea aria-label="강조 문구 선택" disabled={busy} readOnly value={text} onSelect={event => setSelection({ start: event.currentTarget.selectionStart, end: event.currentTarget.selectionEnd })} />
    <p className="hint">기존 문구에서 강조할 부분을 선택하세요. 문구를 수정하면 해당 칸의 강조를 지웁니다.</p>
    {(slide.text_spans?.length ?? 0) >= 100 && <p className="hint">이 장의 부분 강조가 최대 100개에 도달했습니다. 기존 강조를 지운 뒤 추가해 주세요.</p>}
    <button disabled={busy || (slide.text_spans?.length ?? 0) >= 100 || selection.end <= selection.start} onClick={() => void add('bold')}>선택 부분 굵게</button>
    <button disabled={busy || (slide.text_spans?.length ?? 0) >= 100 || selection.end <= selection.start} onClick={() => void add('accent')}>선택 부분 강조색</button>
    <button disabled={busy || !slide.text_spans?.length} onClick={() => onApply(current => ({ ...current, slides: current.slides.map(s => s.chapter_id === chapterId ? { ...s, text_spans: [] } : s) }))}>이 장의 부분 강조 지우기</button>
    {error && <p role="alert">{error}</p>}
  </section>;
}
