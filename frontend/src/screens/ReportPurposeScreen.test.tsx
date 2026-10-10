// 보고 목적 단계 (D3a-2). 옛 SourcesScreen.test.tsx의 보고 정보 시험을 옮겼다(옮김). 저장 계약은 같다:
// 저장 순간의 deck prop에 보고 정보만 바꿔 덱 전체를 PUT한다
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api, ApiError, type Deck } from "../api/client";
import { ReportPurposeScreen } from "./ReportPurposeScreen";
import type { SaveStatus } from "../ui/StatusIndicator";
import { deferred } from "../test/fixtures";

vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return { ...mod, api: { ...mod.api, putDeck: vi.fn() } };
});

const project = { name: "p1", title: "제목", updated_at: "", status: "ok" as const };
const deck: Deck = {
  schema_version: 1,
  meta: { title: "제목", report_type: "research", audience: "", presenter: "", preset_overrides: {} },
  structure: { chapters: [] },
  slides: [],
};

it.each([
  ["weekly", "주간 업무 보고"], ["business", "일반 업무 보고"], ["monthly", "월간 보고"],
  ["data", "데이터 설명 보고"], ["research", "리서치 결과 보고"],
  ["project", "프로젝트 보고"], ["results", "결과 보고"],
  ["approval", "승인요청"], ["strategy", "전략기획"],
])("보고 유형 %s를 선택해 저장하고 다시 연다", async (value, label) => {
  vi.mocked(api.putDeck).mockResolvedValue({ ok: true });
  const onDeckChange = vi.fn();
  const initial: Deck = { ...deck, meta: { ...deck.meta, report_type: value === "research" ? "approval" : "research" } };
  const view = render(<ReportPurposeScreen project={project} deck={initial} onDeckChange={onDeckChange} />);
  await userEvent.selectOptions(screen.getByLabelText("보고 유형"), screen.getByRole("option", { name: label }));
  await userEvent.click(screen.getByRole("button", { name: "보고 정보 저장" }));
  await waitFor(() => expect(onDeckChange).toHaveBeenCalled());
  const saved = vi.mocked(api.putDeck).mock.calls.at(-1)![1];
  expect(saved.meta.report_type).toBe(value);
  view.unmount();
  render(<ReportPurposeScreen project={project} deck={saved} onDeckChange={onDeckChange} />);
  expect(screen.getByLabelText("보고 유형")).toHaveValue(value);
});


it("보고 정보를 저장하면 덱이 갱신된다", async () => {
  vi.mocked(api.putDeck).mockResolvedValue({ ok: true });
  const onDeckChange = vi.fn();
  render(<ReportPurposeScreen project={project} deck={deck} onDeckChange={onDeckChange} />);
  const title = screen.getByLabelText("보고서 제목");
  await userEvent.clear(title);
  await userEvent.type(title, "새 제목");
  await userEvent.click(screen.getByText("보고 정보 저장"));
  expect(api.putDeck).toHaveBeenCalledWith(
    "p1", expect.objectContaining({ meta: expect.objectContaining({ title: "새 제목" }) }), false);
  expect(onDeckChange).toHaveBeenCalled();
});


it("보고 정보의 입력 항목이 각각 한 줄을 차지한다", async () => {
  render(<ReportPurposeScreen project={project} deck={deck} onDeckChange={() => {}} />);
  const fields = ["보고서 제목", "보고 유형", "보고자", "피보고자"].map((l) => screen.getByLabelText(l).closest(".field"));
  fields.forEach((f) => expect(f).not.toBeNull());
  expect(new Set(fields).size).toBe(fields.length);
});


it("보고자를 입력해 저장하면 meta.presenter로 반영되고 피보고자 안내가 보인다", async () => {
  vi.mocked(api.putDeck).mockResolvedValue({ ok: true });
  const onDeckChange = vi.fn();
  render(<ReportPurposeScreen project={project} deck={deck} onDeckChange={onDeckChange} />);
  await userEvent.type(screen.getByLabelText("보고자"), "사업개발팀");
  await userEvent.click(screen.getByText("보고 정보 저장"));
  expect(onDeckChange).toHaveBeenCalledWith(expect.objectContaining({
    meta: expect.objectContaining({ presenter: "사업개발팀" }),
  }));
  expect(screen.getByText(/문서에 적히지 않고/)).toBeInTheDocument();
});


describe("보고 정보 플러시와 충돌 (A5)", () => {
  it("마운트 시 저장됨(false)을 알리고, 입력을 바꾸면 true를, 저장하면 다시 false를 알린다", async () => {
    vi.mocked(api.putDeck).mockResolvedValue({ ok: true });
    const onDirtyChange = vi.fn();
    render(<ReportPurposeScreen project={project} deck={deck} onDeckChange={() => {}}
      onDirtyChange={onDirtyChange} />);
    await waitFor(() => expect(onDirtyChange).toHaveBeenCalledWith(false));
    await userEvent.type(screen.getByLabelText("보고서 제목"), "고침");
    await waitFor(() => expect(onDirtyChange).toHaveBeenLastCalledWith(true));
    await userEvent.click(screen.getByText("보고 정보 저장"));
    await waitFor(() => expect(onDirtyChange).toHaveBeenLastCalledWith(false));
  });

  it("부모에 플러시 함수를 등록하고, 언마운트 시 등록을 해제한다", async () => {
    const onScreenReady = vi.fn();
    const { unmount } = render(<ReportPurposeScreen project={project} deck={deck} onDeckChange={() => {}}
      onScreenReady={onScreenReady} />);
    await waitFor(() => expect(onScreenReady).toHaveBeenCalledWith(expect.any(Function)));
    unmount();
    expect(onScreenReady).toHaveBeenLastCalledWith(null);
  });

  it("저장 버튼 없이 부모가 플러시를 부르면 최신 입력을 저장한다", async () => {
    vi.mocked(api.putDeck).mockResolvedValue({ ok: true });
    let flush: (() => Promise<boolean>) | null = null;
    render(<ReportPurposeScreen project={project} deck={deck} onDeckChange={() => {}}
      onScreenReady={(f) => { flush = f; }} />);
    await userEvent.type(screen.getByLabelText("보고서 제목"), "고침");
    expect(api.putDeck).not.toHaveBeenCalled();
    const ok = await flush!();
    expect(ok).toBe(true);
    expect(api.putDeck).toHaveBeenCalledWith(
      "p1", expect.objectContaining({ meta: expect.objectContaining({ title: "제목고침" }) }), false);
  });

  it("입력을 바꾸지 않았으면 플러시를 불러도 PUT이 없다", async () => {
    let flush: (() => Promise<boolean>) | null = null;
    render(<ReportPurposeScreen project={project} deck={deck} onDeckChange={() => {}}
      onScreenReady={(f) => { flush = f; }} />);
    await waitFor(() => expect(flush).not.toBeNull());
    expect(await flush!()).toBe(true);
    expect(api.putDeck).not.toHaveBeenCalled();
  });

  it("저장 중에는 입력과 저장 버튼을 잠근다", async () => {
    const { promise, resolve } = (() => {
      let r!: (v: { ok: boolean }) => void;
      const p = new Promise<{ ok: boolean }>((res) => { r = res; });
      return { promise: p, resolve: r };
    })();
    vi.mocked(api.putDeck).mockReturnValue(promise);
    render(<ReportPurposeScreen project={project} deck={deck} onDeckChange={() => {}} />);
    await userEvent.type(screen.getByLabelText("보고서 제목"), "고침");
    await userEvent.click(screen.getByText("보고 정보 저장"));
    await waitFor(() => expect(screen.getByLabelText("보고서 제목")).toBeDisabled());
    expect(screen.getByText("보고 정보 저장")).toBeDisabled();
    resolve({ ok: true });
    await waitFor(() => expect(screen.getByLabelText("보고서 제목")).not.toBeDisabled());
  });

  it("저장 버튼 클릭 직후 부모가 플러시를 불러도 PUT은 1회다 (직렬화)", async () => {
    vi.mocked(api.putDeck).mockResolvedValue({ ok: true });
    let flush: (() => Promise<boolean>) | null = null;
    render(<ReportPurposeScreen project={project} deck={deck} onDeckChange={() => {}}
      onScreenReady={(f) => { flush = f; }} />);
    await userEvent.type(screen.getByLabelText("보고서 제목"), "고침");
    await userEvent.click(screen.getByText("보고 정보 저장"));
    const flushed = await flush!();  // 버튼 저장이 아직 착지하기 전에 곧장 플러시를 부른다
    expect(flushed).toBe(true);
    await waitFor(() => expect(api.putDeck).toHaveBeenCalledTimes(1));
  });

  it("저장이 412면 onConflict를 부른다", async () => {
    vi.mocked(api.putDeck).mockRejectedValue(
      new ApiError(412, "다른 창이나 프로그램에서 이 프로젝트가 먼저 저장되었습니다."));
    const onConflict = vi.fn();
    render(<ReportPurposeScreen project={project} deck={deck} onDeckChange={() => {}}
      onConflict={onConflict} />);
    await userEvent.type(screen.getByLabelText("보고서 제목"), "고침");
    await userEvent.click(screen.getByText("보고 정보 저장"));
    await waitFor(() => expect(onConflict).toHaveBeenCalled());
  });
});


it("저장 성공 안내는 오류 알림이 아니고, 화면 낭독기 알림은 상단 머리의 저장 상태 하나다 (D2a-4, D3a 묶음 리뷰 A2)", async () => {
  // 다시 씀(A2): 종전에는 이 글이 role=status라 머리의 "저장됨"과 같은 저장을 두 번 알렸다
  vi.mocked(api.putDeck).mockResolvedValue({ ok: true });
  render(<ReportPurposeScreen project={project} deck={deck} onDeckChange={() => {}} />);
  await userEvent.type(screen.getByLabelText("보고서 제목"), " 수정");  // 변경이 있어야 저장한다
  await userEvent.click(screen.getByText("보고 정보 저장"));
  const notice = await screen.findByText("보고 정보를 저장했습니다.");
  expect(notice).not.toHaveAttribute("role");
  expect(screen.queryByRole("alert")).toBeNull();
});



it("주 행동은 보고 정보 저장 하나다 (D3a-1, 계획 4.6)", () => {
  render(<ReportPurposeScreen project={project} deck={deck} onDeckChange={() => {}} />);
  const primaries = document.querySelectorAll(".btn-primary");
  expect(primaries).toHaveLength(1);
  expect(primaries[0]).toHaveTextContent("보고 정보 저장");
});

it("상단 머리의 저장 상태: 고치면 변경사항 있음, 저장 중, 저장됨, 실패와 충돌은 그 저장의 결과 (D3a-2, 계획 4.1)", async () => {
  const statuses: SaveStatus[] = [];
  const pending = deferred<{ ok: boolean }>();
  vi.mocked(api.putDeck).mockReturnValueOnce(pending.promise)
    .mockRejectedValueOnce(new Error("서버 중단"))
    .mockRejectedValueOnce(new ApiError(412, "다른 창이나 프로그램에서 이 프로젝트가 먼저 저장되었습니다."));
  render(<ReportPurposeScreen project={project} deck={deck} onDeckChange={() => {}} onSaveStatusChange={(s) => statuses.push(s)} />);
  const last = () => statuses.at(-1)?.kind;
  expect(last()).toBe("saved");
  await userEvent.type(screen.getByLabelText("보고서 제목"), " 고침");
  expect(last()).toBe("unsaved");  // 폼이 저장본과 다르면 저장됨이 아니다 (R01 완료 기준)
  await userEvent.click(screen.getByText("보고 정보 저장"));
  await waitFor(() => expect(last()).toBe("saving"));
  pending.resolve({ ok: true });
  await waitFor(() => expect(last()).toBe("saved"));
  await userEvent.type(screen.getByLabelText("보고서 제목"), "2");
  await userEvent.click(screen.getByText("보고 정보 저장"));
  await waitFor(() => expect(last()).toBe("save_failed"));
  await userEvent.click(screen.getByText("보고 정보 저장"));
  await waitFor(() => expect(last()).toBe("conflict"));
});
