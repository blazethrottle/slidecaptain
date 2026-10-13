// 장 후보 비교 화면 (D3c-6, 계획 4.8): 키보드와 초점, 표시 상태, 선택이 미리 보기와 반영에 실리는지
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createRef } from "react";
import { api, type Slide, type Slots } from "../api/client";
import { previewOf } from "../test/compare";
import { CandidateCompareDialog } from "./CandidateCompareDialog";

vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return { ...mod, api: { ...mod.api, previewCandidate: vi.fn() } };
});

const current: Slide = { chapter_id: "c1", eyebrow: "", subtitle: "", slots: {
  template: "bullet_box", bullets: [{ text: "지금 불릿", level: 0 }], conclusion: "지금 결론", footnote: "" },
  direct_edits: { conclusion: { dx_pt: 4, dy_pt: 0 }, footnote: { hidden: true } } };
const candidate: Slots = { template: "bullet_box", bullets: [{ text: "새 불릿", level: 0 }, { text: "둘", level: 0 }],
  conclusion: "새 결론", footnote: "" };

function open(props: Partial<Parameters<typeof CandidateCompareDialog>[0]> = {}) {
  const handlers = { onApply: vi.fn(async () => {}), onClose: vi.fn(), onStaleBase: vi.fn(), onRegenerate: vi.fn(), ...props };
  render(<CandidateCompareDialog projectName="p1" jobId="job-1" title="1장 주제" candidateSlots={candidate} {...handlers} />);
  return handlers;
}
const dialog = () => screen.findByRole("dialog", { name: "1장 주제: 새 내용과 비교" });

it("Tab은 비교 화면 안을 돌고 Escape는 닫으며, 닫히면 연 버튼으로 초점이 돌아온다", async () => {
  vi.mocked(api.previewCandidate).mockResolvedValue(previewOf(current, candidate));
  const opener = document.createElement("button");
  document.body.appendChild(opener);
  const returnFocus = createRef<HTMLElement>() as { current: HTMLElement | null };
  returnFocus.current = opener;
  const onClose = vi.fn();
  const { unmount } = render(<CandidateCompareDialog projectName="p1" jobId="job-1" title="1장 주제"
    candidateSlots={candidate} onApply={vi.fn()} onClose={onClose} onStaleBase={vi.fn()} returnFocus={returnFocus} />);
  const box = await dialog();
  await within(box).findByRole("group", { name: /본문 불릿/ });
  for (let i = 0; i < 40; i++) {
    await userEvent.tab();
    expect(box.contains(document.activeElement)).toBe(true);
  }
  await userEvent.keyboard("{Escape}");
  expect(onClose).toHaveBeenCalled();
  unmount();
  expect(document.activeElement).toBe(opener);
  opener.remove();
});

it("키보드만으로 단위를 고르고 반영하며, 반영은 미리 보기의 실제 선택과 기준 저장본을 넘기고 반영 중에는 Escape로 닫지 않는다", async () => {
  vi.mocked(api.previewCandidate).mockImplementation(async (_n, _j, body) => previewOf(current, candidate,
    { keep_current: body?.keep_current ?? [], base_etag: "e7" }));
  let finish: () => void = () => {};
  const handlers = open({ onApply: vi.fn(() => new Promise<void>((res) => { finish = res; })) });
  const box = await dialog();
  const bullets = await within(box).findByRole("group", { name: /본문 불릿/ });
  within(bullets).getByRole("radio", { name: "지금 문구 유지" }).focus();
  await userEvent.keyboard(" ");
  await waitFor(() => expect(api.previewCandidate).toHaveBeenLastCalledWith("p1", "job-1", { keep_current: ["bullets"] }));
  const apply = within(box).getByRole("button", { name: "반영" });
  await waitFor(() => expect(apply).toBeEnabled());
  apply.focus();
  await userEvent.keyboard("{Enter}");
  expect(handlers.onApply).toHaveBeenCalledWith({ keep_current: ["bullets"], drop_edits: [], unhide: [] }, "e7");
  await userEvent.keyboard("{Escape}");
  expect(handlers.onClose).not.toHaveBeenCalled();
  finish();
});

// 서버의 기본값 계산을 흉내 낸다: 고르지 않은 요소 수정은 결론 단위를 새 문구로 쓰면 지운다(목록 길이 변화의 대역)
const serverDefaults = async (_n: string, _j: string, body?: { keep_current?: string[] | null;
  edit_choices?: Record<string, "keep" | "drop" | "unhide"> | null }) => {
  const keep = body?.keep_current ?? ["conclusion"];
  const drops = new Set(keep.includes("conclusion") ? [] : ["conclusion"]);
  const unhide = new Set<string>();
  for (const [key, how] of Object.entries(body?.edit_choices ?? {})) {
    drops.delete(key); unhide.delete(key);
    if (how === "drop") drops.add(key);
    if (how === "unhide") unhide.add(key);
  }
  return previewOf(current, candidate, { keep_current: keep, drop_edits: [...drops], unhide: [...unhide] });
};

it("요소 수정은 유지, 숨김만 풀기, 지우기를 고르고 건드린 열쇠만 요청에 실린다", async () => {
  vi.mocked(api.previewCandidate).mockImplementation(serverDefaults);
  const handlers = open();
  const box = await dialog();
  const conclusion = await within(box).findByRole("group", { name: "결론 상자의 위치와 서식" });
  const footnote = within(box).getByRole("group", { name: "각주의 위치와 서식 (숨김)" });
  expect(within(conclusion).queryByRole("radio", { name: "숨김만 풀기" })).toBeNull();
  await userEvent.click(within(conclusion).getByRole("radio", { name: "지우기" }));
  await userEvent.click(within(footnote).getByRole("radio", { name: "숨김만 풀기" }));
  await waitFor(() => expect(api.previewCandidate).toHaveBeenLastCalledWith("p1", "job-1",
    { keep_current: ["conclusion"], edit_choices: { conclusion: "drop", footnote: "unhide" } }));
  const apply = within(box).getByRole("button", { name: "반영" });
  await waitFor(() => expect(apply).toBeEnabled());
  await userEvent.click(apply);
  expect(handlers.onApply).toHaveBeenCalledWith({ keep_current: ["conclusion"], drop_edits: ["conclusion"], unhide: ["footnote"] }, "e0");
});

it("건드리지 않은 요소 수정은 단위를 바꿀 때 서버 기본값을 따라가고, 건드리면 그 선택이 남는다 (리뷰 G2)", async () => {
  vi.mocked(api.previewCandidate).mockImplementation(serverDefaults);
  const handlers = open();
  const box = await dialog();
  const conclusionEdit = await within(box).findByRole("group", { name: "결론 상자의 위치와 서식" });
  expect(within(conclusionEdit).getByRole("radio", { name: "유지" })).toBeChecked();
  const unit = within(box).getByRole("group", { name: /^결론 상자$/ });
  await userEvent.click(within(unit).getByRole("radio", { name: "새 문구 사용" }));
  await waitFor(() => expect(api.previewCandidate).toHaveBeenLastCalledWith("p1", "job-1", { keep_current: [] }));
  await waitFor(() => expect(within(conclusionEdit).getByRole("radio", { name: "지우기" })).toBeChecked());
  await userEvent.click(within(conclusionEdit).getByRole("radio", { name: "유지" }));
  await waitFor(() => expect(api.previewCandidate).toHaveBeenLastCalledWith("p1", "job-1",
    { keep_current: [], edit_choices: { conclusion: "keep" } }));
  const apply = within(box).getByRole("button", { name: "반영" });
  await waitFor(() => expect(apply).toBeEnabled());
  await userEvent.click(apply);
  expect(handlers.onApply).toHaveBeenCalledWith({ keep_current: [], drop_edits: [], unhide: [] }, "e0");
});

it("다시 계산한 미리 보기가 실패하면 반영을 막는다 (리뷰 G5)", async () => {
  vi.mocked(api.previewCandidate).mockResolvedValueOnce(previewOf(current, candidate))
    .mockRejectedValueOnce(new Error("연결 끊김"));
  open();
  const box = await dialog();
  const bullets = await within(box).findByRole("group", { name: /본문 불릿/ });
  await userEvent.click(within(bullets).getByRole("radio", { name: "지금 문구 유지" }));
  expect(await within(box).findByRole("alert")).toHaveTextContent("비교 내용을 불러오지 못했습니다");
  expect(within(box).getByRole("button", { name: "반영" })).toBeDisabled();
});

it("늦게 도착한 이전 미리 보기 응답은 새 선택의 결과를 덮지 않는다 (리뷰 V9)", async () => {
  const replies: ((v: ReturnType<typeof previewOf>) => void)[] = [];
  vi.mocked(api.previewCandidate).mockResolvedValueOnce(previewOf(current, candidate))
    .mockImplementation(() => new Promise((res) => { replies.push(res); }));
  open();
  const box = await dialog();
  const bullets = await within(box).findByRole("group", { name: /본문 불릿/ });
  await userEvent.click(within(bullets).getByRole("radio", { name: "지금 문구 유지" }));
  await userEvent.click(within(bullets).getByRole("radio", { name: "새 문구 사용" }));
  await waitFor(() => expect(replies).toHaveLength(2));
  replies[1](previewOf(current, candidate, { keep_current: [], warnings: [{ slot: "bullets", message: "새 선택의 경고" } as never] }));
  expect(await within(box).findByText("새 선택의 경고")).toBeInTheDocument();
  replies[0](previewOf(current, candidate, { keep_current: ["bullets"], warnings: [{ slot: "bullets", message: "옛 선택의 경고" } as never] }));
  await new Promise((r) => setTimeout(r, 0));
  expect(within(box).queryByText("옛 선택의 경고")).toBeNull();
  expect(within(bullets).getByRole("radio", { name: "새 문구 사용" })).toBeChecked();
});

it("Tab은 라디오 묶음을 한 곳으로 보고, 제목에서는 고른 라디오로 가며 첫 묶음에서 Shift+Tab은 마지막으로 돈다 (리뷰 G3, G19, V10)", async () => {
  vi.mocked(api.previewCandidate).mockResolvedValue(previewOf(current, candidate));
  open();
  const box = await dialog();
  const bullets = await within(box).findByRole("group", { name: /본문 불릿/ });
  within(box).getByRole("heading", { name: /새 내용과 비교/ }).focus();
  await userEvent.tab();
  expect(document.activeElement).toBe(within(bullets).getByRole("radio", { name: "새 문구 사용" }));
  await userEvent.tab({ shift: true });
  expect(document.activeElement).toBe(within(box).getByRole("button", { name: "닫기" }));
  within(bullets).getByRole("radio", { name: "지금 문구 유지" }).focus();  // 고르지 않은 라디오도 그 묶음의 자리다
  await userEvent.tab({ shift: true });
  expect(document.activeElement).toBe(within(box).getByRole("button", { name: "닫기" }));
  // 가운데 묶음의 고르지 않은 라디오에서는 붙잡지 않는다(브라우저가 앞 묶음으로 옮긴다)
  const unit = within(box).getByRole("group", { name: /^결론 상자$/ });
  within(unit).getByRole("radio", { name: "지금 문구 유지" }).focus();
  await userEvent.tab({ shift: true });
  expect(document.activeElement).not.toBe(within(box).getByRole("button", { name: "닫기" }));
  expect(box.contains(document.activeElement)).toBe(true);
});

it("표시 상태: 기준 없음, 목록 길이 변화, 경고, 강조 삭제, 이미 같은 내용", async () => {
  vi.mocked(api.previewCandidate).mockResolvedValue(previewOf(current, candidate, {
    length_changed_units: ["bullets"], already_applied: true, removed_spans: 2,
    warnings: [{ slot: "bullets", message: "본문 불릿이 넘칩니다", needed_pt: 10, available_pt: 5 } as never] }));
  open();
  const box = await dialog();
  expect(await within(box).findByText(/반영 기록이 없어 직접 고친 문구를 표시하지 않습니다/)).toBeInTheDocument();
  expect(within(within(box).getByRole("group", { name: /본문 불릿/ })).getByText("새 내용의 항목 수와 순서가 다릅니다."))
    .toBeInTheDocument();
  expect(within(box).getByText("본문 불릿이 넘칩니다")).toBeInTheDocument();
  expect(within(box).getByText(/부분 강조 2개가 지워집니다/)).toBeInTheDocument();
  expect(within(box).getByText(/지금 내용과 같아 바뀌는 것이 없습니다/)).toBeInTheDocument();
});

it("내용이 없는 장은 지금 문구를 고를 수 없고 요소 수정 목록이 없다", async () => {
  vi.mocked(api.previewCandidate).mockResolvedValue(previewOf(null, candidate));
  open();
  const box = await dialog();
  const bullets = await within(box).findByRole("group", { name: /본문 불릿/ });
  expect(within(bullets).getByRole("radio", { name: "지금 문구 유지" })).toBeDisabled();
  expect(within(box).queryByRole("heading", { name: "위치와 서식 수정" })).toBeNull();
  expect(within(box).queryByText(/반영 기록이 없어/)).toBeNull();
});

it("묶음 실행 중이면 비교는 보이되 반영도 다시 생성도 막는다", async () => {
  vi.mocked(api.previewCandidate).mockResolvedValue(previewOf(current, candidate, { blocked_reasons: ["batch_active"] }));
  open();
  const box = await dialog();
  expect(await within(box).findByText(/장 생성 묶음이 진행 중이라 지금은 반영할 수 없습니다/)).toBeInTheDocument();
  expect(within(box).getByRole("button", { name: "반영" })).toBeDisabled();
  expect(within(box).queryByRole("button", { name: "현재 입력으로 다시 생성" })).toBeNull();
});

it("막힌 후보의 다시 생성은 비교 화면을 닫은 뒤 부른다 (동의 창이 앱 화면 안에 뜬다)", async () => {
  vi.mocked(api.previewCandidate).mockResolvedValue(previewOf(current, candidate, { blocked_reasons: ["sources_changed"] }));
  const order: string[] = [];
  open({ onClose: vi.fn(() => { order.push("close"); }), onRegenerate: vi.fn(() => { order.push("regenerate"); }) });
  const box = await dialog();
  await userEvent.click(await within(box).findByRole("button", { name: "현재 입력으로 다시 생성" }));
  expect(order).toEqual(["close", "regenerate"]);
});

it("직접 고친 문구 표시와 바뀌는 수는 선택을 따른다 (리뷰 V1, V2)", async () => {
  vi.mocked(api.previewCandidate).mockImplementation(async (_n, _j, body) => previewOf(current, candidate,
    { edited_units: ["bullets", "conclusion"], keep_current: body?.keep_current ?? ["bullets", "conclusion"] }));
  open();
  const box = await dialog();
  const bullets = await within(box).findByRole("group", { name: "본문 불릿 (직접 고친 문구)" });
  expect(within(box).getByRole("group", { name: "결론 상자 (직접 고친 문구)" })).toBeInTheDocument();
  expect(within(box).getByRole("group", { name: "각주" })).toBeInTheDocument();
  expect(within(box).queryByText(/새 문구로 바뀝니다/)).toBeNull();
  await userEvent.click(within(bullets).getByRole("radio", { name: "새 문구 사용" }));
  expect(await within(box).findByText("직접 고친 문구 1곳이 새 문구로 바뀝니다.")).toBeInTheDocument();
});

it("다른 곳 변경, 자리가 없어 사라지는 요소 수정, 차트 삭제를 알리고 사라지는 수정은 고를 수 없다 (리뷰 V4, V5, V6, G13)", async () => {
  vi.mocked(api.previewCandidate).mockResolvedValue(previewOf(current, candidate, {
    notices: ["deck_changed_elsewhere"], removed_edits: ["footnote", "conclusion"], drop_edits: ["conclusion"],
    removed_chart: true }));
  open();
  const box = await dialog();
  expect(await within(box).findByText("덱의 다른 부분이 바뀌었지만 이 장의 입력은 그대로입니다.")).toBeInTheDocument();
  const footnote = within(box).getByRole("group", { name: "각주의 위치와 서식 (숨김)" });
  expect(within(footnote).getByText("새 내용에 이 요소가 없어 반영하면 수정이 사라집니다.")).toBeInTheDocument();
  expect(within(footnote).getByRole("radio", { name: "유지" })).toBeDisabled();
  const conclusion = within(box).getByRole("group", { name: "결론 상자의 위치와 서식" });  // 지우기로 고른 열쇠는 자리가 있다
  expect(within(conclusion).getByRole("radio", { name: "유지" })).toBeEnabled();
  expect(within(conclusion).queryByText(/새 내용에 이 요소가 없어/)).toBeNull();
  expect(within(box).getByText("비교 차트가 지워집니다.")).toBeInTheDocument();
});

it("다시 생성을 열 수 없는 막힌 후보에는 갈 길을 적는다 (리뷰 G9)", async () => {
  vi.mocked(api.previewCandidate).mockResolvedValue(previewOf(current, candidate, { blocked_reasons: ["sources_changed"] }));
  render(<CandidateCompareDialog projectName="p1" jobId="job-1" title="1장 주제" candidateSlots={candidate}
    onApply={vi.fn()} onClose={vi.fn()} onStaleBase={vi.fn()} regenerateHint="편집 단계에서 다시 생성해 주세요." />);
  const box = await dialog();
  expect(await within(box).findByText("편집 단계에서 다시 생성해 주세요.")).toBeInTheDocument();
  expect(within(box).queryByRole("button", { name: "현재 입력으로 다시 생성" })).toBeNull();
});

it("닫은 뒤 도착한 미리 보기는 충돌 경로를 열지 않는다 (리뷰 G18)", async () => {
  let reply: (v: ReturnType<typeof previewOf>) => void = () => {};
  vi.mocked(api.previewCandidate).mockImplementation(() => new Promise((res) => { reply = res; }));
  const onStaleBase = vi.fn();
  const { unmount } = render(<CandidateCompareDialog projectName="p1" jobId="job-1" title="1장 주제" candidateSlots={candidate}
    onApply={vi.fn()} onClose={vi.fn()} onStaleBase={onStaleBase} />);
  await dialog();
  vi.spyOn(await import("../api/client"), "savedEtag").mockReturnValue('"다른 저장본"');
  unmount();
  reply(previewOf(current, candidate, { base_etag: "e9" }));
  await new Promise((r) => setTimeout(r, 0));
  expect(onStaleBase).not.toHaveBeenCalled();
});
