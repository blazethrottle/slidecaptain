import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import fixture from "../../../backend/tests/fixtures/q3b-project.json";
import { revokeConsent } from "../api/aiGate";
import { resetEtags, type Deck } from "../api/client";
import { defaultProgress, deferred, preset, project } from "../test/fixtures";
import { jobView } from "../test/jobs";
import { emptyUsage } from "../test/usage";
import { ProjectView } from "./ProjectView";

vi.mock("./AISettingsPanel", () => ({ AISettingsPanel: ({ disabled }: { disabled: boolean }) => <button disabled={disabled}>모델 변경 검사</button> }));
vi.mock("./NumericReviewPanel", () => ({ NumericReviewPanel: () => null }));

let jobExtra: Record<string, unknown> = {};  // 작업 조회 응답에 더할 칸(생성이 끝난 뒤의 조회 사유 등)
beforeEach(() => { revokeConsent(); resetEtags(); jobExtra = {}; });
afterEach(() => { vi.unstubAllGlobals(); });
async function open() {
  const pending = deferred<Response>();
  const fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.endsWith("/deck")) return new Response(JSON.stringify(fixture.deck), { headers: { ETag: '"base"' } });
    if (url.endsWith("/sources")) return new Response("[]");
    if (url === "/api/preset") return new Response(JSON.stringify(preset));
    if (url === "/api/render-plan") return new Response(JSON.stringify(fixture.render_plan));
    if (url === "/api/status") return new Response(JSON.stringify({ provider: "chatgpt", model: "selected-model", selection_id: "selected",
      checked_at: "", login: { logged_in: true } }));
    // D2b-5b: 도식 생성은 작업 API로 등록하고 조회한다. 조회 응답은 시험이 생성 결과로 풀어 준다
    if (url === "/api/jobs/active") return new Response(JSON.stringify({ active: null, ledger_available: true }));
    if (url.endsWith("/progress")) return new Response(JSON.stringify(defaultProgress()));  // D3a-3 리뷰 R6
    if (url.endsWith("/jobs") && init?.method === "POST") return new Response(JSON.stringify(
      jobView("diagram", { state: "running", candidate_status: "none" })), { status: 202 });
    if (url.endsWith("/jobs")) return new Response("[]");
    if (url.endsWith("/jobs/job-1")) return pending.promise.then(async (r) => new Response(JSON.stringify(
      jobView("diagram", { result: await r.json(), ...jobExtra }))));
    if (url.endsWith("/jobs/job-1/candidate")) return new Response(JSON.stringify(jobView("diagram")));
    throw new Error(`unexpected ${url}`);
  });
  vi.stubGlobal("fetch", fetch);
  render(<ProjectView project={project} onBack={vi.fn()} />);
  await userEvent.click(await screen.findByRole("button", { name: "편집" }));
  await userEvent.click(await screen.findByRole("button", { name: "도식 추가" }));
  fireEvent.change(screen.getByLabelText("도식 제목"), { target: { value: "AI 도식 요청" } });
  await userEvent.selectOptions(screen.getByLabelText("도식 장 보고 역할"), "evidence");
  await userEvent.click(screen.getByLabelText("보고 계획 주장 claim"));
  await userEvent.click(screen.getByRole("button", { name: "AI 도식 초안 생성" }));
  return { fetch, pending };
}

it("도식 생성 동의창은 정확한 전송 범위를 알리고 포커스를 유지하며 취소 뒤 입력을 보존한다", async () => {
  const { fetch } = await open();
  const consent = await screen.findByRole("dialog", { name: "AI 에게 자료를 보냅니다" });
  expect(within(consent).getByText(/도식 초안 생성/)).toHaveTextContent(/선택한 주장.*등록된 근거 발췌.*보고 정보.*지시/);
  const confirm = within(consent).getByRole("button", { name: "전송에 동의하고 계속" });
  const cancel = within(consent).getByRole("button", { name: "취소" });
  expect(confirm).toHaveFocus();
  await userEvent.tab({ shift: true }); expect(cancel).toHaveFocus();
  await userEvent.tab(); expect(confirm).toHaveFocus();
  expect(screen.getByRole("button", { name: "모델 변경 검사" })).toBeDisabled();
  await userEvent.click(cancel);
  expect(await screen.findByText(/전송을 취소했습니다/)).toBeInTheDocument();
  expect(screen.getByLabelText("도식 제목")).toHaveValue("AI 도식 요청");
  expect(fetch.mock.calls.some(([url, init]) => String(url).endsWith("/jobs") && init?.method === "POST")).toBe(false);
  expect(screen.getByRole("button", { name: "모델 변경 검사" })).toBeEnabled();
  expect(screen.getByRole("dialog", { name: "도식 작성" }).contains(document.activeElement)).toBe(true);
});

it("AI 전송 승인 뒤 응답 대기 중에도 포커스는 살아 있는 도식 작성창에 돌아온다", async () => {
  const { pending, fetch } = await open();
  await userEvent.click(await screen.findByRole("button", { name: "전송에 동의하고 계속" }));
  await waitFor(() => expect(fetch.mock.calls.some(([url, init]) => String(url).endsWith("/jobs") && init?.method === "POST")).toBe(true));
  const dialog = screen.getByRole("dialog", { name: "도식 작성" });
  expect(screen.getByRole("button", { name: "AI 도식 초안 생성" })).toBeDisabled();
  expect(dialog.contains(document.activeElement)).toBe(true);
  await userEvent.tab();
  expect(dialog.contains(document.activeElement)).toBe(true);
  await act(async () => pending.resolve(new Response(JSON.stringify({ status: "format_error", diagram: null,
    raw_text: "synthetic invalid response", unverified_numbers: [], format_retried: false, usage: emptyUsage(),
    base_etag: '"base"', sources_fingerprint: "sources" }))));
});

// 다시 씀 (D3a-5 리뷰 R10): 작성 창을 닫은 뒤 남은 요청은 후보형 작업이라 화면 이동은 막지 않는다(계획 4.4 첫 행).
// 모델 변경과 도식 추가는 요청이 끝날 때까지 잠근다
it("도식 창을 닫아도 이미 보낸 요청이 끝날 때까지 모델 변경을 잠그고, 화면 이동은 막지 않는다", async () => {
  const { pending, fetch } = await open();
  await userEvent.click(await screen.findByRole("button", { name: "전송에 동의하고 계속" }));
  await waitFor(() => expect(fetch.mock.calls.some(([url, init]) => String(url).endsWith("/jobs") && init?.method === "POST")).toBe(true));
  expect(screen.getByRole("button", { name: "모델 변경 검사" })).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: "변경 버리고 닫기" }));
  expect(screen.getByRole("button", { name: "모델 변경 검사" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "구성" })).toBeEnabled();
  expect(screen.getByRole("button", { name: "목록으로" })).toBeEnabled();
  expect(screen.getByRole("button", { name: "도식 추가" })).toBeDisabled();
  // 실제로 떠날 수 있다 (D3a-β 재리뷰 F6). 버튼이 열려 있어도 이탈이 거절되면 편집에 머문다
  await userEvent.click(screen.getByRole("button", { name: "구성" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "구성" })).toHaveAttribute("aria-current", "step"));
  await userEvent.click(screen.getByRole("button", { name: "편집" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "편집" })).toHaveAttribute("aria-current", "step"));
  const deck = fixture.deck as Deck;
  const slide = deck.slides.find(s => s.slots.template === "diagram")!;
  await act(async () => pending.resolve(new Response(JSON.stringify({ status: "ok",
    diagram: slide.slots.template === "diagram" ? slide.slots.diagram : null,
    raw_text: "", unverified_numbers: [], format_retried: false, usage: emptyUsage(), base_etag: '"base"', sources_fingerprint: "sources" }))));
  expect(screen.getByRole("button", { name: "모델 변경 검사" })).toBeEnabled();
  expect(screen.getByRole("button", { name: "도식 추가" })).toBeEnabled();
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});


// C1 W2 리뷰 W2R-01: 생성이 held로 끝난 직후 다른 곳이 덱을 바꾸면 조회 사유가 도식 해시의 사유(story_plan_changed 등)일 수 있다.
// 작성 창은 W2 이전처럼 덱 변경으로 보고 412로 멈추고 후보를 버린다
it.each(["story_plan_changed", "chapter_changed", "deck_changed_elsewhere"])(
  "생성 직후 조회 사유가 %s이면 후보를 보이지 않고 충돌로 멈춘다", async (reason) => {
  jobExtra = { stale_reasons: [reason] };
  const { pending, fetch } = await open();
  await userEvent.click(await screen.findByRole("button", { name: "전송에 동의하고 계속" }));
  await waitFor(() => expect(fetch.mock.calls.some(([url, init]) => String(url).endsWith("/jobs") && init?.method === "POST")).toBe(true));
  const deck = fixture.deck as Deck;
  const slide = deck.slides.find(s => s.slots.template === "diagram")!;
  await act(async () => pending.resolve(new Response(JSON.stringify({ status: "ok",
    diagram: slide.slots.template === "diagram" ? slide.slots.diagram : null,
    raw_text: "", unverified_numbers: [], format_retried: false, usage: emptyUsage(), base_etag: '"base"', sources_fingerprint: "sources" }))));
  await waitFor(() => expect(fetch.mock.calls.some(([url, init]) => String(url).endsWith("/jobs/job-1/candidate")
    && JSON.parse(String(init?.body)).action === "dismissed")).toBe(true));
  expect(screen.queryByRole("region", { name: "AI 도식 후보 검토" })).not.toBeInTheDocument();
});
