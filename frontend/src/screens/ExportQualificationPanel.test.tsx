import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { api, ApiError, type ExportQualification } from "../api/client";
import { ExportQualificationPanel } from "./ExportQualificationPanel";

vi.mock("../api/client", async (original) => ({ ...await original<typeof import("../api/client")>(),
  api: { getExportQualification: vi.fn(), renderExport: vi.fn(), importIndependentReview: vi.fn(), publishFinal: vi.fn() } }));
const basis = (): ExportQualification => ({ export_id: "draft_v001", checked_at: "2026-09-30T00:00:00Z", base_etag: '"basis"',
  input_fingerprint: "1".repeat(64), artifact_sha256: "2".repeat(64), slide_count: 2, status: "current", storage_status: "empty",
  provenance: null, render_status: "not_run", render: null, independent_review_status: "not_run", independent_review: null,
  final_export_allowed: false, can_render: true, can_import_review: true, blockers: ["실제 렌더를 수행하지 않았습니다."] });
beforeEach(() => { vi.clearAllMocks(); vi.mocked(api.getExportQualification).mockResolvedValue(basis()); });

it("shows not-run blockers and never enables final from manual records", async () => {
  render(<ExportQualificationPanel projectName="p" exportId="draft_v001" />);
  expect(await screen.findByText("실제 렌더를 수행하지 않았습니다.")).toBeVisible();
  expect(screen.getByRole("button", { name: "검수한 파일을 제출본으로 게시" })).toBeDisabled();
  expect(api.publishFinal).not.toHaveBeenCalled();
});

it("keeps signed file on conflict and requires a fresh explicit basis", async () => {
  vi.mocked(api.importIndependentReview).mockRejectedValue(new ApiError(412, "저장본 변경"));
  render(<ExportQualificationPanel projectName="p" exportId="draft_v001" />);
  await screen.findByText("실제 렌더를 수행하지 않았습니다.");
  const file = new File(["{}"], "signed-review.json", { type: "application/json" });
  Object.defineProperty(file, "text", { value: () => Promise.resolve(JSON.stringify({ receipt: {}, signature: "3".repeat(64) })) });
  fireEvent.change(screen.getByLabelText("서명된 독립 검수 파일"), { target: { files: [file] } });
  fireEvent.click(screen.getByRole("button", { name: "독립 검수 기록 확인" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("저장본 변경");
  expect(screen.getByText("선택한 검수 파일: signed-review.json")).toBeVisible();
  expect(screen.getByRole("button", { name: "독립 검수 기록 확인" })).toBeDisabled();
  expect(api.importIndependentReview).toHaveBeenCalledWith("p", "draft_v001", expect.objectContaining({
    expected_input_fingerprint: "1".repeat(64), expected_artifact_sha256: "2".repeat(64),
  }), '"basis"');
  fireEvent.click(screen.getByRole("button", { name: "제출 기준 다시 확인" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "독립 검수 기록 확인" })).toBeEnabled());
});

it("blocks leaving and duplicate native calls until the request settles", async () => {
  let finish!: (value: ExportQualification) => void;
  vi.mocked(api.renderExport).mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  let leave: (() => Promise<boolean>) | null = null;
  render(<ExportQualificationPanel projectName="p" exportId="draft_v001" onLeaveReady={value => { leave = value; }} />);
  await screen.findByText("실제 렌더를 수행하지 않았습니다.");
  fireEvent.click(screen.getByRole("button", { name: "PowerPoint 렌더 실행" }));
  fireEvent.click(screen.getByRole("button", { name: "PowerPoint 렌더 실행" }));
  expect(await leave!()).toBe(false);
  expect(api.renderExport).toHaveBeenCalledTimes(1);
  await act(async () => finish(basis()));
  expect(await leave!()).toBe(true);
});

it("ignores late responses from a different export", async () => {
  let old!: (value: ExportQualification) => void;
  vi.mocked(api.getExportQualification).mockImplementationOnce(() => new Promise(resolve => { old = resolve; }));
  const result = render(<ExportQualificationPanel projectName="p" exportId="old" />);
  result.rerender(<ExportQualificationPanel projectName="p" exportId="new" />);
  await screen.findByText("실제 렌더를 수행하지 않았습니다.");
  await act(async () => old({ ...basis(), blockers: ["OLD SHOULD NOT APPEAR"] }));
  expect(screen.queryByText("OLD SHOULD NOT APPEAR")).not.toBeInTheDocument();
});

it("read-only recovery exposes observations without mutation controls", async () => {
  render(<ExportQualificationPanel projectName="p" exportId="draft_v001" readOnly />);
  await screen.findByText("실제 렌더를 수행하지 않았습니다.");
  expect(screen.queryByRole("button", { name: "PowerPoint 렌더 실행" })).not.toBeInTheDocument();
  expect(screen.queryByLabelText("서명된 독립 검수 파일")).not.toBeInTheDocument();
});
