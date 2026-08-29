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
