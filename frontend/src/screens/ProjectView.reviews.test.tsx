import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api, ApiError, type ExportHistoryDetail, type ExportResult, type ExportReviews } from "../api/client";
import qualityFixture from "../../../backend/tests/fixtures/q1b1-quality.json";
import { deckWith, deferred, project } from "../test/fixtures";
import { exportReviews } from "../test/reviews";
import { ProjectView } from "./ProjectView";

vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return { ...mod, api: { ...mod.api,
    getDeck: vi.fn(), listSources: vi.fn(), listExports: vi.fn(), getExport: vi.fn(),
    getExportReviews: vi.fn(), recordExportReview: vi.fn(), createSnapshot: vi.fn(), exportDeck: vi.fn(), listSnapshots: vi.fn(),
  } };
});
vi.mock("./AISettingsPanel", () => ({ AISettingsPanel: () => null }));

const item = { id: "report_v001", file_modified_at: "2026-09-29T10:00:00+00:00", record_status: "readable", artifact_status: "matched",
  input_status: "current", quality_status: "draft", slide_count: 2, gate_version: "preflight-v2" } as const;
const context = { checked_at: "2026-09-29T10:00:00+00:00", current_input_fingerprint: "a".repeat(64), current_input_error: null };
const detail: ExportHistoryDetail = { ...context, item, artifact_sha256: "b".repeat(64), quality: null };

beforeEach(() => {
  vi.mocked(api.getDeck).mockResolvedValue(deckWith(["합성 내용"]));
  vi.mocked(api.listSources).mockResolvedValue([]);
  vi.mocked(api.listSnapshots).mockResolvedValue([]);
  vi.mocked(api.listExports).mockResolvedValue({ ...context, items: [item], total: 1, offset: 0, limit: 20 });
  vi.mocked(api.getExport).mockResolvedValue(detail);
  vi.mocked(api.getExportReviews).mockResolvedValue(exportReviews());
  vi.mocked(api.recordExportReview).mockResolvedValue(exportReviews());
});
afterEach(() => { vi.restoreAllMocks(); });

function beforeUnload() {
  const event = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(event);
  return event.defaultPrevented;
}

async function openReview(onBack = vi.fn()) {
  const view = render(<ProjectView project={project} onBack={onBack} />);
  await userEvent.click(await screen.findByRole("button", { name: "검수 이력" }));
  await userEvent.click(await screen.findByRole("button", { name: "report_v001 상세" }));
  await screen.findByLabelText("판단 근거");
  return { ...view, onBack };
}

it.each(["자료", "구조안", "편집", "목록으로", "스냅샷 복구", "초안 PPTX 내보내기", "검수 이력"])(
  "%s 이탈 확인을 취소하면 검수 입력과 beforeunload 보호를 유지한다", async name => {
    const { onBack } = await openReview();
    await userEvent.type(screen.getByLabelText("판단 근거"), "남겨 둘 수동 검수");
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    expect(beforeUnload()).toBe(true);
    await userEvent.click(screen.getByRole("button", { name }));
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(screen.getByLabelText("판단 근거")).toHaveValue("남겨 둘 수동 검수");
    expect(screen.getByRole("button", { name: "검수 이력" })).toHaveAttribute("aria-pressed", "true");
    expect(beforeUnload()).toBe(true);
    expect(api.createSnapshot).not.toHaveBeenCalled();
    expect(api.exportDeck).not.toHaveBeenCalled();
    expect(onBack).not.toHaveBeenCalled();
  },
);

it("검수 입력을 버리는 이탈을 확인하면 이동하고 dirty 상태를 해제한다", async () => {
  await openReview();
  await userEvent.type(screen.getByLabelText("판단 근거"), "버리기로 확인한 입력");
  vi.spyOn(window, "confirm").mockReturnValue(true);
  await userEvent.click(screen.getByRole("button", { name: "자료" }));
  expect(await screen.findByLabelText("보고서 제목")).toBeInTheDocument();
  expect(screen.queryByLabelText("판단 근거")).toBeNull();
  expect(beforeUnload()).toBe(false);
});

it("수동 검수 저장 중에는 프로젝트 이탈을 차단하고 완료 뒤에는 보호를 해제한다", async () => {
  const pending = deferred<ExportReviews>();
  vi.mocked(api.recordExportReview).mockReturnValue(pending.promise);
  const { onBack } = await openReview();
  await userEvent.selectOptions(screen.getByLabelText("검수 항목"), "visual");
  await userEvent.selectOptions(screen.getByLabelText("판정"), "needs_revision");
  await userEvent.type(screen.getByLabelText("검수자"), "합성 검수자");
  await userEvent.type(screen.getByLabelText("판단 근거"), "합성 저장 대기");
  await userEvent.click(screen.getByRole("checkbox", { name: "1페이지 확인" }));
  await userEvent.click(screen.getByRole("button", { name: "검수 기록 저장" }));
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
  await userEvent.click(screen.getByRole("button", { name: "목록으로" }));
  expect(confirm).not.toHaveBeenCalled();
  expect(onBack).not.toHaveBeenCalled();
  expect(beforeUnload()).toBe(true);
  await act(async () => pending.resolve(exportReviews()));
  await waitFor(() => expect(beforeUnload()).toBe(false));
  await userEvent.click(screen.getByRole("button", { name: "목록으로" }));
  expect(onBack).toHaveBeenCalledTimes(1);
});

it.each(["recovery", "deck_failure"])("%s 화면의 이력은 명시적으로 읽기 전용이다", async mode => {
  if (mode === "deck_failure") vi.mocked(api.getDeck).mockRejectedValue(new ApiError(500, "덱 읽기 실패"));
  render(<ProjectView project={mode === "recovery" ? { ...project, status: "needs_recovery" } : project} onBack={vi.fn()} />);
  await userEvent.click(await screen.findByRole("button", { name: "report_v001 상세" }));
  expect(await screen.findByText("프로젝트를 정상적으로 열어야 새 검수 기록을 입력할 수 있습니다.")).toBeInTheDocument();
  expect(screen.queryByLabelText("검수자")).toBeNull();
  expect(screen.queryByRole("button", { name: "검수 기록 저장" })).toBeNull();
});

it.each(["snapshot", "export"])("%s 대기 중 새 검수 입력이 내보내기 완료로 유실되지 않는다", async phase => {
  const snapshot = deferred<{ ok: boolean }>();
  const exported = deferred<ExportResult>();
  vi.mocked(api.createSnapshot).mockReturnValue(phase === "snapshot" ? snapshot.promise : Promise.resolve({ ok: true }));
  vi.mocked(api.exportDeck).mockReturnValue(exported.promise);
  await openReview();
  await userEvent.click(screen.getByRole("button", { name: "초안 PPTX 내보내기" }));
  await waitFor(() => expect(phase === "snapshot" ? api.createSnapshot : api.exportDeck).toHaveBeenCalledTimes(1));
  const note = screen.getByLabelText("판단 근거");
  expect(note).toBeDisabled();
  expect(screen.getByLabelText("검수 항목")).toBeDisabled();
  expect(screen.getByRole("checkbox", { name: "1페이지 확인" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "검수 기준 다시 확인" })).toBeDisabled();
  await userEvent.type(note, "대기 중 새 입력");
  expect(note).toHaveValue("");
  await act(async () => snapshot.resolve({ ok: true }));
  await act(async () => exported.resolve({ path: "/exports/report_v002.pptx", quality_path: "/exports/report_v002.quality.json", quality: qualityFixture.matched } as ExportResult));
  await waitFor(() => expect(api.listExports).toHaveBeenCalledTimes(2));
});

it("내보내기 중 늦게 열린 검수 화면은 내보내기 실패 후에도 기준을 읽고 입력할 수 있다", async () => {
  const pendingDetail = deferred<ExportHistoryDetail>();
  const exported = deferred<ExportResult>();
  vi.mocked(api.getExport).mockReturnValue(pendingDetail.promise);
  vi.mocked(api.createSnapshot).mockResolvedValue({ ok: true });
  vi.mocked(api.exportDeck).mockReturnValue(exported.promise);
  render(<ProjectView project={project} onBack={vi.fn()} />);
  await userEvent.click(await screen.findByRole("button", { name: "검수 이력" }));
  await userEvent.click(await screen.findByRole("button", { name: "report_v001 상세" }));
  await userEvent.click(screen.getByRole("button", { name: "초안 PPTX 내보내기" }));
  await waitFor(() => expect(api.exportDeck).toHaveBeenCalledTimes(1));
  await act(async () => pendingDetail.resolve(detail));
  expect(screen.getByRole("button", { name: "검수 기준 다시 확인" })).toBeDisabled();
  await act(async () => exported.reject(new ApiError(500, "합성 내보내기 실패")));
  await screen.findByText(/합성 내보내기 실패/);
  await waitFor(() => expect(api.getExportReviews).toHaveBeenCalledTimes(1));
  expect(await screen.findByLabelText("판단 근거")).not.toBeDisabled();
  expect(screen.getByRole("button", { name: "검수 기준 다시 확인" })).not.toBeDisabled();
});
