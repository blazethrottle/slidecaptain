import { act, renderHook, waitFor } from "@testing-library/react";
import { api } from "../api/client";
import { applyTextEdit } from "../editor/slotOps";
import { deckWith, planWith } from "../test/fixtures";
import { useDeckEditor } from "./useDeckEditor";

vi.mock("../api/client", async original => {
  const mod = await original<typeof import("../api/client")>();
  return { ...mod, api: { ...mod.api, measure: vi.fn(), putDeck: vi.fn() } };
});
const original = deckWith(["원본"]);
const persisted = applyTextEdit(original, { chapterId: "c1", slot: "bullets", index: 0 }, "서버 확인 후보");
beforeEach(() => {
  vi.mocked(api.measure).mockResolvedValue(planWith(["서버 확인 후보"]));
  vi.mocked(api.putDeck).mockResolvedValue({ ok: true });
});

it("이미 guard와 스냅샷으로 저장한 후보는 부모·저장 기준만 갱신하고 PUT을 중복하지 않는다", async () => {
  const onDeckChange = vi.fn();
  const ui = renderHook(() => useDeckEditor("synthetic", original, onDeckChange, { measureMs: 0, saveMs: 0 }));
  await act(async () => ui.result.current.acceptSaved(persisted));
  expect(ui.result.current.deck).toBe(persisted); expect(ui.result.current.saveState).toBe("저장됨");
  expect(onDeckChange).toHaveBeenCalledTimes(1); expect(onDeckChange).toHaveBeenCalledWith(persisted);
  expect(await ui.result.current.flushSave()).toBe(true);
  ui.unmount();
  expect(api.putDeck).not.toHaveBeenCalled();
});

it("서버 저장 후보는 undo 기록을 남기고 되돌릴 때에만 원래 문서를 저장한다", async () => {
  const ui = renderHook(() => useDeckEditor("synthetic", original, vi.fn(), { measureMs: 0, saveMs: 100000 }));
  await act(async () => ui.result.current.acceptSaved(persisted));
  expect(ui.result.current.canUndo).toBe(true); expect(api.putDeck).not.toHaveBeenCalled();
  await act(async () => ui.result.current.undo());
  expect(ui.result.current.deck).toBe(original);
  await act(async () => expect(await ui.result.current.flushSave()).toBe(true));
  expect(api.putDeck).toHaveBeenCalledTimes(1);
  expect(api.putDeck).toHaveBeenCalledWith("synthetic", original, true);
});

it("수락한 저장본 후 새 편집은 새 내용만 한 번 저장한다", async () => {
  const ui = renderHook(() => useDeckEditor("synthetic", original, vi.fn(), { measureMs: 0, saveMs: 0 }));
  await act(async () => ui.result.current.acceptSaved(persisted));
  const changed = applyTextEdit(persisted, { chapterId: "c1", slot: "bullets", index: 0 }, "추가 편집");
  await act(async () => ui.result.current.apply(() => changed));
  await waitFor(() => expect(api.putDeck).toHaveBeenCalledTimes(1));
  expect(api.putDeck).toHaveBeenCalledWith("synthetic", changed, true);
  await waitFor(() => expect(ui.result.current.saveState).toBe("저장됨"));
});

it("서버 후보 수락과 같은 배치에서 화면이 내려가도 이전 deckRef를 자동 저장하지 않는다", async () => {
  const onDeckChange = vi.fn();
  const ui = renderHook(() => useDeckEditor("synthetic", original, onDeckChange, { measureMs: 0, saveMs: 0 }));
  await act(async () => {
    ui.result.current.acceptSaved(persisted);
    ui.unmount();
  });
  expect(api.putDeck).not.toHaveBeenCalled();
  expect(onDeckChange).toHaveBeenCalledTimes(1);
  expect(onDeckChange).toHaveBeenCalledWith(persisted);
});
