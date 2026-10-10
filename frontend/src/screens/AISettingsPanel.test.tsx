import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api, type AISettings } from "../api/client";
import { AISettingsPanel } from "./AISettingsPanel";

vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return { ...mod, api: { ...mod.api, getAISettings: vi.fn(), selectAI: vi.fn(), startAILogin: vi.fn(), getAILogin: vi.fn(), cancelAILogin: vi.fn() } };
});

const settings: AISettings = {
  selection: { provider: "claude", model: "sonnet" }, selection_id: "one", busy: false,
  providers: [
    { id: "claude", label: "Claude", login: { logged_in: true, account: "te***@example.com" },
      models: [{ id: "sonnet", label: "Sonnet" }], login_attempt: { state: "idle", message: "" } },
    { id: "chatgpt", label: "ChatGPT", login: { logged_in: false },
      models: [{ id: "gpt-test", label: "GPT Test" }], login_attempt: { state: "idle", message: "" } },
  ],
};

beforeEach(() => { vi.mocked(api.getAISettings).mockResolvedValue(settings); });

it("서비스를 바꾸면 해당 모델만 표시하고 저장한다", async () => {
  vi.mocked(api.selectAI).mockResolvedValue({ provider: "chatgpt", model: "gpt-test" });
  render(<AISettingsPanel />);
  await userEvent.click(screen.getByRole("button", { name: "AI 연결 및 모델" }));
  await screen.findByLabelText("AI 서비스");
  await userEvent.selectOptions(screen.getByLabelText("AI 서비스"), "chatgpt");
  expect(screen.getByLabelText("언어모델")).toHaveValue("gpt-test");
  expect(screen.queryByRole("option", { name: "Sonnet" })).toBeNull();
  await userEvent.click(screen.getByRole("button", { name: "선택 저장" }));
  expect(api.selectAI).toHaveBeenCalledWith({ provider: "chatgpt", model: "gpt-test" });
  expect(await screen.findByText(/다음 생성부터 적용/)).toBeInTheDocument();
});

it("로그인 대기 링크와 취소를 표시하고 로그인 성공으로 오인하지 않는다", async () => {
  vi.mocked(api.startAILogin).mockResolvedValue({ state: "pending", auth_url: "https://auth.openai.com/authorize?state=test", message: "로그인 대기 중" });
  vi.mocked(api.cancelAILogin).mockResolvedValue({ state: "cancelled", message: "로그인 대기를 취소했습니다." });
  render(<AISettingsPanel />);
  await userEvent.click(screen.getByRole("button", { name: "AI 연결 및 모델" }));
  await screen.findByLabelText("AI 서비스");
  await userEvent.selectOptions(screen.getByLabelText("AI 서비스"), "chatgpt");
  await userEvent.click(screen.getByRole("button", { name: "로그인 시작" }));
  expect(await screen.findByRole("link", { name: "공식 로그인 페이지 열기" })).toHaveAttribute("rel", "noopener noreferrer");
  expect(screen.getByText("로그인 대기 중")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "로그인 대기 취소" }));
  expect(await screen.findByText("로그인 대기를 취소했습니다.")).toBeInTheDocument();
  expect(api.cancelAILogin).toHaveBeenCalledWith("chatgpt");
});

it("모델 조회 실패 시 임의 모델을 저장하지 못한다", async () => {
  vi.mocked(api.getAISettings).mockResolvedValue({ ...settings, providers: [settings.providers[0],
    { ...settings.providers[1], models: [], models_error: "Codex 설치가 필요합니다." }] });
  render(<AISettingsPanel />);
  await userEvent.click(screen.getByRole("button", { name: "AI 연결 및 모델" }));
  await screen.findByLabelText("AI 서비스");
  await userEvent.selectOptions(screen.getByLabelText("AI 서비스"), "chatgpt");
  expect(screen.getByText("Codex 설치가 필요합니다.")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "선택 저장" })).toBeDisabled();
});

it("열기 전 조회하지 않고 생성 중에는 설정을 열 수 없다", async () => {
  vi.mocked(api.getAISettings).mockClear();
  render(<AISettingsPanel disabled />);
  expect(screen.getByRole("button", { name: "AI 연결 및 모델" })).toBeDisabled();
  await waitFor(() => expect(api.getAISettings).not.toHaveBeenCalled());
});

function withLuna(selection = settings.selection): AISettings {
  return { ...settings, selection, providers: [settings.providers[0], {
    ...settings.providers[1], models: [
      { id: "gpt-6-sol", label: "GPT-6-Sol" },
      { id: "gpt-6-luna", label: "GPT-6-Luna" },
    ],
  }] };
}

it("Codex LUNA 빠른 선택은 명시적 저장 전에는 적용하지 않는다", async () => {
  vi.mocked(api.getAISettings).mockResolvedValue(withLuna());
  vi.mocked(api.selectAI).mockClear();
  render(<AISettingsPanel />);
  await userEvent.click(screen.getByRole("button", { name: "AI 연결 및 모델" }));
  await userEvent.click(await screen.findByRole("button", { name: "Codex LUNA" }));
  expect(screen.getByLabelText("AI 서비스")).toHaveValue("chatgpt");
  expect(screen.getByLabelText("언어모델")).toHaveValue("gpt-6-luna");
  expect(api.selectAI).not.toHaveBeenCalled();
  expect(screen.getByText("현재 적용: Claude / sonnet")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Codex LUNA" })).toHaveAttribute("aria-pressed", "true");
  vi.mocked(api.getAISettings).mockResolvedValue(withLuna({ provider: "chatgpt", model: "gpt-6-luna" }));
  await userEvent.click(screen.getByRole("button", { name: "선택 저장" }));
  expect(api.selectAI).toHaveBeenCalledWith({ provider: "chatgpt", model: "gpt-6-luna" });
  expect(await screen.findByText(/다음 생성부터 적용/)).toBeInTheDocument();
});

it("저장된 LUNA 선택을 유지하고 Claude Sonnet으로 직접 바꿀 수 있다", async () => {
  vi.mocked(api.getAISettings).mockResolvedValue(withLuna({ provider: "chatgpt", model: "gpt-6-luna" }));
  render(<AISettingsPanel />);
  await userEvent.click(screen.getByRole("button", { name: "AI 연결 및 모델" }));
  expect(await screen.findByRole("button", { name: "Codex LUNA" })).toHaveAttribute("aria-pressed", "true");
  await userEvent.click(screen.getByRole("button", { name: "Claude Sonnet" }));
  expect(screen.getByLabelText("AI 서비스")).toHaveValue("claude");
  expect(screen.getByLabelText("언어모델")).toHaveValue("sonnet");
});

it("실제 모델 목록에 LUNA가 없으면 빠른 선택을 차단하고 이유를 표시한다", async () => {
  render(<AISettingsPanel />);
  await userEvent.click(screen.getByRole("button", { name: "AI 연결 및 모델" }));
  expect(await screen.findByRole("button", { name: "Codex LUNA" })).toBeDisabled();
  expect(screen.getByText(/Codex 모델 목록에서 LUNA를 찾지 못했습니다/)).toBeInTheDocument();
  expect(screen.getByLabelText("언어모델")).toHaveValue("sonnet");
});

it("생성 중에는 두 모델의 빠른 선택을 잠근다", async () => {
  vi.mocked(api.getAISettings).mockResolvedValue({ ...withLuna(), busy: true });
  render(<AISettingsPanel />);
  await userEvent.click(screen.getByRole("button", { name: "AI 연결 및 모델" }));
  expect(await screen.findByRole("button", { name: "Codex LUNA" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Claude Sonnet" })).toBeDisabled();
});

it("열린 설정은 Esc로 닫히고 초점이 여닫기 버튼으로 돌아온다 (D3a-2 리뷰 R7)", async () => {
  render(<AISettingsPanel />);
  const toggle = screen.getByRole("button", { name: "AI 연결 및 모델" });
  await userEvent.click(toggle);
  expect(toggle).toHaveAttribute("aria-expanded", "true");
  await screen.findByRole("heading", { name: "AI 연결" });
  await userEvent.keyboard("{Escape}");
  expect(toggle).toHaveAttribute("aria-expanded", "false");
  expect(document.activeElement).toBe(toggle);
});
