import { useEffect, useRef, useState } from "react";
import type { SaveState } from "../state/useDeckEditor";

// 상태 표시 (개정판 D2a-5, 제품 설계 4절). 색만으로 구별하지 않도록 상태마다 문구와 아이콘을 함께 둔다.
// "현재 보고 있는 단계"는 내비게이션의 선택 표시라 D3에서 다룬다. 작업 상태(취소 요청, 완료 불명)는 D2b다.
export const STATUS_KINDS = [
  "not_started", "unsaved", "saving", "saved", "save_failed", "conflict",
  "ready", "needs_review", "failed", "running",
] as const;
export type StatusKind = (typeof STATUS_KINDS)[number];

type Tone = "neutral" | "warning" | "success" | "danger" | "primary";

const SPEC: Record<StatusKind, { label: string; icon: string; iconName: string; tone: Tone }> = {
  not_started: { label: "시작 전", icon: "○", iconName: "빈 원", tone: "neutral" },
  unsaved: { label: "변경사항 있음", icon: "✎", iconName: "연필", tone: "warning" },
  saving: { label: "저장 중", icon: "↻", iconName: "회전 화살표", tone: "neutral" },
  saved: { label: "저장됨", icon: "✓", iconName: "체크", tone: "success" },
  save_failed: { label: "저장하지 못했습니다. 변경은 이 화면에 남아 있습니다", icon: "⚠", iconName: "경고 삼각형", tone: "danger" },
  conflict: { label: "다른 곳에서 먼저 저장했습니다", icon: "⇄", iconName: "엇갈린 화살표", tone: "danger" },
  ready: { label: "준비됨", icon: "☑", iconName: "체크 상자", tone: "success" },
  needs_review: { label: "확인 필요", icon: "!", iconName: "느낌표", tone: "warning" },
  failed: { label: "실행 실패", icon: "✕", iconName: "엑스", tone: "danger" },
  running: { label: "생성 중", icon: "⋯", iconName: "진행 점", tone: "primary" },
};

/** 저장 훅의 상태를 표시 종류로 옮긴다. 충돌은 저장 실패와 조치가 반대라 따로 둔다. */
export function saveStatusKind(saveState: SaveState, conflict: boolean): StatusKind {
  if (saveState === "저장됨") return "saved";
  if (saveState === "저장 대기") return "unsaved";
  if (saveState === "저장 중") return "saving";
  return conflict ? "conflict" : "save_failed";
}

/** 상태 한 줄. running 같은 작업 상태는 호출자가 정해 넘긴다(D2b에서 원천이 작업 원장으로 바뀐다). */
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
export function SaveAnnouncer({ kind }: { kind: StatusKind }) {
  const previous = useRef(kind);
  const [message, setMessage] = useState("");
  useEffect(() => {
    if (kind === "saved" && previous.current !== "saved") setMessage("저장됨");
    else if (kind !== "saved") setMessage("");
    previous.current = kind;
  }, [kind]);
  return <p className="visually-hidden" role="status">{message}</p>;
}
