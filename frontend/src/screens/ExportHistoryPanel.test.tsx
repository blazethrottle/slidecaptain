import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import fixture from "../../../backend/tests/fixtures/q1b1-quality.json";
import { api, ApiError, type ExportHistoryDetail, type ExportHistoryPage, type QualityReport } from "../api/client";
import { deferred } from "../test/fixtures";
import { exportReviews } from "../test/reviews";
import { ExportHistoryPanel } from "./ExportHistoryPanel";
import type { ReviewLeaveGuard } from "./ReviewRecordsPanel";

vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return { ...mod, api: { ...mod.api, listExports: vi.fn(), getExport: vi.fn(), getExportReviews: vi.fn(), recordExportReview: vi.fn() } };
});

const item = {
  id: "report_v001", file_modified_at: "2026-09-13T10:00:00+00:00",
  record_status: "readable", artifact_status: "matched", input_status: "current",
  quality_status: "draft", slide_count: 1, gate_version: "preflight-v2",
} as const;
const context = {
  checked_at: "2026-09-13T11:00:00+00:00", current_input_fingerprint: "a".repeat(64), current_input_error: null,
};
function page(): ExportHistoryPage {
  return { ...context, items: [item], total: 1, offset: 0, limit: 20 };
}
function detail(): ExportHistoryDetail {
  return { ...context, item, artifact_sha256: "b".repeat(64), quality: fixture.matched as QualityReport };
}
beforeEach(() => {
  vi.mocked(api.listExports).mockResolvedValue(page());
  vi.mocked(api.getExport).mockResolvedValue(detail());
  vi.mocked(api.getExportReviews).mockResolvedValue(exportReviews());
});
afterEach(() => { vi.restoreAllMocks(); });

it("shows independent current input and artifact matches without submission approval", async () => {
  render(<ExportHistoryPanel projectName="p1" />);
  await userEvent.click(await screen.findByRole("button", { name: "report_v001 상세" }));
  const region = await screen.findByRole("region", { name: "저장 당시 점검 결과" });
  expect(region).toHaveTextContent("계산 문구");
  expect(region).toHaveTextContent("검수 전 초안");
  expect(screen.getByRole("region", { name: "내보내기 검수 이력" })).toHaveTextContent("현재 저장본과 일치");
  expect(screen.getByRole("region", { name: "내보내기 검수 이력" })).toHaveTextContent("PPTX 일치");
  expect(screen.queryByText(/초안 내보내기 완료/)).not.toBeInTheDocument();
  expect(screen.queryByText(/^제출 가능$/)).not.toBeInTheDocument();
});

it("keeps missing PPTX and stale input visible alongside the historical result", async () => {
  const data = detail();
  data.item = { ...item, artifact_status: "missing", input_status: "stale" };
  vi.mocked(api.getExport).mockResolvedValue(data);
  render(<ExportHistoryPanel projectName="p1" />);
  await userEvent.click(await screen.findByRole("button", { name: "report_v001 상세" }));
  const panel = await screen.findByRole("region", { name: "내보내기 이력 상세" });
  expect(panel).toHaveTextContent("PPTX 없음");
  expect(panel).toHaveTextContent("현재 저장본과 다름");
  expect(within(panel).getByRole("region", { name: "저장 당시 점검 결과" })).toBeInTheDocument();
  expect(panel).not.toHaveTextContent("내보내기 완료");
});

it("shows corrupt records without fabricating stored checks", async () => {
  const data = detail();
  data.item = { ...item, record_status: "invalid", input_status: "unavailable", artifact_status: "unverified" };
  data.quality = null;
  vi.mocked(api.getExport).mockResolvedValue(data);
  render(<ExportHistoryPanel projectName="p1" />);
  await userEvent.click(await screen.findByRole("button", { name: "report_v001 상세" }));
  expect(await screen.findByRole("region", { name: "내보내기 이력 상세" })).toHaveTextContent("기록 손상");
  expect(screen.queryByRole("region", { name: "저장 당시 점검 결과" })).toBeNull();
});

it("clears previous matches while refreshing and keeps refresh failures visible", async () => {
  render(<ExportHistoryPanel projectName="p1" />);
  await userEvent.click(await screen.findByRole("button", { name: "report_v001 상세" }));
  await screen.findByRole("region", { name: "저장 당시 점검 결과" });
  const pending = deferred<ExportHistoryPage>();
  vi.mocked(api.listExports).mockReturnValue(pending.promise);
  await userEvent.click(screen.getByRole("button", { name: "이력 새로고침" }));
  expect(screen.queryByText("현재 저장본과 일치")).toBeNull();
  expect(screen.queryByRole("region", { name: "저장 당시 점검 결과" })).toBeNull();
  await act(async () => pending.reject(new ApiError(422, "출력 폴더를 읽지 못했습니다.")));
  expect(await screen.findByRole("alert")).toHaveTextContent("출력 폴더를 읽지 못했습니다.");
  expect(screen.queryByText(/이력이 없습니다/)).toBeNull();
});

it("ignores a late detail response after selecting another file", async () => {
  const listing = page();
  listing.items.push({ ...item, id: "report_v002" }); listing.total = 2;
  vi.mocked(api.listExports).mockResolvedValue(listing);
  const first = deferred<ExportHistoryDetail>();
  vi.mocked(api.getExport).mockReturnValueOnce(first.promise).mockResolvedValue({ ...detail(), item: { ...item, id: "report_v002" } });
  render(<ExportHistoryPanel projectName="p1" />);
  await userEvent.click(await screen.findByRole("button", { name: "report_v001 상세" }));
  await userEvent.click(screen.getByRole("button", { name: "report_v002 상세" }));
  await waitFor(() => expect(screen.getByRole("region", { name: "내보내기 이력 상세" })).toHaveTextContent("report_v002"));
  await act(async () => first.resolve(detail()));
  expect(screen.getByRole("region", { name: "내보내기 이력 상세" })).toHaveTextContent("report_v002");
  expect(screen.getByRole("region", { name: "내보내기 이력 상세" })).not.toHaveTextContent("report_v001");
});

it("resets page and ignores late responses when the project changes", async () => {
  const first = deferred<ExportHistoryPage>();
  vi.mocked(api.listExports).mockReturnValueOnce(first.promise).mockResolvedValue({ ...page(), items: [], total: 0 });
  const view = render(<ExportHistoryPanel projectName="old" />);
  view.rerender(<ExportHistoryPanel projectName="new" />);
  expect(await screen.findByText("내보내기 이력이 없습니다.")).toBeInTheDocument();
  await act(async () => first.resolve(page()));
  expect(screen.queryByRole("button", { name: "report_v001 상세" })).toBeNull();
  expect(api.listExports).toHaveBeenLastCalledWith("new", 0, 20);
});

it("offers pagination and never labels file modification time as export time", async () => {
  vi.mocked(api.listExports).mockResolvedValueOnce({ ...page(), total: 21 }).mockResolvedValue({ ...page(), offset: 20, total: 21 });
  render(<ExportHistoryPanel projectName="p1" />);
  await screen.findByRole("button", { name: "report_v001 상세" });
  expect(screen.getByText(/파일 수정 시각/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "다음 이력" }));
  await waitFor(() => expect(api.listExports).toHaveBeenLastCalledWith("p1", 20, 20));
});

it("이력 선택, 페이지 이동과 새로고침은 작성 중인 검수 입력을 버리기 전에 확인한다", async () => {
  vi.mocked(api.listExports).mockResolvedValue({ ...page(), total: 21, items: [item, { ...item, id: "report_v002" }] });
  render(<ExportHistoryPanel projectName="p1" />);
  await userEvent.click(await screen.findByRole("button", { name: "report_v001 상세" }));
  await userEvent.type(await screen.findByLabelText("판단 근거"), "남겨 둘 검수 입력");
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
  for (const name of ["report_v002 상세", "다음 이력", "이력 새로고침"]) {
    await userEvent.click(screen.getByRole("button", { name }));
    expect(screen.getByLabelText("판단 근거")).toHaveValue("남겨 둘 검수 입력");
  }
  expect(confirm).toHaveBeenCalledTimes(3);
  expect(api.listExports).toHaveBeenCalledTimes(1);
  expect(api.getExport).toHaveBeenCalledTimes(1);
  confirm.mockReturnValue(true);
  await userEvent.click(screen.getByRole("button", { name: "report_v002 상세" }));
  expect(api.getExport).toHaveBeenLastCalledWith("p1", "report_v002");
  expect(await screen.findByLabelText("판단 근거")).toHaveValue("");
});

it("이력 화면이 부모 이탈 관문과 dirty 상태를 연결하고 언마운트 때 해제한다", async () => {
  let leave: ReviewLeaveGuard | null = null;
  const ready = vi.fn((guard: ReviewLeaveGuard | null) => { leave = guard; });
  const dirty = vi.fn();
  const view = render(<ExportHistoryPanel projectName="p1" onScreenReady={ready} onDirtyChange={dirty} />);
  await userEvent.click(await screen.findByRole("button", { name: "report_v001 상세" }));
  await userEvent.type(await screen.findByLabelText("판단 근거"), "보존");
  expect(dirty).toHaveBeenLastCalledWith(true);
  view.rerender(<ExportHistoryPanel projectName="p1" onScreenReady={guard => ready(guard)} onDirtyChange={value => dirty(value)} />);
  vi.spyOn(window, "confirm").mockReturnValue(false);
  await act(async () => expect(await leave!()).toBe(false));
  expect(dirty).toHaveBeenLastCalledWith(true);
  view.unmount();
  expect(ready).toHaveBeenLastCalledWith(null);
  expect(dirty).toHaveBeenLastCalledWith(false);
});
