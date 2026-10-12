// 생성 중 이동과 편집의 계약 시험 (개정판 D3a-5, 계획 4.4). 잠금과 "생성 중" 표시는 화면이 보고하는 바쁨이 아니라
// 서버의 진행 작업으로 정한다. 표의 칸마다 시나리오 하나와, 같은 탭 등록의 진행 작업 갱신, 화면 바쁨의 누수,
// 실패 안내와 머리 작업 표시의 이음매(묶음 리뷰 A10, A11)를 지킨다
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api, ApiError, notifyProject, type ActiveJob, type Deck } from "../api/client";
import { deckWith, planWith, preset, project } from "../test/fixtures";
import { batchView, chapterView, jobView } from "../test/jobs";
import { emptyUsage } from "../test/usage";
import { ProjectView } from "./ProjectView";

vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return { ...mod, api: { ...mod.api,
    getDeck: vi.fn(), listSources: vi.fn(), readSource: vi.fn(), writeSource: vi.fn(), measure: vi.fn(), putDeck: vi.fn(),
    getPreset: vi.fn(), listSnapshots: vi.fn(), listExports: vi.fn(), listDrafts: vi.fn(), saveDraft: vi.fn(),
    getActiveJob: vi.fn(), listJobs: vi.fn(), getDocumentChangeBasis: vi.fn(), getStatus: vi.fn(), prepareAi: vi.fn(),
    startChapters: vi.fn(), startJob: vi.fn(), getJob: vi.fn(), cancelJob: vi.fn(), getAISettings: vi.fn(),
    getProgress: vi.fn(), settleCandidate: vi.fn() } };
});

const nav = () => screen.getByRole("navigation", { name: "보고서 작성 단계" });
const stageButton = (name: string) => within(nav()).getByRole("button", { name });
const header = () => document.querySelector(".project-topbar") as HTMLElement;
const emptyHistory = { items: [], total: 0, offset: 0, limit: 20, checked_at: "2026-10-10T10:00:00Z",
  current_input_fingerprint: null, current_input_error: null };
const activeOf = (kind: string, projectName = project.name, id = "job-1"): ActiveJob => ({
  id, project: projectName, kind, target: null, stage: "running", created_at: "2026-10-12T10:00:00+09:00",
  cancel_requested: false });
const status = (active: ActiveJob | null) => ({ active, ledger_available: true });

function dispatchBeforeUnload(): boolean {
  const ev = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(ev);
  return ev.defaultPrevented;
}

const CH1 = { id: "c1", topic: "첫 장", conclusion: "", template: "bullet_box" as const, source_refs: [] };
const structureResult = (chapters: Deck["structure"]["chapters"]) => ({ status: "ok", structure: { chapters },
  usage: emptyUsage(), raw_text: "", unverified_numbers: [], format_retried: false }) as unknown as Record<string, unknown>;

beforeEach(() => {
  vi.mocked(api.getDeck).mockResolvedValue(deckWith(["하나"]));
  vi.mocked(api.listSources).mockResolvedValue([]);
  vi.mocked(api.measure).mockResolvedValue(planWith(["하나"]));
  vi.mocked(api.getPreset).mockResolvedValue(preset);
  vi.mocked(api.listSnapshots).mockResolvedValue([]);
  vi.mocked(api.listExports).mockResolvedValue(emptyHistory);
  vi.mocked(api.listDrafts).mockResolvedValue([]);
  vi.mocked(api.listJobs).mockResolvedValue([]);
  vi.mocked(api.getActiveJob).mockResolvedValue(status(null));
  vi.mocked(api.getStatus).mockRejectedValue(new Error("상태 조회 없음"));
  vi.mocked(api.prepareAi).mockResolvedValue({ "X-AI-Consent": "SlideCaptain" });
  vi.mocked(api.getAISettings).mockRejectedValue(new Error("설정 조회 없음"));
  vi.mocked(api.getProgress).mockRejectedValue(new Error("진행 조회 없음"));
  vi.mocked(api.settleCandidate).mockResolvedValue(jobView("structure"));
});

// 실제 등록 함수는 응답을 받은 뒤 공통 알림을 낸다(client.ts request). 모의도 같이 알린다
function registered<T extends { id: string }>(view: T): T {
  notifyProject({ kind: "job_started", project: project.name, jobId: view.id });
  return view;
}

async function openProject(pollMs = 5) {
  render(<ProjectView project={project} onBack={() => {}} jobPollMs={pollMs} />);
  await waitFor(() => expect(stageButton("편집")).toBeEnabled());
  // 진행 작업 확인이 끝날 때까지 기다린다. 단계 버튼은 확인 전에도 열려 있으므로 그것으로는 알 수 없다 (D3a-5)
  await waitFor(() => expect(screen.getByRole("button", { name: "스냅샷 복구" }))
    .not.toHaveAttribute("title", "작업 상태를 확인하는 중입니다"));
}

describe("진행 작업 갱신 (사실 11, D3a-3 리뷰 R9)", () => {
  it("같은 탭이 작업을 등록하면 창 초점 없이 상단 작업 표시가 나타난다 (회귀)", async () => {
    await openProject(60_000);
    vi.mocked(api.getActiveJob).mockResolvedValue(status(activeOf("chapters")));
    await act(async () => notifyProject({ kind: "job_started", project: project.name, jobId: "job-1" }));
    expect(await within(header()).findByText(/이 프로젝트에서 AI 생성이 진행 중입니다/)).toBeInTheDocument();
  });

  it("조회하던 화면이 내려간 작업도 끝나면 상단 작업 표시가 사라지고 단계 상태를 다시 읽는다 (회귀)", async () => {
    await openProject();
    vi.mocked(api.getActiveJob).mockResolvedValue(status(activeOf("structure")));
    await act(async () => notifyProject({ kind: "job_started", project: project.name, jobId: "job-1" }));
    await within(header()).findByText(/이 프로젝트에서 AI 생성이 진행 중입니다/);
    const before = vi.mocked(api.getProgress).mock.calls.length;
    vi.mocked(api.getActiveJob).mockResolvedValue(status(null));  // 아무 화면도 이 작업을 조회하지 않는다
    await waitFor(() => expect(within(header()).queryByText(/AI 생성이 진행 중입니다/)).toBeNull());
    await waitFor(() => expect(vi.mocked(api.getProgress).mock.calls.length).toBeGreaterThan(before));
  });
});

describe("후보형 작업 중 (계획 4.4 표 첫 행)", () => {
  // 구성 화면에서 구조안 생성을 시작한다. 조회는 끝나지 않는다
  async function startStructure() {
    vi.mocked(api.getDeck).mockResolvedValue({ ...deckWith([]), structure: { chapters: [] }, slides: [] });
    vi.mocked(api.startJob).mockImplementation(async () =>
      registered(jobView("structure", { id: "job-s", state: "running", candidate_status: "none" })));
    vi.mocked(api.getJob).mockImplementation(() => new Promise(() => {}));
    await openProject();
    await userEvent.click(stageButton("구성"));
    vi.mocked(api.getActiveJob).mockResolvedValue(status(activeOf("structure", project.name, "job-s")));
    await userEvent.click(await screen.findByRole("button", { name: "구조안 생성" }));
    await within(header()).findByText(/이 프로젝트에서 AI 생성이 진행 중입니다/);
  }

  it("구조안 생성 중에도 다른 단계로 이동할 수 있다 (회귀)", async () => {
    await startStructure();
    for (const name of ["보고 목적", "자료", "편집", "검토와 내보내기"]) expect(stageButton(name)).toBeEnabled();
    await userEvent.click(stageButton("자료"));
    await waitFor(() => expect(stageButton("자료")).toHaveAttribute("aria-current", "step"));
  });

  it("구조안 생성 중 다른 단계로 간 뒤 작업이 끝나면 잠금과 창 닫기 경고가 풀리고, 돌아오면 후보가 보인다 (회귀)", async () => {
    await startStructure();
    await userEvent.click(stageButton("자료"));
    await waitFor(() => expect(stageButton("자료")).toHaveAttribute("aria-current", "step"));
    expect(screen.getByRole("button", { name: "AI 연결 및 모델" })).toBeDisabled();
    expect(dispatchBeforeUnload()).toBe(true);
    // 작업이 끝났다. 구성 화면은 내려가 있어 아무도 조회하지 않는다
    vi.mocked(api.getActiveJob).mockResolvedValue(status(null));
    vi.mocked(api.listJobs).mockResolvedValue([jobView("structure", { id: "job-s", result: structureResult([CH1]) })]);
    await waitFor(() => expect(screen.getByRole("button", { name: "AI 연결 및 모델" })).toBeEnabled());
    expect(dispatchBeforeUnload()).toBe(false);
    await userEvent.click(stageButton("구성"));
    expect(await screen.findByText(/이전에 만든 구조안 후보를 불러왔습니다/)).toBeInTheDocument();
    expect(screen.getByLabelText("1번 장 주제")).toHaveValue("첫 장");
  });

  it("구조안 생성 중 다른 단계의 다른 생성 버튼은 다른 작업 진행 중으로 안내하고 머리의 취소를 가리킨다", async () => {
    // 장이 있는 덱에서 구조안을 다시 생성한다. 편집 단계에 그 장의 생성 버튼이 있다
    vi.mocked(api.startJob).mockImplementation(async () =>
      registered(jobView("structure", { id: "job-s", state: "running", candidate_status: "none" })));
    vi.mocked(api.getJob).mockImplementation(() => new Promise(() => {}));
    await openProject();
    await userEvent.click(stageButton("구성"));
    vi.mocked(api.getActiveJob).mockResolvedValue(status(activeOf("structure", project.name, "job-s")));
    await userEvent.click(await screen.findByRole("button", { name: "다시 생성" }));
    await within(header()).findByText(/이 프로젝트에서 AI 생성이 진행 중입니다/);
    vi.mocked(api.startJob).mockRejectedValue(new ApiError(409, "다른 AI 생성이 진행 중입니다.", "generation_active",
      activeOf("structure", project.name, "job-s")));
    await userEvent.click(stageButton("편집"));
    await userEvent.click(await screen.findByRole("button", { name: "이 장 다시 생성" }));
    const notice = (await screen.findByText("다른 AI 생성이 진행 중입니다.")).closest(".failure-notice") as HTMLElement;
    expect(notice).toHaveAttribute("role", "status");
    expect(notice).toHaveTextContent(/화면 위쪽의 '그 작업 취소'/);
    expect(screen.getAllByRole("button", { name: "그 작업 취소" })).toHaveLength(1);
  });

  it("후보형 작업 중에는 AI 설정만 잠그고 스냅샷 복구와 다시 읽기는 열어 둔다", async () => {
    vi.mocked(api.getActiveJob).mockResolvedValue(status(activeOf("diagram")));
    await openProject(60_000);
    await within(header()).findByText(/이 프로젝트에서 AI 생성이 진행 중입니다/);
    expect(screen.getByRole("button", { name: "AI 연결 및 모델" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "스냅샷 복구" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "목록으로" })).toBeEnabled();
    expect(screen.getByLabelText("보고서 제목")).toBeEnabled();  // 덱 편집도 허용한다
  });
});

describe("장 생성 묶음 중 (계획 4.4 표 둘째 행, 사용자 결정 Q1의 A)", () => {
  async function batchRunning() {
    vi.mocked(api.getActiveJob).mockResolvedValue(status(activeOf("chapters")));
    await openProject(60_000);
    await within(header()).findByText(/이 프로젝트에서 AI 생성이 진행 중입니다/);
  }

  it("단계 이동과 목록으로는 허용하고 내보내기, 스냅샷 복구, AI 설정은 잠근다", async () => {
    await batchRunning();
    for (const name of ["보고 목적", "자료", "구성", "편집", "검토와 내보내기"]) expect(stageButton(name)).toBeEnabled();
    expect(screen.getByRole("button", { name: "목록으로" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "스냅샷 복구" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "AI 연결 및 모델" })).toBeDisabled();
    await userEvent.click(stageButton("검토와 내보내기"));
    expect(await screen.findByText(/내용 생성이 끝나면 내보내기와 검수 기록을 쓸 수 있습니다/)).toBeInTheDocument();
  });

  it("보고 목적 폼은 읽기 전용이다", async () => {
    await batchRunning();
    await userEvent.click(stageButton("보고 목적"));
    expect(await screen.findByLabelText("보고서 제목")).toBeDisabled();
    expect(screen.getByRole("button", { name: "보고 정보 저장" })).toBeDisabled();
    expect(screen.getByText(/생성 중인 장은 끝나면 보입니다/)).toBeInTheDocument();
  });

  it("편집 단계는 읽기 전용이고, 끝나면 충돌 안내 없이 새 덱으로 다시 마운트한다", async () => {
    await batchRunning();
    await userEvent.click(stageButton("편집"));
    expect(await screen.findByText(/생성 중인 장은 끝나면 보입니다/)).toBeInTheDocument();
    expect(document.querySelector(".editor-right")).toHaveAttribute("inert");  // 장을 골라 보는 것은 허용한다
    expect(screen.getByRole("button", { name: "도식 추가" })).toBeDisabled();
    vi.mocked(api.getDocumentChangeBasis).mockRejectedValue(new ApiError(412, "저장본이 바뀌었습니다."));
    const after = deckWith(["묶음이 만든 내용"]);
    vi.mocked(api.getDeck).mockResolvedValue(after);
    vi.mocked(api.measure).mockResolvedValue(planWith(["묶음이 만든 내용"]));
    vi.mocked(api.getActiveJob).mockResolvedValue(status(null));
    await act(async () => { window.dispatchEvent(new Event("focus")); });
    await waitFor(() => expect(screen.queryByText(/생성 중인 장은 끝나면 보입니다/)).toBeNull());
    expect(document.querySelector(".editor-right")).not.toHaveAttribute("inert");
    expect(screen.queryByText(/다른 창이나 프로그램에서 먼저 저장되었습니다/)).toBeNull();
    expect(screen.queryByRole("button", { name: "서버 내용 다시 읽기" })).toBeNull();
  });

  it("자료 편집은 허용하되 저장 전에 반영되지 않는 장이 생길 수 있음을 알린다", async () => {
    vi.mocked(api.listSources).mockResolvedValue(["메모.md"]);
    vi.mocked(api.readSource).mockResolvedValue({ text: "원래 내용" } as Awaited<ReturnType<typeof api.readSource>>);
    vi.mocked(api.writeSource).mockResolvedValue(undefined as never);
    await batchRunning();
    await userEvent.click(stageButton("자료"));
    expect(await screen.findByText(/내용 생성 중에 자료를 고치면/)).toBeInTheDocument();
    await userEvent.click(await screen.findByRole("button", { name: "메모.md" }));
    const body = await screen.findByLabelText("자료 내용");
    expect(body).toBeEnabled();
    await userEvent.type(body, " 추가");
    const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
    await userEvent.click(screen.getByRole("button", { name: "자료 저장" }));
    expect(confirm.mock.calls[0][0]).toMatch(/AI 호출 하나의 결과가 반영되지 않/);
    expect(api.writeSource).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "자료 저장" }));
    await waitFor(() => expect(api.writeSource).toHaveBeenCalled());
    confirm.mockRestore();
  });
});

describe("묶음 중 읽기 전용이 된 보고 정보의 미저장 입력", () => {
  it("떠나기 전에 버릴지 묻고, 머물면 실패 안내 없이 머문다. 저장하지 않는다", async () => {
    await openProject(5);
    await userEvent.type(screen.getByLabelText("보고서 제목"), " 고침");
    vi.mocked(api.getActiveJob).mockImplementation(async () => status(activeOf("chapters")));
    await act(async () => { window.dispatchEvent(new Event("focus")); });
    await waitFor(() => expect(screen.getByLabelText("보고서 제목")).toBeDisabled());
    const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
    await userEvent.click(stageButton("자료"));
    expect(confirm.mock.calls[0][0]).toMatch(/내용 생성 중이라 고친 내용을 저장할 수 없습니다/);
    expect(stageButton("보고 목적")).toHaveAttribute("aria-current", "step");
    expect(screen.queryByText(/마지막 편집을 저장하지 못해/)).toBeNull();
    await userEvent.click(stageButton("자료"));
    await waitFor(() => expect(stageButton("자료")).toHaveAttribute("aria-current", "step"));
    expect(api.putDeck).not.toHaveBeenCalled();
    confirm.mockRestore();
  });
});

describe("다른 프로젝트의 작업 중 (계획 4.4 표 셋째 행)", () => {
  it("AI 설정만 잠그고 나머지는 허용한다", async () => {
    vi.mocked(api.getActiveJob).mockResolvedValue(status(activeOf("chapters", "다른보고", "job-9")));
    await openProject(60_000);
    await within(header()).findByText(/다른 프로젝트\(다른보고\)에서 AI 생성이 진행 중입니다/);
    expect(screen.getByRole("button", { name: "AI 연결 및 모델" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "스냅샷 복구" })).toBeEnabled();
    expect(screen.getByLabelText("보고서 제목")).toBeEnabled();
  });
});

describe("구성 초안 이탈 확인 (C16)", () => {
  it("승인하지 않은 장 구성 초안을 고친 채 단계를 옮기면 묻고, 취소하면 머문다", async () => {
    await openProject();
    await userEvent.click(stageButton("구성"));
    const topic = await screen.findByLabelText("1번 장 주제");
    await userEvent.type(topic, " 고침");
    const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
    await userEvent.click(stageButton("편집"));
    expect(confirm.mock.calls[0][0]).toMatch(/승인하지 않은 장 구성 초안은 저장되지 않습니다/);
    expect(stageButton("구성")).toHaveAttribute("aria-current", "step");
    expect(screen.queryByText(/마지막 편집을 저장하지 못해/)).toBeNull();
    await userEvent.click(stageButton("편집"));
    await waitFor(() => expect(stageButton("편집")).toHaveAttribute("aria-current", "step"));
    confirm.mockRestore();
  });
});

describe("구성 초안 이탈 확인: 고치지 않은 구조안 후보", () => {
  it("구조안 후보를 고치지 않고 떠나면 묻지 않고, 돌아오면 그 후보를 다시 불러온다", async () => {
    vi.mocked(api.getDeck).mockResolvedValue({ ...deckWith([]), structure: { chapters: [] }, slides: [] });
    const candidate = jobView("structure", { id: "job-s", result: structureResult([CH1]) });
    vi.mocked(api.startJob).mockImplementation(async () => registered(candidate));
    await openProject();
    await userEvent.click(stageButton("구성"));
    await userEvent.click(await screen.findByRole("button", { name: "구조안 생성" }));
    await screen.findByLabelText("1번 장 주제");
    const confirm = vi.spyOn(window, "confirm");
    await userEvent.click(stageButton("자료"));
    await waitFor(() => expect(stageButton("자료")).toHaveAttribute("aria-current", "step"));
    expect(confirm).not.toHaveBeenCalled();
    vi.mocked(api.listJobs).mockResolvedValue([candidate]);
    await userEvent.click(stageButton("구성"));
    expect(await screen.findByLabelText("1번 장 주제")).toHaveValue("첫 장");
    // 후보를 고치면 떠날 때 묻는다
    confirm.mockReturnValueOnce(false);
    await userEvent.type(screen.getByLabelText("1번 장 주제"), " 고침");
    await userEvent.click(stageButton("자료"));
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(stageButton("구성")).toHaveAttribute("aria-current", "step");
    confirm.mockRestore();
  });
});

describe("실패 안내와 머리 작업 표시 (묶음 리뷰 A10, A11)", () => {
  it("다른 작업 진행 중 안내는 머리의 취소를 가리키고, 그 작업이 끝나면 끝났다고 바뀐다 (A10)", async () => {
    vi.mocked(api.getDeck).mockResolvedValue({ ...deckWith([]), structure: { chapters: [] }, slides: [] });
    const other = activeOf("chapters", "다른보고", "job-9");
    vi.mocked(api.startJob).mockRejectedValue(new ApiError(409, "다른 AI 생성이 진행 중입니다.", "generation_active", other));
    await openProject(60_000);
    await userEvent.click(stageButton("구성"));
    vi.mocked(api.getActiveJob).mockResolvedValue(status(other));
    await userEvent.click(await screen.findByRole("button", { name: "구조안 생성" }));
    const notice = (await screen.findByText("다른 AI 생성이 진행 중입니다.")).closest(".failure-notice") as HTMLElement;
    await within(header()).findByText(/다른 프로젝트\(다른보고\)에서 AI 생성이 진행 중입니다/);
    expect(screen.getAllByRole("button", { name: "그 작업 취소" })).toHaveLength(1);  // 머리의 것 하나
    expect(within(notice).queryByRole("button", { name: "그 작업 취소" })).toBeNull();
    expect(notice).toHaveTextContent(/화면 위쪽의 '그 작업 취소'/);
    // 안내가 떠 있는 동안 진행 작업 조회를 되풀이하지 않는다(안내가 뜰 때 한 번, 그 뒤는 조회 간격대로)
    const calls = vi.mocked(api.getActiveJob).mock.calls.length;
    await act(async () => { await new Promise((r) => setTimeout(r, 100)); });
    expect(vi.mocked(api.getActiveJob).mock.calls.length - calls).toBeLessThanOrEqual(2);
    vi.mocked(api.getActiveJob).mockResolvedValue(status(null));
    await act(async () => { window.dispatchEvent(new Event("focus")); });
    await waitFor(() => expect(document.querySelector(".failure-notice")).toHaveTextContent(
      /진행 중이던 다른 AI 작업\(다른보고\)이 끝났습니다.*다시 시도할 수 있습니다/));
    expect(screen.queryByRole("button", { name: "그 작업 취소" })).toBeNull();
  });

  it("같은 탭이 따라가는 묶음에는 취소 버튼이 하나다 (A11)", async () => {
    vi.mocked(api.getDeck).mockResolvedValue({ ...deckWith([]), structure: { chapters: [CH1] }, slides: [] });
    vi.mocked(api.putDeck).mockResolvedValue({ ok: true });
    vi.mocked(api.startChapters).mockImplementation(async () =>
      registered(batchView([chapterView("c1", "running")], { state: "running", outcome: null })));
    vi.mocked(api.getJob).mockImplementation(async () => batchView([chapterView("c1", "running")], { state: "running", outcome: null }));
    await openProject();
    await userEvent.click(stageButton("구성"));
    vi.mocked(api.getActiveJob).mockResolvedValue(status(activeOf("chapters")));
    await userEvent.click(await screen.findByRole("button", { name: "승인하고 내용 생성" }));
    await within(header()).findByText(/이 프로젝트에서 AI 생성이 진행 중입니다/);
    expect(screen.getAllByRole("button", { name: /그 작업 취소|생성 중단/ })).toHaveLength(1);
  });
});

describe("작업 종결 알림 (묶음 리뷰 A12)", () => {
  it("진행 작업에서 사라진 작업은 원장의 결과를 읽어 결과 문구 하나로만 알린다", async () => {
    vi.mocked(api.getActiveJob).mockImplementation(async () => status(activeOf("chapters")));
    await openProject();
    await within(header()).findByText(/이 프로젝트에서 AI 생성이 진행 중입니다/);
    const announcer = document.querySelector('main > p.visually-hidden[role="status"]') as HTMLElement;
    const texts: string[] = [];
    const observer = new MutationObserver(() => texts.push(announcer.textContent ?? ""));
    observer.observe(announcer, { subtree: true, characterData: true, childList: true });
    vi.mocked(api.getJob).mockResolvedValue(batchView([chapterView("c1", "cancelled")], { state: "cancelled", outcome: "cancelled" }));
    vi.mocked(api.getActiveJob).mockImplementation(async () => status(null));  // 이 작업을 조회하는 화면은 없다
    await waitFor(() => expect(announcer).toHaveTextContent("내용 생성을 취소했습니다(p1)"));
    observer.disconnect();
    expect(texts.filter(Boolean)).toEqual(["내용 생성을 취소했습니다(p1)"]);
    expect(api.getJob).toHaveBeenCalledWith("p1", "job-1");
  });
});
