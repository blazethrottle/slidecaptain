import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api, ApiError } from "../api/client";
import { RecoveryScreen } from "./RecoveryScreen";

vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return { ...mod, api: { ...mod.api, listSnapshots: vi.fn(), restoreSnapshot: vi.fn(),
    listDrafts: vi.fn(), restoreDraft: vi.fn(), deleteDraft: vi.fn() } };
});

const project = { name: "p1", title: "제목", updated_at: "", status: "needs_recovery" as const };

beforeEach(() => { vi.mocked(api.listDrafts).mockResolvedValue([]); });

it("스냅샷 목록을 보여주고 확인 후 복원한다", async () => {
  vi.mocked(api.listSnapshots).mockResolvedValue([
    { id: "deck-20260829-100000-000001", saved_at: "2026-08-29T10:00:00+09:00", kind: "snapshot" }]);
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
    { id: "deck-20260829-100000-000001", saved_at: "2026-08-29T10:00:00+09:00", kind: "snapshot" }]);
  vi.spyOn(window, "confirm").mockReturnValue(false);
  render(<RecoveryScreen project={project} onBack={() => {}} />);
  await userEvent.click(await screen.findByText("이 시점으로 복원"));
  expect(api.restoreSnapshot).not.toHaveBeenCalled();
});

it("복원이 412면 onConflict를 부르고 목록으로 돌아가지 않는다 (A5)", async () => {
  vi.mocked(api.listSnapshots).mockResolvedValue([
    { id: "deck-20260829-100000-000001", saved_at: "2026-08-29T10:00:00+09:00", kind: "snapshot" }]);
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

it("새 형식으로 바꾸기 전 복사본을 구별해 보인다 (D2a-1)", async () => {
  vi.mocked(api.listSnapshots).mockResolvedValue([
    { id: "deck-20260829-100000-000001", saved_at: "2026-08-29T10:00:00+09:00", kind: "pre_migration" },
    { id: "deck-20260829-110000-000001", saved_at: "2026-08-29T11:00:00+09:00", kind: "snapshot" },
  ]);
  render(<RecoveryScreen project={project} onBack={() => {}} />);
  const items = await screen.findAllByRole("listitem");
  expect(items[0]).not.toHaveTextContent("새 형식으로 바꾸기 전");  // 최신이 위로
  expect(items[1]).toHaveTextContent("새 형식으로 바꾸기 전");
});


const draft = { id: "draft-20261008-100000-000001", saved_at: "2026-10-08T10:00:00+09:00",
  reason: "generation_unsaved" as const, source: "structure_approval" as const, base_etag: null };

it("보존한 변경은 스냅샷과 별도 목록에 사유와 출처를 보인다 (D2a-2)", async () => {
  vi.mocked(api.listSnapshots).mockResolvedValue([]);
  vi.mocked(api.listDrafts).mockResolvedValue([draft]);
  render(<RecoveryScreen project={project} onBack={() => {}} />);
  const section = (await screen.findByRole("heading", { name: "충돌로 보존한 변경" })).closest("section")!;
  expect(section).toHaveTextContent("저장하지 못한 생성 결과");
  expect(section).toHaveTextContent("구조안 승인");
});

it("보존한 변경의 복원은 현재 저장본이 스냅샷으로 남는다는 확인 뒤에 한다 (D2a-2)", async () => {
  vi.mocked(api.listSnapshots).mockResolvedValue([]);
  vi.mocked(api.listDrafts).mockResolvedValue([draft]);
  vi.mocked(api.restoreDraft).mockResolvedValue({} as never);
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
  const onBack = vi.fn();
  render(<RecoveryScreen project={project} onBack={onBack} />);
  await userEvent.click(await screen.findByRole("button", { name: "이 변경으로 복원" }));
  expect(confirm.mock.calls[0][0]).toContain("복원 직전 시점의 스냅샷으로 남습니다");
  expect(api.restoreDraft).toHaveBeenCalledWith("p1", draft.id);
  expect(onBack).toHaveBeenCalled();
});

it("보존한 변경은 확인 뒤 고른 것만 지운다 (D2a-2)", async () => {
  vi.mocked(api.listSnapshots).mockResolvedValue([]);
  vi.mocked(api.listDrafts).mockResolvedValueOnce([draft]).mockResolvedValueOnce([]);
  vi.mocked(api.deleteDraft).mockResolvedValue({ ok: true });
  vi.spyOn(window, "confirm").mockReturnValue(true);
  render(<RecoveryScreen project={project} onBack={() => {}} />);
  await userEvent.click(await screen.findByRole("button", { name: "이 보존본 지우기" }));
  expect(api.deleteDraft).toHaveBeenCalledWith("p1", draft.id);
  expect(await screen.findByText("보존한 변경이 없습니다.")).toBeInTheDocument();
});

it("보존 목록을 읽지 못해도 스냅샷 목록은 보인다 (D2a-2)", async () => {
  vi.mocked(api.listSnapshots).mockResolvedValue([
    { id: "deck-20260829-100000-000001", saved_at: "2026-08-29T10:00:00+09:00", kind: "snapshot" }]);
  vi.mocked(api.listDrafts).mockRejectedValue(new Error("읽기 실패"));
  render(<RecoveryScreen project={project} onBack={() => {}} />);
  expect(await screen.findByText("이 시점으로 복원")).toBeInTheDocument();
  expect(await screen.findByText(/보존한 변경 목록을 읽지 못했습니다/)).toBeInTheDocument();
});


it("승인하려던 장 구성은 내용 생성 전임을 알리고, 모르는 사유도 목록에 보인다 (리뷰 R5, R12)", async () => {
  vi.mocked(api.listSnapshots).mockResolvedValue([]);
  vi.mocked(api.listDrafts).mockResolvedValue([
    { ...draft, id: "draft-20261008-100000-000002", reason: "conflict", source: "structure_approval" },
    { ...draft, id: "draft-20261008-100000-000003", reason: "later_reason", source: "editor" },
  ]);
  render(<RecoveryScreen project={project} onBack={() => {}} />);
  const section = (await screen.findByRole("heading", { name: "충돌로 보존한 변경" })).closest("section")!;
  expect(section).toHaveTextContent("승인하려던 장 구성(내용 생성 전)");
  expect(section).toHaveTextContent("알 수 없는 사유(later_reason)");
  expect(section).toHaveTextContent("2026-10-08 10:00");
  expect(section).toHaveTextContent("복원 직전 시점의 스냅샷으로 남습니다");
});
