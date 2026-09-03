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
