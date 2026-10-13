import { useEffect, useRef, useState } from "react";
import {
  AiConsentDeclined, api, ApiError, isStaleStoryPlan, type ChapterResult, type Deck, type JobView, type ProjectInfo,
  type Slots,
} from "../api/client";
import {
  blockingReasons, endedSince, FAILED_JOB_STATES, JOB_FOLLOW_ERROR, sameSlots, slotsText, jobResult, JobCancelled, pendingCandidate, reasonText, runJob, runningJob, settle,
  waitJob,
} from "../api/jobs";
import { formatUsage } from "../api/usage";
import { StoryPlanRecoveryGuidance } from "../screens/StoryPlanRecoveryGuidance";
import { Button } from "../ui/Button";
import { Diagnostics } from "../ui/Diagnostics";
import { describeAiOutput, describeFailure, type FailureDescription } from "../ui/failure";
import { FailureNotice } from "../ui/FailureNotice";
import { CandidateCompareDialog, STALE_BASE, type CompareSelection } from "./CandidateCompareDialog";

// 취소는 실패가 아니다 (계획서 B3): StructureScreen의 취소 안내와 같은 문구다
const AI_CONSENT_CANCELLED_NOTICE = "전송을 취소했습니다. 필요하면 다시 시도해 주세요.";

const KINDS = ["chapter", "condense"] as const;
// 적용 요청이 500, 503, 원장 오류로 끝나면 덱은 반영됐을 수 있다. 다음 자동 저장을 멈추고 다시 읽게 한다 (계획 4.7의 6)
export const APPLY_UNCONFIRMED = "반영 결과를 확인하지 못했습니다. 서버 내용을 다시 읽어 주세요.";
// 서버 판정이 반영을 막은 이유. 후보를 다시 조회해 이전 입력 기준 후보로 보인다 (계획 4.8 상태 코드 표)
const APPLY_BLOCKING = new Set(["chapter_missing", "template_changed", "chapter_changed", "story_plan_changed",
  "sources_changed", "slots_changed"]);

export function GeneratePanel({ project, deck, chapterId, onFlush, onApplied, onConflict, onApplyBusyChange, seenJobFailures,
  failuresSince = 0, pollIntervalMs = 1000 }: {
  project: ProjectInfo;
  deck: Deck;
  chapterId: string;
  // 서버 적용의 화면 계약 (D3c-5, 계획 4.7). 반영 직전에 남은 편집을 저장하고(실패하면 진행하지 않는다), 성공하면 응답
  // 덱을 저장본으로 받는다. base는 요청 직전의 화면 덱이다. 그사이 덱이 바뀌었으면 받는 쪽이 버린다(도식 경로와 같다)
  onFlush: () => Promise<boolean>;
  onApplied: (saved: Deck, base: Deck) => void;
  onConflict: (message: string) => void;  // 412와 확인하지 못한 결과: 자동 저장을 멈추고 다시 읽기를 연다
  onApplyBusyChange?: (busy: boolean) => void;  // 요청 중 편집 화면을 잠근다(템플릿 전환과 같다)
  // 이미 보인 실패와 기준 시각. 다시 열 때 이 장의 가장 최근 작업이 그 뒤에 실패했으면 한 번 보인다 (D3a-β 재리뷰 F3)
  seenJobFailures?: Set<string>;
  failuresSince?: number;
  pollIntervalMs?: number;
}) {
  const [instructions, setInstructions] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ChapterResult | null>(null);
  const [job, setJob] = useState<JobView | null>(null);  // 결과를 만든 작업 (후보 처분과 낡음 판정)
  const [earlier, setEarlier] = useState(false);  // 화면을 다시 열어 찾은 지난 후보
  const [error, setError] = useState("");  // 화면이 아는 문구(반영 전 확인 실패)
  const [failure, setFailure] = useState<unknown>(null);  // 생성 실패. 원인별 안내로 보인다 (D3a-4)
  const [followError, setFollowError] = useState("");
  const [storyStale, setStoryStale] = useState(false);
  const [cancelNotice, setCancelNotice] = useState("");  // AI 전송 취소 안내 (role=alert 아님)
  // 반영을 시도했을 때 서버가 막은 이유. 다시 조회한 작업에 없을 수 있어(축약 슬롯, 이전 버전 결과) 따로 둔다 (D3c-5 리뷰 F5)
  const [refused, setRefused] = useState<string[]>([]);
  const [comparing, setComparing] = useState(false);  // 비교 화면이 열려 있다 (D3c-6)
  const compareButton = useRef<HTMLButtonElement>(null);
  const regenerateButton = useRef<HTMLButtonElement>(null);
  const slide = deck.slides.find((s) => s.chapter_id === chapterId);
  const chapterIndex = deck.structure.chapters.findIndex((ch) => ch.id === chapterId);
  const chapterTitle = chapterIndex >= 0 ? `${chapterIndex + 1}장 ${deck.structure.chapters[chapterIndex].topic}` : "이 장";
  const deckRef = useRef(deck);
  deckRef.current = deck;
  const chapterIdRef = useRef(chapterId);
  chapterIdRef.current = chapterId;
  const follow = useRef<AbortController | null>(null);

  const show = (view: JobView, fromEarlier: boolean) => {
    setRefused([]);
    setJob(view);
    setEarlier(fromEarlier);
    try {
      setResult(jobResult<ChapterResult>(view));
    } catch (e) {
      showError(e);
    }
  };
  const showError = (e: unknown) => {
    if (e instanceof ApiError && e.job) seenJobFailures?.add(e.job.id);
    if (e instanceof AiConsentDeclined) setCancelNotice(AI_CONSENT_CANCELLED_NOTICE);
    else if (e instanceof JobCancelled) setCancelNotice("생성이 취소되었습니다.");
    else if (isStaleStoryPlan(e)) setStoryStale(true);
    else setFailure(e);
  };

  // 장을 전환하면 이전 장의 결과와 오류를 비운다: 다른 장에 반영되는 오귀속 쓰기 방지 (리뷰 반영).
  // 그 장의 진행 중 작업은 이어서 조회하고, 처분되지 않은 지난 결과는 다시 보인다 (D2b-5b)
  useEffect(() => {
    setResult(null);
    setJob(null);
    setEarlier(false);
    setError("");
    setFailure(null);
    setFollowError("");
    setStoryStale(false);
    setCancelNotice("");
    setRefused([]);
    setComparing(false);
    setBusy(false);
    const controller = new AbortController();
    follow.current = controller;
    api.listJobs(project.name).then(async (jobs) => {
      if (controller.signal.aborted) return;
      const running = runningJob(jobs, [...KINDS], chapterId);
      if (running) {
        setBusy(true);
        try {
          const final = await waitJob(project.name, running, { intervalMs: pollIntervalMs, signal: controller.signal,
            onError: () => setFollowError(JOB_FOLLOW_ERROR) });
          show(final, false);
        } catch { /* 장을 옮겼다 */ } finally {
          if (!controller.signal.aborted) setBusy(false);
        }
        return;
      }
      const earlierJob = pendingCandidate(jobs, [...KINDS], chapterId);
      if (earlierJob) { show(earlierJob, true); return; }
      // 이 장의 가장 최근 작업이 이 화면이 내려간 동안 실패했으면 원인별 안내로 한 번 보인다
      const last = jobs.find((j) => (KINDS as readonly string[]).includes(j.kind) && j.target === chapterId);
      if (last && FAILED_JOB_STATES.has(last.state) && !seenJobFailures?.has(last.id) && endedSince(last, failuresSince)) {
        seenJobFailures?.add(last.id);
        show(last, false);
      }
    }).catch(() => { /* 지난 결과를 찾지 못해도 새 생성은 할 수 있다 */ });
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chapterId, project.name]);

  if (deck.structure.chapters.some(ch => ch.id === chapterId && ch.template === "diagram")) {
    return null;
  }

  const run = async (kind: "chapter" | "condense", params: object) => {
    const requestedChapterId = chapterId;  // 호출 시점의 장을 캡처해 응답 도착 시 대조한다 (리뷰 반영)
    const controller = follow.current;
    const previous = job;  // 등록에 성공하면 보이던 후보는 새 생성이 대신한다 (D2b-5b 리뷰 R2)
    setBusy(true);
    setError("");
    setFailure(null);
    setFollowError("");
    setStoryStale(false);
    setCancelNotice("");
    setResult(null);
    setJob(null);
    setEarlier(false);
    setRefused([]);
    try {
      // 장을 옮기면 조회만 멈춘다. 작업은 끝까지 돌고 결과는 돌아왔을 때 지난 후보로 보인다
      const { job: final } = await runJob<ChapterResult>(project.name, kind, { chapter_id: requestedChapterId, ...params },
        { intervalMs: pollIntervalMs, signal: controller?.signal, onError: () => setFollowError(JOB_FOLLOW_ERROR),
          onStarted: () => { if (previous && previous.candidate_status !== "applied") void settle(project.name, previous.id, "dismissed"); } });
      if (chapterIdRef.current !== requestedChapterId) return;  // 그사이 장이 바뀌었으면 응답을 버린다
      setFollowError("");
      show(final, false);
    } catch (e) {
      if (chapterIdRef.current !== requestedChapterId || controller?.signal.aborted) return;
      showError(e);
    } finally {
      // 장을 오가며 효과가 새 조회를 시작했으면 그쪽이 바쁨을 관리한다 (리뷰 R17)
      if (chapterIdRef.current === requestedChapterId && follow.current === controller) setBusy(false);
    }
  };

  const regenerate = () => run("chapter", { instructions });
  // 이 패널에서 부른 적이 없으면(다시 연 지난 작업) 그 작업의 종류로 다시 부른다
  // 다시 생성하라는 안내는 바로 위의 두 버튼을 가리킨다. 같은 일을 하는 버튼을 안내 안에 하나 더 두지 않는다
  // (D3a 묶음 리뷰 A8). 다른 장의 요청을 다시 부를 일도 없어진다 (D3a-4 리뷰 R8)
  const POINT_UP = "위의 '이 장 다시 생성'이나 '이 장 축약'을 다시 눌러 주세요.";
  const relabel = (d: FailureDescription): FailureDescription =>
    (["regenerate", "retry", "retry_later", "regenerate_chapter", "check_input"].includes(d.action)
      ? { ...d, guidance: d.action === "retry_later" ? `잠시 뒤 ${POINT_UP}` : POINT_UP } : d);
  const condense = () => {
    if (!slide) return;
    void run("condense", { slots: slide.slots, instructions });
  };

  // 반영을 막는 낡음: 서버 판정에 더해, 축약은 요청한 슬롯과 지금 슬롯이 다르면 낡았다(화면 판정, 계획서 5.8)
  const reasons = job ? blockingReasons(job) : [];
  if (job?.kind === "condense" && slide
      && !sameSlots((job.params as { slots?: Slots }).slots, slide.slots)) {
    reasons.push("slots_changed");
  }
  for (const r of refused) if (!reasons.includes(r)) reasons.push(r);
  const elsewhere = job?.stale_reasons.includes("deck_changed_elsewhere") ?? false;
  const dismiss = () => {
    if (job) void settle(project.name, job.id, "dismissed");
    setResult(null);
    setJob(null);
    setEarlier(false);
  };

  // 서버가 후보를 지금 덱에 합쳐 스냅샷과 함께 저장하고 처분을 applied로 바꾼다 (D3c-5, 계획 4.7, 4.8). 판정(입력이 바뀐
  // 후보, 축약 뒤 바뀐 슬롯)도 서버가 저장 직전에 한다. 비교 화면(D3c-6)이 생기기 전까지는 서버의 기본 선택으로 반영한다:
  // 다시 생성은 직접 고친 문구만 지금 문구로 두고, 축약은 모두 새 문구다. 위치와 서식 수정은 남는다
  const applyResult = async (selection: CompareSelection) => {
    if (!result || result.status !== "ok" || !result.slots || busy || !job) return;
    const requestedChapterId = chapterId;
    const candidate = job;
    setBusy(true);
    setError("");
    setFailure(null);
    onApplyBusyChange?.(true);
    try {
      if (!await onFlush()) return;  // 저장 실패나 충돌이면 진행하지 않는다. 편집기의 안내가 보인다
      if (chapterIdRef.current !== requestedChapterId) return;
      const base = deckRef.current;
      const saved = await api.applyCandidate(project.name, candidate.id, selection);
      onApplied(saved, base);
      if (chapterIdRef.current !== requestedChapterId) return;
      setResult(null);
      setJob(null);
      setEarlier(false);
    } catch (e) {
      if (e instanceof ApiError && e.status === 412) onConflict(e.message);
      else if (e instanceof ApiError && e.status >= 500) onConflict(APPLY_UNCONFIRMED);
      if (chapterIdRef.current !== requestedChapterId) return;
      if (e instanceof ApiError && (e.status === 412 || e.status >= 500)) return;
      if (e instanceof ApiError && e.status === 409 && e.code && (APPLY_BLOCKING.has(e.code) || e.code === "not_applicable")) {
        // 반영 대신 이전 입력 기준 후보로 보이고 현재 입력으로 다시 생성을 연다
        setRefused([e.code]);
        try { setJob(await api.getJob(project.name, candidate.id)); } catch { /* 반영은 이미 막혔다 */ }
        return;
      }
      if (e instanceof ApiError && e.status === 409 && e.code === "candidate_settled") {
        // 다른 탭이 먼저 반영했거나 버렸다. 다시 반영할 수 없으므로 결과를 닫고 알린다 (D3c-5 리뷰 F5)
        setError(e.message);
        setResult(null);
        setJob(null);
        setEarlier(false);
        return;
      }
      setFailure(e);
    } finally {
      onApplyBusyChange?.(false);
      if (chapterIdRef.current === requestedChapterId) setBusy(false);
      setComparing(false);  // 결과(충돌 안내, 낡은 후보, 원인별 안내)는 이 패널과 편집기가 보인다
    }
  };

  // 비교 화면을 열기 전에 남은 편집을 저장한다. 미리 보기는 서버 저장본으로 계산하므로 저장하지 않으면 "지금"이 화면과
  // 다르다 (계획 4.7의 1). 저장이 실패하면 열지 않는다
  const openCompare = async () => {
    if (!result || result.status !== "ok" || busy || !job) return;
    const requestedChapterId = chapterId;
    setBusy(true);
    try {
      if (!await onFlush()) return;
      if (chapterIdRef.current === requestedChapterId) setComparing(true);
    } finally {
      if (chapterIdRef.current === requestedChapterId) setBusy(false);
    }
  };

  return (
    <section className="generate-panel">
      <h4>AI 다시 쓰기</h4>
      <div className="field">
        <label>지시사항 (선택)
          <textarea aria-label="재생성 지시사항" value={instructions}
            onChange={(e) => setInstructions(e.target.value)} />
        </label>
      </div>
      <div className="actions">
        <button ref={regenerateButton} onClick={regenerate} disabled={busy}>이 장 다시 생성</button>
        <button onClick={condense} disabled={busy || !slide}>이 장 축약</button>
      </div>
      {busy && <p>생성 중입니다. 잠시 기다려 주세요 (최대 5분)...</p>}
      {followError && <p role="status">{followError}</p>}
      {error && <p role="alert">{error}</p>}
      <FailureNotice failure={failure ? relabel(describeFailure(failure)) : null} />
      {storyStale && <div role="alert"><StoryPlanRecoveryGuidance
        hasDiagrams={deck.structure.chapters.some(chapter => chapter.template === "diagram")} /></div>}
      {cancelNotice && <p className="notice">{cancelNotice}</p>}
      {result && result.status === "format_error" && (
        <FailureNotice failure={relabel(describeAiOutput(job))}>
          <p>AI 응답 원문</p><pre>{result.raw_text}</pre>
          <p className="usage">{formatUsage(result.usage)}</p>
        </FailureNotice>
      )}
      {result && result.status === "ok" && reasons.length > 0 && (
        <div className="generate-result">
          <p>이전 입력 기준 후보입니다({reasonText(reasons)}). 반영하지 않고 현재 입력으로 다시 생성해 주세요.</p>
          <button ref={compareButton} onClick={() => void openCompare()} disabled={busy}>비교 보기</button>
          {(job?.kind !== "condense" || slide) && (
            <button onClick={() => (job?.kind === "condense" ? condense() : void regenerate())}>현재 입력으로 다시 생성</button>
          )}
          <Button variant="danger" onClick={dismiss}>버리기</Button>
        </div>
      )}
      {result && result.status === "ok" && reasons.length === 0 && (
        <div className="generate-result">
          {earlier && <p>이전에 만든 결과가 있습니다.</p>}
          {elsewhere && <p className="notice">덱의 다른 부분이 바뀌었지만 이 장의 입력은 그대로입니다.</p>}
          <p>새 초안이 준비되었습니다.
            {result.condensed && " 분량에 맞춰 축약했습니다."}
          </p>
          {result.warnings.length > 0 && (
            <ul>{result.warnings.map((w, i) => <li key={i}>{w.message}</li>)}</ul>
          )}
          {result.unverified_numbers.length > 0 && (
            <p className="number-warning">
              자료에서 찾지 못한 수치: {result.unverified_numbers.join(", ")}. 반영 전에 확인해 주세요.
            </p>
          )}
          {/* 반영은 비교 화면에서 단위마다 고른 뒤에 한다 (D3c-6, 계획 4.8) */}
          <button ref={compareButton} onClick={() => void openCompare()} disabled={busy}>비교하고 반영</button>
          <Button variant="danger" onClick={dismiss}>버리기</Button>
        </div>
      )}
      {comparing && job && result?.status === "ok" && result.slots && (
        <CandidateCompareDialog projectName={project.name} jobId={job.id} title={chapterTitle}
          candidateSlots={result.slots} returnFocus={compareButton} fallbackFocus={regenerateButton}
          onApply={(selection) => applyResult(selection)}
          onRegenerate={job.kind === "condense" ? (slide ? condense : undefined) : () => void regenerate()}
          onStaleBase={() => { setComparing(false); onConflict(STALE_BASE); }}
          onClose={() => setComparing(false)} />
      )}
      {/* F5 리뷰 반영: usage는 상태와 무관하게 항상 채워지는 필수 필드다(C2/C3 가정 6). 형식 오류면 실패 안내의
          진단 상세에, 그 밖에는 따로 접힌 진단 상세에 둔다 (D3a-4, R12) */}
      {result && result.status !== "format_error" && (
        <Diagnostics fields={job ? { jobId: job.id, jobKind: job.kind } : undefined}>
          <p className="usage">{formatUsage(result.usage)}</p>
          {result.format_retried && <p>형식 재시도 1회를 거쳤습니다.</p>}
        </Diagnostics>
      )}
    </section>
  );
}
