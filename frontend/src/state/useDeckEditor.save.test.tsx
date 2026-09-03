// 저장 상태 기계 (2026-09-03 저장 안전성 묶음 태스크 A)
// 배경: 저장할 것이 있는지를 참조 비교로만 판단하고 저장을 직렬화하지 않아, 저장 중 되돌리기(FC-01)와
// 겹친 PUT 역순 착지(FC-04)에서 서버와 화면이 어긋났다. 되돌리기로 저장본과 같아지면 '저장 대기' 가 남았다(FC-03).
import { act, renderHook, waitFor } from "@testing-library/react";
import { api, ApiError } from "../api/client";
import { applyTextEdit } from "../editor/slotOps";
import { bulletsOf, deckWith, deferred, planWith, sleep } from "../test/fixtures";
import { useDeckEditor } from "./useDeckEditor";

vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return { ...mod, api: { ...mod.api, measure: vi.fn(), putDeck: vi.fn(), getDeck: vi.fn() } };
});

const S = deckWith(["하나"]);
const E1 = applyTextEdit(S, { chapterId: "c1", slot: "bullets", index: 0 }, "둘");
const E2 = applyTextEdit(E1, { chapterId: "c1", slot: "bullets", index: 0 }, "셋");
const stableNoop = () => {};

it("저장 진행 중 되돌리기: 착지 뒤 되돌린 상태를 자동으로 다시 저장하고 '저장됨' 이 된다 (FC-01)", async () => {
  const d1 = deferred<{ ok: boolean }>();
  vi.mocked(api.measure).mockResolvedValue(planWith(["하나"]));
  vi.mocked(api.putDeck).mockImplementationOnce(() => d1.promise).mockResolvedValue({ ok: true });
  const onDeckChange = vi.fn();
  const { result } = renderHook(() =>
    useDeckEditor("p1", S, onDeckChange, { measureMs: 0, saveMs: 0 }));

  await act(async () => { result.current.apply(() => E1); });
  await waitFor(() => expect(api.putDeck).toHaveBeenCalledTimes(1));
  await act(async () => { result.current.undo(); });
  expect(result.current.deck).toBe(S);

  await act(async () => { d1.resolve({ ok: true }); });
  // 두 번째 PUT 이 되돌린 상태(S)를 올리고, 부모도 S 를 진본으로 안다
  await waitFor(() => expect(api.putDeck).toHaveBeenCalledTimes(2));
  expect(bulletsOf(vi.mocked(api.putDeck).mock.calls[1][1])).toEqual(["하나"]);
  await waitFor(() => expect(result.current.saveState).toBe("저장됨"));
  expect(onDeckChange).toHaveBeenLastCalledWith(S);
});

it("겹친 편집: PUT 은 순차로 나가고 마지막 PUT 본문이 최신 편집이다 (FC-04)", async () => {
  const d1 = deferred<{ ok: boolean }>();
  vi.mocked(api.measure).mockResolvedValue(planWith(["하나"]));
  vi.mocked(api.putDeck).mockImplementationOnce(() => d1.promise).mockResolvedValue({ ok: true });
  const { result } = renderHook(() =>
    useDeckEditor("p1", S, stableNoop, { measureMs: 0, saveMs: 0 }));
  await act(async () => { result.current.apply(() => E1); });
  await waitFor(() => expect(api.putDeck).toHaveBeenCalledTimes(1));
  await act(async () => { result.current.apply(() => E2); });
  await sleep(20);
  expect(api.putDeck).toHaveBeenCalledTimes(1);  // 첫 저장이 착지하기 전에는 둘째 PUT 이 나가지 않는다
  await act(async () => { d1.resolve({ ok: true }); });
  await waitFor(() => expect(api.putDeck).toHaveBeenCalledTimes(2));
  expect(bulletsOf(vi.mocked(api.putDeck).mock.calls[1][1])).toEqual(["셋"]);
  await waitFor(() => expect(result.current.saveState).toBe("저장됨"));
  expect(bulletsOf(result.current.deck)).toEqual(["셋"]);
});

it("저장 타이머 전 되돌리기로 저장본과 같아지면 '저장됨' 으로 돌아온다 (FC-03)", async () => {
  vi.mocked(api.measure).mockResolvedValue(planWith(["하나"]));
  vi.mocked(api.putDeck).mockResolvedValue({ ok: true });
  const { result } = renderHook(() =>
    useDeckEditor("p1", S, stableNoop, { measureMs: 0, saveMs: 100000 }));
  await act(async () => { result.current.apply(() => E1); });
  expect(result.current.saveState).toBe("저장 대기");
  await act(async () => { result.current.undo(); });
  expect(result.current.deck).toBe(S);
  expect(api.putDeck).not.toHaveBeenCalled();
  expect(result.current.saveState).toBe("저장됨");
});

it("저장 중 되돌리기로 저장본과 같아진 뒤 그 PUT 이 실패하면 서버와 화면이 일치하므로 '저장됨' 이다", async () => {
  // 무작위 시나리오 시드 13 에서 발견: 실패한 PUT 의 내용을 이미 되돌렸는데 표시가 '저장 실패' 에 머물렀다
  const d1 = deferred<{ ok: boolean }>();
  vi.mocked(api.measure).mockResolvedValue(planWith(["하나"]));
  vi.mocked(api.putDeck).mockImplementationOnce(() => d1.promise);
  const { result } = renderHook(() =>
    useDeckEditor("p1", S, stableNoop, { measureMs: 0, saveMs: 0 }));
  await act(async () => { result.current.apply(() => E1); });
  await waitFor(() => expect(api.putDeck).toHaveBeenCalledTimes(1));
  await act(async () => { result.current.undo(); });   // 화면은 다시 S = 저장본
  await act(async () => { d1.reject(new ApiError(500, "일시 실패")); });
  await waitFor(() => expect(result.current.saveState).toBe("저장됨"));
  expect(result.current.saveError).toBe("일시 실패");    // 서버 문제 자체는 알린다
  expect(api.putDeck).toHaveBeenCalledTimes(1);          // 되돌린 상태는 저장본과 같으므로 재저장하지 않는다
  expect(await result.current.flushSave()).toBe(true);
});

it("불안정한 onDeckChange 를 넘겨도 저장 진행 중 PUT 은 1회다 (FC-10)", async () => {
  const d1 = deferred<{ ok: boolean }>();
  vi.mocked(api.measure).mockResolvedValue(planWith(["하나"]));
  vi.mocked(api.putDeck).mockImplementation(() => d1.promise);
  const { result } = renderHook(() =>
    useDeckEditor("p1", S, () => {}, { measureMs: 0, saveMs: 0 }));
  await act(async () => { result.current.apply(() => E1); });
  await waitFor(() => expect(api.putDeck).toHaveBeenCalled());
  await sleep(150);
  expect(api.putDeck).toHaveBeenCalledTimes(1);
  await act(async () => { d1.resolve({ ok: true }); });
});

it("저장 실패 뒤에도 다음 편집은 저장을 시도한다 (체인이 실패 상태에 머물지 않는다)", async () => {
  vi.mocked(api.measure).mockResolvedValue(planWith(["하나"]));
  vi.mocked(api.putDeck).mockRejectedValueOnce(new Error("서버 중단")).mockResolvedValue({ ok: true });
  const { result } = renderHook(() =>
    useDeckEditor("p1", S, stableNoop, { measureMs: 0, saveMs: 0 }));
  await act(async () => { result.current.apply(() => E1); });
  await waitFor(() => expect(result.current.saveState).toBe("저장 실패"));
  await act(async () => { result.current.apply(() => E2); });
  await waitFor(() => expect(api.putDeck).toHaveBeenCalledTimes(2));
  await waitFor(() => expect(result.current.saveState).toBe("저장됨"));
  expect(bulletsOf(vi.mocked(api.putDeck).mock.calls[1][1])).toEqual(["셋"]);
});

it("PUT이 412를 돌려주면 conflict가 참이고, 이후 편집에는 PUT이 나가지 않으며 flushSave는 false다 (A5)", async () => {
  vi.mocked(api.measure).mockResolvedValue(planWith(["하나"]));
  vi.mocked(api.putDeck).mockRejectedValue(new ApiError(412, "다른 창에서 먼저 저장되었습니다."));
  const { result } = renderHook(() =>
    useDeckEditor("p1", S, stableNoop, { measureMs: 0, saveMs: 0 }));
  await act(async () => { result.current.apply(() => E1); });
  await waitFor(() => expect(result.current.conflict).toBe(true));
  expect(api.putDeck).toHaveBeenCalledTimes(1);
  await act(async () => { result.current.apply(() => E2); });  // 충돌 상태에서 추가 편집
  await sleep(20);
  expect(api.putDeck).toHaveBeenCalledTimes(1);  // 자동 저장이 더 나가지 않는다
  expect(await result.current.flushSave()).toBe(false);
  expect(api.putDeck).toHaveBeenCalledTimes(1);
});

it("reloadFromServer는 서버 덱을 읽어 되돌리고 저장됨으로 만들며 부모에도 알린다 (A5)", async () => {
  const serverDeck = deckWith(["서버본"]);
  vi.mocked(api.measure).mockResolvedValue(planWith(["하나"]));
  vi.mocked(api.putDeck).mockRejectedValue(new ApiError(412, "다른 창에서 먼저 저장되었습니다."));
  vi.mocked(api.getDeck).mockResolvedValue(serverDeck);
  const onDeckChange = vi.fn();
  const { result } = renderHook(() =>
    useDeckEditor("p1", S, onDeckChange, { measureMs: 0, saveMs: 0 }));
  await act(async () => { result.current.apply(() => E1); });
  await waitFor(() => expect(result.current.conflict).toBe(true));
  await act(async () => { await result.current.reloadFromServer(); });
  expect(result.current.deck).toBe(serverDeck);
  expect(result.current.saveState).toBe("저장됨");
  expect(result.current.canUndo).toBe(false);
  expect(result.current.conflict).toBe(false);
  expect(onDeckChange).toHaveBeenLastCalledWith(serverDeck);
});

it("retrySave는 flushSave의 별칭이라 저장 실패 뒤 다시 부르면 PUT을 재시도한다 (A5)", async () => {
  vi.mocked(api.measure).mockResolvedValue(planWith(["하나"]));
  vi.mocked(api.putDeck).mockRejectedValueOnce(new Error("일시 오류")).mockResolvedValue({ ok: true });
  const { result } = renderHook(() =>
    useDeckEditor("p1", S, stableNoop, { measureMs: 0, saveMs: 0 }));
  await act(async () => { result.current.apply(() => E1); });
  await waitFor(() => expect(result.current.saveState).toBe("저장 실패"));
  expect(api.putDeck).toHaveBeenCalledTimes(1);
  await act(async () => { await result.current.retrySave(); });
  expect(api.putDeck).toHaveBeenCalledTimes(2);
  await waitFor(() => expect(result.current.saveState).toBe("저장됨"));
});

it("flushSave 는 진행 중 저장이 끝난 뒤 잔여 편집까지 올리고 성공 여부를 돌려준다", async () => {
  const d1 = deferred<{ ok: boolean }>();
  vi.mocked(api.measure).mockResolvedValue(planWith(["하나"]));
  vi.mocked(api.putDeck).mockImplementationOnce(() => d1.promise).mockResolvedValue({ ok: true });
  const { result } = renderHook(() =>
    useDeckEditor("p1", S, stableNoop, { measureMs: 0, saveMs: 100000 }));
  await act(async () => { result.current.apply(() => E1); });
  const flushing = result.current.flushSave();       // E1 저장 시작 (타이머를 기다리지 않는다)
  await waitFor(() => expect(api.putDeck).toHaveBeenCalledTimes(1));
  await act(async () => { result.current.apply(() => E2); });  // 플러시 도중 새 편집
  await act(async () => { d1.resolve({ ok: true }); });
  expect(await flushing).toBe(true);
  await waitFor(() => expect(api.putDeck).toHaveBeenCalledTimes(2));
  expect(bulletsOf(vi.mocked(api.putDeck).mock.calls[1][1])).toEqual(["셋"]);
});

// 무작위 시나리오 불변조건: 편집, 되돌리기, 다시 실행, 지연 착지, 실패 1회를 섞어도
// 모든 저장이 정착하면 표시는 '저장됨' 이고 서버가 보유한 덱(마지막 성공 PUT 본문)이 화면 덱과 같다
// (계획서 적대 리뷰 범위 판정 반영). 실패한 PUT 은 서버 상태를 바꾸지 않으므로 비교 대상이 아니다:
// 저장 중 되돌리기로 화면이 저장본과 같아진 뒤 그 PUT 이 실패한 경우가 실제로 나왔다 (시드 13, 22)
function lcg(seed: number) {
  let s = seed >>> 0;
  return () => { s = (s * 1664525 + 1013904223) >>> 0; return s / 2 ** 32; };
}

describe.each(Array.from({ length: 30 }, (_, i) => i + 1))("무작위 시나리오 (시드 %i)", (seed) => {
  it("정착 뒤 서버 최종 = 화면 덱, 표시 = 저장됨", async () => {
    const rand = lcg(seed);
    const failAt = Math.floor(rand() * 6);  // 몇 번째 PUT 을 실패시킬지 (없을 수도 있다)
    let putCount = 0;
    let server = S;                 // 서버가 보유한 덱: 성공한 PUT 만 바꾼다
    const trace: string[] = [];     // 실패 시 순서를 재구성하기 위한 사건 기록
    vi.mocked(api.measure).mockResolvedValue(planWith(["하나"]));
    vi.mocked(api.putDeck).mockImplementation((_p, d) => new Promise((resolve, reject) => {
      const n = putCount++;
      trace.push(`PUT#${n} 시작 ${bulletsOf(d)}`);
      setTimeout(() => {
        if (n === failAt) { trace.push(`PUT#${n} 실패`); reject(new Error("일시 실패")); }
        else { trace.push(`PUT#${n} 성공`); server = d; resolve({ ok: true }); }
      }, Math.floor(rand() * 4));
    }));
    const { result } = renderHook(() =>
      useDeckEditor("p1", S, () => {}, { measureMs: 0, saveMs: Math.floor(rand() * 3) }));
    let n = 0;
    for (let step = 0; step < 8; step++) {
      const r = rand();
      await act(async () => {
        if (r < 0.55) { result.current.apply((d) => applyTextEdit(d, { chapterId: "c1", slot: "bullets", index: 0 }, `v${++n}`)); trace.push(`편집 v${n}`); }
        else if (r < 0.8) { result.current.undo(); trace.push("되돌리기"); }
        else { result.current.redo(); trace.push("다시 실행"); }
        await sleep(Math.floor(rand() * 4));
      });
    }
    // 정착: 플러시가 잔여 편집을 올린다. 실패 1회가 플러시의 PUT 에 걸릴 수 있으므로 실패하면 한 번 더 플러시한다
    let ok = false;
    await act(async () => { ok = await result.current.flushSave(); });
    if (!ok) await act(async () => { ok = await result.current.flushSave(); });
    expect(ok, trace.join("\n")).toBe(true);
    await waitFor(() => expect(result.current.saveState, trace.join("\n")).toBe("저장됨"));
    expect(bulletsOf(server), trace.join("\n")).toEqual(bulletsOf(result.current.deck));
  });
});
