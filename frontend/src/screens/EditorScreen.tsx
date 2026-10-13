import { useCallback, useEffect, useRef, useState } from "react";
import { UnsavedChangeBackup } from "../editor/UnsavedChangeBackup";
import { formatSavedAt } from "../api/time";
import { saveStatusKind, type SaveStatus } from "../ui/StatusIndicator";
import type { Deck, ProjectInfo, TemplateName } from "../api/client";
import { ChapterList } from "../editor/ChapterList";
import { DesignPanel } from "../editor/DesignPanel";
import { GeneratePanel } from "../editor/GeneratePanel";
import { Preview, type FrameRef, type TextRef } from "../editor/Preview";
import { PropertyPanel } from "../editor/PropertyPanel";
import { applyTemplateSwitch } from "../editor/templateSwitch";
import { applyTextEdit, reorderChapters } from "../editor/slotOps";
import { useDeckEditor, type Coalesce, type Timings } from "../state/useDeckEditor";
import { NumericReviewPanel } from "./NumericReviewPanel";
import { SemanticReviewPanel } from "./SemanticReviewPanel";
import { DiagramAuthoringDialog } from "../editor/DiagramAuthoringDialog";
import { createDiagramDraft, editDiagramDraft, type DiagramDraft } from "../editor/diagramDraft";
import { BATCH_DISCARD_CONFIRM, BATCH_READ_ONLY_NOTICE } from "../ui/ActiveJobNotice";
import { DirectEditPanel } from "../editor/DirectEditPanel";
import { clampOffset, displayBoxes, editElement, frameKey, frameKeys, roleName, withObject } from "../editor/directEdit";

const NEED_MODE = "직접 수정을 누르면 요소를 옮기거나 숨길 수 있습니다.";
// 목록 편집 직후 옛 미리보기가 남은 동안은 그려진 항목과 덱의 항목이 다르다 (D3c-3 리뷰 F10)
const REDRAWING = "미리보기를 새로 그리는 중입니다. 다 그린 뒤 다시 시도해 주세요.";
// 직접 수정을 열 수 없는 상태(읽기 전용, 충돌, 다시 읽기 등)에서 모드가 필요한 조작을 했다 (D3c-3 리뷰 F11)
const MODE_BLOCKED = "지금은 직접 수정을 열 수 없습니다. 읽기 전용이나 충돌, 다시 읽기가 끝난 뒤 다시 시도해 주세요.";
const SWITCHED = "이 화면에서 되돌리기로 되찾을 수 있습니다. 전환 직전 상태는 스냅샷으로도 남습니다.";
const MODE_GUIDE = "요소를 고르세요. 문구는 다시 누르거나 Enter, 위치는 손잡이나 방향키(Shift는 10pt)로 고칩니다. 숨기기는 Delete입니다.";

// 서버가 저장한 결과를 화면이 받지 못했다(요청 중 화면 덱이 바뀌었다). 다음 자동 저장이 그 결과를 덮지 않게 충돌로 멈춘다
// (D3c-5 리뷰 F1). 도식 작성 창의 저장된 반영도 같은 문구를 쓴다
const SAVED_ELSEWHERE_CONFLICT = "반영한 내용은 서버에 저장됐지만 그사이 이 화면이 바뀌어 받지 않았습니다. '서버 내용으로 되돌리기'를 누르면 이 화면의 내용을 보존한 뒤 새 문서를 읽습니다.";
const BATCH_END_CONFLICT = "생성한 장이 문서에 반영되어 이 화면의 고친 내용은 저장하지 않았습니다. '서버 내용으로 되돌리기'를 누르면 고친 내용을 보존한 뒤 새 문서를 읽습니다.";
import { Button } from "../ui/Button";

export function EditorScreen({
  project, deck: initialDeck, onDeckChange, onEditorReady, onDirtyChange, onConflictHint, onBusyChange, onAiBusyChange, timings,
  onSaveStatusChange, onFocusSaveStatus, onDraftsChanged, initialChapterId, onChapterChange, readOnly = false,
  readOnlyNotice = false, conflictSignal = 0, seenJobFailures, failuresSince = 0,
}: {
  project: ProjectInfo;
  deck: Deck;
  onDeckChange: (d: Deck) => void;
  // 부모(ProjectView)가 내보내기와 단계 이동 전에 플러시하도록. "declined"는 사용자가 머물기를 골랐다는 뜻이다
  onEditorReady?: (flush: (() => Promise<boolean | "declined">) | null) => void;
  onDirtyChange?: (dirty: boolean) => void;  // 저장 대기/저장 중/저장 실패이면 참 (부모의 beforeunload 경고용)
  onConflictHint?: () => void;  // 412 를 만났음을 부모에 알린다. 배너는 이 화면이 직접 띄우므로 부모는 일반 배너만 생략한다
  // 이 화면을 떠날 수 없는 동안 참이다(도식 작성 창이 열려 있음, 템플릿 전환 전 저장). 부모가 단계 이동을 잠근다.
  // 작성 창을 닫은 뒤 남은 AI 호출은 덱이 아닌 입력을 들지 않으므로 넣지 않는다 (D3a-5 리뷰 R10)
  onBusyChange?: (busy: boolean) => void;
  // 도식 AI 호출이 진행 중이면 참이다(작성 창을 닫은 뒤 포함). 서버가 아직 모르는 등록 전후에도 AI 설정을 잠그고
  // 창 닫기를 경고하게 한다. 단계 이동은 잠그지 않는다 (D3a-5)
  onAiBusyChange?: (busy: boolean) => void;
  timings?: Timings;
  // 저장 상태는 상단 머리가 보인다 (D3a-2, 계획 4.1). 이 화면은 자동 저장 상태를 올리고, 결과 안내가 없는
  // 되돌리기 뒤에는 머리의 저장 상태로 초점을 옮겨 달라고 부른다(D2a-5 리뷰 R11)
  onSaveStatusChange?: (status: SaveStatus) => void;
  onFocusSaveStatus?: () => void;
  onDraftsChanged?: () => void;  // 충돌로 변경을 새로 보존했다. 머리의 보존 건수를 다시 센다 (C18)
  initialChapterId?: string | null;  // 복구 화면에서 옮긴 장을 미리 고른다 (C24)
  onChapterChange?: (chapterId: string | null) => void;  // 고른 장. 부모가 다시 마운트할 때 같은 장을 고른다
  // 이 프로젝트의 장 생성 묶음 중(또는 진행 작업 확인 전)에는 덱을 고치지 않는다. 장을 골라 보는 것은 허용한다.
  // 묶음이 끝나면 부모가 새 덱으로 다시 마운트한다 (D3a-5, 계획 4.4). readOnlyNotice는 묶음을 확인했을 때만 안내한다
  readOnly?: boolean;
  readOnlyNotice?: boolean;
  // 늘어나면 충돌 처리로 들어간다. 장 생성 묶음이 끝났을 때 이 화면에 저장하지 않은 편집이 남아 있으면 부모가 보낸다.
  // 이 화면의 "서버 내용으로 되돌리기"가 편집을 보존한 뒤 새 문서를 읽는다 (D3a-β 리뷰 B2)
  conflictSignal?: number;
  // 생성 패널이 다시 열릴 때 그 장의 지난 실패를 한 번 보이는 데 쓴다 (D3a-β 재리뷰 F3)
  seenJobFailures?: Set<string>;
  failuresSince?: number;
}) {
  // 읽기 전용(장 생성 묶음 중)에는 저장을 멈춘다. 묶음 중 저장은 묶음의 사슬을 끊는다 (D3a-5 리뷰 R7)
  const editor = useDeckEditor(project.name, initialDeck, onDeckChange, timings, onConflictHint, readOnly);
  const readOnlyRef = useRef(readOnly);
  readOnlyRef.current = readOnly;
  // 마운트한 뒤에 늘어난 신호만 본다. 신호는 프로젝트 화면에서 줄지 않으므로, 마운트 때의 값을 새 신호로 읽으면
  // 한 번 겪은 충돌이 다시 열 때마다 되살아났다 (D3a-β 재리뷰 F1)
  const reportConflict = editor.reportConflict;
  const seenSignal = useRef(conflictSignal);
  useEffect(() => {
    if (conflictSignal > seenSignal.current) reportConflict(BATCH_END_CONFLICT);
    seenSignal.current = conflictSignal;
  }, [conflictSignal, reportConflict]);
  const chapters = editor.deck.structure.chapters;
  const [chapterId, setChapterId] = useState<string | null>(
    (initialChapterId && chapters.some((c) => c.id === initialChapterId) ? initialChapterId : chapters[0]?.id) ?? null);
  const [selected, setSelected] = useState<FrameRef | null>(null);
  // 직접 수정 모드 (D3c-3, 계획 4.5). 모드는 이동, 방향키, Delete, 서식을 연다. 고르기와 문구 수정은 모드 밖에서도 된다
  const [mode, setMode] = useState(false);
  const [focusRequest, setFocusRequest] = useState<{ target: string | null; nonce: number } | undefined>();
  const [status, setStatus] = useState("");
  const [pendingInput, setPendingInput] = useState(false);  // 확정 전 위치, 글자 크기 입력 (계획 리뷰 화면 S24)
  const dragging = useRef(false);
  const modeButton = useRef<HTMLButtonElement>(null);
  const hiddenList = useRef<HTMLElement>(null);
  const focusFrame = (target: string | null) => setFocusRequest((r) => ({ target, nonce: (r?.nonce ?? 0) + 1 }));
  useEffect(() => { onChapterChange?.(chapterId); }, [chapterId, onChapterChange]);
  // 되돌리기나 다시 실행이 고른 요소를 숨기면 선택을 비운다. 초점이 그 요소와 함께 사라졌으면 캔버스로 옮긴다
  // (D3c-3 리뷰 F9). 되돌리기 버튼처럼 다른 곳에 있는 초점은 옮기지 않는다(구현 기록의 판단 ②)
  useEffect(() => {
    if (!selected) return;
    const hidden = editor.deck.slides.find((s) => s.chapter_id === selected.chapterId)?.direct_edits?.[selected.slot]?.hidden;
    if (!hidden) return;
    setSelected(null);
    if (!document.activeElement || document.activeElement === document.body) focusFrame(null);
  }, [editor.deck]); // eslint-disable-line react-hooks/exhaustive-deps
  const [diagramDraft, setDiagramDraft] = useState<DiagramDraft | null>(null);
  const [diagramBusy, setDiagramBusy] = useState(false);
  const [templateBusy, setTemplateBusy] = useState(false);
  const templateBusyRef = useRef(false);
  // 장 후보의 서버 적용 중 (D3c-5, 계획 4.7의 2). 템플릿 전환처럼 화면을 잠그고 떠나지 못하게 한다
  const [applyBusy, setApplyBusy] = useState(false);
  const applyBusyRef = useRef(false);
  // 응답이 온 때의 충돌 여부. 패널은 클릭한 때의 콜백을 부르므로 렌더 값(editor.conflict)은 낡을 수 있다
  const conflictNow = useRef(editor.conflict);
  conflictNow.current = editor.conflict;
  const current = useRef({deck: editor.deck, chapterId, mounted: true});
  current.current = {...current.current, deck: editor.deck, chapterId};
  useEffect(() => { current.current.mounted = true; return () => {current.current.mounted = false;}; }, []);
  // 떠날 수 없는 상태를 부모에 알린다. 작성 창이 열려 있거나 템플릿 전환 전 저장 중이다
  const diagramOpen = useRef(false);
  const reportHolding = useCallback(() => {
    onBusyChange?.(templateBusyRef.current || applyBusyRef.current || diagramOpen.current);
  }, [onBusyChange]);
  const switchTemplate = async (id: string, to: TemplateName, base: Deck) => {
    if (templateBusyRef.current || editor.conflict || current.current.deck !== base
      || base.structure.chapters.find(c => c.id === id)?.template === to) return;
    templateBusyRef.current = true;
    setTemplateBusy(true); reportHolding();
    try {
      if (!await editor.flushSave()) return;
      if (!current.current.mounted || current.current.deck !== base || current.current.chapterId !== id) return;
      editor.apply(d => d === base ? applyTemplateSwitch(d, id, to).deck : d, {snapshot: true});
      setSelected(null);
      setStatus(`템플릿을 바꿨습니다. ${SWITCHED}`);  // 계획 4.5 전환 뒤 안내 (D3c-3 리뷰 F14)
    } finally {
      templateBusyRef.current = false;
      if (current.current.mounted) setTemplateBusy(false);
      reportHolding();
    }
  };
  const onApplyBusyChange = useCallback((busy: boolean) => {
    applyBusyRef.current = busy;
    if (current.current.mounted) setApplyBusy(busy);
    reportHolding();
  }, [reportHolding]);
  const diagramCalls = useRef(0);
  const onDiagramBusyChange = useCallback((busy: boolean) => {
    // 닫힌 작성창도 자기 호출이 끝날 때 해제한다. 다른 호출이 있으면 마지막 소유자까지 잠금을 유지한다.
    diagramCalls.current += busy ? 1 : -1;
    setDiagramBusy(diagramCalls.current > 0);
    onAiBusyChange?.(diagramCalls.current > 0);
  }, [onAiBusyChange]);
  const diagramDraftRef = useRef(diagramDraft);
  diagramDraftRef.current = diagramDraft;
  useEffect(() => { diagramOpen.current = diagramDraft !== null; reportHolding(); }, [diagramDraft, reportHolding]);

  // 작성 중인 의미 입력은 아직 Deck이 아니다. 이탈/복원/내보내기로 조용히 버리지 않는다.
  // 작성 창을 닫은 뒤 남은 AI 호출은 막지 않는다. 그 결과는 작업 원장에 후보로 남아 복구 화면에 보인다 (리뷰 R10)
  const flush = useCallback(async (): Promise<boolean | "declined"> => {
    if (diagramDraftRef.current || templateBusyRef.current || applyBusyRef.current) return false;
    // 읽기 전용이면 저장하지 않는다. 이미 나간 저장은 착지를 기다리고(그 편집은 사라지지 않는다), 그래도
    // 저장하지 않은 편집이 남았으면 버릴지 묻는다 (D3a-5 리뷰 R7, D3a-β 리뷰 B5)
    if (readOnlyRef.current) {
      // 저장 충돌 중이면 지금처럼 떠나지 않는다. 고친 내용은 "서버 내용으로 되돌리기"가 보존한다 (재리뷰 F4)
      if (editor.conflict) return editor.flushSave();
      if (await editor.flushSave()) return true;
      return window.confirm(BATCH_DISCARD_CONFIRM) ? true : "declined";
    }
    const saved = await editor.flushSave();
    // 저장을 기다리는 동안 새로 연 작성 창도 보호한다. 시작 시점의 상태만 검사하면 입력을 버리고 이동한다.
    return saved && diagramDraftRef.current === null && !templateBusyRef.current;
  }, [editor.flushSave, editor.conflict]);

  useEffect(() => {
    onEditorReady?.(flush);
    // 언마운트 시 등록을 해제한다: 다음 화면이 이 화면의 낡은 flush 함수를 계속 들고 있으면
    // 단계 이동 플러시가 이미 사라진 편집기를 가리켜 무의미해진다 (2026-08-29 최종 리뷰 발견)
    return () => onEditorReady?.(null);
  }, [onEditorReady, flush]);

  useEffect(() => {
    onDirtyChange?.(diagramDraft !== null || editor.saveState !== "저장됨" || pendingInput);
  }, [diagramDraft, editor.saveState, onDirtyChange, pendingInput]);

  // 되돌린 서버 덱(reloadFromServer)에 지금 보고 있는 장이 없으면 첫 장으로 되돌아간다
  useEffect(() => {
    if (!chapters.some((c) => c.id === chapterId)) {
      setChapterId(chapters[0]?.id ?? null);
    }
  }, [chapters, chapterId]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      // 되돌리기(서버 내용 다시 읽기) 중에는 보존할 덱이 바뀌지 않게 단축키도 막는다 (리뷰 R11)
      // 서버 적용 중에도 막는다. 응답 전에 덱이 바뀌면 서버의 반영 결과를 받지 못한다 (D3c-5 리뷰 F1)
      if (readOnly || diagramDraft || diagramBusy || templateBusyRef.current || applyBusyRef.current || editor.reloading) return;
      // 인라인 편집 입력 중에는 브라우저 네이티브 undo가 동작해야 하므로 덱 undo가 끼어들지 않는다
      // (2026-08-29 최종 리뷰 발견)
      const t = e.target as HTMLElement;
      // 입력란, 선택 상자, 편집 가능한 영역, 열린 대화 상자에서는 그 요소의 되돌리기를 쓴다. 끄는 중에는 받지 않는다
      // (D3c-3, 계획 리뷰 화면 S6, S10)
      if (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable) return;
      if (dragging.current || t.closest?.('[role="dialog"], dialog')) return;
      // 모달(비교 화면 등)이 열린 동안에는 초점이 body로 빠져도 막는다. 앱 화면의 inert는 window의 키 수신을 막지 않는다.
      // 비교 화면 뒤에서 덱이 바뀌면 화면의 "지금"과 저장본이 달라진다 (D3c-6 리뷰 G1)
      if (document.querySelector('[role="dialog"][aria-modal="true"]')) return;
      if (!(e.ctrlKey || e.metaKey)) return;
      const key = e.key.toLowerCase();
      if (key === "z" && !e.shiftKey) { e.preventDefault(); editor.undo(); }
      if (key === "y" || (key === "z" && e.shiftKey)) { e.preventDefault(); editor.redo(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [editor.undo, editor.redo, editor.reloading, diagramDraft, diagramBusy, readOnly]);

  // 보존한 변경 건수는 상단 머리가 센다 (C18). 새로 보존하면 다시 세 달라고 알린다
  const preservedId = editor.preservedDraft?.id;
  useEffect(() => { if (preservedId) onDraftsChanged?.(); }, [preservedId, onDraftsChanged]);
  const saveKind = saveStatusKind(editor.saveState, editor.conflict);
  useEffect(() => { onSaveStatusChange?.({ kind: saveKind }); }, [saveKind, onSaveStatusChange]);
  // 되돌리기 중에는 버튼이 잠긴 영역 안에 있어 초점이 사라진다. 끝나면 결과 안내로 초점을 옮긴다
  // 두 결과 안내(보존 실패, 보존 성공)는 초점 대상을 따로 갖는다. 하나의 ref를 나눠 가지면 두 문단이 함께
  // 그려질 때 React가 새로 붙은 요소에만 ref를 다시 걸어 초점 대상이 어긋날 수 있다 (D3a-1 리뷰 R4)
  const failureRef = useRef<HTMLParagraphElement | null>(null);
  const successRef = useRef<HTMLParagraphElement | null>(null);
  const wasReloading = useRef(false);
  useEffect(() => {
    // 결과 안내가 없는 경로(보존할 변경 없음, 확인 뒤 되돌리기)는 저장 상태로 초점을 옮긴다 (리뷰 R11)
    if (wasReloading.current && !editor.reloading) {
      const outcome = failureRef.current ?? successRef.current;
      if (outcome) outcome.focus(); else onFocusSaveStatus?.();
    }
    wasReloading.current = editor.reloading;
  }, [editor.reloading, onFocusSaveStatus]);

  const slide = editor.plan?.slides.find((s) => s.chapter_id === chapterId) ?? null;
  const commitText = (ref: TextRef, text: string) =>
    editor.apply((d) => applyTextEdit(d, ref, text));

  const deckSlide = editor.deck.slides.find((s) => s.chapter_id === chapterId);
  const keys = deckSlide ? frameKeys(deckSlide) : {};
  const edits = deckSlide?.direct_edits ?? {};
  const template = deckSlide?.slots.template;
  // 모드를 여는 조건 (계획 4.5, 계획 리뷰 화면 S9). 깨지면 끌기를 취소하고(미리보기) 입력은 반영한 뒤(패널) 닫는다
  const canMode = !readOnly && !editor.conflict && !editor.reloading && !templateBusy && diagramDraft === null
    && !!slide && !slide.diagram && template !== undefined && template !== "diagram";
  useEffect(() => { if (!canMode && mode) setMode(false); }, [canMode, mode]);
  // 낡은 계획에서는 열쇠 집합과 목록 길이가 같을 때만 끌기를 허용한다. 목록 편집 직후의 옛 계획은 다른 항목을 그린다
  // (재리뷰 RR15)
  const planSlide = editor.planDeck?.slides.find((s) => s.chapter_id === chapterId);
  const sameShape = !!planSlide && JSON.stringify(Object.keys(frameKeys(planSlide))) === JSON.stringify(Object.keys(keys));
  const dragAllowed = !editor.planStale || sameShape;
  const pageW = editor.plan?.page_width_pt ?? 0;
  const pageH = editor.plan?.page_height_pt ?? 0;
  const hiddenCount = Object.values(edits).filter((e) => e.hidden).length;

  const moveElement = (key: string, dx: number, dy: number, options: { coalesce?: Coalesce }) => {
    if (!slide || !chapterId) return;
    if (!dragAllowed) { setStatus(REDRAWING); return; }
    const c = clampOffset(slide, key, dx, dy, pageW, pageH);
    editor.apply((d) => editElement(d, chapterId, key, { dx_pt: c.dx, dy_pt: c.dy }), { coalesce: options.coalesce });
    const first = slide.frames.find((f) => frameKey(f) === key);
    if (first) {
      const box = displayBoxes(slide, { [key]: { dx_pt: c.dx, dy_pt: c.dy } }, pageW, pageH).get(first.name);
      // 이동 결과는 배율과 상관없이 알린다 (재리뷰 RR12)
      if (box) setStatus(`${roleName(key, template)}: 가로 ${Math.round(box.x)}pt, 세로 ${Math.round(box.y)}pt`);
    }
  };
  const hideElement = (key: string) => {
    if (!slide || !chapterId) return;
    if (!dragAllowed) { setStatus(REDRAWING); return; }
    // 그리는 순서의 다음 요소로 초점을 옮긴다. 없으면 캔버스 (계획 4.5 초점 표)
    const order = [...new Set(slide.frames.map(frameKey))].filter((k) => keys[k] && !edits[k]?.hidden && k !== key);
    const at = slide.frames.findIndex((f) => frameKey(f) === key);
    const next = order.find((k) => slide.frames.findIndex((f) => frameKey(f) === k) > at) ?? null;
    editor.apply((d) => editElement(d, chapterId, key, { hidden: true }));
    setSelected(next ? { chapterId, slot: next } : null);
    focusFrame(next);
    setStatus(`${withObject(roleName(key, template))} 숨겼습니다. 숨긴 요소 목록에서 다시 보이게 할 수 있습니다.`);
  };
  const toggleMode = () => {
    if (mode) {
      setMode(false);
      setTimeout(() => modeButton.current?.focus(), 0);  // 모드 종료 뒤에는 "직접 수정" 버튼으로 (계획 4.5)
    } else if (canMode) {
      setMode(true);
      setStatus("");
    }
  };
  const showHidden = () => {
    if (!canMode) { setStatus(MODE_BLOCKED); return; }
    setMode(true);
    setTimeout(() => hiddenList.current?.focus(), 0);
  };

  return (
    <>
    {diagramBusy && !diagramDraft && <p role="status">도식 AI 응답을 기다리고 있습니다. 작성창을 닫아도 이미 전송된 요청은 계속될 수 있습니다.</p>}
    {templateBusy && <p role="status">전환 전 내용을 저장하고 있습니다.</p>}
    {editor.reloading && <p role="status">변경을 보존하고 서버 내용을 다시 읽고 있습니다.</p>}
    {readOnly && readOnlyNotice && <p role="status">{BATCH_READ_ONLY_NOTICE}
      {/* 묶음 전에 고친 내용이 남아 있으면 그 결과를 알린다 (D3a-β 리뷰 B2) */}
      {editor.saveState === "저장 대기" && " 고친 내용은 생성이 끝난 뒤 다시 저장합니다. 그사이 문서가 바뀌었으면 충돌 안내가 뜨고, 서버 내용으로 되돌릴 때 고친 내용을 보존합니다."}</p>}
    <div className="editor-screen" inert={diagramDraft !== null || diagramBusy || templateBusy || applyBusy || editor.reloading}>
      {/* 막대는 편집 영역의 첫 자식이다: 쌓인 배치에서 장 목록보다 위에 와 512×360에서도 첫 화면 안에 남고,
          넓은 배치에서는 격자 영역으로 가운데 열 위에 둔다 (α 랩업 배치 A) */}
      {slide && !slide.diagram && editor.plan && (
        <div className="direct-edit-bar">
          <button ref={modeButton} aria-pressed={mode} disabled={!mode && !canMode} onClick={toggleMode}>
            {mode ? "수정 완료" : "직접 수정"}</button>
          {mode && <span className="hint">{MODE_GUIDE}</span>}
        </div>
      )}
      <aside className="editor-left">
        <ChapterList deck={editor.deck} plan={editor.plan} selected={chapterId}
          onSelect={(id) => { setChapterId(id); setSelected(null); }}
          onReorder={readOnly ? undefined : (from, to) => editor.apply((d) => reorderChapters(d, from, to))} />
        <button disabled={readOnly || editor.conflict || diagramBusy} onClick={() => setDiagramDraft(createDiagramDraft(editor.deck))}>도식 추가</button>
      </aside>
      <section className="editor-center">
        {editor.saveError && (
          <p role="alert">
            {editor.saveError}{" "}
            {editor.conflict ? (
              <button disabled={editor.reloading} onClick={() => void editor.reloadFromServer()}>서버 내용으로 되돌리기</button>
            ) : (
              editor.saveState === "저장 실패" && (
                <button onClick={() => void editor.retrySave()} disabled={readOnly}>다시 저장</button>
              )
            )}
          </p>
        )}
        {editor.preserveFailure && (
          <div>
            {/* 알림은 첫 문단에만 둔다: 덱 전체를 담은 복사 상자를 화면 낭독기가 읽지 않게 (리뷰 R15) */}
            <p role="alert" tabIndex={-1} ref={failureRef}>
              변경을 보존하지 못해 서버 내용으로 되돌리지 않았습니다. ({editor.preserveFailure.message}){" "}
              아래 내용을 복사해 두거나, 그래도 되돌리면 이 화면의 변경은 사라집니다.
            </p>
            <UnsavedChangeBackup text={JSON.stringify(editor.deck, null, 2)} label="보존하지 못한 변경" />
            <Button variant="danger" disabled={editor.reloading} onClick={() => {
              if (window.confirm("보존하지 못한 변경은 사라집니다. 서버 내용으로 되돌릴까요?")) {
                void editor.reloadFromServer({ discardUnsaved: true });
              }
            }}>그래도 서버 내용으로 되돌리기</Button>
          </div>
        )}
        {editor.preservedDraft && (
          <p role="status" tabIndex={-1} ref={successRef}>
            {editor.reloadIncomplete
              ? <>변경을 보존했습니다({formatSavedAt(editor.preservedDraft.saved_at)}). 서버 내용은 아직 읽지 못해
                  화면은 바뀌지 않았습니다. "서버 내용으로 되돌리기"를 다시 눌러 주세요.</>
              : <>다른 곳에서 먼저 저장해 서버 내용으로 되돌렸습니다. 되돌리기 전의 변경은 보존했습니다
                  ({formatSavedAt(editor.preservedDraft.saved_at)}).</>}
            {" "}스냅샷 복구 화면의 "충돌로 보존한 변경"에서 보거나 복원하거나 지울 수 있습니다.{" "}
            <Button variant="text" onClick={editor.dismissPreservedDraft}>닫기</Button>
          </p>
        )}
        {editor.measureError && (
          <p role="alert">{editor.measureError}{" "}
            <button onClick={editor.remeasure}>다시 그리기</button>
          </p>
        )}
        <p role="status" className="sr-status">{status}</p>
        {slide && editor.plan ? (
          // 2026-08-29 태스크 11 리뷰 이월: 장 전환 시 편집창 잔존 방지 리마운트
          // 낡은 계획(덱이 바뀐 뒤 새 계획이 오기 전)으로는 편집을 열지 않는다 (2026-09-03 FC-05)
          <Preview key={slide.chapter_id} slide={slide} style={editor.plan.style}
            pageW={editor.plan.page_width_pt} pageH={editor.plan.page_height_pt}
            editable={!editor.planStale && !readOnly}
            selected={selected} onSelect={setSelected} onCommitText={commitText}
            template={template} keys={keys} edits={edits} mode={mode} dragAllowed={dragAllowed} deckToken={editor.deck}
            onMove={moveElement} onHide={hideElement} onNeedMode={() => setStatus(canMode ? NEED_MODE : MODE_BLOCKED)}
            onDragChange={(d) => { dragging.current = d; }} focusRequest={focusRequest}
            onDragDiscard={() => setStatus("끄는 동안 다른 변경이 있어 옮기지 않았습니다. 다시 끌어 주세요.")}
            hiddenCount={hiddenCount} onShowHidden={showHidden} />
        ) : editor.measureError ? (
          <p>미리보기를 만들지 못했습니다. 위 오류를 확인한 뒤 다시 그려 주세요.</p>
        ) : editor.deck.slides.some(s => s.chapter_id === chapterId) ? (
          <p>미리보기를 계산하고 있습니다.</p>
        ) : chapters.length === 0 ? (
          <p>아직 장이 없습니다. 왼쪽의 도식 추가로 시작하거나 구성 단계에서 내용을 생성해 주세요.</p>
        ) : (
          <p>이 장은 아직 내용이 없습니다. 구성 단계에서 생성해 주세요.</p>
        )}
      </section>
      <aside className="editor-right" inert={readOnly}>
        <button onClick={editor.undo} disabled={!editor.canUndo}>되돌리기 (Ctrl+Z)</button>
        <button onClick={editor.redo} disabled={!editor.canRedo}>다시 실행</button>
        {mode && chapterId && (
          <DirectEditPanel projectName={project.name} deck={editor.deck} chapterId={chapterId} plan={slide}
            pageW={pageW} pageH={pageH} keys={keys} selectedKey={selected?.slot ?? null} onApply={editor.apply}
            onShowFrame={(k) => { setSelected({ chapterId, slot: k }); focusFrame(k); }} onHide={hideElement}
            onPendingChange={setPendingInput} hiddenListRef={hiddenList} locked={!dragAllowed} />
        )}
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
            seenJobFailures={seenJobFailures} failuresSince={failuresSince}
            onFlush={editor.flushSave} onConflict={editor.reportConflict} onApplyBusyChange={onApplyBusyChange}
            onApplied={(saved, base) => {
              // 요청 중 덱이 바뀌었으면 받지 않는다. 그 편집의 저장이 412로 충돌 경로에 들어간다 (도식 경로와 같다)
              if (current.current.deck !== base) { reportConflict(SAVED_ELSEWHERE_CONFLICT); return; }
              if (conflictNow.current) return;  // 이미 충돌 안내가 있다. 다시 읽기가 서버 내용을 가져온다
              editor.acceptSaved(saved); setSelected(null);
            }} />
        )}
        {/* 일부러 줄인 글자 크기 경고는 분량 넘침이 아니므로 따로 보인다 (D3c-2 리뷰 F3, α 리뷰 A3) */}
        {slide && ([["capacity", "분량 경고"], ["font_size", "글자 크기 경고"]] as const).map(([kind, title]) => {
          const found = slide.warnings.filter((w) => (w.kind ?? "capacity") === kind);
          return found.length > 0 && (
            <section key={kind}>
              <h3>{title}</h3>
              <ul>{found.map((w, i) => <li key={i}>{w.message}</li>)}</ul>
            </section>
          );
        })}
      </aside>
    </div>
    {diagramDraft && <DiagramAuthoringDialog projectName={project.name} deck={editor.deck} initialDraft={diagramDraft} blocked={editor.conflict}
      flushBeforeCheck={editor.flushSave} onConflict={editor.reportConflict} onBusyChange={onDiagramBusyChange}
      onCancel={() => setDiagramDraft(null)} onApply={(candidate, base, id, persisted) => {
        // 저장된 반영을 받지 못하면 충돌로 멈춘다. 렌더 값 대신 최신 값을 본다 (D3c-5 리뷰 F1)
        if (current.current.deck !== base) { if (persisted) reportConflict(SAVED_ELSEWHERE_CONFLICT); return; }
        if (conflictNow.current) return;
        if(persisted) editor.acceptSaved(candidate); else editor.replace(candidate);
        setChapterId(id); setSelected(null); setDiagramDraft(null);
      }} />}
    </>
  );
}
