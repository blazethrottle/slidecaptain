import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api, type Deck, type Preset, type RenderPlan } from "../api/client";
import { ProjectView } from "./ProjectView";

vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return { ...mod, api: { ...mod.api,
    getDeck: vi.fn(), listSources: vi.fn(), createSnapshot: vi.fn(), exportDeck: vi.fn(),
    measure: vi.fn(), putDeck: vi.fn(), listSnapshots: vi.fn(), restoreSnapshot: vi.fn(),
    getPreset: vi.fn() } };
});

const project = { name: "p1", title: "제목", updated_at: "", status: "ok" as const };

const deckWithSlide: Deck = {
  schema_version: 1,
  meta: { title: "제목", report_type: "research", audience: "", preset_overrides: {} },
  structure: { chapters: [
    { id: "c1", topic: "주제", conclusion: "", template: "bullet_box", source_refs: [] }] },
  slides: [{ chapter_id: "c1", slots: {
    template: "bullet_box", bullets: [], conclusion: "결", footnote: "" } }],
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
  vi.mocked(api.exportDeck).mockResolvedValue({ path: "C:\\exports\\제목_v001.pptx" });
  render(<ProjectView project={project} onBack={() => {}} />);
  await userEvent.click(await screen.findByText("PPTX 내보내기"));
  expect(await screen.findByText(/제목_v001\.pptx/)).toBeInTheDocument();
  expect(api.createSnapshot).toHaveBeenCalledWith("p1");  // 내보내기 직전 스냅샷 (결정 1)
  expect(api.exportDeck).toHaveBeenCalledWith("p1");
  // 스냅샷이 내보내기보다 먼저 호출됨을 호출 순서로 단언 (2026-08-29 태스크 16 리뷰 보강)
  const snapOrder = vi.mocked(api.createSnapshot).mock.invocationCallOrder[0];
  const exportOrder = vi.mocked(api.exportDeck).mock.invocationCallOrder[0];
  expect(snapOrder).toBeLessThan(exportOrder);
});

it("복구가 필요한 프로젝트는 복구 화면으로 진입한다", async () => {
  vi.mocked(api.listSnapshots).mockResolvedValue([]);
  render(<ProjectView project={{ ...project, status: "needs_recovery" }} onBack={() => {}} />);
  // /스냅샷 복구/는 교체 전 임시 안내문에도 있던 문구라 RecoveryScreen 진입을 판별하지 못한다.
  // listSnapshots가 빈 목록을 반환할 때만 나오는 RecoveryScreen 고유 산출로 단언한다
  // (2026-08-29 태스크 16 리뷰 정정)
  expect(await screen.findByText("되돌릴 수 있는 저장 시점이 없습니다.")).toBeInTheDocument();
});

it("마지막 편집 저장에 실패하면 내보내기를 중단한다", async () => {
  vi.mocked(api.getDeck).mockResolvedValue(deckWithSlide);
  vi.mocked(api.listSources).mockResolvedValue([]);
  vi.mocked(api.measure).mockResolvedValue(plan);
  vi.mocked(api.getPreset).mockResolvedValue(preset);
  vi.mocked(api.putDeck).mockRejectedValue(new Error("저장 실패"));
  render(<ProjectView project={project} onBack={() => {}} />);
  await userEvent.click(await screen.findByText("편집"));
  // 속성 패널도 같은 텍스트를 보여주므로, 미리보기 영역으로 조회를 한정한다 (EditorScreen.test.tsx와 동일 패턴)
  const preview = () => within(document.querySelector(".editor-center") as HTMLElement);
  await userEvent.click(await preview().findByText("하나"));
  await userEvent.click(preview().getByText("하나"));
  const box = await screen.findByLabelText("내용 수정");
  await userEvent.clear(box);
  await userEvent.type(box, "고침{Enter}");
  // 기본 timings(1.2초 디바운스)에서는 자동 저장이 아직 발화하지 않고, 아래 내보내기 클릭이
  // flushSave로 미저장분을 감지해 putDeck을 호출한다
  await userEvent.click(screen.getByText("PPTX 내보내기"));
  // EditorScreen도 같은 실패로 자체 오류 배너(role=alert)를 띄우므로, findByRole("alert") 단일 조회
  // 대신 중단 안내 문구와 role=alert 컨테이너를 함께 확인해 정밀화한다 (조정 사유: 배너 2개 동시 존재)
  const banner = await screen.findByText(
    "마지막 편집을 저장하지 못해 내보내기를 중단했습니다. 저장 상태를 확인한 뒤 다시 시도해 주세요.",
  );
  expect(banner.closest('[role="alert"]')).not.toBeNull();
  expect(api.exportDeck).not.toHaveBeenCalled();
});
