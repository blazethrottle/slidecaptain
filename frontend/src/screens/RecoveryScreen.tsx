import { useEffect, useState } from "react";
import { api, ApiError, messageOf, type DraftInfo, type ProjectInfo, type SnapshotInfo } from "../api/client";

import { formatSavedAt } from "../api/time";

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

export function RecoveryScreen({ project, onBack, onConflict }: {
  project: ProjectInfo;
  onBack: () => void;
  onConflict?: () => void;  // 복원이 412를 받으면 부모(ProjectView)가 배너를 띄운다
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
              {" "}<button onClick={() => restore(s.id)}>이 시점으로 복원</button>
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
                <button onClick={() => void restoreDraft(d.id)}>이 변경으로 복원</button>{" "}
                <button onClick={() => void deleteDraft(d.id)}>이 보존본 지우기</button>
              </li>
            ))}
          </ul>
        )}
      </section>
      <button onClick={onBack}>목록으로</button>
    </div>
  );
}
