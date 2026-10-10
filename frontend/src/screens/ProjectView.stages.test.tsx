// 다섯 단계 셸의 계약 시험 (개정판 D3a-2, 계획 4.1). 단계 이동과 현재 단계, 상단 머리의 저장 상태 출처,
// 보존 건수, 복구 화면과 단계, 묶음 종결 뒤 분기(β R1 새 분기), 순서 시나리오, 탭 이름 없는 문구를 지킨다
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api, ApiError, type Deck } from "../api/client";
import { deckWith, planWith, preset, project } from "../test/fixtures";
import { emptyUsage } from "../test/usage";
import { StoryPlanRecoveryGuidance } from "./StoryPlanRecoveryGuidance";
import { ProjectView } from "./ProjectView";

vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return { ...mod, api: { ...mod.api,
    getDeck: vi.fn(), listSources: vi.fn(), readSource: vi.fn(), measure: vi.fn(), putDeck: vi.fn(), getPreset: vi.fn(),
    listSnapshots: vi.fn(), listExports: vi.fn(), listDrafts: vi.fn(), saveDraft: vi.fn(), getActiveJob: vi.fn(),
    listJobs: vi.fn(), getDocumentChangeBasis: vi.fn(), getStatus: vi.fn() } };
});
vi.mock("./AISettingsPanel", () => ({ AISettingsPanel: () => null }));

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
