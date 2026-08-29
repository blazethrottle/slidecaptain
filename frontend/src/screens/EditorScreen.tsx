import { useEffect, useState } from "react";
import type { Deck, ProjectInfo } from "../api/client";
import { ChapterList } from "../editor/ChapterList";
import { Preview, type FrameRef, type TextRef } from "../editor/Preview";
import { PropertyPanel } from "../editor/PropertyPanel";
import { applyTextEdit, reorderChapters } from "../editor/slotOps";
import { useDeckEditor, type Timings } from "../state/useDeckEditor";

export function EditorScreen({ project, deck: initialDeck, onDeckChange, onEditorReady, timings }: {
  project: ProjectInfo;
  deck: Deck;
  onDeckChange: (d: Deck) => void;
  onEditorReady?: (flush: () => Promise<void>) => void;  // 부모(ProjectView)가 내보내기 전에 플러시하도록
  timings?: Timings;
}) {
  const editor = useDeckEditor(project.name, initialDeck, onDeckChange, timings);
  const chapters = editor.deck.structure.chapters;
  const [chapterId, setChapterId] = useState<string | null>(chapters[0]?.id ?? null);
  const [selected, setSelected] = useState<FrameRef | null>(null);

  useEffect(() => {
    onEditorReady?.(editor.flushSave);
  }, [onEditorReady, editor.flushSave]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.ctrlKey || e.metaKey)) return;
      const key = e.key.toLowerCase();
      if (key === "z" && !e.shiftKey) { e.preventDefault(); editor.undo(); }
      if (key === "y" || (key === "z" && e.shiftKey)) { e.preventDefault(); editor.redo(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [editor.undo, editor.redo]);

  const slide = editor.plan?.slides.find((s) => s.chapter_id === chapterId) ?? null;
  const commitText = (ref: TextRef, text: string) =>
    editor.apply((d) => applyTextEdit(d, ref, text));

  return (
    <div className="editor-screen">
      <aside className="editor-left">
        <ChapterList deck={editor.deck} plan={editor.plan} selected={chapterId}
          onSelect={(id) => { setChapterId(id); setSelected(null); }}
          onReorder={(from, to) => editor.apply((d) => reorderChapters(d, from, to))} />
      </aside>
      <section className="editor-center">
        {editor.error && <p role="alert">{editor.error}</p>}
        {slide && editor.plan ? (
          // 2026-08-29 태스크 11 리뷰 이월: 장 전환 시 편집창 잔존 방지 리마운트
          <Preview key={slide.chapter_id} slide={slide} style={editor.plan.style}
            pageW={editor.plan.page_width_pt} pageH={editor.plan.page_height_pt}
            selected={selected} onSelect={setSelected} onCommitText={commitText} />
        ) : (
          <p>이 장은 아직 내용이 없습니다. 구조안 탭에서 생성해 주세요.</p>
        )}
      </section>
      <aside className="editor-right">
        <p>저장 상태: {editor.saveState}</p>
        <button onClick={editor.undo} disabled={!editor.canUndo}>되돌리기 (Ctrl+Z)</button>
        <button onClick={editor.redo} disabled={!editor.canRedo}>다시 실행</button>
        {chapterId && (
          <PropertyPanel deck={editor.deck} chapterId={chapterId} onApply={editor.apply} />
        )}
        {slide && slide.warnings.length > 0 && (
          <section>
            <h3>분량 경고</h3>
            <ul>{slide.warnings.map((w, i) => <li key={i}>{w.message}</li>)}</ul>
          </section>
        )}
      </aside>
    </div>
  );
}
