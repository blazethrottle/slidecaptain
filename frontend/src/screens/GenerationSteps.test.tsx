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
  expect(status).toHaveTextContent("구성 생성 중");  // 효과가 채운 뒤
  expect(status).not.toHaveTextContent("초");
  expect(screen.getByText("경과 시간 5초").closest("[role=status], [aria-live]")).toBeNull();
});

test("단계가 쌓인 뒤 취소를 요청하면 목록 끝에 취소 요청됨을 보이고 알린다 (D3b-7 리뷰 R5)", () => {
  const { rerender } = render(<GenerationSteps view={view()} />);
  rerender(<GenerationSteps view={view({ step: null, cancel_requested: true, state: "cancel_requested" })} />);
  const items = screen.getAllByRole("listitem").map((li) => li.textContent);
  expect(items).toEqual(["AI 연결 확인 (지남)", "구성 생성 (지남)", "취소 요청됨"]);
  expect(screen.getByRole("status")).toHaveTextContent("취소 요청됨");
});

test("다시 연 화면은 지금 단계까지의 지난 단계를 되살린다 (D3b-7 리뷰 R4)", () => {
  render(<GenerationSteps view={view({ step: "retrying_format" })} />);
  expect(screen.getAllByRole("listitem").map((li) => li.textContent))
    .toEqual(["AI 연결 확인 (지남)", "구성 생성 (지남)", "형식 다시 맞추는 중"]);
});

test("상태 알림은 빈 채로 생긴 뒤 단계 이름을 채운다 (D3b-7 리뷰 R17)", async () => {
  render(<GenerationSteps view={view()} />);
  // 마운트 직후의 첫 그림은 비어 있고, 효과가 단계 이름을 채운다(낭독기는 생긴 뒤의 변경을 읽는다)
  expect(await screen.findByRole("status")).toHaveTextContent("구성 생성 중");
});

test("경과 시간 표기", () => {
  expect(formatElapsed(9)).toBe("9초");
  expect(formatElapsed(75)).toBe("1분 15초");
});
