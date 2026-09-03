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
  meta: { title: "제목", report_type: "research", audience: "", presenter: "", preset_overrides: {} },
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

it("보고 정보의 입력 항목이 각각 한 줄을 차지한다", async () => {
  vi.mocked(api.listSources).mockResolvedValue([]);
  render(<SourcesScreen project={project} deck={deck} onDeckChange={() => {}} />);
  const fields = ["보고서 제목", "보고 유형", "보고자", "피보고자"].map((l) => screen.getByLabelText(l).closest(".field"));
  fields.forEach((f) => expect(f).not.toBeNull());
  expect(new Set(fields).size).toBe(fields.length);
  expect(screen.getByLabelText("새 자료 이름").closest(".field")).not.toBeNull();
});

it("자료 내용 편집 영역도 세로 배치다", async () => {
  vi.mocked(api.listSources).mockResolvedValue(["자료.md"]);
  vi.mocked(api.readSource).mockResolvedValue({ text: "원문" });
  render(<SourcesScreen project={project} deck={deck} onDeckChange={() => {}} />);
  await userEvent.click(await screen.findByText("자료.md"));
  const area = await screen.findByLabelText("자료 내용");
  expect(area.closest(".field")).not.toBeNull();
  expect(screen.getByText("자료 저장").closest(".actions")).not.toBeNull();
});

it("보고자를 입력해 저장하면 meta.presenter로 반영되고 피보고자 안내가 보인다", async () => {
  vi.mocked(api.listSources).mockResolvedValue([]);
  vi.mocked(api.putDeck).mockResolvedValue({ ok: true });
  const onDeckChange = vi.fn();
  render(<SourcesScreen project={project} deck={deck} onDeckChange={onDeckChange} />);
  await userEvent.type(screen.getByLabelText("보고자"), "사업개발팀");
  await userEvent.click(screen.getByText("보고 정보 저장"));
  expect(onDeckChange).toHaveBeenCalledWith(expect.objectContaining({
    meta: expect.objectContaining({ presenter: "사업개발팀" }),
  }));
  expect(screen.getByText(/문서에 적히지 않고/)).toBeInTheDocument();
});

describe("보고 정보 플러시와 충돌 (A5)", () => {
  it("마운트 시 저장됨(false)을 알리고, 입력을 바꾸면 true를, 저장하면 다시 false를 알린다", async () => {
    vi.mocked(api.listSources).mockResolvedValue([]);
    vi.mocked(api.putDeck).mockResolvedValue({ ok: true });
    const onDirtyChange = vi.fn();
    render(<SourcesScreen project={project} deck={deck} onDeckChange={() => {}}
      onDirtyChange={onDirtyChange} />);
    await waitFor(() => expect(onDirtyChange).toHaveBeenCalledWith(false));
    await userEvent.type(screen.getByLabelText("보고서 제목"), "고침");
    await waitFor(() => expect(onDirtyChange).toHaveBeenLastCalledWith(true));
    await userEvent.click(screen.getByText("보고 정보 저장"));
    await waitFor(() => expect(onDirtyChange).toHaveBeenLastCalledWith(false));
  });

  it("부모에 플러시 함수를 등록하고, 언마운트 시 등록을 해제한다", async () => {
    vi.mocked(api.listSources).mockResolvedValue([]);
    const onScreenReady = vi.fn();
    const { unmount } = render(<SourcesScreen project={project} deck={deck} onDeckChange={() => {}}
      onScreenReady={onScreenReady} />);
    await waitFor(() => expect(onScreenReady).toHaveBeenCalledWith(expect.any(Function)));
    unmount();
    expect(onScreenReady).toHaveBeenLastCalledWith(null);
  });

  it("저장 버튼 없이 부모가 플러시를 부르면 최신 입력을 저장한다", async () => {
    vi.mocked(api.listSources).mockResolvedValue([]);
    vi.mocked(api.putDeck).mockResolvedValue({ ok: true });
    let flush: (() => Promise<boolean>) | null = null;
    render(<SourcesScreen project={project} deck={deck} onDeckChange={() => {}}
      onScreenReady={(f) => { flush = f; }} />);
    await userEvent.type(screen.getByLabelText("보고서 제목"), "고침");
    expect(api.putDeck).not.toHaveBeenCalled();
    const ok = await flush!();
    expect(ok).toBe(true);
    expect(api.putDeck).toHaveBeenCalledWith(
      "p1", expect.objectContaining({ meta: expect.objectContaining({ title: "제목고침" }) }), false);
  });

  it("입력을 바꾸지 않았으면 플러시를 불러도 PUT이 없다", async () => {
    vi.mocked(api.listSources).mockResolvedValue([]);
    let flush: (() => Promise<boolean>) | null = null;
    render(<SourcesScreen project={project} deck={deck} onDeckChange={() => {}}
      onScreenReady={(f) => { flush = f; }} />);
    await waitFor(() => expect(flush).not.toBeNull());
    expect(await flush!()).toBe(true);
    expect(api.putDeck).not.toHaveBeenCalled();
  });

  it("저장 중에는 입력과 저장 버튼을 잠근다", async () => {
    vi.mocked(api.listSources).mockResolvedValue([]);
    const { promise, resolve } = (() => {
      let r!: (v: { ok: boolean }) => void;
      const p = new Promise<{ ok: boolean }>((res) => { r = res; });
      return { promise: p, resolve: r };
    })();
    vi.mocked(api.putDeck).mockReturnValue(promise);
    render(<SourcesScreen project={project} deck={deck} onDeckChange={() => {}} />);
    await userEvent.type(screen.getByLabelText("보고서 제목"), "고침");
    await userEvent.click(screen.getByText("보고 정보 저장"));
    await waitFor(() => expect(screen.getByLabelText("보고서 제목")).toBeDisabled());
    expect(screen.getByText("보고 정보 저장")).toBeDisabled();
    resolve({ ok: true });
    await waitFor(() => expect(screen.getByLabelText("보고서 제목")).not.toBeDisabled());
  });

  it("저장 버튼 클릭 직후 부모가 플러시를 불러도 PUT은 1회다 (직렬화)", async () => {
    vi.mocked(api.listSources).mockResolvedValue([]);
    vi.mocked(api.putDeck).mockResolvedValue({ ok: true });
    let flush: (() => Promise<boolean>) | null = null;
    render(<SourcesScreen project={project} deck={deck} onDeckChange={() => {}}
      onScreenReady={(f) => { flush = f; }} />);
    await userEvent.type(screen.getByLabelText("보고서 제목"), "고침");
    await userEvent.click(screen.getByText("보고 정보 저장"));
    const flushed = await flush!();  // 버튼 저장이 아직 착지하기 전에 곧장 플러시를 부른다
    expect(flushed).toBe(true);
    await waitFor(() => expect(api.putDeck).toHaveBeenCalledTimes(1));
  });

  it("저장이 412면 onConflict를 부른다", async () => {
    vi.mocked(api.listSources).mockResolvedValue([]);
    vi.mocked(api.putDeck).mockRejectedValue(
      new ApiError(412, "다른 창이나 프로그램에서 이 프로젝트가 먼저 저장되었습니다."));
    const onConflict = vi.fn();
    render(<SourcesScreen project={project} deck={deck} onDeckChange={() => {}}
      onConflict={onConflict} />);
    await userEvent.type(screen.getByLabelText("보고서 제목"), "고침");
    await userEvent.click(screen.getByText("보고 정보 저장"));
    await waitFor(() => expect(onConflict).toHaveBeenCalled());
  });
});
