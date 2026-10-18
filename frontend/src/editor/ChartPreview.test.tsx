import { render, screen } from "@testing-library/react";
import type { Frame } from "../api/client";
import { ChartPreview } from "./ChartPreview";

function chartFrame(kind: "bar" | "column"): Frame {
  return {
    name: "c1:chart", x: 50, y: 92, w: 860, h: 359.2, fill: null, border: null, valign: "top", table: null, paras: [],
    chart: {
      rule_version: "comparison-chart-plan-v1", kind, comparison_id: "cmp", claim_id: "claim", definition: "순매출", unit: "원",
      conditions: "조건", axis_minimum: "0", axis_maximum: "1320", plot_x: 48, plot_y: 24, plot_w: 800, plot_h: 305.2,
      font_pt: 12, text_color: "202020",
      points: [{ evidence_id: "e1", label: "A팀", value: "1200", color: "0F8B7E", x: 148, y: 51.7, w: 200, h: 277.5 }],
    },
  } as Frame;
}

test("세로 막대의 범주 이름은 PowerPoint처럼 축 아래 글자 크기의 2.1배에 기준선을 둔다", () => {
  // 2026-10-18 C3: PowerPoint 12pt 범주 이름 획은 축 아래 15.5~25.5pt, 종전 1.5배의 미리보기는 8.05~18.52pt였다
  render(<ChartPreview frame={chartFrame("column")} />);
  const label = screen.getByText("A팀");
  expect(Number(label.getAttribute("y"))).toBeCloseTo(24 + 305.2 + 12 * 2.1);
});

test("가로 막대의 범주 이름은 막대 가운데 높이에 그대로 둔다", () => {
  render(<ChartPreview frame={chartFrame("bar")} />);
  const label = screen.getByText("A팀");
  expect(Number(label.getAttribute("y"))).toBeCloseTo(51.7 + 277.5 / 2);
});
