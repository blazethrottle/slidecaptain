// 직접 수정의 화면 쪽 계약 (D3c-3). 열쇠 함수와 경고 대응이 서버와 같은지 고정 파일로 지킨다
import keysFixture from "../../../backend/tests/fixtures/frame-keys.json";
import warningsFixture from "../../../backend/tests/fixtures/warning-keys.json";
import normalizeFixture from "../../../backend/tests/fixtures/normalize-cases.json";
import type { Deck, SlidePlan } from "../api/client";
import type { ElementEdit } from "./directEdit";
import {
  clampOffset, contrastRatio, displayBoxes, editElement, frameKeys, normalizeDeckEdits, normalizeEdits, roleName,
  shiftListKeys, warningKey, withObject,
} from "./directEdit";

type Slide = Deck["slides"][number];
const samples = keysFixture.samples as Record<string, Record<string, Record<string, unknown>>>;

function sample(template: string, variant: string, common: boolean): Slide {
  // 서버 시험의 _slide와 같다. "blank"는 공백만 있는 선택 칸과 공통 슬롯이다 (D3c-1 리뷰 F6)
  const [eyebrow, subtitle] = variant === "blank" ? [" ", "\u3000"] : ["분류", "한 문장 부제"];
  return { chapter_id: "c1", slots: { template, ...samples[template][variant] } as Slide["slots"],
    eyebrow: common ? eyebrow : "", subtitle: common ? subtitle : "" };
}

it("요소 열쇠와 받는 수정 종류가 서버 frame_keys와 같다 (고정 파일 60개 구성, 공백만 있는 칸 포함)", () => {
  expect(keysFixture.cases.length).toBe(60);
  for (const c of keysFixture.cases) {
    const keys = Object.fromEntries(Object.entries(c.keys).map(([k, spec]) => [k, { kinds: spec.kinds, drag: spec.drag }]));
    expect(frameKeys(sample(c.template, c.variant, c.common)), `${c.template} ${c.variant} ${c.common}`).toEqual(keys);
    // 우리말 역할 이름도 서버 role_name과 같다. 품질 보고 문구가 서버 쪽 표를 쓴다 (D3c-2 리뷰 F6)
    for (const [k, spec] of Object.entries(c.keys)) expect(roleName(k, c.template), k).toBe(spec.name);
  }
});

it("경고 slot의 요소 대응이 서버 warning_key와 같다", () => {
  for (const c of warningsFixture.cases) expect(warningKey(c.slot, c.keys), c.slot).toBe(c.key);
});

it("정규화가 서버 normalize_edits와 같은 결과를 낸다 (고정 파일, D3c-1 리뷰 F12)", () => {
  for (const c of normalizeFixture.cases) {
    const result = normalizeEdits(c.input as unknown as Record<string, ElementEdit>, frameKeys(sample(c.template, c.variant, c.common)));
    expect(Object.keys(result), c.name).toEqual(Object.keys(c.expected));
    expect(result, c.name).toEqual(c.expected);
  }
});

describe("정규화 (서버와 같은 다섯 규칙)", () => {
  const cards = sample("cards", "full", false);
  const keys = frameKeys(cards);
  it("없는 요소, 받지 않는 종류, 효과 없는 값, 빈 객체를 버리고 열쇠를 정렬한다", () => {
    const result = normalizeEdits({
      title: { dx_pt: 10, dy_pt: -5 }, nope: { hidden: true }, card1: { fill: "ink", text_color: "accent1" },
      card0: { hidden: false, dx_pt: 0, dy_pt: 0, font_scale: 1 },
    }, keys);
    expect(Object.keys(result)).toEqual(["card1", "title"]);
    expect(result.card1).toEqual({ text_color: "accent1" });
  });
  it("바뀐 것이 없으면 같은 덱을 돌려준다", () => {
    const deck = { meta: { title: "t" }, structure: { chapters: [] }, slides: [{ ...cards, direct_edits: { title: { hidden: true } } }] } as unknown as Deck;
    expect(normalizeDeckEdits(deck)).toBe(deck);
  });
  it("숨김을 풀면 열쇠가 사라지고 direct_edits 칸도 사라진다 (재리뷰 RR23)", () => {
    const deck = { meta: { title: "t" }, structure: { chapters: [] }, slides: [{ ...cards, direct_edits: { title: { hidden: true } } }] } as unknown as Deck;
    const shown = editElement(deck, "c1", "title", { hidden: undefined });
    expect("direct_edits" in shown.slides[0]).toBe(false);
  });
});

it("목록 항목을 지우면 뒤 항목의 열쇠를 당기고 지운 항목의 수정은 버린다", () => {
  const edits = { card0: { hidden: true }, card1: { dx_pt: 1, dy_pt: 1 }, card2: { fill: "ink" as const }, title: { hidden: true } };
  expect(shiftListKeys(edits, "card", 1)).toEqual({ card0: { hidden: true }, card1: { fill: "ink" }, title: { hidden: true } });
  const steps = { step0_badge: { hidden: true }, step2: { hidden: true }, step2_labels: { hidden: true } };
  expect(shiftListKeys(steps, "step", 0)).toEqual({ step1: { hidden: true }, step1_labels: { hidden: true } });
});

describe("계산된 표시 (계획 4.5, 재리뷰 RR3)", () => {
  const plan = { chapter_id: "c1", template: "table", warnings: [], frames: [
    { name: "c1:chart", x: 50, y: 100, w: 400, h: 300, base_x: 50, base_y: 80, paras: [] },
    { name: "c1:chart_conditions", x: 50, y: 400, w: 400, h: 20, base_x: 50, base_y: 380, paras: [] },
    { name: "c1:title", x: 50, y: 36, w: 860, h: 40, paras: [] },
  ] } as unknown as SlidePlan;
  it("기본 자리에 지금 덱의 거리를 더하고 묶음을 한 번에 페이지 안으로 자른다", () => {
    const boxes = displayBoxes(plan, { table: { dx_pt: 0, dy_pt: 1000 } }, 960, 540);
    expect(boxes.get("c1:chart")!.y).toBe(540 - 320);
    expect(boxes.get("c1:chart_conditions")!.y - boxes.get("c1:chart")!.y).toBe(300);
    expect(boxes.get("c1:title")).toMatchObject({ x: 50, y: 36, hidden: false });
  });
  it("거리를 지우면(되돌리기) 계획을 만든 덱의 거리와 상관없이 기본 자리로 돌아간다", () => {
    expect(displayBoxes(plan, {}, 960, 540).get("c1:chart")).toMatchObject({ x: 50, y: 80 });
  });
  it("숨김은 지금 덱으로 정한다", () => {
    expect(displayBoxes(plan, { title: { hidden: true } }, 960, 540).get("c1:title")!.hidden).toBe(true);
  });
  it("저장할 거리를 페이지 안으로 자른다", () => {
    expect(clampOffset(plan, "table", -500, 10, 960, 540)).toEqual({ dx: -50, dy: 10 });
    expect(clampOffset(plan, "title", 10.123, 0, 960, 540)).toEqual({ dx: 10.12, dy: 0 });
  });
});

it("역할 이름과 대비", () => {
  expect(roleName("card2")).toBe("3번 카드");
  expect(roleName("step0_badge")).toBe("1단계 번호");
  expect(roleName("row1_items")).toBe("2번 행 나열");
  expect(roleName("subtitle", "cover")).toBe("표지 부제");
  expect(contrastRatio("000000", "ffffff")).toBeCloseTo(21);
  expect(contrastRatio("777777", "ffffff")).toBeLessThan(4.5);
});

it("목적격 조사를 끝 받침으로 고른다 (D3c-3 리뷰 F21)", () => {
  expect(withObject("결론 상자")).toBe("결론 상자를");
  expect(withObject("장 제목")).toBe("장 제목을");
  expect(withObject("1단계 본문")).toBe("1단계 본문을");
  expect(withObject("card9")).toBe("card9을(를)");
});

it("계산된 표시는 프레임 하나도 페이지 안으로 자른다 (D3c-3 리뷰 F15의 M7)", () => {
  const one = { chapter_id: "c1", template: "bullet_box", warnings: [], frames: [
    { name: "c1:title", x: 50, y: 36, w: 860, h: 40, base_x: 50, base_y: 36, paras: [] }] } as unknown as SlidePlan;
  expect(displayBoxes(one, { title: { dx_pt: 5000, dy_pt: -5000 } }, 960, 540).get("c1:title")).toMatchObject({ x: 100, y: 0 });
});
