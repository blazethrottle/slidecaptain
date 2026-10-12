// 보고 유형 예시 그림 (D3b-6, 계획 4.6). 10종이 서로 다른 배치인지 도형 요약으로 보고, 대체 텍스트와 "예시" 표시,
// 크게 보기의 초점 이동을 본다
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ExampleArt, EXAMPLE_PAGES } from "./ExampleArt";
import { ReportTypeExample } from "./ReportTypeExample";
import { REPORT_TYPES } from "./reportPurpose";

const types = REPORT_TYPES.map(([value]) => value);

function summary(svg: SVGElement): string {
  const counts: Record<string, number> = {};
  svg.querySelectorAll("*").forEach((el) => { counts[el.tagName] = (counts[el.tagName] ?? 0) + 1; });
  return JSON.stringify(Object.entries(counts).sort());
}

test("10종의 도형 배치 요약(요소 종류와 개수)이 모두 서로 다르다", () => {
  const summaries = types.map((type) => {
    const { container, unmount } = render(<ExampleArt type={type} />);
    const result = summary(container.querySelector("svg")!);
    unmount();
    return result;
  });
  expect(new Set(summaries).size).toBe(10);
});

test("대체 텍스트가 모두 있고 서로 다르며, 문장으로 쓰고 기호를 쓰지 않는다 (리뷰 U9)", () => {
  const labels = types.map((type) => {
    const { unmount } = render(<ExampleArt type={type} />);
    const label = screen.getByRole("img").getAttribute("aria-label")!;
    unmount();
    return label;
  });
  expect(new Set(labels).size).toBe(10);
  for (const [i, label] of labels.entries()) {
    expect(label).toContain(`${REPORT_TYPES[i][1]} 예시:`);
    expect(label).not.toMatch(/[+\u2192\u00B7\u00D7]/);
  }
});

test("모든 예시에 예시 표시가 있고, 글자에 화살표 기호와 중점을 쓰지 않는다", () => {
  for (const type of types) {
    const { container, unmount } = render(<ExampleArt type={type} />);
    const texts = [...container.querySelectorAll("text")].map((t) => t.textContent);
    expect(texts).toContain("예시");
    expect(texts.join(" ")).not.toMatch(/[\u2192\u00B7\u00D7]/);
    unmount();
  }
  expect(Object.keys(EXAMPLE_PAGES).sort()).toEqual([...types].sort());
});

test("크게 보기는 대화 상자를 열어 닫기 버튼으로 초점을 옮기고, 닫으면 크게 보기 버튼으로 돌아온다 (리뷰 U8)", async () => {
  render(<ReportTypeExample selected="weekly" />);
  const enlarge = screen.getByRole("button", { name: "크게 보기" });
  await userEvent.click(enlarge);
  const dialog = screen.getByRole("dialog", { name: /주간 업무 보고 예시/ });
  expect(dialog).toHaveAttribute("aria-modal", "true");
  const close = screen.getByRole("button", { name: "닫기" });
  expect(close).toHaveFocus();
  await userEvent.tab();
  expect(close).toHaveFocus();  // 대화 상자 밖으로 나가지 않는다
  await userEvent.click(close);
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(enlarge).toHaveFocus();
  await userEvent.click(enlarge);
  await userEvent.keyboard("{Escape}");
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(enlarge).toHaveFocus();
});

test("예시 영역은 라이브 영역이 아니다 (리뷰 U9)", () => {
  const { container } = render(<ReportTypeExample selected="ir" />);
  expect(container.querySelector("[aria-live]")).toBeNull();
  expect(screen.getByRole("img", { name: /IR Pitch Deck 예시/ })).toBeInTheDocument();
});
