// 화면 이탈 경로의 플러시 검사 (2026-09-03 저장 안전성 묶음 태스크 C)
// 배경: 내보내기만 플러시 결과를 검사했고, 목록 복귀(FC-08), 탭 전환(FC-14), 스냅샷 복구(FC-11)는 실패를 무시했다.
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { api } from "../api/client";
import { deckWith, deferred, planWith, preset, project } from "../test/fixtures";
import { ProjectView } from "./ProjectView";

vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return { ...mod, api: { ...mod.api,
    getDeck: vi.fn(), listSources: vi.fn(), measure: vi.fn(), putDeck: vi.fn(), getPreset: vi.fn(),
    listSnapshots: vi.fn() } };
});

// App.tsx 와 같은 구조: 목록으로 돌아가면 ProjectView 가 언마운트된다
function Shell() {
  const [open, setOpen] = useState(true);
  return open ? <ProjectView project={project} onBack={() => setOpen(false)} /> : <p>목록 화면</p>;
}

async function openEditorAndEdit(text: string) {
  vi.mocked(api.getDeck).mockResolvedValue(deckWith(["하나"]));
  vi.mocked(api.listSources).mockResolvedValue([]);
  vi.mocked(api.measure).mockResolvedValue(planWith(["하나"]));
  vi.mocked(api.getPreset).mockResolvedValue(preset);
  vi.mocked(api.listSnapshots).mockResolvedValue([]);
  render(<Shell />);
  await userEvent.click(await screen.findByRole("button", { name: "편집" }));
  const preview = () => within(document.querySelector(".editor-center") as HTMLElement);
  await userEvent.click(await preview().findByText("하나"));
  await userEvent.click(preview().getByText("하나"));
  const box = await screen.findByLabelText("내용 수정");
  await userEvent.clear(box);
  await userEvent.type(box, `${text}{Enter}`);
  expect(api.putDeck).not.toHaveBeenCalled();  // 기본 1.2초 디바운스: 아직 저장 전
}

it("목록으로: 플러시가 실패하면 나가지 않고 배너를 띄운다 (FC-08)", async () => {
  vi.mocked(api.putDeck).mockRejectedValue(new Error("서버 중단"));
  await openEditorAndEdit("둘");
  await userEvent.click(screen.getByRole("button", { name: "목록으로" }));
  await waitFor(() => expect(api.putDeck).toHaveBeenCalled());
  // 편집기 자체의 저장 오류 문구도 alert 이므로 둘 중 하나가 이탈 중단 배너다
  await waitFor(() => expect(screen.getAllByRole("alert").map((a) => a.textContent).join("\n"))
    .toContain("저장하지 못해 이동을 중단"));
  expect(screen.queryByText("목록 화면")).toBeNull();
  expect(document.querySelector(".editor-screen")).not.toBeNull();  // 편집기는 내려가지 않았다
});

it("목록으로: 플러시가 성공하면 PUT 착지 뒤에 목록 화면이 뜬다", async () => {
  const d = deferred<{ ok: boolean }>();
  vi.mocked(api.putDeck).mockImplementation(() => d.promise);
  await openEditorAndEdit("둘");
  await userEvent.click(screen.getByRole("button", { name: "목록으로" }));
  await waitFor(() => expect(api.putDeck).toHaveBeenCalledTimes(1));
  expect(screen.queryByText("목록 화면")).toBeNull();  // 착지 전에는 나가지 않는다
  d.resolve({ ok: true });
  expect(await screen.findByText("목록 화면")).toBeInTheDocument();
});

it("탭 전환: 플러시가 실패하면 탭이 바뀌지 않고 배너를 띄운다 (FC-14)", async () => {
  vi.mocked(api.putDeck).mockRejectedValue(new Error("서버 중단"));
  await openEditorAndEdit("둘");
  await userEvent.click(screen.getByRole("button", { name: "구조안" }));
  await waitFor(() => expect(api.putDeck).toHaveBeenCalled());
  // 편집기 자체의 저장 오류 문구도 alert 이므로 둘 중 하나가 이탈 중단 배너다
  await waitFor(() => expect(screen.getAllByRole("alert").map((a) => a.textContent).join("\n"))
    .toContain("저장하지 못해 이동을 중단"));
  expect(screen.getByRole("button", { name: "편집" })).toHaveAttribute("aria-pressed", "true");
  expect(document.querySelector(".structure-screen")).toBeNull();
  expect(document.querySelector(".editor-screen")).not.toBeNull();  // 편집기가 남아 있으므로 언마운트 플러시도 없다
});

it("스냅샷 복구: 플러시가 착지한 뒤에 복구 화면이 열린다 (FC-11)", async () => {
  const d = deferred<{ ok: boolean }>();
  vi.mocked(api.putDeck).mockImplementation(() => d.promise);
  await openEditorAndEdit("둘");
  await userEvent.click(screen.getByRole("button", { name: "스냅샷 복구" }));
  await waitFor(() => expect(api.putDeck).toHaveBeenCalledTimes(1));
  expect(api.listSnapshots).not.toHaveBeenCalled();  // 복구 화면은 아직 열리지 않았다
  d.resolve({ ok: true });
  await waitFor(() => expect(api.listSnapshots).toHaveBeenCalled());
});
