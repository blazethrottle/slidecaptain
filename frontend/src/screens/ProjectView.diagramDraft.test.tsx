import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { api } from "../api/client";
import { deckWith, deferred, planWith, preset, project } from "../test/fixtures";
import { ProjectView } from "./ProjectView";

vi.mock("../api/client", async (original) => {
  const mod = await original<typeof import("../api/client")>();
  return { ...mod, api: { ...mod.api,
    getDeck: vi.fn(), listSources: vi.fn(), measure: vi.fn(), putDeck: vi.fn(), getPreset: vi.fn(),
    listSnapshots: vi.fn(), listExports: vi.fn(), readSource: vi.fn(), writeSource: vi.fn(),
    createSnapshot: vi.fn(), exportDeck: vi.fn(),
  } };
});
vi.mock("./AISettingsPanel", () => ({ AISettingsPanel: () => null }));
vi.mock("./NumericReviewPanel", () => ({ NumericReviewPanel: () => null }));
vi.mock("./ExportQualitySummary", () => ({ ExportQualitySummary: () => <p>내보내기 결과</p> }));

function Shell() {
  const [open, setOpen] = useState(true);
  return open ? <ProjectView project={project} onBack={() => setOpen(false)} /> : <p>목록 화면</p>;
}

async function openEditor() {
  vi.mocked(api.getDeck).mockResolvedValue(deckWith(["하나"]));
  vi.mocked(api.listSources).mockResolvedValue([]);
  vi.mocked(api.measure).mockResolvedValue(planWith(["하나"]));
  vi.mocked(api.getPreset).mockResolvedValue(preset);
  vi.mocked(api.listSnapshots).mockResolvedValue([]);
  vi.mocked(api.listExports).mockResolvedValue({ items: [], total: 0, offset: 0, limit: 20,
    checked_at: "", current_input_fingerprint: null, current_input_error: null });
  render(<Shell />);
  await userEvent.click(await screen.findByRole("button", { name: "편집" }));
  await screen.findByLabelText("장 주제");
}

it("작성 중인 도식 초안이 있으면 화면 이동을 막는다", async () => {
  vi.mocked(api.putDeck).mockReset().mockResolvedValue({ ok: true });
  await openEditor();
  await userEvent.click(screen.getByRole("button", { name: "도식 추가" }));
  fireEvent.change(screen.getByLabelText("도식 제목"), { target: { value: "보존할 새 초안" } });
  await userEvent.click(screen.getByRole("button", { name: "목록으로" }));
  expect(screen.getByLabelText("도식 제목")).toHaveValue("보존할 새 초안");
  expect(screen.queryByText("목록 화면")).not.toBeInTheDocument();
});

// 다시 씀(D3a-2): 탭 이름을 단계 이름으로 바꿨다. 초안 PPTX 내보내기는 검토 단계 화면 안으로 옮겨 편집 단계에서는
// 누를 수 없으므로 목록에서 뺐다(내보내기 전 플러시는 ProjectView.test.tsx의 "마지막 편집 저장에 실패하면"이 지킨다)
it.each(["목록으로", "보고 목적", "자료", "구성", "검토와 내보내기", "스냅샷 복구"])(
  "%s 저장 대기 중 새로 연 도식 초안을 보존한다", async (action) => {
  const pending = deferred<{ ok: boolean }>();
  vi.mocked(api.putDeck).mockReset().mockReturnValue(pending.promise);
  await openEditor();
  fireEvent.change(screen.getByLabelText("장 주제"), { target: { value: "저장 대기 변경" } });
  fireEvent.blur(screen.getByLabelText("장 주제"));
  await userEvent.click(screen.getByRole("button", { name: action }));
  await waitFor(() => expect(api.putDeck).toHaveBeenCalledOnce());

  expect(screen.getByRole("button", { name: "도식 추가" })).toBeEnabled();
  await userEvent.click(screen.getByRole("button", { name: "도식 추가" }));
  fireEvent.change(screen.getByLabelText("도식 제목"), { target: { value: "응답 대기 중 새로 작성한 초안" } });
  expect(screen.getByRole("dialog")).toBeInTheDocument();
  await act(async () => pending.resolve({ ok: true }));

  expect(screen.queryByText("목록 화면")).not.toBeInTheDocument();
  expect(screen.getByLabelText("도식 제목")).toHaveValue("응답 대기 중 새로 작성한 초안");
  expect(screen.getByRole("button", { name: "편집" })).toHaveAttribute("aria-current", "step");
  expect(api.listSnapshots).not.toHaveBeenCalled();
  expect(api.listExports).not.toHaveBeenCalled();
  expect(api.createSnapshot).not.toHaveBeenCalled();
  expect(api.exportDeck).not.toHaveBeenCalled();
  const unloading = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(unloading);
  expect(unloading.defaultPrevented).toBe(true);

  // 명시적으로 입력을 버리고 닫은 뒤에는 이동할 수 있다.
  await userEvent.click(screen.getByRole("button", { name: "변경 버리고 닫기" }));
  await userEvent.click(screen.getByRole("button", { name: "목록으로" }));
  expect(screen.getByText("목록 화면")).toBeInTheDocument();
});
