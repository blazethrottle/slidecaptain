import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api, ApiError, type Deck, type UploadResult } from "../api/client";
import { SourcesScreen } from "./SourcesScreen";
import { deferred } from "../test/fixtures";

const XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";

// 시험이 중간에 실패해 쓰지 않은 한 번짜리 모의 응답이 다음 시험으로 넘어가지 않게 매번 비운다 (D3a-4 리뷰 R20).
// 시험마다 필요한 응답을 스스로 정하므로 구현까지 비워도 된다
beforeEach(() => {
  for (const fn of [api.listSources, api.readSource, api.writeSource, api.putDeck, api.uploadSource]) vi.mocked(fn).mockReset();
});

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
  render(<SourcesScreen project={project} />);
  await userEvent.click(await screen.findByText("자료.md"));
  const area = await screen.findByLabelText("자료 내용");
  expect(area).toHaveValue("원문");
  await userEvent.clear(area);
  await userEvent.type(area, "고친 원문");
  await userEvent.click(screen.getByText("자료 저장"));
  expect(api.writeSource).toHaveBeenCalledWith("p1", "자료.md", "고친 원문");
});

it("새 자료 이름에 확장자가 없으면 .md를 붙인다", async () => {
  vi.mocked(api.listSources).mockResolvedValue([]);
  vi.mocked(api.writeSource).mockResolvedValue({ ok: true });
  vi.mocked(api.readSource).mockResolvedValue({ text: "" });
  render(<SourcesScreen project={project} />);
  await userEvent.type(screen.getByLabelText("새 자료 이름"), "리서치");
  await userEvent.click(screen.getByText("자료 추가"));
  expect(api.writeSource).toHaveBeenCalledWith("p1", "리서치.md", "");
});

it("다른 자료를 기다리는 동안 편집한 본문을 늦은 응답이 덮지 않는다", async () => {
  const pending = deferred<{ text: string }>();
  vi.mocked(api.listSources).mockResolvedValue(["first.md", "second.md"]);
  vi.mocked(api.readSource).mockResolvedValueOnce({ text: "첫 원문" }).mockReturnValue(pending.promise);
  render(<SourcesScreen project={project} />);
  await userEvent.click(await screen.findByRole("button", { name: "first.md" }));
  const box = await screen.findByLabelText("자료 내용");
  await userEvent.click(screen.getByRole("button", { name: "second.md" }));
  await userEvent.type(box, " 수정 중");
  await act(async () => pending.resolve({ text: "둘째 원문" }));
  expect(screen.getByLabelText("자료 내용")).toHaveValue("첫 원문 수정 중");
  expect(screen.getByRole("heading", { name: "first.md" })).toBeInTheDocument();
});

it("자료 선택이 바뀌면 먼저 요청한 파일의 늦은 응답을 버린다", async () => {
  const pending = deferred<{ text: string }>();
  vi.mocked(api.listSources).mockResolvedValue(["first.md", "second.md"]);
  vi.mocked(api.readSource).mockReturnValueOnce(pending.promise).mockResolvedValue({ text: "둘째 원문" });
  render(<SourcesScreen project={project} />);
  await userEvent.click(await screen.findByRole("button", { name: "first.md" }));
  await userEvent.click(screen.getByRole("button", { name: "second.md" }));
  expect(await screen.findByLabelText("자료 내용")).toHaveValue("둘째 원문");
  await act(async () => pending.resolve({ text: "첫 원문" }));
  expect(screen.getByLabelText("자료 내용")).toHaveValue("둘째 원문");
});

it("다른 자료를 저장한 늦은 응답이 현재 본문의 저장 기준을 바꾸지 않는다", async () => {
  const pending = deferred<{ ok: boolean }>();
  const dirty = vi.fn();
  vi.mocked(api.listSources).mockResolvedValue(["first.md", "second.md"]);
  vi.mocked(api.readSource).mockResolvedValueOnce({ text: "첫 원문" }).mockResolvedValue({ text: "둘째 원문" });
  vi.mocked(api.writeSource).mockReturnValue(pending.promise);
  render(<SourcesScreen project={project} onDirtyChange={dirty} />);
  await userEvent.click(await screen.findByRole("button", { name: "first.md" }));
  await screen.findByLabelText("자료 내용");
  await userEvent.click(screen.getByRole("button", { name: "자료 저장" }));
  expect(screen.getByRole("button", { name: "자료 저장" })).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: "second.md" }));
  await waitFor(() => expect(screen.getByLabelText("자료 내용")).toHaveValue("둘째 원문"));
  await act(async () => pending.resolve({ ok: true }));
  fireEvent.change(screen.getByLabelText("자료 내용"), { target: { value: "첫 원문" } });
  expect(dirty).toHaveBeenLastCalledWith(true);
});

describe("자료 파일 업로드", () => {
  const a = new File(["aaa"], "a.md", { type: "text/markdown" });
  const b = new File(["bbb"], "b.txt", { type: "text/plain" });

  afterEach(() => vi.restoreAllMocks());  // window.confirm 스파이가 실패한 테스트에서 다음 테스트로 새지 않게 한다

  function renderScreen() {
    return render(<SourcesScreen project={project} />);
  }

  it("파일 선택으로 2개를 올리면 순서대로 업로드하고 목록을 다시 불러온 뒤 마지막 파일을 연다", async () => {
    vi.mocked(api.listSources).mockResolvedValueOnce([]).mockResolvedValue(["a.md", "b.txt"]);
    vi.mocked(api.uploadSource).mockResolvedValue({
      filename: "x", chars: 3, sheets: null, cells: null, truncated: false, notes: [],
    });
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
    vi.mocked(api.uploadSource).mockResolvedValue({
      filename: "c.csv", chars: 1, sheets: null, cells: null, truncated: false, notes: [],
    });
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
      .mockResolvedValueOnce({
        filename: "a.md", chars: 3, sheets: null, cells: null, truncated: false, notes: [],
      });
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
      .mockResolvedValueOnce({
        filename: "a.md", chars: 3, sheets: null, cells: null, truncated: false, notes: [],
      })
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

  // XLSX 업로드 결과 표시 (계획서 B4)
  it("XLSX 파일을 올리면 시트와 셀 수와 잘린 자리를 알려준다", async () => {
    vi.mocked(api.listSources).mockResolvedValueOnce([]).mockResolvedValue(["매출.xlsx.md"]);
    vi.mocked(api.uploadSource).mockResolvedValue({
      filename: "매출.xlsx", chars: 500, sheets: 3, cells: 1204, truncated: true,
      notes: ["(한계: 60,000자 초과분 생략. 시트 손익 행 412부터)", "계산값 없음: 2곳"],
    });
    vi.mocked(api.readSource).mockResolvedValue({ text: "# XLSX 추출: 매출.xlsx" });
    const xlsx = new File(["PK"], "매출.xlsx", { type: XLSX_MIME });
    renderScreen();
    await userEvent.upload(screen.getByLabelText("자료 파일 선택"), xlsx);
    expect(await screen.findByText("1개 자료를 추가했습니다. 매출.xlsx: 시트 3개, 셀 1,204개. 계산값 없음: 2곳"))
      .toBeInTheDocument();
    expect(await screen.findByText("일부가 잘렸습니다: 매출.xlsx (60,000자 초과분 생략. 시트 손익 행 412부터)"))
      .toBeInTheDocument();
  });

  // 잘림 상세("행 N에서 D, E열 생략")가 "(한계:" 접두사 없이 따로 남으면 잘림 알림이 아니라 일반
  // 안내로 샜다(B 묶음 최종 리뷰 minor F-4). 백엔드가 한 note로 합친 뒤에는 잘림 알림에만 나와야 한다
  it("행 절단 상세가 백엔드 note에 합쳐져 있으면 잘림 알림에만 나오고 일반 안내에는 새지 않는다", async () => {
    vi.mocked(api.listSources).mockResolvedValueOnce([]).mockResolvedValue(["매출.xlsx.md"]);
    vi.mocked(api.uploadSource).mockResolvedValue({
      filename: "매출.xlsx", chars: 500, sheets: 3, cells: 1204, truncated: true,
      notes: ["(한계: 60,000자 초과분 생략. 시트 손익 행 412부터. 행 412에서 D, E열 생략)"],
    });
    vi.mocked(api.readSource).mockResolvedValue({ text: "# XLSX 추출: 매출.xlsx" });
    const xlsx = new File(["PK"], "매출.xlsx", { type: XLSX_MIME });
    renderScreen();
    await userEvent.upload(screen.getByLabelText("자료 파일 선택"), xlsx);
    expect(await screen.findByText(
      "일부가 잘렸습니다: 매출.xlsx (60,000자 초과분 생략. 시트 손익 행 412부터. 행 412에서 D, E열 생략)",
    )).toBeInTheDocument();
    // 일반 안내(시트/셀 수 요약)에는 열 상세가 다시 나타나지 않는다: 같은 정보가 두 곳에서 서로 다른
    // 형태로 보이면 사용자가 둘을 별개 사건으로 오해한다
    expect(await screen.findByText("1개 자료를 추가했습니다. 매출.xlsx: 시트 3개, 셀 1,204개"))
      .toBeInTheDocument();
  });

  it("두 파일 중 하나만 잘린 응답은 그 파일만 잘림 알림에 나온다", async () => {
    const x1 = new File(["PK"], "매출.xlsx", { type: XLSX_MIME });
    const x2 = new File(["PK"], "손익.xlsx", { type: XLSX_MIME });
    vi.mocked(api.listSources).mockResolvedValueOnce([]).mockResolvedValue(["매출.xlsx.md", "손익.xlsx.md"]);
    vi.mocked(api.uploadSource)
      .mockResolvedValueOnce({ filename: "매출.xlsx", chars: 100, sheets: 1, cells: 10, truncated: false, notes: [] })
      .mockResolvedValueOnce({
        filename: "손익.xlsx", chars: 900, sheets: 2, cells: 500, truncated: true,
        notes: ["(한계: 시트 31개 이후 생략)"],
      });
    vi.mocked(api.readSource).mockResolvedValue({ text: "추출본" });
    renderScreen();
    await userEvent.upload(screen.getByLabelText("자료 파일 선택"), [x1, x2]);
    const notice = await screen.findByText(/일부가 잘렸습니다/);
    expect(notice).toHaveTextContent("손익.xlsx");
    expect(notice).not.toHaveTextContent("매출.xlsx");
  });

  // 여러 XLSX가 각각 "계산값 없음" 같은 잘림 아닌 note를 가지면 파일명 없이 이어붙어 어느 파일 것인지
  // 구분되지 않았다(B4 리뷰 F2). 두 파일 모두 note가 있을 때만 파일명을 접두해 구분한다
  it("두 XLSX가 각각 계산값 없음 note를 가지면 안내에 파일명을 구분해 붙인다", async () => {
    const x1 = new File(["PK"], "매출.xlsx", { type: XLSX_MIME });
    const x2 = new File(["PK"], "손익.xlsx", { type: XLSX_MIME });
    vi.mocked(api.listSources).mockResolvedValueOnce([]).mockResolvedValue(["매출.xlsx.md", "손익.xlsx.md"]);
    vi.mocked(api.uploadSource)
      .mockResolvedValueOnce({
        filename: "매출.xlsx", chars: 100, sheets: 1, cells: 10, truncated: false, notes: ["계산값 없음: 2곳"],
      })
      .mockResolvedValueOnce({
        filename: "손익.xlsx", chars: 200, sheets: 1, cells: 20, truncated: false, notes: ["계산값 없음: 1곳"],
      });
    vi.mocked(api.readSource).mockResolvedValue({ text: "추출본" });
    renderScreen();
    await userEvent.upload(screen.getByLabelText("자료 파일 선택"), [x1, x2]);
    const info = await screen.findByText(/계산값 없음/);
    expect(info).toHaveTextContent("매출.xlsx: 계산값 없음: 2곳");
    expect(info).toHaveTextContent("손익.xlsx: 계산값 없음: 1곳");
  });

  it("한 파일만 계산값 없음 note를 가지면 파일명 없이 그대로 보인다(단일 출처라 모호하지 않다)", async () => {
    const x1 = new File(["PK"], "매출.xlsx", { type: XLSX_MIME });
    vi.mocked(api.listSources).mockResolvedValueOnce([]).mockResolvedValue(["매출.xlsx.md"]);
    vi.mocked(api.uploadSource).mockResolvedValueOnce({
      filename: "매출.xlsx", chars: 100, sheets: 1, cells: 10, truncated: false, notes: ["계산값 없음: 2곳"],
    });
    vi.mocked(api.readSource).mockResolvedValue({ text: "추출본" });
    renderScreen();
    await userEvent.upload(screen.getByLabelText("자료 파일 선택"), [x1]);
    expect(await screen.findByText("1개 자료를 추가했습니다. 매출.xlsx: 시트 1개, 셀 10개. 계산값 없음: 2곳"))
      .toBeInTheDocument();
  });
});

// 업로드 중 잠금 신호 (계획서 B4 가정 7): onBusyChange는 부모의 탭 잠금, onDirtyChange는 부모의
// beforeunload 경고에 각각 쓰인다. 둘 다 진행 중에는 true, 착지하면 false로 돌아가되 서로를 덮지 않는다
describe("업로드 중 잠금과 dirty (B4)", () => {
  const project = { name: "p1", title: "제목", updated_at: "", status: "ok" as const };
  const deck: Deck = {
    schema_version: 1,
    meta: { title: "제목", report_type: "research", audience: "", presenter: "", preset_overrides: {} },
    structure: { chapters: [] },
    slides: [],
  };

  function pendingUpload() {
    let resolve!: (v: UploadResult) => void;
    const promise = new Promise<UploadResult>((res) => { resolve = res; });
    return { promise, resolve };
  }

  it("업로드 진행 중에는 onBusyChange(true)와 onDirtyChange(true)를, 착지하면 각각 false를 부른다", async () => {
    vi.mocked(api.listSources).mockResolvedValue([]);
    const { promise, resolve } = pendingUpload();
    vi.mocked(api.uploadSource).mockReturnValue(promise);
    const onBusyChange = vi.fn();
    const onDirtyChange = vi.fn();
    const xlsx = new File(["PK"], "매출.xlsx", { type: XLSX_MIME });
    render(<SourcesScreen project={project}
      onBusyChange={onBusyChange} onDirtyChange={onDirtyChange} />);
    await waitFor(() => expect(onDirtyChange).toHaveBeenCalledWith(false));
    await userEvent.upload(screen.getByLabelText("자료 파일 선택"), xlsx);
    await waitFor(() => expect(onBusyChange).toHaveBeenLastCalledWith(true));
    expect(onDirtyChange).toHaveBeenLastCalledWith(true);
    resolve({ filename: "매출.xlsx", chars: 10, sheets: 1, cells: 1, truncated: false, notes: [] });
    await waitFor(() => expect(onBusyChange).toHaveBeenLastCalledWith(false));
    await waitFor(() => expect(onDirtyChange).toHaveBeenLastCalledWith(false));
  });

  it("업로드가 끝나도 자료 본문이 미저장이면 onDirtyChange는 계속 true다(두 신호가 서로 덮지 않는다)", async () => {
    // 다시 씀(D3a-2): 보고 정보가 보고 목적 단계로 옮겨 가서, 두 신호는 업로드와 자료 본문 미저장이다
    vi.mocked(api.listSources).mockResolvedValue(["자료.md"]);
    vi.mocked(api.readSource).mockResolvedValue({ text: "원문" });
    vi.mocked(api.uploadSource).mockResolvedValue({
      filename: "매출.xlsx", chars: 10, sheets: 1, cells: 1, truncated: false, notes: [],
    });
    const onDirtyChange = vi.fn();
    const xlsx = new File(["PK"], "매출.xlsx", { type: XLSX_MIME });
    render(<SourcesScreen project={project} onDirtyChange={onDirtyChange} />);
    await waitFor(() => expect(onDirtyChange).toHaveBeenCalledWith(false));
    await userEvent.click(await screen.findByText("자료.md"));
    await userEvent.type(await screen.findByLabelText("자료 내용"), " 고침");
    await waitFor(() => expect(onDirtyChange).toHaveBeenLastCalledWith(true));
    fireEvent.drop(document.querySelector(".drop-zone")!, { dataTransfer: { files: [xlsx] } });
    await waitFor(() => expect(screen.getByText(/파일을 가져오기 전에/)).toBeInTheDocument());
    expect(onDirtyChange).toHaveBeenLastCalledWith(true);
  });


  it("언마운트된 뒤 업로드가 응답해도 오류 없이 무시하고 onBusyChange(false)는 부른다", async () => {
    vi.mocked(api.listSources).mockResolvedValue([]);
    const { promise, resolve } = pendingUpload();
    vi.mocked(api.uploadSource).mockReturnValue(promise);
    const onBusyChange = vi.fn();
    const xlsx = new File(["PK"], "매출.xlsx", { type: XLSX_MIME });
    const { unmount } = render(<SourcesScreen project={project}
      onBusyChange={onBusyChange} />);
    await userEvent.upload(screen.getByLabelText("자료 파일 선택"), xlsx);
    await waitFor(() => expect(onBusyChange).toHaveBeenLastCalledWith(true));
    unmount();
    resolve({ filename: "매출.xlsx", chars: 10, sheets: 1, cells: 1, truncated: false, notes: [] });
    await waitFor(() => expect(onBusyChange).toHaveBeenLastCalledWith(false));
  });

  // 업로드가 끝나기 전에 같은 입력으로 겹쳐 시작하면, 먼저 응답한 쪽의 finally가 아직 진행 중인 첫
  // 업로드의 잠금을 풀어 버리는 경합이 있었다(B4 리뷰 F1: FC-17 업로드 중 단계 이동 방지를 무력화한다).
  // 파일 입력은 uploading 동안 잠기고, importFiles 자체도 재진입을 막는다
  it("업로드 진행 중에는 파일 입력이 잠기고, 겹쳐 선택해도 두 번째 업로드는 시작되지 않는다", async () => {
    vi.mocked(api.listSources).mockResolvedValue([]);
    const { promise, resolve } = pendingUpload();
    vi.mocked(api.uploadSource).mockReturnValue(promise);
    const onBusyChange = vi.fn();
    const a = new File(["aaa"], "a.md", { type: "text/markdown" });
    const b = new File(["bbb"], "b.md", { type: "text/markdown" });
    render(<SourcesScreen project={project} onBusyChange={onBusyChange} />);
    await userEvent.upload(screen.getByLabelText("자료 파일 선택"), a);
    await waitFor(() => expect(onBusyChange).toHaveBeenLastCalledWith(true));
    expect(screen.getByLabelText("자료 파일 선택")).toBeDisabled();
    // 실제로는 disabled가 파일 선택 창을 막지만, 그것과 무관하게 재진입 자체를 막는지 직접 확인한다
    fireEvent.change(screen.getByLabelText("자료 파일 선택"), { target: { files: [b] } });
    await Promise.resolve();
    expect(api.uploadSource).toHaveBeenCalledTimes(1);  // b는 시작되지 않았다
    resolve({ filename: "a.md", chars: 3, sheets: null, cells: null, truncated: false, notes: [] });
    await waitFor(() => expect(onBusyChange).toHaveBeenLastCalledWith(false));
    expect(api.uploadSource).toHaveBeenCalledTimes(1);  // a가 끝난 뒤에도 겹친 시도(b)는 되살아나지 않는다
    expect(screen.getByLabelText("자료 파일 선택")).not.toBeDisabled();
  });

  it("업로드 진행 중 겹쳐서 끌어다 놓아도 두 번째 업로드는 시작되지 않는다", async () => {
    vi.mocked(api.listSources).mockResolvedValue([]);
    const { promise, resolve } = pendingUpload();
    vi.mocked(api.uploadSource).mockReturnValue(promise);
    const a = new File(["aaa"], "a.md", { type: "text/markdown" });
    const b = new File(["bbb"], "b.md", { type: "text/markdown" });
    render(<SourcesScreen project={project} />);
    const zone = screen.getByText(/끌어다 놓거나/).closest(".drop-zone")!;
    fireEvent.drop(zone, { dataTransfer: { files: [a], types: ["Files"] } });
    await waitFor(() => expect(api.uploadSource).toHaveBeenCalledTimes(1));
    fireEvent.drop(zone, { dataTransfer: { files: [b], types: ["Files"] } });
    await Promise.resolve();
    expect(api.uploadSource).toHaveBeenCalledTimes(1);  // 겹친 드롭(b)은 무시된다
    resolve({ filename: "a.md", chars: 3, sheets: null, cells: null, truncated: false, notes: [] });
    await waitFor(() => expect(api.uploadSource).toHaveBeenCalledTimes(1));
  });
});

it("자료 내용 편집 영역도 세로 배치다", async () => {
  vi.mocked(api.listSources).mockResolvedValue(["자료.md"]);
  vi.mocked(api.readSource).mockResolvedValue({ text: "원문" });
  render(<SourcesScreen project={project} />);
  await userEvent.click(await screen.findByText("자료.md"));
  const area = await screen.findByLabelText("자료 내용");
  expect(area.closest(".field")).not.toBeNull();
  expect(screen.getByText("자료 저장").closest(".actions")).not.toBeNull();
});

it("자료를 저장한 뒤 다른 자료를 열면 지난 성공 안내를 지운다 (D2a-4 리뷰 R1)", async () => {
  // 다시 씀(D3a-2): 보고 정보 저장 대신 자료 저장의 성공 안내로 같은 규칙을 지킨다
  vi.mocked(api.listSources).mockResolvedValue(["자료.md", "둘째.md"]);
  vi.mocked(api.readSource).mockResolvedValue({ text: "원문" });
  vi.mocked(api.writeSource).mockResolvedValue({ ok: true });
  render(<SourcesScreen project={project} />);
  await userEvent.click(await screen.findByText("자료.md"));
  await userEvent.type(await screen.findByLabelText("자료 내용"), " 수정");
  await userEvent.click(screen.getByText("자료 저장"));
  const notice = await screen.findByText("자료를 저장했습니다.");
  expect(notice).toHaveAttribute("role", "status");
  await userEvent.click(screen.getByText("둘째.md"));
  await waitFor(() => expect(screen.queryByText("자료를 저장했습니다.")).toBeNull());
});

it("편집 중에 보존한 자료 안내는 오류가 아니라 주의 안내로 보인다 (D2a 이월 6, D3a-1)", async () => {
  // 지금 코드의 틀린 동작: 오류 알림(role=alert, 위험색)으로 그린다
  const pending = deferred<{ text: string }>();
  vi.mocked(api.listSources).mockResolvedValue(["first.md", "second.md"]);
  vi.mocked(api.readSource).mockResolvedValueOnce({ text: "첫 원문" }).mockReturnValue(pending.promise);
  render(<SourcesScreen project={project} />);
  await userEvent.click(await screen.findByRole("button", { name: "first.md" }));
  const box = await screen.findByLabelText("자료 내용");
  await userEvent.click(screen.getByRole("button", { name: "second.md" }));
  await userEvent.type(box, " 수정 중");
  await act(async () => pending.resolve({ text: "둘째 원문" }));
  const kept = screen.getByText(/수정 중인 자료 내용을 보존했습니다/);
  expect(kept).toHaveAttribute("role", "status");
  expect(kept).toHaveClass("notice-warning");
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

it("저장 먼저 안내는 주의로, 요청 실패는 오류로 보인다. 문구가 아니라 안내를 내는 자리가 정한다 (D3a-4, R14)", async () => {
  // 지금 코드의 틀린 동작: 보존 안내 하나만 문구로 골라 주의로 그리고, 저장 먼저 안내 네 곳은 오류 알림이다
  vi.mocked(api.listSources).mockResolvedValue(["first.md", "second.md"]);
  vi.mocked(api.readSource).mockResolvedValueOnce({ text: "첫 원문" })
    .mockRejectedValueOnce(new ApiError(404, "자료를 찾지 못했습니다."));
  render(<SourcesScreen project={project} />);
  await userEvent.click(await screen.findByRole("button", { name: "first.md" }));
  await userEvent.type(await screen.findByLabelText("자료 내용"), " 수정");
  await userEvent.click(screen.getByRole("button", { name: "second.md" }));
  const warning = screen.getByText(/다른 자료를 열기 전에/);
  expect(warning).toHaveAttribute("role", "status");
  expect(warning).toHaveClass("notice-warning");
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  await userEvent.clear(screen.getByLabelText("자료 내용"));
  await userEvent.type(screen.getByLabelText("자료 내용"), "첫 원문");
  await userEvent.click(screen.getByRole("button", { name: "second.md" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("자료를 찾지 못했습니다.");
});

it("자료 단계의 주 행동은 파일 선택 하나다 (D3a-1, 계획 4.6)", async () => {
  // 다시 씀(D3a-2): 보고 정보가 보고 목적 단계로 옮겨 가서 화면 하나에 주 행동이 하나다
  vi.mocked(api.listSources).mockResolvedValue(["first.md"]);
  vi.mocked(api.readSource).mockResolvedValue({ text: "원문" });
  render(<SourcesScreen project={project} />);
  await userEvent.click(await screen.findByRole("button", { name: "first.md" }));  // 자료를 연 상태에서도 그대로다
  await screen.findByLabelText("자료 내용");
  const primaries = document.querySelectorAll(".btn-primary");
  expect(primaries).toHaveLength(1);
  expect(primaries[0]).toContainElement(screen.getByLabelText("자료 파일 선택"));  // 파일 올리기가 주 행동이다
  // 보이는 글자는 낭독하지 않는다. 입력의 이름("자료 파일 선택")과 두 번 읽히지 않게 (D3a-1 리뷰 R11)
  expect(within(primaries[0] as HTMLElement).getByText("파일 선택")).toHaveAttribute("aria-hidden", "true");
});
