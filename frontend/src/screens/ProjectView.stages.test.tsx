// 다섯 단계 셸의 계약 시험 (개정판 D3a-2, 계획 4.1). 단계 이동과 현재 단계, 상단 머리의 저장 상태 출처,
// 보존 건수, 복구 화면과 단계, 묶음 종결 뒤 분기(β R1 새 분기), 순서 시나리오, 탭 이름 없는 문구를 지킨다
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api, ApiError, notifyProject, type Deck, type ProjectProgress } from "../api/client";
import { deckWith, deferred, planWith, preset, project } from "../test/fixtures";
import { batchView, chapterResult, chapterView } from "../test/jobs";
import { emptyUsage } from "../test/usage";
import { StoryPlanRecoveryGuidance } from "./StoryPlanRecoveryGuidance";
import { ProjectView } from "./ProjectView";

vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return { ...mod, api: { ...mod.api,
    getDeck: vi.fn(), listSources: vi.fn(), readSource: vi.fn(), measure: vi.fn(), putDeck: vi.fn(), getPreset: vi.fn(),
    listSnapshots: vi.fn(), listExports: vi.fn(), listDrafts: vi.fn(), saveDraft: vi.fn(), getActiveJob: vi.fn(),
    listJobs: vi.fn(), getDocumentChangeBasis: vi.fn(), getStatus: vi.fn(), prepareAi: vi.fn(), startChapters: vi.fn(),
    getJob: vi.fn(), getAISettings: vi.fn(), getProgress: vi.fn() } };
});

const STAGES = ["보고 목적", "자료", "구성", "편집", "검토와 내보내기"];
const nav = () => screen.getByRole("navigation", { name: "보고서 작성 단계" });
const stageButton = (name: string) => within(nav()).getByRole("button", { name });
const headerStatus = () => document.querySelector(".header-save-status .status-label")?.textContent ?? null;
const batchActive = (kind = "chapters") => ({ ledger_available: true, active: {
  id: "job-1", project: project.name, kind, target: null, stage: "running" as const,
  created_at: "2026-10-10T10:00:00+09:00", cancel_requested: false } });
const emptyHistory = { items: [], total: 0, offset: 0, limit: 20, checked_at: "2026-10-10T10:00:00Z",
  current_input_fingerprint: null, current_input_error: null };

beforeEach(() => {
  vi.mocked(api.getDeck).mockResolvedValue(deckWith(["하나"]));
  vi.mocked(api.listSources).mockResolvedValue([]);
  vi.mocked(api.measure).mockResolvedValue(planWith(["하나"]));
  vi.mocked(api.getPreset).mockResolvedValue(preset);
  vi.mocked(api.listSnapshots).mockResolvedValue([]);
  vi.mocked(api.listExports).mockResolvedValue(emptyHistory);
  vi.mocked(api.listDrafts).mockResolvedValue([]);
  vi.mocked(api.listJobs).mockResolvedValue([]);
  vi.mocked(api.getActiveJob).mockResolvedValue({ active: null, ledger_available: true });
  vi.mocked(api.getStatus).mockRejectedValue(new Error("상태 조회 없음"));
  vi.mocked(api.prepareAi).mockResolvedValue({ "X-AI-Consent": "SlideCaptain" });
  vi.mocked(api.getAISettings).mockRejectedValue(new Error("설정 조회 없음"));
  vi.mocked(api.getProgress).mockResolvedValue(PROGRESS);
});

async function openProject() {
  render(<ProjectView project={project} onBack={() => {}} jobPollMs={5} />);
  await waitFor(() => expect(stageButton("편집")).toBeEnabled());
}

// 다른 탭이 이 프로젝트의 장 생성 묶음을 시작했다가 끝낸다. 서버의 저장본은 이 탭이 본 것과 달라졌다(기준 조회 412)
async function otherTabBatchEnds(after: Deck) {
  vi.mocked(api.getDocumentChangeBasis).mockRejectedValue(
    new ApiError(412, "다른 창이나 프로그램에서 먼저 저장되었습니다. 최신 덱을 다시 읽어 주세요."));
  vi.mocked(api.getDeck).mockResolvedValue(after);
  vi.mocked(api.getActiveJob).mockResolvedValueOnce(batchActive())
    .mockImplementation(async () => ({ active: null, ledger_available: true }));
  await act(async () => { window.dispatchEvent(new Event("focus")); });
}

// 진행 API 응답 (D3a-3). 보고 목적은 확인 필요, 자료는 준비됨(한계 사유 붙음), 구성은 준비됨, 편집은 준비됨,
// 검토는 사람 검토가 남은 섞인 상태다
const PROGRESS: ProjectProgress = { project_status: "ok", jobs: [], stages: [
  { stage: "purpose", state: "needs_review", reasons: ["report_type_unconfirmed"] },
  { stage: "sources", state: "ready", reasons: ["extraction_review_unavailable"] },
  { stage: "structure", state: "ready", reasons: [] },
  { stage: "editing", state: "ready", reasons: [], written_chapters: 1, total_chapters: 1 },
  { stage: "review", state: "needs_review", reasons: ["human_review_pending"], parts: [
    { name: "auto_checks", state: "ready", reasons: ["draft_checks_only"] },
    { name: "human_review", state: "not_started", reasons: [] },
    { name: "file", state: "ready", reasons: [] }] },
] };
const statusOf = (stage: string) => document.getElementById(`stage-status-${stage}`);

const batchDeck: Deck = { ...deckWith(["묶음이 만든 내용"]), structure: { chapters: [
  { id: "c1", topic: "묶음이 만든 장", conclusion: "", template: "bullet_box", source_refs: [] }] } };

describe("단계 목록과 현재 단계", () => {
  it("단계 목록 nav에 다섯 단계 버튼이 있고, 고른 단계에만 aria-current=step이 붙는다", async () => {
    await openProject();
    const buttons = within(nav()).getAllByRole("button");
    expect(buttons.map((b) => b.textContent?.replace(/^\d/, ""))).toEqual(STAGES);
    expect(stageButton("보고 목적")).toHaveAttribute("aria-current", "step");  // 처음 여는 단계
    for (const name of STAGES) {
      await userEvent.click(stageButton(name));
      await waitFor(() => expect(stageButton(name)).toHaveAttribute("aria-current", "step"));
      expect(document.querySelectorAll("[aria-current='step']")).toHaveLength(1);
    }
  });

  it("단계 번호는 낭독하지 않아 버튼 이름이 단계 이름과 같다", async () => {
    await openProject();
    expect(within(nav()).getAllByRole("button").map((b) => b.getAttribute("aria-label") ?? "")).toEqual(["", "", "", "", ""]);
    expect(nav().querySelectorAll(".stage-number[aria-hidden='true']")).toHaveLength(5);
  });

  it("DOM 순서가 상단 머리, 단계 목록, 본문이다 (계획 6절 키보드 순서)", async () => {
    await openProject();
    const header = document.querySelector(".project-topbar")!;
    const sidebar = document.querySelector(".stage-sidebar")!;
    const body = document.querySelector(".stage-body")!;
    expect(header.compareDocumentPosition(sidebar) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(sidebar.compareDocumentPosition(body) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("단계마다 누를 수 있는 주 행동이 정확히 1개다. 편집 단계는 0개다 (계획 4.6, D3a-1 R17)", async () => {
    await openProject();
    const expected: Record<string, string[]> = {
      "보고 목적": ["보고 정보 저장"], "자료": ["파일 선택"], "구성": ["승인하고 내용 생성"], "편집": [],
      "검토와 내보내기": ["초안 PPTX 내보내기"] };
    for (const name of STAGES) {
      await userEvent.click(stageButton(name));
      await waitFor(() => expect(stageButton(name)).toHaveAttribute("aria-current", "step"));
      if (name === "편집") await screen.findByLabelText("장 주제");
      await waitFor(() => expect([...document.querySelectorAll(".btn-primary")]
        .filter((b) => !(b as HTMLButtonElement).disabled).map((b) => b.textContent)).toEqual(expected[name]));
    }
  });

  it("덱을 열 수 없는 상태는 다섯 단계 셸을 띄우지 않는다", async () => {
    vi.mocked(api.listJobs).mockResolvedValue([]);
    render(<ProjectView project={{ ...project, status: "needs_recovery" }} onBack={() => {}} />);
    expect(await screen.findByRole("button", { name: "목록으로" })).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "보고서 작성 단계" })).toBeNull();
  });

  it("최초 덱 읽기가 실패하면 다섯 단계 셸을 띄우지 않는다", async () => {
    vi.mocked(api.getDeck).mockRejectedValue(new ApiError(500, "덱을 읽지 못했습니다."));
    render(<ProjectView project={project} onBack={() => {}} />);
    expect(await screen.findByText("덱을 읽지 못했습니다.")).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "보고서 작성 단계" })).toBeNull();
  });
});

describe("상단 머리의 저장 상태 출처 (계획 4.1 표)", () => {
  it("보고 목적: 폼이 저장본과 다르면 저장됨이 아니다", async () => {
    await openProject();
    await waitFor(() => expect(headerStatus()).toBe("저장됨"));
    await userEvent.type(screen.getByLabelText("보고서 제목"), " 고침");
    expect(headerStatus()).toBe("변경사항 있음");
  });

  it("구성: 초안이 저장본과 다르면 변경사항 있음이고, 승인 전 초안은 저장되지 않는 값임을 밝힌다", async () => {
    vi.mocked(api.getDeck).mockResolvedValue({ ...deckWith(["하나"]), structure: { chapters: [
      { id: "c1", topic: "주제", conclusion: "", template: "bullet_box", source_refs: [] },
      { id: "c2", topic: "둘째", conclusion: "", template: "bullet_box", source_refs: [] }] } });
    await openProject();
    await userEvent.click(stageButton("구성"));
    await waitFor(() => expect(headerStatus()).toBe("저장됨"));
    await userEvent.click(await screen.findByRole("button", { name: "둘째 삭제" }));
    expect(headerStatus()).toBe("변경사항 있음");
    expect(document.querySelector(".header-save-status")).toHaveTextContent("승인 전 초안은 저장되지 않습니다");
  });

  it("편집: 자동 저장 상태를 그대로 보인다", async () => {
    vi.mocked(api.putDeck).mockImplementation(() => new Promise(() => {}));
    await openProject();
    await userEvent.click(stageButton("편집"));
    const topic = await screen.findByLabelText("장 주제");
    await waitFor(() => expect(headerStatus()).toBe("저장됨"));
    fireEvent.change(topic, { target: { value: "고침" } });
    fireEvent.blur(topic);
    await waitFor(() => expect(headerStatus()).not.toBe("저장됨"));
  });

  it("검토와 내보내기: 검수 기록 폼이 없으면 표시하지 않는다", async () => {
    await openProject();
    await userEvent.click(stageButton("검토와 내보내기"));
    await screen.findByText("내보내기 이력이 없습니다.");
    expect(document.querySelector(".header-save-status")).toBeNull();
  });
});

describe("보존 건수와 복구 화면 (C18, C24)", () => {
  const draft = { id: "draft-20261010-100000-000001", saved_at: "2026-10-10T10:00:00+09:00",
    reason: "conflict" as const, source: "editor" as const, base_etag: null };

  it("보존한 변경이 있으면 상단 머리에 건수를 보이고, 누르면 복구 화면을 연다", async () => {
    vi.mocked(api.listDrafts).mockResolvedValue([draft, { ...draft, id: "draft-20261010-100000-000002" }]);
    await openProject();
    await userEvent.click(await screen.findByRole("button", { name: "보존한 변경 2건" }));
    expect(await screen.findByText("충돌로 보존한 변경", { exact: false })).toBeInTheDocument();
    expect(document.querySelector(".recovery-screen")).not.toBeNull();
  });

  it("복구 화면이 열린 동안 현재 단계 표시가 없고, 단계를 고르면 복구 화면을 닫고 그 단계로 간다", async () => {
    await openProject();
    await userEvent.click(screen.getByRole("button", { name: "스냅샷 복구" }));
    await waitFor(() => expect(document.querySelector(".recovery-screen")).not.toBeNull());
    expect(document.querySelector("[aria-current='step']")).toBeNull();
    await userEvent.click(stageButton("자료"));
    await waitFor(() => expect(document.querySelector(".recovery-screen")).toBeNull());
    expect(stageButton("자료")).toHaveAttribute("aria-current", "step");
  });

  it("복구 화면의 후보를 다시 만들 단계로 옮기면 그 장을 미리 고른다", async () => {
    const twoChapters: Deck = { ...deckWith(["하나"]), structure: { chapters: [
      { id: "c1", topic: "주제", conclusion: "", template: "bullet_box", source_refs: [] },
      { id: "c2", topic: "둘째 장", conclusion: "", template: "bullet_box", source_refs: [] }] },
      slides: [...deckWith(["하나"]).slides, { chapter_id: "c2", eyebrow: "", subtitle: "", slots: {
        template: "bullet_box", bullets: [{ text: "둘", level: 0 }], conclusion: "", footnote: "" } }] };
    vi.mocked(api.getDeck).mockResolvedValue(twoChapters);
    vi.mocked(api.listJobs).mockResolvedValue([{ id: "job-c", project: project.name, kind: "chapter", state: "succeeded",
      target: "c2", params: {}, candidate_status: "stale", outcome: null, owner: "this_instance",
      created_at: "2026-10-10T10:00:00+09:00", started_at: null, finished_at: null, provider: null, model: null,
      base_etag: null, current_etag: null, relevance_hash: null, stale_reasons: ["template_changed"],
      cancel_requested: false, error: null, result: { status: "ok", usage: emptyUsage(),
        slots: { template: "bullet_box", bullets: [], conclusion: "", footnote: "" } }, chapters: [] }]);
    await openProject();
    await userEvent.click(screen.getByRole("button", { name: "스냅샷 복구" }));
    expect(await screen.findByText(/장 다시 생성 \(2장 둘째 장\)/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "편집 단계로 옮겨 다시 생성" }));
    await waitFor(() => expect(stageButton("편집")).toHaveAttribute("aria-current", "step"));
    expect(await screen.findByLabelText("장 주제")).toHaveValue("둘째 장");
  });
});

describe("묶음 종결 뒤 분기: 그 화면이 저장본과 다른 사본을 들고 있는가 (β R1 새 분기, 계획 4.1)", () => {
  it("보고 목적 폼이 저장본과 다르면 충돌 안내를 띄우고 덱을 몰래 다시 읽지 않는다", async () => {
    await openProject();
    await userEvent.type(screen.getByLabelText("보고서 제목"), " 고침");
    const reads = vi.mocked(api.getDeck).mock.calls.length;
    await otherTabBatchEnds(batchDeck);
    expect(await screen.findByText("다른 창이나 프로그램에서 먼저 저장되었습니다.", { exact: false })).toBeInTheDocument();
    expect(vi.mocked(api.getDeck).mock.calls.length).toBe(reads);
    expect(screen.getByLabelText("보고서 제목")).toHaveValue("제목 고침");  // 입력은 그대로다
  });

  it("보고 목적 폼이 저장본과 같으면 새 덱으로 다시 마운트하고 충돌로 알리지 않는다", async () => {
    await openProject();
    await otherTabBatchEnds({ ...batchDeck, meta: { ...batchDeck.meta, title: "묶음 뒤 제목" } });
    await waitFor(() => expect(screen.getByLabelText("보고서 제목")).toHaveValue("묶음 뒤 제목"));
    expect(screen.queryByText("먼저 저장되었습니다", { exact: false })).toBeNull();
  });

  it("자료 단계는 덱을 들고 있지 않아 자료 본문을 고치는 중이어도 덱만 다시 읽는다", async () => {
    vi.mocked(api.listSources).mockResolvedValue(["자료.md"]);
    vi.mocked(api.readSource).mockResolvedValue({ text: "원문" });
    await openProject();
    await userEvent.click(stageButton("자료"));
    await userEvent.click(await screen.findByRole("button", { name: "자료.md" }));
    await userEvent.type(await screen.findByLabelText("자료 내용"), " 고침");
    const reads = vi.mocked(api.getDeck).mock.calls.length;
    await otherTabBatchEnds(batchDeck);
    await waitFor(() => expect(vi.mocked(api.getDeck).mock.calls.length).toBe(reads + 1));
    expect(screen.queryByText("먼저 저장되었습니다", { exact: false })).toBeNull();
    expect(screen.getByLabelText("자료 내용")).toHaveValue("원문 고침");  // 자료 화면은 다시 마운트하지 않는다
  });
});

describe("순서 시나리오 (계획 5절 D3a-2)", () => {
  it("자료 단계에서 묶음이 끝난 뒤 보고 목적으로 옮겨 저장하면 묶음의 장이 남는다", async () => {
    vi.mocked(api.putDeck).mockResolvedValue({ ok: true });
    await openProject();
    await userEvent.click(stageButton("자료"));
    await screen.findByLabelText("자료 파일 선택");
    const reads = vi.mocked(api.getDeck).mock.calls.length;
    await otherTabBatchEnds(batchDeck);
    await waitFor(() => expect(vi.mocked(api.getDeck).mock.calls.length).toBe(reads + 1));
    await userEvent.click(stageButton("보고 목적"));
    await userEvent.type(await screen.findByLabelText("보고자"), "사업개발팀");
    await userEvent.click(screen.getByRole("button", { name: "보고 정보 저장" }));
    await waitFor(() => expect(api.putDeck).toHaveBeenCalled());
    const saved = vi.mocked(api.putDeck).mock.calls.at(-1)![1];
    expect(saved.structure.chapters[0].topic).toBe("묶음이 만든 장");
    expect(saved.slides[0].slots).toMatchObject({ bullets: [{ text: "묶음이 만든 내용" }] });
  });

  it("편집 단계 충돌 안내 뒤 다른 단계로 가려 해도 옛 덱의 저장이 거절되면 떠나지 않고, 다시 읽은 뒤에는 새 덱이다", async () => {
    // 미저장 편집은 이탈 플러시가 옛 저장 ETag로 보낸다. 서버는 412로 거절하므로(If-Match) 옛 덱은 저장되지 않는다.
    // 모의 시험은 If-Match를 흉내 내지 않으므로 실제 서비스 재현은 α 묶음 리뷰의 두 탭 재현이 맡는다
    let rejectSave = false;
    vi.mocked(api.putDeck).mockImplementation(() => rejectSave
      ? Promise.reject(new ApiError(412, "다른 창이나 프로그램에서 이 프로젝트가 먼저 저장되었습니다."))
      : new Promise(() => {}));
    await openProject();
    await userEvent.click(stageButton("편집"));
    const topic = await screen.findByLabelText("장 주제");
    fireEvent.change(topic, { target: { value: "옛 덱의 편집" } });
    fireEvent.blur(topic);
    await otherTabBatchEnds(batchDeck);
    await screen.findByText("다른 창이나 프로그램에서 먼저 저장되었습니다.", { exact: false });
    rejectSave = true;
    await userEvent.click(stageButton("자료"));
    expect(stageButton("편집")).toHaveAttribute("aria-current", "step");  // 떠나지 않았다
    vi.spyOn(window, "confirm").mockReturnValue(true);
    await userEvent.click(screen.getByRole("button", { name: "서버 내용 다시 읽기" }));
    await waitFor(() => expect(screen.getByLabelText("장 주제")).toHaveValue("묶음이 만든 장"));
  });
});

describe("화면 문구에 탭 이름이 없다 (계획 4.1, 사실 22)", () => {
  // "브라우저 탭"은 브라우저의 탭을 뜻하므로 예외다
  const TAB_NAMES = /(자료|구조안|편집|검수 이력) 탭/;

  it("다섯 단계 화면 어디에도 옛 탭 이름이 보이지 않는다", async () => {
    vi.mocked(api.getDeck).mockResolvedValue({ ...deckWith(["하나"]), structure: { chapters: [] }, slides: [] });
    await openProject();
    for (const name of STAGES) {
      await userEvent.click(stageButton(name));
      await waitFor(() => expect(stageButton(name)).toHaveAttribute("aria-current", "step"));
      expect(document.body.textContent).not.toMatch(TAB_NAMES);
    }
  });

  it("보고 계획 복구 안내는 단계 이름으로 안내한다", () => {
    const { container, rerender } = render(<StoryPlanRecoveryGuidance hasDiagrams={false} />);
    expect(container.textContent).not.toMatch(TAB_NAMES);
    expect(container.textContent).toMatch(/구성 단계/);
    rerender(<StoryPlanRecoveryGuidance hasDiagrams />);
    expect(container.textContent).not.toMatch(TAB_NAMES);
  });
});

describe("고급 작업 (계획 4.1)", () => {
  it("문서 전체 변경과 근거 이동은 접힌 고급 작업 안에 있고, 패널이 열린 동안에는 접히지 않는다", async () => {
    await openProject();
    await userEvent.click(stageButton("구성"));
    const toggle = await screen.findByRole("button", { name: "문서 전체 변경과 근거 이동" });
    const details = toggle.closest("details")!;
    expect(details).toHaveClass("advanced-actions");
    expect(details.open).toBe(false);
    expect(within(details).getByText("고급 작업").tagName).toBe("SUMMARY");
    await userEvent.click(toggle);
    expect(details.open).toBe(true);
    details.open = false;  // 사용자가 요약을 눌러 접으려 한다
    fireEvent(details, new Event("toggle"));
    expect(details.open).toBe(true);
  });
});

describe("D3a-2 리뷰 반영", () => {
  const twoChapters = (): Deck => ({ ...deckWith(["하나"]), structure: { chapters: [
    { id: "c1", topic: "주제", conclusion: "", template: "bullet_box", source_refs: [] },
    { id: "c2", topic: "둘째 장", conclusion: "", template: "bullet_box", source_refs: [] }] } });
  const BODY = { template: "bullet_box" as const, bullets: [{ text: "생성", level: 0 as const }], conclusion: "결", footnote: "" };

  it("이 탭이 구성 단계에서 띄운 묶음의 종결을 진행 작업 조회가 먼저 봐도 구성 화면을 다시 마운트하지 않아 편집 단계로 옮긴다 (R1)", async () => {
    // 회귀 RED: 고치기 전 코드는 기준 조회 412 뒤 구성 화면을 다시 마운트해, 묶음을 따라가던 조회가 끊기고
    // 편집 단계 이동과 결과 안내가 사라졌다(실제 서비스 24회 중 3회)
    const deck = twoChapters();
    const complete: Deck = { ...deck, slides: [...deck.slides, { chapter_id: "c2", eyebrow: "", subtitle: "", slots: BODY }] };
    vi.mocked(api.getDeck).mockResolvedValue(deck);
    vi.mocked(api.putDeck).mockResolvedValue({ ok: true });
    const final = batchView([chapterView("c2", "succeeded", { result: chapterResult(BODY) })]);
    vi.mocked(api.startChapters).mockResolvedValue({ ...final, state: "running", outcome: null });
    // 첫 조회는 아직 실행 중이다. 구성 화면은 다음 조회까지 기다리고(1초), 그 사이에 진행 작업 조회가 종결을 먼저 본다
    vi.mocked(api.getJob).mockResolvedValueOnce({ ...final, state: "running", outcome: null }).mockResolvedValue(final);
    await openProject();
    await userEvent.click(stageButton("구성"));
    await userEvent.click(await screen.findByRole("button", { name: "승인하고 내용 생성" }));
    await waitFor(() => expect(api.getJob).toHaveBeenCalledTimes(1));
    vi.mocked(api.getDocumentChangeBasis).mockRejectedValue(
      new ApiError(412, "다른 창이나 프로그램에서 먼저 저장되었습니다. 최신 덱을 다시 읽어 주세요."));
    vi.mocked(api.getActiveJob).mockResolvedValueOnce(batchActive())
      .mockImplementation(async () => ({ active: null, ledger_available: true }));
    vi.mocked(api.getDeck).mockResolvedValue(complete);
    await act(async () => { window.dispatchEvent(new Event("focus")); });
    await waitFor(() => expect(api.getDocumentChangeBasis).toHaveBeenCalled());
    await waitFor(() => expect(stageButton("편집")).toHaveAttribute("aria-current", "step"), { timeout: 3000 });
  });

  it("저장 없이 단계를 떠나면 보조기기에 저장됨을 알리지 않는다 (R2)", async () => {
    vi.mocked(api.getDeck).mockResolvedValue(twoChapters());
    await openProject();
    await userEvent.click(stageButton("구성"));
    await userEvent.click(await screen.findByRole("button", { name: "둘째 장 삭제" }));
    expect(headerStatus()).toBe("변경사항 있음");
    await userEvent.click(stageButton("자료"));
    await waitFor(() => expect(headerStatus()).toBe("저장됨"));
    expect(document.querySelector(".project-topbar p.visually-hidden[role='status']")).toHaveTextContent("");
  });

  it("구성 단계의 문서 변경 패널에 적용하지 않은 입력이 있으면 머리는 저장됨이 아니다 (R3)", async () => {
    await openProject();
    await userEvent.click(stageButton("구성"));
    await userEvent.click(await screen.findByRole("button", { name: "문서 전체 변경과 근거 이동" }));
    await waitFor(() => expect(headerStatus()).toBe("저장됨"));
    fireEvent.change(await screen.findByLabelText("문서 후보 JSON"), { target: { value: "{}" } });
    await waitFor(() => expect(headerStatus()).toBe("변경사항 있음"));
    expect(document.querySelector(".header-save-status")).toHaveTextContent("적용하지 않은 입력이 있습니다");
  });

  it("지금 단계를 다시 고르면 플러시도 저장 상태 지우기도 하지 않는다 (R4)", async () => {
    vi.mocked(api.putDeck).mockResolvedValue({ ok: true });
    await openProject();
    await waitFor(() => expect(headerStatus()).toBe("저장됨"));
    await userEvent.type(screen.getByLabelText("보고서 제목"), " 고침");
    await userEvent.click(stageButton("보고 목적"));
    expect(api.putDeck).not.toHaveBeenCalled();
    expect(headerStatus()).toBe("변경사항 있음");
  });

  it("복구 화면에서 고른 장은 다른 단계에 갔다 돌아오면 다시 고르지 않는다 (R4)", async () => {
    const deck = twoChapters();
    vi.mocked(api.getDeck).mockResolvedValue({ ...deck, slides: [...deck.slides,
      { chapter_id: "c2", eyebrow: "", subtitle: "", slots: BODY }] });
    vi.mocked(api.listJobs).mockResolvedValue([{ ...batchView([]), kind: "chapter", target: "c2", candidate_status: "stale",
      stale_reasons: ["template_changed"], result: { status: "ok", usage: emptyUsage(), slots: BODY }, chapters: [] }]);
    await openProject();
    await userEvent.click(screen.getByRole("button", { name: "스냅샷 복구" }));
    await userEvent.click(await screen.findByRole("button", { name: "편집 단계로 옮겨 다시 생성" }));
    expect(await screen.findByLabelText("장 주제")).toHaveValue("둘째 장");
    await userEvent.click(stageButton("자료"));
    await userEvent.click(stageButton("편집"));
    expect(await screen.findByLabelText("장 주제")).toHaveValue("주제");
  });

  it("보존할 변경 없이 되돌리면 상단 머리의 저장 상태로 초점이 간다 (R5)", async () => {
    vi.mocked(api.putDeck).mockRejectedValue(new ApiError(412, "다른 창이나 프로그램에서 이 프로젝트가 먼저 저장되었습니다."));
    await openProject();
    await userEvent.click(stageButton("편집"));
    const topic = await screen.findByLabelText("장 주제");
    fireEvent.change(topic, { target: { value: "고침" } });
    fireEvent.blur(topic);
    // 자동 저장은 1.2초 뒤에 나가 412를 받는다
    await screen.findByRole("button", { name: "서버 내용으로 되돌리기" }, { timeout: 3000 });
    await userEvent.click(screen.getByRole("button", { name: "되돌리기 (Ctrl+Z)" }));  // 보존할 변경이 없어진다
    await userEvent.click(screen.getByRole("button", { name: "서버 내용으로 되돌리기" }));
    await waitFor(() => expect(document.activeElement).toBe(document.querySelector(".header-save-status")));
  });

  it("편집 단계에서 충돌로 변경을 보존하면 머리의 보존 건수가 늘어난다 (R5)", async () => {
    const draft = { id: "draft-20261010-100000-000001", saved_at: "2026-10-10T10:00:00+09:00",
      reason: "conflict" as const, source: "editor" as const, base_etag: null };
    vi.mocked(api.putDeck).mockRejectedValue(new ApiError(412, "다른 창이나 프로그램에서 이 프로젝트가 먼저 저장되었습니다."));
    vi.mocked(api.saveDraft).mockResolvedValue(draft);
    await openProject();
    await userEvent.click(stageButton("편집"));
    const topic = await screen.findByLabelText("장 주제");
    expect(screen.queryByRole("button", { name: /보존한 변경/ })).toBeNull();
    fireEvent.change(topic, { target: { value: "고침" } });
    fireEvent.blur(topic);
    vi.mocked(api.listDrafts).mockResolvedValue([draft]);
    await userEvent.click(await screen.findByRole("button", { name: "서버 내용으로 되돌리기" }, { timeout: 3000 }));
    expect(await screen.findByRole("button", { name: "보존한 변경 1건" })).toBeInTheDocument();
  });

  it("주안점과 목표 장수는 단계 이동과 묶음 종결 뒤 다시 마운트에도 남는다 (R6, 계획 4.4)", async () => {
    await openProject();
    await userEvent.click(stageButton("구성"));
    await userEvent.type(await screen.findByLabelText("문서의 주안점 및 원하는 결과 입력"), "경영진 관점");
    await userEvent.type(screen.getByLabelText("목표 장수"), "5");
    await userEvent.click(stageButton("자료"));
    await userEvent.click(stageButton("구성"));
    expect(await screen.findByLabelText("문서의 주안점 및 원하는 결과 입력")).toHaveValue("경영진 관점");
    await otherTabBatchEnds(batchDeck);
    await waitFor(() => expect(screen.getByLabelText("1번 장 주제")).toHaveValue("묶음이 만든 장"));
    expect(screen.getByLabelText("문서의 주안점 및 원하는 결과 입력")).toHaveValue("경영진 관점");
    expect(screen.getByLabelText("목표 장수")).toHaveValue(5);
  });

  it("편집 단계를 새 덱으로 다시 마운트해도 고른 장을 유지한다 (R6)", async () => {
    const deck = twoChapters();
    const withBoth = { ...deck, slides: [...deck.slides, { chapter_id: "c2", eyebrow: "", subtitle: "", slots: BODY }] };
    vi.mocked(api.getDeck).mockResolvedValue(withBoth);
    vi.mocked(api.measure).mockResolvedValue({ ...planWith(["하나"]), slides: [] });
    await openProject();
    await userEvent.click(stageButton("편집"));
    await userEvent.click(await screen.findByRole("button", { name: /둘째 장/ }));
    expect(await screen.findByLabelText("장 주제")).toHaveValue("둘째 장");
    await otherTabBatchEnds({ ...withBoth, meta: { ...withBoth.meta, title: "묶음 뒤" } });
    await waitFor(() => expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("묶음 뒤"));
    expect(screen.getByLabelText("장 주제")).toHaveValue("둘째 장");
  });

  it("단계를 옮기면 초점이 새 현재 단계 버튼에 있다 (R12)", async () => {
    await openProject();
    // 초점을 단계 목록 밖(본문)에 두고 누른다. jsdom은 잠긴 버튼에서 초점을 빼지 않으므로, 초점을 미리 그 버튼에
    // 두면 반영이 없어도 통과했다 (D3a 묶음 리뷰 A18)
    (document.activeElement as HTMLElement | null)?.blur();
    fireEvent.click(stageButton("자료"));
    await waitFor(() => expect(document.activeElement).toBe(stageButton("자료")));
    await userEvent.click(screen.getByRole("button", { name: "스냅샷 복구" }));
    await waitFor(() => expect(document.querySelector(".recovery-screen")).not.toBeNull());
    await userEvent.click(stageButton("구성"));
    await waitFor(() => expect(document.activeElement).toBe(stageButton("구성")));
  });
});

describe("단계 상태 표시와 공통 알림 지점 (D3a-3, 계획 4.2, 4.5)", () => {
  it("현재 단계와 단계 상태는 서로 다른 요소다. 상태는 버튼 밖에 있고 aria-describedby로 이어진다", async () => {
    await openProject();
    await waitFor(() => expect(statusOf("structure")).toHaveTextContent("준비됨"));
    const button = stageButton("구성");
    expect(button).toHaveAttribute("aria-describedby", "stage-status-structure");
    expect(button).not.toContainElement(statusOf("structure"));
    expect(button.textContent).toBe("3구성");  // 버튼 안에는 번호와 단계 이름뿐이다
    // 선택한 단계를 완료로 보이지 않는다: 현재 단계(보고 목적)의 상태는 서버의 확인 필요다
    expect(stageButton("보고 목적")).toHaveAttribute("aria-current", "step");
    expect(statusOf("purpose")).toHaveTextContent("확인 필요");
    expect(statusOf("purpose")).toHaveTextContent("보고 유형을 직접 골랐는지는 아직 기록하지 않습니다");
  });

  it("검토 단계는 남은 부분을 말하고, 준비됨이면 체크 없는 초안 확인됨이다", async () => {
    await openProject();
    await waitFor(() => expect(statusOf("review")).toHaveTextContent("사람 검토가 남았습니다"));
    vi.mocked(api.getProgress).mockResolvedValue({ ...PROGRESS, stages: PROGRESS.stages!.map((st) =>
      st.stage === "review" ? { ...st, state: "ready" as const, reasons: [] } : st) });
    await act(async () => notifyProject({ kind: "saved", project: project.name }));
    await waitFor(() => expect(statusOf("review")).toHaveTextContent("초안 확인됨"));
    expect(within(statusOf("review")!).getByRole("img")).toHaveAccessibleName("초안 점검 통과");
  });

  it("조회가 실패하면 단계 상태를 확인하지 못함으로 보이고 준비됨으로 두지 않는다", async () => {
    vi.mocked(api.getProgress).mockRejectedValue(new ApiError(503, "진행 상태를 읽지 못했습니다."));
    await openProject();
    await waitFor(() => expect(statusOf("structure")).toHaveTextContent("확인하지 못함"));
    expect(nav().textContent).not.toMatch(/준비됨/);
  });

  it("공통 알림(저장, 작업 등록, 작업 종결) 뒤 이 프로젝트의 단계 상태를 다시 읽는다. 다른 프로젝트의 알림은 무시한다", async () => {
    await openProject();
    await waitFor(() => expect(api.getProgress).toHaveBeenCalled());
    const before = vi.mocked(api.getProgress).mock.calls.length;
    await act(async () => notifyProject({ kind: "saved", project: "다른 프로젝트" }));
    expect(vi.mocked(api.getProgress).mock.calls.length).toBe(before);
    for (const kind of ["saved", "job_started", "job_ended"] as const) {
      await act(async () => notifyProject({ kind, project: project.name }));
    }
    expect(vi.mocked(api.getProgress).mock.calls.length).toBe(before + 3);
  });

  it("늦게 온 옛 응답은 새 응답을 덮지 않는다", async () => {
    await openProject();
    await waitFor(() => expect(statusOf("structure")).toHaveTextContent("준비됨"));
    const slow = deferred<ProjectProgress>();
    vi.mocked(api.getProgress).mockReturnValueOnce(slow.promise).mockResolvedValueOnce({ ...PROGRESS,
      stages: PROGRESS.stages!.map((st) => st.stage === "structure" ? { ...st, state: "needs_review" as const, reasons: ["stale_story_plan" as const] } : st) });
    await act(async () => notifyProject({ kind: "saved", project: project.name }));
    await act(async () => notifyProject({ kind: "saved", project: project.name }));
    await waitFor(() => expect(statusOf("structure")).toHaveTextContent("확인 필요"));
    await act(async () => slow.resolve(PROGRESS));
    expect(statusOf("structure")).toHaveTextContent("확인 필요");
  });

  it("현재 단계에 저장하지 않은 변경이 있으면 서버 상태 대신 작성 중이다", async () => {
    await openProject();
    await userEvent.click(stageButton("구성"));
    await waitFor(() => expect(statusOf("structure")).toHaveTextContent("준비됨"));
    await userEvent.type(await screen.findByLabelText("보고 질문"), "질문");
    expect(statusOf("structure")).toHaveTextContent("작성 중");
    expect(statusOf("structure")).not.toHaveTextContent("준비됨");
  });

  it("준비됨에 붙은 사유는 단계 목록에 없고 그 단계 화면의 한계 안내로 보인다", async () => {
    await openProject();
    await waitFor(() => expect(statusOf("sources")).toHaveTextContent("준비됨"));
    expect(nav().textContent).not.toMatch(/부분 추출 경고/);
    await userEvent.click(stageButton("자료"));
    expect(await screen.findByText(/부분 추출 경고는 아직 기록하지 않아/)).toBeInTheDocument();
  });

  it("검토 화면은 자동 검사(내보낸 파일 기준), 사람 검토, 파일 저장을 따로 보인다", async () => {
    await openProject();
    await userEvent.click(stageButton("검토와 내보내기"));
    const parts = await screen.findByRole("list", { name: "검토의 세 부분" });
    const items = within(parts).getAllByRole("listitem").map((li) => li.textContent);
    expect(items).toEqual([expect.stringMatching(/^자동 검사\(내보낸 파일 기준\).*준비됨/),
      expect.stringMatching(/^사람 검토.*시작 전/), expect.stringMatching(/^파일 저장.*준비됨/)]);
    expect(screen.getByText("자동 검사는 내보낸 파일의 사전 점검이며 의미와 시각 품질의 통과가 아닙니다")).toBeInTheDocument();
  });

  it("구성 단계 옆에 가장 최근 장 생성 묶음의 장 요약을 보인다", async () => {
    vi.mocked(api.getProgress).mockResolvedValue({ ...PROGRESS, jobs: [batchView([
      chapterView("c1", "succeeded"), chapterView("c2", "failed")], { state: "failed", outcome: "partial" })] });
    await openProject();
    await waitFor(() => expect(statusOf("structure")).toHaveTextContent("2장 중 1장 실패"));
  });
});

describe("D3a-3 리뷰 반영", () => {
  it("창 초점을 얻으면 단계 상태를 다시 읽는다 (R5)", async () => {
    await openProject();
    await waitFor(() => expect(api.getProgress).toHaveBeenCalled());
    const before = vi.mocked(api.getProgress).mock.calls.length;
    await act(async () => { window.dispatchEvent(new Event("focus")); });
    await waitFor(() => expect(vi.mocked(api.getProgress).mock.calls.length).toBeGreaterThan(before));
  });

  it("진행 작업이 바뀌면(다른 탭의 작업 시작과 종결) 단계 상태를 다시 읽는다 (R5)", async () => {
    vi.mocked(api.getActiveJob).mockResolvedValueOnce({ active: null, ledger_available: true })
      .mockResolvedValueOnce(batchActive("diagram")).mockImplementation(async () => ({ active: null, ledger_available: true }));
    await openProject();
    const before = vi.mocked(api.getProgress).mock.calls.length;
    await act(async () => { window.dispatchEvent(new Event("focus")); });
    // 초점 1회 + 진행 작업 시작 1회 + 종결 1회
    await waitFor(() => expect(vi.mocked(api.getProgress).mock.calls.length).toBeGreaterThanOrEqual(before + 3));
  });

  it("잠긴 단계 버튼은 상태와 함께 잠금 사유를 접근 가능한 설명으로 보인다 (R7)", async () => {
    vi.mocked(api.getActiveJob).mockResolvedValue(batchActive());
    render(<ProjectView project={project} onBack={() => {}} jobPollMs={60_000} />);
    await waitFor(() => expect(stageButton("편집")).toBeDisabled());
    await waitFor(() => expect(stageButton("편집")).toHaveAccessibleDescription(/AI 생성이 끝나면 이동할 수 있습니다/));
    expect(stageButton("편집")).toHaveAccessibleDescription(/준비됨/);
  });

  it("조회가 실패하면 지난 응답의 장 요약과 한계 안내를 보이지 않는다 (R14)", async () => {
    vi.mocked(api.getProgress).mockResolvedValue({ ...PROGRESS, jobs: [batchView([
      chapterView("c1", "succeeded"), chapterView("c2", "failed")], { state: "failed", outcome: "partial" })] });
    await openProject();
    await waitFor(() => expect(statusOf("structure")).toHaveTextContent("2장 중 1장 실패"));
    vi.mocked(api.getProgress).mockRejectedValue(new ApiError(503, "진행 상태를 읽지 못했습니다."));
    await act(async () => notifyProject({ kind: "saved", project: project.name }));
    await waitFor(() => expect(statusOf("structure")).toHaveTextContent("확인하지 못함"));
    expect(statusOf("structure")).not.toHaveTextContent("2장 중 1장 실패");
    await userEvent.click(stageButton("자료"));
    await screen.findByLabelText("자료 파일 선택");
    expect(screen.queryByText(/부분 추출 경고/)).toBeNull();
  });

  it("검토 화면은 첫 조회 전에 읽는 중이라고 하고, 시작 전 부분에도 서버 사유를 붙인다 (R15)", async () => {
    const slow = deferred<ProjectProgress>();
    vi.mocked(api.getProgress).mockReturnValue(slow.promise);
    await openProject();
    await userEvent.click(stageButton("검토와 내보내기"));
    expect(await screen.findByText("검토 상태를 읽는 중입니다.")).toBeInTheDocument();
    await act(async () => slow.resolve({ ...PROGRESS, stages: PROGRESS.stages!.map((st) => st.stage !== "review" ? st : {
      ...st, state: "not_started" as const, reasons: [], parts: [
        { name: "auto_checks", state: "not_started", reasons: [] },
        { name: "human_review", state: "not_started", reasons: [] },
        { name: "file", state: "not_started", reasons: ["no_export"] }] }) }));
    const parts = await screen.findByRole("list", { name: "검토의 세 부분" });
    expect(within(parts).getAllByRole("listitem")[2]).toHaveTextContent("아직 내보낸 파일이 없습니다");
  });
});
