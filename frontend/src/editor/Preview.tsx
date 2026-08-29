import { useLayoutEffect, useRef, useState } from "react";
import type { Frame, Para, SlidePlan, RenderPlan } from "../api/client";

export type FrameRef = { chapterId: string; slot: string };
export type TextRef = FrameRef & { index?: number; row?: number; col?: number };
type Style = RenderPlan["style"];

const TABLE_LINE = "#D0D7E2";  // 화면 전용 경계선 (렌더 계획에 표 경계색 없음)

function frameRef(f: Frame): FrameRef {
  const [chapterId, slot] = f.name.split(":");
  return { chapterId, slot };
}

function isWarned(slide: SlidePlan, slot: string): boolean {
  return slide.warnings.some((w) => w.slot === slot || w.slot.startsWith(`${slot}_`));
}

export function Preview({ slide, style, pageW, pageH, selected, onSelect, onCommitText }: {
  slide: SlidePlan;
  style: Style;
  pageW: number;
  pageH: number;
  selected: FrameRef | null;
  onSelect: (ref: FrameRef | null) => void;
  onCommitText: (ref: TextRef, text: string) => void;
}) {
  const holder = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(1);
  const [editing, setEditing] = useState<{ ref: TextRef; text: string; origin: string } | null>(null);

  useLayoutEffect(() => {
    const measure = () => {
      const w = holder.current?.clientWidth ?? 0;
      setScale(w > 0 ? w / pageW : 1);
    };
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [pageW]);

  const commit = () => {
    // 변경 없는 확정(문단 클릭 후 Enter만 누른 경우 등)은 언두와 저장을 오염시키지 않는다
    // (2026-08-29 최종 리뷰 발견)
    if (editing && editing.text !== editing.origin) onCommitText(editing.ref, editing.text);
    setEditing(null);
  };

  const startEdit = (ref: TextRef, text: string) => {
    const frame = { chapterId: ref.chapterId, slot: ref.slot };
    if (selected?.chapterId === frame.chapterId && selected.slot === frame.slot) {
      setEditing({ ref, text, origin: text });
    } else {
      onSelect(frame);
    }
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
          if (f.name.endsWith(":page_number")) return;
          startEdit(ref, p.text);
        }}
      >
        {p.bullet && (
          <span aria-hidden style={{ position: "absolute", left: indent - style.bullet_indent_pt }}>
            {style.bullet_char}
          </span>
        )}
        {p.lines.map((line, j) => (
          <div key={j} style={{ whiteSpace: "pre" }}>{line || " "}</div>
        ))}
      </div>
    );
  };

  const renderTable = (f: Frame) => {
    const t = f.table;
    if (!t) return null;
    const base = frameRef(f);
    const renderRow = (cells: string[][], texts: string[], rowIdx: number, bold: boolean) => (
      <div key={rowIdx} style={{
        display: "flex", height: t.row_heights_pt[rowIdx + 1],
        background: rowIdx === -1 ? `#${t.header_fill}` : undefined,
        fontWeight: bold ? 700 : 400,
      }}>
        {cells.map((lines, col) => (
          <div key={col} style={{
            width: t.col_widths_pt[col], boxSizing: "border-box",
            padding: `${style.table_cell_pad_y_pt}px ${style.table_cell_pad_x_pt}px`,
            border: `0.5px solid ${TABLE_LINE}`, fontSize: t.font_pt,
            lineHeight: String(style.line_spacing), overflow: "hidden",
          }}
            onClick={(e) => {
              e.stopPropagation();
              startEdit({ ...base, row: rowIdx, col }, texts[col]);
            }}
          >
            {lines.map((line, j) => <div key={j} style={{ whiteSpace: "pre" }}>{line || " "}</div>)}
          </div>
        ))}
      </div>
    );
    return (
      <div>
        {renderRow(t.header_lines, t.header, -1, true)}
        {t.cell_lines.map((rowLines, r) => renderRow(rowLines, t.rows[r], r, false))}
      </div>
    );
  };

  return (
    <div ref={holder} className="preview-holder">
      <div className="preview-canvas"
        style={{
          width: pageW, height: pageH, position: "relative", background: "#ffffff",
          transform: `scale(${scale})`, transformOrigin: "top left",
          fontFamily: `"${style.korean_font}", sans-serif`,
        }}
        onClick={() => { setEditing(null); onSelect(null); }}
      >
        {slide.frames.map((f) => {
          const ref = frameRef(f);
          const boxed = f.fill != null || f.border != null;
          const isSelected = selected?.chapterId === ref.chapterId && selected.slot === ref.slot;
          return (
            <div key={f.name} data-frame={f.name}
              className={[
                "frame",
                isWarned(slide, ref.slot) ? "warned" : "",
                isSelected ? "selected" : "",
              ].join(" ").trim()}
              style={{
                position: "absolute", left: f.x, top: f.y, width: f.w, height: f.h,
                boxSizing: "border-box",
                background: f.fill ? `#${f.fill}` : undefined,
                border: f.border ? `${style.border_width_pt}px solid #${f.border}` : undefined,
                padding: boxed ? style.box_padding_pt : 0,
                display: f.valign === "middle" ? "flex" : undefined,
                flexDirection: f.valign === "middle" ? "column" : undefined,
                justifyContent: f.valign === "middle" ? "center" : undefined,
              }}
              onClick={(e) => {
                e.stopPropagation();
                if (!f.name.endsWith(":page_number")) onSelect(ref);
              }}
            >
              {f.table ? renderTable(f) : f.paras.map((p, i) => renderPara(f, p, i))}
            </div>
          );
        })}
        {editing && (
          <textarea autoFocus aria-label="내용 수정" className="inline-editor"
            value={editing.text}
            onClick={(e) => e.stopPropagation()}
            onChange={(e) => setEditing({ ...editing, text: e.target.value })}
            onBlur={commit}
            onKeyDown={(e) => {
              if (e.key === "Enter") { e.preventDefault(); commit(); }
              if (e.key === "Escape") setEditing(null);
            }}
          />
        )}
      </div>
    </div>
  );
}
