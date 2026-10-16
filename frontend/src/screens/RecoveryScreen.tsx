import { useEffect, useRef, useState } from "react";
import { api, ApiError, messageOf, onProjectEvent, onRemoteProjectEvent, TERMINAL_JOB_STATES, type Deck, type DraftInfo, type DraftSummary, type JobView, type ProjectInfo, type Slots, type SnapshotInfo } from "../api/client";
import { CandidateCompareDialog, STALE_BASE, type CompareSelection } from "../editor/CandidateCompareDialog";
import { reopenRefusal } from "../editor/diagramReopen";
import { blockingReasons, reasonText, slotsText } from "../api/jobs";
import { StatusIndicator } from "../ui/StatusIndicator";

import { formatSavedAt } from "../api/time";
import { Button } from "../ui/Button";
import { JOB_STAGE } from "./stageStatus";

// 사유와 출처는 이후 버전이 값을 늘릴 수 있어 모르는 값도 그대로 보인다 (D2a-2 리뷰 R5)
function describeDraft(d: DraftInfo): string {
  if (d.reason === "conflict" && d.source === "structure_approval") {
    return "승인하려던 장 구성(내용 생성 전) (구조안 승인)";  // 리뷰 R12: 슬라이드가 없을 수 있다
  }
  const reason = ({ conflict: "다른 곳의 저장과 충돌한 편집", generation_unsaved: "저장하지 못한 생성 결과" } as
    Record<string, string>)[d.reason] ?? `알 수 없는 사유(${d.reason})`;
  const source = ({ editor: "편집 화면", structure_approval: "구조안 승인", purpose: "보고 목적" } as Record<string, string>)[d.source]
    ?? d.source;
  return `${reason} (${source})`;
}

// AI 결과 후보 (D2b-5c, 계획서 5.8). 작업 하나 또는 장 생성 묶음의 장 하나가 한 항목이다
type Candidate = {
  key: string; job: JobView; chapterId: string | null; result: Record<string, unknown>; reasons: string[];
  status: string; state: string;  // state: 묶음이면 그 장의 상태, 아니면 작업의 상태
};
const KIND_LABELS: Record<string, string> = {
  structure: "구조안", chapter: "장 다시 생성", condense: "장 축약", diagram: "도식", rewrite: "보고 계획 재작성",
  repair: "제한된 수정", chapters: "장 내용 생성",
};
// 덱 전체 후보는 다시 생성 화면으로 옮기지 않고 보기와 버리기만 한다 (계획서 D2b-5c, D2b-β 리뷰 R3)
const WHOLE_DECK = new Set(["rewrite", "repair"]);

// 장은 내부 ID가 아니라 순서와 제목으로 보인다 (C24). 덱이 없는 복구 대상 프로젝트와 덱에서 사라진 장은
// 순서와 제목을 알 수 없어 ID로 보인다
function chapterLabel(deck: Deck | undefined, id: string): string {
  const index = deck?.structure.chapters.findIndex((c) => c.id === id) ?? -1;
  return index >= 0 ? `${index + 1}장 ${deck!.structure.chapters[index].topic}` : `장 ${id}`;
}
// 다시 만들 단계. 구조안과 장 생성 묶음의 후보는 구성 단계, 그 밖의 장 후보는 편집 단계에서 다시 만든다
type OpenStage = "structure" | "editor";
const STAGE_NAMES: Record<OpenStage, string> = { structure: "구성", editor: "편집" };

function candidatesOf(jobs: JobView[]): Candidate[] {
  const list: Candidate[] = [];
  for (const job of jobs) {
    if (job.kind === "chapters") {
      for (const c of job.chapters) {
        if ((c.candidate_status === "held" || c.candidate_status === "stale") && c.result) {
          list.push({ key: `${job.id}:${c.chapter_id}`, job, chapterId: c.chapter_id, result: c.result,
            reasons: [], status: c.candidate_status, state: c.state });
        }
      }
    } else if ((job.candidate_status === "held" || job.candidate_status === "stale") && job.result) {
      list.push({ key: job.id, job, chapterId: job.target, result: job.result, reasons: blockingReasons(job),
        status: job.candidate_status, state: job.state });
    }
  }
  return list;
}

// 결과 없이 끝난 지난 작업 (D2b-5c 리뷰 R2). 장 생성 묶음은 구조안 화면이 장마다 보인다
const ENDED_WITHOUT_RESULT = new Set(["cancelled", "interrupted", "remote_completion_unknown"]);
function endedWithoutResult(jobs: JobView[]): JobView[] {
  return jobs.filter((j) => j.kind !== "chapters" && ENDED_WITHOUT_RESULT.has(j.state) && !j.result);
}

// 후보가 지금 어떤 상태인지 한 문장으로 알린다 (D2b-5c 리뷰 R7, R8, R9)
function candidateStatus(c: Candidate): string {
  if (c.job.kind === "chapters") {
    if (!TERMINAL_JOB_STATES.has(c.state)) return "아직 적용 여부를 확인하지 못한 결과입니다. 앱을 다시 시작하면 정리합니다.";
    if (c.state === "cancelled") return "취소한 뒤 도착한 결과입니다. 덱에 넣지 않았습니다.";
    return c.status === "stale" ? "만드는 동안 다른 저장이 있어 덱에 넣지 못한 결과입니다."
      : "덱에 넣지 못한 결과입니다.";
  }
  const cancelled = c.state === "cancelled" ? "취소한 뒤 도착한 결과입니다. " : "";
  const basis = `기준 저장본 ${shortEtag(c.job.base_etag)}, 지금 저장본 ${shortEtag(c.job.current_etag)}.`;
  const unreadable = c.job.current_etag === null || c.reasons.some((r) => r.startsWith("unknown_"));
  // 장 재생성과 축약은 다른 장만 바뀐 경우 반영을 막지 않는다. 저장본 값이 달라도 그 사실을 밝힌다 (리뷰 R19). 장 해시는
  // 슬라이드 문구를 담지 않아 그 장의 문구가 바뀌었을 수 있으므로, 두 종류는 영향을 단정하지 않고 비교 화면에 맡긴다
  // (C1 W1 리뷰 W1R-08, C2 계획 4.3 (22))
  const elsewhere = c.job.stale_reasons.includes("deck_changed_elsewhere");
  const chapterKind = c.job.kind === "chapter" || c.job.kind === "condense";
  return `${cancelled}${basis} ${unreadable ? "저장본이나 자료를 읽지 못해 지금 입력과 비교할 수 없습니다."
    : c.reasons.length > 0 ? `이전 입력 기준 후보입니다(${reasonText(c.reasons)}).`
      : elsewhere ? (chapterKind ? "덱의 다른 부분이 바뀌었습니다. 이 장의 문구가 바뀌었는지는 비교 화면에서 확인합니다."
        : "덱의 다른 부분만 바뀌어 이 장에는 영향이 없습니다.") : "지금 입력과 같은 기준입니다."}`;
}

function candidateText(c: Candidate): string {
  const r = c.result as { slots?: unknown; diagram?: { nodes?: { content: string }[] } | null; reason?: string | null;
    structure?: { chapters: { topic: string }[] } | null; deck?: { structure: { chapters: { topic: string }[] } } | null };
  if (r.slots) return slotsText(r.slots);
  if (r.diagram?.nodes) return r.diagram.nodes.map((n) => n.content).join("\n");
  const chapters = r.structure?.chapters ?? r.deck?.structure.chapters;
  if (chapters) return chapters.map((ch, i) => `${i + 1}. ${ch.topic}`).join("\n");
  return r.reason ? `멈춘 이유: ${r.reason}` : "보일 내용이 없습니다.";  // 중단된 수리 (리뷰 R17)
}

const shortEtag = (etag: string | null) => (etag ? etag.replace(/"/g, "").slice(0, 8) : "알 수 없음");

// 장 후보: 복구 화면에서 비교하고 반영한다 (C1 계획 4.2). 적용 라우트가 받는 행만 버튼을 둔다. 단독 행은 성공으로 끝나고
// 관련 입력 해시가 있어야 하고, 묶음 하위 장은 종결되고 부모에 장별 해시 표지(b1:)가 있어야 한다(계획 리뷰 PR-06)
const CHAPTER_KINDS = new Set(["chapter", "condense", "chapters"]);
function applicable(c: Candidate): boolean {
  if (c.job.kind === "chapters") return TERMINAL_JOB_STATES.has(c.state) && !!c.job.relevance_hash?.startsWith("b1:");
  return c.job.state === "succeeded" && !!c.job.relevance_hash;
}
// 새 도식 후보는 요청의 제목으로 부른다. 장 ID는 같은 ID의 후보가 여럿이거나 그 ID를 다른 도식이 쓰게 되면 행을 구별하지
// 못한다(W2 리뷰 W2R-07)
const newDiagram = (c: Candidate) => c.job.kind === "diagram" && (c.job.params as { mode?: string }).mode !== "replace";
function rowTarget(c: Candidate, deck: Deck | undefined): string {
  if (newDiagram(c)) return ` (새 도식: ${(c.job.params as { topic?: string }).topic ?? "제목 없음"})`;
  return c.chapterId ? ` (${chapterLabel(deck, c.chapterId)})` : "";
}
const hasSlide = (deck: Deck, chapterId: string | null) => !!chapterId && deck.slides.some((s) => s.chapter_id === chapterId);
// 다시 만들 단계. 장 후보는 그 장에 슬라이드가 있으면 편집 단계, 없으면 구성 단계다(계획 리뷰 PR-11). 그 밖은 단계 상태의 표
function openStage(c: Candidate, deck: Deck | undefined): OpenStage {
  if (CHAPTER_KINDS.has(c.job.kind) && deck) return hasSlide(deck, c.chapterId) ? "editor" : "structure";
  return JOB_STAGE[c.job.kind] === "structure" ? "structure" : "editor";
}
const SETTLED_ELSEWHERE = "다른 곳에서 이미 처리한 후보입니다. 목록을 다시 읽었습니다.";
const NOT_APPLICABLE = "이전 버전에서 만들었거나 끝까지 만들지 못한 결과라 반영 여부를 판정할 수 없습니다. 보기와 버리기만 할 수 있습니다.";
// 5xx는 저장 전 실패(덱 쓰기 실패, 읽기 실패)와 저장 뒤 원장 커밋 실패를 모두 덮으므로 어느 쪽인지 단정하지 않는다(W1 리뷰 W1R-12)
const MAYBE_APPLIED = "반영했는지 확인하지 못했습니다. 다시 반영해 주세요. 이미 반영됐으면 처리만 정리됩니다.";
// 비교 화면이 막힌 후보에 보일 다시 생성 안내. 복구 화면은 생성을 시작하지 않으므로 "현재 입력으로 다시 생성" 버튼 대신 갈 길을
// 알린다. 이동은 비교 화면을 닫은 뒤 행의 버튼이 맡는다(W1 리뷰 W1R-04)
function regenerateHint(c: Candidate, stage: OpenStage): string {
  if (stage === "structure") return "이 화면을 닫고 '구성 단계로 옮겨 다시 생성'을 누른 뒤 '승인하고 내용 생성'으로 내용이 없는 장을 다시 만들어 주세요.";
  const action = c.job.kind === "condense" ? "이 장 축약" : "이 장 다시 생성";
  return `이 화면을 닫고 '편집 단계로 옮겨 다시 생성'을 누른 뒤 '${action}'으로 현재 입력 기준 후보를 만들어 주세요.`;
}

// 반영 응답이 5xx였던 후보(프로젝트별 후보 열쇠). 모듈 수준이라 배너의 "서버 내용 다시 읽기"로 복구 화면이 다시 마운트돼도
// 같은 탭 안에서는 남는다. 탭을 새로 고치면 사라지고, 그때는 같은 후보를 다시 반영하면 서버가 정리한다 (C1 W1 리뷰 W1R-06,
// C2 계획 4.3 (21))
const maybeAppliedByProject = new Map<string, Set<string>>();

// 시험용: 시험 사이에 비운다(ETag 캐시의 resetEtags와 같은 방식, C2 계획 리뷰 PR-25)
export function resetMaybeApplied(): void {
  maybeAppliedByProject.clear();
}

// 다른 탭이나 이 탭의 저장과 작업 알림을 합쳐 목록을 다시 읽는 간격. 진행 작업 조회 간격(ProjectView jobPollMs)과 같다
const RELOAD_MS = 1000;

function JobCandidates({ project, deck, onOpen, onConflict, onDeckSaved, onApplyUnconfirmed, reloadMs = RELOAD_MS }: {
  project: ProjectInfo; deck?: Deck; onOpen?: (stage: OpenStage, chapterId?: string, diagramJobId?: string) => void;
  onConflict?: () => void; onDeckSaved?: (deck: Deck) => void; onApplyUnconfirmed?: () => void; reloadMs?: number;
}) {
  const [items, setItems] = useState<Candidate[] | null>(null);
  const [ended, setEnded] = useState<JobView[]>([]);
  const [error, setError] = useState("");
  // 안내 종류: batch_active는 묶음이 끝나면 지운다. 반영 성공과 다른 곳의 처분 안내는 지우지 않는다 (C1 W1 리뷰 W1R-11)
  const [notice, setNoticeState] = useState<{ text: string; kind?: "batch_active" }>({ text: "" });
  const setNotice = (text: string, kind?: "batch_active") => setNoticeState({ text, kind });
  const [comparing, setComparing] = useState<Candidate | null>(null);
  // 반영 응답이 5xx였던 후보. 저장됐을 수 있어 그 행에 알린다(계획 리뷰 PR-17)
  const [maybeApplied, setMaybeAppliedState] = useState<Set<string>>(() => new Set(maybeAppliedByProject.get(project.name)));
  const setMaybeApplied = (update: (keys: Set<string>) => Set<string>) => setMaybeAppliedState((keys) => {
    const next = update(keys);
    if (next.size) maybeAppliedByProject.set(project.name, next); else maybeAppliedByProject.delete(project.name);
    return next;
  });
  const live = useRef(true);
  useEffect(() => { live.current = true; return () => { live.current = false; }; }, []);
  const loadSerial = useRef(0);
  const heading = useRef<HTMLHeadingElement>(null);
  // 읽기마다 번호를 매겨 가장 나중에 시작한 읽기의 응답만 받는다. 알림으로 시작한 읽기와 반영 뒤의 읽기가 겹치면 먼저
  // 시작한 응답이 늦게 와 사라진 행을 되살릴 수 있다 (C2 계획 리뷰 PR-13)
  const load = () => {
    const serial = ++loadSerial.current;
    return api.listJobs(project.name)
      .then((jobs) => {
        if (!live.current || serial !== loadSerial.current) return;
        const next = candidatesOf(jobs);
        setItems(next); setEnded(endedWithoutResult(jobs)); setError("");
        // 목록에서 사라진 후보의 "확인하지 못함" 표시는 지운다(반영으로 정리됐거나 다른 곳에서 처분)
        const present = new Set(next.map((c) => c.key));
        setMaybeApplied((keys) => [...keys].every((k) => present.has(k)) ? keys : new Set([...keys].filter((k) => present.has(k))));
      })
      .catch((e) => { if (live.current && serial === loadSerial.current) setError(`AI 결과 후보를 읽지 못했습니다. ${messageOf(e)}`); });
  };
  // 반영 뒤 처리. 목록을 먼저 다시 읽고 비교 화면을 닫는다. 반영으로 행이 사라졌으면 초점이 제목으로 간다(계획 리뷰 PR-16)
  const finish = async (message: string) => {
    setNotice(message);
    await load();
    setComparing(null);
  };
  const applyCompare = async (c: Candidate, selection: CompareSelection, baseEtag: string) => {
    try {
      const saved = await api.applyCandidate(project.name, c.job.id,
        { ...(c.job.kind === "chapters" ? { chapter_id: c.chapterId! } : {}), ...selection }, baseEtag);
      onDeckSaved?.(saved);
      setMaybeApplied((keys) => { const next = new Set(keys); next.delete(c.key); return next; });
      // 반영 성공을 알린다. 행이 사라지고 초점이 제목으로 가므로 화면 낭독기 사용자에게 결과를 들려준다(W1 리뷰 W1R-14)
      await finish(`${chapterLabel(saved, c.chapterId ?? "")}에 반영했습니다.`);
    } catch (e) {
      // 412는 부모의 충돌 배너가 같은 문장을 보이므로 복구 화면 안내는 비운다(W1 리뷰 W1R-10)
      if (e instanceof ApiError && e.status === 412) { onConflict?.(); await finish(""); }
      else if (e instanceof ApiError && e.status >= 500) {
        // 덱 저장 뒤 원장 커밋이 실패했을 수 있다. 같은 후보를 다시 반영하면 서버가 처분만 정리한다(D3c 4.8)
        onApplyUnconfirmed?.();
        setMaybeApplied((keys) => new Set(keys).add(c.key));
        await finish("");
      } else if (e instanceof ApiError && e.code === "candidate_settled") await finish(SETTLED_ELSEWHERE);
      else if (e instanceof ApiError && e.code === "batch_active") { await finish(""); setNotice(messageOf(e), "batch_active"); }
      else await finish(messageOf(e));
    }
  };
  useEffect(() => { void load(); }, [project.name]);  // eslint-disable-line react-hooks/exhaustive-deps
  // 열어 둔 동안 도착한 후보와 다른 탭의 처분을 보인다. 작업 시작과 끝, 저장 알림을 듣고, 자동 저장마다 읽지 않도록 마지막
  // 알림 뒤 한 번으로 합친다. 비교 화면이 열려 있어도 목록만 다시 읽고 비교 대상은 바꾸지 않는다 (C1 계획 리뷰 PR-08,
  // C2 계획 4.3 (20))
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    const bump = (event: { project: string; kind: string }) => {
      if (event.project !== project.name) return;
      if (event.kind === "job_ended") setNoticeState((n) => (n.kind === "batch_active" ? { text: "" } : n));
      clearTimeout(timer);
      timer = setTimeout(() => void load(), reloadMs);
    };
    const offLocal = onProjectEvent(bump);
    const offRemote = onRemoteProjectEvent(bump);
    return () => { offLocal(); offRemote(); clearTimeout(timer); };
  }, [project.name, reloadMs]);  // eslint-disable-line react-hooks/exhaustive-deps
  const dismiss = async (c: Candidate) => {
    try {
      if (c.job.kind === "chapters") await api.dismissChapterCandidate(project.name, c.job.id, c.chapterId!);
      else await api.settleCandidate(project.name, c.job.id, "dismissed");
      await load();
    } catch (e) {
      // 다른 화면이 먼저 처분했으면 목록만 다시 읽는다 (리뷰 R11)
      if (e instanceof ApiError && e.status === 409) await load();
      else setError(messageOf(e));
    }
  };
  return (
    <section className="job-candidates">
      <h3 ref={heading} tabIndex={-1}>AI 결과 후보</h3>
      <p>AI가 만들었지만 아직 반영하거나 버리지 않은 결과입니다. 장 후보는 여기서 비교하고 반영할 수 있습니다.
        도식 후보는 도식 작성 창에서 엽니다. 구조안과 덱 전체 후보는 보기와 버리기만 합니다.</p>
      {error && <p role="alert">{error}</p>}
      {notice.text && <p role="status">{notice.text}</p>}
      {items === null ? (error ? null : <p>불러오는 중...</p>) : items.length === 0 ? (
        <p>남아 있는 AI 결과 후보가 없습니다.</p>
      ) : (
        <ul>
          {items.map((c) => (
            <li key={c.key}>
              <p>{KIND_LABELS[c.job.kind] ?? c.job.kind}{rowTarget(c, deck)},{" "}
                만든 시각 {formatSavedAt(c.job.created_at)}</p>
              <p>{candidateStatus(c)}</p>
              {maybeApplied.has(c.key) && <p className="notice">{MAYBE_APPLIED}</p>}
              <details><summary>보기</summary><pre>{candidateText(c)}</pre></details>
              {/* 덱을 읽지 못하는 프로젝트(needs_recovery)에서는 비교할 지금 덱이 없다 (계획 리뷰 PR-07) */}
              {deck && CHAPTER_KINDS.has(c.job.kind) && TERMINAL_JOB_STATES.has(c.state) && (applicable(c)
                ? <><Button onClick={() => setComparing(c)}>비교하고 반영</Button>{" "}</>
                : <p className="hint">{NOT_APPLICABLE}</p>)}
              {/* 도식 후보는 편집 단계의 작성 창에서 다시 연다 (C1 계획 W2-b). 열 수 없으면 이유를 보인다 */}
              {deck && onOpen && c.job.kind === "diagram" && TERMINAL_JOB_STATES.has(c.state) && (() => {
                const refusal = reopenRefusal(c.job);
                return refusal === null
                  ? <><Button onClick={() => onOpen("editor", newDiagram(c) ? undefined : c.chapterId ?? undefined, c.job.id)}>도식 작성 창에서 열기</Button>{" "}</>
                  : <p className="hint">{refusal ? `${refusal} ` : ""}작성 창에서 열 수 없습니다. 현재 입력으로 다시 생성해 주세요.</p>;
              })()}
              {/* 덱을 읽지 못하는 프로젝트에서는 옮길 화면이 없다 (리뷰 R10) */}
              {!WHOLE_DECK.has(c.job.kind) && onOpen && (() => {
                const target = newDiagram(c) ? undefined : c.chapterId ?? undefined;  // 새 도식의 장 ID는 다른 도식이 쓸 수 있다
                // 장 후보는 그 장의 슬라이드 유무로, 그 밖은 단계 상태와 같은 표로 정한다 (D3a-3 리뷰 R4, 계획 리뷰 PR-11)
                const stage = openStage(c, deck);
                return <><button onClick={() => onOpen(stage, target)}>
                  {STAGE_NAMES[stage]} 단계로 옮겨 다시 생성</button>{" "}
                  {/* 이전 묶음의 빈 장에는 장별 다시 생성 버튼이 없으므로 두 경우를 덮는 버튼을 가리킨다(W1 리뷰 W1R-03, W1R-13) */}
                  {stage === "structure" && CHAPTER_KINDS.has(c.job.kind) && <p className="hint">
                    구성 단계의 &apos;승인하고 내용 생성&apos;으로 내용이 없는 장을 다시 만듭니다.</p>}</>;
              })()}
              {/* 끝나지 않은 장은 다음 시작의 정리가 결과를 덱에 넣을 수 있어 버리지 않는다 (리뷰 R6) */}
              {TERMINAL_JOB_STATES.has(c.state) && <Button variant="danger" onClick={() => void dismiss(c)}>버리기</Button>}
            </li>
          ))}
        </ul>
      )}
      {ended.length > 0 && <>
        <h4>결과 없이 끝난 AI 작업</h4>
        <p>앱을 닫거나 취소해 결과를 받지 못한 작업입니다. 완료 여부를 모르는 작업을 다시 생성하면 AI 사용량이 한 번 더
          기록될 수 있습니다.</p>
        <ul>
          {ended.map((j) => (
            <li key={j.id}>
              {j.state === "remote_completion_unknown" ? <StatusIndicator kind="completion_unknown" />
                : <span>{j.state === "cancelled" ? "취소됨" : "중단됨"}</span>}{" "}
              {KIND_LABELS[j.kind] ?? j.kind}{j.target ? ` (${chapterLabel(deck, j.target)})` : ""}, 만든 시각 {formatSavedAt(j.created_at)}
            </li>
          ))}
        </ul>
      </>}
      {comparing && deck && (
        <CandidateCompareDialog projectName={project.name} jobId={comparing.job.id}
          chapterId={comparing.job.kind === "chapters" ? comparing.chapterId! : undefined}
          title={chapterLabel(deck, comparing.chapterId!)} candidateSlots={(comparing.result as { slots: Slots }).slots}
          onApply={(selection, baseEtag) => applyCompare(comparing, selection, baseEtag)}
          regenerateHint={regenerateHint(comparing, openStage(comparing, deck))}
          onStaleBase={() => { setComparing(null); onConflict?.(); setNotice(STALE_BASE); }}
          onUnavailable={(e) => void finish(e.code === "candidate_settled" ? SETTLED_ELSEWHERE : e.message)}
          onClose={() => setComparing(null)} fallbackFocus={heading} />
      )}
    </section>
  );
}

// 보존본 복원 전 차이 요약의 문장 (D3c-6, E7). 바뀌는 것만 줄마다 적는다
export function draftSummaryText(summary: DraftSummary): string {
  if (!summary.readable) return "이 보존본은 지금 형식으로 읽을 수 없어 차이를 요약하지 못했습니다.";
  // 저장본을 읽지 못하면 복원은 보존본 전체를 쓴다(보고 목적 보존본도). 모든 장이 "생기는 장"이 되므로 목록 대신 그 사실을 알린다(리뷰 G10)
  if (!summary.current_readable) return "저장본을 읽지 못해 차이를 비교하지 못했습니다. 복원하면 보존본 전체로 저장본을 바꿉니다.";
  if (summary.purpose_only) {
    return summary.report_info_changed ? "보고 정보가 저장본과 다릅니다. 복원하면 보고 정보만 바뀝니다."
      : "보고 정보가 저장본과 같습니다. 복원해도 바뀌는 것이 없습니다.";
  }
  const names = (items: { label: string }[]) => items.map((c) => c.label).join(", ");
  const lines = [
    summary.changed_chapters.length > 0 && `내용이 바뀌는 장: ${names(summary.changed_chapters)}`,
    summary.added_chapters.length > 0 && `생기는 장: ${names(summary.added_chapters)}`,
    summary.removed_chapters.length > 0 && `사라지는 장: ${names(summary.removed_chapters)}`,
    summary.direct_edit_chapters.length > 0 && `위치와 서식 수정이 바뀌는 장: ${names(summary.direct_edit_chapters)}`,
    summary.report_info_changed && "보고 정보가 다릅니다.",
    summary.order_changed && "장 순서가 다릅니다.",
    summary.story_plan_changed && "구성 계획이 다릅니다.",
    summary.design_changed && "디자인 값이 다릅니다.",  // 복원은 덱 전체를 쓰므로 알린다(리뷰 G4)
    summary.review_changed && "문서 검토 기록이 다릅니다.",
    // 사라지는 장만 지금 저장본의 번호다. 한 창 안에서 같은 장이 다른 번호로 불릴 수 있어 기준을 밝힌다(리뷰 G16)
    summary.removed_chapters.length > 0 && (summary.changed_chapters.length > 0 || summary.added_chapters.length > 0
      || summary.direct_edit_chapters.length > 0) && "장 번호는 복원 뒤 기준이고, 사라지는 장만 지금 저장본 기준입니다.",
  ].filter(Boolean);
  return lines.length > 0 ? `저장본과 다른 점:\n${lines.join("\n")}` : "저장본과 다른 점이 없습니다.";
}

export function RecoveryScreen({ project, deck, onBack, onConflict, onOpen, onDeckSaved, onApplyUnconfirmed, restoreLockedReason }: {
  project: ProjectInfo;
  // 복원을 잠그는 이유 (D3a-5 리뷰 R1, 계획 4.4: 장 생성 묶음 중). 복구 화면이 열린 채 다른 탭의 묶음이 시작되면
  // 복원이 묶음의 사슬을 끊는다. 보기와 보존본 지우기는 덱을 쓰지 않아 잠그지 않는다
  restoreLockedReason?: string;
  deck?: Deck;  // 장을 순서와 제목으로 보이는 데 쓴다. 덱을 읽지 못하는 프로젝트에서는 없다
  onBack: () => void;
  onConflict?: () => void;  // 복원이 412를 받으면 부모(ProjectView)가 배너를 띄운다
  // 후보를 다시 만들 단계로 옮기고 그 장을 미리 고른다 (D2b-5c, C24)
  onOpen?: (stage: OpenStage, chapterId?: string, diagramJobId?: string) => void;
  // 복구 화면에서 반영한 덱. 부모가 덱 상태에 넣는다(장 이름과 슬라이드 유무 판정에 쓴다, C1 계획 4.2)
  onDeckSaved?: (deck: Deck) => void;
  onApplyUnconfirmed?: () => void;  // 반영 응답이 5xx다. 부모가 "반영 결과를 확인하지 못함" 안내를 띄운다
}) {
  const [snapshots, setSnapshots] = useState<SnapshotInfo[] | null>(null);
  const [error, setError] = useState("");
  // 충돌이나 저장 실패로 보존한 변경 (D2a-2). 스냅샷과 섞지 않는다. 목록 실패가 스냅샷 복구를 막지 않는다
  const [drafts, setDrafts] = useState<DraftInfo[] | null>(null);
  const [draftError, setDraftError] = useState("");
  const loadDrafts = () => api.listDrafts(project.name)
    .then((list) => { setDrafts([...list].reverse()); setDraftError(""); })
    .catch((e) => setDraftError(`보존한 변경 목록을 읽지 못했습니다. ${messageOf(e)}`));
  useEffect(() => { void loadDrafts(); }, [project.name]);  // eslint-disable-line react-hooks/exhaustive-deps

  // 요약을 받는 동안 다른 탭의 묶음이 시작될 수 있다. 확인 뒤에 지금 잠금 이유를 다시 본다(리뷰 G20)
  const lockedRef = useRef(restoreLockedReason);
  lockedRef.current = restoreLockedReason;
  const [summarizing, setSummarizing] = useState(false);
  const restoreDraft = async (id: string) => {
    // 복원 전에 서버 저장본과의 차이를 같은 확인 창에 보인다 (D3c-6, E7). 요약을 받지 못해도 복원은 고를 수 있다
    if (summarizing) return;
    setSummarizing(true);
    let summary: string;
    try {
      summary = await api.getDraftSummary(project.name, id).then(draftSummaryText,
        () => "저장본과의 차이를 확인하지 못했습니다.");
    } finally {
      setSummarizing(false);
    }
    const ok = window.confirm(
      `이 보존본으로 복원합니다. ${summary}\n\n복원하면 지금 저장본(다른 곳의 변경 포함)은 복원 직전 시점의 스냅샷으로 남습니다. 계속할까요?`,
    );
    if (!ok) return;
    if (lockedRef.current) { setDraftError(lockedRef.current); return; }
    try {
      await api.restoreDraft(project.name, id);
      onBack();
    } catch (e) {
      if (e instanceof ApiError && e.status === 412) onConflict?.();
      else setDraftError(messageOf(e));
    }
  };

  const deleteDraft = async (id: string) => {
    if (!window.confirm("이 보존본을 지웁니다. 지운 보존본은 되살릴 수 없습니다. 계속할까요?")) return;
    try {
      await api.deleteDraft(project.name, id);
      await loadDrafts();
    } catch (e) {
      setDraftError(messageOf(e));
    }
  };

  useEffect(() => {
    api.listSnapshots(project.name)
      .then((list) => setSnapshots([...list].reverse()))  // 최신이 위로
      .catch((e) => setError(messageOf(e)));
  }, [project.name]);

  const restore = async (id: string) => {
    const ok = window.confirm(
      "이 시점으로 되돌립니다. 복원 직전 상태도 스냅샷으로 보존되므로 다시 되돌릴 수 있습니다. 계속할까요?",
    );
    if (!ok) return;
    try {
      await api.restoreSnapshot(project.name, id);
      onBack();  // 목록으로 돌아가면 상태가 새로 읽힌다
    } catch (e) {
      if (e instanceof ApiError && e.status === 412) {
        onConflict?.();  // 전용 UI 없이 ProjectView 배너의 "서버 내용 다시 읽기"로 회복한다
      } else {
        setError(messageOf(e));
      }
    }
  };

  return (
    <div className="recovery-screen">
      <h2>스냅샷 복구</h2>
      {restoreLockedReason && <p role="status">{restoreLockedReason}</p>}
      <p>저장 시점 목록입니다. 복원하면 그 시점의 내용으로 돌아갑니다.</p>
      {error && <p role="alert">{error}</p>}
      {snapshots === null ? (
        <p>불러오는 중...</p>
      ) : snapshots.length === 0 ? (
        <p>되돌릴 수 있는 저장 시점이 없습니다.</p>
      ) : (
        <ul>
          {snapshots.map((s) => (
            <li key={s.id}>
              {s.saved_at}
              {s.kind === "pre_migration" && <em> (새 형식으로 바꾸기 전)</em>}
              {/* 0.2.0 같은 다른 앱이 이 프로젝트를 옛 시점으로 되돌리기 직전의 덱 (D3b-1, 되찾을 지점) */}
              {s.kind === "before_revert" && <em> (다른 앱에서 되돌리기 전)</em>}
              {" "}<Button variant="danger" onClick={() => restore(s.id)} disabled={!!restoreLockedReason}
                title={restoreLockedReason}>이 시점으로 복원</Button>
            </li>
          ))}
        </ul>
      )}
      <section className="draft-list">
        <h3>충돌로 보존한 변경</h3>
        <p>다른 곳의 저장과 충돌했거나 저장하지 못한 내용입니다. 자동으로 지우지 않습니다.
          복원하면 지금 저장본(다른 곳의 변경 포함)은 복원 직전 시점의 스냅샷으로 남습니다.</p>
        {draftError && <p role="alert">{draftError}</p>}
        {summarizing && <p role="status">저장본과의 차이를 확인하고 있습니다.</p>}
        {drafts === null ? (draftError ? null : <p>불러오는 중...</p>) : drafts.length === 0 ? (
          <p>보존한 변경이 없습니다.</p>
        ) : (
          <ul>
            {drafts.map((d) => (
              <li key={d.id}>
                {formatSavedAt(d.saved_at)} {describeDraft(d)}{" "}
                <Button variant="danger" onClick={() => void restoreDraft(d.id)} disabled={!!restoreLockedReason || summarizing}
                  title={restoreLockedReason}>이 변경으로 복원</Button>{" "}
                <Button variant="danger" onClick={() => void deleteDraft(d.id)}>이 보존본 지우기</Button>
              </li>
            ))}
          </ul>
        )}
      </section>
      <JobCandidates project={project} deck={deck} onOpen={onOpen} onConflict={onConflict} onDeckSaved={onDeckSaved}
        onApplyUnconfirmed={onApplyUnconfirmed} />
      {/* 다섯 단계 안에서는 복구 화면만 닫는다. 덱을 열 수 없는 프로젝트에서는 프로젝트 목록으로 간다 */}
      <button onClick={onBack}>{deck ? "복구 화면 닫기" : "목록으로"}</button>
    </div>
  );
}
