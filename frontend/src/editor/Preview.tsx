import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import type { Frame, Para, SlidePlan, RenderPlan } from "../api/client";
import { DiagramPreview } from "./DiagramPreview";
import { ChartPreview } from "./ChartPreview";
import { displayBoxes, frameKey, roleName, warningKey, type ElementEdit, type KeySpec } from "./directEdit";
import type { Coalesce } from "../state/useDeckEditor";

export type FrameRef = { chapterId: string; slot: string };
export type TextRef = FrameRef & { index?: number; row?: number; col?: number };
type Style = RenderPlan["style"];

// 표 모양은 PPTX의 내장 표 스타일 Medium Style 2 - Accent 1을 따른다: 표 전체 채움은 강조색 1의 20% 옅은 색(tint 20000,
// python-pptx 기본 테마 강조색 1 4F81BD를 선형 RGB에서 섞은 값), 경계선은 흰색(lt1) 1pt. 라이터는 첫 행과 줄무늬를 끄므로
// 그 두 조건은 쓰지 않는다. 출처는 LibreOffice의 내장 표 스타일 정의(oox predefined-table-styles.cxx)이고 실제
// PowerPoint 표시는 회사 PC에서 확인한다 (D3c-3, E6, 계획 리뷰 저장 S26)
const TABLE_BODY_FILL = "#E9EDF4";
const TABLE_LINE = "#FFFFFF";
// Windows의 기본 끌기 시작 거리(SM_CXDRAG, SM_CYDRAG)를 CSS px로 쓴다. 두 값은 축마다 따로 보는 사각형이다
// (계획 4.5, D3c-3 리뷰 F19)
const DRAG_START_PX = 4;
const ARROW_STEP = { small: 1, large: 10 };  // 화면 시안의 방향키 이동량(pt). PowerPoint의 Shift+방향키와 다르다(가정 8)

// 선택자 안의 따옴표만 막는다. 열쇠와 장 ID는 영문, 숫자, 밑줄이다
const quoted = (value: string) => value.replace(/["\\]/g, "\\$&");

function frameRef(f: Frame): FrameRef {
  const chapterId = f.name.split(":")[0];
  return { chapterId, slot: frameKey(f) };
}

// 문구를 고칠 수 없는 프레임: 쪽 번호, 차트와 그 조건 문구(근거 표시), 단계 번호(자동 번호)
function textEditable(f: Frame): boolean {
  return !/:(page_number|chart|chart_conditions|step\d+_badge)$/.test(f.name);
}

type Drag = {
  key: string; pointerId: number; x0: number; y0: number; scale: number; baseDx: number; baseDy: number;
  started: boolean; token: unknown; target: Element;
  dx: number; dy: number;  // 지금까지 끈 거리(pt). 놓을 때 상태 갱신 함수 밖에서 읽는다 (D3c-3 리뷰 F16)
};

export function Preview({
  slide, style, pageW, pageH, editable = true, selected, onSelect, onCommitText,
  template, keys = {}, edits, mode = false, dragAllowed = false, deckToken, onMove, onHide, onNeedMode, onDragChange, onDragDiscard,
  focusRequest, hiddenCount = 0, onShowHidden,
}: {
  slide: SlidePlan;
  style: Style;
  pageW: number;
  pageH: number;
  editable?: boolean;  // 거짓이면 계획이 낡은 것이다: 흐리게 그리고 문구 입력을 열지 않는다 (프레임 선택은 된다)
  selected: FrameRef | null;
  onSelect: (ref: FrameRef | null) => void;
  onCommitText: (ref: TextRef, text: string) => void;
  // 직접 수정 (D3c-3, 계획 4.5)
  template?: string;
  keys?: Record<string, KeySpec>;  // 지금 덱의 요소 열쇠와 받는 수정 종류
  edits?: Record<string, ElementEdit>;  // 지금 덱의 이 장 수정. 그리는 위치와 숨김은 이 값으로 계산한다
  mode?: boolean;
  dragAllowed?: boolean;
  deckToken?: unknown;  // 지금 덱 객체. 끄는 동안 바뀌면(되돌리기, 다른 탭의 반영) 놓아도 반영하지 않는다
  onMove?: (key: string, dx: number, dy: number, options: { coalesce?: Coalesce }) => void;
  onHide?: (key: string) => void;
  onNeedMode?: () => void;  // 모드 밖에서 Delete나 방향키를 눌렀다
  onDragChange?: (dragging: boolean) => void;
  onDragDiscard?: () => void;  // 끄는 동안 덱이 바뀌어 놓은 결과를 버렸다
  focusRequest?: { target: string | null; nonce: number };  // 요소 열쇠(그 요소의 첫 프레임) 또는 캔버스
  hiddenCount?: number;
  onShowHidden?: () => void;
}) {
  const holder = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(1);
  const [editing, setEditing] = useState<{ ref: TextRef; text: string; origin: string } | null>(null);
  const [drag, setDrag] = useState<{ key: string; dx: number; dy: number } | null>(null);
  const dragRef = useRef<Drag | null>(null);
  const suppressClick = useRef(false);
  // 포인터로 생긴 초점은 선택을 클릭 처리에 맡긴다. 초점에서 고르면 첫 클릭이 곧바로 문구 입력을 열어 지금의
  // "누르면 고르기, 다시 누르면 입력" 흐름이 바뀐다 (모드 밖 기존 흐름 유지, 계획 4.5)
  const pointerFocus = useRef(false);

  // 표시 배율은 미리보기 폭이 바뀔 때마다 다시 잰다. 창 크기가 그대로인데 배치가 바뀌는 경우(스크롤 막대, 안내 문단)도
  // 잡도록 ResizeObserver를 쓴다(jsdom에는 없어 창 resize로 대신한다) (E11, 계획 리뷰 화면 S3)
  useLayoutEffect(() => {
    const measure = () => {
      const w = holder.current?.clientWidth ?? 0;
      setScale(w > 0 ? w / pageW : 1);
    };
    measure();
    if (typeof ResizeObserver !== "undefined" && holder.current) {
      const observer = new ResizeObserver(measure);
      observer.observe(holder.current);
      return () => observer.disconnect();
    }
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [pageW]);

  const endDrag = useCallback((commit: boolean) => {
    const d = dragRef.current;
    if (!d) return;
    dragRef.current = null;  // 먼저 비운다: pointerup 뒤에 오는 lostpointercapture를 무시하기 위해서다 (리뷰 화면 S10)
    try { (d.target as Element & { releasePointerCapture?: (id: number) => void }).releasePointerCapture?.(d.pointerId); } catch { /* 이미 풀림 */ }
    // 반영은 이벤트 처리 안에서 한다. 상태 갱신 함수 안에서 부르면 렌더 중에 편집 화면을 갱신하게 된다 (D3c-3 리뷰 F16)
    if (d.started) suppressClick.current = true;  // 놓기나 취소 뒤 따라오는 클릭이 선택을 바꾸지 않게 (F17)
    if (commit && d.started) {
      if (d.token === deckToken) onMove?.(d.key, d.baseDx + d.dx, d.baseDy + d.dy, {});
      else onDragDiscard?.();
    }
    setDrag(null);
    dragChange.current?.(false);
  }, [deckToken, onMove, onDragDiscard]);

  // 모드가 닫히거나 끌기가 막히면(읽기 전용, 충돌, 서버 내용 다시 읽기, 목록 편집 직후의 낡은 계획) 끌기를 취소한다
  useEffect(() => { if (!mode || !dragAllowed) endDrag(false); }, [mode, dragAllowed, endDrag]);
  // 끌기 여부 알림은 최신 콜백으로 한다. 정리는 마운트 해제 때만 한다: 부모가 렌더마다 새 콜백을 넘기므로 콜백에 걸면
  // 끄는 중 부모가 다시 그려질 때마다 "끌기 끝"을 알려 끄는 중 되돌리기가 통했다 (D3c-3 리뷰 F23)
  const dragChange = useRef(onDragChange);
  dragChange.current = onDragChange;
  useEffect(() => () => { if (dragRef.current) dragChange.current?.(false); }, []);
  useEffect(() => {
    if (!drag) return;
    const cancel = () => endDrag(false);
    // 끌기를 취소한 Escape는 프레임의 선택 해제로 넘기지 않는다. 한 번에 한 단계다 (D3c-3 리뷰 F17)
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.preventDefault(); e.stopImmediatePropagation(); e.stopPropagation(); endDrag(false); }
    };
    window.addEventListener("blur", cancel);
    window.addEventListener("keydown", onKey, true);
    return () => { window.removeEventListener("blur", cancel); window.removeEventListener("keydown", onKey, true); };
  }, [drag !== null, endDrag]); // eslint-disable-line react-hooks/exhaustive-deps

  const startDrag = (e: React.PointerEvent, key: string) => {
    const spec = keys[key];
    if (!mode || !dragAllowed || !spec?.kinds.includes("move") || e.button !== 0) return;
    e.stopPropagation();
    // 끌기를 시작할 때 캔버스의 실제 화면 폭으로 배율을 다시 잰다(브라우저 확대와 배치 변화 포함)
    const rect = canvas.current?.getBoundingClientRect();
    const liveScale = rect && rect.width > 0 ? rect.width / pageW : scale;
    const edit = edits?.[key];
    const target = e.currentTarget;
    try { (target as Element & { setPointerCapture?: (id: number) => void }).setPointerCapture?.(e.pointerId); } catch { /* jsdom */ }
    dragRef.current = { key, pointerId: e.pointerId, x0: e.clientX, y0: e.clientY, scale: liveScale,
      baseDx: edit?.dx_pt ?? 0, baseDy: edit?.dy_pt ?? 0, started: false, token: deckToken, target, dx: 0, dy: 0 };
  };
  const moveDrag = (e: React.PointerEvent) => {
    const d = dragRef.current;
    if (!d || e.pointerId !== d.pointerId) return;
    const px = e.clientX - d.x0;
    const py = e.clientY - d.y0;
    if (!d.started) {
      if (Math.abs(px) <= DRAG_START_PX && Math.abs(py) <= DRAG_START_PX) return;
      d.started = true;
      dragChange.current?.(true);
    }
    d.dx = px / d.scale;
    d.dy = py / d.scale;
    setDrag({ key: d.key, dx: d.dx, dy: d.dy });
  };
  const dragHandlers = {
    onPointerMove: moveDrag,
    onPointerUp: (e: React.PointerEvent) => { if (dragRef.current?.pointerId === e.pointerId) endDrag(true); },
    onPointerCancel: () => endDrag(false),
    onLostPointerCapture: () => endDrag(false),  // pointerup 없이 잡기가 풀렸을 때만 남아 있다
  };

  // 마운트할 때 이미 있던 요청은 다른 장에서 만든 것이므로 적용하지 않는다. 미리보기는 장마다 새로 마운트되고 요청은
  // 편집 화면에 남아, 장을 바꾸면 이전 장의 숨기기가 남긴 초점이 새 장의 같은 요소를 골랐다 (D3c-3 리뷰 F8)
  const handledFocus = useRef(focusRequest?.nonce);
  useEffect(() => {
    if (!focusRequest || focusRequest.nonce === handledFocus.current) return;
    handledFocus.current = focusRequest.nonce;
    if (focusRequest.target === null) { canvas.current?.focus(); return; }
    const el = canvas.current?.querySelector<HTMLElement>(`[data-key="${quoted(focusRequest.target)}"][tabindex="0"]`);
    (el ?? canvas.current)?.focus();
  }, [focusRequest]);

  // 키로 입력란을 닫으면 초점을 그 프레임으로 돌린다. 입력란이 사라지면 초점이 문서 본문으로 빠져 다음 Tab, Delete,
  // 방향키가 요소에 닿지 않았다 (D3c-3 리뷰 F7). 마우스로 다른 곳을 눌러 닫힌 경우(blur)는 초점을 빼앗지 않는다
  const cancelling = useRef(false);
  const focusFrameOf = (ref: TextRef): boolean => {
    const f = frameOf(ref);
    const el = f ? canvas.current?.querySelector<HTMLElement>(`[data-frame="${quoted(f.name)}"]`) : null;
    if (!el) return false;
    el.focus();
    return document.activeElement === el;
  };

  const commit = () => {
    // 변경 없는 확정(문단 클릭 후 Enter만 누른 경우 등)은 언두와 저장을 오염시키지 않는다
    // (2026-08-29 최종 리뷰 발견)
    if (editing && editing.text !== editing.origin) onCommitText(editing.ref, editing.text);
    setEditing(null);
  };

  const startEdit = (ref: TextRef, text: string) => {
    const frame = { chapterId: ref.chapterId, slot: ref.slot };
    if (selected?.chapterId === frame.chapterId && selected.slot === frame.slot) {
      // 낡은 계획의 인덱스로 편집을 열면 다른 문단을 덮어쓴다 (2026-09-03 FC-05). 이미 열려 있는 편집창은
      // 다른 곳을 클릭할 때 브라우저가 textarea 의 blur 를 먼저 일으켜 덱이 바뀌기 전 상태로 확정되므로 안전하다
      if (editable) setEditing({ ref, text, origin: text });
    } else {
      onSelect(frame);
    }
  };

  // 프레임의 문단과 표 칸을 차례로 늘어놓는다. Enter는 처음 것을, 입력란의 Tab은 다음 것을 연다 (재리뷰 RR13)
  const textStops = (f: Frame): { ref: TextRef; text: string }[] => {
    const base = frameRef(f);
    if (f.table) {
      const t = f.table;
      return [
        ...t.header.map((text, col) => ({ ref: { ...base, row: -1, col }, text })),
        ...t.rows.flatMap((row, r) => row.map((text, col) => ({ ref: { ...base, row: r, col }, text }))),
      ];
    }
    return f.paras.map((p, i) => ({ ref: { ...base, index: i }, text: p.text }));
  };
  const frameOf = (ref: TextRef) => slide.frames.find((f) => frameKey(f) === ref.slot && textEditable(f));
  const sameStop = (a: TextRef, b: TextRef) => a.index === b.index && a.row === b.row && a.col === b.col;

  const stepEdit = (direction: 1 | -1) => {
    if (!editing) return;
    const f = frameOf(editing.ref);
    const stops = f ? textStops(f) : [];
    const at = stops.findIndex((s) => sameStop(s.ref, editing.ref));
    const next = stops[at + direction];
    // 칸을 비우거나 빈 칸을 채우는 확정은 선택 칸(카드 배지와 꼬리 등)을 없애거나 만들어 문단 번호의 뜻을 바꾼다. 그때는
    // 옛 계획의 다음 칸을 열지 않고 프레임으로 돌아간다. 열면 고친 문구가 다른 칸을 덮어썼다 (α 리뷰 A1)
    const reshaped = (editing.origin.trim() === "") !== (editing.text.trim() === "");
    if (next && editable && !reshaped) { commit(); setEditing({ ref: next.ref, text: next.text, origin: next.text }); return; }
    // 프레임으로 초점을 옮기면 입력란의 blur가 한 번 확정한다. 옮기지 못했을 때만 여기서 확정한다
    if (!focusFrameOf(editing.ref)) commit();
  };

  const renderPara = (f: Frame, p: Para, i: number) => {
    const indent = p.bullet ? style.bullet_indent_pt * (p.level + 1) : 0;
    const ref: TextRef = { ...frameRef(f), index: i };
    return (
      <div key={i} className="para"
        style={{
          fontSize: p.font_pt, lineHeight: String(style.line_spacing),
          fontWeight: p.bold ? 700 : 400, color: `#${p.color}`, textAlign: p.align,
          paddingLeft: indent, position: "relative",
          marginTop: p.bullet && i > 0 ? style.bullet_gap_pt : 0,
        }}
        onClick={(e) => {
          e.stopPropagation();
          if (suppressClick.current) { suppressClick.current = false; return; }
          if (!textEditable(f)) { onSelect(frameRef(f)); return; }
          startEdit(ref, p.text);
        }}
      >
        {p.bullet && (
          <span aria-hidden style={{ position: "absolute", left: indent - style.bullet_indent_pt }}>
            {style.bullet_char}
          </span>
        )}
        {p.lines.map((line, j) => (
          <div key={j} style={{ whiteSpace: "pre" }}>{p.line_runs?.[j]?.length ?
            p.line_runs[j].map((run,k)=><span key={k} style={{fontWeight:run.bold?700:400,color:`#${run.color}`}}>{run.text}</span>) : line || " "}</div>
        ))}
      </div>
    );
  };

  const cellFill = (t: NonNullable<Frame["table"]>, rowIdx: number, col: number) => {
    if (rowIdx === -1) return `#${t.header_fills?.length ? t.header_fills[col] : t.header_fill}`;
    return t.body_fills?.length ? `#${t.body_fills[col]}` : TABLE_BODY_FILL;
  };

  const renderTable = (f: Frame) => {
    const t = f.table;
    if (!t) return null;
    const base = frameRef(f);
    const renderRow = (cells: string[][], texts: string[], rowIdx: number, bold: boolean) => (
      <div key={rowIdx} style={{
        display: "flex", height: t.row_heights_pt[rowIdx + 1],
        fontWeight: bold ? 700 : 400,
      }}>
        {cells.map((lines, col) => (
          <div key={col} style={{
            width: t.col_widths_pt[col], boxSizing: "border-box",
            // 칸 채움은 라이터와 같은 규칙이다: 칸별 목록이 있으면 그것을, 없으면 머리행만 단일 색, 본문은 표 스타일의 채움
            background: cellFill(t, rowIdx, col),
            padding: `${style.table_cell_pad_y_pt}px ${style.table_cell_pad_x_pt}px`,
            // 칸은 오른쪽과 아래 선만 그린다. 네 변을 다 그리면 이웃 칸의 선이 맞닿아 안쪽 선이 2pt가 된다. 표 스타일은
            // 안쪽과 바깥 선이 모두 1pt다 (D3c-3 리뷰 F20)
            borderRight: `1px solid ${TABLE_LINE}`, borderBottom: `1px solid ${TABLE_LINE}`, fontSize: t.font_pt,
            lineHeight: String(style.line_spacing), overflow: "hidden",
          }}
            onClick={(e) => {
              e.stopPropagation();
              if (suppressClick.current) { suppressClick.current = false; return; }
              startEdit({ ...base, row: rowIdx, col }, texts[col]);
            }}
          >
            {lines.map((line, j) => <div key={j} style={{ whiteSpace: "pre" }}>{line || " "}</div>)}
          </div>
        ))}
      </div>
    );
    return (
      <div style={{ borderTop: `1px solid ${TABLE_LINE}`, borderLeft: `1px solid ${TABLE_LINE}` }}>
        {renderRow(t.header_lines, t.header, -1, true)}
        {t.cell_lines.map((rowLines, r) => renderRow(rowLines, t.rows[r], r, false))}
      </div>
    );
  };

  const onFrameKey = (e: React.KeyboardEvent, f: Frame) => {
    const ref = frameRef(f);
    const spec = keys[ref.slot];
    if (e.key === "Enter") {
      e.preventDefault();
      onSelect(ref);
      const first = textEditable(f) ? textStops(f)[0] : undefined;
      if (first && editable) setEditing({ ref: first.ref, text: first.text, origin: first.text });
      return;
    }
    if (e.key === " ") { e.preventDefault(); onSelect(ref); return; }  // 프레임은 div라 Space의 화면 내림을 막는다
    if (e.key === "Escape") { e.preventDefault(); onSelect(null); return; }  // 모드는 닫지 않는다 (리뷰 화면 S36)
    const arrows: Record<string, [number, number]> = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };
    const isDelete = e.key === "Delete" || e.key === "Backspace";  // Mac의 delete 키는 Backspace다
    if (!isDelete && !arrows[e.key]) return;
    e.preventDefault();
    if (!mode) { onNeedMode?.(); return; }
    if (isDelete) { if (spec?.kinds.includes("hide")) onHide?.(ref.slot); return; }
    if (!spec?.kinds.includes("move")) return;
    const [ux, uy] = arrows[e.key];
    const step = e.shiftKey ? ARROW_STEP.large : ARROW_STEP.small;
    const edit = edits?.[ref.slot];
    onMove?.(ref.slot, (edit?.dx_pt ?? 0) + ux * step, (edit?.dy_pt ?? 0) + uy * step, { coalesce: e.repeat ? "continue" : "start" });
  };

  const boxes = displayBoxes(slide, edits, pageW, pageH);
  // 끄는 동안에도 저장할 때와 같은 규칙으로 페이지 안에 잘라 그린다. 놓을 때만 자르면 보이는 자리와 저장되는 자리가
  // 달랐다 (α 리뷰 A12)
  const dragged = drag ? displayBoxes(slide, { ...edits, [drag.key]: { ...(edits?.[drag.key] ?? {}),
    dx_pt: (edits?.[drag.key]?.dx_pt ?? 0) + drag.dx, dy_pt: (edits?.[drag.key]?.dy_pt ?? 0) + drag.dy } }, pageW, pageH) : null;
  // 경고와 요소의 대응은 서버와 같은 규칙이다(접두어 규칙은 step0이 step0_labels의 경고까지 표시했다, 재리뷰 RR22)
  const frameKeySet = slide.frames.map(frameKey);
  const warnedKeys = new Set(slide.warnings.map((w) => warningKey(w.slot, frameKeySet)).filter(Boolean));
  const tabbedKeys = new Set<string>();
  const editingFrame = editing ? frameOf(editing.ref) : undefined;
  const editingBox = editingFrame ? boxes.get(editingFrame.name) : undefined;

  return (
    <div ref={holder} className="preview-holder" style={{ height: pageH * scale, position: "relative" }}>
      <div ref={canvas} tabIndex={-1} aria-label="슬라이드 미리보기"
        className={[editable ? "preview-canvas" : "preview-canvas stale", mode ? "direct-edit" : ""].join(" ").trim()}
        style={{
          width: pageW, height: pageH, position: "relative", background: "#ffffff",
          transform: `scale(${scale})`, transformOrigin: "top left",
          fontFamily: `"${style.korean_font}", sans-serif`,
          // 화면 토큰(styles.css의 본문 색)을 물려받지 않게 프리셋 글자색을 명시한다 (D2a-4).
          // 표 칸은 글자색을 따로 정하지 않아 이 값을 쓰고, PPTX와 같은 색이 된다
          color: `#${style.text_color}`,
        }}
        onClick={() => { setEditing(null); onSelect(null); }}
        onPointerDownCapture={() => {
          pointerFocus.current = true;
          // 새 누름의 클릭은 거르지 않는다. 손잡이 끌기의 클릭은 손잡이로 가서 깃발이 남아 다음 클릭을 먹었다 (D3c-3 리뷰 F2)
          suppressClick.current = false;
          // 캔버스 밖에서 놓아도 깃발을 내린다. 남으면 그 뒤 키보드 초점이 요소를 고르지 않았다 (D3c-3 리뷰 F6)
          const release = () => {
            pointerFocus.current = false;
            window.removeEventListener("pointerup", release, true);
            window.removeEventListener("pointercancel", release, true);
          };
          window.addEventListener("pointerup", release, true);
          window.addEventListener("pointercancel", release, true);
        }}
      >
        {slide.diagram && <DiagramPreview page={slide.diagram} style={style} />}
        {slide.frames.map((f) => {
          const ref = frameRef(f);
          const box = boxes.get(f.name) ?? { x: f.x, y: f.y, w: f.w, h: f.h, hidden: !!f.hidden };
          // 직접 수정으로 숨긴 요소는 그리지 않는다. 숨김은 지금 덱으로 정하므로 다시 보이기는 새 계획을 기다리지 않는다
          if (box.hidden) return null;
          const isPageNumber = f.name.endsWith(":page_number");
          const spec = keys[ref.slot];
          const boxed = f.fill != null || f.border != null;
          const isSelected = selected?.chapterId === ref.chapterId && selected.slot === ref.slot;
          const dragging = drag?.key === ref.slot;
          // 요소 하나에 Tab 정지 하나다. 표 묶음은 첫 프레임만, 쪽 번호는 정지에서 뺀다 (재리뷰 RR12)
          const tabStop = !isPageNumber && !tabbedKeys.has(ref.slot);
          if (tabStop) tabbedKeys.add(ref.slot);
          // 배지가 있는 카드는 첫 문단이 배지 숫자다. 배지는 소제목보다 작은 글자이므로 그때는 소제목을 쓴다 (D3c-3 리뷰 F21)
          const nameSource = /^card\d+$/.test(ref.slot) && f.paras.length > 1 && f.paras[0].font_pt < f.paras[1].font_pt
            ? f.paras[1] : f.paras[0];
          const firstLine = f.table ? f.table.header.join(", ") : (nameSource?.lines[0] ?? nameSource?.text ?? "");
          // 접근성 트리에는 요소 하나에 버튼 하나다. 표 묶음의 나머지 프레임(차트 조건 문구)은 이름을 달지 않는다
          const labelled = !isPageNumber && tabStop;
          const bodyDrag = mode && spec?.drag === "body" && spec.kinds.includes("move");
          return (
            <div key={f.name} data-frame={f.name} data-key={ref.slot}
              role={labelled ? "button" : undefined}
              tabIndex={isPageNumber ? undefined : tabStop ? 0 : -1}
              // 고름은 눌림 상태가 아니라 지금 항목이다 (D3c-3 리뷰 F21)
              aria-current={labelled && isSelected ? "true" : undefined}
              aria-label={labelled ? `${roleName(ref.slot, template)}${firstLine ? `, ${firstLine}` : ""}` : undefined}
              className={[
                "frame",
                warnedKeys.has(ref.slot) ? "warned" : "",
                isSelected ? "selected" : "",
                dragging ? "dragging" : "",
              ].join(" ").trim()}
              style={{
                position: "absolute", left: dragging ? dragged!.get(f.name)!.x : box.x, top: dragging ? dragged!.get(f.name)!.y : box.y,
                width: f.w, height: f.h,
                boxSizing: "border-box",
                background: f.fill ? `#${f.fill}` : undefined,
                // 테두리 두께는 프레임 값이 있으면 그것을 쓴다. 라이터도 같은 규칙이다
                border: f.border
                  ? `${f.border_width_pt ?? style.border_width_pt}px solid #${f.border}`
                  : undefined,
                // 모서리 반경. CSS 는 반경 합이 변을 넘으면 브라우저가 비례 축소하므로,
                // 짧은 변의 절반 이상이면 라이터의 조정값 0.5(알약, 정원)와 같은 모양이 된다
                borderRadius: f.radius_pt != null ? f.radius_pt : undefined,
                padding: boxed ? style.box_padding_pt : 0,
                display: f.valign === "middle" ? "flex" : undefined,
                flexDirection: f.valign === "middle" ? "column" : undefined,
                justifyContent: f.valign === "middle" ? "center" : undefined,
                touchAction: bodyDrag ? "none" : undefined,  // 손가락 끌기가 화면 이동으로 취소되지 않게 (리뷰 화면 S27)
                cursor: bodyDrag ? "move" : undefined,
              }}
              onFocus={() => { if (!isPageNumber && !isSelected && !pointerFocus.current) onSelect(ref); }}  // 초점과 선택은 늘 같다
              onKeyDown={(e) => { if (e.target === e.currentTarget) onFrameKey(e, f); }}
              onPointerDown={bodyDrag ? (e) => startDrag(e, ref.slot) : undefined}
              {...(bodyDrag ? dragHandlers : {})}
              onClick={(e) => {
                e.stopPropagation();
                if (suppressClick.current) { suppressClick.current = false; return; }
                if (!isPageNumber) onSelect(ref);
              }}
            >
              {f.chart ? <ChartPreview frame={f} /> : f.table ? renderTable(f) : f.paras.map((p, i) => renderPara(f, p, i))}
              {mode && isSelected && spec?.drag === "handle" && spec.kinds.includes("move") && (
                // 글상자는 손잡이로만 끈다. 본체 누름은 문구 수정이다 (화면 시안, 계획 리뷰 화면 S4). 포인터 전용이라 Tab에서 뺀다
                // 손잡이는 초점을 받지 않는다. 누르면 초점이 바깥 프레임에 가서 끈 뒤에도 방향키와 Delete가 그 요소에 걸린다
                // (D3c-3 리뷰 F3)
                <div className="move-handle" aria-hidden style={{ touchAction: "none" }}
                  onClick={(e) => e.stopPropagation()}
                  onPointerDown={(e) => startDrag(e, ref.slot)} {...dragHandlers}>↕</div>
              )}
            </div>
          );
        })}
        {editing && editingBox && (
          <textarea autoFocus aria-label="내용 수정" className="inline-editor"
            // 입력란은 고친 프레임 자리에 연다 (계획 리뷰 화면 S16)
            style={{ left: editingBox.x, top: editingBox.y, width: Math.max(editingBox.w, 120) }}
            value={editing.text}
            onClick={(e) => e.stopPropagation()}
            onChange={(e) => setEditing({ ...editing, text: e.target.value })}
            onBlur={() => { if (!cancelling.current) commit(); }}
            onKeyDown={(e) => {
              // 한글 조합 중의 Enter는 조합을 끝내는 키라 확정하지 않는다 (계획 리뷰 화면 S28)
              if (e.nativeEvent.isComposing) return;
              if (e.key === "Enter") { e.preventDefault(); if (!focusFrameOf(editing.ref)) commit(); }
              if (e.key === "Tab") { e.preventDefault(); stepEdit(e.shiftKey ? -1 : 1); }
              if (e.key === "Escape") {
                e.preventDefault(); e.stopPropagation();
                cancelling.current = true;  // 초점을 옮길 때 생기는 blur가 확정하지 않게 한다
                focusFrameOf(editing.ref);
                cancelling.current = false;
                setEditing(null);
              }
            }}
          />
        )}
      </div>
      {!mode && hiddenCount > 0 && onShowHidden && (
        <button className="btn-text hidden-count" onClick={onShowHidden}>숨긴 요소 {hiddenCount}개</button>
      )}
    </div>
  );
}
