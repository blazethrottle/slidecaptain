// 직접 수정의 편집기 상태 (D3c-3, 계획 4.2, 4.5): 화면 정규화, 방향키 반복의 되돌리기 병합, 목록 편집의 열쇠 옮기기,
// 템플릿 전환의 비우기
import { act, renderHook } from "@testing-library/react";
import { api, type Deck } from "../api/client";
import { useDeckEditor } from "./useDeckEditor";
import { deckWith, planWith } from "../test/fixtures";
import { editElement } from "../editor/directEdit";
import { changeTemplateItems, setSlideField } from "../editor/slotOps";
import { applyTemplateSwitch } from "../editor/templateSwitch";

vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return { ...mod, api: { ...mod.api, measure: vi.fn(), putDeck: vi.fn() } };
});

beforeEach(() => {
  vi.mocked(api.measure).mockResolvedValue(planWith(["문구"]));
  vi.mocked(api.putDeck).mockResolvedValue({ ok: true });
});

const SLOW = { measureMs: 100000, saveMs: 100000 };
const offset = (d: Deck, key = "conclusion") => d.slides[0].direct_edits?.[key];

it("방향키를 누르고 있는 동안의 이동은 되돌리기 한 번으로 돌아간다", async () => {
  const initial = deckWith(["문구"]);
  const { result } = renderHook(() => useDeckEditor("p", initial, () => {}, SLOW));
  await act(async () => result.current.apply((d) => editElement(d, "c1", "conclusion", { dx_pt: 1, dy_pt: 0 }), { coalesce: true }));
  for (let i = 2; i <= 30; i++) {
    await act(async () => result.current.apply((d) => editElement(d, "c1", "conclusion", { dx_pt: i, dy_pt: 0 }), { coalesce: true }));
  }
  expect(offset(result.current.deck)).toEqual({ dx_pt: 30, dy_pt: 0 });
  await act(async () => result.current.undo());
  expect(result.current.deck).toBe(initial);
});

it("병합 사이에 다른 편집이 끼면 새 항목이 된다 (재리뷰 RR16)", async () => {
  const initial = deckWith(["문구"]);
  const { result } = renderHook(() => useDeckEditor("p", initial, () => {}, SLOW));
  await act(async () => result.current.apply((d) => editElement(d, "c1", "conclusion", { dx_pt: 1, dy_pt: 0 }), { coalesce: true }));
  await act(async () => result.current.apply((d) => editElement(d, "c1", "title", { hidden: true })));
  const hidden = result.current.deck;
  await act(async () => result.current.apply((d) => editElement(d, "c1", "conclusion", { dx_pt: 2, dy_pt: 0 }), { coalesce: true }));
  await act(async () => result.current.undo());
  expect(result.current.deck).toBe(hidden);
});

it("바뀐 것이 없는 방향키는 직전의 관계없는 편집을 병합 기준으로 만들지 않는다", async () => {
  const initial = deckWith(["문구"]);
  const { result } = renderHook(() => useDeckEditor("p", initial, () => {}, SLOW));
  await act(async () => result.current.apply((d) => editElement(d, "c1", "title", { hidden: true })));
  const hidden = result.current.deck;
  await act(async () => result.current.apply((d) => d, { coalesce: true }));  // 페이지 끝: 바뀐 것 없음
  await act(async () => result.current.apply((d) => editElement(d, "c1", "conclusion", { dx_pt: 2, dy_pt: 0 }), { coalesce: true }));
  await act(async () => result.current.undo());
  expect(result.current.deck).toBe(hidden);
});

it("요소가 사라지는 편집은 그 요소의 수정도 화면 덱에서 지운다 (재리뷰 RR5)", async () => {
  const initial = deckWith(["문구"]);
  const { result } = renderHook(() => useDeckEditor("p", initial, () => {}, SLOW));
  await act(async () => result.current.apply((d) => setSlideField(d, "c1", "eyebrow", "분류")));
  await act(async () => result.current.apply((d) => editElement(d, "c1", "eyebrow", { dx_pt: 5, dy_pt: 5 })));
  expect(offset(result.current.deck, "eyebrow")).toBeDefined();
  await act(async () => result.current.apply((d) => setSlideField(d, "c1", "eyebrow", "")));
  expect(result.current.deck.slides[0].direct_edits).toBeUndefined();
  // 다시 아이브로우를 써도 지운 수정은 돌아오지 않는다
  await act(async () => result.current.apply((d) => setSlideField(d, "c1", "eyebrow", "다시")));
  expect(result.current.deck.slides[0].direct_edits).toBeUndefined();
});

function cardsDeck(): Deck {
  const deck = deckWith([]);
  return { ...deck,
    structure: { chapters: [{ ...deck.structure.chapters[0], template: "cards" }] },
    slides: [{ ...deck.slides[0], slots: { template: "cards", cards: ["A", "B", "C"].map((h) => ({ heading: h, bullets: [], badge: "", tail: "", emphasis: false })) },
      direct_edits: { card0: { hidden: true }, card1: { dx_pt: 4, dy_pt: 0 }, card2: { text_color: "danger" } } }] };
}

it("카드를 지우면 뒤 카드의 수정이 그 카드를 따라간다 (계획 리뷰 화면 S12)", () => {
  const removed = changeTemplateItems(cardsDeck(), "c1", "remove", 1);
  const slide = removed.slides[0];
  expect(slide.slots.template === "cards" && slide.slots.cards.map((c) => c.heading)).toEqual(["A", "C"]);
  expect(slide.direct_edits).toEqual({ card0: { hidden: true }, card1: { text_color: "danger" } });
});

it("최소 개수라 지우지 못하면 열쇠를 옮기지 않는다", () => {
  const two = cardsDeck();
  const slots = two.slides[0].slots;
  if (slots.template === "cards") two.slides[0].slots = { ...slots, cards: slots.cards.slice(0, 2) };
  const same = changeTemplateItems(two, "c1", "remove", 0);
  expect(same.slides[0].direct_edits).toEqual(two.slides[0].direct_edits);
});

it("템플릿 전환은 그 장의 직접 수정을 비우고 확인 목록에 올린다 (계획 리뷰 화면 S11)", () => {
  const { deck, dropped } = applyTemplateSwitch(cardsDeck(), "c1", "bullet_box");
  expect(deck.slides[0].direct_edits).toBeUndefined();
  expect(dropped).toContain("직접 수정 3건(위치, 글자 크기, 색, 숨김)");
});
