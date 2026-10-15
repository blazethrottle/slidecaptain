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

type Server = { job: JobView; settleStatus: number; settles: { action: string }[]; puts: { ifMatch: string | null; deck: Deck }[] };

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
    if (url.endsWith("/deck")) return new Response(JSON.stringify(deck), { headers: { ETag: '"base"' } });
    if (url.endsWith("/sources")) return new Response("[]");
    if (url.endsWith("/snapshots") || url.endsWith("/drafts")) return new Response("[]");
    if (url === "/api/preset") return new Response(JSON.stringify(preset));
    if (url.endsWith("/render-plan")) return new Response(JSON.stringify(planFor(JSON.parse(init!.body as string))));
    if (url.endsWith("/story-plan/diagram")) return new Response(JSON.stringify(JSON.parse(init!.body as string).deck));
    if (url === "/api/status") return new Response(JSON.stringify({ provider: "chatgpt", model: "m", selection_id: "s",
      checked_at: "", login: { logged_in: true } }));
    if (url === "/api/jobs/active") return new Response(JSON.stringify({ active: null, ledger_available: true }));
    if (url.endsWith("/progress")) return new Response(JSON.stringify(defaultProgress()));
    if (url.endsWith("/jobs/job-d1/candidate")) {
      server.settles.push(JSON.parse(init!.body as string));
      if (server.settleStatus !== 200) {
        return new Response(JSON.stringify({ detail: "처분할 결과 후보가 없거나 이미 처분했습니다." }), { status: server.settleStatus });
      }
      server.job = { ...server.job, candidate_status: "applied" };
      return new Response(JSON.stringify(server.job));
    }
    if (url.endsWith("/jobs/job-d1")) return new Response(JSON.stringify(server.job));
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

const newServer = (over: Partial<Server> = {}): Server => ({ job: diagramJob(), settleStatus: 200, settles: [], puts: [], ...over });

beforeEach(() => { revokeConsent(); resetEtags(); });
afterEach(() => { vi.unstubAllGlobals(); });

// 회귀 RED: 지금 코드는 작성 창을 닫은 뒤 도착한 도식 후보를 앱 안에서 다시 열 길이 없다(SC-02)
it("복구 화면에서 도식 후보를 작성 창과 함께 열고, 여는 동안 처분하지 않는다", async () => {
  const server = newServer();
  const dialog = await reopen(server);
  expect(within(dialog).getByRole("region", { name: "AI 도식 후보 검토" })).toBeInTheDocument();
  expect(within(dialog).getByLabelText("도식 제목")).toHaveValue("다시 연 도식");
  expect(within(dialog).getByText(/입력을 고치면 이 후보를 버립니다/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "편집" })).toHaveAttribute("aria-current", "step");
  expect(server.settles).toEqual([]);
});

it("다시 연 후보를 불러와 확인하고 적용하면 처분이 applied이고 다음 자동 저장이 그 도식을 기준 저장본에 저장한다", async () => {
  const server = newServer();
  const dialog = await reopen(server);
  await userEvent.click(within(dialog).getByRole("button", { name: "작성 폼에 불러오기" }));
  expect(await within(dialog).findByText(/AI 후보의 항목과 관계를 작성 폼에 불러왔습니다/)).toBeInTheDocument();
  expect(server.settles).toEqual([{ action: "applied" }]);
  await userEvent.click(within(dialog).getByRole("button", { name: "입력과 배치 확인" }));
  const apply = within(dialog).getByRole("button", { name: "도식 적용" });
  await waitFor(() => expect(apply).toBeEnabled());
  await userEvent.click(apply);
  await waitFor(() => expect(server.puts).toHaveLength(1), { timeout: 4000 });
  expect(server.puts[0].ifMatch?.replace(/"/g, "")).toBe("base");
  expect(server.puts[0].deck.structure.chapters.map((c) => c.id)).toContain("new-diagram");
  const saved = server.puts[0].deck.slides.find((s) => s.chapter_id === "new-diagram")!;
  expect(saved.slots.template === "diagram" && saved.slots.diagram.nodes.map((n) => n.content))
    .toEqual(diagram!.nodes.map((n) => n.content));
});

it("다른 곳이 먼저 처분했으면(409) 불러오지 않고 알린다", async () => {
  const server = newServer({ settleStatus: 409 });
  const dialog = await reopen(server);
  await userEvent.click(within(dialog).getByRole("button", { name: "작성 폼에 불러오기" }));
  expect(await within(dialog).findByText(/다른 곳에서 이미 처리한 후보입니다/)).toBeInTheDocument();
  expect(within(dialog).queryByText(/AI 후보의 항목과 관계를 작성 폼에 불러왔습니다/)).not.toBeInTheDocument();
  expect(within(dialog).queryByRole("region", { name: "AI 도식 후보 검토" })).not.toBeInTheDocument();
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
  ["생성 도중 덱이 바뀐 후보", { candidate_status: "stale" as const, stale_reasons: ["deck_changed" as const] }, /만든 뒤 입력이 바뀐/],
  ["주장이 바뀐 후보", { stale_reasons: ["story_plan_changed" as const] }, /만든 뒤 입력이 바뀐/],
  ["자료가 바뀐 후보", { stale_reasons: ["sources_changed" as const] }, /만든 뒤 입력이 바뀐/],
  ["해시가 없는 옛 후보", { relevance_hash: null }, /이전 버전에서 만든 도식 후보/],
])("%s는 열 수 없고 이유를 보인다", async (_name, over, reason) => {
  await openRecovery(newServer({ job: diagramJob(over) }));
  expect(await screen.findByText(reason)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "도식 작성 창에서 열기" })).not.toBeInTheDocument();
});

it("다른 곳만 바뀐 후보(알림)는 열 수 있다", async () => {
  await openRecovery(newServer({ job: diagramJob({ stale_reasons: ["deck_changed_elsewhere"] }) }));
  expect(await screen.findByRole("button", { name: "도식 작성 창에서 열기" })).toBeInTheDocument();
});
