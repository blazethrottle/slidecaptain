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

// 사각형 위치(20 단위 격자)의 겹침 비율. 문구만 바꾸거나 요소 몇 개만 더한 같은 배치를 잡는다 (D3b-6 리뷰 R7)
function rectCells(type: (typeof types)[number]): Set<string> {
  const { container, unmount } = render(<ExampleArt type={type} />);
  const cells = new Set([...container.querySelectorAll("rect")].map((r) =>
    ["x", "y", "width", "height"].map((a) => Math.round(Number(r.getAttribute(a) ?? 0) / 20)).join(",")));
  unmount();
  return cells;
}

test("어느 두 그림도 사각형 배치의 절반 이상을 공유하지 않는다(합집합 대비)", () => {
  const cells = types.map(rectCells);
  for (let i = 0; i < cells.length; i++) {
    for (let j = i + 1; j < cells.length; j++) {
      const shared = [...cells[i]].filter((c) => cells[j].has(c)).length;
      const ratio = shared / new Set([...cells[i], ...cells[j]]).size;  // 합집합 대비 공유 비율
      expect(ratio, `${types[i]} / ${types[j]}`).toBeLessThan(0.5);
    }
  }
});

test("대체 텍스트가 모두 있고 서로 다르며, 유형과 특징을 밝히고 기호를 쓰지 않는다 (리뷰 U9)", () => {
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
  // Tab과 Shift+Tab은 닫기와 그림 영역(좁은 창의 가로 스크롤)만 오간다 (D3b-6 리뷰 R5, R7)
  const art = screen.getByRole("group", { name: "확대한 예시 그림" });
  await userEvent.tab();
  expect(art).toHaveFocus();
  await userEvent.tab();
  expect(close).toHaveFocus();
  await userEvent.tab({ shift: true });
  expect(art).toHaveFocus();
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


test("대화 상자 안의 글자를 눌러도 초점이 빠지지 않고 Esc로 닫히며, Esc는 다른 창의 처리기로 넘어가지 않는다 (D3b-6 리뷰 R2, R3)", async () => {
  const other = vi.fn();
  document.addEventListener("keydown", other);  // AI 설정 드로어처럼 문서에서 Esc를 받는 다른 창
  try {
    render(<ReportTypeExample selected="weekly" />);
    const enlarge = screen.getByRole("button", { name: "크게 보기" });
    await userEvent.click(enlarge);
    await userEvent.click(screen.getByRole("heading", { name: /주간 업무 보고 예시/ }));
    expect(screen.getByRole("button", { name: "닫기" })).toHaveFocus();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(enlarge).toHaveFocus();
    expect(other).not.toHaveBeenCalled();
  } finally {
    document.removeEventListener("keydown", other);
  }
});

test("열려 있는 동안 앱 화면을 비활성으로 두고 스크롤을 잠근다. 닫으면 되돌린다 (D3b-6 리뷰 R4)", async () => {
  const root = document.createElement("div");
  root.id = "root";
  document.body.appendChild(root);
  try {
    render(<ReportTypeExample selected="weekly" />, { container: root });
    await userEvent.click(screen.getByRole("button", { name: "크게 보기" }));
    expect(root).toHaveAttribute("inert");
    expect(document.body.style.overflow).toBe("hidden");
    expect(root.contains(screen.getByRole("dialog"))).toBe(false);  // 대화 상자는 앱 화면 밖(포털)이다
    await userEvent.keyboard("{Escape}");
    expect(root).not.toHaveAttribute("inert");
    expect(document.body.style.overflow).toBe("");
  } finally {
    root.remove();
  }
});

test("고른 유형과 다른 예시를 볼 때는 그 유형의 설명을 함께 보인다 (D3b-6 리뷰 R12)", async () => {
  render(<ReportTypeExample selected="weekly" />);
  expect(screen.getByText("주간 업무 보고 예시: 이번 주 업무 현황")).toBeInTheDocument();
  expect(screen.queryByText("현재 업무와 후속 행동을 정리합니다.")).toBeNull();
  await userEvent.click(screen.getByRole("button", { name: "다음 예시" }));
  expect(screen.getByText("현재 업무와 후속 행동을 정리합니다.")).toBeInTheDocument();
});


test("좁은 창에서 확대한 그림 영역은 화살표와 End로 가로 스크롤한다 (D3b-6 리뷰 R5)", async () => {
  render(<ReportTypeExample selected="weekly" />);
  await userEvent.click(screen.getByRole("button", { name: "크게 보기" }));
  const art = screen.getByRole("group", { name: "확대한 예시 그림" });
  Object.defineProperty(art, "scrollWidth", { value: 739, configurable: true });
  let left = 0;  // jsdom은 스크롤 위치를 바꾸지 않으므로 값을 담는다
  Object.defineProperty(art, "scrollLeft", { get: () => left, set: (v: number) => { left = Math.max(0, v); }, configurable: true });
  art.focus();
  await userEvent.keyboard("{ArrowRight}");
  expect(art.scrollLeft).toBe(40);
  await userEvent.keyboard("{Home}");
  expect(art.scrollLeft).toBe(0);
});
