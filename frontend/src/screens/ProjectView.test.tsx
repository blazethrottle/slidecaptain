import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api, type Deck } from "../api/client";
import { ProjectView } from "./ProjectView";

vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return { ...mod, api: { ...mod.api,
    getDeck: vi.fn(), listSources: vi.fn(), createSnapshot: vi.fn(), exportDeck: vi.fn(),
    measure: vi.fn(), putDeck: vi.fn(), listSnapshots: vi.fn(), restoreSnapshot: vi.fn() } };
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

it("내보내기는 스냅샷을 먼저 남기고 경로를 보여준다", async () => {
  vi.mocked(api.getDeck).mockResolvedValue(deckWithSlide);
  vi.mocked(api.listSources).mockResolvedValue([]);
  vi.mocked(api.createSnapshot).mockResolvedValue({ ok: true });
  vi.mocked(api.exportDeck).mockResolvedValue({ path: "C:\\exports\\제목_v001.pptx" });
  render(<ProjectView project={project} onBack={() => {}} />);
  await userEvent.click(await screen.findByText("PPTX 내보내기"));
  await waitFor(() => expect(api.exportDeck).toHaveBeenCalledWith("p1"));
  expect(api.createSnapshot).toHaveBeenCalledWith("p1");  // 내보내기 직전 스냅샷 (결정 1)
  expect(await screen.findByText(/제목_v001\.pptx/)).toBeInTheDocument();
});

it("복구가 필요한 프로젝트는 복구 화면으로 진입한다", async () => {
  vi.mocked(api.listSnapshots).mockResolvedValue([]);
  render(<ProjectView project={{ ...project, status: "needs_recovery" }} onBack={() => {}} />);
  expect(await screen.findByText(/스냅샷 복구/)).toBeInTheDocument();
});
