import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api, ApiError } from "../api/client";
import { RecoveryScreen } from "./RecoveryScreen";

vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return { ...mod, api: { ...mod.api, listSnapshots: vi.fn(), restoreSnapshot: vi.fn() } };
});

const project = { name: "p1", title: "제목", updated_at: "", status: "needs_recovery" as const };

it("스냅샷 목록을 보여주고 확인 후 복원한다", async () => {
  vi.mocked(api.listSnapshots).mockResolvedValue([
    { id: "deck-20260829-100000-000001", saved_at: "2026-08-29T10:00:00+09:00" }]);
  vi.mocked(api.restoreSnapshot).mockResolvedValue({} as never);
  vi.spyOn(window, "confirm").mockReturnValue(true);
  const onBack = vi.fn();
  render(<RecoveryScreen project={project} onBack={onBack} />);
  await userEvent.click(await screen.findByText("이 시점으로 복원"));
  expect(api.restoreSnapshot).toHaveBeenCalledWith("p1", "deck-20260829-100000-000001");
  expect(onBack).toHaveBeenCalled();
});

it("확인을 취소하면 복원하지 않는다", async () => {
  vi.mocked(api.listSnapshots).mockResolvedValue([
    { id: "deck-20260829-100000-000001", saved_at: "2026-08-29T10:00:00+09:00" }]);
  vi.spyOn(window, "confirm").mockReturnValue(false);
  render(<RecoveryScreen project={project} onBack={() => {}} />);
  await userEvent.click(await screen.findByText("이 시점으로 복원"));
  expect(api.restoreSnapshot).not.toHaveBeenCalled();
});

it("복원이 412면 onConflict를 부르고 목록으로 돌아가지 않는다 (A5)", async () => {
  vi.mocked(api.listSnapshots).mockResolvedValue([
    { id: "deck-20260829-100000-000001", saved_at: "2026-08-29T10:00:00+09:00" }]);
  vi.mocked(api.restoreSnapshot).mockRejectedValue(
    new ApiError(412, "다른 창이나 프로그램에서 이 프로젝트가 먼저 저장되었습니다."));
  vi.spyOn(window, "confirm").mockReturnValue(true);
  const onBack = vi.fn();
  const onConflict = vi.fn();
  render(<RecoveryScreen project={project} onBack={onBack} onConflict={onConflict} />);
  await userEvent.click(await screen.findByText("이 시점으로 복원"));
  await waitFor(() => expect(onConflict).toHaveBeenCalled());
  expect(onBack).not.toHaveBeenCalled();
});
