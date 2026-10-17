// 작성 창을 닫은 뒤 남은 도식 AI 후보를 복구 화면에서 다시 연다 (C1 계획 W2-b, SC-02). fetch만 바꿔 요청 계층, ProjectView의
// 한 번 쓰는 작업 ID, 편집 화면의 작성 창 열기, 처분 응답 대기, 반영 뒤 자동 저장의 If-Match를 실제로 지난다
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import fixture from "../../../backend/tests/fixtures/q3b-project.json";
import { revokeConsent } from "../api/aiGate";
import { resetEtags, type Deck, type JobView, type RenderPlan } from "../api/client";
import { defaultProgress, preset, project } from "../test/fixtures";
import { jobView } from "../test/jobs";
import { emptyUsage } from "../test/usage";
import { ProjectView } from "./ProjectView";

vi.mock("./AISettingsPanel", () => ({ AISettingsPanel: () => null }));
vi.mock("./NumericReviewPanel", () => ({ NumericReviewPanel: () => null }));

const deck = fixture.deck as Deck;
const flow = deck.slides.find((s) => s.chapter_id === "synthetic-flow")!;
const diagram = flow.slots.template === "diagram" ? flow.slots.diagram : null;
const PARAMS = { mode: "create", chapter_id: "new-diagram", topic: "다시 연 도식", role: "evidence", claim_ids: ["claim"],
  instructions: "원문의 관계 보존" };

function diagramJob(over: Partial<JobView> = {}): JobView {
  return jobView("diagram", { id: "job-d1", target: "new-diagram", params: PARAMS, relevance_hash: "d1:a|",
    result: { status: "ok", diagram, raw_text: "", unverified_numbers: [], format_retried: false, usage: emptyUsage(),
      base_etag: '"base"', sources_fingerprint: "sources" }, ...over });
}

type Server = { job: JobView; settleStatus: number; settles: { action: string }[]; puts: { ifMatch: string | null; deck: Deck }[];
  changes: { ifMatch: string | null; body: { candidate: Deck; acknowledged_loss_ids: string[] } }[]; reconcileStatus?: number;
  deckEtag?: string; settleGate?: Promise<void>; jobGate?: Promise<void>; deckReadGate?: Promise<void>; deckReadStatus?: number };

// 측정은 덱의 도식 장마다 고정 렌더 계획의 도식 슬라이드를 복사해 돌려준다(작성 창의 확인이 새 장의 도식을 찾는다)
function planFor(body: Deck): RenderPlan {
  const plan = fixture.render_plan as unknown as RenderPlan;
  const template = plan.slides.find((s) => s.chapter_id === "synthetic-flow")!;
  const extra = body.structure.chapters.filter((c) => c.template === "diagram" && !plan.slides.some((s) => s.chapter_id === c.id))
    .map((c) => ({ ...template, chapter_id: c.id }));
  return { ...plan, slides: [...plan.slides, ...extra] };
}

function serve(server: Server) {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const headers = new Headers(init?.headers);
    if (url.split("?")[0].endsWith("/deck") && init?.method === "PUT") {  // 저장은 스냅샷 질의 문자열을 붙인다
      server.puts.push({ ifMatch: headers.get("If-Match"), deck: JSON.parse(init.body as string) });
      return new Response(JSON.stringify({ ok: true }), { headers: { ETag: `"after-${server.puts.length}"` } });
    }
    // 기존 도식 교체는 문서 변경 미리 보기와 손실 확인 뒤 적용으로 반영한다(W2 리뷰 E7을 옮겨 옴)
    if (url.endsWith("/document-changes/basis")) {
      return new Response(JSON.stringify({ base_etag: '"base"', sources_fingerprint: "sources" }), { headers: { ETag: '"base"' } });
    }
    if (url.endsWith("/document-changes/preview")) {
      const body = JSON.parse(init!.body as string);
      return new Response(JSON.stringify({ rule_version: "document-change-v1", reason: "document_replacement", base_fingerprint: "b",
        sources_fingerprint: "sources", candidate_fingerprint: "c", candidate: body.candidate, notice: "교체 전후를 확인해 주세요.",
        losses: [{ id: "loss-1", path: "slides.synthetic-flow.diagram", before: {}, after: {} }], confirmation_token: "tok" }));
    }
    if (url.endsWith("/document-changes/apply")) {
      const body = JSON.parse(init!.body as string);
      server.changes.push({ ifMatch: headers.get("If-Match"), body });
      return new Response(JSON.stringify(body.candidate), { headers: { ETag: '"after-apply"' } });
    }
    if (url.endsWith("/deck")) {
      if (server.deckReadGate) await server.deckReadGate;
      if (server.deckReadStatus) return new Response(JSON.stringify({ detail: "읽기 실패" }), { status: server.deckReadStatus });
      return new Response(JSON.stringify(deck), { headers: { ETag: server.deckEtag ?? '"base"' } });
    }
    if (url.endsWith("/sources")) return new Response("[]");
    if (url.endsWith("/snapshots") || url.endsWith("/drafts")) return new Response("[]");
    if (url === "/api/preset") return new Response(JSON.stringify(preset));
    if (url.endsWith("/render-plan")) return new Response(JSON.stringify(planFor(JSON.parse(init!.body as string))));
    if (url.endsWith("/story-plan/diagram")) {
      if (server.reconcileStatus) {  // 다른 탭이 그사이 저장했다
        return new Response(JSON.stringify({ detail: "다른 창이나 프로그램에서 먼저 저장되었습니다." }), { status: server.reconcileStatus });
      }
      return new Response(JSON.stringify(JSON.parse(init!.body as string).deck));
    }
    if (url === "/api/status") return new Response(JSON.stringify({ provider: "chatgpt", model: "m", selection_id: "s",
      checked_at: "", login: { logged_in: true } }));
    if (url === "/api/jobs/active") return new Response(JSON.stringify({ active: null, ledger_available: true }));
    if (url.endsWith("/progress")) return new Response(JSON.stringify(defaultProgress()));
    if (url.endsWith("/jobs/job-d1/candidate")) {
      server.settles.push(JSON.parse(init!.body as string));
      if (server.settleGate) await server.settleGate;
      if (server.settleStatus !== 200) {
        return new Response(JSON.stringify({ detail: "처분할 결과 후보가 없거나 이미 처분했습니다." }), { status: server.settleStatus });
      }
      server.job = { ...server.job, candidate_status: "applied" };
      return new Response(JSON.stringify(server.job));
    }
    if (url.endsWith("/jobs/job-d1")) {
      if (server.jobGate) await server.jobGate;
      return new Response(JSON.stringify(server.job));
    }
    if (url.endsWith("/jobs")) return new Response(JSON.stringify(server.job.candidate_status === "held"
      || server.job.candidate_status === "stale" ? [server.job] : []));
    throw new Error(`unexpected ${url}`);
  }));
}

async function openRecovery(server: Server) {
  serve(server);
  render(<ProjectView project={project} onBack={vi.fn()} />);
  await userEvent.click(await screen.findByRole("button", { name: "스냅샷 복구" }));
  await screen.findByRole("heading", { name: "AI 결과 후보" });
}

async function reopen(server: Server) {
  await openRecovery(server);
  await userEvent.click(await screen.findByRole("button", { name: "도식 작성 창에서 열기" }));
  return screen.findByRole("dialog");
}

const newServer = (over: Partial<Server> = {}): Server => ({ job: diagramJob(), settleStatus: 200, settles: [], puts: [],
  changes: [], ...over });

beforeEach(() => { revokeConsent(); resetEtags(); });
afterEach(() => { vi.unstubAllGlobals(); });

// 회귀 RED: 지금 코드는 작성 창을 닫은 뒤 도착한 도식 후보를 앱 안에서 다시 열 길이 없다(SC-02)
it("복구 화면에서 도식 후보를 작성 창과 함께 열고, 여는 동안 처분하지 않는다", async () => {
  const server = newServer();
  const dialog = await reopen(server);
  expect(within(dialog).getByRole("region", { name: "AI 도식 후보 검토" })).toBeInTheDocument();
  expect(within(dialog).getByLabelText("도식 제목")).toHaveValue("다시 연 도식");
  expect(within(dialog).getByLabelText("AI 도식 지시사항")).toHaveValue("원문의 관계 보존");
  expect(within(dialog).getByText(/입력을 고치면 이 후보를 버립니다/)).toBeInTheDocument();
  // 초점은 불러오기 버튼이다. 제목 칸이면 첫 입력이 후보를 버린다(W2 리뷰 W2R-02). 안내는 버튼의 설명으로 읽힌다
  const load = within(dialog).getByRole("button", { name: "작성 폼에 불러오기" });
  await waitFor(() => expect(load).toHaveFocus());
  expect(load).toHaveAccessibleDescription(/입력을 고치면 이 후보를 버립니다/);
  expect(screen.getByRole("button", { name: "편집" })).toHaveAttribute("aria-current", "step");
  expect(server.settles).toEqual([]);
});

// C2 계획 4.2: 불러오기는 처분하지 않는다. 새 도식은 적용할 때 처분 응답을 먼저 기다리고, 처분이 성공해야 덱에 넣는다
// (C2 계획 리뷰 PR-01: 반영 뒤 처분이 실패하면 같은 후보를 다시 열어 두 번 넣을 수 있다)
it("다시 연 후보를 불러와 확인하고 적용하면 적용할 때 applied로 처분하고 다음 자동 저장이 그 도식을 기준 저장본에 저장한다", async () => {
  const server = newServer();
  const dialog = await reopen(server);
  await userEvent.click(within(dialog).getByRole("button", { name: "작성 폼에 불러오기" }));
  expect(await within(dialog).findByText(/AI 후보의 항목과 관계를 작성 폼에 불러왔습니다/)).toBeInTheDocument();
  expect(server.settles).toEqual([]);
  await userEvent.click(within(dialog).getByRole("button", { name: "입력과 배치 확인" }));
  const apply = within(dialog).getByRole("button", { name: "도식 적용" });
  await waitFor(() => expect(apply).toBeEnabled());
  expect(server.settles).toEqual([]);
  await userEvent.click(apply);
  await waitFor(() => expect(server.settles).toEqual([{ action: "applied" }]));
  await waitFor(() => expect(server.puts).toHaveLength(1), { timeout: 4000 });
  expect(server.puts[0].ifMatch?.replace(/"/g, "")).toBe("base");
  expect(server.puts[0].deck.structure.chapters.map((c) => c.id)).toContain("new-diagram");
  const saved = server.puts[0].deck.slides.find((s) => s.chapter_id === "new-diagram")!;
  expect(saved.slots.template === "diagram" && saved.slots.diagram.nodes.map((n) => n.content))
    .toEqual(diagram!.nodes.map((n) => n.content));
});

it("불러오기 전에 다른 곳이 먼저 처분했으면 불러오지 않고 알린다", async () => {
  const server = newServer();
  const dialog = await reopen(server);
  server.job = { ...server.job, candidate_status: "dismissed" };  // 다른 탭이 버렸다
  await userEvent.click(within(dialog).getByRole("button", { name: "작성 폼에 불러오기" }));
  expect(await within(dialog).findByText(/다른 곳에서 이미 처리한 후보입니다/)).toBeInTheDocument();
  expect(within(dialog).queryByText(/AI 후보의 항목과 관계를 작성 폼에 불러왔습니다/)).not.toBeInTheDocument();
  expect(within(dialog).queryByRole("region", { name: "AI 도식 후보 검토" })).not.toBeInTheDocument();
  expect(server.settles).toEqual([]);
});

async function loadAndCheck(dialog: HTMLElement) {
  await userEvent.click(within(dialog).getByRole("button", { name: "작성 폼에 불러오기" }));
  await within(dialog).findByText(/AI 후보의 항목과 관계를 작성 폼에 불러왔습니다/);
  await userEvent.click(within(dialog).getByRole("button", { name: "입력과 배치 확인" }));
  const apply = within(dialog).getByRole("button", { name: "도식 적용" });
  await waitFor(() => expect(apply).toBeEnabled());
  return apply;
}

it.each([
  [409, /다른 곳에서 이미 처리한 후보입니다/],
  [500, /AI 후보 처리를 기록하지 못해 반영하지 않았습니다/],
])("적용할 때 처분이 %s이면 덱에 넣지 않고 알린다", async (status, message) => {
  const server = newServer({ settleStatus: status });
  const dialog = await reopen(server);
  const apply = await loadAndCheck(dialog);
  await userEvent.click(apply);
  expect(await within(dialog).findByText(message)).toBeInTheDocument();
  await new Promise((r) => setTimeout(r, 1500));  // 자동 저장(1.2초)이 돌 시간
  expect(server.puts).toEqual([]);
  expect(screen.getByRole("dialog")).toBeInTheDocument();
});

// C2 W2 리뷰 W2R-01: 확인한 뒤 반영하기 전에 다른 탭이 저장하면, 지금 코드는 처분부터 성공시켜 후보가 사라지고 자동 저장은
// 412로 끝나 덱에 도식이 없다. 처분 전에 서버 저장본이 이 탭이 아는 것과 같은지 본다
it("확인한 뒤 다른 탭이 저장했으면 처분하지 않고 충돌로 알리며 후보가 남는다", async () => {
  const server = newServer();
  const dialog = await reopen(server);
  const apply = await loadAndCheck(dialog);
  server.deckEtag = '"other-tab-save"';
  await userEvent.click(apply);
  expect(await screen.findAllByText(/다른 창이나 프로그램에서 먼저 저장되었습니다/)).not.toHaveLength(0);
  // 작성 창은 막히고 편집 화면도 충돌 상태다(머리 표시). 안내 문구만으로는 둘을 구별하지 못한다 (C2 묶음 리뷰 BR-03)
  expect(within(dialog).getByRole("button", { name: "도식 적용" })).toBeDisabled();
  expect(await screen.findByLabelText("저장 충돌")).toBeInTheDocument();
  await new Promise((r) => setTimeout(r, 1500));
  expect(server.settles).toEqual([]);
  expect(server.puts).toEqual([]);
  expect(server.job.candidate_status).toBe("held");
});

it("처분을 기다리는 동안 다른 탭이 저장했으면 덱에 넣지 않고 충돌로 알린다", async () => {
  let open!: () => void;
  const server = newServer({ settleGate: new Promise<void>((r) => { open = r; }) });
  const dialog = await reopen(server);
  const apply = await loadAndCheck(dialog);
  await userEvent.click(apply);
  await waitFor(() => expect(server.settles).toEqual([{ action: "applied" }]));
  server.deckEtag = '"other-tab-save"';
  open();
  expect(await screen.findAllByText(/다른 창이나 프로그램에서 먼저 저장되었습니다/)).not.toHaveLength(0);
  await new Promise((r) => setTimeout(r, 1500));
  expect(server.puts).toEqual([]);
});

// C2 묶음 리뷰 BR-01: 처분 뒤의 저장본 확인이 끝날 때까지 적용과 닫기를 잠근다. 그 사이 닫으면 후보는 applied인데 덱에는
// 도식이 없었다
it("처분 뒤 저장본을 확인하는 동안 적용과 닫기가 잠기고, 확인이 끝나면 반영한다", async () => {
  let openSettle!: () => void;
  let openRead!: () => void;
  const server = newServer({ settleGate: new Promise<void>((r) => { openSettle = r; }) });
  const dialog = await reopen(server);
  const apply = await loadAndCheck(dialog);
  await userEvent.click(apply);
  await waitFor(() => expect(server.settles).toEqual([{ action: "applied" }]));
  server.deckReadGate = new Promise<void>((r) => { openRead = r; });
  openSettle();
  await new Promise((r) => setTimeout(r, 50));
  expect(within(dialog).getByRole("button", { name: "도식 적용" })).toBeDisabled();
  expect(within(dialog).getByRole("button", { name: "변경 버리고 닫기" })).toBeDisabled();
  server.deckReadGate = undefined;
  openRead();
  await waitFor(() => expect(server.puts).toHaveLength(1), { timeout: 4000 });
});

// C2 확인 리뷰 FC-03: 처분 뒤 저장본 확인이 실패하면 반영한다. 이미 처분했으므로 막으면 후보만 사라진다(BR-02의 정책)
it("처분 뒤 저장본 확인이 실패해도 반영하고 작성 창을 닫는다", async () => {
  let openSettle!: () => void;
  const server = newServer({ settleGate: new Promise<void>((r) => { openSettle = r; }) });
  const dialog = await reopen(server);
  const apply = await loadAndCheck(dialog);
  await userEvent.click(apply);
  await waitFor(() => expect(server.settles).toEqual([{ action: "applied" }]));
  server.deckReadStatus = 500;  // 모든 GET /deck에 걸리므로 처분 응답 직전에 건다
  openSettle();
  await waitFor(() => expect(server.puts).toHaveLength(1), { timeout: 4000 });
  server.deckReadStatus = undefined;
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

// C2 묶음 리뷰 BR-02: 처분 전 저장본 확인이 실패하면 처분하지 않는다. 확인 없이 처분하면 W2R-01과 같은 결과가 될 수 있다
it("처분 전 저장본 확인이 실패하면 처분하지 않고 다시 누르게 한다", async () => {
  const server = newServer();
  const dialog = await reopen(server);
  const apply = await loadAndCheck(dialog);
  server.deckReadStatus = 500;
  await userEvent.click(apply);
  expect(await within(dialog).findByText(/저장본을 확인하지 못해 반영하지 않았습니다/)).toBeInTheDocument();
  expect(server.settles).toEqual([]);
  expect(server.job.candidate_status).toBe("held");
  server.deckReadStatus = undefined;
  await userEvent.click(within(dialog).getByRole("button", { name: "도식 적용" }));
  await waitFor(() => expect(server.settles).toEqual([{ action: "applied" }]));
});

// C1 묶음 리뷰 BR-04: 불러온 뒤 다른 탭이 저장해 확인이 412로 막히면, 지금 코드는 후보를 이미 applied로 처분해 잃는다
it("불러온 뒤 다른 탭의 저장으로 확인이 412이면 처분하지 않고 후보가 복구 목록에 남는다", async () => {
  const server = newServer();
  const dialog = await reopen(server);
  await userEvent.click(within(dialog).getByRole("button", { name: "작성 폼에 불러오기" }));
  await within(dialog).findByText(/AI 후보의 항목과 관계를 작성 폼에 불러왔습니다/);
  server.reconcileStatus = 412;
  await userEvent.click(within(dialog).getByRole("button", { name: "입력과 배치 확인" }));
  expect(await within(dialog).findByText("다른 창이나 프로그램에서 먼저 저장되었습니다.")).toBeInTheDocument();
  expect(server.settles).toEqual([]);
  expect(server.job.candidate_status).toBe("held");
});

it("불러온 뒤 반영하지 않고 닫으면 처분하지 않는다", async () => {
  const server = newServer();
  const dialog = await reopen(server);
  await userEvent.click(within(dialog).getByRole("button", { name: "작성 폼에 불러오기" }));
  await within(dialog).findByText(/AI 후보의 항목과 관계를 작성 폼에 불러왔습니다/);
  await userEvent.click(within(dialog).getByRole("button", { name: "변경 버리고 닫기" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(server.settles).toEqual([]);
});

it("다시 연 창을 닫은 뒤 편집 화면이 다시 마운트되어도 작성 창이 다시 열리지 않는다", async () => {
  const server = newServer();
  const dialog = await reopen(server);
  await userEvent.click(within(dialog).getByRole("button", { name: "변경 버리고 닫기" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  await userEvent.click(screen.getByRole("button", { name: "구성" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "구성" })).toHaveAttribute("aria-current", "step"));
  await userEvent.click(screen.getByRole("button", { name: "편집" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "편집" })).toHaveAttribute("aria-current", "step"));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

// C2 W2 리뷰 W2R-05: 다시 열기 행을 읽는 동안 사용자가 다른 단계로 가면 마음을 바꾼 것이다. 나중에 편집 단계로 돌아와도
// 작성 창을 열지 않는다(같은 편집 단계 안의 다시 마운트만 이어 읽는다, W2R-10)
it("다시 열기 응답 전에 다른 단계로 가면 나중에 편집 단계로 돌아와도 작성 창을 열지 않는다", async () => {
  let release!: () => void;
  const server = newServer({ jobGate: new Promise<void>((r) => { release = r; }) });
  await openRecovery(server);
  await userEvent.click(await screen.findByRole("button", { name: "도식 작성 창에서 열기" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "편집" })).toHaveAttribute("aria-current", "step"));
  await userEvent.click(screen.getByRole("button", { name: "구성" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "구성" })).toHaveAttribute("aria-current", "step"));
  release();
  server.jobGate = undefined;
  await userEvent.click(screen.getByRole("button", { name: "편집" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "편집" })).toHaveAttribute("aria-current", "step"));
  await new Promise((r) => setTimeout(r, 300));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

// 옮기는 사이 다른 탭이 이 후보를 처분했으면(편집 화면이 다시 읽은 행이 applied) 작성 창을 열지 않고 안내한다
it("옮기는 사이 다른 곳이 처분한 후보는 작성 창을 열지 않고 안내한다", async () => {
  const server = newServer();
  await openRecovery(server);
  const open = await screen.findByRole("button", { name: "도식 작성 창에서 열기" });
  server.job = { ...server.job, candidate_status: "applied" };
  await userEvent.click(open);
  expect(await screen.findByText("이 도식 후보를 열지 못했습니다. 복구 화면에서 다시 확인해 주세요.")).toBeInTheDocument();
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

it.each([
  ["생성 도중 덱이 바뀐 후보", { candidate_status: "stale" as const, stale_reasons: ["deck_changed" as const] }, /^작성 창에서 열 수 없습니다/],
  ["주장이 바뀐 후보", { stale_reasons: ["story_plan_changed" as const] }, /^작성 창에서 열 수 없습니다/],
  ["자료가 바뀐 후보", { stale_reasons: ["sources_changed" as const] }, /^작성 창에서 열 수 없습니다/],
  ["해시가 없는 옛 후보", { relevance_hash: null }, /이전 버전에서 만든 도식 후보/],
])("%s는 열 수 없고 이유를 보인다", async (_name, over, reason) => {
  await openRecovery(newServer({ job: diagramJob(over) }));
  expect(await screen.findByText(reason)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "도식 작성 창에서 열기" })).not.toBeInTheDocument();
});

// 도식의 chapter_changed는 교체할 도식 장의 정의, 슬라이드, 구성 계획 연결이 바뀐 경우다. 장 후보용 문구("주제나 결론")로
// 부르지 않는다 (C1 W2 리뷰 W2R-09, C2 계획 4.3 (23), 리뷰 PR-20)
it("교체 대상이 바뀐 도식 후보는 도식에 맞는 이유를 보인다", async () => {
  await openRecovery(newServer({ job: diagramJob({ target: "synthetic-flow", stale_reasons: ["chapter_changed"],
    base_etag: '"aaaaaaaa"', current_etag: '"bbbbbbbb"',
    params: { ...PARAMS, mode: "replace", chapter_id: "synthetic-flow" } }) }));
  expect(await screen.findByText(/교체할 도식 장의 제목, 역할, 연결한 주장이나 도식 내용이 바뀌었습니다/)).toBeInTheDocument();
  expect(screen.queryByText(/이 장의 주제나 결론이 바뀌었습니다/)).not.toBeInTheDocument();
});

it("다른 곳만 바뀐 후보(알림)는 열 수 있다", async () => {
  await openRecovery(newServer({ job: diagramJob({ stale_reasons: ["deck_changed_elsewhere"] }) }));
  expect(await screen.findByRole("button", { name: "도식 작성 창에서 열기" })).toBeInTheDocument();
});


it("새 도식 후보 행은 요청의 제목으로 부른다", async () => {
  await openRecovery(newServer());
  expect(await screen.findByText(/도식 \(새 도식: 다시 연 도식\)/)).toBeInTheDocument();
});

it("다시 연 창에서 입력을 고치면 그 후보를 버리고 복구 목록에서 빠진다", async () => {
  const server = newServer();
  const dialog = await reopen(server);
  await userEvent.type(within(dialog).getByLabelText("도식 제목"), "x");
  await waitFor(() => expect(server.settles).toEqual([{ action: "dismissed" }]));
  expect(within(dialog).queryByRole("region", { name: "AI 도식 후보 검토" })).not.toBeInTheDocument();
});

// 교체 후보: 시작값은 지금 덱의 연결에 요청의 제목이고, 불러온 뒤 손실 확인을 거쳐 문서 변경 적용으로 반영한다(계획 5절 W2-b)
it("다시 연 교체 후보는 요청 제목으로 시작하고 손실 확인 뒤 문서 변경 적용으로 반영된다", async () => {
  const changed = structuredClone(diagram!);
  changed.nodes[0].content = "AI 교체 후보 항목";
  const job = diagramJob({ target: "synthetic-flow", relevance_hash: "d1:a|b",
    params: { mode: "replace", chapter_id: "synthetic-flow", topic: "요청 때의 새 제목", role: "answer", claim_ids: ["claim"], instructions: "" },
    result: { status: "ok", diagram: changed, raw_text: "", unverified_numbers: [], format_retried: false, usage: emptyUsage(),
      base_etag: '"base"', sources_fingerprint: "sources" } });
  const server = newServer({ job });
  const dialog = await reopen(server);
  expect(within(dialog).getByLabelText("도식 제목")).toHaveValue("요청 때의 새 제목");
  await userEvent.click(within(dialog).getByRole("button", { name: "작성 폼에 불러오기" }));
  await within(dialog).findByText(/AI 후보의 항목과 관계를 작성 폼에 불러왔습니다/);
  expect(server.settles).toEqual([]);
  await userEvent.click(within(dialog).getByRole("button", { name: "입력과 배치 확인" }));
  const box = await within(dialog).findByRole("checkbox", { name: "이 변경을 확인했습니다" });
  const apply = within(dialog).getByRole("button", { name: "도식 적용" });
  expect(apply).toBeDisabled();
  await userEvent.click(box);
  await waitFor(() => expect(apply).toBeEnabled());
  await userEvent.click(apply);
  await waitFor(() => expect(server.changes).toHaveLength(1));
  await waitFor(() => expect(server.settles).toEqual([{ action: "applied" }]));  // 교체 도식은 저장 성공 뒤 처분한다
  expect(server.changes[0].body.acknowledged_loss_ids).toEqual(["loss-1"]);
  const slide = server.changes[0].body.candidate.slides.find((s) => s.chapter_id === "synthetic-flow")!;
  expect(slide.slots.template === "diagram" && slide.slots.diagram.nodes[0].content).toBe("AI 교체 후보 항목");
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
});
