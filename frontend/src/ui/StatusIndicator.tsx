import { useEffect, useRef, useState } from "react";
import { onProjectEvent, type JobView } from "../api/client";
import type { SaveState } from "../state/useDeckEditor";

// 상태 표시 (개정판 D2a-5, 제품 설계 4절). 색만으로 구별하지 않도록 상태마다 문구와 아이콘을 함께 둔다.
// 아이콘의 접근 가능한 이름은 모양이 아니라 상태의 뜻이고, 라벨 문구와 같은 말을 두 번 읽지 않도록 라벨과 다르게 쓴다 (D2a 이월 7)
// "현재 보고 있는 단계"는 내비게이션의 선택 표시라 D3에서 다룬다. 작업 상태(취소 요청, 완료 불명)는 D2b다.
export const STATUS_KINDS = [
  "not_started", "unsaved", "saving", "saved", "save_failed", "conflict",
  "ready", "needs_review", "failed", "running", "cancel_requested", "completion_unknown",
  // 단계 상태 (D3a-3, 계획 4.2). 조회 실패, 현재 단계의 미저장 변경, 검토 단계의 준비됨
  "unknown", "in_progress", "draft_checked",
] as const;
export type StatusKind = (typeof STATUS_KINDS)[number];
/** 상단 머리의 저장 상태 (D3a-2, 계획 4.1). 단계 화면이 자기 출처로 정해 올리고, null이면 표시하지 않는다. */
export type SaveStatus = { kind: StatusKind; detail?: string } | null;

type Tone = "neutral" | "warning" | "success" | "danger" | "primary";

const SPEC: Record<StatusKind, { label: string; icon: string; iconName: string; tone: Tone }> = {
  not_started: { label: "시작 전", icon: "○", iconName: "아직 시작하지 않음", tone: "neutral" },
  // 일부 글자는 운영체제가 색 이모지로 그려 글자색이 적용되지 않는다. U+FE0E로 글자 모양을 요청한다 (D2a-5 리뷰 R13)
  unsaved: { label: "변경사항 있음", icon: "\u270E\uFE0E", iconName: "저장하지 않은 변경", tone: "warning" },
  saving: { label: "저장 중", icon: "\u21BB\uFE0E", iconName: "저장 진행", tone: "neutral" },
  saved: { label: "저장됨", icon: "✓", iconName: "저장 완료", tone: "success" },
  save_failed: { label: "저장하지 못했습니다. 변경은 이 화면에 남아 있습니다", icon: "\u26A0\uFE0E", iconName: "저장 실패 경고", tone: "danger" },
  conflict: { label: "다른 곳에서 먼저 저장했습니다", icon: "\u21C4\uFE0E", iconName: "저장 충돌", tone: "danger" },
  ready: { label: "준비됨", icon: "\u2611\uFE0E", iconName: "준비 완료", tone: "success" },
  needs_review: { label: "확인 필요", icon: "!", iconName: "주의", tone: "warning" },
  failed: { label: "실행 실패", icon: "✕", iconName: "오류", tone: "danger" },
  running: { label: "생성 중", icon: "\u22EF\uFE0E", iconName: "진행 중", tone: "primary" },
  // 작업 상태 (D2b-5c). 취소 요청은 아직 진행 중이라 중립색, 완료 불명은 사용자의 확인이 필요해 주의색이다
  cancel_requested: { label: "취소 요청됨", icon: "\u23F8\uFE0E", iconName: "취소 대기", tone: "neutral" },
  completion_unknown: { label: "완료 여부 확인 필요", icon: "?", iconName: "결과 불명", tone: "warning" },
  // 단계 상태를 읽지 못했다. 준비됨으로 두지 않는다. 글자는 완료 불명과 같지만 뜻과 색이 다르다 (D3a-3)
  unknown: { label: "확인하지 못함", icon: "?", iconName: "상태 미확인", tone: "neutral" },
  // 현재 단계에 저장하지 않은 변경이 있다. 서버의 단계 상태보다 앞선다 (제품 설계 3절 "구성 작성 중")
  in_progress: { label: "작성 중", icon: "\u25D4\uFE0E", iconName: "작성 진행", tone: "warning" },
  // 검토 단계의 준비됨. 제출 가능을 뜻하지 않으므로 체크를 쓰지 않는다 (계획 4.2)
  draft_checked: { label: "초안 확인됨", icon: "\u25CE\uFE0E", iconName: "초안 점검 통과", tone: "primary" },
};

/** 저장 훅의 상태를 표시 종류로 옮긴다. 충돌은 저장 실패와 조치가 반대라 따로 둔다. */
export function saveStatusKind(saveState: SaveState, conflict: boolean): StatusKind {
  if (saveState === "저장됨") return "saved";
  if (saveState === "저장 대기") return "unsaved";
  if (saveState === "저장 중") return "saving";
  return conflict ? "conflict" : "save_failed";
}

/** 상태 한 줄. 작업 상태(생성 중, 취소 요청됨, 완료 여부 확인 필요)는 작업 원장에서 정해 넘긴다 (D2b-5c). */
export function StatusIndicator({ kind, detail }: { kind: StatusKind; detail?: string }) {
  const spec = SPEC[kind];
  return (
    <span className={`status-indicator status-${spec.tone} status-kind-${kind}`}>
      <span className="status-icon" role="img" aria-label={spec.iconName}>{spec.icon}</span>
      <span className="status-label">{spec.label}</span>
      {detail && <span className="status-detail">{detail}</span>}
    </span>
  );
}

/**
 * 보조기기 알림. 자동 저장은 1.2초마다 상태가 바뀌므로 "저장됨"으로 바뀔 때만 알린다.
 * 저장 실패와 충돌은 화면의 기존 오류 알림(role=alert)이 이미 알리므로 여기서 다시 알리지 않는다.
 */
export function SaveAnnouncer({ kind }: { kind: StatusKind | null }) {
  const previous = useRef(kind);
  const [message, setMessage] = useState("");
  useEffect(() => {
    // 충돌을 서버 내용으로 되돌린 뒤의 "저장됨"은 내 편집이 저장된 것이 아니므로 알리지 않는다 (리뷰 R10).
    // null은 저장 상태를 보이지 않는 때다(단계를 옮기는 중, 복구 화면). 그 앞뒤의 바뀜은 저장이 아니므로
    // 알리지 않는다. 저장 없이 단계를 떠날 때 "저장됨"을 낭독하지 않게 한다 (D3a-2 리뷰 R2)
    if (kind === "saved" && previous.current !== null && previous.current !== "saved" && previous.current !== "conflict") setMessage("저장됨");
    else if (kind !== "saved") setMessage("");
    previous.current = kind;
  }, [kind]);
  return <p className="visually-hidden" role="status">{message}</p>;
}

/**
 * 작업 상태의 보조기기 알림 (D2b-5c). 지켜보던 작업이 사라지거나 다른 작업으로 바뀔 때(종결 전이)에만 알린다.
 * 조회는 1초마다 반복되므로 진행 중 상태가 바뀔 때마다 알리면 읽기가 끊긴다. 한 조회 간격 안에 다음 작업이
 * 시작돼도 앞 작업의 끝을 놓치지 않도록 작업 ID로 비교한다 (D2b-5c 리뷰 R13)
 */
// 문구에 작업 종류를 넣는다. 같은 프로젝트에서 같은 결과의 작업이 연달아 끝나도(구조안 생성 뒤 내용 생성) 글이
// 달라 화면 낭독기가 다시 읽는다 (D3a 묶음 리뷰 A1). 주어는 모두 받침으로 끝나 조사를 고정한다
const KIND_SUBJECT: Record<string, string> = {
  structure: "구조안 생성", chapters: "내용 생성", chapter: "장 다시 생성", condense: "장 축약", diagram: "도식 생성",
  rewrite: "구성 재작성", repair: "제한된 수정",
};
const ENDED_TEXT: Partial<Record<JobView["state"], (subject: string) => string>> = {
  succeeded: (s) => `${s}이 끝났습니다`,
  failed: (s) => `${s}이 실패했습니다`,
  cancelled: (s) => `${s}을 취소했습니다`,
  interrupted: (s) => `${s}이 중단되었습니다`,
  remote_completion_unknown: (s) => `${s}이 끝났는지 확인하지 못했습니다`,
};

// 결과는 이 탭이 따라간 작업의 종결 알림(job_ended)에서 얻는다. 같은 탭의 작업은 진행 작업 조회가 모를 수 있어
// 종결 알림만으로도 알린다(리뷰 R11). 다른 탭의 작업처럼 결과를 모르면 끝났다고만 알리고, 사라짐을 먼저 알린 뒤
// 결과가 오면 결과 문구로 고친다. 한 작업은 한 번만 알린다 (D3a-4, C23)
export function JobAnnouncer({ active }: { active: { id: string; project: string; kind?: string } | null }) {
  const previous = useRef(active);
  const ended = useRef(new Map<string, JobView["state"]>());
  const kinds = useRef(new Map<string, string>());
  const announced = useRef<{ id: string; project: string } | null>(null);  // 마지막으로 알린 작업
  const seen = useRef(new Set<string>());  // 이미 알린 작업 ID
  const [message, setMessage] = useState("");
  const text = (job: { id: string; project: string }) => {
    const state = ended.current.get(job.id);
    const subject = KIND_SUBJECT[kinds.current.get(job.id) ?? ""] ?? "AI 생성 작업";
    return `${((state && ENDED_TEXT[state]) ?? ENDED_TEXT.succeeded!)(subject)}(${job.project})`;
  };
  useEffect(() => onProjectEvent((event) => {
    if (event.kind !== "job_ended" || !event.jobId || !event.state) return;
    ended.current.set(event.jobId, event.state);
    if (event.jobKind) kinds.current.set(event.jobId, event.jobKind);
    if (announced.current?.id === event.jobId) setMessage(text(announced.current));
    else if (!seen.current.has(event.jobId)) {
      announced.current = { id: event.jobId, project: event.project };
      seen.current.add(event.jobId);
      setMessage(text(announced.current));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }), []);
  useEffect(() => {
    if (active?.kind) kinds.current.set(active.id, active.kind);
    const before = previous.current;
    if (before && before.id !== active?.id && !seen.current.has(before.id)) {
      announced.current = before;
      seen.current.add(before.id);
      setMessage(text(before));
    } else if (active && active.id !== before?.id && !seen.current.has(active.id)) setMessage("");  // 새 작업이 시작됐다
    previous.current = active;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active]);
  return <p className="visually-hidden" role="status">{message}</p>;
}
