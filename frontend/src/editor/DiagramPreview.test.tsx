import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import fixture from "../../../backend/tests/fixtures/q3b-render.json";
import type { RenderPlan } from "../api/client";
import { Preview } from "./Preview";

const plan = fixture.render_plan as RenderPlan;
const page = plan.slides[0].diagram!;

function preview(onSelect = vi.fn(), onCommitText = vi.fn()) {
  return render(<Preview slide={plan.slides[0]} style={plan.style}
    pageW={plan.page_width_pt} pageH={plan.page_height_pt}
    selected={null} onSelect={onSelect} onCommitText={onCommitText} />);
}

it("백엔드가 계산한 노드 중심선 좌표와 모든 조건을 표시한다", () => {
  const { container } = preview();
  expect(screen.getByRole("group", { name: "도식 미리보기" })).toBeInTheDocument();
  for (const node of page.layout.nodes) {
    const shape = container.querySelector(`[data-diagram-node="${node.node.id}"]`)!;
    for (const [attr, value] of Object.entries(node.bounds)) {
      expect(shape).toHaveAttribute({ w: "width", h: "height" }[attr] ?? attr, String(value));
    }
    expect(shape).toHaveAttribute("stroke-width", String(page.layout.border_width_pt));
    expect(shape).toHaveAttribute("data-evidence-ids", node.node.evidence_ids.join(" "));
    node.texts.forEach((text, index) => {
      const element = container.querySelector(`[data-diagram-text="${node.node.id}:${index}"]`)!;
      expect(element.textContent).toBe(text.lines.join("\n"));
      expect(element).toHaveStyle({ left: `${text.bounds.x}px`, top: `${text.bounds.y}px`,
        fontSize: `${text.font_pt}px`, lineHeight: `${text.line_height_pt}px`, whiteSpace: "pre" });
    });
  }
});

it("흐름 화살표와 제안/참조 선의 원래 점과 dash를 사용한다", () => {
  const { container } = preview();
  for (const edge of page.layout.edges) {
    const line = container.querySelector(`[data-diagram-edge="${edge.edge.id}"]`)!;
    expect(line).toHaveAttribute("x1", String(edge.start.point.x));
    expect(line).toHaveAttribute("x2", String(edge.end.point.x));
    expect(line).toHaveAttribute("y1", String(edge.start.point.y));
    expect(line).toHaveAttribute("y2", String(edge.end.point.y));
    expect(line).toHaveAttribute("stroke-linecap", "butt");
    expect(line).toHaveAttribute("stroke-dasharray", edge.dash_pattern_pt.length ? edge.dash_pattern_pt.join(" ") : "none");
    const arrow = container.querySelector(`[data-diagram-arrow="${edge.edge.id}"]`);
    if (edge.arrow_points.length) {
      expect(arrow).toHaveAttribute("points", edge.arrow_points.map(p => `${p.x},${p.y}`).join(" "));
      expect(arrow).toHaveAttribute("stroke", "none");
    } else expect(arrow).toBeNull();
  }
});

it("제목과 각주를 한 번씩 표시하고 클릭해도 슬롯 편집을 열지 않는다", async () => {
  const onSelect = vi.fn(), onCommitText = vi.fn();
  const { container } = preview(onSelect, onCommitText);
  for (const frame of page.headers) {
    const text = container.querySelector(`[data-diagram-header="${frame.name}"]`)!;
    expect(text).toHaveTextContent(frame.paras[0].text);
    expect(text).toHaveStyle({ left: `${frame.x}px`, top: `${frame.y}px` });
    expect(container.querySelectorAll(`[data-diagram-header="${frame.name}"]`)).toHaveLength(1);
    await userEvent.click(text);
  }
  await userEvent.click(screen.getByText("요청 접수"));
  expect(onSelect).not.toHaveBeenCalled();
  expect(onCommitText).not.toHaveBeenCalled();
  expect(container.querySelector("textarea")).toBeNull();
});

it("출력 문자열을 HTML로 실행하지 않고 빈 줄을 보존한다", () => {
  const changed = structuredClone(plan);
  const text = changed.slides[0].diagram!.layout.nodes[0].texts[1];
  text.text = '<img src=x onerror="alert(1)">\n\nA & B';
  text.lines = ['<img src=x onerror="alert(1)">', '', 'A & B'];
  const { container } = render(<Preview slide={changed.slides[0]} style={changed.style}
    pageW={changed.page_width_pt} pageH={changed.page_height_pt}
    selected={null} onSelect={vi.fn()} onCommitText={vi.fn()} />);
  expect(container.querySelector("img")).toBeNull();
  expect(container.querySelector('[data-diagram-text="intake:1"]')!.textContent).toBe(text.text);
});
