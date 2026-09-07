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
