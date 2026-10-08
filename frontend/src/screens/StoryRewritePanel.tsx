import { useEffect, useRef, useState } from "react";
import { AiConsentDeclined, api, ApiError, messageOf, type Deck, type JobView, type StoryRewriteResult, type StoryRepairResult } from "../api/client";
import {
  blockingReasons, JOB_FOLLOW_ERROR, jobResult, JobCancelled, pendingCandidate, reasonText, runJob, runningJob, settle,
  waitJob,
} from "../api/jobs";
import { formatUsage } from "../api/usage";
import { ActiveJobNotice } from "../ui/ActiveJobNotice";

const CANCEL_REQUESTED_NOTICE = "취소를 요청했습니다. AI가 응답을 멈추면 취소됨으로 바뀝니다.";
const REPAIR_CANCELLED_NOTICE = "수정 요청을 취소했습니다. 입력과 기존 저장본은 유지됩니다.";
import { StoryPlanView } from "./StoryPlanView";

const ROLES = { answer: "핵심 답변", context: "배경", evidence: "근거", risk: "위험", action: "다음 행동", cover: "표지", divider: "간지" };

export function StoryRewritePanel({ projectName, deck, disabled, onApplied, onBusyChange, onActiveChange,
  onConflict, onScreenReady, onDirtyChange, pollIntervalMs = 1000 }: {
  projectName: string; deck: Deck; disabled: boolean; onApplied: (deck: Deck) => void;
  onBusyChange?: (busy: boolean) => void; onActiveChange: (active: boolean) => void;
  onConflict?: () => void; onScreenReady?: (flush: () => Promise<boolean>) => void;
  onDirtyChange?: (dirty: boolean) => void;
  pollIntervalMs?: number;
}) {
  const initialQuestion = deck.structure.story_plan!.brief.decision_question;
  const [question, setQuestion] = useState(initialQuestion);
  const [instructions, setInstructions] = useState("");
  const [result, setResult] = useState<StoryRewriteResult | StoryRepairResult | null>(null);
  const [problems, setProblems] = useState("");
  const [calls, setCalls] = useState(2);
  const [rounds, setRounds] = useState(1);
  const [seconds, setSeconds] = useState(60);
  const [budgetConfirmed, setBudgetConfirmed] = useState(false);
  const abort = useRef<AbortController | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [acknowledged, setAcknowledged] = useState(false);
  const [blocked, setBlocked] = useState(false);
  const [failure, setFailure] = useState<unknown>(null);
  const [followError, setFollowError] = useState("");
  const [staleReasons, setStaleReasons] = useState<string[]>([]);  // 이전 입력 기준 후보의 이유 (D2b-5b)
  const [earlier, setEarlier] = useState(false);
  const candidateJob = useRef<string | null>(null);  // 지금 보이는 후보를 만든 작업 (처분)
  const running = useRef<string | null>(null);  // 실행 중인 수리 작업 (실행 중단)
  const [repairJob, setRepairJobState] = useState<string | null>(null);
  const setRepairJob = (id: string | null) => { running.current = id; setRepairJobState(id); };
  const epoch = useRef(0);
  const ownsBusy = useRef(false);
  const current = useRef({ deck, projectName, busy: false, dirty: false });
  const dirty = !!result || question !== initialQuestion || instructions !== "" || problems !== "";
  const candidateReady = !!result && ("submission_approved" in result ? result.status === "reviewed_candidate" : result.status === "ok");
  current.current = { deck, projectName, busy, dirty };

  // 지금 보이는 후보를 버린다. 처분하지 않으면 다음에 열 때 지난 결과로 다시 보인다 (D2b-5b)
  const dropCandidate = () => {
    if (candidateJob.current) void settle(projectName, candidateJob.current, "dismissed");
    candidateJob.current = null;
  };
  const clear = () => {
    epoch.current += 1;
    setResult(null); setQuestion(initialQuestion); setInstructions(""); setProblems(""); setBudgetConfirmed(false); setAcknowledged(false);
    setError(""); setNotice(""); setBlocked(false); setFailure(null); setFollowError(""); setStaleReasons([]); setEarlier(false);
    candidateJob.current = null;
  };
  // 작업의 결과를 화면에 올린다. 관련 입력이 바뀐 후보는 적용 대신 이전 입력 기준 후보로 보인다
  const showJob = (view: JobView, fromEarlier: boolean) => {
    const response = jobResult<StoryRewriteResult | StoryRepairResult>(view);
    candidateJob.current = view.id;
    setResult(response);
    setEarlier(fromEarlier);
    const reasons = blockingReasons(view);
    setStaleReasons(reasons);
    if (reasons.some((r) => r === "deck_changed" || r === "unknown_deck")) onConflict?.();
    if (reasons.length === 0) {
      if ("submission_approved" in response) {
        if (response.status !== "reviewed_candidate") setNotice(response.reason ?? "해결되지 않은 문제가 있습니다. 후보와 기존 저장본을 보존했습니다.");
      } else if (response.status !== "ok" || !response.deck) {
        setError("재작성 응답의 형식을 확인하지 못했습니다. 원문을 확인하고 다시 시도해 주세요.");
      }
    }
  };
  useEffect(() => {
    clear();
    // 진행 중인 재작성이나 수리는 이어서 조회하고, 처분하지 않은 지난 후보는 다시 보인다 (D2b-5b)
    const controller = new AbortController();
    abort.current = controller;
    const id = epoch.current;
    api.listJobs(projectName).then(async (jobs) => {
      if (controller.signal.aborted || id !== epoch.current) return;
      const live = runningJob(jobs, ["rewrite", "repair"]);
      if (live) {
        setRepairJob(live.kind === "repair" ? live.id : null);
        setRunning(true);
        try {
          const final = await waitJob(projectName, live, { intervalMs: pollIntervalMs, signal: controller.signal,
            onError: () => setFollowError(JOB_FOLLOW_ERROR) });
          if (id === epoch.current) { setFollowError(""); showJob(final, false); }
        } catch (e) {
          if (!controller.signal.aborted && id === epoch.current) showError(e);
        } finally {
          if (!controller.signal.aborted) { setRepairJob(null); setRunning(false); }
        }
        return;
      }
      const earlierJob = pendingCandidate(jobs, ["rewrite", "repair"]);
      if (earlierJob) {
        const brief = (earlierJob.params as { brief?: { decision_question?: string } }).brief;
        if (brief?.decision_question) setQuestion(brief.decision_question);
        showJob(earlierJob, true);
      }
    }).catch(() => { /* 지난 후보를 찾지 못해도 새 재작성은 할 수 있다 */ });
    return () => {
      epoch.current += 1;
      controller.abort();  // 조회만 멈춘다. 작업은 취소하지 않는다 (계획서 D2b-5b)
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deck, projectName]); // 저장본이 바뀌면 이전 후보와 늦은 응답은 적용하지 않는다.
  useEffect(() => { onActiveChange(busy || dirty); onDirtyChange?.(dirty); }, [busy, dirty, onActiveChange, onDirtyChange]);
  useEffect(() => {
    onScreenReady?.(async () => {
      if (current.current.busy) return false;
      if (current.current.dirty && !window.confirm("아직 적용하지 않은 재작성 입력과 후보를 버리고 계속할까요?")) return false;
      return true;
    });
  });

  const change = (setter: (value: string) => void, value: string) => {
    epoch.current += 1; setter(value); setResult(null); setAcknowledged(false); setBlocked(false);
    dropCandidate(); setStaleReasons([]); setEarlier(false);
    setBudgetConfirmed(false);
    setError(""); setNotice("");
  };
  const setRunning = (value: boolean) => {
    ownsBusy.current = value;
    current.current.busy = value;
    setBusy(value); onBusyChange?.(value);
  };
  const showError = (e: unknown) => {
    if (e instanceof AiConsentDeclined) { setNotice("재작성을 취소했습니다. 기존 계획은 유지됩니다."); return; }
    if (e instanceof JobCancelled) { setNotice(REPAIR_CANCELLED_NOTICE); return; }
    setError(messageOf(e));
    setFailure(e);
    if (e instanceof ApiError && (e.status === 409 || e.status === 412)) setBlocked(true);
    if (e instanceof ApiError && e.status === 412) onConflict?.();
  };
  const preview = async () => {
    if (ownsBusy.current || current.current.busy || disabled || !question.trim()) return;
    dropCandidate();
    const id = ++epoch.current;
    const follow = abort.current;
    setRunning(true); setError(""); setNotice(""); setResult(null); setBlocked(false); setAcknowledged(false);
    setFailure(null); setFollowError(""); setStaleReasons([]); setEarlier(false);
    try {
      const { job } = await runJob<StoryRewriteResult>(projectName, "rewrite", {
        brief: { ...deck.structure.story_plan!.brief, decision_question: question.trim(),
          audience: deck.meta.audience, report_type: deck.meta.report_type }, instructions,
      }, { intervalMs: pollIntervalMs, signal: follow?.signal, onError: () => setFollowError(JOB_FOLLOW_ERROR) });
      if (id !== epoch.current || current.current.deck !== deck || current.current.projectName !== projectName) return;
      setFollowError("");
      showJob(job, false);
    } catch (e) { if (id === epoch.current && !follow?.signal.aborted) showError(e); }
    finally { setRunning(false); }
  };
  const repair = async () => {
    if (ownsBusy.current || current.current.busy || disabled || !question.trim() || !problems.trim() || !budgetConfirmed) return;
    const findings = problems.split("\n").map(s => s.trim()).filter(Boolean);
    if (findings.length > 30 || findings.some(s => s.length > 1000)) { setError("문제는 30개 이내, 항목마다 1,000자 이내로 입력해 주세요."); return; }
    dropCandidate();
    const id = ++epoch.current;
    const follow = abort.current;
    setRunning(true); setError(""); setNotice(""); setResult(null); setBlocked(false); setAcknowledged(false);
    setFailure(null); setFollowError(""); setStaleReasons([]); setEarlier(false);
    try {
      // 실행 중단은 작업 취소를 요청하고 조회는 계속한다. 작업이 취소로 끝난 뒤에만 취소 완료를 알린다 (D2b-5b)
      const { job } = await runJob<StoryRepairResult>(projectName, "repair", {
        brief: { ...deck.structure.story_plan!.brief, decision_question: question.trim(),
          audience: deck.meta.audience, report_type: deck.meta.report_type }, instructions,
        findings: findings.map(message => ({code: "user_review", target: "report", message})),
        max_calls: calls, max_rounds: rounds, max_seconds: seconds,
      }, { intervalMs: pollIntervalMs, signal: follow?.signal, onStarted: (view) => setRepairJob(view.id),
        onError: () => setFollowError(JOB_FOLLOW_ERROR) });
      if (id !== epoch.current || current.current.deck !== deck || current.current.projectName !== projectName) return;
      setFollowError("");
      showJob(job, false);
    } catch (e) {
      if (id === epoch.current && !follow?.signal.aborted) showError(e);
    } finally { setRunning(false); setRepairJob(null); }
  };
  const stopRepair = async () => {
    if (!running.current) return;
    try {
      await api.cancelJob(projectName, running.current);
      setNotice(CANCEL_REQUESTED_NOTICE);
    } catch (e) { setError(messageOf(e)); }
  };
  const apply = async () => {
    if (ownsBusy.current || current.current.busy || blocked || staleReasons.length > 0 || !result?.deck || !candidateReady
      || !acknowledged || disabled) return;
    const id = ++epoch.current;
    setRunning(true); setError("");
    try {
      const saved = await api.applyStoryRewrite(projectName, result);
      if (candidateJob.current) void settle(projectName, candidateJob.current, "applied");
      candidateJob.current = null;
      if (id !== epoch.current || current.current.deck !== deck || current.current.projectName !== projectName) return;
      setResult(null); setInstructions(""); setQuestion(saved.structure.story_plan!.brief.decision_question);
      onApplied(saved);
    } catch (e) { if (id === epoch.current) showError(e); }
    finally { setRunning(false); }
  };
  return <section className="story-rewrite" aria-label="보고 계획 재작성">
    <h2>기존 편집을 보존하며 계획 재작성</h2>
    <p>장 수와 제목, 본문과 도식은 유지하고 현재 자료로 보고 질문, 장 순서와 근거 연결을 다시 계획합니다. 도식이 의존하는 원자료가 바뀌었다면 재작성을 중단합니다.</p>
    {disabled && <p className="notice">장 구성에 미승인 변경이 있거나 다른 작업이 진행 중입니다. 먼저 승인하거나 프로젝트를 다시 열어 주세요.</p>}
    <label>재작성 보고 질문<input aria-label="재작성 보고 질문" value={question} disabled={busy || disabled}
      onChange={e => change(setQuestion, e.target.value)} /></label>
    <label>재작성 지시사항<textarea aria-label="재작성 지시사항" value={instructions} disabled={busy || disabled} rows={3}
      onChange={e => change(setInstructions, e.target.value)} /></label>
    <div className="actions">
      <button disabled={busy || disabled || !question.trim()} onClick={preview}>재작성 미리보기</button>
      {dirty && <button disabled={busy} onClick={() => { if (window.confirm("재작성 입력과 후보를 버릴까요?")) { dropCandidate(); clear(); } }}>재작성 취소</button>}
      {busy && <span role="status">처리 중입니다...</span>}
      {busy && repairJob && <button onClick={() => void stopRepair()}>실행 중단</button>}
    </div>
    <details><summary>문제 목록으로 제한된 수정·재검수</summary>
      <p>현재 선택한 AI에 원문 자료, 기존 초안과 문제 목록을 보냅니다. 실패·형식 재시도와 별도 AI 재검수까지 아래 총 호출에 포함됩니다. 본문과 도식은 유지하며 제출 승인은 부여하지 않습니다.</p>
      <label>확인할 문제 (한 줄에 하나)<textarea aria-label="수정 문제 목록" value={problems} disabled={busy || disabled}
        onChange={e => { change(setProblems, e.target.value); setBudgetConfirmed(false); }} /></label>
      <label>총 호출 상한<input aria-label="수정 총 호출 상한" type="number" min={2} max={8} value={calls} disabled={busy}
        onChange={e => {setCalls(Number(e.target.value)); setBudgetConfirmed(false);}} /></label>
      <label>수정 회차 상한<input aria-label="수정 회차 상한" type="number" min={1} max={3} value={rounds} disabled={busy}
        onChange={e => {setRounds(Number(e.target.value)); setBudgetConfirmed(false);}} /></label>
      <label>시간 상한 (초)<input aria-label="수정 시간 상한" type="number" min={10} max={300} value={seconds} disabled={busy}
        onChange={e => {setSeconds(Number(e.target.value)); setBudgetConfirmed(false);}} /></label>
      <label><input type="checkbox" checked={budgetConfirmed} disabled={busy || disabled}
        onChange={e => setBudgetConfirmed(e.target.checked)} />문제 목록과 입력 범위, 총 {calls}회·{rounds}회차·{seconds}초 상한을 확인했습니다</label>
      <button disabled={busy || disabled || !budgetConfirmed || !problems.trim() || !question.trim() ||
        !Number.isInteger(calls) || calls<2 || calls>8 || !Number.isInteger(rounds) || rounds<1 || rounds>3 ||
        !Number.isInteger(seconds) || seconds<10 || seconds>300}
        onClick={() => void repair()}>제한된 수정 미리보기</button>
    </details>
    {followError && <p role="status">{followError}</p>}
    {error && <p role="alert">{error}</p>}{notice && <p className="notice">{notice}</p>}
    <ActiveJobNotice error={failure} />
    {result && <p className="usage">{formatUsage(result.usage)}</p>}
    {result && "raw_text" in result && result.raw_text && result.status !== "ok" && <details><summary>재작성 응답 원문</summary><pre>{result.raw_text}</pre></details>}
    {result && "submission_approved" in result && <div aria-label="제한된 수정 결과">
      <p>{result.notice}</p><p>사용 호출 {result.calls}회, 재검수 {result.review_calls}회, 수정 {result.rounds}회차</p>
      {result.findings.map((f,i) => <p key={i}>{f.target}: {f.message}</p>)}
      {result.review_notes.map((note,i) => <p key={i}>{note}</p>)}
    </div>}
    {result?.deck && <section aria-label="재작성 후보">
      <h3>아직 적용하지 않은 계획</h3>
      {earlier && <p>이전에 만든 결과가 있습니다.</p>}
      <p className="notice">기존 본문과 도식은 다시 생성하지 않습니다. 새 계획과 본문의 주장, 수치와 흐름이 맞는지 모두 재검토해야 합니다.</p>
      {"unverified_numbers" in result && !!result.unverified_numbers?.length && <p className="number-warning">자료에서 찾지 못한 수치: {result.unverified_numbers.join(", ")}</p>}
      <h4>새 장 순서와 역할</h4>
      <ol>{result.deck.structure.chapters.map(ch => <li key={ch.id}>{ch.topic} / {ROLES[result.deck!.structure.story_plan!.chapters.find(c => c.chapter_id === ch.id)!.role]}</li>)}</ol>
      <StoryPlanView plan={result.deck.structure.story_plan!} />
      <label><input type="checkbox" checked={acknowledged} disabled={busy || blocked}
        onChange={e => setAcknowledged(e.target.checked)} />본문 재검토가 필요함을 확인했습니다</label>
      {staleReasons.length > 0 ? <>
        <p className="notice">이전 입력 기준 후보입니다({reasonText(staleReasons)}). 적용하지 않고 현재 입력으로 다시 만들어 주세요.</p>
        <button disabled={busy || disabled || !question.trim()} onClick={() => void preview()}>현재 입력으로 다시 생성</button>
      </> : <button disabled={busy || disabled || blocked || !acknowledged || !candidateReady} onClick={apply}>이 계획 적용</button>}
    </section>}
  </section>;
}
