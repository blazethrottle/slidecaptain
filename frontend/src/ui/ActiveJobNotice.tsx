import { useState } from "react";
import { api, ApiError, messageOf, type ActiveJob } from "../api/client";

// 다른 AI 생성이 진행 중이라 등록이 거절됐을 때(409 generation_active) 그 작업을 취소할 수단을 보인다 (D2b-5b)
export function ActiveJobNotice({ error }: { error: unknown }) {
  if (!(error instanceof ApiError) || error.code !== "generation_active" || !error.active) return null;
  // 안내 상태는 안쪽 부품이 가진다. 오류가 사라지면 함께 사라지므로 앞 작업의 취소 안내가 다음 작업의
  // 취소 버튼을 가리지 않는다 (D2b-5b 리뷰 R13)
  return <ActiveJobCancel active={error.active} />;
}

function ActiveJobCancel({ active }: { active: ActiveJob }) {
  const [notice, setNotice] = useState("");
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
