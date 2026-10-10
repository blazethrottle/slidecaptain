import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api, ApiError, savedEtag, type Deck, type Preset, type QualityReport, type RenderPlan, type UploadResult } from "../api/client";
import qualityFixture from "../../../backend/tests/fixtures/q1b1-quality.json";
import { deferred } from "../test/fixtures";
import { emptyUsage } from "../test/usage";
import { ProjectView } from "./ProjectView";

vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return { ...mod, api: { ...mod.api,
    getDeck: vi.fn(), listSources: vi.fn(), readSource: vi.fn(), createSnapshot: vi.fn(), exportDeck: vi.fn(),
    measure: vi.fn(), putDeck: vi.fn(), listSnapshots: vi.fn(), restoreSnapshot: vi.fn(),
    getPreset: vi.fn(), generateChapter: vi.fn(), uploadSource: vi.fn(), listExports: vi.fn(),
    saveDraft: vi.fn(), listDrafts: vi.fn(), getActiveJob: vi.fn(), listJobs: vi.fn(), prepareAi: vi.fn(),
    startChapters: vi.fn(), getJob: vi.fn(), cancelJob: vi.fn(), getDocumentChangeBasis: vi.fn() } };
});

// D2a-2: 충돌 시 보존 요청은 기본으로 성공한다
beforeEach(() => {
  vi.mocked(api.saveDraft).mockResolvedValue({ id: "draft-20261008-100000-000001",
    saved_at: "2026-10-08T10:00:00+09:00", reason: "generation_unsaved", source: "structure_approval", base_etag: null });
  vi.mocked(api.listDrafts).mockResolvedValue([]);
  // D2b-5a: 진행 중 작업이 없고 원장을 쓸 수 있는 상태가 기본이다
  vi.mocked(api.getActiveJob).mockResolvedValue({ active: null, ledger_available: true });
  vi.mocked(api.listJobs).mockResolvedValue([]);
  vi.mocked(api.prepareAi).mockResolvedValue({ "X-AI-Consent": "SlideCaptain" });
});

// 등록은 되었고 조회는 끝나지 않는 장 생성 묶음
function hangingBatch() {
  vi.mocked(api.startChapters).mockResolvedValue({
    id: "job-1", project: project.name, kind: "chapters", state: "running", target: null, params: {},
    candidate_status: "none", outcome: null, owner: "this_instance", created_at: "2026-10-08T10:00:00+09:00",
    started_at: null, finished_at: null, provider: null, model: null, base_etag: null, current_etag: null,
    relevance_hash: null, stale_reasons: [], cancel_requested: false, error: null, result: null,
    chapters: [{ chapter_id: "c1", position: 0, state: "running", candidate_status: "none", error: null, result: null,
      started_at: null, finished_at: null }],
  });
  vi.mocked(api.getJob).mockImplementation(() => new Promise(() => {}));
}

// 업로드 잠금과 beforeunload 테스트가 공용으로 쓰는 XLSX 픽스처와 헬퍼 (계획서 B4)
const XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";

function dispatchBeforeUnload(): boolean {
  const ev = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(ev);
  return ev.defaultPrevented;
}

const project = { name: "p1", title: "제목", updated_at: "", status: "ok" as const };

it("내용이 없는 프로젝트에서도 도식을 작성하고 작성 중 이탈/새로고침을 보호한다", async () => {
  const empty = { ...deckWithSlide, structure: { chapters: [] }, slides: [] };
  vi.mocked(api.getDeck).mockResolvedValue(empty);
  vi.mocked(api.listSources).mockResolvedValue([]);
  vi.mocked(api.getPreset).mockResolvedValue(preset);
  vi.mocked(api.measure).mockResolvedValue({ ...plan, slides: [] });
  render(<ProjectView project={project} onBack={vi.fn()} />);
  const editTab = await screen.findByRole("button", { name: "편집" });
  expect(editTab).toBeEnabled();
  await userEvent.click(editTab);
  await userEvent.click(screen.getByRole("button", { name: "도식 추가" }));
  expect(dispatchBeforeUnload()).toBe(true);
  await userEvent.click(screen.getByRole("button", { name: "자료" }));
  expect(screen.getByRole("dialog")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "편집" })).toHaveAttribute("aria-current", "step");
  await userEvent.click(screen.getByRole("button", { name: "변경 버리고 닫기" }));
  expect(dispatchBeforeUnload()).toBe(false);
  await userEvent.click(screen.getByRole("button", { name: "자료" }));
  expect(screen.getByRole("button", { name: "자료" })).toHaveAttribute("aria-current", "step");
  expect(api.putDeck).not.toHaveBeenCalled();
});

const emptyHistory = { checked_at: "2026-09-13T12:00:00Z", current_input_fingerprint: null,
  current_input_error: null, items: [], total: 0, offset: 0, limit: 20 };

it("복구 대상 프로젝트에서도 덱 없이 검수 이력을 조회한다", async () => {
  vi.mocked(api.listExports).mockResolvedValue(emptyHistory);
  vi.mocked(api.listSnapshots).mockResolvedValue([]);
  render(<ProjectView project={{ ...project, status: "needs_recovery" }} onBack={() => {}} />);
  expect(await screen.findByText("내보내기 이력이 없습니다.")).toBeInTheDocument();
  expect(api.getDeck).not.toHaveBeenCalled();
});

it("스냅샷 복구 화면에서는 이력 선택을 잠그고 닫은 뒤 다시 열 수 있다", async () => {
  vi.mocked(api.getDeck).mockResolvedValue(deckWithSlide);
  vi.mocked(api.listSources).mockResolvedValue([]);
  vi.mocked(api.listSnapshots).mockResolvedValue([]);
  vi.mocked(api.listExports).mockResolvedValue(emptyHistory);
  render(<ProjectView project={project} onBack={() => {}} />);
  await userEvent.click(await screen.findByRole("button", { name: "스냅샷 복구" }));
  // 다시 씀(D3a-2): 복구 화면은 단계가 아니다. 열린 동안 현재 단계 표시가 없고, 단계를 고르면 복구 화면을 닫고
  // 그 단계로 간다(계획 4.1). 옛 탭 구조는 복구 화면이 열린 동안 검수 이력 탭을 잠갔다
  expect(document.querySelector("[aria-current='step']")).toBeNull();
  const reads = vi.mocked(api.getDeck).mock.calls.length;
  await userEvent.click(screen.getByRole("button", { name: "검토와 내보내기" }));
  expect(await screen.findByText("내보내기 이력이 없습니다.")).toBeInTheDocument();
  expect(document.querySelector(".recovery-screen")).toBeNull();
  expect(screen.getByRole("button", { name: "검토와 내보내기" })).toHaveAttribute("aria-current", "step");
  expect(vi.mocked(api.getDeck).mock.calls.length).toBe(reads + 1);  // 복구 화면에서 처분했을 수 있어 덱을 다시 읽는다
  await userEvent.click(screen.getByRole("button", { name: "스냅샷 복구" }));
  const recovery = document.querySelector(".recovery-screen") as HTMLElement;
  await userEvent.click(within(recovery).getByRole("button", { name: "복구 화면 닫기" }));
  await waitFor(() => expect(document.querySelector(".recovery-screen")).toBeNull());
});

it("이력 화면에서 새로 내보내면 목록을 다시 조회한다", async () => {
  vi.mocked(api.getDeck).mockResolvedValue(deckWithSlide);
  vi.mocked(api.listSources).mockResolvedValue([]);
  vi.mocked(api.listExports).mockResolvedValue(emptyHistory);
  vi.mocked(api.createSnapshot).mockResolvedValue({ ok: true });
  vi.mocked(api.exportDeck).mockResolvedValue({ path: "/exports/report_v002.pptx",
    quality_path: "/exports/report_v002.quality.json", quality: qualityFixture.matched as QualityReport });
  render(<ProjectView project={project} onBack={() => {}} />);
  await userEvent.click(await screen.findByRole("button", { name: "검토와 내보내기" }));
  await screen.findByText("내보내기 이력이 없습니다.");
  await userEvent.click(screen.getByRole("button", { name: "초안 PPTX 내보내기" }));
  await waitFor(() => expect(api.listExports).toHaveBeenCalledTimes(2));
});

const deckWithSlide: Deck = {
  schema_version: 1,
  meta: { title: "제목", report_type: "research", audience: "", presenter: "", preset_overrides: {} },
  structure: { chapters: [
    { id: "c1", topic: "주제", conclusion: "", template: "bullet_box", source_refs: [] }] },
  slides: [{ chapter_id: "c1", eyebrow: "", subtitle: "", slots: {
    template: "bullet_box", bullets: [], conclusion: "결", footnote: "" } }],
};

// 편집한 값이 실제로 반영되는지 확인하려면 미리보기(plan)가 가리키는 인덱스 0에
// 실제 불릿이 있어야 한다 (EditorScreen.test.tsx 픽스처와 동일 패턴)
const deckWithEditableSlide: Deck = {
  schema_version: 1,
  meta: { title: "제목", report_type: "research", audience: "", presenter: "", preset_overrides: {} },
  structure: { chapters: [
    { id: "c1", topic: "주제", conclusion: "", template: "bullet_box", source_refs: [] }] },
  slides: [{ chapter_id: "c1", eyebrow: "", subtitle: "", slots: {
    template: "bullet_box", bullets: [{ text: "하나", level: 0 }], conclusion: "결론", footnote: "" } }],
};

// 편집 탭에서 DesignPanel이 함께 그려지므로, 그 프리셋 조회 목이 필요하다 (EditorScreen.test.tsx 픽스처 재사용)
const preset = {
  fonts: { korean: "Noto Sans KR", latin: "Noto Sans KR" },
  font_roles: { cover_title_pt: 28, section_title_pt: 24, title_pt: 20, subtitle_pt: 14,
    body_pt: 12, box_pt: 12, table_pt: 12, footnote_pt: 9, page_number_pt: 9 },
  colors: { text: "202020", accent: "1F4E79", box_fill: "EEF3F9",
    table_header_fill: "F2F2F2", border: "D0D7E2", background: "FFFFFF" },
  spacing: {}, bullet_marker: { char: "•", font: "Arial" },
  page_width_pt: 960, page_height_pt: 540, language: "ko-KR",
} as unknown as Preset;

// 편집 탭 미리보기(실측 결과)도 EditorScreen.test.tsx 픽스처를 재사용한다
const plan: RenderPlan = {
  page_width_pt: 960, page_height_pt: 540,
  style: {
    korean_font: "Noto Sans KR", latin_font: "Noto Sans KR", text_color: "202020",
    box_padding_pt: 10, line_spacing: 1.4, bullet_indent_pt: 18, bullet_gap_pt: 6,
    table_cell_pad_x_pt: 6, table_cell_pad_y_pt: 3, border_width_pt: 0.75,
    bullet_char: "•", bullet_font: "Arial",
  },
  slides: [{ chapter_id: "c1", template: "bullet_box", warnings: [], frames: [
    { name: "c1:bullets", x: 50, y: 92, w: 860, h: 300, fill: null, border: null,
      valign: "top", table: null,
      paras: [{ text: "하나", level: 0, font_pt: 12, bold: false, color: "202020",
        align: "left", bullet: true, lines: ["하나"] }] },
  ] }],
};

it("내보내기는 스냅샷을 먼저 남기고 경로를 보여준다", async () => {
  vi.mocked(api.getDeck).mockResolvedValue(deckWithSlide);
  vi.mocked(api.listSources).mockResolvedValue([]);
  vi.mocked(api.createSnapshot).mockResolvedValue({ ok: true });
  vi.mocked(api.exportDeck).mockResolvedValue({ path: "C:\\exports\\제목_v001.pptx",
    quality_path: "C:\\exports\\제목_v001.quality.json", quality: qualityFixture.matched as QualityReport });
  render(<ProjectView project={project} onBack={() => {}} />);
  await userEvent.click(await screen.findByRole("button", { name: "검토와 내보내기" }));  // 다시 씀(D3a-2): 내보내기는 검토 단계에 있다
  await userEvent.click(await screen.findByText("초안 PPTX 내보내기"));
  const result = await screen.findByText(/제목_v001\.pptx/);
  expect(result).toHaveAttribute("role", "status");
  expect(result).toHaveTextContent("초안 내보내기 완료");
  expect(result).toHaveTextContent("C:\\exports\\제목_v001.quality.json");
  expect(result).toHaveTextContent("검수 통과를 뜻하지 않습니다");
  expect(screen.getByText(/현재 산출물은 검수 전 초안입니다/)).toBeInTheDocument();
  expect(api.createSnapshot).toHaveBeenCalledWith("p1");  // 내보내기 직전 스냅샷 (결정 1)
  expect(api.exportDeck).toHaveBeenCalledWith("p1");
  // 스냅샷이 내보내기보다 먼저 호출됨을 호출 순서로 단언 (2026-08-29 태스크 16 리뷰 보강)
  const snapOrder = vi.mocked(api.createSnapshot).mock.invocationCallOrder[0];
  const exportOrder = vi.mocked(api.exportDeck).mock.invocationCallOrder[0];
  expect(snapOrder).toBeLessThan(exportOrder);
});

it("빈 덱은 초안 내보내기 버튼을 잠그고 요청을 보내지 않는다", async () => {
  vi.mocked(api.getDeck).mockResolvedValue({
    ...deckWithSlide, structure: { chapters: [] }, slides: [],
  });
  vi.mocked(api.listSources).mockResolvedValue([]);
  render(<ProjectView project={project} onBack={() => {}} />);
  await userEvent.click(await screen.findByRole("button", { name: "검토와 내보내기" }));  // 다시 씀(D3a-2): 내보내기는 검토 단계에 있다
  const button = await screen.findByRole("button", { name: "초안 PPTX 내보내기" });
  expect(button).toBeDisabled();
  await userEvent.click(button);
  expect(api.createSnapshot).not.toHaveBeenCalled();
  expect(api.exportDeck).not.toHaveBeenCalled();
  expect(screen.getByText(/현재 산출물은 검수 전 초안입니다/)).toBeInTheDocument();
});

it("서버의 내보내기 거절은 오류로 표시하고 성공 경로를 표시하지 않는다", async () => {
  // 화면을 읽은 뒤 서버 상태가 바뀌어도 422를 성공으로 표시하면 안 된다.
  vi.mocked(api.getDeck).mockResolvedValue(deckWithSlide);
  vi.mocked(api.listSources).mockResolvedValue([]);
  vi.mocked(api.createSnapshot).mockResolvedValue({ ok: true });
  vi.mocked(api.exportDeck).mockRejectedValue(new ApiError(422, "내보낼 슬라이드가 없습니다."));
  render(<ProjectView project={project} onBack={() => {}} />);
  await userEvent.click(await screen.findByRole("button", { name: "검토와 내보내기" }));  // 다시 씀(D3a-2): 내보내기는 검토 단계에 있다
  await userEvent.click(await screen.findByRole("button", { name: "초안 PPTX 내보내기" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("내보낼 슬라이드가 없습니다");
  expect(screen.queryByText(/초안 내보내기 완료/)).toBeNull();
  expect(screen.getByText(/현재 산출물은 검수 전 초안입니다/)).toBeInTheDocument();
});

it("복구가 필요한 프로젝트는 복구 화면으로 진입한다", async () => {
  vi.mocked(api.listSnapshots).mockResolvedValue([]);
  render(<ProjectView project={{ ...project, status: "needs_recovery" }} onBack={() => {}} />);
  // /스냅샷 복구/는 교체 전 임시 안내문에도 있던 문구라 RecoveryScreen 진입을 판별하지 못한다.
  // listSnapshots가 빈 목록을 반환할 때만 나오는 RecoveryScreen 고유 산출로 단언한다
  // (2026-08-29 태스크 16 리뷰 정정)
  expect(await screen.findByText("되돌릴 수 있는 저장 시점이 없습니다.")).toBeInTheDocument();
});

it("마지막 편집 저장에 실패하면 검토 단계로 옮기지 않아 내보낼 수 없다", async () => {
  // 다시 씀(D3a-2): 내보내기가 검토 단계 화면 안으로 옮겨, 편집 단계의 미저장 편집은 검토 단계로 옮기는
  // 이탈 플러시가 먼저 막는다. 검토 단계 안의 내보내기 전 플러시는 ProjectView.reviews.test.tsx가 지킨다
  vi.mocked(api.getDeck).mockResolvedValue(deckWithSlide);
  vi.mocked(api.listSources).mockResolvedValue([]);
  vi.mocked(api.measure).mockResolvedValue(plan);
  vi.mocked(api.getPreset).mockResolvedValue(preset);
  vi.mocked(api.putDeck).mockRejectedValue(new Error("저장 실패"));
  render(<ProjectView project={project} onBack={() => {}} />);
  await userEvent.click(await screen.findByRole("button", { name: "편집" }));
  // 속성 패널도 같은 텍스트를 보여주므로, 미리보기 영역으로 조회를 한정한다 (EditorScreen.test.tsx와 동일 패턴)
  const preview = () => within(document.querySelector(".editor-center") as HTMLElement);
  await userEvent.click(await preview().findByText("하나"));
  await userEvent.click(preview().getByText("하나"));
  const box = await screen.findByLabelText("내용 수정");
  await userEvent.clear(box);
  await userEvent.type(box, "고침{Enter}");
  // 기본 timings(1.2초 디바운스)에서는 자동 저장이 아직 발화하지 않고, 아래 내보내기 클릭이
  // flushSave로 미저장분을 감지해 putDeck을 호출한다
  await userEvent.click(screen.getByRole("button", { name: "검토와 내보내기" }));
  // EditorScreen도 같은 실패로 자체 오류 배너(role=alert)를 띄우므로, findByRole("alert") 단일 조회
  // 대신 중단 안내 문구와 role=alert 컨테이너를 함께 확인해 정밀화한다 (조정 사유: 배너 2개 동시 존재)
  const banner = await screen.findByText(
    "마지막 편집을 저장하지 못해 이동을 중단했습니다. 저장 상태를 확인한 뒤 다시 시도해 주세요.",
  );
  expect(banner.closest('[role="alert"]')).not.toBeNull();
  expect(screen.queryByRole("button", { name: "초안 PPTX 내보내기" })).toBeNull();
  expect(api.exportDeck).not.toHaveBeenCalled();
});

it("탭 전환 전 편집기 플러시를 기다린 뒤 다음 탭을 연다", async () => {
  vi.mocked(api.getDeck).mockResolvedValue(deckWithEditableSlide);
  vi.mocked(api.listSources).mockResolvedValue([]);
  vi.mocked(api.measure).mockResolvedValue(plan);
  vi.mocked(api.getPreset).mockResolvedValue(preset);
  // putDeck 응답을 붙잡아 둔다: 응답이 오기 전까지 편집 화면이 유지되어야 플러시 선행이 증명된다
  // (즉시 resolve하면 setTab이 플러시 이전이든 이후든 결과 DOM이 같아져 판별이 안 된다)
  let resolvePut = (_v: { ok: true }) => {};
  vi.mocked(api.putDeck).mockImplementation(
    () => new Promise((resolve) => { resolvePut = resolve; }));
  render(<ProjectView project={project} onBack={() => {}} />);
  await userEvent.click(await screen.findByText("편집"));
  const preview = () => within(document.querySelector(".editor-center") as HTMLElement);
  await userEvent.click(await preview().findByText("하나"));
  await userEvent.click(preview().getByText("하나"));
  const box = await screen.findByLabelText("내용 수정");
  await userEvent.clear(box);
  await userEvent.type(box, "고침{Enter}");
  // 기본 timings(1.2초 디바운스)에서는 자동 저장이 아직 발화하지 않은 상태에서 구조안 탭으로 전환한다:
  // switchTab의 선행 플러시가 없으면 이 편집은 putDeck 호출 없이 유실된다 (Task 16 플러시 실패 테스트 패턴 재사용)
  await userEvent.click(screen.getByRole("button", { name: "구성" }));
  await waitFor(() => expect(api.putDeck).toHaveBeenCalled());
  const [, savedDeck] = vi.mocked(api.putDeck).mock.calls[0];
  const slots = savedDeck.slides[0].slots;
  expect(slots.template === "bullet_box" && slots.bullets?.[0].text).toBe("고침");
  // putDeck 응답이 오기 전에는 아직 편집 화면이다: 플러시를 기다리지 않고 곧장 탭을
  // 전환했다면 이 시점에 이미 구조안 화면(옛 덱으로 초기화된 draft)이 떠 있을 것이다
  expect(document.querySelector(".editor-screen")).not.toBeNull();
  expect(document.querySelector(".structure-screen")).toBeNull();
  // 플러시가 응답한 뒤에야 구조안 화면으로 전환된다
  resolvePut({ ok: true });
  await waitFor(() => expect(document.querySelector(".structure-screen")).not.toBeNull());
  expect(document.querySelector(".editor-screen")).toBeNull();
});

it("장별 순차 생성이 진행 중일 때는 편집 탭으로 이동할 수 없다", async () => {
  // 구조안이 이미 있고(승인 전) 슬라이드는 아직 없는 프로젝트: 승인 즉시 순차 생성이 시작된다
  const deckWithStructure: Deck = {
    schema_version: 1,
    meta: { title: "제목", report_type: "research", audience: "", presenter: "", preset_overrides: {} },
    structure: { chapters: [
      { id: "c1", topic: "표지", conclusion: "", template: "cover", source_refs: [] }] },
    slides: [],
  };
  vi.mocked(api.getDeck).mockResolvedValue(deckWithStructure);
  vi.mocked(api.listSources).mockResolvedValue([]);
  vi.mocked(api.putDeck).mockResolvedValue({ ok: true });
  hangingBatch();  // 끝나지 않는 장 생성 묶음
  render(<ProjectView project={project} onBack={() => {}} />);
  await userEvent.click(await screen.findByRole("button", { name: "구성" }));
  await userEvent.click(await screen.findByRole("button", { name: "승인하고 내용 생성" }));
  const editorBtn = screen.getByRole("button", { name: "편집" });
  await waitFor(() => expect(editorBtn).toBeDisabled());
  // hasSlides가 false라서가 아니라 생성 진행 중이라서 막혔음을 문구로 구분한다
  expect(editorBtn).toHaveAttribute("title", "AI 생성이 끝나면 이동할 수 있습니다");
  const sourcesBtn = screen.getByRole("button", { name: "자료" });
  expect(sourcesBtn).toBeDisabled();
  // 다시 씀(D3a-2): 내보내기는 검토 단계 화면 안에 있으므로 그 단계로 가는 버튼이 잠김을 본다
  expect(screen.getByRole("button", { name: "검토와 내보내기" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "보고 목적" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "스냅샷 복구" })).toBeDisabled();
  // 구조안 탭 자체는 진행 표시가 그 화면에 있으므로 잠그지 않는다
  expect(screen.getByRole("button", { name: "구성" })).not.toBeDisabled();
});

// 충돌 배너 (2026-09-03 A5): 구조안과 복구 화면의 412는 ProjectView 배너의 "서버 내용 다시 읽기"로 회복한다
// (자료 탭 경로는 ProjectView.flush.test.tsx)
it("구조안 승인 반영에서 412를 받으면 배너가 뜨고, 다시 읽기를 누르면 최신 덱으로 다시 마운트한다 (A5)", async () => {
  const deckWithStructure: Deck = {
    schema_version: 1,
    meta: { title: "제목", report_type: "research", audience: "", presenter: "", preset_overrides: {} },
    structure: { chapters: [
      { id: "c1", topic: "표지", conclusion: "", template: "cover", source_refs: [] }] },
    slides: [],
  };
  const serverDeck: Deck = { ...deckWithStructure, meta: { ...deckWithStructure.meta, title: "서버본" } };
  vi.mocked(api.getDeck).mockResolvedValueOnce(deckWithStructure).mockResolvedValue(serverDeck);
  vi.mocked(api.listSources).mockResolvedValue([]);
  // 장 결과는 서버 묶음이 저장하므로 화면의 PUT은 승인 반영 1회다. 그 PUT이 412를 받는다
  vi.mocked(api.putDeck)
    .mockRejectedValueOnce(new ApiError(412, "다른 창이나 프로그램에서 이 프로젝트가 먼저 저장되었습니다."));
  render(<ProjectView project={project} onBack={() => {}} />);
  await userEvent.click(await screen.findByRole("button", { name: "구성" }));
  await userEvent.click(await screen.findByRole("button", { name: "승인하고 내용 생성" }));
  expect(await screen.findByText("다른 창이나 프로그램에서 먼저 저장되었습니다.", { exact: false }))
    .toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "서버 내용 다시 읽기" }));
  await waitFor(() => expect(api.getDeck).toHaveBeenCalledTimes(2));
  expect(await screen.findByText("서버본")).toBeInTheDocument();  // h1 제목이 서버 덱으로 갱신됨
});

it("스냅샷 복구가 412면 배너가 뜨고, 다시 읽기를 누르면 최신 덱으로 다시 마운트한다 (A5)", async () => {
  const serverDeck: Deck = { ...deckWithSlide, meta: { ...deckWithSlide.meta, title: "서버본" } };
  vi.mocked(api.getDeck).mockResolvedValueOnce(deckWithSlide).mockResolvedValue(serverDeck);
  vi.mocked(api.listSources).mockResolvedValue([]);
  vi.mocked(api.listSnapshots).mockResolvedValue([
    { id: "deck-20260829-100000-000001", saved_at: "2026-08-29T10:00:00+09:00", kind: "snapshot" }]);
  vi.mocked(api.restoreSnapshot).mockRejectedValue(
    new ApiError(412, "다른 창이나 프로그램에서 이 프로젝트가 먼저 저장되었습니다."));
  vi.spyOn(window, "confirm").mockReturnValue(true);
  render(<ProjectView project={project} onBack={() => {}} />);
  await userEvent.click(await screen.findByText("스냅샷 복구"));
  await userEvent.click(await screen.findByText("이 시점으로 복원"));
  expect(await screen.findByText("다른 창이나 프로그램에서 먼저 저장되었습니다.", { exact: false }))
    .toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "서버 내용 다시 읽기" }));
  await waitFor(() => expect(api.getDeck).toHaveBeenCalledTimes(2));
  expect(await screen.findByText("서버본")).toBeInTheDocument();
});

it("스냅샷 복구가 412인 채로 '목록으로'를 눌러 나가도 충돌 배너가 남지 않는다 (A5b 리뷰)", async () => {
  const serverDeck: Deck = { ...deckWithSlide, meta: { ...deckWithSlide.meta, title: "서버본" } };
  vi.mocked(api.getDeck).mockResolvedValueOnce(deckWithSlide).mockResolvedValue(serverDeck);
  vi.mocked(api.listSources).mockResolvedValue([]);
  vi.mocked(api.listSnapshots).mockResolvedValue([
    { id: "deck-20260829-100000-000001", saved_at: "2026-08-29T10:00:00+09:00", kind: "snapshot" }]);
  vi.mocked(api.restoreSnapshot).mockRejectedValue(
    new ApiError(412, "다른 창이나 프로그램에서 이 프로젝트가 먼저 저장되었습니다."));
  vi.spyOn(window, "confirm").mockReturnValue(true);
  render(<ProjectView project={project} onBack={() => {}} />);
  await userEvent.click(await screen.findByText("스냅샷 복구"));
  await userEvent.click(await screen.findByText("이 시점으로 복원"));
  expect(await screen.findByText("다른 창이나 프로그램에서 먼저 저장되었습니다.", { exact: false }))
    .toBeInTheDocument();
  // 배너의 "서버 내용 다시 읽기" 대신 RecoveryScreen 자체의 닫기로 나간다: 덱은 새로 읽히지만 이 경로가
  // 충돌 안내를 내리지 않으면 이미 해소된 배너가 영구히 남는다. 다시 씀(D3a-2): 다섯 단계 안의 복구 화면은
  // "목록으로" 대신 "복구 화면 닫기"다
  const recovery = within(document.querySelector(".recovery-screen") as HTMLElement);
  await userEvent.click(recovery.getByRole("button", { name: "복구 화면 닫기" }));
  await waitFor(() => expect(api.getDeck).toHaveBeenCalledTimes(2));
  await screen.findByText("서버본");
  expect(screen.queryByText("다른 창이나 프로그램에서 먼저 저장되었습니다.", { exact: false })).toBeNull();
});

// F-1 (B 묶음 최종 리뷰 major): "서버 내용 다시 읽기" 버튼은 다른 헤더 버튼과 같이 uploading에도
// 잠겨야 한다. 안 잠기면 업로드 진행 중 눌러 자료 화면이 통째로 언마운트되어, 나중에 응답한 업로드
// 결과가 화면에 영구히 반영되지 않는다(파일은 서버에 저장되지만 사용자는 확인할 방법이 없다)
it("자료 업로드 진행 중에는 다시 읽기 버튼도 잠긴다 (F-1)", async () => {
  vi.mocked(api.getDeck).mockResolvedValue(deckWithSlide);
  vi.mocked(api.listSources).mockResolvedValue([]);
  const upload = deferred<UploadResult>();
  vi.mocked(api.uploadSource).mockReturnValue(upload.promise);
  vi.mocked(api.putDeck).mockRejectedValue(new ApiError(412, "다른 창이나 프로그램에서 이 프로젝트가 먼저 저장되었습니다."));
  render(<ProjectView project={project} onBack={() => {}} />);

  // 다시 씀(D3a-2): 보고 정보는 보고 목적 단계에 있어 업로드 중에는 고칠 수 없다. 먼저 보고 정보 저장의 412로
  // 충돌 안내를 띄우고, 입력을 되돌려 미저장이 없게 한 뒤 자료 단계로 옮겨 업로드를 시작한다
  const title = await screen.findByLabelText("보고서 제목");
  await userEvent.type(title, " 고침");
  await userEvent.click(screen.getByRole("button", { name: "보고 정보 저장" }));
  const reloadBtn = await screen.findByRole("button", { name: "서버 내용 다시 읽기" });
  await userEvent.clear(title);
  await userEvent.type(title, "제목");
  await userEvent.click(screen.getByRole("button", { name: "자료" }));
  const xlsx = new File(["PK"], "매출.xlsx", { type: XLSX_MIME });
  await userEvent.upload(await screen.findByLabelText("자료 파일 선택"), xlsx);
  await waitFor(() => expect(api.uploadSource).toHaveBeenCalledTimes(1));

  expect(reloadBtn).toBeDisabled();  // 업로드가 여전히 진행 중이므로 잠겨 있어야 한다

  upload.resolve({ filename: "매출.xlsx", chars: 10, sheets: 1, cells: 1, truncated: false, notes: [] });
  await waitFor(() => expect(reloadBtn).not.toBeDisabled());  // 업로드가 끝나면 다시 풀린다
});

// 업로드 중 화면 잠금 (계획서 B4 가정 7): 업로드가 응답하기 전까지는 자료 탭 안의 일이라도 탭 5개
// 전부와 목록으로와 내보내기와 스냅샷 복구를 잠가야 FC-17(업로드 중 탭 전환)이 막힌다
it("자료 업로드가 진행 중이면 탭 버튼과 목록으로와 내보내기와 스냅샷 복구가 잠기고, 착지 뒤 풀린다", async () => {
  vi.mocked(api.getDeck).mockResolvedValue(deckWithSlide);
  vi.mocked(api.listSources).mockResolvedValue([]);
  const d = deferred<UploadResult>();
  vi.mocked(api.uploadSource).mockReturnValue(d.promise);
  render(<ProjectView project={project} onBack={() => {}} />);
  await userEvent.click(await screen.findByRole("button", { name: "자료" }));
  const xlsx = new File(["PK"], "매출.xlsx", { type: XLSX_MIME });
  await userEvent.upload(await screen.findByLabelText("자료 파일 선택"), xlsx);
  await waitFor(() => expect(api.uploadSource).toHaveBeenCalled());
  // 다시 씀(D3a-2): 탭 대신 다섯 단계 버튼 전부. 내보내기는 검토 단계 화면 안에 있어 그 단계로 가는 버튼으로 본다
  const all = ["목록으로", "보고 목적", "자료", "구성", "편집", "검토와 내보내기", "스냅샷 복구"];
  for (const name of all) {
    expect(screen.getByRole("button", { name })).toBeDisabled();
  }
  d.resolve({ filename: "매출.xlsx", chars: 10, sheets: 1, cells: 1, truncated: false, notes: [] });
  await waitFor(() => expect(screen.getByRole("button", { name: "목록으로" })).not.toBeDisabled());
  for (const name of all) {
    expect(screen.getByRole("button", { name })).not.toBeDisabled();
  }
});

// beforeunload 조건 dirty || uploading || generating (계획서 B4)
it("자료 업로드 진행 중에는 beforeunload가 막히고, 끝나면 풀리며, 자료 본문을 고치면 다시 막힌다", async () => {
  // 다시 씀(D3a-2): 보고 정보가 보고 목적 단계로 옮겨 업로드와 동시에 고칠 수 없다. 자료 단계의 두 신호는
  // 업로드와 자료 본문 미저장이다
  vi.mocked(api.getDeck).mockResolvedValue(deckWithSlide);
  vi.mocked(api.listSources).mockResolvedValue([]);
  vi.mocked(api.readSource).mockResolvedValue({ text: "추출본" });
  const d = deferred<UploadResult>();
  vi.mocked(api.uploadSource).mockReturnValue(d.promise);
  render(<ProjectView project={project} onBack={() => {}} />);
  await userEvent.click(await screen.findByRole("button", { name: "자료" }));
  await screen.findByLabelText("자료 파일 선택");
  expect(dispatchBeforeUnload()).toBe(false);  // 아직 아무 일도 없다
  const xlsx = new File(["PK"], "매출.xlsx", { type: XLSX_MIME });
  await userEvent.upload(await screen.findByLabelText("자료 파일 선택"), xlsx);
  await waitFor(() => expect(api.uploadSource).toHaveBeenCalled());
  expect(dispatchBeforeUnload()).toBe(true);  // 업로드 진행 중
  d.resolve({ filename: "매출.xlsx", chars: 10, sheets: 1, cells: 1, truncated: false, notes: [] });
  await waitFor(() => expect(screen.getByRole("button", { name: "목록으로" })).not.toBeDisabled());
  await waitFor(() => expect(dispatchBeforeUnload()).toBe(false));
  await userEvent.type(await screen.findByLabelText("자료 내용"), " 고침");
  expect(dispatchBeforeUnload()).toBe(true);
});

// 종전에는 dirty만 검사해 순차 생성 중 창을 닫아도 경고가 없었다 (계획서 B4 가정 7, 1차 리뷰)
it("장별 순차 생성이 진행 중이면 beforeunload가 막힌다", async () => {
  const deckWithStructure: Deck = {
    schema_version: 1,
    meta: { title: "제목", report_type: "research", audience: "", presenter: "", preset_overrides: {} },
    structure: { chapters: [
      { id: "c1", topic: "표지", conclusion: "", template: "cover", source_refs: [] }] },
    slides: [],
  };
  vi.mocked(api.getDeck).mockResolvedValue(deckWithStructure);
  vi.mocked(api.listSources).mockResolvedValue([]);
  vi.mocked(api.putDeck).mockResolvedValue({ ok: true });
  hangingBatch();  // 끝나지 않는 장 생성 묶음
  render(<ProjectView project={project} onBack={() => {}} />);
  expect(dispatchBeforeUnload()).toBe(false);
  await userEvent.click(await screen.findByRole("button", { name: "구성" }));
  await userEvent.click(await screen.findByRole("button", { name: "승인하고 내용 생성" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "편집" })).toBeDisabled());
  expect(dispatchBeforeUnload()).toBe(true);
});

it("더 새 형식 프로젝트는 열지 않고 안내만 보인다 (D2a-1)", async () => {
  render(<ProjectView project={{ ...project, status: "newer_format" }} onBack={() => {}} />);
  expect(await screen.findByText(/더 새 버전의 SlideCaptain이 만든 프로젝트/)).toBeInTheDocument();
  expect(screen.getByText(/프로젝트 파일은 바꾸지 않았습니다/)).toBeInTheDocument();
  expect(api.getDeck).not.toHaveBeenCalled();
  expect(api.listSnapshots).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "목록으로" })).toBeInTheDocument();
});

it("형식 기록을 읽을 수 없는 프로젝트는 열지 않고 보관 방법을 안내한다 (D2a-1 리뷰 R2)", async () => {
  render(<ProjectView project={{ ...project, status: "unreadable_manifest" }} onBack={() => {}} />);
  expect(await screen.findByText(/형식 기록 파일\(manifest.json\)을 읽지 못했습니다/)).toBeInTheDocument();
  expect(api.getDeck).not.toHaveBeenCalled();
  expect(api.listSnapshots).not.toHaveBeenCalled();
});

// D2b-5a: 새로고침이나 다른 창에서 돌던 장 생성 묶음도 서비스의 진행 중 작업으로 잠근다
it("이 프로젝트의 장 생성 묶음이 진행 중이면 다시 열어도 구조안 탭을 열고 다른 탭과 창 닫기를 막는다 (D2b-5a)", async () => {
  vi.mocked(api.getDeck).mockResolvedValue(deckWithSlide);
  vi.mocked(api.listSources).mockResolvedValue([]);
  vi.mocked(api.getActiveJob).mockResolvedValue({ ledger_available: true, active: {
    id: "job-1", project: project.name, kind: "chapters", target: null, stage: "running",
    created_at: "2026-10-08T10:00:00+09:00", cancel_requested: false } });
  render(<ProjectView project={project} onBack={() => {}} jobPollMs={60_000} />);
  await waitFor(() => expect(document.querySelector(".structure-screen")).not.toBeNull());
  expect(screen.getByRole("button", { name: "편집" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "자료" })).toBeDisabled();
  expect(dispatchBeforeUnload()).toBe(true);
});

it("다른 프로젝트의 AI 작업이 진행 중이면 안내하고 그 작업을 취소할 수 있다 (D2b-5a)", async () => {
  vi.mocked(api.getDeck).mockResolvedValue(deckWithSlide);
  vi.mocked(api.listSources).mockResolvedValue([]);
  vi.mocked(api.getActiveJob)
    .mockResolvedValueOnce({ ledger_available: true, active: {
      id: "job-9", project: "다른프로젝트", kind: "chapters", target: null, stage: "running",
      created_at: "2026-10-08T10:00:00+09:00", cancel_requested: false } })
    .mockResolvedValue({ active: null, ledger_available: true });
  vi.mocked(api.cancelJob).mockResolvedValue({} as Awaited<ReturnType<typeof api.cancelJob>>);
  render(<ProjectView project={project} onBack={() => {}} jobPollMs={60_000} />);
  await userEvent.click(await screen.findByRole("button", { name: "그 작업 취소" }));
  expect(api.cancelJob).toHaveBeenCalledWith("다른프로젝트", "job-9");
  await waitFor(() => expect(screen.queryByRole("button", { name: "그 작업 취소" })).toBeNull());
  // 다른 프로젝트의 작업은 이 프로젝트의 탭을 잠그지 않는다
  expect(screen.getByRole("button", { name: "편집" })).not.toBeDisabled();
});

it("진행 중 작업을 확인하기 전에는 탭을 잠그고 확인 중이라고 알린다 (D2b-5a)", async () => {
  vi.mocked(api.getDeck).mockResolvedValue(deckWithSlide);
  vi.mocked(api.listSources).mockResolvedValue([]);
  const status = deferred<Awaited<ReturnType<typeof api.getActiveJob>>>();
  vi.mocked(api.getActiveJob).mockReturnValue(status.promise);
  render(<ProjectView project={project} onBack={() => {}} />);
  const editorBtn = await screen.findByRole("button", { name: "편집" });
  expect(editorBtn).toBeDisabled();
  expect(editorBtn).toHaveAttribute("title", "작업 상태를 확인하는 중입니다");
  status.resolve({ active: null, ledger_available: true });
  await waitFor(() => expect(editorBtn).not.toBeDisabled());
});

// -- D2b-5a 리뷰 반영 -------------------------------------------------------------------------

const batchActive = (project_: string, kind = "chapters") => ({ ledger_available: true, active: {
  id: "job-1", project: project_, kind, target: null, stage: "running" as const, created_at: "2026-10-08T10:00:00+09:00",
  cancel_requested: false } });

it("열고 난 뒤 나타난 이 프로젝트 묶음은 편집 탭을 강제로 바꾸지 않고 잠금과 안내만 한다 (리뷰 R3)", async () => {
  vi.mocked(api.getDeck).mockResolvedValue(deckWithSlide);
  vi.mocked(api.listSources).mockResolvedValue([]);
  vi.mocked(api.getPreset).mockResolvedValue(preset);
  vi.mocked(api.measure).mockResolvedValue({ ...plan, slides: [] });
  render(<ProjectView project={project} onBack={() => {}} jobPollMs={60_000} />);
  const editTab = await screen.findByRole("button", { name: "편집" });
  await waitFor(() => expect(editTab).toBeEnabled());
  await userEvent.click(editTab);
  vi.mocked(api.getActiveJob).mockResolvedValue(batchActive(project.name));
  window.dispatchEvent(new Event("focus"));  // 초점을 얻을 때 다시 조회한다
  expect(await screen.findByText("이 프로젝트에서 AI 생성이 진행 중입니다.", { exact: false })).toBeInTheDocument();
  await new Promise((r) => setTimeout(r, 30));  // 탭을 바꾸는 효과가 있었다면 실행될 시간을 준다
  expect(screen.getByRole("button", { name: "편집" })).toHaveAttribute("aria-current", "step");
  expect(document.querySelector(".structure-screen")).toBeNull();
  expect(screen.getByRole("button", { name: "자료" })).toBeDisabled();
});

it("진행 중으로 확인한 작업은 조회가 한 번 실패해도 잠금을 유지하고 계속 조회한다 (리뷰 R4)", async () => {
  vi.mocked(api.getDeck).mockResolvedValue(deckWithSlide);
  vi.mocked(api.listSources).mockResolvedValue([]);
  vi.mocked(api.getActiveJob)
    .mockResolvedValueOnce(batchActive(project.name))
    .mockRejectedValueOnce(new ApiError(503, "연결 오류"))
    .mockImplementation(async () => batchActive(project.name));  // 응답마다 새 객체 (리뷰 R22)
  render(<ProjectView project={project} onBack={() => {}} jobPollMs={5} />);
  await waitFor(() => expect(vi.mocked(api.getActiveJob).mock.calls.length).toBeGreaterThanOrEqual(4));
  expect(screen.getByRole("button", { name: "편집" })).toBeDisabled();
  expect(dispatchBeforeUnload()).toBe(true);
});

it("이 프로젝트 묶음이 끝나면 덱을 다시 읽는다 (리뷰 R5)", async () => {
  vi.mocked(api.getDeck).mockResolvedValue(deckWithSlide);
  vi.mocked(api.listSources).mockResolvedValue([]);
  vi.mocked(api.listJobs).mockRejectedValue(new ApiError(503, "목록 오류"));  // 구조안 화면은 따라가지 못한다
  vi.mocked(api.getActiveJob)
    .mockResolvedValueOnce(batchActive(project.name))
    .mockResolvedValue({ active: null, ledger_available: true });
  vi.mocked(api.getDocumentChangeBasis).mockRejectedValue(new ApiError(412, "다른 창이나 프로그램에서 먼저 저장되었습니다. 최신 덱을 다시 읽어 주세요."));  // 서버는 저장 ETag가 다르면 412다
  render(<ProjectView project={project} onBack={() => {}} jobPollMs={5} />);
  await waitFor(() => expect(api.getDeck).toHaveBeenCalledTimes(2));  // 구조안 탭이라 덱을 다시 읽는다
});

it("편집 단계에 미저장 변경이 없으면 다른 탭의 묶음이 끝난 뒤 새 덱으로 다시 마운트하고 충돌로 알리지 않는다 (β 리뷰 R1, D3a-2)", async () => {
  // 다시 씀(D3a-2, 계획 4.1): 분기는 탭 이름이 아니라 "그 화면이 저장본과 다른 사본을 들고 있는가"다.
  // 미저장 사본이 없으면 옛 사본으로 묶음의 장을 덮을 일이 없으므로 새 덱으로 다시 마운트한다
  const batchDeck: Deck = { ...deckWithSlide, structure: { chapters: [
    { id: "c1", topic: "묶음이 바꾼 주제", conclusion: "", template: "bullet_box", source_refs: [] }] } };
  vi.mocked(api.getDeck).mockResolvedValue(deckWithSlide);
  vi.mocked(api.listSources).mockResolvedValue([]);
  vi.mocked(api.getPreset).mockResolvedValue(preset);
  vi.mocked(api.measure).mockResolvedValue({ ...plan, slides: [] });
  vi.mocked(api.getDocumentChangeBasis).mockRejectedValue(new ApiError(412, "다른 창이나 프로그램에서 먼저 저장되었습니다. 최신 덱을 다시 읽어 주세요."));  // 서버는 저장 ETag가 다르면 412다
  render(<ProjectView project={project} onBack={() => {}} jobPollMs={5} />);
  const editTab = await screen.findByRole("button", { name: "편집" });
  await waitFor(() => expect(editTab).toBeEnabled());
  await userEvent.click(editTab);
  expect(await screen.findByLabelText("장 주제")).toHaveValue("주제");
  vi.mocked(api.getDeck).mockResolvedValue(batchDeck);
  // 다른 탭이 이 프로젝트의 묶음을 시작했다가 끝낸다
  vi.mocked(api.getActiveJob).mockResolvedValueOnce(batchActive(project.name))
    .mockImplementation(async () => ({ active: null, ledger_available: true }));
  window.dispatchEvent(new Event("focus"));
  await waitFor(() => expect(screen.getByLabelText("장 주제")).toHaveValue("묶음이 바꾼 주제"));
  expect(screen.queryByText("먼저 저장되었습니다", { exact: false })).toBeNull();
  expect(screen.getByRole("button", { name: "편집" })).toHaveAttribute("aria-current", "step");
});

it("편집 단계에 미저장 변경이 있으면 다른 탭의 묶음이 끝나도 덱을 덮지 않고 충돌 안내로 다시 읽기를 맡긴다 (β 리뷰 R1, D3a-2)", async () => {
  vi.mocked(api.getDeck).mockResolvedValue(deckWithSlide);
  vi.mocked(api.listSources).mockResolvedValue([]);
  vi.mocked(api.getPreset).mockResolvedValue(preset);
  vi.mocked(api.measure).mockResolvedValue({ ...plan, slides: [] });
  vi.mocked(api.putDeck).mockImplementation(() => new Promise(() => {}));  // 저장이 끝나지 않아 미저장으로 남는다
  vi.mocked(api.getDocumentChangeBasis).mockRejectedValue(new ApiError(412, "다른 창이나 프로그램에서 먼저 저장되었습니다. 최신 덱을 다시 읽어 주세요."));
  render(<ProjectView project={project} onBack={() => {}} jobPollMs={5} />);
  const editTab = await screen.findByRole("button", { name: "편집" });
  await waitFor(() => expect(editTab).toBeEnabled());
  await userEvent.click(editTab);
  const topic = await screen.findByLabelText("장 주제");
  fireEvent.change(topic, { target: { value: "주제 고침" } });
  fireEvent.blur(topic);  // 속성 패널은 입력을 떠날 때 덱에 반영한다
  const reads = vi.mocked(api.getDeck).mock.calls.length;
  vi.mocked(api.getActiveJob).mockResolvedValueOnce(batchActive(project.name))
    .mockImplementation(async () => ({ active: null, ledger_available: true }));
  window.dispatchEvent(new Event("focus"));
  expect(await screen.findByText("다른 창이나 프로그램에서 먼저 저장되었습니다.", { exact: false })).toBeInTheDocument();
  expect(vi.mocked(api.getDeck).mock.calls.length).toBe(reads);  // 저장 ETag를 몰래 새로 읽지 않는다
  expect(screen.getByLabelText("장 주제")).toHaveValue("주제 고침");
});


it("같은 프로젝트의 다른 종류 작업도 안내하고, 취소가 실패하면 원인을 보인다 (리뷰 R14, R15)", async () => {
  vi.mocked(api.getDeck).mockResolvedValue(deckWithSlide);
  vi.mocked(api.listSources).mockResolvedValue([]);
  vi.mocked(api.getActiveJob).mockResolvedValue(batchActive(project.name, "diagram"));
  vi.mocked(api.cancelJob).mockRejectedValue(new ApiError(503, "취소 요청을 보내지 못했습니다."));
  render(<ProjectView project={project} onBack={() => {}} jobPollMs={60_000} />);
  await userEvent.click(await screen.findByRole("button", { name: "그 작업 취소" }));
  expect(api.cancelJob).toHaveBeenCalledWith(project.name, "job-1");
  expect(await screen.findByText("취소 요청을 보내지 못했습니다.")).toBeInTheDocument();
});

it("작업 기록을 열 수 없으면 AI 생성만 막혔다고 알린다 (D2b-5c)", async () => {
  vi.mocked(api.getDeck).mockResolvedValue(deckWithSlide);
  vi.mocked(api.listSources).mockResolvedValue([]);
  vi.mocked(api.getActiveJob).mockResolvedValue({ active: null, ledger_available: false });
  render(<ProjectView project={project} onBack={() => {}} />);
  expect(await screen.findByText("작업 기록을 열 수 없어 AI 생성을 쓸 수 없습니다. 편집과 내보내기는 계속할 수 있습니다."))
    .toBeInTheDocument();
});

it("독립 앱에서는 진행 중 AI 작업만으로 창 닫기를 막지 않는다. main 프로세스가 묻는다 (D2b-5c 리뷰 R3)", async () => {
  vi.mocked(api.getDeck).mockResolvedValue(deckWithSlide);
  vi.mocked(api.listSources).mockResolvedValue([]);
  vi.mocked(api.getActiveJob).mockResolvedValue(batchActive(project.name));
  (window as { slidecaptain?: unknown }).slidecaptain = {};  // 독립 앱의 연결 객체가 있는 것처럼 둔다
  try {
    render(<ProjectView project={project} onBack={() => {}} jobPollMs={60_000} />);
    await screen.findByText("이 프로젝트에서 AI 생성이 진행 중입니다.", { exact: false });
    expect(dispatchBeforeUnload()).toBe(false);
  } finally {
    delete (window as { slidecaptain?: unknown }).slidecaptain;
  }
});

it("복구 화면의 후보에서 다시 생성하면 덱을 다시 읽고 맞는 탭으로 옮긴다. 원장이 정상이면 안내가 없다 (D2b-5c 리뷰 R16)", async () => {
  vi.mocked(api.getDeck).mockResolvedValue(deckWithSlide);
  vi.mocked(api.listSources).mockResolvedValue([]);
  vi.mocked(api.listSnapshots).mockResolvedValue([]);
  vi.mocked(api.listJobs).mockResolvedValue([{ id: "job-s", project: project.name, kind: "structure", state: "succeeded",
    target: null, params: {}, candidate_status: "held", outcome: null, owner: "this_instance", created_at: "2026-10-08T10:00:00+09:00",
    started_at: null, finished_at: null, provider: null, model: null, base_etag: null, current_etag: null,
    relevance_hash: null, stale_reasons: [], cancel_requested: false, error: null,
    result: { status: "ok", structure: { chapters: [] }, usage: emptyUsage(), raw_text: "", unverified_numbers: [],
      format_retried: false }, chapters: [] }]);
  render(<ProjectView project={project} onBack={() => {}} jobPollMs={60_000} />);
  await userEvent.click(await screen.findByRole("button", { name: "스냅샷 복구" }));
  const before = vi.mocked(api.getDeck).mock.calls.length;
  await userEvent.click(await screen.findByRole("button", { name: "구성 단계로 옮겨 다시 생성" }));
  await waitFor(() => expect(vi.mocked(api.getDeck).mock.calls.length).toBeGreaterThan(before));
  await waitFor(() => expect(screen.getByRole("button", { name: "구성" })).toHaveAttribute("aria-current", "step"));
  expect(screen.queryByText(/작업 기록을 열 수 없어/)).toBeNull();
});

it("이 탭이 이미 따라간 묶음이 끝나면 다시 읽지도 충돌로 알리지도 않는다 (β 리뷰 R1)", async () => {
  vi.mocked(api.getDeck).mockResolvedValue(deckWithSlide);
  vi.mocked(api.listSources).mockResolvedValue([]);
  vi.mocked(api.getPreset).mockResolvedValue(preset);
  vi.mocked(api.measure).mockResolvedValue({ ...plan, slides: [] });
  // If-Match가 서버 저장본과 같으면 기준 조회는 200이고 base_etag는 그 값이다
  vi.mocked(api.getDocumentChangeBasis).mockImplementation(async (name) => ({ base_etag: savedEtag(name) as string,
    sources_fingerprint: "s", evidence_fingerprints: {} }));
  render(<ProjectView project={project} onBack={() => {}} jobPollMs={5} />);
  const editTab = await screen.findByRole("button", { name: "편집" });
  await waitFor(() => expect(editTab).toBeEnabled());
  await userEvent.click(editTab);
  const reads = vi.mocked(api.getDeck).mock.calls.length;
  vi.mocked(api.getActiveJob).mockResolvedValueOnce(batchActive(project.name))
    .mockImplementation(async () => ({ active: null, ledger_available: true }));
  window.dispatchEvent(new Event("focus"));
  await waitFor(() => expect(api.getDocumentChangeBasis).toHaveBeenCalled());
  await new Promise((r) => setTimeout(r, 30));
  expect(vi.mocked(api.getDeck).mock.calls.length).toBe(reads);
  expect(screen.queryByText("다른 창이나 프로그램에서 먼저 저장되었습니다.", { exact: false })).toBeNull();
});

it("구성 초안을 고친 채 다른 탭의 묶음이 끝나면 덱을 몰래 다시 읽지 않고 충돌로 알린다 (D3a-2, 계획 4.1)", async () => {
  // 회귀 RED: 고치기 전 코드는 구조안 탭이면 덱을 다시 읽어 저장 ETag만 새로 바꿨다. 구성 화면의 초안 사본은
  // 옛 값이라, 그 뒤 승인이 다른 탭의 구조를 옛 사본으로 덮을 수 있었다 (사실 15)
  const twoChapters: Deck = { ...deckWithSlide, structure: { chapters: [
    { id: "c1", topic: "주제", conclusion: "", template: "bullet_box", source_refs: [] },
    { id: "c2", topic: "둘째", conclusion: "", template: "bullet_box", source_refs: [] }] } };
  vi.mocked(api.getDeck).mockResolvedValue(twoChapters);
  vi.mocked(api.listSources).mockResolvedValue([]);
  vi.mocked(api.getDocumentChangeBasis).mockRejectedValue(new ApiError(412, "다른 창이나 프로그램에서 먼저 저장되었습니다. 최신 덱을 다시 읽어 주세요."));
  render(<ProjectView project={project} onBack={() => {}} jobPollMs={5} />);
  const structureTab = await screen.findByRole("button", { name: /^(구조안|구성)$/ });
  await waitFor(() => expect(structureTab).toBeEnabled());
  await userEvent.click(structureTab);
  await userEvent.click(await screen.findByRole("button", { name: "둘째 삭제" }));  // 초안이 저장본과 달라진다
  const reads = vi.mocked(api.getDeck).mock.calls.length;
  vi.mocked(api.getActiveJob).mockResolvedValueOnce(batchActive(project.name))
    .mockImplementation(async () => ({ active: null, ledger_available: true }));
  window.dispatchEvent(new Event("focus"));
  expect(await screen.findByText("먼저 저장되었습니다", { exact: false })).toBeInTheDocument();
  expect(vi.mocked(api.getDeck).mock.calls.length).toBe(reads);
});
