import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api, ApiError, type Deck } from "../api/client";
import { SourcesScreen } from "./SourcesScreen";

vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return { ...mod, api: { ...mod.api,
    listSources: vi.fn(), readSource: vi.fn(), writeSource: vi.fn(), putDeck: vi.fn(),
    uploadSource: vi.fn() } };
});

const project = { name: "p1", title: "제목", updated_at: "", status: "ok" as const };
const deck: Deck = {
  schema_version: 1,
  meta: { title: "제목", report_type: "research", audience: "", preset_overrides: {} },
  structure: { chapters: [] },
  slides: [],
};

it("자료 목록을 보여주고 파일을 열어 저장한다", async () => {
  vi.mocked(api.listSources).mockResolvedValue(["자료.md"]);
  vi.mocked(api.readSource).mockResolvedValue({ text: "원문" });
  vi.mocked(api.writeSource).mockResolvedValue({ ok: true });
  render(<SourcesScreen project={project} deck={deck} onDeckChange={() => {}} />);
  await userEvent.click(await screen.findByText("자료.md"));
  const area = await screen.findByLabelText("자료 내용");
  expect(area).toHaveValue("원문");
  await userEvent.clear(area);
  await userEvent.type(area, "고친 원문");
  await userEvent.click(screen.getByText("자료 저장"));
  expect(api.writeSource).toHaveBeenCalledWith("p1", "자료.md", "고친 원문");
});

it("보고 정보를 저장하면 덱이 갱신된다", async () => {
  vi.mocked(api.listSources).mockResolvedValue([]);
  vi.mocked(api.putDeck).mockResolvedValue({ ok: true });
  const onDeckChange = vi.fn();
  render(<SourcesScreen project={project} deck={deck} onDeckChange={onDeckChange} />);
  const title = screen.getByLabelText("보고서 제목");
  await userEvent.clear(title);
  await userEvent.type(title, "새 제목");
  await userEvent.click(screen.getByText("보고 정보 저장"));
  expect(api.putDeck).toHaveBeenCalledWith(
    "p1", expect.objectContaining({ meta: expect.objectContaining({ title: "새 제목" }) }), false);
  expect(onDeckChange).toHaveBeenCalled();
});

it("새 자료 이름에 확장자가 없으면 .md를 붙인다", async () => {
  vi.mocked(api.listSources).mockResolvedValue([]);
  vi.mocked(api.writeSource).mockResolvedValue({ ok: true });
  vi.mocked(api.readSource).mockResolvedValue({ text: "" });
  render(<SourcesScreen project={project} deck={deck} onDeckChange={() => {}} />);
  await userEvent.type(screen.getByLabelText("새 자료 이름"), "리서치");
  await userEvent.click(screen.getByText("자료 추가"));
  expect(api.writeSource).toHaveBeenCalledWith("p1", "리서치.md", "");
});

describe("자료 파일 업로드", () => {
  const a = new File(["aaa"], "a.md", { type: "text/markdown" });
  const b = new File(["bbb"], "b.txt", { type: "text/plain" });

  afterEach(() => vi.restoreAllMocks());  // window.confirm 스파이가 실패한 테스트에서 다음 테스트로 새지 않게 한다

  function renderScreen() {
    return render(<SourcesScreen project={project} deck={deck} onDeckChange={() => {}} />);
  }

  it("파일 선택으로 2개를 올리면 순서대로 업로드하고 목록을 다시 불러온 뒤 마지막 파일을 연다", async () => {
    vi.mocked(api.listSources).mockResolvedValueOnce([]).mockResolvedValue(["a.md", "b.txt"]);
    vi.mocked(api.uploadSource).mockResolvedValue({ filename: "x", chars: 3 });
    vi.mocked(api.readSource).mockResolvedValue({ text: "bbb" });
    renderScreen();
    await userEvent.upload(screen.getByLabelText("자료 파일 선택"), [a, b]);
    await waitFor(() => expect(api.uploadSource).toHaveBeenCalledTimes(2));
    expect(api.uploadSource).toHaveBeenNthCalledWith(1, "p1", a, false);
    expect(api.uploadSource).toHaveBeenNthCalledWith(2, "p1", b, false);
    expect(await screen.findByText("2개 자료를 추가했습니다.")).toBeInTheDocument();
    expect(api.listSources).toHaveBeenCalledTimes(2);
    expect(await screen.findByRole("heading", { level: 3, name: "b.txt" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();  // 성공 안내는 오류 영역이 아니다
  });

  it("끌어다 놓기로도 업로드한다", async () => {
    vi.mocked(api.listSources).mockResolvedValue([]);
    vi.mocked(api.uploadSource).mockResolvedValue({ filename: "c.csv", chars: 1 });
    renderScreen();
    const zone = screen.getByText(/끌어다 놓거나/).closest(".drop-zone")!;
    const c = new File(["x"], "c.csv", { type: "text/csv" });
    fireEvent.drop(zone, { dataTransfer: { files: [c], types: ["Files"] } });
    await waitFor(() => expect(api.uploadSource).toHaveBeenCalledWith("p1", c, false));
  });

  it("같은 이름이 있으면 확인을 받아 덮어쓴다", async () => {
    vi.mocked(api.listSources).mockResolvedValue(["a.md"]);
    vi.mocked(api.readSource).mockResolvedValue({ text: "aaa" });
    vi.mocked(api.uploadSource)
      .mockRejectedValueOnce(new ApiError(409, "같은 이름의 자료가 이미 있습니다: a.md"))
      .mockResolvedValueOnce({ filename: "a.md", chars: 3 });
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    renderScreen();
    await userEvent.upload(screen.getByLabelText("자료 파일 선택"), [a]);
    await waitFor(() => expect(api.uploadSource).toHaveBeenCalledTimes(2));
    expect(api.uploadSource).toHaveBeenLastCalledWith("p1", a, true);
    expect(confirmSpy).toHaveBeenCalledTimes(1);
    expect(confirmSpy.mock.calls[0][0]).toContain("a.md");
    expect(await screen.findByText("1개 자료를 추가했습니다.")).toBeInTheDocument();
    confirmSpy.mockRestore();
  });

  it("덮어쓰기를 거절하면 건너뛴다", async () => {
    vi.mocked(api.listSources).mockResolvedValue(["a.md"]);
    vi.mocked(api.uploadSource)
      .mockRejectedValueOnce(new ApiError(409, "같은 이름의 자료가 이미 있습니다: a.md"));
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
    renderScreen();
    await userEvent.upload(screen.getByLabelText("자료 파일 선택"), [a]);
    expect(await screen.findByText("추가한 자료가 없습니다. 건너뜀 1개.")).toBeInTheDocument();
    expect(api.uploadSource).toHaveBeenCalledTimes(1);
    expect(api.readSource).not.toHaveBeenCalled();  // 추가한 파일이 없으면 열지 않는다
    expect(screen.queryByRole("alert")).toBeNull();
    confirmSpy.mockRestore();
  });

  it("일부만 실패하면 성공 수와 실패한 파일의 사유를 함께 보여준다", async () => {
    vi.mocked(api.listSources).mockResolvedValue(["a.md"]);
    vi.mocked(api.readSource).mockResolvedValue({ text: "aaa" });
    const pdf = new File(["%PDF"], "보고서.pdf", { type: "application/pdf" });
    vi.mocked(api.uploadSource)
      .mockResolvedValueOnce({ filename: "a.md", chars: 3 })
      .mockRejectedValueOnce(new ApiError(422, "지원하지 않는 형식입니다. PDF와 Word는 아직 지원하지 않습니다."));
    renderScreen();
    // 파일 선택 입력은 accept 필터가 PDF를 거르지만, 끌어다 놓기는 거르지 않아 서버 422가 실제로 발생하는 경로다
    const zone = screen.getByText(/끌어다 놓거나/).closest(".drop-zone")!;
    fireEvent.drop(zone, { dataTransfer: { files: [a, pdf], types: ["Files"] } });
    expect(await screen.findByText("1개 자료를 추가했습니다.")).toBeInTheDocument();
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("보고서.pdf");
    expect(alert).toHaveTextContent("지원하지 않는 형식입니다");
  });
});
