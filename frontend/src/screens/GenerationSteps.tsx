import { useEffect, useRef, useState } from "react";
import type { JobView } from "../api/client";

// 구조안 생성의 실행 단계와 경과 시간 (개정판 D3b-7, 계획 4.7과 4.8). 단계는 시간이 드는 경계다. 화면은 지난 단계 목록과
// 지금 단계를 보이고, 재시도는 단계를 하나 더하는 것으로 보이며 되돌아가지 않는다. 백분율과 남은 시간은 보이지 않는다
export const STEP_LABELS = {
  connecting: "AI 연결 확인 중",
  generating: "구성 생성 중",
  retrying_format: "형식 다시 맞추는 중",
} as const;
// 지난 단계의 이름. "중"과 "(지남)"이 함께 붙지 않게 한다 (D3b-7 리뷰 R20)
const PAST_LABELS = { connecting: "AI 연결 확인", generating: "구성 생성", retrying_format: "형식 다시 맞춤" } as const;
type Step = keyof typeof STEP_LABELS;
const ORDER: Step[] = ["connecting", "generating", "retrying_format"];

// 화면이 쓰는 단계. step을 stage보다 우선한다. 시작 직후 단계가 아직 없으면 연결 확인 중으로 둔다(실행 중인데 step이
// connecting인 밀리초 구간도 같다, D3b-4 리뷰 R10). 취소 요청 중에는 단계를 보이지 않는다
function currentStep(view: JobView): Step | null {
  if (view.cancel_requested) return null;
  if (view.step) return view.step;
  return view.state === "queued" ? "connecting" : null;
}

export function formatElapsed(seconds: number): string {
  return seconds < 60 ? `${seconds}초` : `${Math.floor(seconds / 60)}분 ${seconds % 60}초`;
}

export function GenerationSteps({ view }: { view: JobView }) {
  const step = currentStep(view);
  // 다시 연 화면이나 새로고침 뒤에도 지난 단계를 되살린다. 단계 순서가 고정이라 지금 단계에서 앞 단계를 안다 (리뷰 R4)
  const [seen, setSeen] = useState<Step[]>(() => (step ? ORDER.slice(0, ORDER.indexOf(step) + 1) : []));
  useEffect(() => {
    if (step) setSeen((list) => (list.at(-1) === step ? list : [...list, step]));
  }, [step]);
  // 상태 알림은 빈 채로 먼저 그린 뒤 채운다. 내용을 가진 채 생긴 알림 영역은 낭독되지 않을 수 있다 (리뷰 R17)
  const label = step ? STEP_LABELS[step] : view.cancel_requested ? "취소 요청됨" : "";
  const [announced, setAnnounced] = useState("");
  useEffect(() => { setAnnounced(label); }, [label]);
  // 경과 시간: 서버가 준 경과 초를 처음 한 번 받아 그 뒤로 브라우저가 센다. 조회마다 맞추면 두 시계 차이로 값이 튄다
  const base = useRef<{ jobId: string; seconds: number; at: number } | null>(null);
  if ((base.current === null || base.current.jobId !== view.id) && view.elapsed_seconds != null) {
    base.current = { jobId: view.id, seconds: view.elapsed_seconds, at: Date.now() };
  }
  const [, tick] = useState(0);
  useEffect(() => {
    const timer = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(timer);
  }, []);
  const elapsed = base.current ? base.current.seconds + Math.floor((Date.now() - base.current.at) / 1000) : null;
  return (
    <div className="generation-steps">
      {/* 단계가 바뀔 때만 한 번 알린다. 경과 시간은 이 알림 밖에 둔다 (리뷰 U18) */}
      <p role="status" className="visually-hidden">{announced}</p>
      <ol className="generation-step-list" aria-label="구조안 생성 단계">
        {seen.map((name, i) => {
          const now = i === seen.length - 1 && name === step;
          return <li key={`${name}-${i}`} aria-current={now ? "step" : undefined}>
            {now ? STEP_LABELS[name] : `${PAST_LABELS[name]} (지남)`}</li>;
        })}
        {/* 취소 요청 중에는 보이는 목록 끝에도 그 사실을 둔다(작업이 계속 도는 것처럼 읽히지 않게, 리뷰 R5) */}
        {view.cancel_requested && <li aria-current="step">취소 요청됨</li>}
      </ol>
      {elapsed !== null && <p className="hint">경과 시간 {formatElapsed(elapsed)}</p>}
    </div>
  );
}
