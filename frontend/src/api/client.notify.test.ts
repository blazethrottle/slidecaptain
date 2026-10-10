// 공통 알림 지점의 계약 시험 (개정판 D3a-3, 계획 4.5). 실제 request()를 거치도록 fetch만 흉내 낸다
import { api, followJob, onProjectEvent, resetEtags, type JobView, type ProjectEvent } from "./client";
import { deckWith } from "../test/fixtures";
import { batchView } from "../test/jobs";

let events: ProjectEvent[] = [];
let stop: () => void = () => {};
beforeEach(() => { resetEtags(); events = []; stop = onProjectEvent((e) => events.push(e)); });
afterEach(() => { stop(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

const ok = (body: unknown, etag?: string) => new Response(JSON.stringify(body),
  { status: 200, headers: etag ? { ETag: etag } : {} });

it("저장 성공(덱 PUT, 자료 저장, 업로드, 복원, 내보내기)을 그 프로젝트의 저장 알림으로 낸다", async () => {
  const fetchMock = vi.fn().mockImplementation(async () => ok({ ok: true }, '"e1"'));
  vi.stubGlobal("fetch", fetchMock);
  await api.putDeck("p1", deckWith(["하나"]), false);
  await api.writeSource("p1", "a.md", "본문");
  fetchMock.mockResolvedValueOnce(ok({ filename: "a.xlsx", chars: 1, sheets: 1, cells: 1, truncated: false, notes: [] }));
  await api.uploadSource("p1", new File(["x"], "a.xlsx"), false);
  fetchMock.mockResolvedValueOnce(ok(deckWith(["하나"]), '"e2"'));
  await api.restoreSnapshot("p1", "deck-1");
  fetchMock.mockResolvedValueOnce(ok({ path: "x.pptx", quality_path: "x.json", quality: null }));
  await api.exportDeck("p1");
  expect(events).toEqual(Array(5).fill({ kind: "saved", project: "p1" }));
});

it("저장하지 않는 POST(실측, 수치 검토)와 조회는 알리지 않는다", async () => {
  vi.stubGlobal("fetch", vi.fn().mockImplementation(async () => ok({ slides: [] })));
  await api.measure(deckWith(["하나"]), "p1");
  await api.reviewNumbers("p1", deckWith(["하나"]));
  await api.listJobs("p1");
  expect(events).toEqual([]);
});

it("실패한 저장은 알리지 않는다", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "충돌" }), { status: 412 })));
  await expect(api.putDeck("p1", deckWith(["하나"]), false)).rejects.toThrow();
  expect(events).toEqual([]);
});

it("작업 등록은 응답을 받은 뒤 작업 ID와 함께 알린다", async () => {
  let resolve!: (r: Response) => void;
  vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise<Response>((r) => { resolve = r; })));
  const pending = api.startChapters("p1", ["c1"], {}, "req-1");
  await Promise.resolve();
  expect(events).toEqual([]);  // 응답 전에는 알리지 않는다
  resolve(ok({ ...batchView([]), id: "job-9", state: "running" }));
  await pending;
  expect(events).toEqual([{ kind: "job_started", project: "p1", jobId: "job-9" }]);
});

it("작업 조회가 종결 상태를 보면 작업 종결을 알린다", async () => {
  const running = { ...batchView([]), id: "job-9", state: "running" } as JobView;
  const done = { ...running, state: "succeeded" } as JobView;
  const fetchJob = vi.fn().mockResolvedValueOnce(running).mockResolvedValueOnce(done);
  await followJob(fetchJob, () => {}, { intervalMs: 0 });
  expect(events).toEqual([{ kind: "job_ended", project: "p1", jobId: "job-9" }]);
});

it("듣는 쪽의 오류는 요청을 실패로 만들지 않는다", async () => {
  const off = onProjectEvent(() => { throw new Error("듣는 쪽 오류"); });
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(ok({ ok: true })));
  await expect(api.writeSource("p1", "a.md", "본문")).resolves.toEqual({ ok: true });
  off();
});
