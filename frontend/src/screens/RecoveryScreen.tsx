import { useEffect, useState } from "react";
import { api, ApiError, messageOf, type ProjectInfo, type SnapshotInfo } from "../api/client";

export function RecoveryScreen({ project, onBack, onConflict }: {
  project: ProjectInfo;
  onBack: () => void;
  onConflict?: () => void;  // 복원이 412를 받으면 부모(ProjectView)가 배너를 띄운다
}) {
  const [snapshots, setSnapshots] = useState<SnapshotInfo[] | null>(null);
  const [error, setError] = useState("");

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
              {s.saved_at} <button onClick={() => restore(s.id)}>이 시점으로 복원</button>
            </li>
          ))}
        </ul>
      )}
      <button onClick={onBack}>목록으로</button>
    </div>
  );
}
