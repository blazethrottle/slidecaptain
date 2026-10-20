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
      points: [{ evidence_id: "e1", label: "A팀", value: "1200.125", display: "1200.13", color: "0F8B7E", x: 148, y: 51.7, w: 200, h: 277.5 }],
    },
  } as Frame;
}

test("값 글자는 원문 대신 표시 글자(소수 2자리)를 그린다", () => {
  // 2026-10-20 회사 PC 이월표 (18) 사용자 결정 A: 소수 3자리 이상인 값은 2자리로 보이고 원문은 렌더 계획에 남는다
  for (const kind of ["bar", "column"] as const) {
    const { unmount } = render(<ChartPreview frame={chartFrame(kind)} />);
    expect(screen.getByText("1200.13")).toBeTruthy();
    expect(screen.queryByText("1200.125")).toBeNull();
    expect(screen.getByRole("img").getAttribute("aria-label")).toContain("A팀 1200.13원");
    unmount();
  }
});

test("가로 막대의 값 축 글자는 PowerPoint처럼 눈금 가운데, 축 아래 글자 크기의 1.95배 기준선에 둔다", () => {
  // 2026-10-20 회사 PC 실측(build 20430, 12pt): 0과 최댓값의 획은 축 아래 14.5~23.5pt, 눈금 가운데였다.
  // 종전 미리보기는 기준선 1배(획 3.0~12.2pt)에 0은 시작 맞춤, 최댓값은 끝 맞춤이었다
  render(<ChartPreview frame={chartFrame("bar")} />);
  const y0 = 24 + 305.2;
  for (const [text, x] of [["0", 48], ["1320", 848]] as const) {
    const label = screen.getByText(text);
    expect(label.getAttribute("text-anchor")).toBe("middle");
    expect(Number(label.getAttribute("x"))).toBeCloseTo(x);
    expect(Number(label.getAttribute("y"))).toBeCloseTo(y0 + 12 * 1.95);
  }
});

test("세로 막대의 값 축 글자는 PowerPoint처럼 축 왼쪽에 끝 맞춤하고 눈금 높이에 둔다", () => {
  // 2026-10-20 회사 PC 실측(build 20430, 12pt): 0과 최댓값은 축 왼쪽 약 13.5pt에 끝 맞춤되고 획 가운데가 눈금 높이다.
  // 종전 미리보기는 0을 그림 영역 아래(가로 막대와 같은 자리)에 그렸다
  render(<ChartPreview frame={chartFrame("column")} />);
  for (const [text, tick] of [["0", 24 + 305.2], ["1320", 24]] as const) {
    const label = screen.getByText(text);
    expect(label.getAttribute("text-anchor")).toBe("end");
    expect(Number(label.getAttribute("x"))).toBeCloseTo(48 - 12 * 1.125);
    expect(Number(label.getAttribute("y"))).toBeCloseTo(tick + 12 / 3);
  }
});

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
