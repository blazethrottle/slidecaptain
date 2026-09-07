import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { SlidePlan } from "../api/client";
import { Preview } from "./Preview";

const style = {
  korean_font: "Noto Sans KR", latin_font: "Noto Sans KR", text_color: "202020",
  box_padding_pt: 10, line_spacing: 1.4, bullet_indent_pt: 18, bullet_gap_pt: 6,
  table_cell_pad_x_pt: 6, table_cell_pad_y_pt: 3, border_width_pt: 0.75,
  bullet_char: "•", bullet_font: "Arial",
};

const slide: SlidePlan = {
  chapter_id: "c1",
  template: "bullet_box",
  warnings: [{ chapter_id: "c1", slot: "bullets", message: "넘침", needed_pt: 400, available_pt: 300 }],
  frames: [
    { name: "c1:title", x: 50, y: 36, w: 860, h: 40, fill: null, border: null, valign: "top", table: null,
      paras: [{ text: "장 제목", level: 0, font_pt: 20, bold: true, color: "202020",
        align: "left", bullet: false, lines: ["장 제목"] }] },
    { name: "c1:bullets", x: 50, y: 92, w: 860, h: 300, fill: null, border: null, valign: "top", table: null,
      paras: [{ text: "첫 불릿 문장", level: 0, font_pt: 12, bold: false, color: "202020",
        align: "left", bullet: true, lines: ["첫 불릿", "문장"] }] },
    { name: "c1:page_number", x: 850, y: 512, w: 60, h: 16, fill: null, border: null, valign: "top", table: null,
      paras: [{ text: "1", level: 0, font_pt: 9, bold: false, color: "202020",
        align: "right", bullet: false, lines: ["1"] }] },
  ],
};

it("엔진의 줄바꿈 결과를 줄 단위로 그린다", () => {
  render(<Preview slide={slide} style={style} pageW={960} pageH={540}
    selected={null} onSelect={() => {}} onCommitText={() => {}} />);
  expect(screen.getByText("첫 불릿")).toBeInTheDocument();
  expect(screen.getByText("문장")).toBeInTheDocument();  // 한 문단이 두 줄 div
});

it("경고가 있는 프레임에 warned 표시를 붙인다", () => {
  const { container } = render(<Preview slide={slide} style={style} pageW={960} pageH={540}
    selected={null} onSelect={() => {}} onCommitText={() => {}} />);
  const bullets = container.querySelector('[data-frame="c1:bullets"]');
  expect(bullets).toHaveClass("warned");
  expect(container.querySelector('[data-frame="c1:title"]')).not.toHaveClass("warned");
});

it("프레임 클릭이 선택을 알린다", async () => {
  const onSelect = vi.fn();
  render(<Preview slide={slide} style={style} pageW={960} pageH={540}
    selected={null} onSelect={onSelect} onCommitText={() => {}} />);
  await userEvent.click(screen.getByText("장 제목"));
  expect(onSelect).toHaveBeenCalledWith({ chapterId: "c1", slot: "title" });
});

it("선택된 프레임의 문단을 클릭하면 입력이 열리고 확정 시 반영된다", async () => {
  const onCommitText = vi.fn();
  render(<Preview slide={slide} style={style} pageW={960} pageH={540}
    selected={{ chapterId: "c1", slot: "title" }} onSelect={() => {}} onCommitText={onCommitText} />);
  await userEvent.click(screen.getByText("장 제목"));
  const box = await screen.findByLabelText("내용 수정");
  expect(box).toHaveValue("장 제목");
  await userEvent.clear(box);
  await userEvent.type(box, "새 제목{Enter}");
  expect(onCommitText).toHaveBeenCalledWith({ chapterId: "c1", slot: "title", index: 0 }, "새 제목");
});

it("무변경 확정은 onCommitText를 부르지 않는다", async () => {
  const onCommitText = vi.fn();
  render(<Preview slide={slide} style={style} pageW={960} pageH={540}
    selected={{ chapterId: "c1", slot: "title" }} onSelect={() => {}} onCommitText={onCommitText} />);
  await userEvent.click(screen.getByText("장 제목"));
  const box = await screen.findByLabelText("내용 수정");
  await userEvent.type(box, "{Enter}");
  expect(onCommitText).not.toHaveBeenCalled();
});

it("표 칸을 편집하면 행과 열이 담긴 참조로 반영된다", async () => {
  const tableSlide: SlidePlan = {
    chapter_id: "c1", template: "table", warnings: [],
    frames: [{ name: "c1:table", x: 50, y: 92, w: 860, h: 400, fill: null, border: null,
      valign: "top", paras: [],
      table: {
        col_widths_pt: [200, 660], header: ["구분", "내용"], rows: [["A", "값"]],
        font_pt: 12, header_fill: "F2F2F2", row_heights_pt: [22.8, 22.8],
        header_lines: [["구분"], ["내용"]], cell_lines: [[["A"], ["값"]]],
        header_fills: [], body_fills: [],
      } }],
  };
  const onCommitText = vi.fn();
  render(<Preview slide={tableSlide} style={style} pageW={960} pageH={540}
    selected={{ chapterId: "c1", slot: "table" }} onSelect={() => {}} onCommitText={onCommitText} />);
  await userEvent.click(screen.getByText("값"));
  const box = await screen.findByLabelText("내용 수정");
  await userEvent.clear(box);
  await userEvent.type(box, "새 값{Enter}");
  expect(onCommitText).toHaveBeenCalledWith(
    { chapterId: "c1", slot: "table", row: 0, col: 1 }, "새 값");
});

it("editable 이 거짓이면 stale 표시가 붙고 선택된 프레임의 문단을 클릭해도 입력이 열리지 않는다 (2026-09-03 FC-05)", async () => {
  const onSelect = vi.fn();
  render(<Preview slide={slide} style={style} pageW={960} pageH={540} editable={false}
    selected={{ chapterId: "c1", slot: "bullets" }} onSelect={onSelect} onCommitText={() => {}} />);
  expect(document.querySelector(".preview-canvas")).toHaveClass("stale");
  await userEvent.click(screen.getByText("첫 불릿"));
  expect(screen.queryByLabelText("내용 수정")).toBeNull();
  // 프레임 선택은 그대로 된다: 선택되지 않은 제목 프레임을 클릭하면 알린다
  await userEvent.click(screen.getByText("장 제목"));
  expect(onSelect).toHaveBeenCalledWith({ chapterId: "c1", slot: "title" });
});

const roundedSlide: SlidePlan = {
  chapter_id: "c2",
  template: "cards",
  warnings: [],
  frames: [
    { name: "c2:card", x: 50, y: 50, w: 300, h: 100, fill: "EAF2F1", border: "DCE3E5",
      valign: "top", table: null, radius_pt: 10, border_width_pt: null,
      paras: [{ text: "카드", level: 0, font_pt: 12, bold: false, color: "202020",
        align: "left", bullet: false, lines: ["카드"] }] },
    { name: "c2:badge", x: 50, y: 200, w: 200, h: 40, fill: "0E8C7F", border: "0E8C7F",
      valign: "middle", table: null, radius_pt: 20, border_width_pt: 2.5,
      paras: [{ text: "배지", level: 0, font_pt: 10, bold: true, color: "FFFFFF",
        align: "center", bullet: false, lines: ["배지"] }] },
    { name: "c2:plain", x: 50, y: 300, w: 300, h: 60, fill: "F4F6F7", border: null,
      valign: "top", table: null, radius_pt: null, border_width_pt: null,
      paras: [{ text: "직각", level: 0, font_pt: 12, bold: false, color: "202020",
        align: "left", bullet: false, lines: ["직각"] }] },
  ],
};

it("모서리 반경을 border-radius 로 그리고 없으면 직각으로 둔다", () => {
  const { container } = render(<Preview slide={roundedSlide} style={style} pageW={960} pageH={540}
    selected={null} onSelect={() => {}} onCommitText={() => {}} />);

  const card = container.querySelector('[data-frame="c2:card"]') as HTMLElement;
  const badge = container.querySelector('[data-frame="c2:badge"]') as HTMLElement;
  const plain = container.querySelector('[data-frame="c2:plain"]') as HTMLElement;

  expect(card.style.borderRadius).toBe("10px");
  expect(badge.style.borderRadius).toBe("20px");
  expect(plain.style.borderRadius).toBe("");
});

it("프레임별 테두리 두께가 있으면 그 값을, 없으면 계획의 기본값을 쓴다", () => {
  const { container } = render(<Preview slide={roundedSlide} style={style} pageW={960} pageH={540}
    selected={null} onSelect={() => {}} onCommitText={() => {}} />);

  const card = container.querySelector('[data-frame="c2:card"]') as HTMLElement;
  const badge = container.querySelector('[data-frame="c2:badge"]') as HTMLElement;

  expect(card.style.border).toContain("0.75px");
  expect(badge.style.border).toContain("2.5px");
});

it("표 칸별 채움이 있으면 그 색을, 없으면 머리행 단일 색을 쓴다", () => {
  const table = {
    col_widths_pt: [200, 330, 330], header: ["구분", "A안", "B안"], rows: [["비용", "높음", "낮음"]],
    font_pt: 12, header_fill: "F2F2F2", row_heights_pt: [22.8, 22.8],
    header_lines: [["구분"], ["A안"], ["B안"]], cell_lines: [[["비용"], ["높음"], ["낮음"]]],
    header_fills: ["F4F6F7", "1B2A3A", "0E8C7F"], body_fills: ["FFFFFF", "EAF2F1", "FBF3E6"],
  };
  const coloured: SlidePlan = {
    chapter_id: "c3", template: "table", warnings: [],
    frames: [{ name: "c3:table", x: 50, y: 92, w: 860, h: 200, fill: null, border: null,
      valign: "top", paras: [], radius_pt: null, border_width_pt: null, table }],
  };
  const { container } = render(<Preview slide={coloured} style={style} pageW={960} pageH={540}
    selected={null} onSelect={() => {}} onCommitText={() => {}} />);

  const cells = Array.from(container.querySelectorAll('[data-frame="c3:table"] div'))
    .filter((el) => (el as HTMLElement).style.width !== "");
  const backgrounds = cells.map((c) => (c as HTMLElement).style.background);

  expect(backgrounds.slice(0, 3)).toEqual(["rgb(244, 246, 247)", "rgb(27, 42, 58)", "rgb(14, 140, 127)"]);
  expect(backgrounds.slice(3, 6)).toEqual(["rgb(255, 255, 255)", "rgb(234, 242, 241)", "rgb(251, 243, 230)"]);
});

it("칸별 채움이 비면 머리행 칸들이 단일 색을 그대로 쓴다", () => {
  const table = {
    col_widths_pt: [200, 660], header: ["구분", "내용"], rows: [["A", "값"]],
    font_pt: 12, header_fill: "F2F2F2", row_heights_pt: [22.8, 22.8],
    header_lines: [["구분"], ["내용"]], cell_lines: [[["A"], ["값"]]],
    header_fills: [], body_fills: [],
  };
  const plain: SlidePlan = {
    chapter_id: "c4", template: "table", warnings: [],
    frames: [{ name: "c4:table", x: 50, y: 92, w: 860, h: 200, fill: null, border: null,
      valign: "top", paras: [], radius_pt: null, border_width_pt: null, table }],
  };
  const { container } = render(<Preview slide={plain} style={style} pageW={960} pageH={540}
    selected={null} onSelect={() => {}} onCommitText={() => {}} />);

  // 칸에는 폭이 지정돼 있다. 칸 안의 줄 div 와 구분하려면 그 속성으로 거른다
  const cells = Array.from(container.querySelectorAll('[data-frame="c4:table"] div'))
    .filter((el) => (el as HTMLElement).style.width !== "");
  const backgrounds = cells.map((c) => (c as HTMLElement).style.background);

  expect(backgrounds.slice(0, 2)).toEqual(["rgb(242, 242, 242)", "rgb(242, 242, 242)"]);
  expect(backgrounds.slice(2)).toEqual(["", ""]);
});

const processSlide: SlidePlan = {
  chapter_id: "c5",
  template: "process",
  // 라벨 넘침 경고의 slot은 라벨 프레임 자신의 slot("step0_labels")과 같은 접두어로
  // 시작해야 isWarned()가 그 프레임에 강조를 매칭한다 (DB-3 리뷰 발견 1: 백엔드가 예전에
  // "step0_label0"을 냈을 때는 이 접두어가 어긋나 강조가 뜨지 않았다)
  warnings: [{ chapter_id: "c5", slot: "step0_labels_0", message: "넘침", needed_pt: 40, available_pt: 14 }],
  frames: [
    { name: "c5:step0_badge", x: 50, y: 92, w: 28, h: 28, fill: "0E8C7F", border: null,
      valign: "middle", table: null,
      paras: [{ text: "1", level: 0, font_pt: 9, bold: true, color: "FFFFFF",
        align: "center", bullet: false, lines: ["1"] }] },
    { name: "c5:step0", x: 90, y: 92, w: 600, h: 60, fill: null, border: null,
      valign: "top", table: null,
      paras: [{ text: "단계 제목", level: 0, font_pt: 12, bold: true, color: "202020",
        align: "left", bullet: false, lines: ["단계 제목"] }] },
    { name: "c5:step0_labels", x: 700, y: 92, w: 140, h: 60, fill: null, border: null,
      valign: "top", table: null,
      paras: [{ text: "보조 라벨", level: 0, font_pt: 9, bold: false, color: "202020",
        align: "right", bullet: false, lines: ["보조 라벨"] }] },
  ],
};

it("process 단계의 라벨 넘침 경고가 라벨 프레임에 강조를 붙인다 (DB-3 리뷰 발견 1)", () => {
  const { container } = render(<Preview slide={processSlide} style={style} pageW={960} pageH={540}
    selected={null} onSelect={() => {}} onCommitText={() => {}} />);
  const labels = container.querySelector('[data-frame="c5:step0_labels"]');
  expect(labels).toHaveClass("warned");
  // 배지 프레임의 slot("step0_badge")은 이 경고 slot의 접두어가 아니니 강조가 붙지 않는다.
  // ("step0"은 여기서 쓰지 않는다: "step0_labels"도 "step0_"로 시작해 isWarned()가 라벨
  // 경고를 제목/부제 프레임에도 함께 매칭한다. 이는 이번 수정 대상인 리뷰 발견 1과는 다른,
  // 형제 프레임 이름이 서로의 접두어가 되는 기존 구조적 한계라 이 커밋의 범위 밖이다.)
  expect(container.querySelector('[data-frame="c5:step0_badge"]')).not.toHaveClass("warned");
});
