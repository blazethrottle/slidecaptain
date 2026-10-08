// 충돌 시 미저장본 보존 (개정판 D2a-2)
// 412 뒤 "서버 내용으로 되돌리기"는 교체 직전 화면의 미저장 덱을 서버 drafts/에 보존한다.
// 보존이 실패하면 교체하지 않고, 사용자가 확인한 경우에만 보존 없이 교체한다.
import { act, renderHook, waitFor } from "@testing-library/react";
import { api, ApiError } from "../api/client";
import { applyTextEdit } from "../editor/slotOps";
import { deckWith, deferred, planWith } from "../test/fixtures";
import { useDeckEditor } from "./useDeckEditor";

vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return { ...mod, api: { ...mod.api, measure: vi.fn(), putDeck: vi.fn(), getDeck: vi.fn(), saveDraft: vi.fn() } };
});

const S = deckWith(["하나"]);
const E1 = applyTextEdit(S, { chapterId: "c1", slot: "bullets", index: 0 }, "둘");
const E2 = applyTextEdit(E1, { chapterId: "c1", slot: "bullets", index: 0 }, "셋");
const serverDeck = deckWith(["서버본"]);
const draftInfo = { id: "draft-20261008-100000-000001", saved_at: "2026-10-08T10:00:00+09:00",
  reason: "conflict" as const, source: "editor" as const, base_etag: null };

async function conflicted() {
  vi.mocked(api.measure).mockResolvedValue(planWith(["하나"]));
  vi.mocked(api.putDeck).mockRejectedValue(new ApiError(412, "다른 창에서 먼저 저장되었습니다."));
  vi.mocked(api.getDeck).mockResolvedValue(serverDeck);
  const hook = renderHook(() => useDeckEditor("p1", S, () => {}, { measureMs: 0, saveMs: 0 }));
  await act(async () => { hook.result.current.apply(() => E1); });
  await waitFor(() => expect(hook.result.current.conflict).toBe(true));
  return hook;
}

it("되돌리기 직전에 충돌 뒤 편집까지 포함한 미저장 덱을 보존하고 교체한다", async () => {
  vi.mocked(api.saveDraft).mockResolvedValue(draftInfo);
  const { result } = await conflicted();
  await act(async () => { result.current.apply(() => E2); });  // 충돌 뒤에도 편집은 막히지 않는다
  await act(async () => { await result.current.reloadFromServer(); });
  expect(api.saveDraft).toHaveBeenCalledOnce();
  expect(vi.mocked(api.saveDraft).mock.calls[0][1]).toMatchObject({ reason: "conflict", source: "editor" });
  expect(vi.mocked(api.saveDraft).mock.calls[0][1].deck).toBe(E2);
  expect(result.current.deck).toBe(serverDeck);
  expect(result.current.preservedDraft).toEqual(draftInfo);
  expect(result.current.conflict).toBe(false);
});

it("미저장 변경이 없는 충돌에서는 보존 요청을 보내지 않는다", async () => {
  vi.mocked(api.measure).mockResolvedValue(planWith(["하나"]));
  vi.mocked(api.getDeck).mockResolvedValue(serverDeck);
  const { result } = renderHook(() => useDeckEditor("p1", S, () => {}, { measureMs: 0, saveMs: 0 }));
  act(() => { result.current.reportConflict("도식 연결 확인 중 다른 곳에서 저장했습니다."); });
  await act(async () => { await result.current.reloadFromServer(); });
  expect(api.saveDraft).not.toHaveBeenCalled();
  expect(result.current.deck).toBe(serverDeck);
  expect(result.current.preservedDraft).toBeNull();
});

it("보존이 실패하면 교체하지 않고 복사할 내용과 확인 뒤 교체 경로를 남긴다", async () => {
  vi.mocked(api.saveDraft).mockRejectedValue(new Error("서버 응답 없음"));
  const { result } = await conflicted();
  await act(async () => { await result.current.reloadFromServer(); });
  expect(result.current.deck).toBe(E1);
  expect(result.current.conflict).toBe(true);
  expect(result.current.preserveFailure?.message).toBeTruthy();
  expect(api.getDeck).not.toHaveBeenCalled();
  await act(async () => { await result.current.reloadFromServer({ discardUnsaved: true }); });
  expect(result.current.deck).toBe(serverDeck);
  expect(result.current.preserveFailure).toBeNull();
  expect(api.saveDraft).toHaveBeenCalledOnce();  // 확인 뒤 교체는 다시 보존하지 않는다
});

it("되돌리기가 진행되는 동안 reloading이 켜지고 겹친 호출은 보존을 한 번만 보낸다", async () => {
  const pending = deferred<typeof draftInfo>();
  vi.mocked(api.saveDraft).mockImplementation(() => pending.promise);
  const { result } = await conflicted();
  let first!: Promise<void>;
  let second!: Promise<void>;
  act(() => { first = result.current.reloadFromServer(); second = result.current.reloadFromServer(); });
  await waitFor(() => expect(result.current.reloading).toBe(true));
  await act(async () => { pending.resolve(draftInfo); await first; await second; });
  expect(api.saveDraft).toHaveBeenCalledOnce();
  expect(result.current.reloading).toBe(false);
  expect(result.current.deck).toBe(serverDeck);
});


it("보존이 성공한 뒤 서버 덱 읽기가 실패해도 보존 사실과 충돌 맥락을 남긴다 (리뷰 R3)", async () => {
  vi.mocked(api.saveDraft).mockResolvedValue(draftInfo);
  const { result } = await conflicted();
  vi.mocked(api.getDeck).mockRejectedValueOnce(new Error("서버 응답 없음"));
  await act(async () => { await result.current.reloadFromServer(); });
  expect(result.current.preservedDraft).toEqual(draftInfo);
  expect(result.current.saveError).toContain("변경은 보존했지만 서버 내용을 읽지 못했습니다");
  expect(result.current.conflict).toBe(true);
});
