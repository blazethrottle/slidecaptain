// 실행 단계와 경과 시간 (D3b-7, 계획 4.7). 경과 초는 서버 값을 처음 한 번 받아 그 뒤로 브라우저가 센다
import { act, render, screen } from "@testing-library/react";
import { jobView } from "../test/jobs";
import { formatElapsed, GenerationSteps } from "./GenerationSteps";

afterEach(() => vi.useRealTimers());

const view = (extra = {}) => jobView("structure", { id: "j1", state: "running", candidate_status: "none", result: null,
  step: "generating", step_started_at: "2026-10-12T10:00:00+09:00", elapsed_seconds: 5, ...extra });

test("경과 시간은 서버 값에서 브라우저가 이어 세고, 다음 조회의 서버 값으로 튀지 않는다", () => {
  vi.useFakeTimers();
  const { rerender } = render(<GenerationSteps view={view()} />);
  expect(screen.getByText("경과 시간 5초")).toBeInTheDocument();
  act(() => { vi.advanceTimersByTime(2000); });
  expect(screen.getByText("경과 시간 7초")).toBeInTheDocument();
  rerender(<GenerationSteps view={view({ elapsed_seconds: 30 })} />);
  expect(screen.getByText("경과 시간 7초")).toBeInTheDocument();
});

test("경과 시간은 라이브 영역 밖이고 알림은 단계 이름만 담는다 (리뷰 U18)", () => {
  render(<GenerationSteps view={view()} />);
  const status = screen.getByRole("status");
  expect(status).toHaveTextContent("구성 생성 중");
  expect(status).not.toHaveTextContent("초");
  expect(screen.getByText("경과 시간 5초").closest("[role=status], [aria-live]")).toBeNull();
});

test("취소 요청 중에는 단계를 보이지 않고 취소 요청됨을 알린다", () => {
  render(<GenerationSteps view={view({ step: null, cancel_requested: true, state: "cancel_requested" })} />);
  expect(screen.getByRole("status")).toHaveTextContent("취소 요청됨");
  expect(screen.queryByRole("listitem")).toBeNull();
});

test("경과 시간 표기", () => {
  expect(formatElapsed(9)).toBe("9초");
  expect(formatElapsed(75)).toBe("1분 15초");
});
