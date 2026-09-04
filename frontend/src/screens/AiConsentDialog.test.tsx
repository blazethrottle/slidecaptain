import { useState } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api, type AppStatus } from "../api/client";
import { AiConsentDialog } from "./AiConsentDialog";

vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return { ...mod, api: { ...mod.api, getStatus: vi.fn() } };
});

const STATUS: AppStatus = {
  provider: "subscription", model: "sonnet", last_generation_at: null, checked_at: "2026-09-04T09:00:00+09:00",
  login: { logged_in: true, auth_method: "claude.ai", account: "co***@example.com", cli_version: null, error: null },
};

function neverResolves<T>(): Promise<T> {
  return new Promise(() => {});
}

it("role=dialog와 aria-modal을 갖고 첫 버튼에 포커스한다", async () => {
  vi.mocked(api.getStatus).mockResolvedValue(STATUS);
  render(<AiConsentDialog onConfirm={() => {}} onCancel={() => {}} />);
  const dialog = await screen.findByRole("dialog");
  expect(dialog).toHaveAttribute("aria-modal", "true");
  expect(dialog).toHaveAttribute("aria-labelledby");
  await waitFor(() => expect(screen.getByRole("button", { name: "전송에 동의하고 계속" })).toHaveFocus());
});

it("상태 조회 전에는 확인 중을 보인다", () => {
  vi.mocked(api.getStatus).mockReturnValue(neverResolves());
  render(<AiConsentDialog onConfirm={() => {}} onCancel={() => {}} />);
  expect(screen.getByText(/확인 중/)).toBeInTheDocument();
});

it("상태 조회 응답 뒤 제공자와 모델을 표시한다", async () => {
  vi.mocked(api.getStatus).mockResolvedValue(STATUS);
  render(<AiConsentDialog onConfirm={() => {}} onCancel={() => {}} />);
  expect(await screen.findByText(/sonnet/)).toBeInTheDocument();
});

it("전송에 동의하고 계속을 누르면 onConfirm이 불린다", async () => {
  vi.mocked(api.getStatus).mockResolvedValue(STATUS);
  const onConfirm = vi.fn();
  render(<AiConsentDialog onConfirm={onConfirm} onCancel={() => {}} />);
  await userEvent.click(await screen.findByRole("button", { name: "전송에 동의하고 계속" }));
  expect(onConfirm).toHaveBeenCalledTimes(1);
});

it("취소를 누르면 onCancel이 불린다", async () => {
  vi.mocked(api.getStatus).mockResolvedValue(STATUS);
  const onCancel = vi.fn();
  render(<AiConsentDialog onConfirm={() => {}} onCancel={onCancel} />);
  await userEvent.click(await screen.findByRole("button", { name: "취소" }));
  expect(onCancel).toHaveBeenCalledTimes(1);
});

// nit F-5 (B 묶음 최종 리뷰): 상태 조회 실패는 "AI 제공자 확인 실패에게 전송됩니다" 처럼 조사가
// 어색하게 붙는 문장 대신, 실패를 그대로 알리는 별도 문장으로 보여야 한다
it("상태 조회가 실패하면 조사가 어색한 문장 대신 별도 안내를 보여준다", async () => {
  vi.mocked(api.getStatus).mockRejectedValue(new Error("네트워크 오류"));
  render(<AiConsentDialog onConfirm={() => {}} onCancel={() => {}} />);
  expect(await screen.findByText(
    "AI 제공자 정보를 확인하지 못했습니다. 연결 상태를 확인한 뒤 다시 시도해 주세요.",
  )).toBeInTheDocument();
  expect(screen.queryByText(/확인 실패에게/)).toBeNull();
});

it("Escape를 누르면 onCancel이 불린다", async () => {
  vi.mocked(api.getStatus).mockResolvedValue(STATUS);
  const onCancel = vi.fn();
  render(<AiConsentDialog onConfirm={() => {}} onCancel={onCancel} />);
  await screen.findByRole("dialog");
  await userEvent.keyboard("{Escape}");
  expect(onCancel).toHaveBeenCalledTimes(1);
});

// F-2 (B 묶음 최종 리뷰 major): role="dialog" aria-modal="true"만으로는 포커스가 대화 상자 밖으로
// 새는 것을 막지 못한다. 마지막 요소(취소)에서 Tab -> 첫 요소(확인)로, 첫 요소에서 Shift+Tab ->
// 마지막 요소로 순환해야 한다
it("Tab과 Shift+Tab이 대화 상자 안의 포커스 가능 요소 사이에서 순환한다 (F-2)", async () => {
  vi.mocked(api.getStatus).mockResolvedValue(STATUS);
  render(<AiConsentDialog onConfirm={() => {}} onCancel={() => {}} />);
  const confirmBtn = await screen.findByRole("button", { name: "전송에 동의하고 계속" });
  const cancelBtn = screen.getByRole("button", { name: "취소" });
  await waitFor(() => expect(confirmBtn).toHaveFocus());

  await userEvent.tab();
  expect(cancelBtn).toHaveFocus();  // 대화 상자 안의 두 번째(마지막) 요소

  await userEvent.tab();  // 마지막에서 Tab -> 첫 요소로 순환
  expect(confirmBtn).toHaveFocus();

  await userEvent.tab({ shift: true });  // 첫 요소에서 Shift+Tab -> 마지막 요소로 순환
  expect(cancelBtn).toHaveFocus();
});

it("닫힐 때 이전 포커스 요소로 돌아간다", async () => {
  vi.mocked(api.getStatus).mockResolvedValue(STATUS);
  function Wrapper() {
    const [open, setOpen] = useState(false);
    return (
      <div>
        <button onClick={() => setOpen(true)}>열기 버튼</button>
        {open && <AiConsentDialog onConfirm={() => setOpen(false)} onCancel={() => setOpen(false)} />}
      </div>
    );
  }
  render(<Wrapper />);
  // 실제 흐름과 같게 버튼 클릭으로 대화 상자를 연다: 클릭이 먼저 그 버튼에 포커스를 주므로
  // 대화 상자가 마운트될 때 이전 포커스로 그 버튼이 잡힌다
  await userEvent.click(screen.getByRole("button", { name: "열기 버튼" }));
  const opener = screen.getByRole("button", { name: "열기 버튼" });
  await screen.findByRole("dialog");
  await userEvent.click(screen.getByRole("button", { name: "취소" }));
  await waitFor(() => expect(opener).toHaveFocus());
});
