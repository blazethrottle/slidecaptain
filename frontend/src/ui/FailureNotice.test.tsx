// 다른 작업 진행 중(409) 안내와 머리의 진행 작업 (개정판 D3a-5, 묶음 리뷰 A10, D3a-5 리뷰 R8, R13)
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api, ApiError, type ActiveJob } from "../api/client";
import { ActiveJobContext } from "./ActiveJobNotice";
import { describeFailure } from "./failure";
import { FailureNotice } from "./FailureNotice";

const job = (id: string, project = "다른보고"): ActiveJob => ({ id, project, kind: "chapters", target: null,
  stage: "running", created_at: "", cancel_requested: false });
const rejected = describeFailure(new ApiError(409, "다른 AI 생성이 진행 중입니다.", "generation_active", job("job-9")));

function renderWith(active: ActiveJob | null, revision: number, inModal = false) {
  return render(<ActiveJobContext.Provider value={{ active, revision, refresh: () => {} }}>
    <FailureNotice failure={rejected} inModal={inModal} />
  </ActiveJobContext.Provider>);
}

it("프로젝트 화면 안에서는 안내 안에 취소 버튼을 두지 않고 머리의 취소를 가리킨다", () => {
  renderWith(job("job-9"), 1);
  expect(screen.queryByRole("button", { name: "그 작업 취소" })).toBeNull();
  expect(screen.getByRole("status")).toHaveTextContent(/화면 위쪽의 '그 작업 취소'/);
});

it("초점을 가두는 대화 상자 안에서는 안내 안에 취소 버튼을 남긴다 (R8)", () => {
  renderWith(job("job-9"), 1, true);
  expect(screen.getByRole("button", { name: "그 작업 취소" })).toBeInTheDocument();
});

it("머리에 다른 작업이 진행 중이면 끝났다고 하지 않는다 (R13)", () => {
  const { rerender } = renderWith(job("job-9"), 1);
  rerender(<ActiveJobContext.Provider value={{ active: job("job-10", "또다른보고"), revision: 2, refresh: () => {} }}>
    <FailureNotice failure={rejected} />
  </ActiveJobContext.Provider>);
  expect(screen.getByRole("status")).not.toHaveTextContent(/끝났습니다/);
  rerender(<ActiveJobContext.Provider value={{ active: null, revision: 3, refresh: () => {} }}>
    <FailureNotice failure={rejected} />
  </ActiveJobContext.Provider>);
  expect(screen.getByRole("status")).toHaveTextContent(/진행 중이던 다른 AI 작업\(다른보고\)이 끝났습니다/);
});

it("프로젝트 화면 밖에서는 지금처럼 안내 안의 취소 버튼을 보인다", () => {
  render(<FailureNotice failure={rejected} />);
  expect(screen.getByRole("button", { name: "그 작업 취소" })).toBeInTheDocument();
});

it("거절의 원인 작업이 끝나고 다른 작업이 돌면 그 작업을 말하고, 대화 상자 안 취소도 그 작업을 겨냥한다 (재리뷰 F11)", async () => {
  const cancel = vi.spyOn(api, "cancelJob").mockResolvedValue({} as Awaited<ReturnType<typeof api.cancelJob>>);
  render(<ActiveJobContext.Provider value={{ active: job("job-10", "또다른보고"), revision: 2, refresh: () => {} }}>
    <FailureNotice failure={rejected} inModal />
  </ActiveJobContext.Provider>);
  expect(screen.getByRole("status")).toHaveTextContent("다른 AI 작업이 진행 중입니다.");
  await userEvent.click(screen.getByRole("button", { name: "그 작업 취소" }));
  expect(cancel).toHaveBeenCalledWith("또다른보고", "job-10");
  cancel.mockRestore();
});
