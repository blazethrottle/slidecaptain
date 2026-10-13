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

it("키보드만으로 단위를 고르고 반영하며, 반영 중에는 Escape로 닫지 않는다", async () => {
  vi.mocked(api.previewCandidate).mockImplementation(async (_n, _j, body) => previewOf(current, candidate,
    { keep_current: body?.keep_current ?? [] }));
  let finish: () => void = () => {};
  const handlers = open({ onApply: vi.fn(() => new Promise<void>((res) => { finish = res; })) });
  const box = await dialog();
  const bullets = await within(box).findByRole("group", { name: /본문 불릿/ });
  within(bullets).getByRole("radio", { name: "지금 문구 유지" }).focus();
  await userEvent.keyboard(" ");
  await waitFor(() => expect(api.previewCandidate).toHaveBeenLastCalledWith("p1", "job-1",
    { keep_current: ["bullets"], drop_edits: [], unhide: [] }));
  const apply = within(box).getByRole("button", { name: "반영" });
  await waitFor(() => expect(apply).toBeEnabled());
  apply.focus();
  await userEvent.keyboard("{Enter}");
  expect(handlers.onApply).toHaveBeenCalledWith({ keep_current: ["bullets"], drop_edits: [], unhide: [] });
  await userEvent.keyboard("{Escape}");
  expect(handlers.onClose).not.toHaveBeenCalled();
  finish();
});

it("요소 수정은 유지, 숨김만 풀기, 지우기를 고르고 그 선택이 요청에 실린다", async () => {
  vi.mocked(api.previewCandidate).mockImplementation(async (_n, _j, body) => previewOf(current, candidate,
    { drop_edits: body?.drop_edits ?? [], unhide: body?.unhide ?? [] }));
  const handlers = open();
  const box = await dialog();
  const conclusion = await within(box).findByRole("group", { name: "결론 상자의 위치와 서식" });
  const footnote = within(box).getByRole("group", { name: "각주의 위치와 서식 (숨김)" });
  expect(within(conclusion).queryByRole("radio", { name: "숨김만 풀기" })).toBeNull();
  await userEvent.click(within(conclusion).getByRole("radio", { name: "지우기" }));
  await userEvent.click(within(footnote).getByRole("radio", { name: "숨김만 풀기" }));
  await waitFor(() => expect(api.previewCandidate).toHaveBeenLastCalledWith("p1", "job-1",
    { keep_current: [], drop_edits: ["conclusion"], unhide: ["footnote"] }));
  await userEvent.click(within(box).getByRole("button", { name: "반영" }));
  expect(handlers.onApply).toHaveBeenCalledWith({ keep_current: [], drop_edits: ["conclusion"], unhide: ["footnote"] });
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
