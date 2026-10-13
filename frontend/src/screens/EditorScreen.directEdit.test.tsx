// 편집 화면의 직접 수정 모드 (D3c-3, 계획 4.5). jsdom이 흉내 내지 못하는 좌표, 배율, 키 자동 반복, 실제 포인터
// 잡기 순서는 D3c-4의 실제 브라우저 확인에서 본다. 여기서는 규칙(초점과 선택, 키 범위, 되돌리기 단위, 끌기 끝)을 본다
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api, type Deck, type Preset, type RenderPlan } from "../api/client";
import { EditorScreen } from "./EditorScreen";

vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return { ...mod, api: { ...mod.api, measure: vi.fn(), putDeck: vi.fn(), getPreset: vi.fn(), getDeck: vi.fn(),
    saveDraft: vi.fn(), listDrafts: vi.fn(), fontLimit: vi.fn() } };
});

const preset = {
  fonts: { korean: "Noto Sans KR", latin: "Noto Sans KR" },
  font_roles: { cover_title_pt: 28, section_title_pt: 24, title_pt: 20, subtitle_pt: 14, body_pt: 12, box_pt: 12,
    table_pt: 12, footnote_pt: 9, page_number_pt: 9, eyebrow_pt: 10.5 },
  colors: { text: "202020", accent: "1F4E79", box_fill: "EEF3F9", table_header_fill: "F2F2F2", border: "D0D7E2",
    background: "FFFFFF", danger: "B42318", surface1: "F4F6F8", accent1: "244C83" },
  spacing: {}, bullet_marker: { char: "•", font: "Arial" }, page_width_pt: 960, page_height_pt: 540, language: "ko-KR",
} as unknown as Preset;
const project = { name: "p1", title: "제목", updated_at: "", status: "ok" as const };

const deck: Deck = {
  schema_version: 1,
  meta: { title: "제목", report_type: "research", audience: "", presenter: "", preset_overrides: {} },
  structure: { chapters: [{ id: "c1", topic: "주제", conclusion: "", template: "bullet_box", source_refs: [] }] },
  slides: [{ chapter_id: "c1", eyebrow: "", subtitle: "", slots: {
    template: "bullet_box", bullets: [{ text: "하나", level: 0 }, { text: "둘", level: 0 }], conclusion: "결론",
    footnote: "출처" } }],
};
const para = (text: string, font = 12) => ({ text, level: 0, font_pt: font, bold: false, color: "202020",
  align: "left" as const, bullet: false, lines: [text] });
const plan: RenderPlan = {
  page_width_pt: 960, page_height_pt: 540,
  style: { korean_font: "Noto Sans KR", latin_font: "Noto Sans KR", text_color: "202020", box_padding_pt: 10,
    line_spacing: 1.4, bullet_indent_pt: 18, bullet_gap_pt: 6, table_cell_pad_x_pt: 6, table_cell_pad_y_pt: 3,
    border_width_pt: 0.75, bullet_char: "•", bullet_font: "Arial" },
  slides: [{ chapter_id: "c1", template: "bullet_box", warnings: [], frames: [
    { name: "c1:title", x: 50, y: 36, w: 860, h: 40, fill: null, border: null, valign: "top", table: null, paras: [para("주제", 20)] },
    { name: "c1:bullets", x: 50, y: 92, w: 860, h: 300, fill: null, border: null, valign: "top", table: null,
      paras: [{ ...para("하나"), bullet: true }, { ...para("둘"), bullet: true }] },
    { name: "c1:conclusion", x: 50, y: 400, w: 860, h: 60, fill: "EEF3F9", border: "D0D7E2", valign: "top", table: null, paras: [para("결론")] },
    { name: "c1:footnote", x: 50, y: 470, w: 860, h: 20, fill: null, border: null, valign: "top", table: null, paras: [para("출처", 9)] },
    { name: "c1:page_number", x: 850, y: 512, w: 60, h: 16, fill: null, border: null, valign: "top", table: null, paras: [para("1", 9)] },
  ] }],
};

beforeEach(() => {
  vi.mocked(api.measure).mockResolvedValue(plan);
  vi.mocked(api.putDeck).mockResolvedValue({ ok: true });
  vi.mocked(api.getPreset).mockResolvedValue(preset);
  vi.mocked(api.listDrafts).mockResolvedValue([]);
  vi.mocked(api.fontLimit).mockResolvedValue({ base_pt: 12, current_pt: 12, fits_up_to_pt: 13.5, min_pt: 1, max_pt: 1131 });
});

const FAST = { measureMs: 0, saveMs: 10 };

// jsdom에는 PointerEvent가 없어 좌표와 pointerId가 전달되지 않는다. 시험용 최소 구현이다
if (!("PointerEvent" in window)) {
  class TestPointerEvent extends MouseEvent {
    pointerId: number;
    constructor(type: string, init: PointerEventInit = {}) { super(type, init); this.pointerId = init.pointerId ?? 0; }
  }
  (window as unknown as { PointerEvent: typeof TestPointerEvent }).PointerEvent = TestPointerEvent;
}
const frame = (key: string) => document.querySelector<HTMLElement>(`[data-key="${key}"]`);
const lastSaved = () => vi.mocked(api.putDeck).mock.calls.at(-1)![1] as Deck;

async function open(props: Partial<Parameters<typeof EditorScreen>[0]> = {}) {
  render(<EditorScreen project={project} deck={deck} onDeckChange={() => {}} timings={FAST} {...props} />);
  await waitFor(() => expect(frame("bullets")).not.toBeNull());
}
const modeButton = () => screen.getByRole("button", { name: /직접 수정|수정 완료/ });

describe("모드", () => {
  it("직접 수정 버튼은 모드를 켜고 끄며, 끄면 그 버튼으로 초점이 돌아온다", async () => {
    await open();
    expect(modeButton()).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(modeButton());
    expect(modeButton()).toHaveTextContent("수정 완료");
    expect(screen.getByText(/요소를 고르세요/)).toBeInTheDocument();
    await userEvent.click(modeButton());
    await waitFor(() => expect(modeButton()).toHaveFocus());
    expect(modeButton()).toHaveTextContent("직접 수정");
  });

  it("읽기 전용에서는 모드를 열 수 없다", async () => {
    await open({ readOnly: true });
    expect(modeButton()).toBeDisabled();
  });
});

describe("키보드와 초점", () => {
  it("Tab으로 프레임에 초점이 가면 그 프레임을 고르고, 쪽 번호는 Tab 정지가 아니다", async () => {
    await open();
    act(() => frame("title")!.focus());
    expect(frame("title")).toHaveAttribute("aria-pressed", "true");
    expect(frame("title")).toHaveAccessibleName("장 제목, 주제");
    expect(frame("page_number")).not.toHaveAttribute("tabindex");
  });

  it("Enter는 첫 문단을 열고, 입력란의 Tab은 확정한 뒤 다음 문단을 연다 (재리뷰 RR13)", async () => {
    await open();
    act(() => frame("bullets")!.focus());
    fireEvent.keyDown(frame("bullets")!, { key: "Enter" });
    const editor = await screen.findByRole("textbox", { name: "내용 수정" });
    expect(editor).toHaveValue("하나");
    fireEvent.change(editor, { target: { value: "하나 고침" } });
    fireEvent.keyDown(editor, { key: "Tab" });
    expect(await screen.findByRole("textbox", { name: "내용 수정" })).toHaveValue("둘");
    await waitFor(() => expect(lastSaved().slides[0].slots).toMatchObject({ bullets: [{ text: "하나 고침" }, { text: "둘" }] }));
  });

  it("한글 조합 중의 Enter는 확정하지 않는다 (계획 리뷰 화면 S28)", async () => {
    await open();
    act(() => frame("bullets")!.focus());
    fireEvent.keyDown(frame("bullets")!, { key: "Enter" });
    const editor = await screen.findByRole("textbox", { name: "내용 수정" });
    fireEvent.change(editor, { target: { value: "하나ㄱ" } });
    fireEvent.keyDown(editor, { key: "Enter", isComposing: true });
    expect(screen.getByRole("textbox", { name: "내용 수정" })).toBeInTheDocument();
  });

  it("모드 밖의 Delete와 방향키는 아무것도 바꾸지 않고 모드를 안내한다", async () => {
    await open();
    act(() => frame("conclusion")!.focus());
    fireEvent.keyDown(frame("conclusion")!, { key: "Delete" });
    fireEvent.keyDown(frame("conclusion")!, { key: "ArrowRight" });
    expect(screen.getByRole("status", { name: "" }).textContent ?? "").toMatch(/직접 수정을 누르면/);
    expect(frame("conclusion")).not.toBeNull();
    expect(api.putDeck).not.toHaveBeenCalled();
  });

  it("모드에서 Delete는 숨기고 다음 요소로 초점을 옮기며, 목록의 다시 보이기는 그 요소로 초점을 돌린다", async () => {
    await open();
    await userEvent.click(modeButton());
    act(() => frame("conclusion")!.focus());
    fireEvent.keyDown(frame("conclusion")!, { key: "Backspace" });  // Mac의 delete 키
    expect(frame("conclusion")).toBeNull();
    await waitFor(() => expect(frame("footnote")).toHaveFocus());
    const list = screen.getByRole("region", { name: "숨긴 요소" });
    await userEvent.click(within(list).getByRole("button", { name: "다시 보이기" }));
    await waitFor(() => expect(frame("conclusion")).toHaveFocus());
  });

  it("속성 패널 버튼에 초점이 있을 때 Delete와 방향키는 요소에 닿지 않는다 (계획 리뷰 화면 S6)", async () => {
    await open();
    await userEvent.click(modeButton());
    act(() => frame("conclusion")!.focus());
    const hide = screen.getByRole("button", { name: "숨기기 (Delete)" });
    hide.focus();
    fireEvent.keyDown(hide, { key: "Delete" });
    fireEvent.keyDown(hide, { key: "ArrowRight" });
    expect(frame("conclusion")).not.toBeNull();
    expect(frame("conclusion")!.style.left).toBe("50px");
  });

  it("방향키는 1pt, Shift는 10pt 옮기고, 누르고 있는 동안의 반복은 되돌리기 한 번으로 돌아간다", async () => {
    await open();
    await userEvent.click(modeButton());
    act(() => frame("conclusion")!.focus());
    fireEvent.keyDown(frame("conclusion")!, { key: "ArrowRight" });
    expect(frame("conclusion")!.style.left).toBe("51px");
    fireEvent.keyDown(frame("conclusion")!, { key: "ArrowDown", shiftKey: true });
    expect(frame("conclusion")!.style.top).toBe("410px");
    for (let i = 0; i < 5; i++) fireEvent.keyDown(frame("conclusion")!, { key: "ArrowRight", repeat: true });
    expect(frame("conclusion")!.style.left).toBe("56px");
    expect(screen.getAllByRole("status").some((s) => /결론 상자: 가로 56pt, 세로 410pt/.test(s.textContent ?? ""))).toBe(true);
    await userEvent.click(screen.getByRole("button", { name: "되돌리기 (Ctrl+Z)" }));
    expect(frame("conclusion")!.style.left).toBe("51px");  // 반복 다섯 번이 한 항목
  });
});

describe("속성 패널", () => {
  it("위치 칸은 Enter에 반영하고 페이지 밖 값은 페이지 안으로 자른다", async () => {
    await open();
    await userEvent.click(modeButton());
    act(() => frame("conclusion")!.focus());
    const x = screen.getByRole("spinbutton", { name: "가로 위치" });
    await userEvent.clear(x);
    await userEvent.type(x, "5000{Enter}");
    expect(frame("conclusion")!.style.left).toBe("100px");  // 960 - 860
    await userEvent.click(screen.getByRole("button", { name: "위치 원래대로" }));
    expect(frame("conclusion")!.style.left).toBe("50px");
  });

  it("글자 색과 채움 색은 우리말 이름으로 고르고 원래대로 지운다. 채움은 채움이 있는 요소에만 있다", async () => {
    await open();
    await userEvent.click(modeButton());
    act(() => frame("conclusion")!.focus());
    const color = screen.getByRole("combobox", { name: "글자 색" });
    expect(within(color).getByRole("option", { name: "주의(빨강 계열)" })).toBeInTheDocument();
    await userEvent.selectOptions(color, "danger");
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "채움 색" }), "surface1");
    await waitFor(() => expect(lastSaved().slides[0].direct_edits).toEqual({ conclusion: { text_color: "danger", fill: "surface1" } }));
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "글자 색" }), "");
    await waitFor(() => expect(lastSaved().slides[0].direct_edits).toEqual({ conclusion: { fill: "surface1" } }));
    act(() => frame("bullets")!.focus());
    expect(screen.queryByRole("combobox", { name: "채움 색" })).toBeNull();
  });

  it("글자 크기 칸은 넘치지 않는 최대 크기를 보이고, 고른 크기를 배율로 저장한다", async () => {
    await open();
    await userEvent.click(modeButton());
    act(() => frame("conclusion")!.focus());
    expect(await screen.findByText("이 상자에서 넘치지 않는 최대 크기: 13.5pt")).toBeInTheDocument();
    const size = screen.getByRole("spinbutton", { name: "글자 크기(pt)" });
    await userEvent.clear(size);
    await userEvent.type(size, "15{Enter}");
    await waitFor(() => expect(lastSaved().slides[0].direct_edits).toEqual({ conclusion: { font_scale: 1.25 } }));
    await userEvent.clear(size);
    await userEvent.type(size, "200{Enter}");
    expect(screen.getByRole("alert")).toHaveTextContent("1pt부터 72pt까지");
  });

  it("모드 밖에서는 숨긴 요소 수를 미리보기 모서리에 보이고 누르면 모드와 목록을 연다", async () => {
    await open({ deck: { ...deck, slides: [{ ...deck.slides[0], direct_edits: { footnote: { hidden: true } } }] } });
    await userEvent.click(screen.getByRole("button", { name: "숨긴 요소 1개" }));
    expect(modeButton()).toHaveAttribute("aria-pressed", "true");
    await waitFor(() => expect(screen.getByRole("region", { name: "숨긴 요소" })).toHaveFocus());
  });
});

describe("끌기 (jsdom 규칙만)", () => {
  async function selected() {
    await open();
    await userEvent.click(modeButton());
    act(() => frame("conclusion")!.focus());
    return frame("conclusion")!.querySelector<HTMLElement>(".move-handle")!;
  }
  it("손잡이를 4px 넘게 끌어 놓으면 한 번 반영하고, 뒤따른 잡기 해제는 무시한다", async () => {
    const handle = await selected();
    fireEvent.pointerDown(handle, { pointerId: 1, button: 0, clientX: 100, clientY: 100 });
    fireEvent.pointerMove(handle, { pointerId: 1, clientX: 103, clientY: 100 });
    expect(frame("conclusion")!.style.left).toBe("50px");  // 4px 이하는 끌기가 아니다
    fireEvent.pointerMove(handle, { pointerId: 1, clientX: 130, clientY: 120 });
    expect(frame("conclusion")!.style.left).toBe("80px");
    fireEvent.pointerUp(handle, { pointerId: 1, clientX: 130, clientY: 120 });
    fireEvent(handle, new Event("lostpointercapture", { bubbles: true }));
    expect(frame("conclusion")!.style.left).toBe("80px");
    await waitFor(() => expect(lastSaved().slides[0].direct_edits).toEqual({ conclusion: { dx_pt: 30, dy_pt: 20 } }));
  });

  it("Escape와 pointerup 없는 잡기 해제는 취소한다", async () => {
    const handle = await selected();
    fireEvent.pointerDown(handle, { pointerId: 1, button: 0, clientX: 100, clientY: 100 });
    fireEvent.pointerMove(handle, { pointerId: 1, clientX: 150, clientY: 100 });
    fireEvent.keyDown(window, { key: "Escape" });
    expect(frame("conclusion")!.style.left).toBe("50px");
    fireEvent.pointerDown(handle, { pointerId: 2, button: 0, clientX: 100, clientY: 100 });
    fireEvent.pointerMove(handle, { pointerId: 2, clientX: 150, clientY: 100 });
    fireEvent(handle, new Event("lostpointercapture", { bubbles: true }));
    fireEvent.pointerUp(handle, { pointerId: 2, clientX: 150, clientY: 100 });
    expect(frame("conclusion")!.style.left).toBe("50px");
    expect(api.putDeck).not.toHaveBeenCalled();
  });

  it("모드 밖에는 손잡이가 없고 글상자 본체 누름은 끌기가 아니다", async () => {
    await open();
    act(() => frame("conclusion")!.focus());
    expect(frame("conclusion")!.querySelector(".move-handle")).toBeNull();
  });
});

describe("경합과 보호", () => {
  it("목록과 공통 슬롯이 바뀐 뒤 새 계획이 오기 전에는 끌기를 시작하지 않는다 (재리뷰 RR15)", async () => {
    await open();
    await userEvent.click(modeButton());
    act(() => frame("conclusion")!.focus());
    vi.mocked(api.measure).mockImplementation(() => new Promise(() => {}));  // 새 계획이 오지 않는다
    fireEvent.change(screen.getByRole("textbox", { name: "아이브로우" }), { target: { value: "분류" } });
    act(() => frame("conclusion")!.focus());
    const handle = frame("conclusion")!.querySelector<HTMLElement>(".move-handle")!;
    fireEvent.pointerDown(handle, { pointerId: 1, button: 0, clientX: 100, clientY: 100 });
    fireEvent.pointerMove(handle, { pointerId: 1, clientX: 150, clientY: 100 });
    fireEvent.pointerUp(handle, { pointerId: 1, clientX: 150, clientY: 100 });
    expect(frame("conclusion")!.style.left).toBe("50px");
  });

  it("선택 상자에 초점이 있으면 Ctrl+Z는 덱을 되돌리지 않는다 (계획 리뷰 화면 S6)", async () => {
    await open();
    await userEvent.click(modeButton());
    act(() => frame("conclusion")!.focus());
    fireEvent.keyDown(frame("conclusion")!, { key: "ArrowRight" });
    const color = screen.getByRole("combobox", { name: "글자 색" });
    color.focus();
    fireEvent.keyDown(color, { key: "z", ctrlKey: true });
    expect(frame("conclusion")!.style.left).toBe("51px");
    fireEvent.keyDown(document.body, { key: "z", ctrlKey: true });
    expect(frame("conclusion")!.style.left).toBe("50px");
  });
});
