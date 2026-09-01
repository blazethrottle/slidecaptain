import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api, type AppStatus } from "../api/client";
import { ProjectList } from "./ProjectList";

vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return { ...mod, api: { ...mod.api, listProjects: vi.fn(), createProject: vi.fn(), getStatus: vi.fn() } };
});

const LOGGED_IN: AppStatus = {
  provider: "subscription",
  login: { logged_in: true, auth_method: "claude.ai", account: "co***@example.com", cli_version: null, error: null },
  model: "sonnet",
  last_generation_at: null,
  checked_at: "2026-09-01T09:50:00+09:00",
};

beforeEach(() => {
  vi.mocked(api.getStatus).mockResolvedValue(LOGGED_IN);
});

it("프로젝트 목록과 복구 필요 표지를 보여준다", async () => {
  vi.mocked(api.listProjects).mockResolvedValue([
    { name: "p1", title: "주간 보고", updated_at: "", status: "ok" },
    { name: "p2", title: "(deck.json 없음: 스냅샷 복구가 필요합니다)", updated_at: "", status: "needs_recovery" },
  ]);
  render(<ProjectList onOpen={() => {}} />);
  expect(await screen.findByText("주간 보고")).toBeInTheDocument();
  expect(screen.getByText("복구 필요")).toBeInTheDocument();
});

it("새 프로젝트를 만들고 연다", async () => {
  vi.mocked(api.listProjects).mockResolvedValue([]);
  vi.mocked(api.createProject).mockResolvedValue(
    { name: "새보고", title: "새보고", updated_at: "", status: "ok" });
  const onOpen = vi.fn();
  render(<ProjectList onOpen={onOpen} />);
  await userEvent.type(screen.getByLabelText("프로젝트 이름"), "새보고");
  await userEvent.click(screen.getByText("만들기"));
  expect(onOpen).toHaveBeenCalledWith(expect.objectContaining({ name: "새보고" }));
});

it("만들기 실패의 안내 문구를 보여준다", async () => {
  vi.mocked(api.listProjects).mockResolvedValue([]);
  const { ApiError } = await import("../api/client");
  vi.mocked(api.createProject).mockRejectedValue(new ApiError(409, "같은 이름의 프로젝트가 이미 있습니다: p1"));
  render(<ProjectList onOpen={() => {}} />);
  await userEvent.type(screen.getByLabelText("프로젝트 이름"), "p1");
  await userEvent.click(screen.getByText("만들기"));
  expect(await screen.findByRole("alert")).toHaveTextContent("이미 있습니다");
});

describe("AI 연결 상태 한 줄", () => {
  beforeEach(() => {
    vi.mocked(api.listProjects).mockResolvedValue([]);
  });

  it("로그인됨이면 방식, 가린 계정, 마지막 생성 성공 시각을 보여준다", async () => {
    vi.mocked(api.getStatus).mockResolvedValue({ ...LOGGED_IN, last_generation_at: "2026-09-01T09:52:10+09:00" });
    render(<ProjectList onOpen={() => {}} />);
    expect(await screen.findByText(
      "AI 연결: 로그인됨 (claude.ai, co***@example.com). 마지막 생성 성공: 2026-09-01 09:52",
    )).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("생성 이력이 없으면 아직 없음으로 표시한다", async () => {
    render(<ProjectList onOpen={() => {}} />);
    expect(await screen.findByText(/마지막 생성 성공: 아직 없음/)).toBeInTheDocument();
  });

  it("로그인되지 않았으면 로그인 후 재실행 안내를 보여준다", async () => {
    vi.mocked(api.getStatus).mockResolvedValue({
      ...LOGGED_IN, login: { logged_in: false, auth_method: null, account: null, cli_version: null, error: null },
    });
    render(<ProjectList onOpen={() => {}} />);
    const line = await screen.findByText(/로그인되지 않았습니다/);
    expect(line).toHaveTextContent("SlideCaptain실행.bat");
  });

  it("확인하지 못하면 사유와 CLI 버전을 함께 보여준다", async () => {
    vi.mocked(api.getStatus).mockResolvedValue({
      ...LOGGED_IN,
      login: { logged_in: null, auth_method: null, account: null, cli_version: "2.1.247",
        error: "Claude CLI의 응답을 해석하지 못했습니다(종료 코드 1)" },
    });
    render(<ProjectList onOpen={() => {}} />);
    const line = await screen.findByText(/AI 연결: 확인하지 못했습니다/);
    expect(line).toHaveTextContent("응답을 해석하지 못했습니다");
    expect(line).toHaveTextContent("2.1.247");
  });

  it("상태 조회가 실패해도 목록은 보이고 별도 문구만 남긴다", async () => {
    vi.mocked(api.listProjects).mockResolvedValue([{ name: "p1", title: "주간 보고", updated_at: "", status: "ok" }]);
    vi.mocked(api.getStatus).mockRejectedValue(new Error("network"));
    render(<ProjectList onOpen={() => {}} />);
    expect(await screen.findByText("주간 보고")).toBeInTheDocument();
    expect(await screen.findByText("AI 연결 상태를 불러오지 못했습니다.")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
