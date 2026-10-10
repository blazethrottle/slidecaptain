import { useCallback, useEffect, useRef, useState } from "react";
import {
  AiConsentDeclined, api, ApiError, followJob, isStaleStoryPlan, messageOf, newRequestId, TERMINAL_JOB_STATES,
  type Chapter, type ChapterView, type Deck, type GenerationUsage, type JobView, type ProjectInfo, type StoryPlan,
  type StructureResult,
  type TemplateName,
} from "../api/client";
import {
  blockingReasons, JOB_FOLLOW_ERROR, jobResult, JobCancelled, pendingCandidate, reasonText, runJob, runningJob, settle, slotsText, waitJob,
} from "../api/jobs";
import { formatUsage, sumUsage } from "../api/usage";
import { Diagnostics } from "../ui/Diagnostics";
import { describeAiOutput, describeFailure, describeJobFailure, type FailureDescription } from "../ui/failure";
import { FailureNotice } from "../ui/FailureNotice";
import { StatusIndicator } from "../ui/StatusIndicator";
import { SELECTABLE_TEMPLATES, TEMPLATE_LABELS } from "../editor/labels";
import { StoryPlanView } from "./StoryPlanView";
import { StoryPlanRecoveryGuidance } from "./StoryPlanRecoveryGuidance";
import { StoryRewritePanel } from "./StoryRewritePanel";
import { DocumentChangePanel } from "./DocumentChangePanel";
import { UnsavedChangeBackup } from "../editor/UnsavedChangeBackup";
import { formatSavedAt } from "../api/time";
import { Button } from "../ui/Button";
import type { SaveStatus } from "../ui/StatusIndicator";

// 실패한 장은 결과 자체가 없어 usage 합계에서 빠진다: 그 사실을 합계 줄에 밝힌다 (가정 7)
const FAILED_CHAPTER_USAGE_NOTICE =
  "(실패한 장의 사용량은 이 합계에 포함되지 않았습니다. 정확한 기록은 프로젝트 폴더의 사용량 기록 파일에 있습니다.)";

// 취소는 실패가 아니다 (계획서 B3): AI 전송 고지를 취소하면 "취소"로 표시하고 role=alert 배너를
// 띄우지 않는다. 이 문구는 GeneratePanel의 취소 안내와 같다
const AI_CONSENT_CANCELLED_NOTICE = "전송을 취소했습니다. 필요하면 다시 시도해 주세요.";
const UNSAVED_RESULT_CONFIRM =
  "저장하지 못한 생성 결과가 있습니다. 복사하지 않고 계속하면 그 결과는 사라집니다. 계속할까요?";

type ProgressLabel = "대기" | "생성 중" | "완료" | "실패" | "취소" | "보류" | "중단" | "취소 요청됨"
  | "완료 여부 확인 필요" | "이전 입력 기준";
type Progress = Record<string, ProgressLabel>;

const LEDGER_UNAVAILABLE_BEFORE_APPROVAL = "작업 기록을 열 수 없어 내용 생성을 시작할 수 없습니다. 장 구성은 바꾸지 않았습니다. 앱을 다시 시작한 뒤 승인해 주세요.";
const ACTIVE_JOB_BEFORE_APPROVAL = "다른 AI 작업이 진행 중이라 승인하지 않았습니다. 장 구성은 바꾸지 않았습니다. 그 작업이 끝난 뒤 다시 승인해 주세요.";
const UNKNOWN_REGENERATE_CONFIRM =
  "완료 여부를 확인하지 못한 장이 있습니다. 다시 생성하면 AI 사용량이 한 번 더 기록될 수 있습니다. 계속할까요?";
const CANCEL_REQUESTED_NOTICE = "취소를 요청했습니다. AI가 응답을 멈추면 취소됨으로 바뀝니다.";
// 승인 반영이 저장 충돌(412)로 거절됐을 때 실패 안내의 "무슨 일"과 "무엇이 보존됐는가" (D2a 이월 3, D3a-4)
const APPROVAL_CONFLICT = "다른 창이나 프로그램에서 먼저 저장되어 장 구성을 승인하지 않았습니다.";
const APPROVAL_NOT_PRESERVED = "승인하려던 장 구성을 보존하지 못했습니다. 아래 상자의 내용을 복사해 보관해 주세요.";

// 원장의 장 상태를 화면 표시로 바꾼다 (계획서 D2b-5a 하위 상태 표). 그 뒤 슬라이드가 생긴 장은 완료로 보인다
function chapterLabel(chapter: ChapterView, hasSlide: boolean): ProgressLabel {
  if (hasSlide) return "완료";
  switch (chapter.state) {
    case "queued": return "대기";
    case "running": case "validating": return "생성 중";
    case "cancel_requested": return "취소 요청됨";
    case "succeeded": return "완료";
    case "cancelled": return "취소";
    case "remote_completion_unknown": return "완료 여부 확인 필요";
    case "interrupted": return chapter.error?.code === "held_stale_plan" ? "보류" : "중단";
    default: return chapter.candidate_status === "stale" ? "이전 입력 기준" : "실패";
  }
}

// 다시 생성할 수 있는 장 상태. 보류(구성 계획 낡음)는 복구 안내를 따른다
const RETRYABLE_STATES = new Set(["failed", "interrupted", "cancelled", "remote_completion_unknown"]);

function candidateText(chapter: ChapterView): string {
  return slotsText((chapter.result as { slots?: unknown } | null)?.slots);
}

function nextChapterId(chapters: Chapter[]): string {
  const max = chapters
    .map((c) => /^c(\d+)$/.exec(c.id))
    .reduce((n, m) => (m ? Math.max(n, Number(m[1])) : n), 0);
  return `c${max + 1}`;
}

export type StructureBrief = { instructions: string; targetChapters: string };
export const EMPTY_BRIEF: StructureBrief = { instructions: "", targetChapters: "" };

export function StructureScreen({ project, deck, onDeckChange, onDone, onBusyChange, onConflict, onScreenReady, onDirtyChange,
  onSaveStatusChange, onJobRegistered, focusChapterId, brief, onBriefChange, pollIntervalMs = 1000 }: {
  project: ProjectInfo;
  deck: Deck;
  onDeckChange: (d: Deck) => void;
  onDone: () => void;
  onBusyChange?: (busy: boolean) => void;  // 승인 중 순차 생성 진행을 부모(ProjectView)에 알려 다른 탭 진입을 막는다
  onConflict?: () => void;  // 승인 루프의 putDeck이 412를 받으면 부모가 배너를 띄운다
  onScreenReady?: (flush: () => Promise<boolean>) => void;
  onDirtyChange?: (dirty: boolean) => void;
  onSaveStatusChange?: (status: SaveStatus) => void;  // 상단 머리의 저장 상태 (계획 4.1 저장 상태 출처 표)
  onJobRegistered?: (jobId: string) => void;  // 장 생성 묶음을 등록했다. 묶음 종결 뒤 충돌 안내를 사실에 맞게 쓴다 (계획 4.1)
  focusChapterId?: string | null;  // 복구 화면에서 옮긴 장. 마운트 때 그 장의 주제 입력으로 초점을 옮긴다 (C24)
  // 주안점과 목표 장수. 저장하지 않는 값이라 부모(프로젝트 화면)가 들고 있어 단계 이동과 다시 마운트 사이에
  // 남는다(계획 4.4, 사실 13, D3a-2 리뷰 R6). 넘기지 않으면 이 화면 안에서만 든다
  brief?: StructureBrief;
  onBriefChange?: (brief: StructureBrief) => void;
  pollIntervalMs?: number;  // 작업 조회 간격. 시험에서 실제 1초 대기를 쓰지 않게 한다 (계획서 5.9)
}) {
  const [draft, setDraft] = useState<Chapter[]>(deck.structure.chapters);
  const [storyPlan, setStoryPlan] = useState<StoryPlan | null>(deck.structure.story_plan ?? null);
  const [decisionQuestion, setDecisionQuestion] = useState(deck.structure.story_plan?.brief.decision_question ?? "");
  const [draftGenerated, setDraftGenerated] = useState(false);  // AI 재생성 초안 여부 (결정 15: 승인 시 전면 교체)
  const [localBrief, setLocalBrief] = useState<StructureBrief>(EMPTY_BRIEF);
  const currentBrief = brief ?? localBrief;
  const changeBrief = (next: StructureBrief) => (brief && onBriefChange ? onBriefChange(next) : setLocalBrief(next));
  const { targetChapters, instructions } = currentBrief;
  const setTargetChapters = (v: string) => changeBrief({ ...currentBrief, targetChapters: v });
  const setInstructions = (v: string) => changeBrief({ ...currentBrief, instructions: v });
  const [busy, setBusy] = useState(false);
  const [rewriteActive, setRewriteActive] = useState(false);
  const [documentActive,setDocumentActive] = useState(false);
  const [documentOpen,setDocumentOpen] = useState(false);
  const rewriteLeave = useRef<()=>Promise<boolean>>(async()=>true);
  const documentLeave = useRef<()=>Promise<boolean>>(async()=>true);
  const dirtyParts = useRef({rewrite:false,document:false,draft:false,backup:false});
  const parentDirty = useRef(onDirtyChange);parentDirty.current=onDirtyChange;
  // 재작성과 문서 변경 패널의 적용하지 않은 입력, 저장하지 못한 생성 결과도 머리의 저장 상태에 올린다 (D3a-2 리뷰 R3)
  const [pendingParts, setPendingParts] = useState({ panels: false, backup: false });
  const reportDirty = useCallback(()=>{const d=dirtyParts.current;parentDirty.current?.(d.rewrite||d.document||d.draft||d.backup);
    setPendingParts((p) => (p.panels === (d.rewrite||d.document) && p.backup === d.backup ? p : { panels: d.rewrite||d.document, backup: d.backup }));},[]);
  const setRewriteDirty = useCallback((dirty:boolean)=>{dirtyParts.current.rewrite=dirty;reportDirty();},[reportDirty]);
  const setDocumentDirty = useCallback((dirty:boolean)=>{dirtyParts.current.document=dirty;reportDirty();},[reportDirty]);
  // 장 구성 초안이 저장본과 다르면 창 닫기 경고에 포함한다 (D2a-2: 종전에는 경고 없이 사라졌다)
  const draftDirty = JSON.stringify(draft) !== JSON.stringify(deck.structure.chapters);
  const draftDirtyRef = useRef(draftDirty);
  draftDirtyRef.current = draftDirty;
  // 지금 초안에 올린 구조안 후보와 불러오지 않은 이전 입력 기준 후보 (D2b-5b, 처분)
  const structureJob = useRef<string | null>(null);
  const staleStructure = useRef<string | null>(null);
  const [earlierNotice, setEarlierNotice] = useState("");
  const registerRewrite = useCallback((guard:()=>Promise<boolean>)=>{rewriteLeave.current=guard;},[]);
  const registerDocument = useCallback((guard:()=>Promise<boolean>)=>{documentLeave.current=guard;},[]);
  // 화면을 떠나기 전 확인. 저장하지 못한 생성 결과(복사 상자)가 있으면 먼저 확인을 받는다 (리뷰 R1).
  // 끝에 미저장 신호를 다시 보고한다: 부모가 이동 준비 중 신호를 지우면 내보내기처럼 화면이 남는
  // 경우 초안의 미저장 표시가 꺼진 채 남았다 (리뷰 R9)
  useEffect(()=>{onScreenReady?.(async()=>{
    if(dirtyParts.current.backup&&!window.confirm(UNSAVED_RESULT_CONFIRM))return false;
    const ok=await documentLeave.current() && await rewriteLeave.current();
    queueMicrotask(reportDirty);
    return ok;
  });},[onScreenReady,reportDirty]);
  const [error, setError] = useState("");
  const [storyStale, setStoryStale] = useState(false);
  const [cancelNotice, setCancelNotice] = useState("");  // AI 전송 취소 안내 (role=alert 아님)
  const cancelNoticeRef = useRef("");
  cancelNoticeRef.current = cancelNotice;
  const [rawText, setRawText] = useState("");
  // 원인별 실패 안내 (D3a-4, 계획 4.3). failure: 화면이 받은 오류, formatWhat: 구조안 형식 오류의 문구,
  // batchFailure: 이 화면이 따라간 묶음의 첫 실패 장
  const [failure, setFailure] = useState<FailureDescription | null>(null);
  const [formatWhat, setFormatWhat] = useState("");
  const formatJob = useRef<JobView | null>(null);  // 형식 오류를 낸 구조안 작업 (진단 상세의 작업 ID)
  const [batchFailure, setBatchFailure] = useState<{ lead: string; failure: FailureDescription } | null>(null);
  // 저장하지 못한 생성 결과의 보존 (D2a-2): 보존 안내 또는 보존마저 실패했을 때 복사할 내용
  const [preservedNotice, setPreservedNotice] = useState("");
  const [unsavedBackup, setUnsavedBackup] = useState<string | null>(null);
  const [numbers, setNumbers] = useState<string[]>([]);
  // 가장 최근 장 생성 묶음 (D2b-5a). 장별 진행 표시와 실패 요약은 원장의 이 작업에서 계산한다
  const [job, setJob] = useState<JobView | null>(null);
  const [showJob, setShowJob] = useState(true);  // 새 승인이나 재작성 적용 뒤에는 이전 요약을 숨긴다
  const [followError, setFollowError] = useState("");
  const [startFailure, setStartFailure] = useState("");
  const [startError, setStartError] = useState<unknown>(null);
  const [pastNotice, setPastNotice] = useState("");  // 지난 묶음과 다른 실행의 묶음 안내 (알림이 아니다)
  const followAbort = useRef<AbortController | null>(null);
  const mounted = useRef(true);
  const startEpoch = useRef(0);  // 승인이나 장 다시 생성을 시작할 때마다 늘린다 (늦은 목록 응답 무시)
  const pendingStart = useRef<{ targets: string[]; headers: Record<string, string>; requestId: string; approval: boolean } | null>(null);
  const [canRestart, setCanRestart] = useState(false);  // 등록 실패 안내의 "내용 생성 다시 시작" (D2b-β 리뷰 R2, R7)
  const dismissing = useRef(false);
  const appliedSeen = useRef<Set<string>>(new Set());
  const progress: Progress = job && showJob ? Object.fromEntries(job.chapters.map((c) =>
    [c.chapter_id, chapterLabel(c, deck.slides.some((s) => s.chapter_id === c.chapter_id))])) : {};
  const setProgress = (_: Progress) => setShowJob(false);
  const [structureUsage, setStructureUsage] = useState<GenerationUsage | null>(null);
  const [chapterUsageSummary, setChapterUsageSummary] = useState<GenerationUsage | null>(null);
  const [chapterUsageCount, setChapterUsageCount] = useState(0);  // 합계에 실제로 실린 장 수
  const [chapterUsageHadUnaccountedFailure, setChapterUsageHadUnaccountedFailure] = useState(false);
  const questionChanged = decisionQuestion.trim() !== (storyPlan?.brief.decision_question ?? "");
  // 주 행동 (D3a-1, 계획 4.6): 초안이 없거나 낡으면 구조안 생성, 유효한 초안이면 승인
  const hasDiagrams = deck.structure.chapters.some(c => c.template === "diagram");
  // 도식이 있으면 구조안 생성을 쓸 수 없으므로 주 행동이 아니다. 그때 초안이 낡았으면 버튼 주 행동은 없고
  // 복구 안내가 다음 할 일을 말한다 (D3a-1 리뷰 R6)
  const validDraft = draft.length > 0 && !questionChanged && !storyStale;
  const generatePrimary = !validDraft && !hasDiagrams;
  // 승인이 지울 기존 장 내용. 누르기 전에 화면에 알린다 (D3a-1 리뷰 R13, 계획 4.6의 "장 내용 교체를 동반한 승인")
  const keptSlides = () => {
    const draftById = new Map(draft.map((c) => [c.id, c]));
    return draftGenerated ? [] : deck.slides.filter((s) => {
      const ch = draftById.get(s.chapter_id);
      return ch !== undefined && ch.template === s.slots.template;
    });
  };
  const replacedCount = deck.slides.length - keptSlides().length;
  // 장 구성 초안, 보고 질문, 저장하지 못한 생성 결과가 남아 있으면 창 닫기 경고에 포함한다 (D2a-2, 리뷰 R1, R16)
  // 승인 전 초안은 덱이 아니라 저장되지 않는다. 머리의 저장 상태는 그 사실을 문구로 밝힌다 (계획 4.1)
  useEffect(() => {
    onSaveStatusChange?.(pendingParts.backup ? { kind: "unsaved", detail: "저장하지 못한 생성 결과가 있습니다" }
      : draftDirty || questionChanged ? { kind: "unsaved", detail: "승인 전 초안은 저장되지 않습니다" }
      : pendingParts.panels ? { kind: "unsaved", detail: "적용하지 않은 입력이 있습니다" } : { kind: "saved" });
  }, [draftDirty, questionChanged, pendingParts, onSaveStatusChange]);
  const tableRef = useRef<HTMLTableSectionElement | null>(null);
  useEffect(() => {
    if (!focusChapterId) return;
    const row = [...(tableRef.current?.rows ?? [])].find((r) => r.dataset.chapterId === focusChapterId);
    row?.querySelector("input")?.focus();
  }, [focusChapterId]);
  useEffect(()=>{
    dirtyParts.current.draft=draftDirty||questionChanged;
    dirtyParts.current.backup=unsavedBackup!==null;
    reportDirty();
  },[draftDirty,questionChanged,unsavedBackup,reportDirty]);
  const preserveUnsaved = async (target: Deck, reason: "conflict" | "generation_unsaved") => {
    try {
      const info = await api.saveDraft(project.name, { reason, source: "structure_approval", deck: target });
      setUnsavedBackup(null);
      // 충돌 보존은 실패 안내의 "무엇이 보존됐는가"에 싣는다. 따로 띄우면 두 안내가 어긋난다 (D2a 이월 3)
      if (reason === "conflict") {
        return `승인하려던 장 구성을 보존했습니다(${formatSavedAt(info.saved_at)}). 스냅샷 복구 화면의 "충돌로 보존한 변경"에서 보거나 복원할 수 있습니다.`;
      }
      setPreservedNotice(`저장하지 못한 생성 결과를 보존했습니다(${formatSavedAt(info.saved_at)}). 스냅샷 복구 화면의 "충돌로 보존한 변경"에서 보거나 복원할 수 있습니다.`);
      return null;
    } catch {
      setPreservedNotice("");
      setUnsavedBackup(JSON.stringify(target, null, 2));
      return null;
    }
  };
  const showFailure = (error: unknown) => {
    const stale = isStaleStoryPlan(error);
    setStoryStale(stale);
    setError("");
    setFailure(stale ? null : describeFailure(error));
  };
  const resetError = () => { setError(""); setFailure(null); setFormatWhat(""); setBatchFailure(null); };

  // 구조안 작업의 결과를 초안에 올린다. 후보는 항상 AI 재생성 초안으로 보아 승인 때 옛 슬라이드를 계승하지 않는다
  const showStructure = (view: JobView) => {
    const result = jobResult<StructureResult>(view);
    if (result.status === "format_error") {
      formatJob.current = view;
      setFormatWhat(result.format_issue === "answer_not_in_summary"
        ? "AI가 만든 구성에서 핵심 답변을 설명하는 장에 일부 주장이 연결되지 않았습니다."
        : "AI 응답을 형식에 맞게 읽지 못했습니다.");
      setRawText(result.raw_text);
      setStructureUsage(result.usage);  // C-1 리뷰 반영: usage는 상태와 무관하게 항상 채워진다
    } else if (result.structure) {
      structureJob.current = view.id;
      setDraft(result.structure.chapters);
      setStoryPlan(result.structure.story_plan ?? null);
      setDecisionQuestion(result.structure.story_plan?.brief.decision_question ?? decisionQuestion);
      setDraftGenerated(true);
      setNumbers(result.unverified_numbers);
      setStructureUsage(result.usage);
    }
  };

  const generate = async () => {
    if (hasDiagrams) return;
    setBusy(true);
    onBusyChange?.(true);
    resetError();
    setStoryStale(false);
    setCancelNotice("");
    setRawText("");
    setStructureUsage(null);
    // F1 리뷰 반영: 새 구조안을 받으면 이전 승인 루프의 장 사용량 합계는 더 이상 유효하지 않다
    setChapterUsageSummary(null);
    setChapterUsageCount(0);
    setChapterUsageHadUnaccountedFailure(false);
    setStartError(null);
    setFollowError("");
    // 등록에 성공하면 지금 초안의 후보와 불러오지 않은 낡은 후보를 버린다. 등록이 실패하면 남긴다 (리뷰 R8)
    const previous = [structureJob.current, staleStructure.current].filter((id): id is string => id !== null);
    const controller = new AbortController();
    followAbort.current = controller;
    try {
      const n = targetChapters.trim() === "" ? undefined : Number(targetChapters);
      const { job: final } = await runJob<StructureResult>(project.name, "structure", {
        target_chapters: n, instructions,
        ...(decisionQuestion.trim() ? { brief: {
          decision_question: decisionQuestion.trim(), audience: deck.meta.audience,
          report_type: deck.meta.report_type,
          reading_profile: storyPlan?.brief.reading_profile ?? "미지정",
          constraints: storyPlan?.brief.constraints ?? [],
        } } : {}),
      }, { intervalMs: pollIntervalMs, signal: controller.signal,
        onError: () => setFollowError(JOB_FOLLOW_ERROR),  // 리뷰 R11
        onStarted: () => {
          previous.forEach((id) => void settle(project.name, id, "dismissed"));
          structureJob.current = null;
          staleStructure.current = null;
          setEarlierNotice("");
        } });
      setFollowError("");
      showStructure(final);
      // 만드는 동안 자료나 저장본이 바뀌었으면 승인 전에 알린다 (리뷰 R22)
      const reasons = blockingReasons(final);
      if (reasons.length > 0) setEarlierNotice(`구조안을 만드는 동안 입력이 바뀌었습니다(${reasonText(reasons)}). 승인하기 전에 다시 생성을 검토해 주세요.`);
    } catch (e) {
      if (controller.signal.aborted) return;  // 화면이 내려갔다 (리뷰 R23)
      if (e instanceof AiConsentDeclined) setCancelNotice(AI_CONSENT_CANCELLED_NOTICE);
      else if (e instanceof JobCancelled) setCancelNotice("구조안 생성이 취소되었습니다.");
      else showFailure(e);  // 다른 작업이 진행 중이면 실패 안내가 그 작업 취소 버튼을 보인다 (리뷰 R12)
    } finally {
      if (followAbort.current === controller) followAbort.current = null;
      if (!controller.signal.aborted) { setBusy(false); onBusyChange?.(false); }
    }
  };

  const update = (i: number, patch: Partial<Chapter>) => {
    setDraft(draft.map((c, j) => (j === i ? { ...c, ...patch } : c)));
  };
  const move = (i: number, delta: number) => {
    const j = i + delta;
    if (j < 0 || j >= draft.length) return;
    const next = [...draft];
    [next[i], next[j]] = [next[j], next[i]];
    setDraft(next);
  };
  const remove = (i: number) => setDraft(draft.filter((_, j) => j !== i));
  const add = () => {
    setDraft([...draft, {
      id: nextChapterId(draft), topic: "새 장", conclusion: "",
      template: "bullet_box", source_refs: [],
    }]);
  };

  // 장별 결과에서 사용량 합계, 결과 없는 실패, 미검증 숫자, 형식 오류 원문, 구성 계획 낡음을 계산한다
  // live: 이 화면에서 따라간 묶음. 지난 묶음(다시 열기)은 충돌 알림 없이 요약만 보이고, 덱이 완성됐으면 숨긴다 (D2b-5a 리뷰 R2)
  const summarize = (view: JobView, live = true, current: Deck = deck) => {
    const results = view.chapters.filter((c) => c.result);
    const usages = results.map((c) => (c.result as { usage?: GenerationUsage }).usage).filter(Boolean) as GenerationUsage[];
    setChapterUsageSummary(usages.length > 0 ? sumUsage(usages) : null);
    setChapterUsageCount(usages.length);
    // 시작하지 않은 장은 AI에 보내지 않았으므로 사용량 누락의 단서가 아니다 (D2b-5a 리뷰 R11)
    setChapterUsageHadUnaccountedFailure(view.chapters.some((c) => !c.result && c.started_at !== null
      && ["failed", "interrupted", "remote_completion_unknown", "cancelled"].includes(c.state)));
    const found = results.flatMap((c) => (c.result as { unverified_numbers?: string[] }).unverified_numbers ?? []);
    setNumbers((n) => [...new Set([...n, ...found])]);
    const malformed = view.chapters.filter((c) => c.error?.error_class === "ai_output" && c.result);
    if (malformed.length) setRawText((malformed[malformed.length - 1].result as { raw_text?: string }).raw_text ?? "");
    if (view.chapters.some((c) => c.error?.code === "stale_story_plan")) setStoryStale(true);
    if (cancelNoticeRef.current === CANCEL_REQUESTED_NOTICE) setCancelNotice("");  // 종결 뒤 예고 문구를 지운다 (리뷰 R19)
    const complete = current.structure.chapters.every((ch) => current.slides.some((sl) => sl.chapter_id === ch.id));
    if (!live && complete) return;
    const show = (message: string) => (live ? setError(message) : setPastNotice(`지난 내용 생성: ${message}`));
    if (view.started_at === null && view.error) {
      // 시작하기 전에 끝났다(다른 저장, AI 연결 변경 등). 장마다가 아니라 작업의 원인을 보인다 (D2b-4 리뷰 R12)
      show(`내용 생성을 시작하지 못했습니다. ${view.error.detail ?? ""}`.trim());
      if (live && view.error.error_class === "base_changed") onConflict?.();
    } else if (view.outcome === "chain_broken") {
      // 자료만 바뀐 경우는 저장본이 그대로라 충돌 안내를 띄우지 않는다 (D2b-4 리뷰 R18, β 리뷰 R5)
      const deckChanged = view.chapters.some((c) => c.error?.code === "chain_broken" || c.error?.code === "base_changed");
      if (deckChanged) {
        show("다른 창이나 프로그램에서 덱이 바뀌어 일부 장을 반영하지 않았습니다. 서버 내용을 다시 읽은 뒤 남은 장을 다시 생성해 주세요.");
        if (live) onConflict?.();
      } else {
        show("만드는 동안 자료가 바뀌어 일부 장을 반영하지 않았습니다. 현재 자료로 남은 장을 다시 생성해 주세요.");
      }
    } else if (view.state === "failed" && view.outcome !== "held_stale_plan") {
      const malformedOnly = view.chapters.every((c) => c.state === "succeeded" || c.error?.error_class === "ai_output");
      const failed = view.chapters.find((c) => c.state === "failed");
      if (malformedOnly) show("일부 장의 AI 응답을 형식에 맞게 읽지 못했습니다. 실패한 장만 다시 생성해 주세요.");
      else if (live && failed) {
        // 첫 실패 장의 원인으로 안내한다. 남은 장은 "앞 장 때문에 중단"이라 따로 안내하지 않는다 (D3a-4, 계획 4.3)
        setBatchFailure({ lead: "일부 장을 만들지 못했습니다. 아래 원인을 확인한 뒤 실패한 장만 다시 생성해 주세요.",
          failure: describeJobFailure(view, failed) });
      } else {
        const detail = failed?.error?.detail;
        show(`일부 장을 만들지 못했습니다${detail ? `(${detail})` : ""}. 실패한 장만 다시 생성해 주세요.`);
      }
    }
  };

  // 묶음을 끝까지 조회한다. 장이 적용될 때마다 덱과 저장 ETag를 다시 읽는다 (D2b-5a, 계획서 F1)
  const follow = async (jobId: string, registeredHere: boolean) => {
    setBusy(true);
    onBusyChange?.(true);
    setShowJob(true);
    const controller = new AbortController();
    followAbort.current = controller;
    let latest: Deck | null = null;
    let deckUnread = false;
    try {
      const final = await followJob(() => api.getJob(project.name, jobId), async (view) => {
        setJob(view);
        setFollowError("");
        const newly = view.chapters.filter((c) => c.state === "succeeded" && !appliedSeen.current.has(c.chapter_id));
        if (newly.length > 0 || TERMINAL_JOB_STATES.has(view.state)) {
          try {
            latest = await api.getDeck(project.name);
            onDeckChange(latest);
            newly.forEach((c) => appliedSeen.current.add(c.chapter_id));
          } catch (e) {
            // 종결 뒤의 덱 읽기 실패로 조회를 끝없이 반복하지 않는다. 다시 읽기는 충돌 배너가 맡는다 (D2b-5a 리뷰 R1)
            if (!TERMINAL_JOB_STATES.has(view.state)) throw e;
            deckUnread = true;
          }
        }
      }, { intervalMs: pollIntervalMs, signal: controller.signal,
        onError: () => setFollowError(JOB_FOLLOW_ERROR) });
      summarize(final, true, latest ?? deck);
      if (deckUnread) {
        setError("AI 작업은 끝났지만 저장본을 다시 읽지 못했습니다. 서버 내용을 다시 읽어 주세요.");
        onConflict?.();
      }
      // 장 하나만 다시 만든 경우에도 다른 장이 비어 있으면 편집 단계으로 옮기지 않는다
      const complete = latest === null || (latest as Deck).structure.chapters
        .every((ch) => (latest as Deck).slides.some((sl) => sl.chapter_id === ch.id));
      if (registeredHere && final.state === "succeeded" && complete && !deckUnread) onDone();
    } catch (e) {
      if (!controller.signal.aborted) showFailure(e);
    } finally {
      if (followAbort.current === controller) followAbort.current = null;
      setBusy(false);
      onBusyChange?.(false);
    }
  };

  // 화면을 다시 열면 진행 중인 묶음을 이어서 조회하고, 끝난 묶음은 결과를 보인다 (D2b-5a)
  useEffect(() => {
    let live = true;
    mounted.current = true;
    const startedAt = startEpoch.current;
    // 승인이나 장 다시 생성이 그사이 시작했으면 늦게 온 목록으로 새 작업을 덮지 않는다 (D2b-5a 리뷰 R7)
    const current = () => live && startEpoch.current === startedAt;
    api.listJobs(project.name).then(async (jobs) => {
      if (!current()) return;
      // 구조안: 진행 중이면 이어서 조회하고, 처분하지 않은 후보는 초안으로 불러온다 (D2b-5b)
      try {
      const runningStructure = runningJob(jobs, ["structure"]);
      if (runningStructure) {
        setBusy(true);
        onBusyChange?.(true);
        const controller = new AbortController();
        followAbort.current = controller;
        try {
          showStructure(await waitJob(project.name, runningStructure, { intervalMs: pollIntervalMs, signal: controller.signal,
            onError: () => setFollowError(JOB_FOLLOW_ERROR) }));
          setFollowError("");
        } catch (e) {
          if (!controller.signal.aborted) showFailure(e);
        } finally {
          if (!controller.signal.aborted) { setBusy(false); onBusyChange?.(false); }
        }
      } else {
        const earlier = pendingCandidate(jobs, ["structure"]);
        const reasons = earlier ? blockingReasons(earlier) : [];
        if (earlier && reasons.length === 0) {
          // 저장하지 않은 초안 편집이 있으면 바꾸기 전에 묻는다
          if (!draftDirtyRef.current || window.confirm("새 구조안 후보가 도착했습니다. 지금 초안을 바꿀까요?")) {
            showStructure(earlier);
            setEarlierNotice("이전에 만든 구조안 후보를 불러왔습니다. 승인해야 저장됩니다.");
          }
        } else if (earlier) {
          staleStructure.current = earlier.id;
          setEarlierNotice(`이전 입력 기준 구조안 후보가 있습니다(${reasonText(reasons)}). 현재 자료로 다시 생성해 주세요.`);
        }
      }
      } catch (e) {
        // 지난 구조안을 보이지 못해도 아래 장 생성 묶음은 이어서 본다 (D2b-5b 리뷰 R5)
        if (current()) showFailure(e);
      }
      if (!current()) return;
      // 다른 실행이 남긴 미종결 묶음은 따라가지 않는다. 그 실행이 끝났는지 이 화면은 알 수 없다 (D2b-5a 리뷰 R6)
      const batches = jobs.filter((j) => j.kind === "chapters");
      const latest = batches.find((j) => TERMINAL_JOB_STATES.has(j.state) || j.owner === "this_instance");
      if (batches.some((j) => !TERMINAL_JOB_STATES.has(j.state) && j.owner !== "this_instance")) {
        setPastNotice("다른 실행의 내용 생성 작업이 끝나지 않은 채 남아 있습니다. 앱을 다시 시작하면 상태를 확인합니다.");
      }
      if (!latest) return;
      if (!TERMINAL_JOB_STATES.has(latest.state)) {
        latest.chapters.filter((c) => c.state === "succeeded").forEach((c) => appliedSeen.current.add(c.chapter_id));
        void follow(latest.id, false);
      } else { setJob(latest); summarize(latest, false); }
    }).catch(() => { /* 원장 문제는 생성 버튼을 누를 때 안내한다 */ });
    return () => { live = false; mounted.current = false; followAbort.current?.abort(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project.name]);

  const cancelGeneration = async () => {
    if (!job) return;
    try {
      const view = await api.cancelJob(project.name, job.id);
      if (view.kind === "chapters") setJob(view);  // 다음 조회까지 중단 버튼이 열려 있지 않게 한다 (리뷰 R12)
      setCancelNotice(CANCEL_REQUESTED_NOTICE);
    } catch (e) {
      setError(messageOf(e));
    }
  };

  // 묶음 등록. 응답을 받지 못한 등록은 같은 요청 ID로만 다시 보낸다 (계획서 5.9, D2b-5a 리뷰 R9).
  // approval: 승인 흐름의 등록인지, 장 하나 다시 생성인지. 실패 안내와 다시 시작이 다르다 (D2b-β 리뷰 R7)
  const register = async (targets: string[], headers: Record<string, string>, requestId: string, approval: boolean) => {
    startEpoch.current += 1;
    const previous = job;
    try {
      const started = await api.startChapters(project.name, targets, headers, requestId);
      pendingStart.current = null;
      onJobRegistered?.(started.id);
      // 같은 장의 지난 후보는 새 묶음이 대신하므로 등록에 성공한 뒤 버린다 (리뷰 R17, D2b-β 리뷰 R6)
      for (const c of previous?.chapters ?? []) {
        if (targets.includes(c.chapter_id) && (c.candidate_status === "held" || c.candidate_status === "stale")) {
          void api.dismissChapterCandidate(project.name, previous!.id, c.chapter_id).catch(() => {});
        }
      }
      return started;
    } catch (e) {
      pendingStart.current = e instanceof ApiError ? null : { targets, headers, requestId, approval };
      if (isStaleStoryPlan(e)) {
        // 등록 검사에서 구성 계획이 낡았다. 다시 시작해도 같은 거절이므로 복구 안내만 보인다 (D2b-β 리뷰 R2)
        setCanRestart(false);
        showFailure(e);
        return null;
      }
      setStartError(e);  // 원인별 안내로 보인다 (D3a-4)
      const what = approval ? "장 구성은 저장했지만" : "이 장의 다시 생성은";
      if (e instanceof ApiError && e.status === 412) {
        // 등록 기준 저장본이 바뀌었다. 다시 시작 대신 서버 내용을 다시 읽게 한다 (리뷰 R10)
        setCanRestart(false);
        setStartFailure(`${what} 다른 곳에서 먼저 저장되어 내용 생성을 시작하지 못했습니다. 서버 내용을 다시 읽어 주세요.`);
        onConflict?.();
      } else {
        // 장 하나 다시 생성은 그 장의 버튼으로 다시 시작한다. 응답을 받지 못한 등록만 같은 요청으로 다시 보낸다
        setCanRestart(approval || pendingStart.current !== null);
        setStartFailure(approval ? "장 구성은 저장했고 내용 생성은 시작하지 못했습니다."
          : "이 장의 다시 생성을 시작하지 못했습니다.");
      }
      return null;
    }
  };

  // 등록만 다시 보낸다. 응답을 받지 못한 경우는 같은 요청 ID, 그 밖에는 승인부터 다시 한다
  const restart = async () => {
    const pending = pendingStart.current;
    if (!pending) { void approve(); return; }
    setBusy(true);
    onBusyChange?.(true);
    setStartFailure("");
    setStartError(null);
    const started = await register(pending.targets, pending.headers, pending.requestId, pending.approval);
    if (!started || !mounted.current) { setBusy(false); onBusyChange?.(false); return; }
    appliedSeen.current = new Set();
    setJob(started);
    await follow(started.id, true);
  };

  const approve = async () => {
    // 다시 승인하면 복사 상자가 지워진다. 먼저 확인한다 (리뷰 R1)
    if (unsavedBackup !== null && !window.confirm(UNSAVED_RESULT_CONFIRM)) return;
    // AI 재생성 초안은 장 id가 재부여되어 옛 슬라이드와의 대응이 보장되지 않으므로 전면 교체한다 (결정 15).
    // 기존 구조안을 손으로 고친 경우에만 id와 템플릿이 일치하는 슬라이드를 계승한다
    const kept = keptSlides();
    const droppedCount = deck.slides.length - kept.length;
    if (droppedCount > 0) {
      const ok = window.confirm(
        draftGenerated
          ? `새 구조안을 승인하면 기존 장 내용 ${droppedCount}개를 지우고 전부 새로 생성합니다. 계속할까요?`
          : `구조안 변경으로 기존 장 내용 ${droppedCount}개가 사라집니다. 계속할까요?`,
      );
      if (!ok) return;
    }
    const targets = draft.filter((c) => !kept.some((s) => s.chapter_id === c.id)).map((c) => c.id);
    const unknown = job?.chapters.some((c) => c.state === "remote_completion_unknown" && targets.includes(c.chapter_id));
    if (unknown && !window.confirm(UNKNOWN_REGENERATE_CONFIRM)) return;
    setBusy(true);
    onBusyChange?.(true);
    resetError();
    setStoryStale(false);
    setCancelNotice("");
    setPreservedNotice("");
    setStartFailure("");
    setStartError(null);
    setPastNotice("");
    pendingStart.current = null;
    setUnsavedBackup(null);
    setChapterUsageSummary(null);
    setChapterUsageCount(0);
    setChapterUsageHadUnaccountedFailure(false);
    let started: JobView | null = null;
    try {
      // ① 로그인과 동의 확인 ② 승인 반영 ③ 묶음 등록 순서다. 동의를 거절하면 덱을 바꾸지 않는다 (D2b-5a).
      // 생성할 장이 없으면 AI에 보내지 않으므로 동의도 묻지 않는다
      let headers: Record<string, string> = {};
      // 원장을 쓸 수 없거나 다른 작업이 돌면 등록이 거절된다. 장 구성을 저장하기 전에 알린다 (D2b-β 리뷰 R11).
      // 확인 자체가 실패하면 등록 단계의 안내에 맡긴다
      if (targets.length > 0) {
        const status = await api.getActiveJob().catch(() => null);
        if (status && !status.ledger_available) { setError(LEDGER_UNAVAILABLE_BEFORE_APPROVAL); return; }
        if (status?.active) {
          setFailure(describeFailure(new ApiError(409, ACTIVE_JOB_BEFORE_APPROVAL, "generation_active", status.active)));
          return;
        }
      }
      try {
        if (targets.length > 0) headers = await api.prepareAi();
      } catch (e) {
        if (e instanceof AiConsentDeclined) { setCancelNotice(AI_CONSENT_CANCELLED_NOTICE); return; }
        throw e;
      }
      const current: Deck = {
        ...deck, structure: { ...deck.structure, chapters: draft, story_plan: storyPlan }, slides: kept,
      };
      try {
        await api.putDeck(project.name, current, true);  // 승인 반영: 직전 상태가 스냅샷으로 남는다
      } catch (e) {
        if (!(e instanceof ApiError && e.status === 412)) throw e;
        const kept = await preserveUnsaved(current, "conflict");
        onConflict?.();
        setFailure({ ...describeFailure(e), what: APPROVAL_CONFLICT, preserved: kept ?? APPROVAL_NOT_PRESERVED });
        return;
      }
      onDeckChange(current);
      if (structureJob.current) {
        // 만드는 동안 입력이 바뀐 구조안은 서버가 반영 처분을 거절한다. 그때는 버려서 낡은 후보로 되살아나지 않게 한다 (D2b-β 리뷰 R4)
        const id = structureJob.current;
        void api.settleCandidate(project.name, id, "applied").catch(() => settle(project.name, id, "dismissed"));
        structureJob.current = null;
      }
      setEarlierNotice("");
      setDraftGenerated(false);  // 승인이 반영된 순간부터는 재승인이 성공분을 계승한다 (실패한 장만 재생성)
      setShowJob(false);
      if (targets.length === 0) { onDone(); return; }
      started = await register(targets, headers, newRequestId(), true);
    } catch (e) {
      showFailure(e);
    } finally {
      if (!started || !mounted.current) { setBusy(false); onBusyChange?.(false); }
    }
    // 승인 도중 화면이 내려갔으면 조회를 시작하지 않는다 (리뷰 R8)
    if (started && mounted.current) {
      appliedSeen.current = new Set();
      setJob(started);
      await follow(started.id, true);
    }
  };

  // 장 하나를 새 묶음으로 다시 생성한다. 장 구성은 이미 저장했으므로 덱을 저장하지 않는다 (D2b-5a)
  const regenerateChapter = async (chapterId: string) => {
    const row = job?.chapters.find((c) => c.chapter_id === chapterId);
    if (row?.state === "remote_completion_unknown" && !window.confirm(UNKNOWN_REGENERATE_CONFIRM)) return;
    setBusy(true);
    onBusyChange?.(true);
    resetError();
    setStoryStale(false);
    setCancelNotice("");
    setStartFailure("");
    setStartError(null);
    let started: JobView | null = null;
    try {
      const headers = await api.prepareAi();
      started = await register([chapterId], headers, newRequestId(), false);
    } catch (e) {
      if (e instanceof AiConsentDeclined) setCancelNotice(AI_CONSENT_CANCELLED_NOTICE);
      else showFailure(e);
    } finally {
      if (!started || !mounted.current) { setBusy(false); onBusyChange?.(false); }
    }
    if (started && mounted.current) {
      setJob(started);
      await follow(started.id, true);
    }
  };

  // 이전 입력 기준 후보나 취소 뒤 도착한 결과를 버린다. 버린 장은 결과 없이 실패한 장과 같이 다시 생성할 수 있다
  const dismissCandidate = async (chapterId: string) => {
    if (!job || dismissing.current) return;
    dismissing.current = true;
    try {
      setJob(await api.dismissChapterCandidate(project.name, job.id, chapterId));
    } catch (e) {
      // 이미 처분된 후보면 오류 대신 지금 상태를 다시 읽는다 (리뷰 R13)
      if (e instanceof ApiError && e.status === 409) setJob(await api.getJob(project.name, job.id).catch(() => job));
      else setError(messageOf(e));
    } finally {
      dismissing.current = false;
    }
  };

  // 장별 행동: 결과가 없는 장은 다시 생성할 수 있고, 이전 입력 기준 후보는 내용을 볼 수 있다
  const chapterRow = (chapterId: string) => job && showJob && !busy && !draftDirty
    ? job.chapters.find((c) => c.chapter_id === chapterId && RETRYABLE_STATES.has(c.state)
      && c.error?.code !== "held_stale_plan" && !deck.slides.some((sl) => sl.chapter_id === chapterId))
    : undefined;

  return (
    <div className="structure-screen">
      {/* 생성 중에는 아래 입력 영역이 잠기므로 중단 버튼은 그 밖에 둔다 */}
      {busy && job && !TERMINAL_JOB_STATES.has(job.state) && (
        <p><button onClick={cancelGeneration} disabled={job.state === "cancel_requested" || job.cancel_requested}>생성 중단</button></p>
      )}
      <fieldset className="structure-controls" disabled={busy || rewriteActive || documentActive}>
      {error && <p role="alert">{error}</p>}
      {followError && <p role="status">{followError}</p>}
      <FailureNotice failure={failure} />
      {batchFailure && <FailureNotice failure={batchFailure.failure} lead={batchFailure.lead} />}
      {formatWhat && <FailureNotice failure={describeAiOutput(formatJob.current, formatWhat)} actions={busy ? {} : { regenerate: () => void generate() }}>
        {rawText && <><p>AI 응답 원문</p><pre>{rawText}</pre></>}
        {structureUsage && <p className="usage">{formatUsage(structureUsage)}</p>}
      </FailureNotice>}
      {startFailure && (startError
        ? <FailureNotice failure={describeFailure(startError)} lead={startFailure} />
        : <p role="alert">{startFailure}</p>)}
      {startFailure && canRestart && <p><button onClick={() => void restart()}>내용 생성 다시 시작</button></p>}
      {pastNotice && <p className="notice">{pastNotice}</p>}
      {preservedNotice && <p role="status">{preservedNotice}</p>}
      {unsavedBackup && (
        <div role="alert">
          <p>생성 결과를 저장하지 못했고 보존도 하지 못했습니다. 이 화면을 떠나기 전에 아래 내용을 복사해 보관해 주세요.</p>
          <UnsavedChangeBackup text={unsavedBackup} label="저장하지 못한 생성 결과" />
        </div>
      )}
      {storyStale && <div role="alert"><StoryPlanRecoveryGuidance hasDiagrams={hasDiagrams} /></div>}
      {cancelNotice && <p className="notice">{cancelNotice}</p>}
      {earlierNotice && <p className="notice">{earlierNotice}
        {staleStructure.current && <Button variant="danger" onClick={() => {
          void settle(project.name, staleStructure.current!, "dismissed");
          staleStructure.current = null;
          setEarlierNotice("");
        }}>후보 버리기</Button>}</p>}
      {/* C-1 리뷰 반영: draft 유무와 무관하게 렌더한다(형식 오류 안내 근처). 사용량과 응답 원문은 접힌 진단
          상세에 둔다. 구조안 형식 오류면 위 실패 안내의 진단 상세에 있다 (D3a-4, R12) */}
      {!formatWhat && (rawText || structureUsage) && <Diagnostics>
        {rawText && <><p>AI 응답 원문</p><pre>{rawText}</pre></>}
        {structureUsage && <p className="usage">{formatUsage(structureUsage)}</p>}
      </Diagnostics>}
      {numbers.length > 0 && (
        <p className="number-warning">자료에서 찾지 못한 수치가 있습니다: {numbers.join(", ")}. 반영 전에 확인해 주세요.</p>
      )}
      <section>
        <h2>구조안</h2>
        <div className="field">
          <label>보고 질문 (선택)
            <input aria-label="보고 질문" value={decisionQuestion} disabled={busy} readOnly={hasDiagrams}
              placeholder="이 보고서로 무엇을 판단해야 하나요?"
              onChange={(e) => setDecisionQuestion(e.target.value)} />
          </label>
          <p>질문을 입력하면 주장별 근거와 전체 보고 흐름을 함께 계획합니다.</p>
        </div>
        <div className="field">
          <label>목표 장수 (비우면 AI가 정함)
            <input aria-label="목표 장수" type="number" min={1} value={targetChapters}
              onChange={(e) => setTargetChapters(e.target.value)} />
          </label>
        </div>
        <div className="field">
          <label>문서의 주안점 및 원하는 결과 입력
            <textarea aria-label="문서의 주안점 및 원하는 결과 입력" rows={5} value={instructions}
              onChange={(e) => setInstructions(e.target.value)} />
          </label>
        </div>
        <div className="actions">
          <Button variant={generatePrimary ? "primary" : "secondary"} onClick={generate} disabled={busy || hasDiagrams}>
            {draft.length > 0 || rawText ? "다시 생성" : "구조안 생성"}
          </Button>
          {draft.length === 0 && !busy && <span> 자료를 먼저 넣고 눌러 주세요.</span>}
          {busy && <span> 진행 중입니다. 잠시 기다려 주세요...</span>}
        </div>
        {hasDiagrams && <div className="notice">
          <p>저장된 도식을 보존하기 위해 전체 구조안 다시 생성은 아직 지원하지 않습니다. 편집 단계에서 ‘도식 수정’으로 내용을 고칠 수 있으며 여기서는 장 순서를 바꿀 수 있습니다.</p>
          {!storyStale && <details><summary>자료나 보고 계획이 달라졌다면</summary>
            <StoryPlanRecoveryGuidance hasDiagrams confirmed={false} />
          </details>}
        </div>}
      </section>
      {storyPlan && <StoryPlanView plan={storyPlan} />}
      {draft.length > 0 && (
        <section>
          <h2>장 구성</h2>
          <div className="structure-table-scroll" role="region" aria-label="장 구성표" tabIndex={0}>
          <table>
            <thead>
              <tr><th>순서</th><th>주제</th><th>결론 한 줄</th><th>템플릿</th><th></th></tr>
            </thead>
            <tbody ref={tableRef}>
              {draft.map((c, i) => (
                <tr key={c.id} data-chapter-id={c.id}>
                  <td>
                    <button aria-label={`${c.topic} 위로`} onClick={() => move(i, -1)}>위</button>
                    <button aria-label={`${c.topic} 아래로`} onClick={() => move(i, 1)}>아래</button>
                  </td>
                  <td><input aria-label={`${i + 1}번 장 주제`} value={c.topic} readOnly={c.template === "diagram"}
                    onChange={(e) => update(i, { topic: e.target.value })} /></td>
                  <td><input aria-label={`${i + 1}번 장 결론`} value={c.conclusion ?? ""} readOnly={c.template === "diagram"}
                    onChange={(e) => update(i, { conclusion: e.target.value })} /></td>
                  <td>
                    <select aria-label={`${i + 1}번 장 템플릿`} value={c.template}
                      disabled={c.template === "diagram"}
                      onChange={(e) => update(i, { template: e.target.value as TemplateName })}>
                      {SELECTABLE_TEMPLATES.map((v) => (
                        <option key={v} value={v}>{TEMPLATE_LABELS[v]}</option>
                      ))}
                      {c.template === "diagram" && <option value="diagram">{TEMPLATE_LABELS.diagram}</option>}
                    </select>
                  </td>
                  <td>
                    <button aria-label={`${c.topic} 삭제`} disabled={c.template === "diagram"} onClick={() => remove(i)}>삭제</button>
                    {progress[c.id] === "취소 요청됨" ? <> <StatusIndicator kind="cancel_requested" /></>
                      : progress[c.id] === "완료 여부 확인 필요" ? <> <StatusIndicator kind="completion_unknown" /></>
                        : progress[c.id] && <span> {progress[c.id]}</span>}
                    {chapterRow(c.id) && (
                      <button aria-label={`${i + 1}번 장 다시 생성`} onClick={() => void regenerateChapter(c.id)}>
                        {["stale", "held"].includes(chapterRow(c.id)!.candidate_status) ? "현재 입력으로 다시 생성" : "이 장 다시 생성"}</button>
                    )}
                    {["stale", "held"].includes(chapterRow(c.id)?.candidate_status ?? "") && (<>
                      {candidateText(chapterRow(c.id)!) && (
                        <details><summary>후보 보기</summary><pre>{candidateText(chapterRow(c.id)!)}</pre></details>
                      )}
                      <Button variant="danger" aria-label={`${i + 1}번 장 후보 버리기`} onClick={() => void dismissCandidate(c.id)}>후보 버리기</Button>
                    </>)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
          <button onClick={add}>장 추가</button>
          {/* F2 리뷰 반영: 성공한 장이 하나도 없어도(전부 실패) 실패 단서만은 표시한다.
              chapterUsageSummary만 조건으로 두면 성공분이 0건일 때 이 문단 자체가 사라졌다 */}
          {(chapterUsageSummary || chapterUsageHadUnaccountedFailure) && <Diagnostics>
            <p className="usage">
              {[
                chapterUsageSummary
                  && `장 생성 ${chapterUsageCount}회: ${formatUsage(chapterUsageSummary).replace(/^AI 사용량: /, "")}`,
                chapterUsageHadUnaccountedFailure && FAILED_CHAPTER_USAGE_NOTICE,
              ].filter(Boolean).join(" ")}
            </p>
          </Diagnostics>}
          {job && showJob && !busy && (() => {
            // 가장 최근 묶음이 장 하나만 다시 만들었더라도 요약은 덱 전체의 빈 장을 센다
            const chapters = deck.structure.chapters;
            const missing = chapters.filter((ch) => !deck.slides.some((sl) => sl.chapter_id === ch.id));
            return missing.length > 0
              ? <p className="notice">{job.state === "failed" && <><StatusIndicator kind="failed" detail={`${chapters.length}장 중 ${missing.length}장 실패`} />{" "}</>}
                {chapters.length}장 중 {missing.length}장을 만들지 못했습니다. 아래 버튼을 누르면 만들지 못한 장만 다시 생성합니다.</p>
              : null;
          })()}
          {questionChanged && <p className="notice">보고 질문이 바뀌었습니다. 구조안을 다시 생성해 주세요.</p>}
          {validDraft && replacedCount > 0 && (
            <p className="notice-warning" id="approve-replace-warning">
              승인하면 기존 장 내용 {replacedCount}개를 지우고 새로 생성합니다.</p>)}
          <Button variant={validDraft ? "primary" : "secondary"} onClick={approve}
            aria-describedby={validDraft && replacedCount > 0 ? "approve-replace-warning" : undefined}
            disabled={busy || draft.length === 0 || questionChanged}>승인하고 내용 생성</Button>
        </section>
      )}
      </fieldset>
      {deck.structure.story_plan && <StoryRewritePanel projectName={project.name} deck={deck}
        disabled={busy || documentActive || draftGenerated || JSON.stringify(draft) !== JSON.stringify(deck.structure.chapters)}
        onBusyChange={onBusyChange} onActiveChange={setRewriteActive} onConflict={onConflict}
        onScreenReady={registerRewrite} onDirtyChange={setRewriteDirty}
        onApplied={saved => {
          setDraft(saved.structure.chapters); setStoryPlan(saved.structure.story_plan ?? null);
          setDecisionQuestion(saved.structure.story_plan!.brief.decision_question);
          setDraftGenerated(false); setStoryStale(false); resetError();
          setProgress({}); onDeckChange(saved);
        }} />}
      {/* 문서 전체 변경과 근거 이동은 JSON을 다루는 고급 작업이라 접힌 영역에 두어 단계의 주 행동과 섞지 않는다
          (계획 4.1). 패널이 열려 있는 동안에는 접히지 않는다: 접기가 패널 닫기의 이탈 확인(documentLeave)을
          우회해 입력을 숨기지 않게 하고, 닫기는 아래 버튼으로만 한다 */}
      <details className="advanced-actions" open={documentOpen ? true : undefined}
        onToggle={(e) => { if (documentOpen && !e.currentTarget.open) e.currentTarget.open = true; }}>
      <summary>고급 작업</summary>
      <button aria-expanded={documentOpen} disabled={busy || rewriteActive} onClick={()=>{
        if(!documentOpen){setDocumentOpen(true);return;}
        void documentLeave.current().then(allowed=>{if(allowed){setDocumentOpen(false);documentLeave.current=async()=>true;setDocumentDirty(false);setDocumentActive(false);}});
      }}>문서 전체 변경과 근거 이동</button>
      {documentOpen && <DocumentChangePanel projectName={project.name} deck={deck}
        disabled={busy || rewriteActive || draftGenerated || JSON.stringify(draft)!==JSON.stringify(deck.structure.chapters)}
        onBusyChange={onBusyChange} onActiveChange={setDocumentActive} onConflict={onConflict}
        onScreenReady={registerDocument} onDirtyChange={setDocumentDirty}
        onApplied={saved=>{
          setDraft(saved.structure.chapters);setStoryPlan(saved.structure.story_plan??null);
          setDecisionQuestion(saved.structure.story_plan?.brief.decision_question??"");
          setDraftGenerated(false);setStoryStale(false);resetError();setProgress({});onDeckChange(saved);
        }} />}
      </details>
    </div>
  );
}
