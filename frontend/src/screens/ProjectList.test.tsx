import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api } from "../api/client";
import { ProjectList } from "./ProjectList";

vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return { ...mod, api: { ...mod.api, listProjects: vi.fn(), createProject: vi.fn() } };
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
