import { useCallback, useEffect, useRef, useState } from "react";
import { UnsavedChangeBackup } from "../editor/UnsavedChangeBackup";
import type { Deck, ProjectInfo, TemplateName } from "../api/client";
import { ChapterList } from "../editor/ChapterList";
import { DesignPanel } from "../editor/DesignPanel";
import { GeneratePanel } from "../editor/GeneratePanel";
import { Preview, type FrameRef, type TextRef } from "../editor/Preview";
import { PropertyPanel } from "../editor/PropertyPanel";
import { applyTemplateSwitch } from "../editor/templateSwitch";
import { applyTextEdit, reorderChapters } from "../editor/slotOps";
import { useDeckEditor, type Timings } from "../state/useDeckEditor";
import { NumericReviewPanel } from "./NumericReviewPanel";
import { SemanticReviewPanel } from "./SemanticReviewPanel";
import { DiagramAuthoringDialog } from "../editor/DiagramAuthoringDialog";
import { createDiagramDraft, editDiagramDraft, type DiagramDraft } from "../editor/diagramDraft";

export function EditorScreen({
  project, deck: initialDeck, onDeckChange, onEditorReady, onDirtyChange, onConflictHint, onBusyChange, timings,
}: {
  project: ProjectInfo;
  deck: Deck;
  onDeckChange: (d: Deck) => void;
  onEditorReady?: (flush: (() => Promise<boolean>) | null) => void;  // 부모(ProjectView)가 내보내기와 탭 전환 전에 플러시하도록
  onDirtyChange?: (dirty: boolean) => void;  // 저장 대기/저장 중/저장 실패이면 참 (부모의 beforeunload 경고용)
  onConflictHint?: () => void;  // 412 를 만났음을 부모에 알린다. 배너는 이 화면이 직접 띄우므로 부모는 일반 배너만 생략한다
  onBusyChange?: (busy: boolean) => void;
  timings?: Timings;
}) {
  const editor = useDeckEditor(project.name, initialDeck, onDeckChange, timings, onConflictHint);
  const chapters = editor.deck.structure.chapters;
  const [chapterId, setChapterId] = useState<string | null>(chapters[0]?.id ?? null);
  const [selected, setSelected] = useState<FrameRef | null>(null);
  const [diagramDraft, setDiagramDraft] = useState<DiagramDraft | null>(null);
  const [diagramBusy, setDiagramBusy] = useState(false);
  const [templateBusy, setTemplateBusy] = useState(false);
  const templateBusyRef = useRef(false);
  const current = useRef({deck: editor.deck, chapterId, mounted: true});
  current.current = {...current.current, deck: editor.deck, chapterId};
  useEffect(() => { current.current.mounted = true; return () => {current.current.mounted = false;}; }, []);
  const switchTemplate = async (id: string, to: TemplateName, base: Deck) => {
    if (templateBusyRef.current || editor.conflict || current.current.deck !== base
      || base.structure.chapters.find(c => c.id === id)?.template === to) return;
    templateBusyRef.current = true;
    setTemplateBusy(true); onBusyChange?.(true);
    try {
      if (!await editor.flushSave()) return;
      if (!current.current.mounted || current.current.deck !== base || current.current.chapterId !== id) return;
      editor.apply(d => d === base ? applyTemplateSwitch(d, id, to).deck : d, {snapshot: true});
      setSelected(null);
    } finally {
      templateBusyRef.current = false;
      if (current.current.mounted) setTemplateBusy(false);
      onBusyChange?.(false);
    }
  };
  const diagramCalls = useRef(0);
  const onDiagramBusyChange = useCallback((busy: boolean) => {
    // 닫힌 작성창도 자기 호출이 끝날 때 해제한다. 다른 호출이 있으면 마지막 소유자까지 잠금을 유지한다.
    diagramCalls.current += busy ? 1 : -1;
    const active = diagramCalls.current > 0;
    setDiagramBusy(active); onBusyChange?.(active);
  }, [onBusyChange]);
  const diagramDraftRef = useRef(diagramDraft);
  diagramDraftRef.current = diagramDraft;

  // 작성 중인 의미 입력은 아직 Deck이 아니다. 이탈/복원/내보내기로 조용히 버리지 않는다.
  const flush = useCallback(async () => {
    if (diagramDraftRef.current || diagramCalls.current > 0 || templateBusyRef.current) return false;
    const saved = await editor.flushSave();
    // 저장을 기다리는 동안 새로 연 작성 창도 보호한다. 시작 시점의 상태만 검사하면 입력을 버리고 이동한다.
    return saved && diagramDraftRef.current === null && diagramCalls.current === 0 && !templateBusyRef.current;
  }, [editor.flushSave]);

  useEffect(() => {
    onEditorReady?.(flush);
    // 언마운트 시 등록을 해제한다: 다음 화면이 이 화면의 낡은 flush 함수를 계속 들고 있으면
    // 탭 전환 플러시가 이미 사라진 편집기를 가리켜 무의미해진다 (2026-08-29 최종 리뷰 발견)
    return () => onEditorReady?.(null);
  }, [onEditorReady, flush]);

  useEffect(() => {
    onDirtyChange?.(diagramDraft !== null || editor.saveState !== "저장됨");
  }, [diagramDraft, editor.saveState, onDirtyChange]);

  // 되돌린 서버 덱(reloadFromServer)에 지금 보고 있는 장이 없으면 첫 장으로 되돌아간다
  useEffect(() => {
    if (!chapters.some((c) => c.id === chapterId)) {
      setChapterId(chapters[0]?.id ?? null);
    }
  }, [chapters, chapterId]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (diagramDraft || diagramBusy || templateBusyRef.current) return;
      // 인라인 편집 입력 중에는 브라우저 네이티브 undo가 동작해야 하므로 덱 undo가 끼어들지 않는다
      // (2026-08-29 최종 리뷰 발견)
      const t = e.target as HTMLElement;
      if (t.tagName === "INPUT" || t.tagName === "TEXTAREA") return;
      if (!(e.ctrlKey || e.metaKey)) return;
      const key = e.key.toLowerCase();
      if (key === "z" && !e.shiftKey) { e.preventDefault(); editor.undo(); }
      if (key === "y" || (key === "z" && e.shiftKey)) { e.preventDefault(); editor.redo(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [editor.undo, editor.redo, diagramDraft, diagramBusy]);

  const slide = editor.plan?.slides.find((s) => s.chapter_id === chapterId) ?? null;
  const commitText = (ref: TextRef, text: string) =>
    editor.apply((d) => applyTextEdit(d, ref, text));

  return (
    <>
    {diagramBusy && !diagramDraft && <p role="status">도식 AI 응답을 기다리고 있습니다. 작성창을 닫아도 이미 전송된 요청은 계속될 수 있습니다.</p>}
    {templateBusy && <p role="status">전환 전 내용을 저장하고 있습니다.</p>}
    {editor.reloading && <p role="status">변경을 보존하고 서버 내용을 다시 읽고 있습니다.</p>}
    <div className="editor-screen" inert={diagramDraft !== null || diagramBusy || templateBusy || editor.reloading}>
      <aside className="editor-left">
        <ChapterList deck={editor.deck} plan={editor.plan} selected={chapterId}
          onSelect={(id) => { setChapterId(id); setSelected(null); }}
          onReorder={(from, to) => editor.apply((d) => reorderChapters(d, from, to))} />
        <button disabled={editor.conflict || diagramBusy} onClick={() => setDiagramDraft(createDiagramDraft(editor.deck))}>도식 추가</button>
      </aside>
      <section className="editor-center">
        {editor.saveError && (
          <p role="alert">
            {editor.saveError}{" "}
            {editor.conflict ? (
              <button disabled={editor.reloading} onClick={() => void editor.reloadFromServer()}>서버 내용으로 되돌리기</button>
            ) : (
              editor.saveState === "저장 실패" && (
                <button onClick={() => void editor.retrySave()}>다시 저장</button>
              )
            )}
          </p>
        )}
        {editor.preserveFailure && (
          <div role="alert">
            <p>
              변경을 보존하지 못해 서버 내용으로 되돌리지 않았습니다. ({editor.preserveFailure.message}){" "}
              아래 내용을 복사해 두거나, 그래도 되돌리면 이 화면의 변경은 사라집니다.
            </p>
            <UnsavedChangeBackup text={editor.preserveFailure.deckJson} label="보존하지 못한 변경" />
            <button disabled={editor.reloading} onClick={() => {
              if (window.confirm("보존하지 못한 변경은 사라집니다. 서버 내용으로 되돌릴까요?")) {
                void editor.reloadFromServer({ discardUnsaved: true });
              }
            }}>그래도 서버 내용으로 되돌리기</button>
          </div>
        )}
        {editor.preservedDraft && (
          <p role="status">
            다른 곳에서 먼저 저장해 서버 내용으로 되돌렸습니다. 되돌리기 전의 변경은 보존했습니다
            ({editor.preservedDraft.saved_at.slice(0, 16).replace("T", " ")}). 스냅샷 복구 화면의
            "충돌로 보존한 변경"에서 보거나 복원하거나 지울 수 있습니다.{" "}
            <button onClick={editor.dismissPreservedDraft}>닫기</button>
          </p>
        )}
        {editor.measureError && (
          <p role="alert">{editor.measureError}{" "}
            <button onClick={editor.remeasure}>다시 그리기</button>
          </p>
        )}
        {slide && editor.plan ? (
          // 2026-08-29 태스크 11 리뷰 이월: 장 전환 시 편집창 잔존 방지 리마운트
          // 낡은 계획(덱이 바뀐 뒤 새 계획이 오기 전)으로는 편집을 열지 않는다 (2026-09-03 FC-05)
          <Preview key={slide.chapter_id} slide={slide} style={editor.plan.style}
            pageW={editor.plan.page_width_pt} pageH={editor.plan.page_height_pt}
            editable={!editor.planStale}
            selected={selected} onSelect={setSelected} onCommitText={commitText} />
        ) : editor.measureError ? (
          <p>미리보기를 만들지 못했습니다. 위 오류를 확인한 뒤 다시 그려 주세요.</p>
        ) : editor.deck.slides.some(s => s.chapter_id === chapterId) ? (
          <p>미리보기를 계산하고 있습니다.</p>
        ) : chapters.length === 0 ? (
          <p>아직 장이 없습니다. 왼쪽의 도식 추가로 시작하거나 구조안 탭에서 내용을 생성해 주세요.</p>
        ) : (
          <p>이 장은 아직 내용이 없습니다. 구조안 탭에서 생성해 주세요.</p>
        )}
      </section>
      <aside className="editor-right">
        <p>저장 상태: {editor.saveState}</p>
        <button onClick={editor.undo} disabled={!editor.canUndo}>되돌리기 (Ctrl+Z)</button>
        <button onClick={editor.redo} disabled={!editor.canRedo}>다시 실행</button>
        {chapterId && (
          <PropertyPanel deck={editor.deck} chapterId={chapterId} onApply={editor.apply}
            onEditDiagram={() => setDiagramDraft(editDiagramDraft(editor.deck, chapterId))}
            diagramDisabled={editor.conflict} onSwitchTemplate={(id,to,base) => void switchTemplate(id,to,base)} />
        )}
        <DesignPanel deck={editor.deck} onApply={editor.apply} />
        <NumericReviewPanel projectName={project.name} deck={editor.deck} />
        <SemanticReviewPanel projectName={project.name} deck={editor.deck} />
        {chapterId && (
          <GeneratePanel project={project} deck={editor.deck} chapterId={chapterId}
            onReplace={editor.replace} />
        )}
        {slide && slide.warnings.length > 0 && (
          <section>
            <h3>분량 경고</h3>
            <ul>{slide.warnings.map((w, i) => <li key={i}>{w.message}</li>)}</ul>
          </section>
        )}
      </aside>
    </div>
    {diagramDraft && <DiagramAuthoringDialog projectName={project.name} deck={editor.deck} initialDraft={diagramDraft} blocked={editor.conflict}
      flushBeforeCheck={editor.flushSave} onConflict={editor.reportConflict} onBusyChange={onDiagramBusyChange}
      onCancel={() => setDiagramDraft(null)} onApply={(candidate, base, id, persisted) => {
        if (editor.deck !== base || editor.conflict) return;
        if(persisted) editor.acceptSaved(candidate); else editor.replace(candidate);
        setChapterId(id); setSelected(null); setDiagramDraft(null);
      }} />}
    </>
  );
}
