import { useCallback, useEffect, useRef, useState } from "react";
import {
  AiConsentDeclined, api, ApiError, followJob, isStaleStoryPlan, messageOf, newRequestId, TERMINAL_JOB_STATES,
  type Chapter, type ChapterView, type Deck, type GenerationUsage, type JobView, type ProjectInfo, type StoryPlan,
  type TemplateName,
} from "../api/client";
import { formatUsage, sumUsage } from "../api/usage";
import { SELECTABLE_TEMPLATES, TEMPLATE_LABELS } from "../editor/labels";
import { StoryPlanView } from "./StoryPlanView";
import { StoryPlanRecoveryGuidance } from "./StoryPlanRecoveryGuidance";
import { StoryRewritePanel } from "./StoryRewritePanel";
import { DocumentChangePanel } from "./DocumentChangePanel";
import { UnsavedChangeBackup } from "../editor/UnsavedChangeBackup";
import { formatSavedAt } from "../api/time";

// 실패한 장은 결과 자체가 없어 usage 합계에서 빠진다: 그 사실을 합계 줄에 밝힌다 (가정 7)
const FAILED_CHAPTER_USAGE_NOTICE =
  "(실패한 장의 사용량은 이 합계에 포함되지 않았습니다. 정확한 기록은 프로젝트 폴더의 ai-usage.jsonl)";

// 취소는 실패가 아니다 (계획서 B3): AI 전송 고지를 취소하면 "취소"로 표시하고 role=alert 배너를
// 띄우지 않는다. 이 문구는 GeneratePanel의 취소 안내와 같다
const AI_CONSENT_CANCELLED_NOTICE = "전송을 취소했습니다. 필요하면 다시 시도해 주세요.";
const UNSAVED_RESULT_CONFIRM =
  "저장하지 못한 생성 결과가 있습니다. 복사하지 않고 계속하면 그 결과는 사라집니다. 계속할까요?";

type ProgressLabel = "대기" | "생성 중" | "완료" | "실패" | "취소" | "보류" | "중단" | "취소 요청됨"
  | "완료 여부 확인 필요" | "이전 입력 기준";
type Progress = Record<string, ProgressLabel>;

const UNKNOWN_REGENERATE_CONFIRM =
  "완료 여부를 확인하지 못한 장이 있습니다. 다시 생성하면 AI 사용량이 한 번 더 기록될 수 있습니다. 계속할까요?";
const CANCEL_REQUESTED_NOTICE = "취소를 요청했습니다. AI가 응답을 멈추면 취소됨으로 바뀝니다.";

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

// 후보 슬롯의 글자만 모아 보인다. 사용자가 반영 여부를 판단하는 데는 구조보다 내용이 필요하다
function candidateText(chapter: ChapterView): string {
  const slots = (chapter.result as { slots?: unknown } | null)?.slots;
  const texts: string[] = [];
  const walk = (value: unknown, key = "") => {
    if (typeof value === "string") { if (value && key !== "template" && key !== "tone") texts.push(value); }
    else if (Array.isArray(value)) value.forEach((v) => walk(v));
    else if (value && typeof value === "object") Object.entries(value).forEach(([k, v]) => walk(v, k));
  };
  walk(slots);
  return texts.join("\n");
}

function nextChapterId(chapters: Chapter[]): string {
  const max = chapters
    .map((c) => /^c(\d+)$/.exec(c.id))
    .reduce((n, m) => (m ? Math.max(n, Number(m[1])) : n), 0);
  return `c${max + 1}`;
}

export function StructureScreen({ project, deck, onDeckChange, onDone, onBusyChange, onConflict, onScreenReady, onDirtyChange, pollIntervalMs = 1000 }: {
  project: ProjectInfo;
  deck: Deck;
  onDeckChange: (d: Deck) => void;
  onDone: () => void;
  onBusyChange?: (busy: boolean) => void;  // 승인 중 순차 생성 진행을 부모(ProjectView)에 알려 다른 탭 진입을 막는다
  onConflict?: () => void;  // 승인 루프의 putDeck이 412를 받으면 부모가 배너를 띄운다
  onScreenReady?: (flush: () => Promise<boolean>) => void;
  onDirtyChange?: (dirty: boolean) => void;
  pollIntervalMs?: number;  // 작업 조회 간격. 시험에서 실제 1초 대기를 쓰지 않게 한다 (계획서 5.9)
}) {
  const [draft, setDraft] = useState<Chapter[]>(deck.structure.chapters);
  const [storyPlan, setStoryPlan] = useState<StoryPlan | null>(deck.structure.story_plan ?? null);
  const [decisionQuestion, setDecisionQuestion] = useState(deck.structure.story_plan?.brief.decision_question ?? "");
  const [draftGenerated, setDraftGenerated] = useState(false);  // AI 재생성 초안 여부 (결정 15: 승인 시 전면 교체)
  const [targetChapters, setTargetChapters] = useState("");
  const [instructions, setInstructions] = useState("");
  const [busy, setBusy] = useState(false);
  const [rewriteActive, setRewriteActive] = useState(false);
  const [documentActive,setDocumentActive] = useState(false);
  const [documentOpen,setDocumentOpen] = useState(false);
  const rewriteLeave = useRef<()=>Promise<boolean>>(async()=>true);
  const documentLeave = useRef<()=>Promise<boolean>>(async()=>true);
  const dirtyParts = useRef({rewrite:false,document:false,draft:false,backup:false});
  const parentDirty = useRef(onDirtyChange);parentDirty.current=onDirtyChange;
  const reportDirty = useCallback(()=>{const d=dirtyParts.current;parentDirty.current?.(d.rewrite||d.document||d.draft||d.backup);},[]);
  const setRewriteDirty = useCallback((dirty:boolean)=>{dirtyParts.current.rewrite=dirty;reportDirty();},[reportDirty]);
  const setDocumentDirty = useCallback((dirty:boolean)=>{dirtyParts.current.document=dirty;reportDirty();},[reportDirty]);
  // 장 구성 초안이 저장본과 다르면 창 닫기 경고에 포함한다 (D2a-2: 종전에는 경고 없이 사라졌다)
  const draftDirty = JSON.stringify(draft) !== JSON.stringify(deck.structure.chapters);
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
  const [rawText, setRawText] = useState("");
  // 저장하지 못한 생성 결과의 보존 (D2a-2): 보존 안내 또는 보존마저 실패했을 때 복사할 내용
  const [preservedNotice, setPreservedNotice] = useState("");
  const [unsavedBackup, setUnsavedBackup] = useState<string | null>(null);
  const [numbers, setNumbers] = useState<string[]>([]);
  // 가장 최근 장 생성 묶음 (D2b-5a). 장별 진행 표시와 실패 요약은 원장의 이 작업에서 계산한다
  const [job, setJob] = useState<JobView | null>(null);
  const [showJob, setShowJob] = useState(true);  // 새 승인이나 재작성 적용 뒤에는 이전 요약을 숨긴다
  const [followError, setFollowError] = useState("");
  const [startFailure, setStartFailure] = useState("");
  const followAbort = useRef<AbortController | null>(null);
  const appliedSeen = useRef<Set<string>>(new Set());
  const progress: Progress = job && showJob ? Object.fromEntries(job.chapters.map((c) =>
    [c.chapter_id, chapterLabel(c, deck.slides.some((s) => s.chapter_id === c.chapter_id))])) : {};
  const setProgress = (_: Progress) => setShowJob(false);
  const [structureUsage, setStructureUsage] = useState<GenerationUsage | null>(null);
  const [chapterUsageSummary, setChapterUsageSummary] = useState<GenerationUsage | null>(null);
  const [chapterUsageCount, setChapterUsageCount] = useState(0);  // 합계에 실제로 실린 장 수
  const [chapterUsageHadUnaccountedFailure, setChapterUsageHadUnaccountedFailure] = useState(false);
  const questionChanged = decisionQuestion.trim() !== (storyPlan?.brief.decision_question ?? "");
  // 장 구성 초안, 보고 질문, 저장하지 못한 생성 결과가 남아 있으면 창 닫기 경고에 포함한다 (D2a-2, 리뷰 R1, R16)
  useEffect(()=>{
    dirtyParts.current.draft=draftDirty||questionChanged;
    dirtyParts.current.backup=unsavedBackup!==null;
    reportDirty();
  },[draftDirty,questionChanged,unsavedBackup,reportDirty]);
  const hasDiagrams = deck.structure.chapters.some(c => c.template === "diagram");
  const preserveUnsaved = async (target: Deck, reason: "conflict" | "generation_unsaved") => {
    try {
      const info = await api.saveDraft(project.name, { reason, source: "structure_approval", deck: target });
      setUnsavedBackup(null);
      setPreservedNotice(reason === "generation_unsaved"
        ? `저장하지 못한 생성 결과를 보존했습니다(${formatSavedAt(info.saved_at)}). 스냅샷 복구 화면의 "충돌로 보존한 변경"에서 보거나 복원할 수 있습니다.`
        : `승인하려던 장 구성을 보존했습니다(${formatSavedAt(info.saved_at)}). 스냅샷 복구 화면의 "충돌로 보존한 변경"에서 보거나 복원할 수 있습니다.`);
    } catch {
      setPreservedNotice("");
      setUnsavedBackup(JSON.stringify(target, null, 2));
    }
  };
  const showFailure = (error: unknown) => {
    const stale = isStaleStoryPlan(error);
    setStoryStale(stale);
    setError(stale ? "" : messageOf(error));
  };

  const generate = async () => {
    if (hasDiagrams) return;
    setBusy(true);
    onBusyChange?.(true);
    setError("");
    setStoryStale(false);
    setCancelNotice("");
    setRawText("");
    setStructureUsage(null);
    // F1 리뷰 반영: 새 구조안을 받으면 이전 승인 루프의 장 사용량 합계는 더 이상 유효하지 않다
    setChapterUsageSummary(null);
    setChapterUsageCount(0);
    setChapterUsageHadUnaccountedFailure(false);
    try {
      const n = targetChapters.trim() === "" ? undefined : Number(targetChapters);
      const result = await api.generateStructure(project.name, {
        target_chapters: n, instructions,
        ...(decisionQuestion.trim() ? { brief: {
          decision_question: decisionQuestion.trim(), audience: deck.meta.audience,
          report_type: deck.meta.report_type,
          reading_profile: storyPlan?.brief.reading_profile ?? "미지정",
          constraints: storyPlan?.brief.constraints ?? [],
        } } : {}),
      });
      if (result.status === "format_error") {
        setError(result.format_issue === "answer_not_in_summary"
          ? "AI가 만든 구성에서 핵심 답변을 설명하는 장에 일부 주장이 연결되지 않았습니다. 입력한 자료와 주안점은 유지했습니다. 다시 생성해 주세요."
          : "AI 응답을 형식에 맞게 읽지 못했습니다. 입력한 자료와 주안점은 유지했습니다. 다시 생성해 주세요.");
        setRawText(result.raw_text);
        setStructureUsage(result.usage);  // C-1 리뷰 반영: usage는 상태와 무관하게 항상 채워진다
      } else if (result.structure) {
        setDraft(result.structure.chapters);
        setStoryPlan(result.structure.story_plan ?? null);
        setDraftGenerated(true);
        setNumbers(result.unverified_numbers);
        setStructureUsage(result.usage);
      }
    } catch (e) {
      if (e instanceof AiConsentDeclined) setCancelNotice(AI_CONSENT_CANCELLED_NOTICE);
      else showFailure(e);
    } finally {
      setBusy(false);
      onBusyChange?.(false);
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
  const summarize = (view: JobView) => {
    const results = view.chapters.filter((c) => c.result);
    const usages = results.map((c) => (c.result as { usage?: GenerationUsage }).usage).filter(Boolean) as GenerationUsage[];
    setChapterUsageSummary(usages.length > 0 ? sumUsage(usages) : null);
    setChapterUsageCount(usages.length);
    // 시작 전에 취소된 장은 AI에 보내지 않았으므로 사용량 누락의 단서가 아니다
    setChapterUsageHadUnaccountedFailure(view.chapters.some((c) => !c.result
      && (["failed", "interrupted", "remote_completion_unknown"].includes(c.state)
        || (c.state === "cancelled" && c.started_at !== null))));
    const found = results.flatMap((c) => (c.result as { unverified_numbers?: string[] }).unverified_numbers ?? []);
    setNumbers((n) => [...new Set([...n, ...found])]);
    const malformed = view.chapters.filter((c) => c.error?.error_class === "ai_output" && c.result);
    if (malformed.length) setRawText((malformed[malformed.length - 1].result as { raw_text?: string }).raw_text ?? "");
    if (view.chapters.some((c) => c.error?.code === "stale_story_plan")) setStoryStale(true);
    if (view.started_at === null && view.error) {
      // 시작하기 전에 끝났다(다른 저장, AI 연결 변경 등). 장마다가 아니라 작업의 원인을 보인다 (D2b-4 리뷰 R12)
      setError(`내용 생성을 시작하지 못했습니다. ${view.error.detail ?? ""}`.trim());
      if (view.error.error_class === "base_changed") onConflict?.();
    } else if (view.outcome === "chain_broken") {
      setError("다른 창이나 프로그램에서 덱이 바뀌어 일부 장을 반영하지 않았습니다. 서버 내용을 다시 읽은 뒤 남은 장을 다시 생성해 주세요.");
      onConflict?.();
    } else if (view.state === "failed" && view.outcome !== "held_stale_plan") {
      const malformedOnly = view.chapters.every((c) => c.state === "succeeded" || c.error?.error_class === "ai_output");
      const detail = view.chapters.find((c) => c.state === "failed" && c.error?.detail)?.error?.detail;
      setError(malformedOnly ? "일부 장의 AI 응답을 형식에 맞게 읽지 못했습니다. 실패한 장만 다시 생성해 주세요."
        : `일부 장을 만들지 못했습니다${detail ? `(${detail})` : ""}. 실패한 장만 다시 생성해 주세요.`);
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
    try {
      const final = await followJob(() => api.getJob(project.name, jobId), async (view) => {
        setJob(view);
        setFollowError("");
        const newly = view.chapters.filter((c) => c.state === "succeeded" && !appliedSeen.current.has(c.chapter_id));
        if (newly.length > 0 || TERMINAL_JOB_STATES.has(view.state)) {
          newly.forEach((c) => appliedSeen.current.add(c.chapter_id));
          latest = await api.getDeck(project.name);
          onDeckChange(latest);
        }
      }, { intervalMs: pollIntervalMs, signal: controller.signal,
        onError: () => setFollowError("작업 상태를 확인하지 못했습니다. 계속 확인합니다.") });
      summarize(final);
      // 장 하나만 다시 만든 경우에도 다른 장이 비어 있으면 편집 탭으로 옮기지 않는다
      const complete = latest === null || (latest as Deck).structure.chapters
        .every((ch) => (latest as Deck).slides.some((sl) => sl.chapter_id === ch.id));
      if (registeredHere && final.state === "succeeded" && complete) onDone();
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
    api.listJobs(project.name).then((jobs) => {
      const latest = jobs.find((j) => j.kind === "chapters");
      if (!live || !latest) return;
      latest.chapters.filter((c) => c.state === "succeeded").forEach((c) => appliedSeen.current.add(c.chapter_id));
      if (!TERMINAL_JOB_STATES.has(latest.state) && latest.owner === "this_instance") void follow(latest.id, false);
      else { setJob(latest); summarize(latest); }
    }).catch(() => { /* 원장 문제는 생성 버튼을 누를 때 안내한다 */ });
    return () => { live = false; followAbort.current?.abort(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project.name]);

  const cancelGeneration = async () => {
    if (!job) return;
    try {
      await api.cancelJob(project.name, job.id);
      setCancelNotice(CANCEL_REQUESTED_NOTICE);
    } catch (e) {
      setError(messageOf(e));
    }
  };

  const approve = async () => {
    // 다시 승인하면 복사 상자가 지워진다. 먼저 확인한다 (리뷰 R1)
    if (unsavedBackup !== null && !window.confirm(UNSAVED_RESULT_CONFIRM)) return;
    // AI 재생성 초안은 장 id가 재부여되어 옛 슬라이드와의 대응이 보장되지 않으므로 전면 교체한다 (결정 15).
    // 기존 구조안을 손으로 고친 경우에만 id와 템플릿이 일치하는 슬라이드를 계승한다
    const draftById = new Map(draft.map((c) => [c.id, c]));
    const kept = draftGenerated ? [] : deck.slides.filter((s) => {
      const ch = draftById.get(s.chapter_id);
      return ch !== undefined && ch.template === s.slots.template;
    });
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
    setError("");
    setStoryStale(false);
    setCancelNotice("");
    setPreservedNotice("");
    setStartFailure("");
    setUnsavedBackup(null);
    setChapterUsageSummary(null);
    setChapterUsageCount(0);
    setChapterUsageHadUnaccountedFailure(false);
    let started: JobView | null = null;
    try {
      // ① 로그인과 동의 확인 ② 승인 반영 ③ 묶음 등록 순서다. 동의를 거절하면 덱을 바꾸지 않는다 (D2b-5a).
      // 생성할 장이 없으면 AI에 보내지 않으므로 동의도 묻지 않는다
      let headers: Record<string, string> = {};
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
        if (e instanceof ApiError && e.status === 412) { await preserveUnsaved(current, "conflict"); onConflict?.(); }
        throw e;
      }
      onDeckChange(current);
      setDraftGenerated(false);  // 승인이 반영된 순간부터는 재승인이 성공분을 계승한다 (실패한 장만 재생성)
      setShowJob(false);
      if (targets.length === 0) { onDone(); return; }
      try {
        started = await api.startChapters(project.name, targets, headers, newRequestId());
      } catch (e) {
        setStartFailure(`장 구성은 저장했고 내용 생성은 시작하지 못했습니다. ${messageOf(e)}`);
        return;
      }
    } catch (e) {
      showFailure(e);
    } finally {
      if (!started) { setBusy(false); onBusyChange?.(false); }
    }
    if (started) {
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
    setError("");
    setStoryStale(false);
    setCancelNotice("");
    setStartFailure("");
    let started: JobView | null = null;
    try {
      const headers = await api.prepareAi();
      started = await api.startChapters(project.name, [chapterId], headers, newRequestId());
    } catch (e) {
      if (e instanceof AiConsentDeclined) setCancelNotice(AI_CONSENT_CANCELLED_NOTICE);
      else {
        showFailure(e);
        if (e instanceof ApiError && e.status === 412) onConflict?.();
      }
    } finally {
      if (!started) { setBusy(false); onBusyChange?.(false); }
    }
    if (started) {
      setJob(started);
      await follow(started.id, true);
    }
  };

  // 이전 입력 기준 후보나 취소 뒤 도착한 결과를 버린다. 버린 장은 결과 없이 실패한 장과 같이 다시 생성할 수 있다
  const dismissCandidate = async (chapterId: string) => {
    if (!job) return;
    try {
      setJob(await api.dismissChapterCandidate(project.name, job.id, chapterId));
    } catch (e) {
      setError(messageOf(e));
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
        <p><button onClick={cancelGeneration} disabled={job.state === "cancel_requested"}>생성 중단</button></p>
      )}
      <fieldset className="structure-controls" disabled={busy || rewriteActive || documentActive}>
      {error && <p role="alert">{error}</p>}
      {followError && <p role="status">{followError}</p>}
      {startFailure && <p role="alert">{startFailure} <button onClick={approve}>내용 생성 다시 시작</button></p>}
      {preservedNotice && <p role="status">{preservedNotice}</p>}
      {unsavedBackup && (
        <div role="alert">
          <p>생성 결과를 저장하지 못했고 보존도 하지 못했습니다. 이 화면을 떠나기 전에 아래 내용을 복사해 보관해 주세요.</p>
          <UnsavedChangeBackup text={unsavedBackup} label="저장하지 못한 생성 결과" />
        </div>
      )}
      {storyStale && <div role="alert"><StoryPlanRecoveryGuidance hasDiagrams={hasDiagrams} /></div>}
      {cancelNotice && <p className="notice">{cancelNotice}</p>}
      {rawText && <details><summary>AI 응답 원문</summary><pre>{rawText}</pre></details>}
      {/* C-1 리뷰 반영: draft 유무와 무관하게 렌더한다(형식 오류 안내 근처).
          draft가 비어 있으면 "장 구성" 섹션 자체가 없어 그 안에 두면 최초 생성의
          format_error에서 사용량을 보여줄 자리가 없었다 */}
      {structureUsage && <p className="usage">{formatUsage(structureUsage)}</p>}
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
          <button onClick={generate} disabled={busy || hasDiagrams}>
            {draft.length > 0 || rawText ? "다시 생성" : "구조안 생성"}
          </button>
          {draft.length === 0 && !busy && <span> 자료를 먼저 넣고 눌러 주세요.</span>}
          {busy && <span> 진행 중입니다. 잠시 기다려 주세요...</span>}
        </div>
        {hasDiagrams && <div className="notice">
          <p>저장된 도식을 보존하기 위해 전체 구조안 다시 생성은 아직 지원하지 않습니다. 편집 탭에서 ‘도식 수정’으로 내용을 고칠 수 있으며 여기서는 장 순서를 바꿀 수 있습니다.</p>
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
            <tbody>
              {draft.map((c, i) => (
                <tr key={c.id}>
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
                    {progress[c.id] && <span> {progress[c.id]}</span>}
                    {chapterRow(c.id) && (
                      <button aria-label={`${i + 1}번 장 다시 생성`} onClick={() => void regenerateChapter(c.id)}>이 장 다시 생성</button>
                    )}
                    {["stale", "held"].includes(chapterRow(c.id)?.candidate_status ?? "") && (<>
                      {candidateText(chapterRow(c.id)!) && (
                        <details><summary>후보 보기</summary><pre>{candidateText(chapterRow(c.id)!)}</pre></details>
                      )}
                      <button aria-label={`${i + 1}번 장 후보 버리기`} onClick={() => void dismissCandidate(c.id)}>후보 버리기</button>
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
          {(chapterUsageSummary || chapterUsageHadUnaccountedFailure) && (
            <p className="usage">
              {[
                chapterUsageSummary
                  && `장 생성 ${chapterUsageCount}회: ${formatUsage(chapterUsageSummary).replace(/^AI 사용량: /, "")}`,
                chapterUsageHadUnaccountedFailure && FAILED_CHAPTER_USAGE_NOTICE,
              ].filter(Boolean).join(" ")}
            </p>
          )}
          {job && showJob && !busy && (() => {
            // 가장 최근 묶음이 장 하나만 다시 만들었더라도 요약은 덱 전체의 빈 장을 센다
            const chapters = deck.structure.chapters;
            const missing = chapters.filter((ch) => !deck.slides.some((sl) => sl.chapter_id === ch.id));
            return missing.length > 0
              ? <p className="notice">{chapters.length}장 중 {missing.length}장을 만들지 못했습니다. 아래 버튼을 누르면 만들지 못한 장만 다시 생성합니다.</p>
              : null;
          })()}
          {questionChanged && <p className="notice">보고 질문이 바뀌었습니다. 구조안을 다시 생성해 주세요.</p>}
          <button onClick={approve} disabled={busy || draft.length === 0 || questionChanged}>승인하고 내용 생성</button>
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
          setDraftGenerated(false); setStoryStale(false); setError("");
          setProgress({}); onDeckChange(saved);
        }} />}
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
          setDraftGenerated(false);setStoryStale(false);setError("");setProgress({});onDeckChange(saved);
        }} />}
    </div>
  );
}
