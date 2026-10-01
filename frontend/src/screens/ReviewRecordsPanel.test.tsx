import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api, ApiError, type ExportReviews } from "../api/client";
import { deferred } from "../test/fixtures";
import { exportReviews, reviewRecord } from "../test/reviews";
import { ReviewRecordsPanel, type ReviewLeaveGuard } from "./ReviewRecordsPanel";

vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return { ...mod, api: { ...mod.api, getExportReviews: vi.fn(), recordExportReview: vi.fn() } };
});

beforeEach(() => {
  vi.mocked(api.getExportReviews).mockResolvedValue(exportReviews());
  vi.mocked(api.recordExportReview).mockResolvedValue(exportReviews({ storage_status: "readable", records: [reviewRecord()] }));
});
afterEach(() => { vi.restoreAllMocks(); });

async function fillReview(status: "passed" | "needs_revision" = "passed") {
  await userEvent.selectOptions(await screen.findByLabelText("검수 항목"), "narrative");
  await userEvent.type(screen.getByLabelText("검수자"), "합성 검수자");
  await userEvent.type(screen.getByLabelText("판단 근거"), "합성 QA 기록입니다.");
  await userEvent.selectOptions(screen.getByLabelText("판정"), status);
  await userEvent.click(screen.getByRole("checkbox", { name: "1페이지 확인" }));
}

it("통과나 페이지 확인을 기본 선택하지 않고 전체 페이지를 직접 확인한 경우만 통과를 기록한다", async () => {
  render(<ReviewRecordsPanel projectName="p1" exportId="report_v001" />);
  expect(await screen.findByLabelText("판정")).toHaveValue("");
  expect(screen.getByRole("checkbox", { name: "1페이지 확인" })).not.toBeChecked();
  expect(screen.getByRole("checkbox", { name: "2페이지 확인" })).not.toBeChecked();
  await fillReview();
  expect(screen.getByRole("button", { name: "검수 기록 저장" })).toBeDisabled();
  await userEvent.click(screen.getByRole("checkbox", { name: "2페이지 확인" }));
  await userEvent.click(screen.getByRole("button", { name: "검수 기록 저장" }));
  expect(api.recordExportReview).toHaveBeenCalledWith("p1", "report_v001", {
    expected_input_fingerprint: "a".repeat(64), expected_artifact_sha256: "b".repeat(64),
    category: "narrative", reviewer: "합성 검수자", note: "합성 QA 기록입니다.", status: "passed", pages: [1, 2],
  }, '"opened-deck"');
  expect(await screen.findByText(/검수 기록을 저장했습니다/)).toBeInTheDocument();
  expect(screen.getByLabelText("검수자")).toHaveValue("");
  expect(screen.queryByText(/^제출 가능$/)).not.toBeInTheDocument();
});

it("수정 필요 판정은 확인한 일부 페이지만 기록하며 빈 입력과 대상 0은 저장하지 않는다", async () => {
  render(<ReviewRecordsPanel projectName="p1" exportId="report_v001" />);
  await fillReview("needs_revision");
  await userEvent.click(screen.getByRole("checkbox", { name: "1페이지 확인" }));
  expect(screen.getByRole("button", { name: "검수 기록 저장" })).toBeDisabled();
  await userEvent.click(screen.getByRole("checkbox", { name: "1페이지 확인" }));
  await userEvent.click(screen.getByRole("button", { name: "검수 기록 저장" }));
  expect(api.recordExportReview).toHaveBeenCalledWith("p1", "report_v001", expect.objectContaining({ status: "needs_revision", pages: [1] }), '"opened-deck"');
});

it.each([409, 412, 500])("%i 저장 실패 후 입력을 보존하고 재조회 전에는 다시 저장하지 않는다", async status => {
  vi.mocked(api.recordExportReview).mockRejectedValueOnce(new ApiError(status, "검수 기준을 다시 확인해 주세요."));
  const newer = exportReviews({ base_etag: '"rechecked-deck"' });
  vi.mocked(api.getExportReviews).mockResolvedValueOnce(exportReviews()).mockResolvedValue(newer);
  render(<ReviewRecordsPanel projectName="p1" exportId="report_v001" />);
  await fillReview("needs_revision");
  await userEvent.click(screen.getByRole("button", { name: "검수 기록 저장" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("검수 기준을 다시 확인해 주세요.");
  expect(screen.getByLabelText("판단 근거")).toHaveValue("합성 QA 기록입니다.");
  expect(screen.getByRole("checkbox", { name: "1페이지 확인" })).toBeChecked();
  expect(screen.getByRole("button", { name: "검수 기록 저장" })).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: "검수 기준 다시 확인" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "검수 기록 저장" })).toBeEnabled());
  expect(screen.getByLabelText("검수자")).toHaveValue("합성 검수자");
  await userEvent.click(screen.getByRole("button", { name: "검수 기록 저장" }));
  expect(api.recordExportReview).toHaveBeenLastCalledWith("p1", "report_v001", expect.any(Object), '"rechecked-deck"');
});

it("최근 실패, 과거 통과와 현재성을 분리해 표시한다", async () => {
  const past = reviewRecord();
  const latest = reviewRecord({ id: "review-2", sequence: 2, status: "needs_revision", note: "두 번째 페이지 결론을 수정해야 합니다.", pages: [2] });
  const data = exportReviews({ storage_status: "readable", records: [latest, past] });
  data.categories[0] = { category: "narrative", status: "needs_revision", latest_record_id: "review-2" };
  vi.mocked(api.getExportReviews).mockResolvedValue(data);
  render(<ReviewRecordsPanel projectName="p1" exportId="report_v001" />);
  const summary = await screen.findByRole("region", { name: "항목별 최근 판정" });
  expect(summary).toHaveTextContent("보고 흐름: 수정 필요");
  expect(summary).toHaveTextContent("두 번째 페이지 결론을 수정해야 합니다.");
  expect(summary).not.toHaveTextContent("합성 QA 기록입니다.");
  await userEvent.click(screen.getByText("과거 검수 기록 (2개)"));
  expect(screen.getByRole("region", { name: "과거 검수 기록" })).toHaveTextContent("합성 QA 기록입니다.");
  expect(screen.getByText(/수동 기록은 검수자의 자기 신고/)).toBeInTheDocument();
});

it.each(["stale", "unavailable"] as const)("%s 기준에서는 과거 기록과 원인을 보여 주고 저장을 막는다", async status => {
  vi.mocked(api.getExportReviews).mockResolvedValue(exportReviews({ status, can_record: false, reason: "자료 또는 출력 파일을 확인해야 합니다.", records: [reviewRecord()] }));
  render(<ReviewRecordsPanel projectName="p1" exportId="report_v001" />);
  expect(await screen.findByText("자료 또는 출력 파일을 확인해야 합니다.")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "검수 기록 저장" })).toBeDisabled();
  expect(screen.getByText("과거 검수 기록 (1개)")).toBeInTheDocument();
});

it("손상된 기록을 미수행으로 숨기지 않고 읽기 전용 화면에서는 새 기록 폼을 열지 않는다", async () => {
  vi.mocked(api.getExportReviews).mockResolvedValue(exportReviews({ status: "unavailable", storage_status: "invalid", can_record: false, reason: "검수 기록이 손상되었습니다." }));
  render(<ReviewRecordsPanel projectName="p1" exportId="report_v001" readOnly />);
  expect(await screen.findByText("검수 기록이 손상되었습니다.")).toBeInTheDocument();
  expect(screen.queryByLabelText("검수자")).toBeNull();
  expect(screen.queryByRole("button", { name: "검수 기록 저장" })).toBeNull();
});

it("프로젝트와 출력 변경 후 늦은 조회 또는 저장 응답은 새 폼에 적용하지 않는다", async () => {
  const pending = deferred<ExportReviews>();
  vi.mocked(api.getExportReviews).mockReturnValueOnce(pending.promise).mockResolvedValue(exportReviews({ export_id: "report_v002" }));
  const view = render(<ReviewRecordsPanel projectName="old" exportId="report_v001" />);
  view.rerender(<ReviewRecordsPanel projectName="new" exportId="report_v002" />);
  await screen.findByLabelText("검수자");
  await act(async () => pending.resolve(exportReviews({ reason: "오래된 응답" })));
  expect(screen.queryByText("오래된 응답")).toBeNull();
  const save = deferred<ExportReviews>();
  vi.mocked(api.recordExportReview).mockReturnValue(save.promise);
  await fillReview("needs_revision");
  await userEvent.click(screen.getByRole("button", { name: "검수 기록 저장" }));
  view.rerender(<ReviewRecordsPanel projectName="third" exportId="report_v003" />);
  await screen.findByLabelText("검수자");
  await act(async () => save.resolve(exportReviews({ reason: "오래된 저장" })));
  expect(screen.queryByText("오래된 저장")).toBeNull();
  expect(screen.queryByText(/검수 기록을 저장했습니다/)).toBeNull();
});

it("dirty 콜백 변경으로 입력 상태를 초기화하지 않고 이탈 확인과 저장 중 차단을 유지한다", async () => {
  let leave: ReviewLeaveGuard | null = null;
  const dirty = vi.fn();
  const register = vi.fn((guard: ReviewLeaveGuard | null) => { leave = guard; });
  const view = render(<ReviewRecordsPanel projectName="p1" exportId="report_v001" onDirtyChange={dirty} onLeaveReady={register} />);
  await fillReview("needs_revision");
  expect(dirty).toHaveBeenLastCalledWith(true);
  const nextDirty = vi.fn();
  view.rerender(<ReviewRecordsPanel projectName="p1" exportId="report_v001" onDirtyChange={nextDirty} onLeaveReady={guard => register(guard)} />);
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
  await act(async () => expect(await leave!()).toBe(false));
  expect(confirm).toHaveBeenCalledTimes(1);
  expect(screen.getByLabelText("판단 근거")).toHaveValue("합성 QA 기록입니다.");
  const pending = deferred<ExportReviews>();
  vi.mocked(api.recordExportReview).mockReturnValue(pending.promise);
  await userEvent.click(screen.getByRole("button", { name: "검수 기록 저장" }));
  await act(async () => expect(await leave!()).toBe(false));
  expect(confirm).toHaveBeenCalledTimes(1);
  view.unmount();
  expect(nextDirty).toHaveBeenLastCalledWith(false);
  expect(register).toHaveBeenLastCalledWith(null);
  await act(async () => pending.resolve(exportReviews()));
});
