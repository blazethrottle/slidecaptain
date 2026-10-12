import { createContext, useContext, useEffect, useRef, useState } from "react";
import { api, messageOf, type ActiveJob } from "../api/client";

// 상단 머리가 보이는 서비스의 진행 작업 (개정판 D3a-5, 계획 4.4). 프로젝트 화면이 내려 주어, 실패 안내와 화면 안의
// 취소 버튼이 머리의 작업 표시와 따로 놀지 않게 한다 (D3a 묶음 리뷰 A10, A11). revision은 진행 작업 조회가 끝날
// 때마다 는다. 프로젝트 화면 밖(단독 시험)에서는 없다
export type ActiveJobState = { active: ActiveJob | null; revision: number; refresh: () => void };
export const ActiveJobContext = createContext<ActiveJobState | null>(null);

// 장 생성 묶음 중 덱을 쓰는 화면의 안내 (D3a-5, 계획 4.4, 사용자 결정 Q1의 A). 묶음과 사용자 저장의 경합을 실제로
// 막는 것은 서버의 If-Match와 사슬 검사이고, 이 안내와 읽기 전용은 사용자에게 알리는 일이다
export const BATCH_READ_ONLY_NOTICE = "내용 생성 중에는 문서를 고칠 수 없습니다. 생성 중인 장은 끝나면 보입니다.";
// 묶음 중 읽기 전용이 된 화면에 저장하지 않은 입력이 남아 있으면 떠나기 전에 묻는다. 저장하면 묶음의 사슬이 끊긴다
export const BATCH_DISCARD_CONFIRM = "내용 생성 중이라 고친 내용을 저장할 수 없습니다. 이 화면을 떠나면 고친 내용이 사라집니다. 계속할까요?";

// 머리가 이 작업을 보이고 있는가. 보이는 동안 화면 안에는 같은 작업의 취소 버튼을 두지 않는다 (A11)
export function useHeaderShowsJob(jobId: string | null | undefined): boolean {
  const ctx = useContext(ActiveJobContext);
  return !!ctx && !!jobId && ctx.active?.id === jobId;
}

// 다른 작업 진행 중(409)으로 거절됐을 때 그 작업의 지금 상태. 프로젝트 화면 밖이면 "unknown"이다. 안내가 뜬 뒤
// 진행 작업 조회가 한 번이라도 끝났는데 그 작업이 없으면 끝난 것으로 본다. 안내가 뜰 때 머리가 그 작업을 아직
// 모를 수 있으므로 바로 다시 조회하게 한다 (A10)
// 머리에 다른 작업이 진행 중이면 끝났다고 하지 않는다. 다시 시도해도 그 작업 때문에 다시 거절된다 (D3a-5 리뷰 R13)
export function useActiveJobFate(active: ActiveJob | undefined): "unknown" | "running" | "ended" {
  const ctx = useContext(ActiveJobContext);
  const mountRevision = useRef(ctx?.revision ?? 0);
  // 다시 조회는 거절의 원인 작업이 정해질 때 한 번만 한다. 조회가 끝나면 상태가 바뀌어 다시 그려지므로,
  // 조회 함수를 효과의 조건에 넣으면 조회가 되풀이된다
  const refresh = useRef(ctx?.refresh);
  refresh.current = ctx?.refresh;
  const activeId = active?.id;
  useEffect(() => { if (activeId) refresh.current?.(); }, [activeId]);
  if (!ctx || !active) return "unknown";
  if (ctx.active) return "running";
  return ctx.revision > mountRevision.current ? "ended" : "running";
}

// 다른 AI 생성이 진행 중이라 등록이 거절됐을 때(409 generation_active) 그 작업을 취소할 수단 (D2b-5b).
// 프로젝트 화면 밖에서만 실패 안내가 그린다. 안에서는 머리의 "그 작업 취소"를 가리킨다 (A10). 안내 상태는 이
// 부품이 가지므로 실패 안내가 사라지면 함께 사라져 앞 작업의 취소 안내가 다음 작업의 취소 버튼을 가리지 않는다
// (D2b-5b 리뷰 R13)
export function ActiveJobCancel({ active }: { active: ActiveJob }) {
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
