import type { Slots } from "../api/client";
import { switchTemplate } from "./templateSwitch";

const bulletSlots: Slots = {
  template: "bullet_box",
  bullets: [{ text: "가", level: 0 }, { text: "나", level: 0 }],
  conclusion: "결론", footnote: "주석",
};

it("bullet_box에서 summary로: 불릿과 결론은 이사, 각주는 소실 목록", () => {
  const r = switchTemplate(bulletSlots, "summary");
  expect(r.slots.template === "summary" && r.slots.points).toHaveLength(2);
  expect(r.slots.template === "summary" && r.slots.conclusion).toBe("결론");
  expect(r.dropped.join(" ")).toContain("각주");
});

it("bullet_box에서 compare2로: 불릿은 왼쪽 카드로", () => {
  const r = switchTemplate(bulletSlots, "compare2");
  expect(r.slots.template === "compare2" && r.slots.left.bullets).toHaveLength(2);
  expect(r.slots.template === "compare2" && r.slots.right.bullets).toHaveLength(0);
});

it("compare2에서 bullet_box로: 두 카드 불릿을 합치고 소제목은 소실 목록", () => {
  const compare: Slots = {
    template: "compare2", conclusion: "결",
    left: { heading: "옵션 A", bullets: [{ text: "가", level: 0 }] },
    right: { heading: "옵션 B", bullets: [{ text: "나", level: 0 }] },
  };
  const r = switchTemplate(compare, "bullet_box");
  expect(r.slots.template === "bullet_box" && r.slots.bullets?.map((b) => b.text)).toEqual(["가", "나"]);
  expect(r.dropped.join(" ")).toContain("옵션 A");
  expect(r.dropped.join(" ")).toContain("옵션 B");
});

it("table로 바꾸면 불릿과 결론이 소실 목록에 오르고 빈 표가 생긴다", () => {
  const r = switchTemplate(bulletSlots, "table");
  expect(r.slots.template === "table" && r.slots.columns.length).toBeGreaterThan(0);
  expect(r.dropped.join(" ")).toContain("불릿");
  expect(r.dropped.join(" ")).toContain("결론");
  expect(r.slots.template === "table" && r.slots.footnote).toBe("주석");  // 각주는 table로 이사
});

it("같은 템플릿이면 그대로다", () => {
  const r = switchTemplate(bulletSlots, "bullet_box");
  expect(r.slots).toBe(bulletSlots);
  expect(r.dropped).toEqual([]);
});

it("표지로 바꾸면 슬롯에 제목, 부제, 날짜만 남고 보고자와 피보고자 칸은 없다", () => {
  const r = switchTemplate(bulletSlots, "cover");
  expect(r.slots).toEqual({ template: "cover", title: "", subtitle: "", date: "" });
});

// ---- 강조 밴드(callout) 전환 (2026-09-07 DB-1) ----
// 문장 하나뿐인 템플릿이라 결론으로 옮기는 것이 자연스럽다: bullet_box의 conclusion과
// summary의 conclusion이 이미 "그 장의 결론 한 줄"이라는 같은 의미이므로 callout의 text도
// 그 자리와 오가게 한다. 불릿과 각주는 밴드에 담을 자리가 없어 소실 목록에 오른다.

it("bullet_box에서 callout로: 결론이 밴드 문장이 되고 불릿과 각주는 소실 목록", () => {
  const r = switchTemplate(bulletSlots, "callout");
  expect(r.slots.template === "callout" && r.slots.text).toBe("결론");
  expect(r.slots.template === "callout" && r.slots.tone).toBe("surface1");
  expect(r.dropped.join(" ")).toContain("불릿");
  expect(r.dropped.join(" ")).toContain("각주");
});

it("callout에서 summary로: 밴드 문장이 결론으로 이사하고 요점은 비어 있다", () => {
  const callout: Slots = { template: "callout", text: "핵심 메시지", tone: "accent1" };
  const r = switchTemplate(callout, "summary");
  expect(r.slots.template === "summary" && r.slots.conclusion).toBe("핵심 메시지");
  expect(r.slots.template === "summary" && r.slots.points).toEqual([]);
  expect(r.dropped).toEqual([]);
});

it("callout에서 table로: 밴드 문장이 결론 취급으로 소실 목록에 오른다", () => {
  const callout: Slots = { template: "callout", text: "핵심 메시지", tone: "accent1" };
  const r = switchTemplate(callout, "table");
  expect(r.dropped.join(" ")).toContain("핵심 메시지");
});

it("callout끼리는 그대로다", () => {
  const callout: Slots = { template: "callout", text: "문장", tone: "surface1" };
  const r = switchTemplate(callout, "callout");
  expect(r.slots).toBe(callout);
  expect(r.dropped).toEqual([]);
});

// ---- 카드(cards) 전환 (2026-09-07 DB-2) ----
// conclusion/footnote에 대응하는 자리가 없어 결론과 각주는 소실 목록에 오르고, 불릿은
// 최소 카드 수(2개)로 고르게 나눠 담는다.

it("bullet_box에서 cards로: 불릿이 두 카드로 고르게 나뉘고 결론과 각주는 소실 목록", () => {
  const r = switchTemplate(bulletSlots, "cards");
  expect(r.slots.template === "cards" && r.slots.cards).toHaveLength(2);
  expect(r.slots.template === "cards" && r.slots.cards[0].bullets).toHaveLength(1);
  expect(r.slots.template === "cards" && r.slots.cards[1].bullets).toHaveLength(1);
  expect(r.dropped.join(" ")).toContain("결론");
  expect(r.dropped.join(" ")).toContain("각주");
});

it("cards에서 bullet_box로: 카드들의 불릿을 합치고 배지, 소제목, 꼬리 라벨은 소실 목록", () => {
  const cards: Slots = {
    template: "cards",
    cards: [
      { badge: "신규", heading: "카드 A", bullets: [{ text: "가", level: 0 }], tail: "자세히", emphasis: false },
      { badge: "", heading: "카드 B", bullets: [{ text: "나", level: 0 }], tail: "", emphasis: true },
    ],
  };
  const r = switchTemplate(cards, "bullet_box");
  expect(r.slots.template === "bullet_box" && r.slots.bullets?.map((b) => b.text)).toEqual(["가", "나"]);
  expect(r.dropped.join(" ")).toContain("신규");
  expect(r.dropped.join(" ")).toContain("카드 A");
  expect(r.dropped.join(" ")).toContain("자세히");
  expect(r.dropped.join(" ")).toContain("카드 B");
});

it("cards끼리는 그대로다", () => {
  const cards: Slots = { template: "cards", cards: [
    { badge: "", heading: "A", bullets: [], tail: "", emphasis: false },
    { badge: "", heading: "B", bullets: [], tail: "", emphasis: false },
  ] };
  const r = switchTemplate(cards, "cards");
  expect(r.slots).toBe(cards);
  expect(r.dropped).toEqual([]);
});

// ---- 번호 단계(process) 전환 (2026-09-07 DB-3) ----
// 결론/각주에 대응하는 자리가 없어 결론과 각주는 소실 목록에 오른다. 단계 제목은 다른
// 템플릿의 불릿과 같은 자리다: 순서 목록이라는 의미가 통해서 서로 오갈 수 있다.

it("bullet_box에서 process로: 불릿이 단계 제목이 되고 결론과 각주는 소실 목록", () => {
  const r = switchTemplate(bulletSlots, "process");
  // 불릿 2개뿐이라 최소 단계 수(3개)를 채우려고 빈 제목 하나가 더 붙는다
  expect(r.slots.template === "process" && r.slots.steps.map((s) => s.heading)).toEqual(["가", "나", ""]);
  expect(r.dropped.join(" ")).toContain("결론");
  expect(r.dropped.join(" ")).toContain("각주");
});

it("불릿이 6개보다 많으면 process로 옮길 때 초과분은 소실 목록에 오른다", () => {
  const many: Slots = {
    template: "bullet_box",
    bullets: Array.from({ length: 8 }, (_, i) => ({ text: `항목${i}`, level: 0 as const })),
    conclusion: "결", footnote: "",
  };
  const r = switchTemplate(many, "process");
  expect(r.slots.template === "process" && r.slots.steps).toHaveLength(6);
  expect(r.dropped.join(" ")).toContain("단계 2개");
});

it("들여쓰기가 있는 불릿을 process로 옮기면 소실 목록에 들여쓰기 손실이 남는다 (리뷰 닛 1)", () => {
  // ProcessStep에는 들여쓰기 깊이를 담을 자리가 없다: 단계 제목은 평문으로만 옮겨지고
  // level은 조용히 버려졌었다. 몇 개가 버려졌는지 안내한다.
  const indented: Slots = {
    template: "bullet_box",
    bullets: [
      { text: "가", level: 0 }, { text: "나", level: 1 }, { text: "다", level: 1 },
    ],
    conclusion: "", footnote: "",
  };
  const r = switchTemplate(indented, "process");
  expect(r.slots.template === "process" && r.slots.steps.map((s) => s.heading)).toEqual(["가", "나", "다"]);
  expect(r.dropped.join(" ")).toContain("들여쓰기 정보 2개");
});

it("들여쓰기가 없는 불릿을 process로 옮기면 들여쓰기 손실 안내가 없다", () => {
  const r = switchTemplate(bulletSlots, "process");
  expect(r.dropped.some((d) => d.includes("들여쓰기"))).toBe(false);
});

it("process에서 bullet_box로: 단계 제목들을 불릿으로 모으고 부제와 보조 라벨은 소실 목록", () => {
  const process: Slots = {
    template: "process",
    steps: [
      { heading: "가", subtitle: "부제1", notes: ["라벨1"] },
      { heading: "나", subtitle: "", notes: [] },
      { heading: "다", subtitle: "", notes: ["라벨2", "라벨3"] },
    ],
  };
  const r = switchTemplate(process, "bullet_box");
  expect(r.slots.template === "bullet_box" && r.slots.bullets?.map((b) => b.text)).toEqual(["가", "나", "다"]);
  expect(r.dropped.join(" ")).toContain("부제1");
  expect(r.dropped.join(" ")).toContain("라벨1");
  expect(r.dropped.join(" ")).toContain("라벨2");
  expect(r.dropped.join(" ")).toContain("라벨3");
});

it("process끼리는 그대로다", () => {
  const process: Slots = { template: "process", steps: [
    { heading: "A", subtitle: "", notes: [] },
    { heading: "B", subtitle: "", notes: [] },
    { heading: "C", subtitle: "", notes: [] },
  ] };
  const r = switchTemplate(process, "process");
  expect(r.slots).toBe(process);
  expect(r.dropped).toEqual([]);
});

// ---- 행렬(matrix) 전환 (2026-09-07 DB-4) ----
// 결론/각주에 대응하는 자리가 없어 결론과 각주는 소실 목록에 오른다. 분류는 process의 단계
// 제목과 같은 이유로 다른 템플릿의 불릿과 같은 자리다: 순서 목록이라는 의미가 통해서 서로
// 오갈 수 있다. 대표 항목과 나열은 다른 템플릿에 대응하는 자리가 없어 소실 목록에 남는다.

it("bullet_box에서 matrix로: 불릿이 분류가 되고 결론과 각주는 소실 목록", () => {
  const r = switchTemplate(bulletSlots, "matrix");
  // 불릿 2개뿐이라 최소 행 수(3개)를 채우려고 빈 분류 하나가 더 붙는다
  expect(r.slots.template === "matrix" && r.slots.rows.map((row) => row.category)).toEqual(["가", "나", ""]);
  expect(r.dropped.join(" ")).toContain("결론");
  expect(r.dropped.join(" ")).toContain("각주");
});

it("불릿이 6개보다 많으면 matrix로 옮길 때 초과분은 소실 목록에 오른다", () => {
  const many: Slots = {
    template: "bullet_box",
    bullets: Array.from({ length: 8 }, (_, i) => ({ text: `항목${i}`, level: 0 as const })),
    conclusion: "결", footnote: "",
  };
  const r = switchTemplate(many, "matrix");
  expect(r.slots.template === "matrix" && r.slots.rows).toHaveLength(6);
  expect(r.dropped.join(" ")).toContain("행 2개");
});

it("matrix에서 bullet_box로: 분류들을 불릿으로 모으고 대표 항목과 나열은 소실 목록", () => {
  const matrix: Slots = {
    template: "matrix",
    rows: [
      { category: "가", primary: "대표1", items: ["항목1"] },
      { category: "나", primary: "", items: [] },
      { category: "다", primary: "", items: ["항목2", "항목3"] },
    ],
  };
  const r = switchTemplate(matrix, "bullet_box");
  expect(r.slots.template === "bullet_box" && r.slots.bullets?.map((b) => b.text)).toEqual(["가", "나", "다"]);
  expect(r.dropped.join(" ")).toContain("대표1");
  expect(r.dropped.join(" ")).toContain("항목1");
  expect(r.dropped.join(" ")).toContain("항목2");
  expect(r.dropped.join(" ")).toContain("항목3");
});

it("matrix끼리는 그대로다", () => {
  const matrix: Slots = { template: "matrix", rows: [
    { category: "A", primary: "", items: [] },
    { category: "B", primary: "", items: [] },
    { category: "C", primary: "", items: [] },
  ] };
  const r = switchTemplate(matrix, "matrix");
  expect(r.slots).toBe(matrix);
  expect(r.dropped).toEqual([]);
});
