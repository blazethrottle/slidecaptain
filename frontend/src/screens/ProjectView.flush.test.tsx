// 화면 이탈 경로의 플러시 검사 (2026-09-03 저장 안전성 묶음 태스크 C)
// 배경: 내보내기만 플러시 결과를 검사했고, 목록 복귀(FC-08), 탭 전환(FC-14), 스냅샷 복구(FC-11)는 실패를 무시했다.
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { api, ApiError } from "../api/client";
import { deckWith, deferred, planWith, preset, project } from "../test/fixtures";
import { ProjectView } from "./ProjectView";

function dispatchBeforeUnload(): boolean {
  const ev = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(ev);
  return ev.defaultPrevented;
}

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
  // 이탈 처리 중에는 다른 이탈 경로도 잠근다: 두 leaveEditor 가 겹치면 먼저 끝난 쪽이 화면을 내린 뒤
  // 나중 쪽의 setTab 이 사라진 컴포넌트에 떨어진다 (브랜치 리뷰 발견 7, 2026-09-03)
  for (const name of ["자료", "구조안", "편집", "PPTX 내보내기", "스냅샷 복구", "목록으로"]) {
    expect(screen.getByRole("button", { name })).toBeDisabled();
  }
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

// 창 닫기 경고 (FC-15): 편집 탭과 자료 탭 양쪽의 미저장 상태에 beforeunload를 건다 (2026-09-03 A5)
it("편집 탭에서 미저장 상태면 beforeunload를 막고, 플러시가 착지하면 막지 않는다 (A5)", async () => {
  vi.mocked(api.putDeck).mockResolvedValue({ ok: true });
  await openEditorAndEdit("셋");
  expect(dispatchBeforeUnload()).toBe(true);  // 아직 저장 대기
  await userEvent.click(screen.getByRole("button", { name: "구조안" }));
  await waitFor(() => expect(document.querySelector(".structure-screen")).not.toBeNull());
  expect(dispatchBeforeUnload()).toBe(false);
});

// 구형 브라우저 호환: preventDefault만으로는 확인 대화가 안 뜨는 구현이 있어 returnValue도 함께 설정한다
// (A5b 리뷰 발견 5). jsdom의 Event.returnValue getter는 defaultPrevented의 별칭이라 실제 DOM
// 디스패치로는 문자열 대입 여부를 관측할 수 없으므로, 등록된 리스너를 직접 붙잡아 평범한 객체로 불러 확인한다
it("beforeunload 핸들러는 dirty일 때 returnValue를 빈 문자열로 설정한다 (A5b 리뷰)", async () => {
  vi.mocked(api.putDeck).mockResolvedValue({ ok: true });
  const addSpy = vi.spyOn(window, "addEventListener");
  await openEditorAndEdit("넷");
  const call = addSpy.mock.calls.filter(([type]) => type === "beforeunload").at(-1);
  expect(call).toBeDefined();
  const handler = call![1] as (e: { preventDefault: () => void; returnValue: unknown }) => void;
  const fakeEvent = { preventDefault: vi.fn(), returnValue: undefined as unknown };
  handler(fakeEvent);
  expect(fakeEvent.preventDefault).toHaveBeenCalled();
  expect(fakeEvent.returnValue).toBe("");
  addSpy.mockRestore();
});

it("자료 탭에서 보고 정보를 고치고 저장하지 않으면 beforeunload를 막고, 플러시가 착지하면 막지 않는다 (A5)", async () => {
  vi.mocked(api.getDeck).mockResolvedValue(deckWith(["하나"]));
  vi.mocked(api.listSources).mockResolvedValue([]);
  vi.mocked(api.putDeck).mockResolvedValue({ ok: true });
  render(<ProjectView project={project} onBack={() => {}} />);
  const title = await screen.findByLabelText("보고서 제목");
  expect(dispatchBeforeUnload()).toBe(false);  // 아직 아무것도 고치지 않았다
  await userEvent.clear(title);
  await userEvent.type(title, "새 제목");
  expect(dispatchBeforeUnload()).toBe(true);
  await userEvent.click(screen.getByRole("button", { name: "구조안" }));
  await waitFor(() => expect(api.putDeck).toHaveBeenCalled());
  expect(dispatchBeforeUnload()).toBe(false);
});

// 충돌 배너 (2026-09-03 A5): 구조안, 자료, 복구 화면의 412는 ProjectView 배너의
// "서버 내용 다시 읽기"로 회복한다. 여기서는 자료 탭 경로를 확인한다(구조안과 복구는 ProjectView.test.tsx)
it("자료 탭 저장이 412면 배너가 뜨고, 다시 읽기를 누르면 최신 덱으로 다시 마운트한다 (A5)", async () => {
  vi.mocked(api.getDeck).mockResolvedValueOnce(deckWith(["하나"])).mockResolvedValue(deckWith(["서버본"]));
  vi.mocked(api.listSources).mockResolvedValue([]);
  vi.mocked(api.putDeck).mockRejectedValue(
    new ApiError(412, "다른 창이나 프로그램에서 이 프로젝트가 먼저 저장되었습니다."));
  render(<ProjectView project={project} onBack={() => {}} />);
  const title = await screen.findByLabelText("보고서 제목");
  await userEvent.clear(title);
  await userEvent.type(title, "새 제목");
  await userEvent.click(screen.getByText("보고 정보 저장"));
  expect(await screen.findByText("다른 창이나 프로그램에서 먼저 저장되었습니다.", { exact: false }))
    .toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "서버 내용 다시 읽기" }));
  await waitFor(() => expect(api.getDeck).toHaveBeenCalledTimes(2));
  // 서버본으로 다시 마운트되어 방금 고친 "새 제목"이 아니라 원래 제목("제목")이 보인다
  await waitFor(() => expect(screen.getByLabelText("보고서 제목")).toHaveValue("제목"));
});

it("자료 탭에서 저장 버튼 없이 탭을 전환해 412를 받아도 이동 중단 배너는 중복으로 뜨지 않는다 (A5b 리뷰)", async () => {
  vi.mocked(api.getDeck).mockResolvedValue(deckWith(["하나"]));
  vi.mocked(api.listSources).mockResolvedValue([]);
  vi.mocked(api.putDeck).mockRejectedValue(
    new ApiError(412, "다른 창이나 프로그램에서 이 프로젝트가 먼저 저장되었습니다."));
  render(<ProjectView project={project} onBack={() => {}} />);
  const title = await screen.findByLabelText("보고서 제목");
  await userEvent.clear(title);
  await userEvent.type(title, "새 제목");
  await userEvent.click(screen.getByRole("button", { name: "구조안" }));  // 저장 버튼 없이 탭 전환(leaveScreen 경유)
  expect(await screen.findByText("다른 창이나 프로그램에서 먼저 저장되었습니다.", { exact: false }))
    .toBeInTheDocument();
  // leaveScreen의 일반 이동 중단 문구는 onConflict가 이미 배너를 띄운 경우 생략한다(중복 안내 방지)
  expect(screen.queryByText("이동을 중단했습니다", { exact: false })).toBeNull();
  expect(screen.getAllByRole("alert")).toHaveLength(1);
  expect(document.querySelector(".sources-screen")).not.toBeNull();  // 탭은 바뀌지 않았다
});

it("자료 탭 저장 버튼의 412 뒤에 무관한 저장 실패로 이동이 막히면 일반 배너가 뜬다 (묶음 최종 리뷰 1)", async () => {
  // 종전에는 leaveScreen 밖(저장 버튼)에서 켜진 억제 플래그가 재설정되지 않아 이후 무관한 실패의 배너까지 삼켰다
  vi.mocked(api.getDeck).mockResolvedValue(deckWith(["하나"]));
  vi.mocked(api.listSources).mockResolvedValue([]);
  vi.mocked(api.putDeck)
    .mockRejectedValueOnce(new ApiError(412, "다른 창이나 프로그램에서 이 프로젝트가 먼저 저장되었습니다."))
    .mockRejectedValue(new Error("서버 중단"));
  render(<ProjectView project={project} onBack={() => {}} />);
  const title = await screen.findByLabelText("보고서 제목");
  await userEvent.clear(title);
  await userEvent.type(title, "새 제목");
  await userEvent.click(screen.getByText("보고 정보 저장"));  // 412: leaveScreen 을 거치지 않는 경로
  expect(await screen.findByText("다른 창이나 프로그램에서 먼저 저장되었습니다.", { exact: false }))
    .toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "서버 내용 다시 읽기" }));
  await waitFor(() => expect(api.getDeck).toHaveBeenCalledTimes(2));
  const title2 = await screen.findByLabelText("보고서 제목");
  await waitFor(() => expect(title2).toHaveValue("제목"));
  await userEvent.clear(title2);
  await userEvent.type(title2, "다시 고침");
  await userEvent.click(screen.getByRole("button", { name: "구조안" }));  // 이번 실패는 412 가 아니다
  expect(await screen.findByText("이동을 중단했습니다", { exact: false })).toBeInTheDocument();
  expect(document.querySelector(".sources-screen")).not.toBeNull();
});

it("편집 탭이 충돌 상태면 이탈 시 편집기 자체 안내만 남고 일반 이동 중단 배너는 뜨지 않는다 (묶음 최종 리뷰 2)", async () => {
  vi.mocked(api.putDeck).mockRejectedValue(
    new ApiError(412, "다른 창이나 프로그램에서 이 프로젝트가 먼저 저장되었습니다."));
  await openEditorAndEdit("둘");
  await userEvent.click(screen.getByRole("button", { name: "구조안" }));  // 플러시 → 412 → 편집기 충돌
  expect(await screen.findByRole("button", { name: "서버 내용으로 되돌리기" })).toBeInTheDocument();
  // 편집기의 정답은 재시도가 아니라 되돌리기이므로 "다시 시도" 를 권하는 일반 배너는 생략한다
  expect(screen.queryByText("이동을 중단했습니다", { exact: false })).toBeNull();
  expect(document.querySelector(".editor-screen")).not.toBeNull();
});
