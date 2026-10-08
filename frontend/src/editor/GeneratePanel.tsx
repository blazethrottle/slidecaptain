import { useEffect, useRef, useState } from "react";
import {
  AiConsentDeclined, api, isStaleStoryPlan, messageOf, type ChapterResult, type Deck, type JobView, type ProjectInfo,
  type Slots,
} from "../api/client";
import {
  blockingReasons, JOB_FOLLOW_ERROR, sameSlots, slotsText, jobResult, JobCancelled, pendingCandidate, reasonText, runJob, runningJob, settle,
  waitJob,
} from "../api/jobs";
import { formatUsage } from "../api/usage";
import { StoryPlanRecoveryGuidance } from "../screens/StoryPlanRecoveryGuidance";
import { ActiveJobNotice } from "../ui/ActiveJobNotice";

// 취소는 실패가 아니다 (계획서 B3): StructureScreen의 취소 안내와 같은 문구다
const AI_CONSENT_CANCELLED_NOTICE = "전송을 취소했습니다. 필요하면 다시 시도해 주세요.";

const KINDS = ["chapter", "condense"] as const;

export function GeneratePanel({ project, deck, chapterId, onReplace, pollIntervalMs = 1000 }: {
  project: ProjectInfo;
  deck: Deck;
  chapterId: string;
  onReplace: (next: Deck) => void;
  pollIntervalMs?: number;
}) {
  const [instructions, setInstructions] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ChapterResult | null>(null);
  const [job, setJob] = useState<JobView | null>(null);  // 결과를 만든 작업 (후보 처분과 낡음 판정)
  const [earlier, setEarlier] = useState(false);  // 화면을 다시 열어 찾은 지난 후보
  const [error, setError] = useState("");
  const [failure, setFailure] = useState<unknown>(null);
  const [followError, setFollowError] = useState("");
  const [storyStale, setStoryStale] = useState(false);
  const [cancelNotice, setCancelNotice] = useState("");  // AI 전송 취소 안내 (role=alert 아님)
  const slide = deck.slides.find((s) => s.chapter_id === chapterId);
  const chapterIdRef = useRef(chapterId);
  chapterIdRef.current = chapterId;
  const follow = useRef<AbortController | null>(null);

  const show = (view: JobView, fromEarlier: boolean) => {
    setJob(view);
    setEarlier(fromEarlier);
    try {
      setResult(jobResult<ChapterResult>(view));
    } catch (e) {
      showError(e);
    }
  };
  const showError = (e: unknown) => {
    if (e instanceof AiConsentDeclined) setCancelNotice(AI_CONSENT_CANCELLED_NOTICE);
    else if (e instanceof JobCancelled) setCancelNotice("생성이 취소되었습니다.");
    else if (isStaleStoryPlan(e)) setStoryStale(true);
    else { setError(messageOf(e)); setFailure(e); }
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
      if (earlierJob) show(earlierJob, true);
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
  const elsewhere = job?.stale_reasons.includes("deck_changed_elsewhere") ?? false;
  const dismiss = () => {
    if (job) void settle(project.name, job.id, "dismissed");
    setResult(null);
    setJob(null);
    setEarlier(false);
  };

  const applyResult = () => {
    if (!result || result.status !== "ok" || !result.slots) return;
    const slots = result.slots;
    const next: Deck = {
      ...deck,
      slides: deck.slides.some((s) => s.chapter_id === chapterId)
        ? deck.slides.map((s) => (s.chapter_id === chapterId ? { ...s, slots } : s))
        : [...deck.slides, { chapter_id: chapterId, slots, eyebrow: "", subtitle: "" }],  // 공통 슬롯은 생성이 채우지 않는다. 값은 사용자가 속성 패널에서 넣는다 (DA-4)
    };
    onReplace(next);  // 반영 저장은 스냅샷을 남긴다 (결정 1)
    if (job) void settle(project.name, job.id, "applied");
    setResult(null);
    setJob(null);
    setEarlier(false);
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
        <button onClick={regenerate} disabled={busy}>이 장 다시 생성</button>
        <button onClick={condense} disabled={busy || !slide}>이 장 축약</button>
      </div>
      {busy && <p>생성 중입니다. 잠시 기다려 주세요 (최대 5분)...</p>}
      {followError && <p role="status">{followError}</p>}
      {error && <p role="alert">{error}</p>}
      <ActiveJobNotice error={failure} />
      {storyStale && <div role="alert"><StoryPlanRecoveryGuidance
        hasDiagrams={deck.structure.chapters.some(chapter => chapter.template === "diagram")} /></div>}
      {cancelNotice && <p className="notice">{cancelNotice}</p>}
      {result && result.status === "format_error" && (
        <div role="alert">
          <p>AI 응답을 형식에 맞게 읽지 못했습니다. 원문을 확인하고 다시 시도해 주세요.</p>
          <details><summary>AI 응답 원문</summary><pre>{result.raw_text}</pre></details>
        </div>
      )}
      {result && result.status === "ok" && reasons.length > 0 && (
        <div className="generate-result">
          <p>이전 입력 기준 후보입니다({reasonText(reasons)}). 반영하지 않고 현재 입력으로 다시 생성해 주세요.</p>
          <details><summary>후보 보기</summary><pre>{slotsText(result.slots)}</pre></details>
          {(job?.kind !== "condense" || slide) && (
            <button onClick={() => (job?.kind === "condense" ? condense() : void regenerate())}>현재 입력으로 다시 생성</button>
          )}
          <button onClick={dismiss}>버리기</button>
        </div>
      )}
      {result && result.status === "ok" && reasons.length === 0 && (
        <div className="generate-result">
          {earlier && <p>이전에 만든 결과가 있습니다.</p>}
          {elsewhere && <p className="notice">덱의 다른 부분이 바뀌었지만 이 장의 입력은 그대로입니다.</p>}
          <p>새 초안이 준비되었습니다.
            {result.condensed && " 분량에 맞춰 축약했습니다."}
            {result.format_retried && " 형식 재시도 1회를 거쳤습니다."}
          </p>
          {result.warnings.length > 0 && (
            <ul>{result.warnings.map((w, i) => <li key={i}>{w.message}</li>)}</ul>
          )}
          {result.unverified_numbers.length > 0 && (
            <p className="number-warning">
              자료에서 찾지 못한 수치: {result.unverified_numbers.join(", ")}. 반영 전에 확인해 주세요.
            </p>
          )}
          <button onClick={applyResult}>반영</button>
          <button onClick={dismiss}>버리기</button>
        </div>
      )}
      {/* F5 리뷰 반영: usage는 상태와 무관하게 항상 채워지는 필수 필드다(C2/C3 가정 6).
          형식 오류로 끝나도 최소 1회 호출은 있었으므로 상태 분기 밖에서 항상 보인다 */}
      {result && <p className="usage">{formatUsage(result.usage)}</p>}
    </section>
  );
}
