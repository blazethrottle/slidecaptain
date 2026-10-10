import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api, ApiError } from "../api/client";
import { batchView, chapterView, jobView } from "../test/jobs";
import { RecoveryScreen } from "./RecoveryScreen";

vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return { ...mod, api: { ...mod.api, listSnapshots: vi.fn(), restoreSnapshot: vi.fn(),
    listDrafts: vi.fn(), restoreDraft: vi.fn(), deleteDraft: vi.fn(), listJobs: vi.fn(), settleCandidate: vi.fn(),
    dismissChapterCandidate: vi.fn() } };
});

const project = { name: "p1", title: "제목", updated_at: "", status: "needs_recovery" as const };

beforeEach(() => {
  vi.mocked(api.listDrafts).mockResolvedValue([]);
  vi.mocked(api.listJobs).mockResolvedValue([]);
});

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
  const remove = await screen.findByRole("button", { name: "이 보존본 지우기" });
  // 지운 보존본은 되살릴 수 없으므로 위험 계층이다 (D3a-1 리뷰 R8)
  expect(remove).toHaveClass("btn-danger");
  await userEvent.click(remove);
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

// -- D2b-5c: AI 결과 후보 ------------------------------------------------------------------------

const slots = { template: "bullet_box" as const, bullets: [{ text: "후보 내용", level: 0 as const }], conclusion: "결론", footnote: "" };

it("재시작 뒤 복구 화면에 이전 입력 기준 후보가 기준과 지금 저장본, 이유와 함께 보인다 (지금은 후보가 없다)", async () => {
  vi.mocked(api.listJobs).mockResolvedValue([jobView("chapter", { id: "job-c", target: "c2", candidate_status: "stale",
    stale_reasons: ["template_changed"], base_etag: '"aaaaaaaa1111"', current_etag: '"bbbbbbbb2222"',
    result: { status: "ok", slots } })]);
  const onOpen = vi.fn();
  render(<RecoveryScreen project={project} onBack={() => {}} onOpen={onOpen} />);
  expect(await screen.findByText(/장 다시 생성 \(장 c2\)/)).toBeInTheDocument();
  expect(screen.getByText(/기준 저장본 aaaaaaaa, 지금 저장본 bbbbbbbb/)).toBeInTheDocument();
  expect(screen.getByText(/이전 입력 기준 후보입니다\(이 장의 템플릿이 바뀌었습니다\)/)).toBeInTheDocument();
  await userEvent.click(screen.getByText("보기"));
  expect(screen.getByText(/후보 내용/)).toBeInTheDocument();
  // 다시 씀(D3a-2, C24): 버튼이 옮길 단계 이름을 밝히고, 옮긴 뒤 그 장을 미리 고르도록 장 ID를 넘긴다
  await userEvent.click(screen.getByRole("button", { name: "편집 단계로 옮겨 다시 생성" }));
  expect(onOpen).toHaveBeenCalledWith("editor", "c2");
});

it("덱이 있으면 후보의 장을 내부 ID가 아니라 순서와 제목으로 보인다 (C24, D3a-2)", async () => {
  vi.mocked(api.listJobs).mockResolvedValue([jobView("chapter", { id: "job-c", target: "c2", candidate_status: "stale",
    stale_reasons: ["template_changed"], base_etag: '"aaaaaaaa1111"', current_etag: '"bbbbbbbb2222"',
    result: { status: "ok", slots } })]);
  const deck = { schema_version: 1,
    meta: { title: "제목", report_type: "research" as const, audience: "", presenter: "", preset_overrides: {} },
    structure: { chapters: [
      { id: "c1", topic: "표지", conclusion: "", template: "cover" as const, source_refs: [] },
      { id: "c2", topic: "시장 규모", conclusion: "", template: "bullet_box" as const, source_refs: [] }] },
    slides: [] };
  render(<RecoveryScreen project={project} deck={deck} onBack={() => {}} onOpen={() => {}} />);
  expect(await screen.findByText(/장 다시 생성 \(2장 시장 규모\)/)).toBeInTheDocument();
  expect(screen.queryByText(/장 c2/)).toBeNull();
  expect(screen.getByRole("button", { name: "복구 화면 닫기" })).toBeInTheDocument();
});

it("후보를 버리면 처분하고 목록을 다시 읽는다. 묶음의 장 후보는 장 단위로 버린다 (D2b-5c)", async () => {
  vi.mocked(api.listJobs).mockResolvedValueOnce([
    jobView("structure", { id: "job-s", result: { status: "ok", structure: { chapters: [{ topic: "첫 장" }] } } }),
    batchView([chapterView("c1", "failed", { candidate_status: "stale", result: { status: "ok", slots } })], { id: "job-b" }),
  ]).mockResolvedValue([]);
  vi.mocked(api.settleCandidate).mockResolvedValue(jobView("structure"));
  vi.mocked(api.dismissChapterCandidate).mockResolvedValue(batchView([]));
  render(<RecoveryScreen project={project} onBack={() => {}} />);
  const buttons = await screen.findAllByRole("button", { name: "버리기" });
  expect(buttons).toHaveLength(2);
  await userEvent.click(buttons[1]);
  expect(api.dismissChapterCandidate).toHaveBeenCalledWith("p1", "job-b", "c1");
  expect(await screen.findByText("남아 있는 AI 결과 후보가 없습니다.")).toBeInTheDocument();
});

it("덱 전체 후보는 다시 생성으로 옮기지 않고 버릴 수만 있으며, 저장본을 읽지 못하면 판정 불가로 보인다 (D2b-5c, β 리뷰 R3)", async () => {
  vi.mocked(api.listJobs).mockResolvedValue([jobView("rewrite", { id: "job-r", current_etag: null,
    result: { status: "ok", deck: { structure: { chapters: [{ topic: "새 순서의 첫 장" }] } } } })]);
  render(<RecoveryScreen project={project} onBack={() => {}} />);
  expect(await screen.findByText(/보고 계획 재작성/)).toBeInTheDocument();
  expect(screen.getByText(/저장본이나 자료를 읽지 못해 지금 입력과 비교할 수 없습니다/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "현재 입력으로 다시 생성" })).toBeNull();
  await userEvent.click(screen.getByText("보기"));
  expect(screen.getByText(/1\. 새 순서의 첫 장/)).toBeInTheDocument();
  vi.mocked(api.settleCandidate).mockResolvedValue(jobView("rewrite"));
  vi.mocked(api.listJobs).mockResolvedValue([]);
  await userEvent.click(screen.getByRole("button", { name: "버리기" }));
  expect(api.settleCandidate).toHaveBeenCalledWith("p1", "job-r", "dismissed");
  await waitFor(() => expect(screen.queryByText(/보고 계획 재작성/)).toBeNull());
});

// -- D2b-5c 리뷰 반영 ------------------------------------------------------------------------

it("결과 없이 끝난 지난 작업을 상태와 함께 보인다 (리뷰 R2)", async () => {
  vi.mocked(api.listJobs).mockResolvedValue([
    jobView("structure", { id: "j1", state: "remote_completion_unknown", candidate_status: "none", result: null }),
    jobView("chapter", { id: "j2", state: "cancelled", candidate_status: "none", result: null, target: "c3" }),
    jobView("rewrite", { id: "j3", state: "interrupted", candidate_status: "none", result: null }),
  ]);
  render(<RecoveryScreen project={project} onBack={() => {}} />);
  expect(await screen.findByText("결과 없이 끝난 AI 작업")).toBeInTheDocument();
  expect(screen.getByRole("img", { name: "결과 불명" })).toBeInTheDocument();  // 완료 여부 확인 필요
  expect(screen.getByText(/취소됨/)).toBeInTheDocument();
  expect(screen.getByText(/중단됨/)).toBeInTheDocument();
});

it("묶음 장 후보는 상태별로 설명하고, 끝나지 않은 장은 버리지 못한다 (리뷰 R6, R7, R8)", async () => {
  vi.mocked(api.listJobs).mockResolvedValue([batchView([
    chapterView("c1", "validating", { candidate_status: "held", result: { status: "ok", slots } }),
    chapterView("c2", "failed", { candidate_status: "stale", result: { status: "ok", slots } }),
    chapterView("c3", "cancelled", { candidate_status: "held", result: { status: "ok", slots } }),
  ], { id: "job-b", state: "running" })]);
  render(<RecoveryScreen project={project} onBack={() => {}} onOpen={() => {}} />);
  expect(await screen.findByText(/아직 적용 여부를 확인하지 못한 결과입니다/)).toBeInTheDocument();
  expect(screen.getByText(/만드는 동안 다른 저장이 있어 덱에 넣지 못한 결과입니다/)).toBeInTheDocument();
  expect(screen.getByText(/취소한 뒤 도착한 결과입니다/)).toBeInTheDocument();
  expect(screen.getAllByRole("button", { name: "버리기" })).toHaveLength(2);  // c1은 버릴 수 없다
  expect(screen.queryByText(/기준 저장본/)).toBeNull();  // 묶음 장에는 작업 기준을 보이지 않는다
});

it("자료를 읽지 못한 후보는 이전 입력 기준이 아니라 비교할 수 없다고 알린다 (리뷰 R9)", async () => {
  vi.mocked(api.listJobs).mockResolvedValue([jobView("chapter", { target: "c1", base_etag: '"aaaaaaaa"',
    current_etag: '"aaaaaaaa"', stale_reasons: ["unknown_sources"], result: { status: "ok", slots } })]);
  render(<RecoveryScreen project={project} onBack={() => {}} onOpen={() => {}} />);
  expect(await screen.findByText(/저장본이나 자료를 읽지 못해 지금 입력과 비교할 수 없습니다/)).toBeInTheDocument();
  expect(screen.queryByText(/이전 입력 기준 후보입니다/)).toBeNull();
});

it("옮길 화면이 없으면 다시 생성 버튼을 숨기고, 이미 처분된 후보는 목록만 다시 읽는다 (리뷰 R10, R11)", async () => {
  vi.mocked(api.listJobs).mockResolvedValueOnce([jobView("chapter", { target: "c1", result: { status: "ok", slots } })])
    .mockResolvedValue([]);
  vi.mocked(api.settleCandidate).mockRejectedValue(new ApiError(409, "처분할 결과 후보가 없거나 이미 처분했습니다."));
  render(<RecoveryScreen project={project} onBack={() => {}} />);
  await screen.findByRole("button", { name: "버리기" });
  expect(screen.queryByRole("button", { name: "현재 입력으로 다시 생성" })).toBeNull();
  await userEvent.click(screen.getByRole("button", { name: "버리기" }));
  expect(await screen.findByText("남아 있는 AI 결과 후보가 없습니다.")).toBeInTheDocument();
  expect(screen.queryByRole("alert")).toBeNull();
});

it("다른 장만 바뀐 후보는 같은 기준이라고 하지 않는다 (리뷰 R19)", async () => {
  vi.mocked(api.listJobs).mockResolvedValue([jobView("chapter", { target: "c1", base_etag: '"aaaaaaaa"',
    current_etag: '"bbbbbbbb"', stale_reasons: ["deck_changed_elsewhere"], result: { status: "ok", slots } })]);
  render(<RecoveryScreen project={project} onBack={() => {}} onOpen={() => {}} />);
  expect(await screen.findByText(/덱의 다른 부분만 바뀌어 이 장에는 영향이 없습니다/)).toBeInTheDocument();
});

it("멈춘 수리 후보는 멈춘 이유를 보인다 (리뷰 R17)", async () => {
  vi.mocked(api.listJobs).mockResolvedValue([jobView("repair", { result: { status: "stopped", deck: null,
    reason: "호출 상한에 닿았습니다." } })]);
  render(<RecoveryScreen project={project} onBack={() => {}} />);
  await userEvent.click(await screen.findByText("보기"));
  expect(screen.getByText("멈춘 이유: 호출 상한에 닿았습니다.")).toBeInTheDocument();
});

// -- D2b-β 리뷰 R16: 변형 F13 ---------------------------------------------------------------

it("화면에 전달한 후보(delivered)는 복구 목록에 넣지 않는다 (β 리뷰 R16)", async () => {
  const slots = { status: "ok", slots: { template: "bullet_box" } } as unknown as Record<string, unknown>;
  vi.mocked(api.listJobs).mockResolvedValue([
    jobView("chapter", { id: "j-d", target: "c1", candidate_status: "delivered", result: slots }),
    batchView([chapterView("c2", "succeeded", { candidate_status: "delivered", result: slots })], { id: "j-b" }),
    jobView("chapter", { id: "j-h", target: "c3", candidate_status: "held", result: slots }),  // 대조군
  ]);
  render(<RecoveryScreen project={project} onBack={() => {}} />);
  expect(await screen.findByText(/\(장 c3\)/)).toBeInTheDocument();
  expect(screen.queryByText(/\(장 c1\)/)).toBeNull();
  expect(screen.queryByText(/\(장 c2\)/)).toBeNull();
});
