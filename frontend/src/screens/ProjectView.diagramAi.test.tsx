import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import fixture from "../../../backend/tests/fixtures/q3b-project.json";
import { revokeConsent } from "../api/aiGate";
import { resetEtags, type Deck } from "../api/client";
import { deferred, preset, project } from "../test/fixtures";
import { emptyUsage } from "../test/usage";
import { ProjectView } from "./ProjectView";

vi.mock("./AISettingsPanel", () => ({ AISettingsPanel: ({ disabled }: { disabled: boolean }) => <button disabled={disabled}>모델 변경 검사</button> }));
vi.mock("./NumericReviewPanel", () => ({ NumericReviewPanel: () => null }));

beforeEach(() => { revokeConsent(); resetEtags(); });
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
    if (url.endsWith("/generate/diagram") && init?.method === "POST") return pending.promise;
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
  expect(fetch.mock.calls.some(([url]) => String(url).endsWith("/generate/diagram"))).toBe(false);
  expect(screen.getByRole("button", { name: "모델 변경 검사" })).toBeEnabled();
  expect(screen.getByRole("dialog", { name: "도식 작성" }).contains(document.activeElement)).toBe(true);
});

it("AI 전송 승인 뒤 응답 대기 중에도 포커스는 살아 있는 도식 작성창에 돌아온다", async () => {
  const { pending, fetch } = await open();
  await userEvent.click(await screen.findByRole("button", { name: "전송에 동의하고 계속" }));
  await waitFor(() => expect(fetch.mock.calls.some(([url]) => String(url).endsWith("/generate/diagram"))).toBe(true));
  const dialog = screen.getByRole("dialog", { name: "도식 작성" });
  expect(screen.getByRole("button", { name: "AI 도식 초안 생성" })).toBeDisabled();
  expect(dialog.contains(document.activeElement)).toBe(true);
  await userEvent.tab();
  expect(dialog.contains(document.activeElement)).toBe(true);
  await act(async () => pending.resolve(new Response(JSON.stringify({ status: "format_error", diagram: null,
    raw_text: "synthetic invalid response", unverified_numbers: [], format_retried: false, usage: emptyUsage(),
    base_etag: '"base"', sources_fingerprint: "sources" }))));
});

it("도식 창을 닫아도 이미 보낸 요청이 끝날 때까지 모델과 화면 이동을 잠근다", async () => {
  const { pending, fetch } = await open();
  await userEvent.click(await screen.findByRole("button", { name: "전송에 동의하고 계속" }));
  await waitFor(() => expect(fetch.mock.calls.some(([url]) => String(url).endsWith("/generate/diagram"))).toBe(true));
  expect(screen.getByRole("button", { name: "모델 변경 검사" })).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: "변경 버리고 닫기" }));
  expect(screen.getByRole("button", { name: "모델 변경 검사" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "구조안" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "목록으로" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "도식 추가" })).toBeDisabled();
  const deck = fixture.deck as Deck;
  const slide = deck.slides.find(s => s.slots.template === "diagram")!;
  await act(async () => pending.resolve(new Response(JSON.stringify({ status: "ok",
    diagram: slide.slots.template === "diagram" ? slide.slots.diagram : null,
    raw_text: "", unverified_numbers: [], format_retried: false, usage: emptyUsage(), base_etag: '"base"', sources_fingerprint: "sources" }))));
  expect(screen.getByRole("button", { name: "모델 변경 검사" })).toBeEnabled();
  expect(screen.getByRole("button", { name: "도식 추가" })).toBeEnabled();
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});
