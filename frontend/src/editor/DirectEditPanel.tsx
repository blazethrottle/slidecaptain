import { useEffect, useRef, useState } from "react";
import { api, messageOf, type Deck, type FontLimit, type Preset, type SlidePlan } from "../api/client";
import type { Coalesce } from "../state/useDeckEditor";
import {
  FILL_NAMES, TEXT_COLOR_NAMES, clampOffset, contrastRatio, displayBoxes, editElement, frameKey, roleName,
  type ElementEdit, type FillRole, type KeySpec, type TextColorRole,
} from "./directEdit";

const FONT_INPUT_MAX = 72;  // 화면 시안의 글자 크기 상한 (계획 4.5)
const CONTRAST_MIN = 4.5;  // WCAG 2 AA 본문 대비

type Apply = (edit: (d: Deck) => Deck, options?: { snapshot?: boolean; coalesce?: Coalesce }) => void;

// 오류 문구(문자열)는 반영하지 않았다는 뜻이고, 안내({ notice })는 값을 고쳐 반영했다는 뜻이다
type CommitResult = string | null | { notice: string };

/** 확정 전 입력 칸. Enter, 초점 이동, 칸이 사라질 때 유효한 값을 반영한다 (계획 4.5, 계획 리뷰 화면 S17, S24). */
function CommitField({ label, value, min, max, step, onCommit, onPending }: {
  label: string; value: number; min?: number; max?: number; step?: number;
  onCommit: (v: number) => CommitResult;
  onPending: (pending: boolean) => void;
}) {
  const [text, setText] = useState(String(value));
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [typing, setTyping] = useState(false);  // 반영 전 입력이 있다
  const dirty = useRef(false);
  const latest = useRef({ text, onCommit });
  latest.current = { text, onCommit };
  useEffect(() => { if (!dirty.current) setText(String(value)); }, [value]);
  const commit = () => {
    if (!dirty.current) return;
    dirty.current = false;
    onPending(false);
    setTyping(false);
    const v = Number(latest.current.text);
    const result = Number.isFinite(latest.current.text.trim() === "" ? NaN : v) ? latest.current.onCommit(v) : "숫자를 입력해 주세요.";
    setError(typeof result === "string" ? result : "");
    setNotice(result && typeof result === "object" ? result.notice : "");
    // 반영하지 않았거나 값을 고쳐 반영했으면 칸을 실제 값으로 돌린다. 고친 값이 지금 값과 같으면 덱이 바뀌지 않아
    // 칸이 입력한 값으로 남았다 (D3c-3 리뷰 F5)
    if (result) setText(String(value));
  };
  // 모드가 닫히거나 요소가 바뀌어 칸이 사라질 때도 유효한 값은 반영한다
  useEffect(() => () => { if (dirty.current) { dirty.current = false; onPending(false); const v = Number(latest.current.text); if (Number.isFinite(v)) latest.current.onCommit(v); } }, []);  // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <label>{label}
      <input type="number" inputMode="decimal" aria-label={label} value={text} min={min} max={max} step={step}
        onChange={(e) => { setText(e.target.value); if (!dirty.current) { dirty.current = true; onPending(true); setTyping(true); } }}
        onBlur={commit} onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); commit(); } }} />
      {error && <span role="alert" className="field-error">{error}</span>}
      {notice && <span role="status" className="hint">{notice}</span>}
      {/* 머리의 저장 상태는 반영된 편집만 말하므로 반영 전 입력은 칸에서 알린다 (D3c-3 리뷰 F22) */}
      {typing && <span className="hint">Enter를 누르거나 다른 곳을 누르면 반영됩니다.</span>}
    </label>
  );
}

export function DirectEditPanel({ projectName, deck, chapterId, plan, pageW, pageH, keys, selectedKey, onApply,
  onShowFrame, onHide, onPendingChange, hiddenListRef, locked = false }: {
  projectName: string;
  deck: Deck;
  chapterId: string;
  plan: SlidePlan | null;
  pageW: number;
  pageH: number;
  keys: Record<string, KeySpec>;
  selectedKey: string | null;
  onApply: Apply;
  onShowFrame: (key: string) => void;  // 다시 보이게 한 요소로 초점을 옮긴다
  onHide: (key: string) => void;  // Delete 키와 같은 처리(다음 요소로 초점)
  onPendingChange: (pending: boolean) => void;
  hiddenListRef?: React.Ref<HTMLElement>;
  locked?: boolean;  // 목록 편집 직후 옛 미리보기가 남은 동안. 그려진 항목과 덱의 항목이 달라 막는다 (D3c-3 리뷰 F10)
}) {
  const slide = deck.slides.find((s) => s.chapter_id === chapterId);
  const template = slide?.slots.template;
  const edits = slide?.direct_edits ?? {};
  const [preset, setPreset] = useState<Preset | null>(null);
  const [limit, setLimit] = useState<FontLimit | null>(null);
  const [limitError, setLimitError] = useState("");
  const pending = useRef(new Set<string>());
  const setPending = (name: string) => (p: boolean) => {
    if (p) pending.current.add(name); else pending.current.delete(name);
    onPendingChange(pending.current.size > 0);
  };
  useEffect(() => { api.getPreset().then(setPreset).catch(() => setPreset(null)); }, []);

  const spec = selectedKey ? keys[selectedKey] : undefined;
  const edit: ElementEdit = (selectedKey && edits[selectedKey]) || {};
  // 글이 없는 요소(빈 표지 부제 등)는 서버도 배율을 버리므로 칸을 보이지 않는다 (D3c-2 리뷰 F10)
  const hasText = !!plan?.frames.some((f) => frameKey(f) === selectedKey && f.paras.some((p) => p.text.trim()));
  const canFont = !!spec?.kinds.includes("font") && hasText;

  // 넘치지 않는 최대 크기는 서버가 빌더와 같은 판정식으로 계산한다 (재리뷰 RR2). 입력이 멈춘 뒤 묻는다
  // 같은 요소를 고치는 동안에는 새 응답이 올 때까지 이전 값을 둔다. 지우면 입력 칸이 사라졌다가 다시 생긴다
  const limitKey = useRef<string | null>(null);
  // 한도는 그 장의 문구와 공통 슬롯, 장 제목, 글자 배율, 디자인 값에만 달렸다. 위치, 색, 숨김만 바뀐 편집에는 다시
  // 묻지 않는다 (D3c-3 리뷰 F13). 보낼 덱은 최신 덱이다
  const deckRef = useRef(deck);
  deckRef.current = deck;
  const limitInput = JSON.stringify({
    slots: slide?.slots, eyebrow: slide?.eyebrow, subtitle: slide?.subtitle,
    topic: deck.structure.chapters.find((c) => c.id === chapterId)?.topic, presenter: deck.meta.presenter,
    scales: Object.entries(edits).filter(([, e]) => e.font_scale != null).map(([k, e]) => [k, e.font_scale]),
    spans: slide?.text_spans,  // 서버 한도는 부분 강조까지 적용해 본다 (D3c-2 리뷰 F4, α 리뷰 A4)
    overrides: deck.meta.preset_overrides,
  });
  useEffect(() => {
    if (limitKey.current !== selectedKey) { setLimit(null); limitKey.current = selectedKey; }
    setLimitError("");
    if (!canFont || !selectedKey) return;
    let cancelled = false;
    const t = setTimeout(() => {
      api.fontLimit(projectName, deckRef.current, chapterId, selectedKey)
        .then((r) => { if (!cancelled) setLimit(r); })
        .catch((e) => { if (!cancelled) setLimitError(messageOf(e)); });
    }, 300);
    return () => { cancelled = true; clearTimeout(t); };
  }, [projectName, limitInput, chapterId, selectedKey, canFont]);

  const colors = { ...(preset?.colors ?? {}), ...((deck.meta.preset_overrides as { colors?: Record<string, string> })?.colors ?? {}) } as Record<string, string>;
  const apply = (patch: Partial<ElementEdit>) => selectedKey && onApply((d) => editElement(d, chapterId, selectedKey, patch));

  const hidden = Object.entries(edits).filter(([, e]) => e.hidden).map(([k]) => k);
  const hiddenList = (
    <section aria-label="숨긴 요소" ref={hiddenListRef} tabIndex={-1}>
      <h4>숨긴 요소</h4>
      {hidden.length === 0 ? <p className="hint">숨긴 요소가 없습니다.</p> : (
        <ul>{hidden.map((k) => (
          <li key={k}>{roleName(k, template)}{" "}
            {/* 옛 미리보기가 남은 동안은 초점을 줄 프레임이 다른 항목일 수 있어 막는다 (α 리뷰 A11) */}
            <button disabled={locked} onClick={() => { onApply((d) => editElement(d, chapterId, k, { hidden: undefined })); onShowFrame(k); }}>
              다시 보이기</button></li>
        ))}</ul>
      )}
    </section>
  );

  if (locked) {
    return <section className="direct-edit-panel"><p className="hint" role="status">미리보기를 새로 그리는 중입니다. 다 그린 뒤 고칠 수 있습니다.</p>{hiddenList}</section>;
  }
  if (!selectedKey || !spec || !plan) {
    return <section className="direct-edit-panel"><p className="hint">미리보기에서 요소를 고르면 위치와 글자, 색을 바꿀 수 있습니다.</p>{hiddenList}</section>;
  }

  const frames = plan.frames.filter((f) => frameKey(f) === selectedKey);
  const boxes = displayBoxes(plan, edits, pageW, pageH);
  const first = frames[0];
  const box = first ? boxes.get(first.name) : undefined;
  const baseX = first ? (first.base_x ?? first.x) : 0;
  const baseY = first ? (first.base_y ?? first.y) : 0;
  // 페이지 밖 값은 저장하는 쪽에서 잘라 반영하고 맞춘 자리를 알린다 (계획 4.2, D3c-3 리뷰 F5)
  const commitPos = (axis: "x" | "y") => (v: number): CommitResult => {
    const dx = axis === "x" ? v - baseX : (edit.dx_pt ?? 0);
    const dy = axis === "y" ? v - baseY : (edit.dy_pt ?? 0);
    const c = clampOffset(plan, selectedKey, dx, dy, pageW, pageH);
    apply({ dx_pt: c.dx, dy_pt: c.dy });
    const placed = axis === "x" ? baseX + c.dx : baseY + c.dy;
    return Math.abs(placed - v) > 0.005
      ? { notice: `페이지 안으로 맞췄습니다(${axis === "x" ? "가로" : "세로"} ${Math.round(placed * 100) / 100}pt).` } : null;
  };
  const sizes = preset ? [...new Set(Object.values(preset.font_roles).filter((v): v is number => typeof v === "number"))].sort((a, b) => a - b) : [];
  const setSize = (pt: number): CommitResult => {
    if (!limit) return "글자 크기 범위를 아직 확인하지 못했습니다.";
    if (pt < 1 || pt > FONT_INPUT_MAX) return `1pt부터 ${FONT_INPUT_MAX}pt까지 입력해 주세요.`;
    apply({ font_scale: Math.round((pt / limit.base_pt) * 10000) / 10000 });
    return null;
  };
  const textColor = edit.text_color ? colors[edit.text_color] : first?.paras[0]?.color;
  const fill = edit.fill ? colors[edit.fill] : first?.fill ?? undefined;
  // 채움이 없으면 바탕은 슬라이드 배경이다. 문단마다 색이 다르면 가장 낮은 대비를 본다 (D3c-3 리뷰 F12)
  const backdrop = fill ?? colors.background ?? "FFFFFF";
  const textColors = edit.text_color ? [colors[edit.text_color]] : frames.flatMap((f) => f.paras.map((p) => p.color));
  const lowContrast = textColors.some((c) => c && contrastRatio(c, backdrop) < CONTRAST_MIN);
  const swatch = (hex?: string) => hex ? <span className="swatch" aria-hidden style={{ background: `#${hex}` }} /> : null;

  return (
    <section className="direct-edit-panel" aria-label="직접 수정">
      <h4>{roleName(selectedKey, template)}</h4>
      {spec.kinds.includes("move") && box && (
        <fieldset>
          <legend>위치(pt, 슬라이드 왼쪽 위 기준)</legend>
          <CommitField key={`${selectedKey}-x`} label="가로 위치" value={Math.round(box.x * 100) / 100} step={1}
            onCommit={commitPos("x")} onPending={setPending("x")} />
          <CommitField key={`${selectedKey}-y`} label="세로 위치" value={Math.round(box.y * 100) / 100} step={1}
            onCommit={commitPos("y")} onPending={setPending("y")} />
          <button disabled={edit.dx_pt == null} onClick={() => apply({ dx_pt: undefined, dy_pt: undefined })}>위치 원래대로</button>
        </fieldset>
      )}
      {canFont && (
        <fieldset>
          <legend>글자 크기</legend>
          <p className="hint">요소 안 글자를 같은 비율로 바꿉니다.</p>
          {limit && <CommitField key={`${selectedKey}-font`} label="글자 크기(pt)" value={limit.current_pt} min={1}
            max={FONT_INPUT_MAX} step={0.5} onCommit={setSize} onPending={setPending("font")} />}
          {limit && sizes.length > 0 && (
            <label>자주 쓰는 크기<select aria-label="자주 쓰는 크기" value="" onChange={(e) => { if (e.target.value) setSize(Number(e.target.value)); }}>
              <option value="">고르기</option>
              {sizes.map((s) => <option key={s} value={s}>{s}pt</option>)}
            </select></label>
          )}
          {limit && (limit.fits_up_to_pt == null
            ? <p className="hint">가장 작은 크기에서도 이 상자를 넘칩니다.</p>
            : <p className="hint">이 상자에서 넘치지 않는 최대 크기: {limit.fits_up_to_pt}pt</p>)}
          {limitError && <p role="alert">글자 크기 범위를 확인하지 못했습니다. ({limitError})</p>}
          <button disabled={edit.font_scale == null} onClick={() => apply({ font_scale: undefined })}>글자 크기 원래대로</button>
        </fieldset>
      )}
      {spec.kinds.includes("text_color") && (
        <label>글자 색 {swatch(textColor)}
          <select aria-label="글자 색" value={edit.text_color ?? ""} onChange={(e) =>
            apply({ text_color: (e.target.value || undefined) as TextColorRole | undefined })}>
            <option value="">원래대로</option>
            {(Object.keys(TEXT_COLOR_NAMES) as TextColorRole[]).map((r) => <option key={r} value={r}>{TEXT_COLOR_NAMES[r]}</option>)}
          </select>
        </label>
      )}
      {spec.kinds.includes("fill") && (
        <label>채움 색 {swatch(fill)}
          <select aria-label="채움 색" value={edit.fill ?? ""} onChange={(e) =>
            apply({ fill: (e.target.value || undefined) as FillRole | undefined })}>
            <option value="">원래대로</option>
            {(Object.keys(FILL_NAMES) as FillRole[]).map((r) => <option key={r} value={r}>{FILL_NAMES[r]}</option>)}
          </select>
        </label>
      )}
      {(spec.kinds.includes("text_color") || spec.kinds.includes("fill")) && preset && (
        // 고르기 전에 역할마다 지금 프리셋의 색을 볼 수 있게 견본 목록을 둔다 (계획 4.3, D3c-3 리뷰 F18)
        <details className="swatch-legend">
          <summary>색 견본 보기</summary>
          <ul>{[...new Set([
            ...(spec.kinds.includes("text_color") ? Object.keys(TEXT_COLOR_NAMES) : []),
            ...(spec.kinds.includes("fill") ? Object.keys(FILL_NAMES) : []),
          ])].map((role) => (
            <li key={role}>{swatch(colors[role])}{" "}
              {TEXT_COLOR_NAMES[role as TextColorRole] ?? FILL_NAMES[role as FillRole]}</li>
          ))}</ul>
        </details>
      )}
      {lowContrast && <p role="status">글자와 바탕의 대비가 낮습니다(4.5:1 미만). 읽기 어려울 수 있습니다.</p>}
      {spec.kinds.includes("hide") && (
        <button onClick={() => onHide(selectedKey)}>숨기기 (Delete)</button>
      )}
      {hiddenList}
    </section>
  );
}
