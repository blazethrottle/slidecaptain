import { useEffect, useState } from "react";
import { api, ApiError, messageOf, TERMINAL_JOB_STATES, type DraftInfo, type JobView, type ProjectInfo, type SnapshotInfo } from "../api/client";
import { blockingReasons, reasonText, slotsText } from "../api/jobs";
import { StatusIndicator } from "../ui/StatusIndicator";

import { formatSavedAt } from "../api/time";
import { Button } from "../ui/Button";

// 사유와 출처는 이후 버전이 값을 늘릴 수 있어 모르는 값도 그대로 보인다 (D2a-2 리뷰 R5)
function describeDraft(d: DraftInfo): string {
  if (d.reason === "conflict" && d.source === "structure_approval") {
    return "승인하려던 장 구성(내용 생성 전) (구조안 승인)";  // 리뷰 R12: 슬라이드가 없을 수 있다
  }
  const reason = ({ conflict: "다른 곳의 저장과 충돌한 편집", generation_unsaved: "저장하지 못한 생성 결과" } as
    Record<string, string>)[d.reason] ?? `알 수 없는 사유(${d.reason})`;
  const source = ({ editor: "편집 화면", structure_approval: "구조안 승인" } as Record<string, string>)[d.source]
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
  // 장 재생성과 축약은 다른 장만 바뀐 경우 반영을 막지 않는다. 저장본 값이 달라도 그 사실을 밝힌다 (리뷰 R19)
  const elsewhere = c.job.stale_reasons.includes("deck_changed_elsewhere");
  return `${cancelled}${basis} ${unreadable ? "저장본이나 자료를 읽지 못해 지금 입력과 비교할 수 없습니다."
    : c.reasons.length > 0 ? `이전 입력 기준 후보입니다(${reasonText(c.reasons)}).`
      : elsewhere ? "덱의 다른 부분만 바뀌어 이 장에는 영향이 없습니다." : "지금 입력과 같은 기준입니다."}`;
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

function JobCandidates({ project, onOpen }: { project: ProjectInfo; onOpen?: (tab: "structure" | "editor") => void }) {
  const [items, setItems] = useState<Candidate[] | null>(null);
  const [ended, setEnded] = useState<JobView[]>([]);
  const [error, setError] = useState("");
  const load = () => api.listJobs(project.name)
    .then((jobs) => { setItems(candidatesOf(jobs)); setEnded(endedWithoutResult(jobs)); setError(""); })
    .catch((e) => setError(`AI 결과 후보를 읽지 못했습니다. ${messageOf(e)}`));
  useEffect(() => { void load(); }, [project.name]);  // eslint-disable-line react-hooks/exhaustive-deps
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
      <h3>AI 결과 후보</h3>
      <p>AI가 만들었지만 아직 반영하거나 버리지 않은 결과입니다. 반영은 해당 화면에서 합니다.</p>
      {error && <p role="alert">{error}</p>}
      {items === null ? (error ? null : <p>불러오는 중...</p>) : items.length === 0 ? (
        <p>남아 있는 AI 결과 후보가 없습니다.</p>
      ) : (
        <ul>
          {items.map((c) => (
            <li key={c.key}>
              <p>{KIND_LABELS[c.job.kind] ?? c.job.kind}{c.chapterId ? ` (장 ${c.chapterId})` : ""},{" "}
                만든 시각 {formatSavedAt(c.job.created_at)}</p>
              <p>{candidateStatus(c)}</p>
              <details><summary>보기</summary><pre>{candidateText(c)}</pre></details>
              {/* 덱을 읽지 못하는 프로젝트에서는 옮길 화면이 없다 (리뷰 R10) */}
              {!WHOLE_DECK.has(c.job.kind) && onOpen && <><button onClick={() => onOpen(["structure", "chapters"].includes(c.job.kind) ? "structure" : "editor")}>
                현재 입력으로 다시 생성</button>{" "}</>}
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
              {KIND_LABELS[j.kind] ?? j.kind}{j.target ? ` (장 ${j.target})` : ""}, 만든 시각 {formatSavedAt(j.created_at)}
            </li>
          ))}
        </ul>
      </>}
    </section>
  );
}

export function RecoveryScreen({ project, onBack, onConflict, onOpen }: {
  project: ProjectInfo;
  onBack: () => void;
  onConflict?: () => void;  // 복원이 412를 받으면 부모(ProjectView)가 배너를 띄운다
  onOpen?: (tab: "structure" | "editor") => void;  // 후보를 다시 만들 화면으로 옮긴다 (D2b-5c)
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

  const restoreDraft = async (id: string) => {
    const ok = window.confirm(
      "이 보존본으로 복원합니다. 복원하면 지금 저장본(다른 곳의 변경 포함)은 복원 직전 시점의 스냅샷으로 남습니다. 계속할까요?",
    );
    if (!ok) return;
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
              {" "}<Button variant="danger" onClick={() => restore(s.id)}>이 시점으로 복원</Button>
            </li>
          ))}
        </ul>
      )}
      <section className="draft-list">
        <h3>충돌로 보존한 변경</h3>
        <p>다른 곳의 저장과 충돌했거나 저장하지 못한 내용입니다. 자동으로 지우지 않습니다.
          복원하면 지금 저장본(다른 곳의 변경 포함)은 복원 직전 시점의 스냅샷으로 남습니다.</p>
        {draftError && <p role="alert">{draftError}</p>}
        {drafts === null ? (draftError ? null : <p>불러오는 중...</p>) : drafts.length === 0 ? (
          <p>보존한 변경이 없습니다.</p>
        ) : (
          <ul>
            {drafts.map((d) => (
              <li key={d.id}>
                {formatSavedAt(d.saved_at)} {describeDraft(d)}{" "}
                <Button variant="danger" onClick={() => void restoreDraft(d.id)}>이 변경으로 복원</Button>{" "}
                <button onClick={() => void deleteDraft(d.id)}>이 보존본 지우기</button>
              </li>
            ))}
          </ul>
        )}
      </section>
      <JobCandidates project={project} onOpen={onOpen} />
      <button onClick={onBack}>목록으로</button>
    </div>
  );
}
