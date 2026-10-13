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
    // 실제 자동 반복처럼 첫 keydown은 repeat가 아니고 그 뒤 다섯 번이 반복이다 (D3c-3 리뷰 F1)
    fireEvent.keyDown(frame("conclusion")!, { key: "ArrowRight" });
    for (let i = 0; i < 5; i++) fireEvent.keyDown(frame("conclusion")!, { key: "ArrowRight", repeat: true });
    expect(frame("conclusion")!.style.left).toBe("57px");
    expect(screen.getAllByRole("status").some((s) => /결론 상자: 가로 57pt, 세로 410pt/.test(s.textContent ?? ""))).toBe(true);
    await userEvent.click(screen.getByRole("button", { name: "되돌리기 (Ctrl+Z)" }));
    // 누르고 있던 이동 전체(첫 누름과 반복)가 한 항목이고, 앞의 Shift 이동은 남는다
    expect(frame("conclusion")!.style.left).toBe("51px");
    expect(frame("conclusion")!.style.top).toBe("410px");
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

describe("D3c-3 리뷰 반영", () => {
  it("입력란을 Enter로 확정하거나 Escape로 취소하면 초점이 그 프레임으로 돌아온다 (F7)", async () => {
    await open();
    act(() => frame("conclusion")!.focus());
    fireEvent.keyDown(frame("conclusion")!, { key: "Enter" });
    const box = await screen.findByLabelText("내용 수정");
    await userEvent.clear(box);
    await userEvent.type(box, "새 결론{Enter}");
    expect(document.activeElement).toBe(frame("conclusion"));
    await waitFor(() => expect(lastSaved().slides[0].slots).toMatchObject({ conclusion: "새 결론" }));
    const saves = vi.mocked(api.putDeck).mock.calls.length;
    fireEvent.keyDown(frame("conclusion")!, { key: "Enter" });
    const again = await screen.findByLabelText("내용 수정");
    await userEvent.type(again, "버릴 문구");
    fireEvent.keyDown(again, { key: "Escape" });
    expect(screen.queryByLabelText("내용 수정")).toBeNull();
    expect(document.activeElement).toBe(frame("conclusion"));
    // 다음 Escape는 선택을 푼다 (Escape 우선순위의 세 번째 단계)
    fireEvent.keyDown(frame("conclusion")!, { key: "Escape" });
    expect(frame("conclusion")).toHaveAttribute("aria-pressed", "false");
    await new Promise((r) => setTimeout(r, 30));
    expect(vi.mocked(api.putDeck).mock.calls.length).toBe(saves);  // 취소는 확정하지 않는다
    expect(lastSaved().slides[0].slots).toMatchObject({ conclusion: "새 결론" });
  });

  it("페이지 밖 위치는 잘라서 반영하고 칸을 실제 값으로 돌리며 알린다 (F5)", async () => {
    await open();
    await userEvent.click(modeButton());
    act(() => frame("conclusion")!.focus());
    const x = screen.getByRole("spinbutton", { name: "가로 위치" });
    await userEvent.clear(x);
    await userEvent.type(x, "-50{Enter}");
    expect(frame("conclusion")!.style.left).toBe("0px");
    expect(x).toHaveValue(0);
    expect(screen.getByText("페이지 안으로 맞췄습니다(가로 0pt).")).toBeInTheDocument();
    // 이미 0인 자리에 다시 밖의 값을 넣어 덱이 바뀌지 않아도 칸은 실제 값으로 돌아간다
    await userEvent.clear(x);
    await userEvent.type(x, "-80{Enter}");
    expect(x).toHaveValue(0);
  });

  it("되돌리기가 초점이 있던 요소를 숨기면 선택을 풀고 초점을 캔버스로 옮긴다 (F9)", async () => {
    await open();
    await userEvent.click(modeButton());
    act(() => frame("bullets")!.focus());
    fireEvent.keyDown(frame("bullets")!, { key: "Delete" });
    await userEvent.click(screen.getByRole("button", { name: "다시 보이기" }));
    await waitFor(() => expect(document.activeElement).toBe(frame("bullets")));
    fireEvent.keyDown(frame("bullets")!, { key: "z", ctrlKey: true });
    expect(frame("bullets")).toBeNull();
    await waitFor(() => expect(document.activeElement).toBe(screen.getByLabelText("슬라이드 미리보기")));
    expect(screen.queryByRole("group", { name: "직접 수정" }) ?? screen.queryByRole("region", { name: "직접 수정" })).toBeNull();
  });

  it("손잡이로 끈 뒤 다른 요소를 한 번 누르면 바로 고른다 (F2), 손잡이는 초점을 받지 않는다 (F3)", async () => {
    await open();
    await userEvent.click(modeButton());
    act(() => frame("conclusion")!.focus());
    const handle = frame("conclusion")!.querySelector<HTMLElement>(".move-handle")!;
    expect(handle).not.toHaveAttribute("tabindex");
    fireEvent.pointerDown(handle, { pointerId: 1, button: 0, clientX: 100, clientY: 100 });
    fireEvent.pointerMove(handle, { pointerId: 1, clientX: 130, clientY: 100 });
    fireEvent.pointerUp(handle, { pointerId: 1, clientX: 130, clientY: 100 });
    fireEvent.click(handle);  // 잡기 때문에 뒤따른 클릭은 손잡이로 간다
    await userEvent.click(frame("footnote")!);
    expect(frame("footnote")).toHaveAttribute("aria-pressed", "true");
  });

  it("캔버스 밖에서 놓은 누름 뒤에도 키보드 초점이 요소를 고른다 (F6)", async () => {
    await open();
    fireEvent.pointerDown(frame("title")!, { pointerId: 1, button: 0 });
    fireEvent.pointerUp(document.body, { pointerId: 1 });
    act(() => frame("footnote")!.focus());
    expect(frame("footnote")).toHaveAttribute("aria-pressed", "true");
  });

  it("장을 바꾸면 이전 장에서 만든 초점 요청을 새 장에 다시 적용하지 않는다 (F8)", async () => {
    const two: Deck = { ...deck,
      structure: { chapters: [deck.structure.chapters[0], { ...deck.structure.chapters[0], id: "c2", topic: "둘째 장" }] },
      slides: [deck.slides[0], { ...deck.slides[0], chapter_id: "c2" }] };
    const second = { ...plan.slides[0], chapter_id: "c2",
      frames: plan.slides[0].frames.map((f) => ({ ...f, name: f.name.replace("c1:", "c2:") })) };
    vi.mocked(api.measure).mockResolvedValue({ ...plan, slides: [plan.slides[0], second] });
    await open({ deck: two });
    await userEvent.click(modeButton());
    act(() => frame("bullets")!.focus());
    fireEvent.keyDown(frame("bullets")!, { key: "Delete" });  // 초점 요청: 결론 상자
    await waitFor(() => expect(document.activeElement).toBe(frame("conclusion")));
    const chapterButton = screen.getByRole("button", { name: /둘째 장/ });
    await userEvent.click(chapterButton);
    await waitFor(() => expect(document.querySelector('[data-frame="c2:conclusion"]')).not.toBeNull());
    expect(document.querySelector('[data-frame="c2:conclusion"]')).toHaveAttribute("aria-pressed", "false");
    expect(document.activeElement).toBe(chapterButton);
  });
});

describe("D3c-3 리뷰 반영 (F10~F13)", () => {
  it("옛 미리보기가 남은 동안 키 조작과 속성 입력을 막고 이유를 알린다 (F10)", async () => {
    // 목록 편집 직후처럼 계획을 만든 덱과 지금 덱의 열쇠 집합이 다르면 낡은 계획이다. 여기서는 새 계획을 늦추고
    // 아이브로우를 더해 열쇠 집합을 바꾼다
    await open();
    await userEvent.click(modeButton());
    let release: (v: RenderPlan) => void = () => {};
    vi.mocked(api.measure).mockImplementation(() => new Promise((r) => { release = r; }));
    await userEvent.type(screen.getByLabelText("아이브로우"), "분");
    act(() => frame("conclusion")!.focus());
    fireEvent.keyDown(frame("conclusion")!, { key: "ArrowRight" });
    fireEvent.keyDown(frame("conclusion")!, { key: "Delete" });
    expect(frame("conclusion")!.style.left).toBe("50px");
    expect(screen.getAllByRole("status").some((s) => /미리보기를 새로 그리는 중입니다. 다 그린 뒤 다시 시도해 주세요/.test(s.textContent ?? ""))).toBe(true);
    expect(screen.getByText("미리보기를 새로 그리는 중입니다. 다 그린 뒤 고칠 수 있습니다.")).toBeInTheDocument();
    expect(screen.queryByRole("spinbutton", { name: "가로 위치" })).toBeNull();
    await act(async () => release(plan));
  });

  it("직접 수정을 열 수 없을 때 모서리 버튼과 모드 밖 키는 막힌 이유를 알린다 (F11)", async () => {
    const hiddenDeck: Deck = { ...deck, slides: [{ ...deck.slides[0], direct_edits: { footnote: { hidden: true } } }] };
    await open({ deck: hiddenDeck, readOnly: true });
    await userEvent.click(screen.getByRole("button", { name: "숨긴 요소 1개" }));
    expect(modeButton()).toHaveAttribute("aria-pressed", "false");
    expect(screen.getAllByRole("status").some((s) => /지금은 직접 수정을 열 수 없습니다/.test(s.textContent ?? ""))).toBe(true);
  });

  it("채움이 없는 요소의 흰 글자도 슬라이드 배경과 비교해 대비를 안내한다 (F12)", async () => {
    await open();
    await userEvent.click(modeButton());
    act(() => frame("title")!.focus());
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "글자 색" }), "background");
    expect(await screen.findByText(/글자와 바탕의 대비가 낮습니다/)).toBeInTheDocument();
  });

  it("위치만 바꾸는 편집에는 글자 크기 한도를 다시 묻지 않는다 (F13)", async () => {
    await open();
    await userEvent.click(modeButton());
    act(() => frame("conclusion")!.focus());
    await waitFor(() => expect(api.fontLimit).toHaveBeenCalledTimes(1), { timeout: 2000 });
    fireEvent.keyDown(frame("conclusion")!, { key: "ArrowRight" });
    fireEvent.keyDown(frame("conclusion")!, { key: "ArrowRight" });
    await new Promise((r) => setTimeout(r, 450));
    expect(api.fontLimit).toHaveBeenCalledTimes(1);
  });
});
