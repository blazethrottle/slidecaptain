// 복구 화면의 장 후보 비교와 반영 (C1 계획 W1-b, 2026-10-15). API 함수를 흉내 내지 않고 fetch만 바꿔 요청 계층의 ETag 캐시와
// ProjectView의 덱 상태를 실제로 지난다(계획 리뷰 PR-04, PR-15). 서버는 시험 안의 작은 상태 기계다: 덱과 ETag, 작업 목록,
// 미리 보기와 적용이 서로 맞물린다
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { revokeConsent } from "../api/aiGate";
import { resetEtags, type Deck, type JobView, type Slots } from "../api/client";
import { compareDialog, previewOf } from "../test/compare";
import { defaultProgress, planWith, preset, project } from "../test/fixtures";
import { batchView, chapterResult, chapterView, jobView } from "../test/jobs";
import { ProjectView } from "./ProjectView";

vi.mock("./AISettingsPanel", () => ({ AISettingsPanel: () => null }));
vi.mock("./NumericReviewPanel", () => ({ NumericReviewPanel: () => null }));

const bullets = (text: string): Slots => ({ template: "bullet_box", bullets: [{ text, level: 0 }], conclusion: text, footnote: "" });
const chapter = (id: string, topic: string) => ({ id, topic, conclusion: "", template: "bullet_box" as const, source_refs: [] });

function baseDeck(): Deck {
  return {
    schema_version: 1,
    meta: { title: "제목", report_type: "research", audience: "", presenter: "", preset_overrides: {} },
    structure: { chapters: [chapter("c1", "시장 현황"), chapter("c2", "원가 구조")] },
    slides: [{ chapter_id: "c1", eyebrow: "", subtitle: "", slots: bullets("지금 c1") }],
  };
}

type Server = {
  deck: Deck; etag: number; jobs: JobView[];
  applyStatus?: number; applyBody?: Record<string, unknown>; previewStatus?: number; previewBody?: Record<string, unknown>;
  applies: { url: string; ifMatch: string | null; body: Record<string, unknown> }[];
  puts: { ifMatch: string | null }[]; deckReads: number;
};

// 이전 묶음(job-old, 장별 해시 표지 b1:)의 c2 하위 장이 낡은 후보로 남고, 새 묶음(job-new)은 c1만 만들었다
function olderBatch(): JobView {
  return batchView([chapterView("c2", "failed", { candidate_status: "stale", result: chapterResult(bullets("이전 묶음 c2")) })],
    { id: "job-old", relevance_hash: "b1:{}", outcome: "partial", created_at: "2026-10-14T09:00:00+09:00" });
}
const newerBatch = () => batchView([chapterView("c1", "succeeded")], { id: "job-new", relevance_hash: "b1:{}" });

function serve(server: Server) {
  const fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const headers = new Headers(init?.headers);
    const tag = () => `"E${server.etag}"`;
    const ifMatch = () => headers.get("If-Match")?.replace(/"/g, "") ?? null;  // 서버는 따옴표를 떼고 비교한다
    if (url.endsWith("/deck") && init?.method === "PUT") {
      server.puts.push({ ifMatch: ifMatch() });
      server.deck = JSON.parse(init.body as string);
      server.etag += 1;
      return new Response(JSON.stringify({ ok: true }), { headers: { ETag: tag() } });
    }
    if (url.endsWith("/deck")) { server.deckReads += 1; return new Response(JSON.stringify(server.deck), { headers: { ETag: tag() } }); }
    if (url.endsWith("/sources")) return new Response("[]");
    if (url.endsWith("/snapshots") || url.endsWith("/drafts")) return new Response("[]");
    if (url === "/api/preset") return new Response(JSON.stringify(preset));
    if (url === "/api/render-plan") return new Response(JSON.stringify(planWith(["미리보기"])));
    if (url === "/api/jobs/active") return new Response(JSON.stringify({ active: null, ledger_available: true }));
    if (url.endsWith("/progress")) return new Response(JSON.stringify(defaultProgress()));
    if (url.includes("/apply/preview")) {
      if (server.previewStatus) return new Response(JSON.stringify(server.previewBody ?? {}), { status: server.previewStatus });
      const body = JSON.parse(init!.body as string);
      const job = url.split("/jobs/")[1].split("/")[0];
      const chapterId = body.chapter_id ?? server.jobs.find((j) => j.id === job)?.target ?? "c1";
      const current = server.deck.slides.find((s) => s.chapter_id === chapterId) ?? null;
      return new Response(JSON.stringify(previewOf(current, bullets(`후보 ${chapterId}`),
        { job_id: job, chapter_id: chapterId, base_etag: `E${server.etag}` })));
    }
    if (url.includes("/apply")) {
      const body = JSON.parse(init!.body as string);
      server.applies.push({ url, ifMatch: ifMatch(), body });
      if (server.applyStatus) return new Response(JSON.stringify(server.applyBody ?? {}), { status: server.applyStatus });
      if (ifMatch() !== `E${server.etag}`) {
        return new Response(JSON.stringify({ detail: "다른 창이나 프로그램에서 먼저 저장되었습니다. 최신 덱을 다시 읽어 주세요." }), { status: 412 });
      }
      const job = url.split("/jobs/")[1].split("/")[0];
      const row = server.jobs.find((j) => j.id === job)!;
      const chapterId = body.chapter_id ?? row.target!;
      const slide = { chapter_id: chapterId, eyebrow: "", subtitle: "", slots: bullets(`후보 ${chapterId}`) };
      server.deck = { ...server.deck, slides: [...server.deck.slides.filter((s) => s.chapter_id !== chapterId), slide] };
      server.etag += 1;
      // 반영한 후보는 처분이 applied라 목록에서 빠진다
      server.jobs = server.jobs.map((j) => j.id !== job ? j : j.kind === "chapters"
        ? { ...j, chapters: j.chapters.map((c) => c.chapter_id === chapterId ? { ...c, candidate_status: "applied" } : c) }
        : { ...j, candidate_status: "applied" });
      return new Response(JSON.stringify(server.deck), { headers: { ETag: tag() } });
    }
    if (url.endsWith("/jobs")) {
      const visible = server.jobs.filter((j) => j.candidate_status === "held" || j.candidate_status === "stale"
        || j.chapters.some((c) => c.candidate_status === "held" || c.candidate_status === "stale"));
      return new Response(JSON.stringify(visible));
    }
    throw new Error(`unexpected ${url}`);
  });
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

function newServer(jobs: JobView[], over: Partial<Server> = {}): Server {
  return { deck: baseDeck(), etag: 0, jobs, applies: [], puts: [], deckReads: 0, ...over };
}

async function openRecovery(server: Server) {
  serve(server);
  render(<ProjectView project={project} onBack={vi.fn()} />);
  await userEvent.click(await screen.findByRole("button", { name: "스냅샷 복구" }));
  return screen.findByRole("heading", { name: "AI 결과 후보" });
}

const candidateRow = (label: RegExp) => screen.getByText(label).closest("li") as HTMLElement;

async function applyFrom(row: HTMLElement) {
  await userEvent.click(within(row).getByRole("button", { name: "비교하고 반영" }));
  const dialog = await compareDialog();
  const apply = await within(dialog).findByRole("button", { name: "반영" });
  await waitFor(() => expect(apply).toBeEnabled());
  await userEvent.click(apply);
}

beforeEach(() => { revokeConsent(); resetEtags(); });
afterEach(() => { vi.unstubAllGlobals(); });

// 회귀 RED: 지금 코드는 복구 화면에 반영 입구가 없다(C1). 같은 장(c2)의 단독 다시 생성 후보를 함께 두어, 반영 뒤 덱 상태가
// 복구 화면에 들어왔는지를 그 행의 다시 생성 목적지로 관측한다(빈 장이던 c2에 슬라이드가 생기면 "편집 단계"로 바뀐다)
it("새 묶음 뒤에도 이전 묶음의 낡은 장 후보를 복구 화면에서 비교하고 반영한다", async () => {
  const single = jobView("chapter", { id: "job-single", target: "c2", relevance_hash: "c1:x", params: { chapter_id: "c2" },
    result: chapterResult(bullets("단독 c2")) });
  const server = newServer([newerBatch(), olderBatch(), single]);
  await openRecovery(server);
  const older = await waitFor(() => candidateRow(/장 내용 생성 \(2장 원가 구조\)/));
  const singleRow = candidateRow(/장 다시 생성 \(2장 원가 구조\)/);
  expect(within(singleRow).getByRole("button", { name: "구성 단계로 옮겨 다시 생성" })).toBeInTheDocument();
  await applyFrom(older);
  await waitFor(() => expect(screen.queryByText(/장 내용 생성 \(2장 원가 구조\)/)).not.toBeInTheDocument());
  expect(server.applies).toHaveLength(1);
  expect(server.applies[0].url).toContain("/jobs/job-old/apply");
  expect(server.applies[0].body.chapter_id).toBe("c2");
  expect(server.applies[0].ifMatch).toBe("E0");
  expect(within(candidateRow(/장 다시 생성 \(2장 원가 구조\)/)).getByRole("button", { name: "편집 단계로 옮겨 다시 생성" }))
    .toBeInTheDocument();
  // 반영으로 연 버튼이 사라지면 초점은 후보 목록 제목으로 간다 (계획 리뷰 PR-16)
  await waitFor(() => expect(screen.getByRole("heading", { name: "AI 결과 후보" })).toHaveFocus());
});

// 계약(ETag 캐시): 반영 응답의 ETag가 캐시에 들어가야 둘째 비교 화면이 "다른 곳에서 먼저 저장"으로 막히지 않는다
it("복구 화면 안에서 두 후보를 연달아 반영해도 둘째 비교 화면이 막히지 않는다", async () => {
  const c1 = jobView("chapter", { id: "job-c1", target: "c1", relevance_hash: "c1:x", params: { chapter_id: "c1" },
    result: chapterResult(bullets("단독 c1")) });
  const server = newServer([olderBatch(), c1]);
  await openRecovery(server);
  await applyFrom(await waitFor(() => candidateRow(/장 내용 생성 \(2장 원가 구조\)/)));
  await waitFor(() => expect(server.applies).toHaveLength(1));
  await applyFrom(await waitFor(() => candidateRow(/장 다시 생성 \(1장 시장 현황\)/)));
  await waitFor(() => expect(server.applies).toHaveLength(2));
  expect(server.applies[1].ifMatch).toBe("E1");
  expect(screen.queryByText(/이 화면이 연 뒤 다른 곳에서 먼저 저장했습니다/)).not.toBeInTheDocument();
});

// 계약(닫을 때 다시 읽기): 반영한 뒤 다른 탭이 덱을 다시 바꿨으면, 복구 화면을 닫고 간 단계는 서버의 새 덱을 그린다
it("반영 뒤 서버 덱이 다시 바뀐 상태에서 복구 화면을 닫으면 단계 화면은 서버 덱을 읽는다", async () => {
  // c1의 후보는 남겨 두어, 다시 연 복구 화면이 그 장 이름을 지금 덱으로 보이게 한다
  const c1 = jobView("chapter", { id: "job-c1", target: "c1", relevance_hash: "c1:x", params: { chapter_id: "c1" },
    result: chapterResult(bullets("단독 c1")) });
  const server = newServer([olderBatch(), c1]);
  await openRecovery(server);
  await applyFrom(await waitFor(() => candidateRow(/장 내용 생성 \(2장 원가 구조\)/)));
  await waitFor(() => expect(server.applies).toHaveLength(1));
  server.deck = { ...server.deck, structure: { ...server.deck.structure,
    chapters: [chapter("c1", "다른 탭이 바꾼 제목"), chapter("c2", "원가 구조")] } };
  server.etag += 1;
  const reads = server.deckReads;
  await userEvent.click(screen.getByRole("button", { name: "복구 화면 닫기" }));
  await waitFor(() => expect(server.deckReads).toBe(reads + 1));
  await userEvent.click(await screen.findByRole("button", { name: "스냅샷 복구" }));
  expect(await screen.findByText(/1장 다른 탭이 바꾼 제목/)).toBeInTheDocument();
});

it("반영이 412이면 충돌 안내, 5xx이면 확인하지 못함 안내와 그 행의 알림, 409 candidate_settled이면 목록을 다시 읽는다", async () => {
  const server = newServer([olderBatch()], { applyStatus: 412,
    applyBody: { detail: "다른 창이나 프로그램에서 먼저 저장되었습니다. 최신 덱을 다시 읽어 주세요." } });
  await openRecovery(server);
  await applyFrom(await waitFor(() => candidateRow(/장 내용 생성 \(2장 원가 구조\)/)));
  expect(await screen.findByText(/서버 내용 다시 읽기/)).toBeInTheDocument();

  server.applyStatus = 503; server.applyBody = { detail: "덱을 저장하지 못했습니다.", code: "deck_write_failed" };
  await applyFrom(candidateRow(/장 내용 생성 \(2장 원가 구조\)/));
  expect(await screen.findByText("반영 결과를 확인하지 못했습니다. 서버 내용을 다시 읽어 주세요.", { exact: false })).toBeInTheDocument();
  expect(within(candidateRow(/장 내용 생성 \(2장 원가 구조\)/)).getByText(/반영했을 수 있습니다/)).toBeInTheDocument();

  server.applyStatus = 409; server.applyBody = { detail: "이미 반영했거나 버린 후보입니다. 화면을 새로 고쳐 주세요.", code: "candidate_settled" };
  server.jobs = [];
  await applyFrom(candidateRow(/장 내용 생성 \(2장 원가 구조\)/));
  expect(await screen.findByText("다른 곳에서 이미 처리한 후보입니다. 목록을 다시 읽었습니다.")).toBeInTheDocument();
  expect(screen.queryByText(/화면을 새로 고쳐 주세요/)).not.toBeInTheDocument();
  expect(screen.getByText("남아 있는 AI 결과 후보가 없습니다.")).toBeInTheDocument();
});

it("미리 보기가 409이면 비교 화면을 닫고 안내한 뒤 목록을 다시 읽는다", async () => {
  const server = newServer([olderBatch()], { previewStatus: 409,
    previewBody: { detail: "이전 버전에서 만든 결과라 반영 여부를 판정할 수 없습니다.", code: "not_applicable" } });
  await openRecovery(server);
  await userEvent.click(within(await waitFor(() => candidateRow(/장 내용 생성 \(2장 원가 구조\)/)))
    .getByRole("button", { name: "비교하고 반영" }));
  expect(await screen.findByText("이전 버전에서 만든 결과라 반영 여부를 판정할 수 없습니다.")).toBeInTheDocument();
  expect(screen.queryByRole("dialog", { name: /새 내용과 비교/ })).not.toBeInTheDocument();
});

// 고정: 적용 라우트가 받지 않는 행과 다른 종류의 후보에는 반영 버튼이 없다(계획 리뷰 PR-06)
it("판정할 수 없는 장 후보와 장 후보가 아닌 행에는 비교하고 반영 버튼이 없다", async () => {
  const cancelled = jobView("chapter", { id: "job-cancelled", state: "cancelled", target: "c1", params: { chapter_id: "c1" },
    relevance_hash: "c1:x", result: chapterResult(bullets("취소 뒤 도착")) });
  const legacy = batchView([chapterView("c2", "failed", { candidate_status: "stale", result: chapterResult(bullets("옛 묶음")) })],
    { id: "job-legacy", relevance_hash: null });
  const structure = jobView("structure", { id: "job-structure", result: { structure: { chapters: [{ topic: "구조" }] } } });
  const server = newServer([cancelled, legacy, structure]);
  await openRecovery(server);
  await waitFor(() => candidateRow(/장 다시 생성 \(1장 시장 현황\)/));
  expect(screen.queryByRole("button", { name: "비교하고 반영" })).not.toBeInTheDocument();
  expect(screen.getAllByText(/반영 여부를 판정할 수 없습니다. 보기와 버리기만/)).toHaveLength(2);
});

it("덱을 열 수 없는 복구 대상 프로젝트에는 비교하고 반영 버튼이 없다", async () => {
  serve(newServer([olderBatch()]));
  render(<ProjectView project={{ ...project, status: "needs_recovery" }} onBack={vi.fn()} />);
  await screen.findByText(/장 내용 생성/);
  expect(screen.queryByRole("button", { name: "비교하고 반영" })).not.toBeInTheDocument();
});
