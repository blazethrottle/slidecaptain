// 보고 목적 단계 (D3a-2, D3b-5). 저장 계약: 저장 순간의 최신 덱에 보고 정보만 바꿔 덱 전체를 PUT한다.
// D3b-5부터 저장 버튼 없이 입력이 멈추면 자동 저장한다. 옛 "보고 정보 저장" 클릭 시험의 대응은 계획 D3b-5 구현 기록의 표다
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api, ApiError, notifyProject, type Deck } from "../api/client";
import { ReportPurposeScreen, type PurposePreserveResult } from "./ReportPurposeScreen";
import type { SaveStatus } from "../ui/StatusIndicator";
import { deferred } from "../test/fixtures";
import { jobView } from "../test/jobs";

beforeEach(() => { vi.mocked(api.listJobs).mockResolvedValue([]); });

vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return { ...mod, api: { ...mod.api, putDeck: vi.fn(), saveDraft: vi.fn(), listJobs: vi.fn() } };
});

const project = { name: "p1", title: "제목", updated_at: "", status: "ok" as const };
const deck: Deck = {
  schema_version: 1,
  meta: { title: "제목", report_type: "research", audience: "", presenter: "", preset_overrides: {} },
  structure: { chapters: [] },
  slides: [],
};

// 시험의 자동 저장 지연(ms). 글자를 하나씩 치는 시험은 Windows CI에서 한 글자에 20ms를 넘길 수 있으므로, 횟수를 세는
// 시험은 입력을 한 번에 넣고(paste) 시간 창에 기대는 시험은 지연을 넉넉히 준다
const FAST = 20;
const SLOW = 60_000;  // 자동 저장이 끼어들지 않게 할 때
type Props = Partial<Parameters<typeof ReportPurposeScreen>[0]>;
function renderScreen(props: Props = {}) {
  return render(<ReportPurposeScreen project={project} deck={deck} onDeckChange={() => {}} saveDelayMs={FAST} {...props} />);
}
const puts = () => vi.mocked(api.putDeck).mock.calls;
const pause = (ms: number) => act(() => new Promise((r) => setTimeout(r, ms)));

it.each([
  ["weekly", "주간 업무 보고"], ["business", "일반 업무 보고"], ["monthly", "월간 보고"],
  ["data", "데이터 설명 보고"], ["research", "리서치 결과 보고"],
  ["project", "프로젝트 보고"], ["results", "결과 보고"],
  ["approval", "승인요청"], ["strategy", "전략기획"], ["ir", "IR Pitch Deck"],
])("보고 유형 %s를 골라 자동 저장하고 다시 연다", async (value, label) => {
  // 다시 씀(D3b-5): 저장 버튼 클릭 대신 자동 저장을 기다린다
  vi.mocked(api.putDeck).mockResolvedValue({ ok: true });
  const onDeckChange = vi.fn();
  const initial: Deck = { ...deck, meta: { ...deck.meta, report_type: value === "research" ? "approval" : "research" } };
  const view = renderScreen({ deck: initial, onDeckChange });
  await userEvent.selectOptions(screen.getByLabelText("보고 유형"), screen.getByRole("option", { name: label }));
  await waitFor(() => expect(onDeckChange).toHaveBeenCalled());
  const saved = puts().at(-1)![1];
  expect(saved.meta.report_type).toBe(value);
  expect(saved.meta.report_type_confirmed).toBe(true);  // 직접 고른 유형은 확인된 유형이다 (D3b-1 리뷰 R4)
  view.unmount();
  renderScreen({ deck: saved, onDeckChange });
  expect(screen.getByLabelText("보고 유형")).toHaveValue(value);
});

it("확인되지 않은 기본 유형을 다른 유형에 들렀다가 다시 골라도 확인으로 저장한다 (α 묶음 리뷰 A4)", async () => {
  // 유형은 처음과 같고 확인 표시만 달라진다. 저장본 비교가 확인 표시를 보지 않으면 저장할 것이 없다고 판단한다
  vi.mocked(api.putDeck).mockResolvedValue({ ok: true });
  let flush: (() => Promise<boolean | "declined">) | null = null;
  renderScreen({ saveDelayMs: SLOW, onScreenReady: (f) => { flush = f; } });
  const select = screen.getByLabelText("보고 유형");
  await userEvent.selectOptions(select, screen.getByRole("option", { name: "승인요청" }));
  await userEvent.selectOptions(select, screen.getByRole("option", { name: "리서치 결과 보고" }));
  expect(await flush!()).toBe(true);
  const saved = puts().at(-1)![1];
  expect(saved.meta.report_type).toBe("research");
  expect(saved.meta.report_type_confirmed).toBe(true);
});

it("입력이 멈추면 한 번 자동 저장하고, 화면을 연 뒤 첫 저장은 스냅샷을 요청한다 (D3b-5, 재리뷰 RR2)", async () => {
  // 다시 씀(D3b-5): 옛 "보고 정보를 저장하면 덱이 갱신된다"
  vi.mocked(api.putDeck).mockResolvedValue({ ok: true });
  const onDeckChange = vi.fn();
  renderScreen({ onDeckChange });
  const title = screen.getByLabelText("보고서 제목");
  await userEvent.clear(title);
  await waitFor(() => expect(puts()).toHaveLength(1));  // 지운 것도 입력이다
  await userEvent.click(title);
  await userEvent.paste("새 제목");
  await waitFor(() => expect(puts()).toHaveLength(2));
  expect(puts()[0][2]).toBe(true);  // 화면을 연 뒤 첫 저장은 스냅샷을 요청한다
  expect(puts()[1]).toEqual(["p1", expect.objectContaining({ meta: expect.objectContaining({ title: "새 제목" }) }), false]);
  expect(onDeckChange).toHaveBeenCalled();
  await userEvent.paste("2");
  await waitFor(() => expect(puts()).toHaveLength(3));
  expect(puts()[2][2]).toBe(false);  // 둘째 저장부터는 스냅샷을 요청하지 않는다
  await pause(FAST * 3);
  expect(puts()).toHaveLength(3);
});

it("보고 정보의 입력 항목이 각각 한 줄을 차지한다", async () => {
  renderScreen();
  const fields = ["보고서 제목", "보고 유형", "보고자", "피보고자"].map((l) => screen.getByLabelText(l).closest(".field"));
  fields.forEach((f) => expect(f).not.toBeNull());
  expect(new Set(fields).size).toBe(fields.length);
});

it("보고자를 입력하면 meta.presenter로 자동 저장되고 피보고자 안내가 보인다", async () => {
  // 다시 씀(D3b-5): 저장 버튼 클릭 대신 자동 저장을 기다린다
  vi.mocked(api.putDeck).mockResolvedValue({ ok: true });
  const onDeckChange = vi.fn();
  renderScreen({ onDeckChange });
  await userEvent.type(screen.getByLabelText("보고자"), "사업개발팀");
  await waitFor(() => expect(onDeckChange).toHaveBeenCalledWith(expect.objectContaining({
    meta: expect.objectContaining({ presenter: "사업개발팀" }),
  })));
  expect(screen.getByText(/문서에 적히지 않고/)).toBeInTheDocument();
});


describe("자동 저장, 플러시와 충돌 (A5, D3b-5)", () => {
  it("마운트 시 저장됨(false)을 알리고, 입력을 바꾸면 true를, 자동 저장되면 다시 false를 알린다", async () => {
    vi.mocked(api.putDeck).mockResolvedValue({ ok: true });
    const onDirtyChange = vi.fn();
    renderScreen({ onDirtyChange });
    await waitFor(() => expect(onDirtyChange).toHaveBeenCalledWith(false));
    await userEvent.type(screen.getByLabelText("보고서 제목"), "고침");
    expect(onDirtyChange).toHaveBeenCalledWith(true);
    await waitFor(() => expect(onDirtyChange).toHaveBeenLastCalledWith(false));
  });

  it("부모에 플러시 함수를 등록하고, 언마운트 시 등록을 해제한다", async () => {
    const onScreenReady = vi.fn();
    const { unmount } = renderScreen({ onScreenReady });
    await waitFor(() => expect(onScreenReady).toHaveBeenCalledWith(expect.any(Function)));
    unmount();
    expect(onScreenReady).toHaveBeenLastCalledWith(null);
  });

  it("자동 저장 전에 부모가 플러시를 부르면 최신 입력을 바로 저장한다", async () => {
    vi.mocked(api.putDeck).mockResolvedValue({ ok: true });
    let flush: (() => Promise<boolean | "declined">) | null = null;
    renderScreen({ saveDelayMs: SLOW, onScreenReady: (f) => { flush = f; } });
    await userEvent.type(screen.getByLabelText("보고서 제목"), "고침");
    expect(api.putDeck).not.toHaveBeenCalled();
    expect(await flush!()).toBe(true);
    expect(api.putDeck).toHaveBeenCalledWith(
      "p1", expect.objectContaining({ meta: expect.objectContaining({ title: "제목고침" }) }), true);
  });

  it("입력을 바꾸지 않았으면 플러시를 불러도 PUT이 없다", async () => {
    let flush: (() => Promise<boolean | "declined">) | null = null;
    renderScreen({ onScreenReady: (f) => { flush = f; } });
    await waitFor(() => expect(flush).not.toBeNull());
    expect(await flush!()).toBe(true);
    expect(api.putDeck).not.toHaveBeenCalled();
  });

  it("저장 중에도 입력을 잠그지 않고, 이어 친 글자를 저장이 끝난 뒤 이어서 저장한다 (리뷰 U1)", async () => {
    // 다시 씀(D3b-5): 옛 "저장 중에는 입력과 저장 버튼을 잠근다". 잠그면 초점이 빠지고 이어 친 글자가 사라진다
    const first = deferred<{ ok: boolean }>();
    vi.mocked(api.putDeck).mockReturnValueOnce(first.promise).mockResolvedValue({ ok: true });
    renderScreen();
    const title = screen.getByLabelText("보고서 제목");
    await userEvent.type(title, "가");
    await waitFor(() => expect(puts()).toHaveLength(1));
    expect(title).not.toBeDisabled();
    await userEvent.type(title, "나");
    first.resolve({ ok: true });
    await waitFor(() => expect(puts()).toHaveLength(2));
    expect(puts()[1][1].meta.title).toBe("제목가나");
    expect(title).toHaveValue("제목가나");
  });

  it("자동 저장이 날아가는 중에 부모가 플러시를 불러도 PUT은 1회다 (직렬화)", async () => {
    // 다시 씀(D3b-5): 옛 "저장 버튼 클릭 직후 부모가 플러시를 불러도 PUT은 1회다"
    const first = deferred<{ ok: boolean }>();
    vi.mocked(api.putDeck).mockReturnValueOnce(first.promise);
    let flush: (() => Promise<boolean | "declined">) | null = null;
    renderScreen({ onScreenReady: (f) => { flush = f; } });
    await userEvent.click(screen.getByLabelText("보고서 제목"));
    await userEvent.paste("고침");
    await waitFor(() => expect(puts()).toHaveLength(1));
    const flushed = flush!();
    first.resolve({ ok: true });
    expect(await flushed).toBe(true);
    expect(puts()).toHaveLength(1);
  });

  it("저장이 412면 onConflict를 부르고, 그 뒤 입력 세 번에도 다시 저장하지 않는다 (리뷰 U3)", async () => {
    vi.mocked(api.putDeck).mockRejectedValue(
      new ApiError(412, "다른 창이나 프로그램에서 이 프로젝트가 먼저 저장되었습니다."));
    const onConflict = vi.fn();
    renderScreen({ onConflict });
    const title = screen.getByLabelText("보고서 제목");
    await userEvent.type(title, "고침");
    await waitFor(() => expect(onConflict).toHaveBeenCalled());
    for (const text of ["1", "2", "3"]) {
      await userEvent.type(title, text);
      await pause(FAST * 2);
    }
    expect(puts()).toHaveLength(1);
  });

  it("읽기 전용이 되면 예약된 저장이 나가지 않고, 풀리면 남은 입력을 저장한다 (리뷰 U2)", async () => {
    vi.mocked(api.putDeck).mockResolvedValue({ ok: true });
    const view = renderScreen({ saveDelayMs: 300 });
    await userEvent.click(screen.getByLabelText("보고서 제목"));
    await userEvent.paste("고침");
    view.rerender(<ReportPurposeScreen project={project} deck={deck} onDeckChange={() => {}} saveDelayMs={300} readOnly />);
    await pause(500);
    expect(api.putDeck).not.toHaveBeenCalled();
    view.rerender(<ReportPurposeScreen project={project} deck={deck} onDeckChange={() => {}} saveDelayMs={300} />);
    await waitFor(() => expect(puts()).toHaveLength(1));
  });

  it("마운트 뒤 충돌 신호가 오면 자동 저장을 멈춘다. 마운트 때 이미 늘어난 값은 신호가 아니다 (F1)", async () => {
    vi.mocked(api.putDeck).mockResolvedValue({ ok: true });
    const props = { project, deck, onDeckChange: () => {}, saveDelayMs: 300 };
    const view = render(<ReportPurposeScreen {...props} conflictSignal={3} />);
    await userEvent.type(screen.getByLabelText("보고서 제목"), "가");
    await waitFor(() => expect(puts()).toHaveLength(1));  // 마운트 때의 3은 충돌이 아니다
    await userEvent.type(screen.getByLabelText("보고서 제목"), "나");
    view.rerender(<ReportPurposeScreen {...props} conflictSignal={4} />);
    await pause(500);
    expect(puts()).toHaveLength(1);
  });

  it("412가 아닌 실패에는 다시 저장을 둔다 (리뷰 U14)", async () => {
    vi.mocked(api.putDeck).mockRejectedValueOnce(new Error("서버 중단")).mockResolvedValue({ ok: true });
    renderScreen();
    await userEvent.click(screen.getByLabelText("보고서 제목"));
    await userEvent.paste("고침");
    const retry = await screen.findByRole("button", { name: "다시 저장" });
    await userEvent.click(retry);
    await waitFor(() => expect(puts()).toHaveLength(2));
    await waitFor(() => expect(screen.queryByRole("button", { name: "다시 저장" })).toBeNull());
  });

  it("유형 드롭다운은 초점이 떠나면 지연을 기다리지 않고 저장한다", async () => {
    vi.mocked(api.putDeck).mockResolvedValue({ ok: true });
    renderScreen({ saveDelayMs: SLOW });
    await userEvent.selectOptions(screen.getByLabelText("보고 유형"), screen.getByRole("option", { name: "승인요청" }));
    expect(api.putDeck).not.toHaveBeenCalled();
    await userEvent.tab();
    await waitFor(() => expect(puts()).toHaveLength(1));
  });
});

describe("충돌 해소 전 보존 (B9, 리뷰 U4)", () => {
  it("미저장 보고 정보를 출처 purpose로 보존한다", async () => {
    vi.mocked(api.putDeck).mockRejectedValue(new ApiError(412, "먼저 저장되었습니다."));
    vi.mocked(api.saveDraft).mockResolvedValue({ id: "d1", saved_at: "2026-10-12T10:00:00+09:00",
      reason: "conflict", source: "purpose", base_etag: null });
    let preserve: (() => Promise<PurposePreserveResult>) | null = null;
    renderScreen({ onPreserveReady: (f) => { preserve = f; } });
    await userEvent.type(screen.getByLabelText("보고서 제목"), "고침");
    await waitFor(() => expect(puts()).toHaveLength(1));
    const result = await act(() => preserve!());
    expect(result).toEqual({ kind: "preserved", savedAt: "2026-10-12T10:00:00+09:00" });
    expect(api.saveDraft).toHaveBeenCalledWith("p1", expect.objectContaining({ reason: "conflict", source: "purpose",
      deck: expect.objectContaining({ meta: expect.objectContaining({ title: "제목고침" }) }) }));
  });

  it("보존에 실패하면 복사 상자를 보인다", async () => {
    vi.mocked(api.putDeck).mockRejectedValue(new ApiError(412, "먼저 저장되었습니다."));
    vi.mocked(api.saveDraft).mockRejectedValue(new Error("디스크 오류"));
    let preserve: (() => Promise<PurposePreserveResult>) | null = null;
    renderScreen({ onPreserveReady: (f) => { preserve = f; } });
    await userEvent.type(screen.getByLabelText("보고서 제목"), "고침");
    await waitFor(() => expect(puts()).toHaveLength(1));
    expect(await act(() => preserve!())).toEqual({ kind: "failed" });
    expect(screen.getByText(/보고 정보를 보존하지 못했습니다/)).toBeInTheDocument();
    expect(screen.getByText("저장하지 못한 보고 정보")).toBeInTheDocument();
    expect((screen.getByLabelText("보관용 변경 내용") as HTMLTextAreaElement).value).toContain("제목고침");
  });

  it("미저장 입력이 없으면 보존하지 않는다", async () => {
    let preserve: (() => Promise<PurposePreserveResult>) | null = null;
    renderScreen({ onPreserveReady: (f) => { preserve = f; } });
    await waitFor(() => expect(preserve).not.toBeNull());
    expect(await act(() => preserve!())).toEqual({ kind: "none" });
    expect(api.saveDraft).not.toHaveBeenCalled();
  });
});


it("저장이 끝나도 성공 문장을 따로 보이지 않는다. 알림은 상단 머리의 저장 상태 하나다 (리뷰 U15, D3a 묶음 리뷰 A2)", async () => {
  // 다시 씀(D3b-5): 옛 시험은 성공 문장이 role 없이 보이는지 봤다. 자동 저장에서는 문장을 없앴다
  vi.mocked(api.putDeck).mockResolvedValue({ ok: true });
  renderScreen();
  await userEvent.click(screen.getByLabelText("보고서 제목"));
  await userEvent.paste(" 수정");
  await waitFor(() => expect(puts()).toHaveLength(1));
  expect(screen.queryByText("보고 정보를 저장했습니다.")).toBeNull();
  expect(screen.queryByRole("alert")).toBeNull();
});

it("주 행동은 자료 단계로 하나다 (D3a-1, 계획 4.6, Q2)", async () => {
  const onNext = vi.fn();
  const view = renderScreen({ onNext });
  const primaries = document.querySelectorAll(".btn-primary");
  expect(primaries).toHaveLength(1);
  expect(primaries[0]).toHaveTextContent("자료 단계로");
  await userEvent.click(screen.getByRole("button", { name: "자료 단계로" }));
  expect(onNext).toHaveBeenCalledTimes(1);
  view.rerender(<ReportPurposeScreen project={project} deck={deck} onDeckChange={() => {}} onNext={onNext} nextDisabled />);
  expect(screen.getByRole("button", { name: "자료 단계로" })).toBeDisabled();
});

it("상단 머리의 저장 상태: 고치면 변경사항 있음, 저장 중, 저장됨, 실패와 충돌은 그 저장의 결과 (D3a-2, 계획 4.1)", async () => {
  // 다시 씀(D3b-5): 저장 버튼 대신 부모의 플러시와 "다시 저장"으로 저장을 일으킨다
  const statuses: SaveStatus[] = [];
  const pending = deferred<{ ok: boolean }>();
  vi.mocked(api.putDeck).mockReturnValueOnce(pending.promise)
    .mockRejectedValueOnce(new Error("서버 중단"))
    .mockRejectedValueOnce(new ApiError(412, "다른 창이나 프로그램에서 이 프로젝트가 먼저 저장되었습니다."));
  let flush: (() => Promise<boolean | "declined">) | null = null;
  renderScreen({ saveDelayMs: SLOW, onSaveStatusChange: (st) => statuses.push(st), onScreenReady: (f) => { flush = f; } });
  const last = () => statuses.at(-1)?.kind;
  expect(last()).toBe("saved");
  await userEvent.type(screen.getByLabelText("보고서 제목"), " 고침");
  expect(last()).toBe("unsaved");  // 폼이 저장본과 다르면 저장됨이 아니다 (R01 완료 기준)
  const first = flush!();
  await waitFor(() => expect(last()).toBe("saving"));
  pending.resolve({ ok: true });
  await first;
  await waitFor(() => expect(last()).toBe("saved"));
  await userEvent.type(screen.getByLabelText("보고서 제목"), "2");
  await act(() => flush!());
  await waitFor(() => expect(last()).toBe("save_failed"));
  await userEvent.click(screen.getByRole("button", { name: "다시 저장" }));
  await waitFor(() => expect(last()).toBe("conflict"));
});


describe("보고 목적 입력 (D3b-5, 계획 4.5)", () => {
  const confirmedDeck = (meta: Partial<Deck["meta"]> = {}): Deck =>
    ({ ...deck, meta: { ...deck.meta, report_type: "weekly", report_type_confirmed: true, ...meta } });

  it("배치 순서는 기본 정보, 유형 영역, 원하는 결과, 주 행동이다 (Tab 순서)", () => {
    renderScreen({ deck: confirmedDeck() });
    const order = ["보고서 제목", "보고자", "피보고자", "이 보고서에서 전달할 핵심 내용", "보고 유형", "보고 기간 (선택)"]
      .map((l) => screen.getByLabelText(l));
    const outcome = screen.getByRole("radio", { name: "사업 기획안" });
    const next = screen.getByRole("button", { name: "자료 단계로" });
    [...order, outcome, next].reduce((previous, current) => {
      expect(previous.compareDocumentPosition(current) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
      return current;
    });
  });

  it("핵심 내용, 원하는 결과, 지금 유형의 추가 입력을 자동 저장한다", async () => {
    vi.mocked(api.putDeck).mockResolvedValue({ ok: true });
    renderScreen({ deck: confirmedDeck() });
    await userEvent.type(screen.getByLabelText("이 보고서에서 전달할 핵심 내용"), "핵심");
    await userEvent.click(screen.getByRole("radio", { name: "투자자 및 의사결정자 설득" }));
    await userEvent.type(screen.getByLabelText("보고 기간 (선택)"), "10월 1주");
    await waitFor(() => expect(puts().at(-1)![1].meta).toMatchObject({
      key_message: "핵심", desired_outcome: "persuasion", report_details: { "weekly.period": "10월 1주" } }));
  });

  it("핵심 내용은 글자 수를 보이고 8,000자를 넘겨 입력할 수 없다", () => {
    renderScreen({ deck: confirmedDeck({ key_message: "가나다" }) });
    expect(screen.getByLabelText("이 보고서에서 전달할 핵심 내용")).toHaveAttribute("maxLength", "8000");
    expect(screen.getByText("3 / 8,000자")).toBeInTheDocument();
    expect(screen.getByLabelText("보고 기간 (선택)")).toHaveAttribute("maxLength", "1000");
  });

  it("기타를 고르면 설명 칸이 나오고, 비어 있으면 그 칸 아래에 알린다 (리뷰 U22)", async () => {
    renderScreen({ deck: confirmedDeck(), saveDelayMs: SLOW });
    expect(screen.queryByLabelText("기타 목적 설명")).toBeNull();
    await userEvent.click(screen.getByRole("radio", { name: "기타 (직접 입력)" }));
    expect(screen.getByLabelText("기타 목적 설명")).toHaveAccessibleDescription(/기타 목적의 설명이 비어 있습니다\./);
    await userEvent.type(screen.getByLabelText("기타 목적 설명"), "내부 공유");
    expect(screen.queryByText("기타 목적의 설명이 비어 있습니다.")).toBeNull();
  });

  it("유형을 바꾸면 그 유형의 추가 입력이 보이고, 앞 유형의 입력은 숨은 입력으로 남는다", async () => {
    renderScreen({ deck: confirmedDeck({ report_details: { "weekly.period": "10월" } }), saveDelayMs: SLOW });
    await userEvent.selectOptions(screen.getByLabelText("보고 유형"), screen.getByRole("option", { name: "IR Pitch Deck" }));
    expect(screen.queryByLabelText("보고 기간 (선택)")).toBeNull();
    expect(screen.getByLabelText("투자 단계 (선택)")).toBeInTheDocument();
    expect(screen.getByText(/지금 쓰지 않는 입력 1개/)).toBeInTheDocument();
  });

  it("숨은 입력 지우기는 다른 유형의 추가 입력과 기타가 아닐 때의 기타 설명을 지운다", async () => {
    vi.mocked(api.putDeck).mockResolvedValue({ ok: true });
    renderScreen({ deck: confirmedDeck({ desired_outcome: "facts", desired_outcome_other: "옛 설명",
      report_details: { "weekly.period": "유지", "ir.investment_stage": "시드" } }) });
    expect(screen.getByText(/지금 쓰지 않는 입력 2개/)).toBeInTheDocument();
    vi.spyOn(window, "confirm").mockReturnValueOnce(true);  // 지우기 전에 확인한다 (D3b-5 리뷰 R13)
    await userEvent.click(screen.getByRole("button", { name: "쓰지 않는 입력 지우기" }));
    await waitFor(() => expect(puts()).toHaveLength(1));
    const meta = puts()[0][1].meta;
    expect(meta.report_details).toEqual({ "weekly.period": "유지" });
    expect(meta.desired_outcome_other).toBe("");
    expect(screen.queryByText(/남아 있습니다/)).toBeNull();
  });

  it("확인되지 않은 덱은 고르기를 요청하고 예시 자리를 비워 둔다. 리서치 결과 보고를 고르면 확인된다 (리뷰 U10)", async () => {
    vi.mocked(api.putDeck).mockResolvedValue({ ok: true });
    renderScreen();
    expect(screen.getByLabelText("보고 유형")).toHaveValue("");
    expect(screen.getByRole("option", { name: "보고 유형을 고르세요" })).toBeInTheDocument();
    expect(screen.getByText("유형을 고르면 예시가 보입니다.")).toBeInTheDocument();
    expect(screen.queryByLabelText("조사 질문 (선택)")).toBeNull();
    await userEvent.selectOptions(screen.getByLabelText("보고 유형"), screen.getByRole("option", { name: "리서치 결과 보고" }));
    await waitFor(() => expect(puts().at(-1)![1].meta.report_type_confirmed).toBe(true));
    expect(screen.queryByRole("option", { name: "보고 유형을 고르세요" })).toBeNull();
    expect(screen.getByLabelText("조사 질문 (선택)")).toBeInTheDocument();
  });

  it("유형 설명과 추천 구성이 드롭다운의 설명으로 이어진다", () => {
    renderScreen({ deck: confirmedDeck() });
    expect(screen.getByLabelText("보고 유형")).toHaveAccessibleDescription(/실적과 다음 주 계획을 정리합니다/);
    expect(screen.getByRole("list")).toHaveTextContent("이번 주 요약");
  });

  it("예시 둘러보기는 저장하지 않고 10종을 넘긴다. 드롭다운에서 고르면 그 유형으로 돌아온다 (리뷰 U11)", async () => {
    renderScreen({ deck: confirmedDeck() });
    const example = screen.getByRole("region", { name: "보고 유형 예시" });
    const seen = new Set<string>();
    for (let i = 0; i < 10; i++) {
      seen.add(example.querySelector("strong")!.textContent!);
      await userEvent.click(screen.getByRole("button", { name: "다음 예시" }));
    }
    expect(seen.size).toBe(10);
    await pause(FAST * 3);
    expect(api.putDeck).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "이전 예시" }));
    await userEvent.selectOptions(screen.getByLabelText("보고 유형"), screen.getByRole("option", { name: "승인요청" }));
    expect(example.querySelector("strong")).toHaveTextContent("승인요청");
  });

  it("저장된 구성 계획이 있으면 계획에 쓰인 값을 고칠 때만 다시 확인을 미리 알린다 (α 묶음 리뷰 A6)", async () => {
    const plan = { brief: { decision_question: "질문", audience: "", report_type: "weekly", reading_profile: "미지정",
      constraints: [] } } as unknown as NonNullable<Deck["structure"]["story_plan"]>;
    const withPlan: Deck = { ...confirmedDeck({ key_message: "핵심" }), structure: { chapters: [], story_plan: plan } };
    renderScreen({ deck: withPlan, saveDelayMs: SLOW });
    const warning = "보고 정보가 바뀌어 구성 단계의 저장된 계획을 다시 확인해야 합니다.";
    await userEvent.type(screen.getByLabelText("보고자"), "팀");  // 보고자는 계획을 낡게 하지 않는다
    await userEvent.type(screen.getByLabelText("이 보고서에서 전달할 핵심 내용"), " ");  // 앞뒤 공백도 그렇다 (α 묶음 리뷰 A5)
    expect(screen.queryByText(warning)).toBeNull();
    await userEvent.type(screen.getByLabelText("이 보고서에서 전달할 핵심 내용"), "추가");
    expect(screen.getByText(warning)).toBeInTheDocument();
  });

  it("처분하지 않은 구조안 후보가 있으면 고치기 전에 알린다 (리뷰 U21)", async () => {
    vi.mocked(api.listJobs).mockResolvedValue([jobView("structure", { candidate_status: "held" })]);
    renderScreen();
    expect(await screen.findByText("반영하지 않은 생성 후보가 있습니다. 보고 정보를 고치면 그 후보가 이전 입력 기준이 될 수 있습니다."))
      .toBeInTheDocument();
  });

  it("핵심 내용 없음 같은 한계 사유를 이 화면에 보인다 (D3b-1 리뷰 R7)", () => {
    renderScreen({ limitations: ["전달할 핵심 내용이 비어 있습니다."] });
    expect(screen.getByText("전달할 핵심 내용이 비어 있습니다.")).toBeInTheDocument();
  });
});


describe("D3b-5 리뷰 반영", () => {
  const plan = { brief: { decision_question: "질문", audience: "", report_type: "weekly", reading_profile: "미지정",
    constraints: [] } } as unknown as NonNullable<Deck["structure"]["story_plan"]>;
  const planned = (meta: Partial<Deck["meta"]> = {}): Deck =>
    ({ ...deck, meta: { ...deck.meta, report_type: "weekly", report_type_confirmed: true, ...meta }, structure: { chapters: [], story_plan: plan } });
  const WARNING = "보고 정보가 바뀌어 구성 단계의 저장된 계획을 다시 확인해야 합니다.";

  it("추가 입력이 없는 덱에서 유형만 바꿔도, 제목을 바꿔도 미리 알린다 (R1, R2)", async () => {
    const view = renderScreen({ deck: planned(), saveDelayMs: SLOW });
    await userEvent.selectOptions(screen.getByLabelText("보고 유형"), screen.getByRole("option", { name: "IR Pitch Deck" }));
    expect(screen.getByText(WARNING)).toBeInTheDocument();
    view.unmount();
    renderScreen({ deck: planned(), saveDelayMs: SLOW });
    await userEvent.type(screen.getByLabelText("보고서 제목"), " 고침");
    expect(screen.getByText(WARNING)).toBeInTheDocument();
  });

  it("구성 계획이 없으면 고쳐도 알리지 않고, 진행 API가 낡았다고 하면 고치지 않아도 알린다 (R6, 변형 M15)", async () => {
    const view = renderScreen({ deck: { ...deck, meta: { ...deck.meta, report_type_confirmed: true } }, saveDelayMs: SLOW });
    await userEvent.type(screen.getByLabelText("보고서 제목"), " 고침");
    expect(screen.queryByText(WARNING)).toBeNull();
    view.unmount();
    renderScreen({ deck: planned(), planStale: true });
    expect(screen.getByText(WARNING)).toBeInTheDocument();
  });

  it("미리 알림은 늘 있는 상태 알림 안에 나타난다 (R10)", async () => {
    renderScreen({ deck: planned(), saveDelayMs: SLOW });
    const status = screen.getAllByRole("status").find((el) => el.classList.contains("purpose-notices"))!;
    expect(status).toBeEmptyDOMElement();
    await userEvent.type(screen.getByLabelText("보고서 제목"), " 고침");
    expect(status).toHaveTextContent(WARNING);
  });

  it("진행 중인 생성 작업을 알리고, 작업이 끝나면 작업 목록을 다시 읽는다 (R7)", async () => {
    vi.mocked(api.listJobs).mockResolvedValueOnce([jobView("rewrite", { state: "running", candidate_status: "none" })])
      .mockResolvedValue([]);
    renderScreen();
    expect(await screen.findByText(/진행 중인 AI 생성이 있습니다/)).toBeInTheDocument();
    await act(async () => notifyProject({ kind: "job_ended", project: "p1", jobId: "job-1", state: "succeeded",
      jobKind: "rewrite" }, { broadcast: false }));
    await waitFor(() => expect(screen.queryByText(/진행 중인 AI 생성이 있습니다/)).toBeNull());
  });

  it("원하는 결과는 고르지 않음으로 되돌릴 수 있다 (R9)", async () => {
    vi.mocked(api.putDeck).mockResolvedValue({ ok: true });
    renderScreen({ deck: planned({ desired_outcome: "persuasion" }) });
    await userEvent.click(screen.getByRole("radio", { name: "고르지 않음 (보고 유형의 구성을 따름)" }));
    await waitFor(() => expect(puts().at(-1)![1].meta.desired_outcome).toBeNull());
  });

  it("핵심 내용과 추가 입력의 이름은 보이는 라벨 그대로다 (R11)", () => {
    renderScreen({ deck: planned() });
    expect(screen.getByRole("textbox", { name: "이 보고서에서 전달할 핵심 내용" })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "보고 기간 (선택)" })).toBeInTheDocument();
  });

  it("보존을 시작하면 이 화면의 저장을 멈춰, 다시 마운트할 때 언마운트 저장이 나가지 않는다 (R3)", async () => {
    vi.mocked(api.putDeck).mockResolvedValue({ ok: true });
    vi.mocked(api.saveDraft).mockResolvedValue({ id: "d1", saved_at: "2026-10-12T10:00:00+09:00", reason: "conflict",
      source: "purpose", base_etag: null });
    let preserve: (() => Promise<PurposePreserveResult>) | null = null;
    const view = renderScreen({ saveDelayMs: SLOW, onPreserveReady: (f) => { preserve = f; } });
    await userEvent.type(screen.getByLabelText("보고서 제목"), "고침");
    await act(() => preserve!());
    view.unmount();
    await pause(FAST * 2);  // 언마운트 저장은 저장 사슬 뒤에 비동기로 나간다
    expect(api.putDeck).not.toHaveBeenCalled();
  });

  it("부모의 충돌 안내가 떠 있는 채로 열리면 입력해도 자동 저장하지 않는다 (R3)", async () => {
    vi.mocked(api.putDeck).mockResolvedValue({ ok: true });
    renderScreen({ startInConflict: true });
    await userEvent.type(screen.getByLabelText("보고서 제목"), "고침");
    await pause(FAST * 4);
    expect(api.putDeck).not.toHaveBeenCalled();
  });

  it("저장이 날아가는 동안 부모 덱이 바뀌면 착지 뒤 그 덱에 보고 정보만 얹는다 (R8)", async () => {
    const first = deferred<{ ok: boolean }>();
    vi.mocked(api.putDeck).mockReturnValueOnce(first.promise).mockResolvedValue({ ok: true });
    const onDeckChange = vi.fn();
    const props = { project, onDeckChange, saveDelayMs: FAST };
    const view = render(<ReportPurposeScreen {...props} deck={deck} />);
    await userEvent.click(screen.getByLabelText("보고서 제목"));
    await userEvent.paste("가");
    await waitFor(() => expect(puts()).toHaveLength(1));
    const newer: Deck = { ...deck, structure: { chapters: [{ id: "c9", topic: "새 장", conclusion: "", template: "bullet_box", source_refs: [] }] } };
    view.rerender(<ReportPurposeScreen {...props} deck={newer} />);
    await userEvent.paste("나");
    first.resolve({ ok: true });
    await waitFor(() => expect(puts()).toHaveLength(2));
    expect(puts()[1][1].structure.chapters[0].id).toBe("c9");
    expect(onDeckChange.mock.calls[0][0].structure.chapters[0].id).toBe("c9");
  });

  it("플러시는 날아가던 저장 뒤 남은 입력까지 저장하고 참을 돌려준다 (변형 M5)", async () => {
    const first = deferred<{ ok: boolean }>();
    vi.mocked(api.putDeck).mockReturnValueOnce(first.promise).mockResolvedValue({ ok: true });
    let flush: (() => Promise<boolean | "declined">) | null = null;
    renderScreen({ saveDelayMs: SLOW, onScreenReady: (f) => { flush = f; } });
    await userEvent.click(screen.getByLabelText("보고서 제목"));
    await userEvent.paste("가");
    const one = flush!();
    await waitFor(() => expect(puts()).toHaveLength(1));
    await userEvent.paste("나");
    first.resolve({ ok: true });
    expect(await one).toBe(true);
    await waitFor(() => expect(puts()).toHaveLength(2));
    expect(puts()[1][1].meta.title).toBe("제목가나");
  });

  it("저장 중 읽기 전용이 되면 남은 입력을 이어 저장하지 않는다 (변형 M4)", async () => {
    const first = deferred<{ ok: boolean }>();
    vi.mocked(api.putDeck).mockReturnValueOnce(first.promise).mockResolvedValue({ ok: true });
    const props = { project, deck, onDeckChange: () => {}, saveDelayMs: FAST };
    const view = render(<ReportPurposeScreen {...props} />);
    await userEvent.click(screen.getByLabelText("보고서 제목"));
    await userEvent.paste("가");
    await waitFor(() => expect(puts()).toHaveLength(1));
    await userEvent.paste("나");
    view.rerender(<ReportPurposeScreen {...props} readOnly />);
    first.resolve({ ok: true });
    await pause(FAST * 4);
    expect(puts()).toHaveLength(1);
  });

  it("언마운트 저장은 미저장 입력이 있으면 나가고, 충돌 중이면 나가지 않는다 (변형 M7, M8)", async () => {
    vi.mocked(api.putDeck).mockResolvedValue({ ok: true });
    const view = renderScreen({ saveDelayMs: SLOW });
    await userEvent.type(screen.getByLabelText("보고서 제목"), "가");
    view.unmount();
    await waitFor(() => expect(puts()).toHaveLength(1));
    vi.mocked(api.putDeck).mockReset();
    vi.mocked(api.putDeck).mockRejectedValue(new ApiError(412, "먼저 저장되었습니다."));
    const second = renderScreen();
    await userEvent.click(screen.getByLabelText("보고서 제목"));
    await userEvent.paste("나");
    await waitFor(() => expect(puts()).toHaveLength(1));  // 412
    await userEvent.paste("다");
    second.unmount();
    await pause(FAST * 2);
    expect(puts()).toHaveLength(1);
  });

  it("저장이 날아가는 동안 충돌 신호가 오면 늦은 성공이 충돌 상태를 지우지 않는다 (변형 M1)", async () => {
    const first = deferred<{ ok: boolean }>();
    vi.mocked(api.putDeck).mockReturnValueOnce(first.promise);
    const statuses: SaveStatus[] = [];
    const props = { project, deck, onDeckChange: () => {}, saveDelayMs: FAST, onSaveStatusChange: (st: SaveStatus) => statuses.push(st) };
    const view = render(<ReportPurposeScreen {...props} conflictSignal={0} />);
    await userEvent.click(screen.getByLabelText("보고서 제목"));
    await userEvent.paste("가");
    await waitFor(() => expect(puts()).toHaveLength(1));
    view.rerender(<ReportPurposeScreen {...props} conflictSignal={1} />);
    first.resolve({ ok: true });
    await pause(FAST * 2);
    expect(statuses.at(-1)?.kind).toBe("conflict");
  });
});
