import { useState } from "react";
import { api, ApiError, messageOf } from "../api/client";

// 다른 AI 생성이 진행 중이라 등록이 거절됐을 때(409 generation_active) 그 작업을 취소할 수단을 보인다 (D2b-5b)
export function ActiveJobNotice({ error }: { error: unknown }) {
  const [notice, setNotice] = useState("");
  if (!(error instanceof ApiError) || error.code !== "generation_active" || !error.active) return null;
  const active = error.active;
  const cancel = async () => {
    try {
      await api.cancelJob(active.project, active.id);
      setNotice("취소를 요청했습니다. 그 작업이 멈추면 다시 시도해 주세요.");
    } catch (e) {
      setNotice(messageOf(e));
    }
  };
  return (
    <p className="notice">
      진행 중인 작업: {active.project}{" "}
      {notice ? <span>{notice}</span> : <button onClick={() => void cancel()}>그 작업 취소</button>}
    </p>
  );
}
