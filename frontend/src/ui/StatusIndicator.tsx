import { useEffect, useRef, useState } from "react";
import type { SaveState } from "../state/useDeckEditor";

// 상태 표시 (개정판 D2a-5, 제품 설계 4절). 색만으로 구별하지 않도록 상태마다 문구와 아이콘을 함께 둔다.
// "현재 보고 있는 단계"는 내비게이션의 선택 표시라 D3에서 다룬다. 작업 상태(취소 요청, 완료 불명)는 D2b다.
export const STATUS_KINDS = [
  "not_started", "unsaved", "saving", "saved", "save_failed", "conflict",
  "ready", "needs_review", "failed", "running", "cancel_requested", "completion_unknown",
] as const;
export type StatusKind = (typeof STATUS_KINDS)[number];

type Tone = "neutral" | "warning" | "success" | "danger" | "primary";

const SPEC: Record<StatusKind, { label: string; icon: string; iconName: string; tone: Tone }> = {
  not_started: { label: "시작 전", icon: "○", iconName: "빈 원", tone: "neutral" },
  // 일부 글자는 운영체제가 색 이모지로 그려 글자색이 적용되지 않는다. U+FE0E로 글자 모양을 요청한다 (D2a-5 리뷰 R13)
  unsaved: { label: "변경사항 있음", icon: "\u270E\uFE0E", iconName: "연필", tone: "warning" },
  saving: { label: "저장 중", icon: "\u21BB\uFE0E", iconName: "회전 화살표", tone: "neutral" },
  saved: { label: "저장됨", icon: "✓", iconName: "체크", tone: "success" },
  save_failed: { label: "저장하지 못했습니다. 변경은 이 화면에 남아 있습니다", icon: "\u26A0\uFE0E", iconName: "경고 삼각형", tone: "danger" },
  conflict: { label: "다른 곳에서 먼저 저장했습니다", icon: "\u21C4\uFE0E", iconName: "엇갈린 화살표", tone: "danger" },
  ready: { label: "준비됨", icon: "\u2611\uFE0E", iconName: "체크 상자", tone: "success" },
  needs_review: { label: "확인 필요", icon: "!", iconName: "느낌표", tone: "warning" },
  failed: { label: "실행 실패", icon: "✕", iconName: "엑스", tone: "danger" },
  running: { label: "생성 중", icon: "\u22EF\uFE0E", iconName: "진행 점", tone: "primary" },
  // 작업 상태 (D2b-5c). 취소 요청은 아직 진행 중이라 중립색, 완료 불명은 사용자의 확인이 필요해 주의색이다
  cancel_requested: { label: "취소 요청됨", icon: "\u23F8\uFE0E", iconName: "일시 정지", tone: "neutral" },
  completion_unknown: { label: "완료 여부 확인 필요", icon: "?", iconName: "물음표", tone: "warning" },
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
export function SaveAnnouncer({ kind }: { kind: StatusKind }) {
  const previous = useRef(kind);
  const [message, setMessage] = useState("");
  useEffect(() => {
    // 충돌을 서버 내용으로 되돌린 뒤의 "저장됨"은 내 편집이 저장된 것이 아니므로 알리지 않는다 (리뷰 R10)
    if (kind === "saved" && previous.current !== "saved" && previous.current !== "conflict") setMessage("저장됨");
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
export function JobAnnouncer({ active }: { active: { id: string; project: string } | null }) {
  const previous = useRef(active);
  const [message, setMessage] = useState("");
  useEffect(() => {
    const before = previous.current;
    if (before && before.id !== active?.id) setMessage(`AI 생성 작업이 끝났습니다(${before.project})`);
    else if (active) setMessage("");
    previous.current = active;
  }, [active]);
  return <p className="visually-hidden" role="status">{message}</p>;
}
